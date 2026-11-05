"""Leverage-weighted rotation depth from CBBD play-by-play.

Every second of a game gets a weight for how much the outcome was still in doubt, from the
margin and the time left. Weighted minutes then feed the effective rotation,
(sum min)^2 / sum min^2, so garbage time fades out instead of being cut at a line,
and nobody is sorted into starters and bench.

  weight: leader's win probability p = Phi(lead / sd), sd = sqrt(16^2 * t_left/2400 + 3^2)
          (t_left = seconds left in regulation, or in the overtime period being played;
           the 3-point floor keeps the last possessions of a one-score game at full weight)
          w = 1 while p <= 0.95, 0 once p >= 0.999, linear in log-odds in between.
          e.g. up 10 with 2:00 left 0.71, up 15 with 5:00 left 0.57, up 20 with 12:00 left 0.69,
               up 20 with 5:00 left 0.00, up 30 with 15:00 left 0.14.

Sources: /plays/date (one call per date: score, clock and the ten players on the floor on every play).
A team-game whose on-floor data fails the checks (five on the floor, minutes adding up) is rebuilt
from /substitutions/game/{id} instead; if that fails too it is written with reliable = False.

Outputs (data/rotation/):
  player_games.csv  one row per player per team-game: raw and weighted minutes, closing-window minutes
  team_games.csv    one row per team-game: eff_raw, eff_lev, competitive share, closing group, checks
  teams_current.csv one row per team, pooled over every reliable D-I team-game so far
                    (pooling weighted minutes means close games count more than routs)

Usage: python jobs/rotation.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
       default: the day after the last date in team_games.csv through yesterday (ET)
       python jobs/rotation.py --from-json raw_dir/   offline: replay saved /plays/date JSON files
"""
import os, sys, json, math, time, argparse, datetime as dt, collections

import pandas as pd

OUT = 'data/rotation'
REG = 2400
SIGMA_GAME, SIGMA_FLOOR = 16.0, 3.0
P_FULL, P_ZERO = 0.95, 0.999
CLOSE_WINDOW = 480          # closing group: the 8:00 ending when the game was last live, weighted


# ----------------------------------------------------------------- weights
def logit(p): return math.log(p / (1 - p))
L_FULL, L_ZERO = logit(P_FULL), logit(P_ZERO)

def weight(lead, t_left):
    """how much a second at this lead and time left counts (0..1)"""
    lead = abs(lead)
    if lead == 0: return 1.0
    sd = math.sqrt(SIGMA_GAME ** 2 * max(t_left, 0) / REG + SIGMA_FLOOR ** 2)
    p = 0.5 * (1 + math.erf(lead / sd / math.sqrt(2)))
    p = min(p, 1 - 1e-12)
    return min(1.0, max(0.0, (L_ZERO - logit(p)) / (L_ZERO - L_FULL)))


# ----------------------------------------------------------------- clock
def period_start(p): return (p - 1) * 1200 if p <= 2 else REG + (p - 3) * 300
def period_len(p): return 1200 if p <= 2 else 300

def make_clock(plays):
    """seconds-elapsed function; detects whether secondsRemaining counts down the period or the game"""
    sr1 = [x['secondsRemaining'] for x in plays if x.get('period') == 1 and x.get('secondsRemaining') is not None]
    game_mode = bool(sr1) and max(sr1) > 1260
    def elapsed(p, sr):
        if game_mode and p <= 2: return REG - sr
        return period_start(p) + period_len(p) - sr
    return elapsed, game_mode

def t_left(t):
    """seconds left in regulation, or in the overtime period containing t"""
    if t < REG: return REG - t
    k = int((t - REG) // 300)
    return REG + (k + 1) * 300 - t


# ----------------------------------------------------------------- one game
def game_end(plays, elapsed):
    last = max(x['period'] for x in plays)
    return period_start(last) + period_len(last), last

def second_weights(plays, elapsed, end):
    """per-second weight array for the game, from the home margin path"""
    pts = sorted((elapsed(x['period'], x['secondsRemaining']), x['homeScore'] - x['awayScore']) for x in plays
                 if x.get('homeScore') is not None and x.get('awayScore') is not None)
    w, j, margin = [0.0] * end, 0, 0
    for s in range(end):
        while j < len(pts) and pts[j][0] <= s: margin = pts[j][1]; j += 1
        w[s] = weight(margin, t_left(s + 0.5))
    return w

def stints_from_floor(plays, elapsed, end, team):
    """[(athleteId, name, t0, t1, share)] from the on-floor list carried on each play.
    When the feed lists more than five for a stretch, each listed player gets 5/n of it,
    so a stray extra name can't inflate anyone's minutes."""
    seq = sorted(((elapsed(x['period'], x['secondsRemaining']), i, x) for i, x in enumerate(plays)), key=lambda z: (z[0], z[1]))
    out, five = [], 0
    for k, (t0, _, x) in enumerate(seq):
        t1 = seq[k + 1][0] if k + 1 < len(seq) else end
        if t1 <= t0: continue
        on = [(o['id'], o.get('name')) for o in (x.get('onFloor') or []) if o.get('team') == team and o.get('id') is not None]
        five += (t1 - t0) if len(on) == 5 else 0
        share = 5 / len(on) if len(on) > 5 else 1.0
        for aid, nm in on: out.append((aid, nm, t0, t1, share))
    return out, five

def stints_from_subs(subs, elapsed, team):
    out = []
    for s in subs:
        if s['team'] != team: continue
        a, b = s['subIn'], s['subOut']
        t0, t1 = elapsed(a['period'], a['secondsRemaining']), elapsed(b['period'], b['secondsRemaining'])
        if t1 > t0: out.append((s['athleteId'], s['athlete'], t0, t1, 1.0))
    return out

def close_window(w):
    """the 8:00 of regulation that ends at the last second the game was still live (w >= 0.5):
    the real closing stretch in a close game, the stretch before the bench cleared in a rout"""
    last = max((s for s in range(min(REG, len(w))) if w[s] >= 0.5), default=REG - 1) + 1
    return max(0, last - CLOSE_WINDOW), last

def credit(stints, w, end):
    """per-player raw seconds, weighted seconds, weighted seconds in the closing window"""
    cs = [0.0]
    for x in w: cs.append(cs[-1] + x)
    win0, win1 = close_window(w)
    raw, lev, close, h1, names = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter(), {}
    for aid, nm, t0, t1, f in stints:
        a, b = max(0, int(round(t0))), min(end, int(round(t1)))
        if b <= a: continue
        raw[aid] += f * (b - a); lev[aid] += f * (cs[b] - cs[a]); names[aid] = nm
        ca, cb = max(a, win0), min(b, win1)
        if cb > ca: close[aid] += f * (cs[cb] - cs[ca])
        if a < 1200: h1[aid] += f * (min(b, 1200) - a)
    return raw, lev, close, h1, names

def eff(vals):
    v = [x for x in vals if x > 0]; t = sum(v)
    return t * t / sum(x * x for x in v) if t else float('nan')

def team_game(plays, subs_fetch, team, opp, gid, date, elapsed, end, n_per, w):
    expect = 5 * end
    st, five = stints_from_floor(plays, elapsed, end, team)
    raw, lev, close, h1, names = credit(st, w, end)
    adds_up = abs(sum(raw.values()) - expect) <= 0.02 * expect
    ok = adds_up and five >= 0.95 * end
    source = 'onFloor'
    if not ok and subs_fetch is not None:
        subs = subs_fetch(gid)
        if subs:
            st2 = stints_from_subs(subs, elapsed, team)
            r2, l2, c2, h2, n2 = credit(st2, w, end)
            if abs(sum(r2.values()) - expect) <= 0.02 * expect:
                raw, lev, close, h1, names, ok, source = r2, l2, c2, h2, n2, True, 'substitutions'
    if not ok and adds_up and five >= 0.80 * end:     # a few stretches with six listed, already scaled to five
        ok, source = True, 'onFloor (scaled)'
    tot_raw, tot_lev, tot_close = sum(raw.values()), sum(lev.values()), sum(close.values())
    closing = [names[a] for a, _ in close.most_common(5)] if tot_close >= 5 * 60 else []
    players = [dict(gameId=gid, date=date, team=team, opponent=opp, athleteId=a, athlete=names[a],
                    min_raw=round(raw[a] / 60, 2), min_lev=round(lev[a] / 60, 2), min_close=round(close[a] / 60, 2))
               for a in raw]
    tg = dict(gameId=gid, date=date, team=team, opponent=opp, periods=n_per, source=source, reliable=ok,
              team_min_raw=round(tot_raw / 60, 1), team_min_lev=round(tot_lev / 60, 1),
              comp_share=round(tot_lev / tot_raw, 3) if tot_raw else None,
              eff_raw=round(eff(raw.values()), 2), eff_lev=round(eff(lev.values()), 2), eff_h1=round(eff(h1.values()), 2),
              players_used=sum(1 for v in raw.values() if v > 0),
              closing_group=' / '.join(closing), five_on_floor=round(five / end, 3))
    return tg, players

def process_game(gid, plays, subs_fetch=None):
    plays = [x for x in plays if x.get('period') is not None and x.get('secondsRemaining') is not None]
    if not plays: return [], []
    elapsed, _ = make_clock(plays)
    end, n_per = game_end(plays, elapsed)
    w = second_weights(plays, elapsed, end)
    teams = {}
    for x in plays:
        if x.get('team') and x.get('isHomeTeam') is not None:
            teams[x['team']] = (x['isHomeTeam'], x.get('opponent'), x.get('conference'), x.get('opponentConference'))
    date = str(plays[0].get('gameStartDate', ''))[:10]
    tgs, pls = [], []
    for team, (is_home, opp, conf, oconf) in teams.items():
        tg, pl = team_game(plays, subs_fetch, team, opp, gid, date, elapsed, end, n_per, w)
        tg.update(isHome=is_home, d1_game=bool(conf) and bool(oconf),
                  final_margin=(plays[-1]['homeScore'] - plays[-1]['awayScore']) * (1 if is_home else -1))
        tgs.append(tg); pls += pl
    return tgs, pls


# ----------------------------------------------------------------- pooling
def pool(team_games, player_games):
    ok = team_games[team_games.reliable & team_games.d1_game]
    pg = player_games.merge(ok[['gameId', 'team']], on=['gameId', 'team'])
    rows = []
    for team, g in pg.groupby('team'):
        per = g.groupby('athleteId').agg(athlete=('athlete', 'last'), raw=('min_raw', 'sum'), lev=('min_lev', 'sum'), close=('min_close', 'sum'))
        tg = ok[ok.team == team]
        top = per.sort_values('close', ascending=False).head(5)
        rows.append(dict(team=team, games=len(tg), eff_lev=round(eff(per.lev), 2), eff_raw=round(eff(per.raw), 2),
                         comp_share=round(per.lev.sum() / per.raw.sum(), 3), weighted_games=round(per.lev.sum() / 200, 2),
                         minutes_leader=per.loc[per.lev.idxmax(), 'athlete'],
                         closing_group=' / '.join(top.athlete) if top.close.sum() >= 5 else '',
                         last_date=tg.date.max()))
    return pd.DataFrame(rows).sort_values('eff_lev')


# ----------------------------------------------------------------- CBBD
def api():
    import requests
    hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
    def get(path, **p):
        for i in range(5):
            r = requests.get('https://api.collegebasketballdata.com' + path, headers=hdr, params=p, timeout=120)
            if r.status_code == 200: time.sleep(0.3); return r.json()
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
            r.raise_for_status()
        raise SystemExit(f'gave up on {path} {p}')
    return get

def by_game(plays):
    g = collections.defaultdict(list)
    for x in plays: g[x['gameId']].append(x)
    return g

def et_date(iso):
    t = pd.Timestamp(iso)
    t = t.tz_localize('UTC') if t.tzinfo is None else t
    return t.tz_convert('America/New_York').strftime('%Y-%m-%d')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--start'); ap.add_argument('--end'); ap.add_argument('--from-json')
    ap.add_argument('--save-raw', help='also write each /plays/date response here (for replay)')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    f_tg, f_pg = f'{OUT}/team_games.csv', f'{OUT}/player_games.csv'
    old_tg = pd.read_csv(f_tg) if os.path.exists(f_tg) else pd.DataFrame()
    old_pg = pd.read_csv(f_pg) if os.path.exists(f_pg) else pd.DataFrame()

    games = {}
    if a.from_json:
        for fn in sorted(os.listdir(a.from_json)):
            if fn.endswith('.json'): games.update(by_game(json.load(open(os.path.join(a.from_json, fn)))))
        subs_fetch = None
    else:
        get = api()
        yday = (pd.Timestamp.now(tz='America/New_York') - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        start = a.start or ((pd.Timestamp(old_tg.date.max()) + pd.Timedelta(days=1)).strftime('%Y-%m-%d') if len(old_tg) else yday)
        end = a.end or a.start or yday
        # the endpoint's day boundary doesn't line up with ET, so pull a day either side
        # and keep the games whose ET tip date falls in the range
        for d in pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=1), pd.Timestamp(end) + pd.Timedelta(days=1)):
            data = get('/plays/date', date=d.strftime('%Y-%m-%d'), utcOffset=-5)
            if a.save_raw:
                os.makedirs(a.save_raw, exist_ok=True); json.dump(data, open(f'{a.save_raw}/plays_{d:%Y-%m-%d}.json', 'w'))
            for gid, pl in by_game(data).items():
                if start <= et_date(pl[0]['gameStartDate']) <= end:
                    have = games.setdefault(gid, {})
                    for x in pl: have[x['id']] = x          # a game split across two responses is stitched back together
            print(f'{d:%Y-%m-%d}: {len(data)} plays')
        games = {gid: list(v.values()) for gid, v in games.items()}
        print(f'{len(games)} games tipping {start} to {end} (ET)')
        subs_cache = {}
        def subs_fetch(gid):
            if gid not in subs_cache: subs_cache[gid] = get(f'/substitutions/game/{gid}')
            return subs_cache[gid]

    new_tg, new_pg = [], []
    for gid, plays in games.items():
        tgs, pls = process_game(gid, plays, subs_fetch)
        for t in tgs: t['date'] = et_date(plays[0]['gameStartDate'])
        for p in pls: p['date'] = tgs[0]['date'] if tgs else p['date']
        new_tg += tgs; new_pg += pls
    new_tg, new_pg = pd.DataFrame(new_tg), pd.DataFrame(new_pg)
    if not len(new_tg): print('no games'); return
    keep = lambda old: old[~old.gameId.isin(new_tg.gameId)] if len(old) else old
    tg = pd.concat([keep(old_tg), new_tg], ignore_index=True).sort_values(['date', 'gameId', 'team'])
    pg = pd.concat([keep(old_pg), new_pg], ignore_index=True).sort_values(['date', 'gameId', 'team', 'min_lev'], ascending=[True, True, True, False])
    tg.to_csv(f_tg, index=False); pg.to_csv(f_pg, index=False)
    teams = pool(tg, pg); teams.to_csv(f'{OUT}/teams_current.csv', index=False)

    n = new_tg; d1 = n[n.d1_game]
    print(f'{len(n)} team-games ({len(d1)} D-I vs D-I): reliable {int(n.reliable.sum())}, '
          f"from onFloor {int((n.source == 'onFloor').sum())}, from substitutions {int((n.source == 'substitutions').sum())}")
    bad = n[~n.reliable]
    if len(bad): print('unreliable:', ', '.join(f'{r.team} ({r.team_min_raw} min, five-on-floor {r.five_on_floor})' for r in bad.itertuples()))
    print(f'{len(teams)} teams pooled -> {OUT}/teams_current.csv')

if __name__ == '__main__':
    main()
