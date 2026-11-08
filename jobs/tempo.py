"""Possession-level tempo tracker from CBBD play-by-play — the TIS successor, built live from game one.

The old TIS profiles took every possession in a game at face value: a walk-up with the bench in,
up 22 with six minutes left, counted the same as a possession in a two-point game. This job keeps
every possession but tags it, so the profile can be built from the possessions that carry tempo
information and the rest can be dropped or down-weighted.

Each possession gets:
  start_type   how it began: made_fg, made_ft, dreb, steal (live-ball turnover), dead_to, oob_reb (missed shot out of
               bounds, team rebound), ft_miss, oreb (after a lost thread), period_start, unknown
  end_type     how it ended: made_fg, miss, to, ft, period_end
  dur          seconds, from start to end (overtime, period boundaries handled)
  margin       the possessing team's lead at the start, and t_left in regulation / the OT period
  lev          leverage weight at the start (rotation.py's win-probability weight; 1 = fully live,
               0 = decided), so garbage time fades instead of being cut at a line
  flags        ot (period 3+), half_end (ended at a period buzzer), short_clock (started with
               under 35 s left in the period), foul_seq (leading team, last 2:00 of regulation,
               fouled within 8 s: an intentional-foul possession, not a tempo choice)

Profiles (teams_current.csv) pool each team's D-I possessions two ways: raw (everything) and
competitive (lev-weighted, structural flags dropped). The legacy TIS composite is computed from
both so the rank correlation raw-vs-competitive is on screen every day — the gate that decides
whether the competitive profile is doing anything the z-score can't absorb. Also: offensive
possession length by start type, by game state (ahead / behind / within four in the second half),
and the length distribution (share under 10 s, 10-20, 20-30, 30+).

Sources: /plays/date (one call per date), then /plays/game/{id} for D-I games on those dates that
the date feed left out (it returned about 55% of games last season; the gap fill is capped per run).
Possession counts are checked against the box-score possessions in data/games_2026-27.csv.

Outputs (data/tempo/):
  possessions_<YYYY-MM>.csv.gz  one row per possession
  team_games.csv                one row per team-game: possession counts (parsed vs box), APL raw/comp
  ../pbp/game_factors.csv       one row per team-game: four-factor totals raw / competitive (jobs/pbp_factors.py)
  teams_current.csv             one row per team (KenPom spelling), pooled over D-I games so far

Usage: python jobs/tempo.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--gap-fill N]
       default: the last date in team_games.csv through yesterday (ET); gap fill 300
       python jobs/tempo.py --from-json raw_dir/   offline: replay saved /plays/date JSON files
"""
import os, sys, json, math, argparse, collections

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rotation import weight, make_clock, period_start, period_len, t_left, by_game, et_date, REG


def game_factors(*a):
    from pbp_factors import game_factors as gf
    return gf(*a)

def write_factors(rows):
    from pbp_factors import write
    return write(rows)


def api():
    """CBBD getter: long timeout and retries on timeouts, returns None if a call can't be completed
    (the big opening-week /plays/date responses time out now and then; the per-game fallback covers them)"""
    import time, requests
    hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
    def get(path, **p):
        for i in range(5):
            try:
                r = requests.get('https://api.collegebasketballdata.com' + path, headers=hdr, params=p, timeout=300)
            except requests.RequestException as e:
                print(f'  {path} {p}: {type(e).__name__}, retry {i + 1}', flush=True); time.sleep(5 * (i + 1)); continue
            if r.status_code == 200: time.sleep(0.3); return r.json()
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
            print(f'  {path} {p}: HTTP {r.status_code}', flush=True); return None
        print(f'  gave up on {path} {p}', flush=True); return None
    return get

OUT = 'data/tempo'
GAMES = 'data/games_2026-27.csv'
XWALK = 'data/xwalk_cbbd_kp.json'
MAX_DUR = 45            # a possession can't run longer than this; longer = clock/parse gap, dropped
SHORT_CLOCK = 35        # started with fewer seconds than this left in the period
FOUL_WINDOW = 120       # last 2:00 of regulation
FOUL_QUICK = 8          # fouled within this many seconds of the start
MIN_GAMES_Z = 1         # teams with at least this many D-I games enter the cross-sectional z-scores
DIAG = collections.Counter()   # --diag: what preceded each 'unknown' possession change
DIAG_EX = {}
QUIET = ('substitution', 'timeout', 'tvtimeout')


# ----------------------------------------------------------------- play classification
def kind(x):
    """one of: fga, ft, oreb, dreb, steal, to, other — from playType with playText as backup"""
    t = (x.get('playType') or '').lower().replace(' ', '')
    txt = (x.get('playText') or '').lower()
    if 'freethrow' in t or 'free throw' in txt: return 'ft'
    if 'offensiverebound' in t: return 'oreb'
    if 'defensiverebound' in t: return 'dreb'
    if 'deadball' in t: return 'dbreb'                    # team rebound, ball out of bounds (or between free throws)
    if 'technical' in t: return 'tech'
    if 'steal' in t: return 'steal'
    if 'turnover' in t: return 'to'
    if 'block' in t: return 'other'                       # credited to the defense; the miss follows as its own play
    if any(k in t for k in ('jumpshot', 'layup', 'dunk', 'tipshot', 'tip')): return 'fga'
    if 'shot' in t and 'block' not in t: return 'fga'
    return 'other'

def missed(x):
    txt = (x.get('playText') or '').lower()
    if 'missed' in txt or 'miss' in txt.split(): return True
    if 'made' in txt or 'good' in txt: return False
    return x.get('scoringPlay') is False

def final_ft(x):
    import re
    m = re.search(r'(\d+)\s*of\s*(\d+)', x.get('playText') or '', re.I)
    return int(m.group(1)) == int(m.group(2)) if m else True


# ----------------------------------------------------------------- one game -> possessions
def parse_game(gid, plays):
    plays = [x for x in plays if x.get('period') is not None and x.get('secondsRemaining') is not None]
    if not plays: return [], {}
    elapsed, _ = make_clock(plays)
    # within one clock second the feed lists plays newest-first (FT 2 of 2 before 1 of 2, a putback before its rebound);
    # play ids run in game order, so sort on (clock, id)
    def pid(x, i):
        try: return int(x.get('id'))
        except (TypeError, ValueError): return i
    seq = sorted(((elapsed(x['period'], x['secondsRemaining']), pid(x, i), x) for i, x in enumerate(plays)), key=lambda z: (z[0], z[1]))

    home = away = None
    for x in plays:
        if x.get('team') and x.get('isHomeTeam') is not None:
            if x['isHomeTeam']: home = home or x['team']
            else: away = away or x['team']
            if home is None and x.get('opponent') and not x['isHomeTeam']: home = x['opponent']
            if away is None and x.get('opponent') and x['isHomeTeam']: away = x['opponent']
    if not home or not away: return [], {}
    conf = {x['team']: (x.get('conference'), x.get('opponentConference')) for x in plays if x.get('team')}
    d1 = all(bool(c[0]) and bool(c[1]) for c in conf.values() if c) if conf else False
    opp = lambda t: away if t == home else home

    rows = []
    hist = collections.deque(maxlen=4)   # recent non-substitution plays, for --diag
    def note(tag, x):
        rel = lambda y: (y.get('playType') or '?') + ('' if not y.get('team') else ('/same' if y.get('team') == x.get('team') else '/other'))
        prev = list(hist)[:-1]                   # hist already holds x itself
        key = (tag, ' > '.join(rel(y) for y in prev), x.get('playType'))
        DIAG[key] += 1
        DIAG_EX.setdefault(key, ' | '.join((y.get('playText') or '')[:60] for y in prev + [x]))
    cur = None                       # dict(team, t0, period, start_type, margin, t_left, lev)
    pending_start = ('period_start', None)   # how the NEXT possession began
    hs = as_ = 0
    last_steal = {}                  # team -> time of its last steal (quick-shot detection)
    last_miss = None                 # (team, t) of the last missed FGA still waiting on a rebound
    last_tech = -99                  # time of the last technical foul (its free throws don't change possession)

    def margin_for(team, h, a): return (h - a) if team == home else (a - h)

    def start(team, t, period, how, h, a):
        nonlocal cur
        if how == 'period_start': t = period_start(period)   # the feed has no tip/half-start event; clock it from the period start
        tl = t_left(t)
        cur = dict(team=team, t0=t, period=period, start_type=how, margin=margin_for(team, h, a), t_left=tl,
                   lev=weight(h - a, tl), p_left=period_start(period) + period_len(period) - t)

    def end(t, how, period):
        nonlocal cur
        if cur is None: return
        dur = t - cur['t0']
        if 0 < dur <= MAX_DUR and cur['period'] == period:
            rows.append(dict(gameId=gid, team=cur['team'], opp=opp(cur['team']), isHome=cur['team'] == home, d1_game=d1,
                             period=period, t0=round(cur['t0'], 1), dur=round(dur, 1), start_type=cur['start_type'], end_type=how,
                             margin=cur['margin'], t_left=round(cur['t_left']), lev=round(cur['lev'], 3),
                             ot=period > 2, half_end=how == 'period_end', short_clock=cur['p_left'] < SHORT_CLOCK,
                             foul_seq=(how == 'ft' and period == 2 and cur['t_left'] <= FOUL_WINDOW and 0 < cur['margin'] <= 10
                                       and dur <= FOUL_QUICK)))
        cur = None

    prev_period = None
    for t, _, x in seq:
        period = int(x['period'])
        if prev_period is not None and period != prev_period:
            end(period_start(prev_period) + period_len(prev_period), 'period_end', prev_period)
            pending_start = ('period_start', None)
        prev_period = period
        if x.get('homeScore') is not None: hs, as_ = x['homeScore'], x['awayScore']
        team = x.get('team')
        k = kind(x)
        if not any(q in (x.get('playType') or '').lower().replace(' ', '') for q in QUIET): hist.append(x)
        if k == 'tech': last_tech = t; continue
        if k == 'other' or team not in (home, away): continue
        if k == 'dbreb':
            if cur and team != cur['team'] and (last_miss is not None or 'ft_end' in cur):
                fe = cur.pop('ft_end', None)          # missed shot (or last FT) out of bounds: the other team inbounds
                end(fe if fe is not None else t, 'ft' if fe is not None else 'miss', period)
                start(team, t, period, 'oob_reb', hs, as_)
            elif cur and team == cur['team']:
                cur.pop('ft_end', None)               # kept by the shooting team: same possession
            last_miss = None
            continue
        if k == 'ft' and t - last_tech <= 2: continue  # technical free throws

        if cur is None and k in ('fga', 'ft', 'oreb', 'to', 'steal'):
            # we lost the thread (or period just started): open a possession for whoever is acting
            who = opp(team) if k == 'steal' else team
            how = pending_start[0] if pending_start[1] in (None, who) else 'unknown'
            if how == 'unknown': note('open', x)
            start(who, t, period, how, hs, as_)

        if k == 'fga':
            if cur and cur['team'] != team:          # other team shoots without a change recorded
                if 'ft_end' in cur:                   # missed last FT, rebound not logged: the shooter's possession ended at the line
                    end(cur.pop('ft_end'), 'ft', period); start(team, t, period, 'ft_miss', hs, as_)
                else:
                    note('fga_other', x); end(t, 'unknown', period); start(team, t, period, 'unknown', hs, as_)
            if missed(x):
                last_miss = (team, t)
                continue                              # the rebound decides what happens next
            end(t, 'made_fg', period); last_miss = None
            pending_start = ('made_fg', opp(team)); start(opp(team), t, period, 'made_fg', hs, as_)
        elif k == 'ft':
            if cur and cur['team'] != team:
                if cur['start_type'] == 'made_fg' and t - cur['t0'] <= 5 and '1 of 1' in (x.get('playText') or ''):
                    # and-1: the shooter's free throw after his own make; the other team's possession already began
                    if final_ft(x) and missed(x): cur['and1_miss'] = True
                    continue
                note('ft_other', x); end(t, 'unknown', period); start(team, t, period, 'unknown', hs, as_)
            if final_ft(x):
                if not missed(x):
                    end(t, 'ft', period)
                    pending_start = ('made_ft', opp(team)); start(opp(team), t, period, 'made_ft', hs, as_)
                else:
                    cur['ft_end'] = t                  # missed last free throw: the rebound decides (OREB = same possession)
                    pending_start = ('ft_miss', None)
        elif k == 'oreb':
            last_miss = None
            if cur is None or cur['team'] != team:      # lost thread
                if cur: end(cur.pop('ft_end', t), 'miss', period)
                start(team, t, period, 'oreb', hs, as_)
            else:
                cur.pop('ft_end', None)                 # same team keeps the ball (incl. after its missed FT): one possession
        elif k == 'dreb':
            last_miss = None
            if cur and cur['team'] == opp(team):
                fe = cur.pop('ft_end', None); end(fe if fe is not None else t, 'ft' if fe is not None else 'miss', period)
            elif cur and cur.pop('and1_miss', False):
                cur['start_type'] = 'dreb'; continue    # defense rebounds a missed and-1: its possession already began
            elif cur: note('dreb_own', x); end(t, 'unknown', period)
            start(team, t, period, 'dreb', hs, as_)
        elif k == 'steal':
            # the paired Turnover play may already have opened this possession as dead_to at the same clock
            if cur and cur['team'] == team and cur['start_type'] == 'dead_to' and cur['t0'] == t:
                cur['start_type'] = 'steal'; last_steal[team] = t; continue
            end(t, 'to', period); start(team, t, period, 'steal', hs, as_); last_steal[team] = t
        elif k == 'to':
            if cur and cur['start_type'] == 'steal' and cur['t0'] == t:
                continue                              # the Steal play already recorded this change of possession
            if cur and cur['team'] != team:
                note('to_other', x); end(t, 'unknown', period); start(team, t, period, 'unknown', hs, as_)
            end(t, 'to', period); start(opp(team), t, period, 'dead_to', hs, as_)

    if prev_period is not None: end(period_start(prev_period) + period_len(prev_period), 'period_end', prev_period)
    meta = dict(home=home, away=away, d1_game=d1, final=(hs, as_), periods=prev_period or 2)
    return rows, meta


# ----------------------------------------------------------------- pooling
def wmean(v, w):
    w = w.where(v.notna(), 0); s = w.sum()
    return (v * w).sum() / s if s > 0 else float('nan')

def z(s):
    v = s.astype(float); sd = v.std()
    return (v - v.mean()) / sd if sd and sd > 0 else v * 0

def legacy_tis(t, off, dfn, nst, qg, qa):
    """the 2025-26 composite on whichever inputs are passed: FIS 0.65(-zOff)+0.35 burst, SIS 0.60 zDef+0.40 zNST"""
    zo, zd, zn = z(t[off]), z(t[dfn]), z(t[nst])
    burst = z(t[qg]) - z(t[qa])
    fis, sis = z(0.65 * (-zo) + 0.35 * burst), z(0.60 * zd + 0.40 * zn)
    return fis, sis, fis - sis, pd.concat([fis, sis], axis=1).max(axis=1).clip(lower=0)

def pool(poss, team_games, xwalk):
    p = poss[poss.d1_game].copy()
    if not len(p): return pd.DataFrame()
    comp = p[~(p.ot | p.half_end | p.short_clock | p.foul_seq)].copy()
    rows = []
    for team in sorted(p.team.unique()):
        o, d = p[p.team == team], p[p.opp == team]
        oc, dc = comp[comp.team == team], comp[comp.opp == team]
        games = team_games[(team_games.team == team) & team_games.d1_game].gameId.nunique()
        r = dict(team=xwalk.get(team, team), cbbd=team, games=games,
                 poss_off=len(o), poss_off_comp=round(oc.lev.sum(), 1), comp_share=round(oc.lev.sum() / len(o), 3) if len(o) else None,
                 off_apl_raw=o.dur.mean(), off_apl_comp=wmean(oc.dur, oc.lev),
                 def_apl_raw=d.dur.mean(), def_apl_comp=wmean(dc.dur, dc.lev))
        # by start type (competitive, offense)
        for st in ('dreb', 'steal', 'made_fg', 'made_ft', 'dead_to'):
            s = oc[oc.start_type == st]; r[f'off_apl_{st}'] = wmean(s.dur, s.lev)
        # defense: how long the opponent takes after each kind of start
        for st in ('dreb', 'made_fg'):
            s = dc[dc.start_type == st]; r[f'def_apl_{st}'] = wmean(s.dur, s.lev)
        # second-half game state (offense, competitive)
        h2 = oc[oc.period == 2]
        for name, m in (('ahead5', h2.margin >= 5), ('behind5', h2.margin <= -5), ('within4', h2.margin.abs() <= 4)):
            s = h2[m]; r[f'off_apl_h2_{name}'] = wmean(s.dur, s.lev); r[f'n_h2_{name}'] = int(m.sum())
        # length distribution (offense, competitive, lev-weighted shares)
        tot = oc.lev.sum()
        for lo, hi, nm in ((0, 10, 'u10'), (10, 20, '10_20'), (20, 30, '20_30'), (30, 99, '30p')):
            r[f'share_{nm}'] = round(oc[(oc.dur >= lo) & (oc.dur < hi)].lev.sum() / tot, 3) if tot else None
        # the old TIS inputs, raw and competitive
        for tag, oo, dd in (('raw', o, d), ('comp', oc, dc)):
            w_o = oo.lev if tag == 'comp' else pd.Series(1.0, index=oo.index)
            w_d = dd.lev if tag == 'comp' else pd.Series(1.0, index=dd.index)
            n_o, n_d = w_o.sum(), w_d.sum()
            # quick shots: possession started with a steal, made FG within 10 s
            qo = oo[(oo.start_type == 'steal') & (oo.end_type == 'made_fg') & (oo.dur <= 10)]
            qd = dd[(dd.start_type == 'steal') & (dd.end_type == 'made_fg') & (dd.dur <= 10)]
            r[f'quick_gen_{tag}'] = 100 * w_o[qo.index].sum() / n_o if n_o else None
            r[f'quick_allowed_{tag}'] = 100 * w_d[qd.index].sum() / n_d if n_d else None
        rows.append(r)
    t = pd.DataFrame(rows)
    # dead-ball turnovers forced per 100 defensive possessions (opponent possession ended in a non-steal turnover)
    for tag, src in (('raw', p), ('comp', comp)):
        w = src.lev if tag == 'comp' else pd.Series(1.0, index=src.index)
        dto = src[src.end_type == 'to']
        # a possession ending 'to' whose successor started 'dead_to' is a dead-ball turnover; successor 'steal' is live
        nxt = src.sort_values(['gameId', 't0']).groupby('gameId').start_type.shift(-1)
        dead = dto[nxt.reindex(dto.index) == 'dead_to']
        forced = (w[dead.index].groupby(dead.opp).sum()).rename('f')
        tot = w.groupby(src.opp).sum().rename('n')
        t[f'nst_forced_{tag}'] = t.cbbd.map((100 * forced / tot).fillna(0)).round(2)
    z_ok = t.games >= MIN_GAMES_Z
    for tag in ('raw', 'comp'):
        sub = t[z_ok]
        fis, sis, net, dom = legacy_tis(sub, f'off_apl_{tag}', f'def_apl_{tag}', f'nst_forced_{tag}', f'quick_gen_{tag}', f'quick_allowed_{tag}')
        t.loc[z_ok, f'FIS_{tag}'], t.loc[z_ok, f'SIS_{tag}'] = fis.round(3), sis.round(3)
        t.loc[z_ok, f'NetTIS_{tag}'], t.loc[z_ok, f'StrengthDom_{tag}'] = net.round(3), dom.round(3)
    for c in t.columns:
        if t[c].dtype == float and not c.startswith(('share', 'comp_share')): t[c] = t[c].round(2)
    return t.sort_values('NetTIS_comp', ascending=False)


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--start'); ap.add_argument('--end'); ap.add_argument('--from-json')
    ap.add_argument('--gap-fill', type=int, default=300, help='max /plays/game calls for D-I games the date feed skipped')
    ap.add_argument('--save-raw')
    ap.add_argument('--diag', action='store_true', help='print what precedes unknown possession changes; write nothing')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    f_tg = f'{OUT}/team_games.csv'
    old_tg = pd.read_csv(f_tg) if os.path.exists(f_tg) else pd.DataFrame()
    xwalk = {k: v.strip() for k, v in json.load(open(XWALK)).items()} if os.path.exists(XWALK) else {}
    box = pd.read_csv(GAMES) if os.path.exists(GAMES) else pd.DataFrame()

    games = {}
    if a.from_json:
        for fn in sorted(os.listdir(a.from_json)):
            if fn.endswith('.json'): games.update(by_game(json.load(open(os.path.join(a.from_json, fn)))))
        start = end = None
    else:
        get = api()
        yday = (pd.Timestamp.now(tz='America/New_York') - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        start = a.start or (min(old_tg.date.max(), yday) if len(old_tg) else '2026-11-01')   # re-pull the last stored day
        end = a.end or a.start or yday
        if start > end: print(f'nothing to do: {start} > {end}'); return
        failed_dates = []
        for d in pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=1), pd.Timestamp(end) + pd.Timedelta(days=1)):
            data = get('/plays/date', date=d.strftime('%Y-%m-%d'), utcOffset=-5)
            if data is None:
                failed_dates.append(d.strftime('%Y-%m-%d')); continue
            if a.save_raw:
                os.makedirs(a.save_raw, exist_ok=True); json.dump(data, open(f'{a.save_raw}/plays_{d:%Y-%m-%d}.json', 'w'))
            for gid, pl in by_game(data).items():
                if start <= et_date(pl[0]['gameStartDate']) <= end:
                    have = games.setdefault(gid, {})
                    for x in pl: have[x['id']] = x
            print(f'{d:%Y-%m-%d}: {len(data)} plays', flush=True)
        games = {gid: list(v.values()) for gid, v in games.items()}
        if failed_dates: print(f'date feed failed for {failed_dates}; those days come from /plays/game', flush=True)
        # gap fill: games in the box-score store on these dates that the date feed left out (or failed on)
        if len(box) and a.gap_fill:
            want = box[(box.date >= start) & (box.date <= end) & box.isHome].gameId.astype(int).unique().tolist()
            missing = [g for g in want if g not in games]
            fetched = 0
            for g in missing[:a.gap_fill]:
                pl = get(f'/plays/game/{g}')
                if pl:
                    games[g] = pl; fetched += 1
            print(f'{len(games)} games tipping {start} to {end} (ET); gap fill fetched {fetched} of {len(missing)} missing'
                  + (f' (capped at {a.gap_fill})' if len(missing) > a.gap_fill else ''), flush=True)

    box_date = dict(zip(box.gameId.astype(int), box.date)) if len(box) else {}
    poss_all, tg_rows, unknown = [], [], collections.Counter()
    fac_rows, fac_err = [], collections.Counter()   # four-factor totals for the garbage-time-free ratings (jobs/pbp_factors.py)
    for gid, plays in games.items():
        rows, meta = parse_game(gid, plays)
        if not rows: continue
        gsd = plays[0].get('gameStartDate')
        date = et_date(gsd) if gsd else box_date.get(int(gid))
        if not date: continue
        for r in rows: r['date'] = date
        poss_all += rows
        try:
            for f in game_factors(gid, plays, rows, meta): f['date'] = date; fac_rows.append(f)
        except Exception as e:                      # never let the factor pass break the tempo outputs
            fac_err[type(e).__name__] += 1
        pr = pd.DataFrame(rows)
        for team in (meta['home'], meta['away']):
            o = pr[pr.team == team]; oc = o[~(o.ot | o.half_end | o.short_clock | o.foul_seq)]
            tg_rows.append(dict(gameId=gid, date=date, team=team, opponent=meta['home'] if team == meta['away'] else meta['away'],
                                isHome=team == meta['home'], d1_game=meta['d1_game'], periods=meta['periods'],
                                poss_parsed=len(o), poss_unknown=int((o.start_type == 'unknown').sum()),
                                off_apl_raw=round(o.dur.mean(), 2), off_apl_comp=round(wmean(oc.dur, oc.lev), 2),
                                comp_share=round(oc.lev.sum() / len(o), 3) if len(o) else None,
                                final_margin=(meta['final'][0] - meta['final'][1]) * (1 if team == meta['home'] else -1)))
        for x in plays:
            if kind(x) == 'other': unknown[x.get('playType')] += 1
    if not poss_all: print('no games'); return
    if a.diag:
        n = sum(DIAG.values()); print(f'\n{n} unknown possession changes across {len(games)} games; top patterns '
                                       f'(tag | previous plays, same/other = team vs the triggering play | trigger):')
        for (tag, prev, trig), c in DIAG.most_common(30):
            print(f'{c:5d} {c / n:6.1%}  {tag:9s} | {prev} | {trig}\n         e.g. {DIAG_EX[(tag, prev, trig)]}')
        chk = pd.DataFrame(tg_rows)
        if len(box):
            chk = chk.merge(box[['gameId', 'team', 'poss']], on=['gameId', 'team'], how='left')
            print(f'\nparsed - box possessions: mean {(chk.poss_parsed - chk.poss).mean():+.2f}, |diff| {(chk.poss_parsed - chk.poss).abs().mean():.2f}')
        return

    poss = pd.DataFrame(poss_all)
    for ym, grp in poss.groupby(poss.date.str[:7]):
        fp = f'{OUT}/possessions_{ym}.csv.gz'
        old = pd.read_csv(fp) if os.path.exists(fp) else pd.DataFrame()
        if len(old): old = old[~old.gameId.isin(grp.gameId)]
        pd.concat([old, grp], ignore_index=True).sort_values(['date', 'gameId', 't0']).to_csv(fp, index=False, compression={'method': 'gzip', 'mtime': 0})
    new_tg = pd.DataFrame(tg_rows)
    if len(box):
        b = box[['gameId', 'team', 'poss']].rename(columns={'poss': 'poss_box'})
        new_tg = new_tg.merge(b, on=['gameId', 'team'], how='left')
        new_tg['poss_diff'] = new_tg.poss_parsed - new_tg.poss_box
    tg = pd.concat([old_tg[~old_tg.gameId.isin(new_tg.gameId)] if len(old_tg) else old_tg, new_tg], ignore_index=True)
    tg = tg.sort_values(['date', 'gameId', 'team']); tg.to_csv(f_tg, index=False)
    try:
        nf = write_factors(fac_rows)
        print(f'four-factor totals: {nf} team-games -> data/pbp/game_factors.csv' + (f'; failed on {dict(fac_err)}' if fac_err else ''))
    except Exception as e:
        print(f'four-factor totals not written: {type(e).__name__}: {e}')

    # profiles from the whole store
    store = pd.concat([pd.read_csv(f'{OUT}/{f}') for f in sorted(os.listdir(OUT)) if f.startswith('possessions_')], ignore_index=True)
    teams = pool(store, tg, xwalk)
    teams.to_csv(f'{OUT}/teams_current.csv', index=False)

    # report
    d1 = new_tg[new_tg.d1_game]
    print(f'{len(new_tg)} team-games parsed ({len(d1)} D-I vs D-I), {len(poss)} possessions')
    if 'poss_box' in new_tg and new_tg.poss_box.notna().any():
        chk = new_tg.dropna(subset=['poss_box'])
        print(f'possessions vs box score: mean diff {chk.poss_diff.mean():+.1f}, mean |diff| {chk.poss_diff.abs().mean():.1f}, '
              f'within 3: {(chk.poss_diff.abs() <= 3).mean():.0%} (n={len(chk)})')
    print(f'unknown-start possessions: {new_tg.poss_unknown.sum()} of {new_tg.poss_parsed.sum()} ({new_tg.poss_unknown.sum() / max(new_tg.poss_parsed.sum(), 1):.1%})')
    print(f'competitive share of possessions (lev-weighted): {d1.comp_share.mean():.3f}')
    if unknown: print('play types treated as non-possession events:', dict(unknown.most_common(12)))
    if len(teams):
        ok = teams[teams.games >= 3]
        rc = ok.NetTIS_raw.rank().corr(ok.NetTIS_comp.rank()) if len(ok) > 10 else float('nan')
        print(f'{len(teams)} teams pooled -> {OUT}/teams_current.csv; NetTIS rank corr raw vs competitive '
              f'(teams with 3+ games, n={len(ok)}): {rc:.3f}  [>0.90 absorbed by z-score, <0.80 reshuffling]')

if __name__ == '__main__':
    main()
