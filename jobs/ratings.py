"""In-season ratings: preseason prior blended with an in-season box-score composite (production recipe, locked Oct 16).
  in-season  = per-pillar ridge SRS (ridge 0.5, home term) on D-I vs D-I games, pillars clipped at +/-3 game SD:
               net 2PT% .32, net OREB rate .26, net TO rate .24, net 3PT% .10, net FTA rate .08; z-scored over teams with games,
               composite re-z'd.
  blend      = lam*z_in + (1-lam)*z_prior, lam = N/(N+K(d)), N = D-I games played,
               K(d) = 8 through Nov 30, ramps linearly to 12 between Dec 1 and Jan 15, 12 after.
               Not re-standardized (Nov 3 decision): a team with no D-I games stays exactly at its prior; the monthly
               spread-scale refit against closing lines absorbs any change in overall spread.
Early games (option 2b, Nov 3): teams with <3 D-I games move by lam x their four-factor surprise vs the priors' expectation
               instead of the SRS read (which splits a single game evenly around average); SRS blend from game 3.
Games come from CollegeBasketballData (/games/teams). Uses games played before the as-of date (ET).
Writes data/games_2026-27.csv, data/ratings/ratings_<date>.csv and data/ratings_current.csv.
Usage: python jobs/ratings.py [--date YYYY-MM-DD]   (date = the card date; default today ET)"""
import os, sys, json, time, argparse, collections, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, requests
ET = ZoneInfo('America/New_York')
ap = argparse.ArgumentParser(); ap.add_argument('--date'); a = ap.parse_args()
asof = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
SEASON, START = 2027, dt.date(2026, 10, 30)
BASE = 'https://api.collegebasketballdata.com'
W = {'net2pt': .32, 'netreb': .26, 'netto': .24, 'net3pt': .10, 'netfta': .08}; PILLARS = list(W)
RIDGE = 0.5

def K_of(d):
    d = dt.date.fromisoformat(d); k = 8 + 4 * (d - dt.date(2026, 12, 1)).days / 45
    return float(min(max(k, 8), 12))

def get(path, **params):
    hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
    for i in range(5):
        r = requests.get(BASE + path, headers=hdr, params=params, timeout=60)
        if r.status_code == 200: time.sleep(0.3); return r.json()
        if r.status_code == 401: raise SystemExit('CBBD 401 Unauthorized - check the CBBD_API_KEY secret')
        if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
        r.raise_for_status()
    raise SystemExit(f'CBBD gave up on {path} {params}')

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

# ---- prior + names
P = pd.read_csv('data/prior_2026-27.csv'); teams = list(P.team); tix = {t: i for i, t in enumerate(teams)}
zp = P.z_prior.to_numpy(float); n = len(teams)
XB = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
G, unmapped = [], set()
if len(TG):
    TG = TG[(TG.date < asof) & TG.pts.notna() & TG.opp_pts.notna()]
    for gid, x in TG.groupby('gameId'):
        r = x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]
        tm, op = XB.get(r.team) or (r.team if r.team in tix else None), XB.get(r.opp) or (r.opp if r.opp in tix else None)
        if tm not in tix or op not in tix:
            for nm, k in ((r.team, tm), (r.opp, op)):
                if k not in tix: unmapped.add(nm)
            continue
        v = [r[c] for c in ('p2m', 'p2a', 'opp_p2m', 'opp_p2a', 'p3m', 'p3a', 'opp_p3m', 'opp_p3a', 'orb', 'drb', 'opp_orb', 'opp_drb',
                            'fta', 'fga', 'opp_fta', 'opp_fga', 'to', 'poss', 'opp_to', 'opp_poss')]
        if any(pd.isna(z) for z in v) or 0 in (v[1], v[3], v[5], v[7], v[13], v[15], v[17], v[19]): continue
        p2m, p2a, o2m, o2a, p3m, p3a, o3m, o3a, orb, drb, oorb, odrb, fta, fga, ofta, ofga, to, poss, oto, oposs = map(float, v)
        G.append(dict(date=r.date, t=tix[tm], o=tix[op], home=not bool(r.neutral), margin=float(r.pts - r.opp_pts),
                      net2pt=p2m / p2a - o2m / o2a, net3pt=p3m / p3a - o3m / o3a, netreb=orb / (orb + odrb) - oorb / (oorb + drb),
                      netfta=fta / fga - ofta / ofga, netto=oto / oposs - to / poss))
print(f'D-I vs D-I games used: {len(G)}' + (f"; names not in the KenPom list (non-D-I or crosswalk gap): {', '.join(sorted(map(str, unmapped)))}" if unmapped else ''))

# ---- in-season composite
N = np.zeros(n)
for x in G: N[x['t']] += 1; N[x['o']] += 1
mask = N > 0
def srs(p, sd):
    A = np.zeros((len(G), n + 1)); y = np.zeros(len(G))
    for i, x in enumerate(G):
        A[i, x['t']] = 1; A[i, x['o']] = -1; A[i, n] = 1.0 if x['home'] else 0.0
        y[i] = float(np.clip(x[p], -3 * sd, 3 * sd))
    reg = np.eye(n + 1) * RIDGE; reg[n, n] = 0
    return np.linalg.solve(A.T @ A + reg, A.T @ y)[:n]
def zs(v):
    out = np.zeros(n)
    if mask.sum() > 2: m, s = v[mask].mean(), v[mask].std(); out[mask] = (v[mask] - m) / (s if s > 0 else 1)
    return out
if len(G) >= 2:
    comp = sum(W[p] * zs(srs(p, np.std([x[p] for x in G]) or 1.0)) for p in PILLARS); z_in = zs(comp)
else:
    z_in = np.zeros(n)
K = K_of(asof); lam = N / (N + K)
zb = lam * z_in + (1 - lam) * zp
# ---- option 2b (Nov 3): teams with fewer than EARLY_N D-I games update from expectation, not from zero.
# Each game is scored on the same four-factor composite (pillars clipped at +/-3 game SD and divided by it, standing weights).
# Fit composite = a*home + b*(z_prior_t - z_prior_o) across all games; a team's surprise in a game = residual / b (rating SDs),
# averaged over its games; rating = z_prior + lam * surprise. At EARLY_N games the team hands off to the tested SRS blend above.
EARLY_N = 3
method = np.where(N >= EARLY_N, 'srs', np.where(N > 0, 'early', 'prior'))
surprise = np.full(n, np.nan); fit = ''
if len(G) >= 20:
    SDG = {p: (np.std([x[p] for x in G]) or 1.0) for p in PILLARS}
    c = np.array([sum(W[p] * float(np.clip(x[p], -3 * SDG[p], 3 * SDG[p])) / SDG[p] for p in PILLARS) for x in G])
    gap = np.array([zp[x['t']] - zp[x['o']] for x in G]); hm = np.array([1.0 if x['home'] else 0.0 for x in G])
    X = np.column_stack([hm, gap]); (a_h, b), *_ = np.linalg.lstsq(X, c, rcond=None)
    res = (c - X @ np.array([a_h, b])) / b
    acc = collections.defaultdict(list)
    for x, r in zip(G, res): acc[x['t']].append(r); acc[x['o']].append(-r)
    for i, v in acc.items(): surprise[i] = np.mean(v)
    early = method == 'early'
    zb = np.where(early, zp + lam * np.nan_to_num(surprise), zb)
    r2 = 1 - np.var(c - X @ np.array([a_h, b])) / np.var(c)
    fit = f'early-game fit on {len(G)} games: composite = {a_h:.3f}*home + {b:.3f}*prior gap (z), R^2 {r2:.2f}'
    print(fit)
R = pd.DataFrame(dict(team=teams, n_games=N.astype(int), K=K, lam=lam.round(3), prior_wt=(1 - lam).round(3),
                      z_prior=zp.round(4), z_inseason=np.where(mask, z_in, np.nan).round(4), surprise=np.round(surprise, 4),
                      method=method, z_blend=zb.round(4), move_pts=((zb - zp) * 9.5).round(2), asof=asof))
R.to_csv(f'data/ratings/ratings_{asof}.csv', index=False); R.to_csv('data/ratings_current.csv', index=False)
print(f'ratings as of {asof}: K={K:.1f}, {int(mask.sum())} teams with games; prior weight min {R.prior_wt.min():.2f}')
mv = R[R.n_games > 0].reindex(R[R.n_games > 0].move_pts.abs().sort_values(ascending=False).index).head(10)
print('largest moves vs prior (pts on the 9.5 scale):'); print(mv[['team', 'n_games', 'prior_wt', 'move_pts']].to_string(index=False))
