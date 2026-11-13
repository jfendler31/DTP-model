"""Should the noisy pillars (net 3PT%, net FTA rate) be opponent-adjusted this early? (Jon, Nov 13, 2026 — ULM's +15.6 adjusted 3PT pillar)

rate_v() is a line-for-line copy of ratings_core.rate() with per-pillar options. Production is untouched. Every date, the 'base'
variant is asserted equal to production rate() (max |diff| < 1e-9) — if the copy drifts, the script stops.

Variants (only the in-season pillar ratings change; early method for games 1-2, K, weights, blend are production):
  base          production (ridge 0.5 on every pillar, opponent/home-adjusted)
  raw3          net3pt pillar = team's possession-weighted mean of its game values (no opponent/home adjustment)
  raw3fta       net3pt and netfta raw
  ridge3_2/_5   ridge 2 / 5 on net3pt only
  ridge3fta_2/_5  ridge 2 / 5 on net3pt and netfta
  drop3         net3pt weight 0
  ridgeall_1/_2 ridge 1 / 2 on every pillar
  rawall        no opponent adjustment on any pillar (reference)
Walk-forward, Nov-Dec, seasons with a backtest store. Output preds_<S>.csv; grade with evaluate_pillars.py.
Usage: python3 data/research/pillar_adj/backtest_pillars.py --season 2026"""
import os, sys, json, argparse, collections, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, 'jobs')
import ratings_core as rc
from ratings_core import build_games, rate, load_factors, W, PILLARS, RIDGE, EARLY_N, K_of

OUT = 'data/research/pillar_adj'
VAR = {
    'base': {},
    'raw3': dict(raw={'net3pt'}),
    'raw3fta': dict(raw={'net3pt', 'netfta'}),
    'ridge3_2': dict(ridge={'net3pt': 2}),
    'ridge3_5': dict(ridge={'net3pt': 5}),
    'ridge3fta_2': dict(ridge={'net3pt': 2, 'netfta': 2}),
    'ridge3fta_5': dict(ridge={'net3pt': 5, 'netfta': 5}),
    'drop3': dict(w={'net3pt': 0.0}),
    'ridgeall_1': dict(ridge={p: 1 for p in PILLARS}),
    'ridgeall_2': dict(ridge={p: 2 for p in PILLARS}),
    'rawall': dict(raw=set(PILLARS)),
}


def rate_v(G, n, zp, asof, cfg):
    """copy of ratings_core.rate(game_wt=True) with cfg: raw (set of pillars), ridge ({pillar: value}), w ({pillar: weight})"""
    raw, ridge, wov = cfg.get('raw', set()), cfg.get('ridge', {}), cfg.get('w', {})
    N = np.zeros(n)
    for x in G: N[x['t']] += 1; N[x['o']] += 1
    mask = N > 0
    w = np.array([x['n_poss'] for x in G], float)
    w = w / w.mean()
    sw = np.sqrt(w)
    def srs(p, sd):
        A = np.zeros((len(G), n + 1)); y = np.zeros(len(G))
        for i, x in enumerate(G):
            A[i, x['t']] = 1; A[i, x['o']] = -1; A[i, n] = 1.0 if x['home'] else 0.0
            y[i] = float(np.clip(x[p], -3 * sd, 3 * sd))
        if p in raw:                         # no opponent/home adjustment: weighted mean of the team's own game values
            num = np.zeros(n); den = np.zeros(n)
            for i, x in enumerate(G):
                num[x['t']] += w[i] * y[i]; den[x['t']] += w[i]; num[x['o']] -= w[i] * y[i]; den[x['o']] += w[i]
            return np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
        A, y = A * sw[:, None], y * sw
        reg = np.eye(n + 1) * ridge.get(p, RIDGE); reg[n, n] = 0
        return np.linalg.solve(A.T @ A + reg, A.T @ y)[:n]
    def zs(v):
        out = np.zeros(n)
        if mask.sum() > 2: m, s = v[mask].mean(), v[mask].std(); out[mask] = (v[mask] - m) / (s if s > 0 else 1)
        return out
    comp = sum(wov.get(p, W[p]) * zs(srs(p, np.std([x[p] for x in G]) or 1.0)) for p in PILLARS); z_in = zs(comp)
    K = K_of(asof); lam = N / (N + K)
    zb = lam * z_in + (1 - lam) * zp
    method = np.where(N >= EARLY_N, 'srs', np.where(N > 0, 'early', 'prior'))
    surprise = np.full(n, np.nan)
    SDG = {p: (np.std([x[p] for x in G]) or 1.0) for p in PILLARS}
    c = np.array([sum(W[p] * float(np.clip(x[p], -3 * SDG[p], 3 * SDG[p])) / SDG[p] for p in PILLARS) for x in G])
    gap = np.array([zp[x['t']] - zp[x['o']] for x in G]); hm = np.array([1.0 if x['home'] else 0.0 for x in G])
    X = np.column_stack([hm, gap]); (a_h, b), *_ = np.linalg.lstsq(X * sw[:, None], c * sw, rcond=None)
    res = (c - X @ np.array([a_h, b])) / b
    acc = collections.defaultdict(list); gidx = collections.defaultdict(list)
    for gi, (x, r, wi) in enumerate(zip(G, res, w)):
        acc[x['t']].append((r, wi)); acc[x['o']].append((-r, wi)); gidx[x['t']].append(gi); gidx[x['o']].append(gi)
    for i, v in acc.items(): surprise[i] = sum(r * wi for r, wi in v) / sum(wi for _, wi in v)
    zb = np.where(method == 'early', zp + lam * np.nan_to_num(surprise), zb)
    def loo(j, gi):
        if method[j] != 'early': return zb[j] - zp[j]
        rest = [(r, wi) for (r, wi), g in zip(acc[j], gidx[j]) if g != gi]
        if not rest: return 0.0
        n1 = N[j] - 1; l1 = n1 / (n1 + K)
        return l1 * sum(r * wi for r, wi in rest) / sum(wi for _, wi in rest)
    acc2 = collections.defaultdict(list)
    for gi, (x, r, wi) in enumerate(zip(G, res, w)):
        acc2[x['t']].append((r + loo(x['o'], gi), wi)); acc2[x['o']].append((-r + loo(x['t'], gi), wi))
    for i, v in acc2.items(): surprise[i] = sum(r * wi for r, wi in v) / sum(wi for _, wi in v)
    zb = np.where(method == 'early', zp + lam * np.nan_to_num(surprise), zb)
    return zb, N


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--season', type=int, required=True); a = ap.parse_args()
    assert rc.OPP_CURRENT and rc.RIDGE == 0.5, 'production settings changed; re-copy rate()'
    S = a.season; B = 'data/backtest'
    P = pd.read_csv(f'data/kenpom/preseason_{S}.csv')
    teams = list(P.TeamName); tix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    zp = ((P.AdjEM - P.AdjEM.mean()) / P.AdjEM.std(ddof=0)).to_numpy(float)
    X = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    X.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    TG = pd.read_csv(f'{B}/games_{S}.csv')
    XB = {}
    for nm in set(TG.team) | set(TG.opp):
        if nm in tix: XB[nm] = nm
        elif X.get(nm) in tix: XB[nm] = X[nm]
    HCA = dict(pd.read_csv('data/kp_hca.csv')[['team', 'hca']].values)
    FX = load_factors(f'{B}/game_factors_{S}.csv')
    L = pd.read_csv(f'{B}/lines_{S}.csv').set_index('gameId')
    TG = TG[TG.pts.notna() & TG.opp_pts.notna()].copy()
    G = build_games(TG, tix, XB, FX, 'cw' if FX else 'box', collections.Counter(), reb_team=S <= 2025)[0]
    home = TG[TG.isHome == True].drop_duplicates('gameId').set_index('gameId')
    print(f'season {S}: {len(G)} D-I games; factors {"pbp" if FX else "BOX ONLY"}')
    rows, maxdiff = [], 0.0
    for d in sorted({x['date'] for x in G}):
        past = [x for x in G if x['date'] < d]
        if len(past) < 20: continue
        live = (dt.date.fromisoformat(d).replace(year=dt.date.fromisoformat(d).year + (2027 - S))).isoformat()
        prod = rate(past, n, zp, live, game_wt=True)['z_blend']
        Z = {}
        for v, cfg in VAR.items(): Z[v], Ncount = rate_v(past, n, zp, live, cfg)
        diff = float(np.abs(Z['base'] - prod).max()); maxdiff = max(maxdiff, diff)
        assert diff < 1e-9, f'{d}: base variant differs from production rate() by {diff}'
        for x in G:
            if x['date'] != d or x['gameId'] not in home.index: continue
            r = home.loc[x['gameId']]; h, o = x['t'], x['o']; hca = HCA.get(teams[h], 2.84) if x['home'] else 0.0
            row = dict(date=d, gameId=x['gameId'], home=teams[h], away=teams[o], neutral=not x['home'], margin=r.pts - r.opp_pts,
                       n_home=int(Ncount[h]), n_away=int(Ncount[o]), pred_prior=round(9.5 * (zp[h] - zp[o]) + hca, 3))
            for v, z in Z.items(): row[f'pred_{v}'] = round(9.5 * (z[h] - z[o]) + hca, 3)
            ln = L.loc[x['gameId']] if x['gameId'] in L.index else None
            row['open'] = None if ln is None or pd.isna(ln.spread_open) else float(ln.spread_open)
            row['close'] = None if ln is None or pd.isna(ln.spread_close) else float(ln.spread_close)
            rows.append(row)
    R = pd.DataFrame(rows); R.to_csv(f'{OUT}/preds_{S}.csv', index=False)
    print(f'{len(R)} games {R.date.min()} to {R.date.max()}; base vs production rate(): max |diff| {maxdiff:.2e} on every date -> {OUT}/preds_{S}.csv')


if __name__ == '__main__':
    main()
