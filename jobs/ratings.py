"""In-season ratings: preseason prior blended with an in-season four-factor composite (production recipe, locked Oct 16).
  in-season  = per-pillar ridge SRS (ridge 0.5, home term) on D-I vs D-I games, pillars clipped at +/-3 game SD:
               net 2PT% .32, net OREB rate .26, net TO rate .24, net 3PT% .10, net FTA rate .08; z-scored over teams with games,
               composite re-z'd.
  blend      = lam*z_in + (1-lam)*z_prior, lam = N/(N+K(d)), N = D-I games played,
               K(d) = 8 through Nov 30, ramps linearly to 12 between Dec 1 and Jan 15, 12 after.
               Not re-standardized (Nov 3 decision): a team with no D-I games stays exactly at its prior.
Early games (option 2b, Nov 3): teams with <3 D-I games move by lam x their four-factor surprise vs the priors' expectation
               instead of the SRS read (which splits a single game evenly around average); SRS blend from game 3.
               Nov 11 (Jon): each game is judged against the opponent's CURRENT rating (leave-one-out for early-method
               opponents), not its preseason prior, so beating/losing to a team that has since risen or fallen is scored
               against what that team now looks like (OPP_CURRENT in ratings_core.py; max effect 0.6 pts on Nov 11).
Garbage time out (Jon, Nov 8): the pillars come from play-by-play competitive totals (data/pbp/game_factors.csv, version
               FACTOR_SRC = 'cw': every possession weighted by its leverage; end-of-half heaves, possessions starting under
               35 s in a period and late intentional-foul possessions dropped; overtime kept). A game with no play-by-play,
               or whose raw play-by-play doesn't match its box score, uses its CBBD box totals; counts are printed.
               GAME_WT: each game counts in proportion to its competitive possessions (mean weight 1), in the SRS and the
               games-1-2 fit/averaging, so a blowout's short competitive stretch weighs less than a full close game.
Games come from CollegeBasketballData (/games/teams). Uses games played before the as-of date (ET). Math: jobs/ratings_core.py.
Writes data/games_2026-27.csv, data/ratings/ratings_<date>.csv and data/ratings_current.csv.
Usage: python jobs/ratings.py [--date YYYY-MM-DD]   (date = the card date; default today ET)
       --games-only   pull and write data/games_2026-27.csv, then stop (the card job runs the play-by-play pass next)
       --offline      skip the CBBD pull and use the stored data/games_2026-27.csv"""
import os, sys, json, time, argparse, collections, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratings_core import build_games, rate, frame, load_factors
ET = ZoneInfo('America/New_York')
ap = argparse.ArgumentParser(); ap.add_argument('--date'); ap.add_argument('--games-only', action='store_true'); ap.add_argument('--offline', action='store_true')
ap.add_argument('--src', default=None, help="override FACTOR_SRC ('box' or 'cw') for a test run")
a = ap.parse_args()
asof = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
SEASON, START = 2027, dt.date(2026, 10, 30)
BASE = 'https://api.collegebasketballdata.com'
FACTOR_SRC = a.src or 'cw'      # 'box' = production through Nov 8
GAME_WT = True           # each game counted by its competitive possessions (Jon, Nov 8: stopping effect in blowouts)
FACTORS = 'data/pbp/game_factors.csv'

def get(path, **params):
    hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
    for i in range(5):
        r = requests.get(BASE + path, headers=hdr, params=params, timeout=60)
        if r.status_code == 200: time.sleep(0.3); return r.json()
        if r.status_code == 401: raise SystemExit('CBBD 401 Unauthorized - check the CBBD_API_KEY secret')
        if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
        r.raise_for_status()
    raise SystemExit(f'CBBD gave up on {path} {params}')

if a.offline:
    TG = pd.read_csv('data/games_2026-27.csv'); os.makedirs('data/ratings', exist_ok=True)
    print(f'offline: {len(TG)} stored team-game rows')
else:
    # ---- pull team-game box scores in 10-day windows
    end = dt.date.fromisoformat(asof) + dt.timedelta(days=1)
    rows, seen, d = [], set(), START
    while d < end:
        e = min(d + dt.timedelta(days=10), end)
        for r in get('/games/teams', season=SEASON, startDateRange=d.isoformat(), endDateRange=e.isoformat()):
            k = (r.get('gameId'), r.get('teamId'))
            if k in seen: continue
            seen.add(k); rows.append(r)
        d = e
    def g(x, *ks):
        for k in ks: x = x.get(k) if isinstance(x, dict) else None
        return x
    def side(s):
        return dict(pts=g(s, 'points', 'total'), poss=g(s, 'possessions'), p2m=g(s, 'twoPointFieldGoals', 'made'), p2a=g(s, 'twoPointFieldGoals', 'attempted'),
                    p3m=g(s, 'threePointFieldGoals', 'made'), p3a=g(s, 'threePointFieldGoals', 'attempted'), fta=g(s, 'freeThrows', 'attempted'),
                    fga=g(s, 'fieldGoals', 'attempted'), orb=g(s, 'rebounds', 'offensive'), drb=g(s, 'rebounds', 'defensive'), to=g(s, 'turnovers', 'total'))
    TG = []
    for r in rows:
        t = dt.datetime.fromisoformat(str(r.get('startDate')).replace('Z', '+00:00')).astimezone(ET)
        rec = dict(gameId=r.get('gameId'), date=t.strftime('%Y-%m-%d'), seasonType=r.get('seasonType'), team=r.get('team'), opp=r.get('opponent'),
                   isHome=r.get('isHome'), neutral=r.get('neutralSite'))
        rec.update(side(r.get('teamStats'))); rec.update({'opp_' + k: v for k, v in side(r.get('opponentStats')).items()})
        TG.append(rec)
    TG = pd.DataFrame(TG)
    os.makedirs('data/ratings', exist_ok=True)
    TG.to_csv('data/games_2026-27.csv', index=False)
    print(f'CBBD: {len(TG)} team-game rows, {TG.gameId.nunique() if len(TG) else 0} games through {asof}')
if a.games_only: sys.exit(0)

# ---- prior + names
P = pd.read_csv('data/prior_2026-27.csv'); teams = list(P.team); tix = {t: i for i, t in enumerate(teams)}
zp = P.z_prior.to_numpy(float); n = len(teams)
XB = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
XB.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})   # KenPom renamed; crosswalk still has the old spelling
G, unmapped, srcs = [], set(), collections.Counter()
if len(TG):
    TG = TG[(TG.date < asof) & TG.pts.notna() & TG.opp_pts.notna()]
    G, unmapped = build_games(TG, tix, XB, load_factors(FACTORS) if FACTOR_SRC != 'box' else {}, FACTOR_SRC, srcs)
print(f'D-I vs D-I games used: {len(G)}' + (f"; names not in the KenPom list (non-D-I or crosswalk gap): {', '.join(sorted(map(str, unmapped)))}" if unmapped else ''))
print(f'pillar source ({FACTOR_SRC}{", game-weighted" if GAME_WT else ""}): ' + ', '.join(f'{k} {v}' for k, v in srcs.most_common()))
out = rate(G, n, zp, asof, game_wt=GAME_WT)
if out['fit']: print(f"early-game fit on {len(G)} games: {out['fit']}")
R = frame(teams, zp, out, asof)
R.to_csv(f'data/ratings/ratings_{asof}.csv', index=False); R.to_csv('data/ratings_current.csv', index=False)
print(f"ratings as of {asof}: K={out['K']:.1f}, {int((out['N'] > 0).sum())} teams with games; prior weight min {R.prior_wt.min():.2f}")
mv = R[R.n_games > 0].reindex(R[R.n_games > 0].move_pts.abs().sort_values(ascending=False).index).head(10)
print('largest moves vs prior (pts on the 9.5 scale):'); print(mv[['team', 'n_games', 'prior_wt', 'move_pts']].to_string(index=False))
