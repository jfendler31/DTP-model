"""Four-factor team totals from CBBD play-by-play, raw and competitive — the input for garbage-time-free ratings.

Called from jobs/tempo.py for every game it parses (same fetch, same possessions, same leverage), so
"garbage time" means one thing everywhere. Writes nothing on its own; tempo.py merges the rows into
data/pbp/game_factors.csv.

Every counted event is tied to a possession from tempo.parse_game:
  field goals (2PT/3PT, made/att), free throws  -> the shooting team's possession at that moment
                                                   (an and-1 or late FT goes to that team's possession that just ended)
  rebounds, player and team (dead-ball)          -> the possession of the team that missed
  turnovers                                      -> the losing team's possession (Turnover play; an unpaired Steal counts too)
and takes that possession's weight. Events no possession covers (possessions over 45 s or across a
period are dropped by the parser) take the leverage at the play itself.

Three versions per team-game:
  raw  every event and possession counts 1 (should match the box score; checked downstream)
  cw   competitive, weighted: possession lev (0-1), with tempo's structural drops except overtime
       (half_end, short_clock, foul_seq possessions count 0; OT kept at its leverage — Jon, Nov 8)
  cc   competitive, cutoff: possession counts 1 if lev >= 0.5 and not structurally dropped, else 0

Columns per version v: poss_v, p2m_v, p2a_v, p3m_v, p3a_v, ftm_v, fta_v, orb_v, drb_v (player rebounds),
orbt_v, drbt_v (team / dead-ball rebounds), to_v. Plus n_orphan (events with no possession).
"""
import os, re, bisect, collections

import pandas as pd

from rotation import weight, make_clock, t_left
from tempo import kind, missed, final_ft

OUT = 'data/pbp/game_factors.csv'
VERSIONS = ('raw', 'cw', 'cc')
STATS = ('poss', 'p2m', 'p2a', 'p3m', 'p3a', 'ftm', 'fta', 'orb', 'drb', 'orbt', 'drbt', 'to')
CUT = 0.5               # cc: possessions at or above this leverage count
SLACK = 0.6             # seconds of clock slack when matching a play to a possession window
FT_BACK = 12            # an FT may follow its team's possession end by this much (and-1, foul after the make)
REB_BACK = 3            # a rebound (esp. dead-ball, after a missed last FT) may trail the possession end by this much


def is_three(x):
    si = x.get('shotInfo') or {}
    rng = (si.get('range') or '').lower() if isinstance(si, dict) else ''
    if rng: return 'three' in rng
    txt = (x.get('playText') or '').lower()
    if re.search(r'three point|3-pt|3pt|three-point', txt): return True
    return bool(x.get('scoringPlay')) and x.get('scoreValue') == 3


def shot_made(x):
    si = x.get('shotInfo') or {}
    if isinstance(si, dict) and si.get('made') is not None: return bool(si['made'])
    return not missed(x)


def team_reb(x, team):
    """a rebound credited to the team, not a player (2024-25 feed style)"""
    return not x.get('participants') and (x.get('playText') or '').strip().lower().startswith(str(team or '').lower() + ' ')


def structural(r):
    # tempo also drops overtime; for the ratings OT is competitive play and stays in (Jon, Nov 8)
    return bool(r['half_end'] or r['short_clock'] or r['foul_seq'])


def game_factors(gid, plays, rows, meta):
    """rows/meta: tempo.parse_game output for this game. Returns one dict per team (two), or [] if unusable."""
    plays = [x for x in plays if x.get('period') is not None and x.get('secondsRemaining') is not None]
    if not plays or not rows: return []
    home, away = meta['home'], meta['away']
    opp = lambda t: away if t == home else home
    elapsed, _ = make_clock(plays)
    def pid(x, i):
        try: return int(x.get('id'))
        except (TypeError, ValueError): return i
    seq = sorted(((elapsed(x['period'], x['secondsRemaining']), pid(x, i), x) for i, x in enumerate(plays)), key=lambda z: (z[0], z[1]))

    # possession windows per team, and their weights in each version
    win = collections.defaultdict(list)        # team -> [(t0, t1, wt dict)]
    tot = {t: collections.Counter() for t in (home, away)}
    for r in rows:
        if r['team'] not in tot: continue
        s = structural(r)
        wt = {'raw': 1.0, 'cw': 0.0 if s else float(r['lev']), 'cc': 0.0 if s or r['lev'] < CUT else 1.0}
        win[r['team']].append((r['t0'], r['t0'] + r['dur'], wt))
        for v in VERSIONS: tot[r['team']][f'poss_{v}'] += wt[v]
    for t in win: win[t].sort(key=lambda z: z[0])
    starts = {t: [w[0] for w in win[t]] for t in win}

    def find(team, t, back=0):
        """the team's possession covering clock time t (latest start wins); FTs and rebounds may fall just after it ends"""
        ws = win.get(team, [])
        j = bisect.bisect_right(starts.get(team, []), t + SLACK) - 1
        if j >= 0:
            t0, t1, wt = ws[j]
            if t <= t1 + SLACK: return wt
            if back and t - t1 <= back: return wt
        return None

    orphans = 0
    def add(team, t, stat, hs, as_, period, back=0, owner=None):
        """credit `stat` to `team`, weighted by the possession of `owner` (default: team itself)"""
        nonlocal orphans
        wt = find(owner or team, t, back)
        if wt is None:
            orphans += 1
            lv = weight(hs - as_, t_left(t))
            wt = {'raw': 1.0, 'cw': lv, 'cc': 1.0 if lv >= CUT else 0.0}
        for v in VERSIONS: tot[team][f'{stat}_{v}'] += wt[v]

    hs = as_ = 0
    last_miss = None            # team whose missed shot / missed last FT is waiting on a rebound
    last_tech = -99
    to_seen = []                # (team, t) of Turnover plays, to pair with Steals
    steals = []
    for t, _, x in seq:
        period = int(x['period'])
        if x.get('homeScore') is not None: hs, as_ = x['homeScore'], x['awayScore']
        team = x.get('team')
        k = kind(x)
        if k == 'tech': last_tech = t; continue
        if team not in (home, away): continue
        if k == 'fga':
            three, made = is_three(x), shot_made(x)
            p = 'p3' if three else 'p2'
            add(team, t, p + 'a', hs, as_, period)
            if made: add(team, t, p + 'm', hs, as_, period); last_miss = None
            else: last_miss = team
        elif k == 'ft':
            add(team, t, 'fta', hs, as_, period, back=FT_BACK)
            ok = not missed(x)
            if ok: add(team, t, 'ftm', hs, as_, period, back=FT_BACK)
            if t - last_tech > 2:
                # a miss that drew the foul has no rebound; only a missed last FT leaves one pending
                last_miss = (None if ok else team) if final_ft(x) else None
        elif k in ('oreb', 'dreb') and team_reb(x, team):
            # 2024-25 feed: team rebounds come as "<Team> Offensive/Defensive Rebound." with no player (later seasons
            # log them as Deadball Team Rebound). Box scores leave team rebounds out, so treat them like dbreb.
            if last_miss is None: continue          # between free throws
            add(team, t, 'orbt' if team == last_miss else 'drbt', hs, as_, period, back=REB_BACK, owner=last_miss)
            last_miss = None
        elif k in ('oreb', 'dreb'):
            shooter = team if k == 'oreb' else opp(team)       # rebound rides on the missing team's possession
            add(team, t, 'orb' if k == 'oreb' else 'drb', hs, as_, period, back=REB_BACK, owner=shooter)
            last_miss = None
        elif k == 'dbreb':
            if last_miss is None: continue          # between free throws, or nothing to rebound
            add(team, t, 'orbt' if team == last_miss else 'drbt', hs, as_, period, back=REB_BACK, owner=last_miss)
            last_miss = None
        elif k == 'to':
            add(team, t, 'to', hs, as_, period); to_seen.append((team, t)); last_miss = None
        elif k == 'steal':
            steals.append((opp(team), t, hs, as_, period)); last_miss = None
    for loser, t, h, a_, period in steals:      # a Steal with no Turnover play by the other team at that clock
        if not any(tm == loser and abs(tt - t) <= 1.5 for tm, tt in to_seen):
            add(loser, t, 'to', h, a_, period)

    out = []
    for team in (home, away):
        r = dict(gameId=gid, team=team, opponent=opp(team), isHome=team == home, d1_game=meta['d1_game'], n_orphan=orphans)
        for v in VERSIONS:
            for s in STATS: r[f'{s}_{v}'] = round(tot[team][f'{s}_{v}'], 3)
        out.append(r)
    return out


def write(rows, path=OUT):
    """merge new team-game rows into the store (a re-parsed game replaces its old rows)"""
    if not rows: return 0
    new = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()
    if len(old): old = old[~old.gameId.isin(new.gameId)]
    allr = pd.concat([old, new], ignore_index=True).sort_values(['date', 'gameId', 'team'])
    allr.to_csv(path, index=False)
    return len(new)
