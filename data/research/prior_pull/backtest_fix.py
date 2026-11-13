"""Backtest of the prior-pull fix (Nov 12, 2026). Production ratings_core.rate() is NOT modified; the fix is applied on top.

Finding: the in-season composite z_in is re-standardized to SD 1, so after a few games (mostly noise) its slope on the
prior is ~0.7-0.8 instead of ~1, and the blend pulls every team toward the middle by ~0.7 x z_prior (rating pts).

Variants (walk-forward, Nov-Dec, stored backtest seasons, same machinery as comp_vs_sb.py; prior = KenPom preseason z):
  base      production: z_blend = lam*z_in + (1-lam)*z_prior
  fix       z_in rescaled by 1/b, b = slope of z_in on z_prior across SRS-method teams that day (b clipped to [0.5, 1.5];
            fitted on all rated teams while fewer than 30 are on SRS) -> slope of the in-season reading on the prior = 1
  fix_k125  fix with K x 1.25 for SRS teams (the rescaled reading is noisier)
  fix_k150  fix with K x 1.5
Early-method teams (games 1-2) are untouched in every variant (they move by surprise, not z_in).
Output: data/research/prior_pull/preds_<S>.csv. Then: python3 data/research/prior_pull/evaluate_fix.py
Usage: python3 data/research/prior_pull/backtest_fix.py --season 2026
"""
import os, sys, json, argparse, collections, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, 'jobs')
import ratings_core as rc
from ratings_core import build_games, rate, load_factors

OUT = 'data/research/prior_pull'
KMULT = {'fix': 1.0, 'fix_k125': 1.25, 'fix_k150': 1.5}


def fixed_blend(out, zp, kmult):
    """apply the fix to a production rate() result: rescale z_in so its slope on zp is 1 (SRS teams), optional K multiplier"""
    N, method, z_in = out['N'], out['method'], np.nan_to_num(out['z_in'])
    srs = method == 'srs'; rated = N > 0
    fit_on = srs if srs.sum() >= 30 else rated
    if fit_on.sum() < 10: return out['z_blend'].copy(), np.nan
    b = np.polyfit(zp[fit_on], z_in[fit_on], 1)[0]; b = float(np.clip(b, 0.5, 1.5))
    K = out['K'] * kmult; lam = N / (N + K)
    zb = out['z_blend'].copy()
    zb[srs] = lam[srs] * z_in[srs] / b + (1 - lam[srs]) * zp[srs]
    return zb, b


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--season', type=int, required=True); a = ap.parse_args()
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
    G = build_games(TG, tix, XB, FX, 'cw', collections.Counter(), reb_team=S <= 2025)[0]
    home = TG[TG.isHome == True].drop_duplicates('gameId').set_index('gameId')
    print(f'season {S}: {len(G)} D-I games')
    rows, slopes = [], []
    for d in sorted({x['date'] for x in G}):
        past = [x for x in G if x['date'] < d]
        if len(past) < 20: continue
        live = (dt.date.fromisoformat(d).replace(year=dt.date.fromisoformat(d).year + (2027 - S))).isoformat()
        out = rate(past, n, zp, live, game_wt=True)
        Z = {'base': out['z_blend']}
        for v, km in KMULT.items():
            Z[v], b = fixed_blend(out, zp, km)
            if v == 'fix': slopes.append((d, int((out['method'] == 'srs').sum()), b))
        Ncount = out['N']
        for x in G:
            if x['date'] != d or x['gameId'] not in home.index: continue
            r = home.loc[x['gameId']]; h, o = x['t'], x['o']; hca = HCA.get(teams[h], 2.84) if x['home'] else 0.0
            row = dict(date=d, gameId=x['gameId'], home=teams[h], away=teams[o], neutral=not x['home'], margin=r.pts - r.opp_pts,
                       n_home=int(Ncount[h]), n_away=int(Ncount[o]), zp_home=round(zp[h], 3), zp_away=round(zp[o], 3),
                       pred_prior=round(9.5 * (zp[h] - zp[o]) + hca, 2))
            for v, z in Z.items():
                row[f'pred_{v}'] = round(9.5 * (z[h] - z[o]) + hca, 2)
                row[f'mv_{v}_home'] = round(9.5 * (z[h] - zp[h]), 2); row[f'mv_{v}_away'] = round(9.5 * (z[o] - zp[o]), 2)
            ln = L.loc[x['gameId']] if x['gameId'] in L.index else None
            row['open'] = None if ln is None or pd.isna(ln.spread_open) else float(ln.spread_open)
            row['close'] = None if ln is None or pd.isna(ln.spread_close) else float(ln.spread_close)
            rows.append(row)
    R = pd.DataFrame(rows); os.makedirs(OUT, exist_ok=True); R.to_csv(f'{OUT}/preds_{S}.csv', index=False)
    pd.DataFrame(slopes, columns=['date', 'n_srs', 'b']).to_csv(f'{OUT}/slope_{S}.csv', index=False)
    print(f'{len(R)} games, {R.date.min()} to {R.date.max()} -> {OUT}/preds_{S}.csv; daily b in slope_{S}.csv')


if __name__ == '__main__':
    main()
