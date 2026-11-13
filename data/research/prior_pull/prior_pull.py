"""Systematic pull of in-season moves toward the middle (Nov 12, 2026).
Part 1 (live): slope of move_pts on z_prior for SRS-method teams in data/ratings_current.csv,
  and each card game's edge with the fitted pull removed (--card cards/card_D.csv).
Part 2 (backtest): split the composite's move into the pull (fitted on z_prior by games played)
  and the team-specific residual; regress favorite margin minus close on both (+ prior minus close).
Usage: python3 data/research/prior_pull/prior_pull.py [--card cards/card_D.csv]"""
import argparse, numpy as np, pandas as pd
ap = argparse.ArgumentParser(); ap.add_argument('--card'); a = ap.parse_args()
r = pd.read_csv('data/ratings_current.csv').set_index('team'); s = r[r.method == 'srs']
b1, b0 = np.polyfit(s.z_prior, s.move_pts, 1)
print(f'live: {len(s)} SRS teams, move = {b1:.2f}*z_prior + {b0:.2f}')
if a.card:
    fit = lambda t: (b1 * r.z_prior[t] + b0) if t in r.index and r.method[t] == 'srs' else 0.0
    c = pd.read_csv(a.card); out = []
    for _, g in c.iterrows():
        pull = fit(g.home) - fit(g.away); e = g.market_home_spread - g.model_home_spread_adj
        out.append((g.away, g.home, g.market_home_spread, round(e, 1), round(-pull, 1), round(e - pull, 1)))
    d = pd.DataFrame(out, columns=['away', 'home', 'market', 'edge_home', 'pull_toward_away', 'edge_net'])
    print(d.reindex(d.edge_net.abs().sort_values(ascending=False).index).to_string(index=False))
d = pd.concat([pd.read_csv(f'data/research/comp_vs_sb/preds_{y}.csv') for y in (2025, 2026)])
d = d[d.close.notna() & d.n_home.between(3, 12) & d.n_away.between(3, 12)].copy()
tm = pd.concat([d[['zp_home', 'mv_comp_T_home', 'n_home']].set_axis(['zp', 'mv', 'n'], axis=1),
                d[['zp_away', 'mv_comp_T_away', 'n_away']].set_axis(['zp', 'mv', 'n'], axis=1)])
fits = {n: np.polyfit(tm[tm.n == n].zp, tm[tm.n == n].mv, 1) for n in range(3, 13)}
print('backtest slope of move on z_prior by games:', {n: round(f[0], 2) for n, f in fits.items()})
f = lambda zp, n: np.array([fits[k][0] * z + fits[k][1] for z, k in zip(zp, n)])
d['mkt'] = -d.close; sg = np.sign(d.mkt)
d['pull'] = sg * (f(d.zp_home, d.n_home) - f(d.zp_away, d.n_away))
d['resid'] = sg * (d.mv_comp_T_home - d.mv_comp_T_away) - d.pull
d['pm'] = sg * (d.pred_prior - d.mkt); d['y'] = sg * (d.margin - d.mkt)
for lo in (0, 15, 20):
    x = d[d.mkt.abs() >= lo]
    for cols in (['pull', 'resid'], ['pull', 'resid', 'pm']):
        X = np.c_[x[cols].values, np.ones(len(x))]; co = np.linalg.lstsq(X, x.y, rcond=None)[0]
        e = x.y - X @ co; se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * e.var())
        print(f'line>={lo} n={len(x)} pull mean {x.pull.mean():.2f} | ' + ' '.join(f'{c} {p:.2f} ({q:.2f})' for c, p, q in zip(cols, co, se)))
