"""Size-curve refit (Nov 13, 2026). Question: how much should the model spread be widened per point beyond the knee so that the
size-adjusted number is unbiased against the market/result at every line band, and does a steeper curve change what the card
sorts to the top without hurting the sub-20 edges?

Data: production model walk-forward predictions (data/research/prior_pull/preds_<S>.csv, pred_base = raw model home margin),
backtest lines and games (data/backtest). Curve applied as the card does: only home games, model favoring the home team,
non-conference (conf != opp_conf), widened k per point beyond knee 10.

Protocol: fit on one season, test on the other, both directions. Three fits per training season:
  k_mkt   least squares of (market - model) on (|model| - 10)+  : makes our number match the market on average
  k_res   least squares of (favorite margin - model) on (|model| - 10)+ : makes our number match results on average
Then grade k in {0.20 (production), 0.30, 0.40, k_mkt, k_res} on the held-out season: model-side ATS vs the close by line band,
model-on-dog vs model-on-fav, CLV, and how many 20+ dog edges of 3+ remain.
Usage: python3 data/research/size_curve/fit_curve.py"""
import numpy as np, pandas as pd

KNEE = 10
rows = []
for S in (2025, 2026):
    R = pd.read_csv(f'data/research/prior_pull/preds_{S}.csv').assign(season=S)
    G = pd.read_csv(f'data/backtest/games_{S}.csv').drop_duplicates('gameId').set_index('gameId')
    R['conf_game'] = R.gameId.map(lambda g: G.conf.get(g) == G.opp_conf.get(g) if g in G.index else np.nan)
    rows.append(R)
R = pd.concat(rows, ignore_index=True)      # duplicate indices across seasons broke a .loc join in the first run
R = R[(~R.neutral) & R.close.notna() & R.conf_game.notna()]
R = R[R.open.isna() | ((R.open - R.close).abs() < 6)].copy()
R['mkt'] = -R.close                                   # home favored by this many
R['ok'] = (R.pred_base > 0) & (~R.conf_game.astype(bool))     # curve applies: model favors home, non-conference
R['x'] = np.where(R.ok, np.maximum(R.pred_base - KNEE, 0), 0)
print(f'{len(R)} home games with a close; curve applies to {int(R.ok.sum())}; x>0 in {int((R.x > 0).sum())}')


def adj(df, k): return df.pred_base + k * df.x


def grade(df, k, label):
    m = adj(df, k); e = m + df.close                 # >0: model on home vs the close
    res = np.sign(e) * (df.margin + df.close)
    sg = np.sign(df.mkt)
    out = {'curve': label}
    for lo, hi, nm in ((0, 10, '<10'), (10, 15, '10-15'), (15, 20, '15-20'), (20, 99, '20+')):
        b = (df.mkt.abs() >= lo) & (df.mkt.abs() < hi) & (e.abs() >= 3)
        w, l = int((res[b] > 0).sum()), int((res[b] < 0).sum())
        dog = b & (np.sign(e) != sg); wd, ld = int((res[dog] > 0).sum()), int((res[dog] < 0).sum())
        out[f'{nm} 3+'] = f'{w}-{l} {w / (w + l):.0%}' if w + l else '-'
        out[f'{nm} dog'] = f'{wd}-{ld}'
    b = e.abs() >= 3; w, l = int((res[b] > 0).sum()), int((res[b] < 0).sum())
    out['all 3+'] = f'{w}-{l} {w / (w + l):.1%}'
    o = df[df.open.notna()]
    if len(o):
        eo = adj(o, k) + o.open; bo = eo.abs() >= 3
        out['CLV 3+'] = f'{(np.sign(eo[bo]) * (o.open[bo] - o.close[bo])).mean():+.2f}'
    big = df[(df.mkt.abs() >= 20) & df.ok]
    out['20+ bias (mkt-model)'] = f'{(big.mkt - adj(big, k)).mean():+.2f}'
    out['20+ dog 3+ count'] = int(((adj(big, k) + big.close) <= -3).sum())
    return out


for train, test in ((2025, 2026), (2026, 2025)):
    tr = R[(R.season == train) & (R.x > 0)]; te = R[R.season == test]
    k_mkt = float(np.polyfit(tr.x, tr.mkt - tr.pred_base, 1)[0])
    k_res = float(np.polyfit(tr.x, tr.margin - tr.pred_base, 1)[0])
    # also the intercept-free versions (through the knee)
    k_mkt0 = float((tr.x * (tr.mkt - tr.pred_base)).sum() / (tr.x ** 2).sum())
    k_res0 = float((tr.x * (tr.margin - tr.pred_base)).sum() / (tr.x ** 2).sum())
    print(f'\n== fit on {train} (n {len(tr)} curve games): k_mkt {k_mkt:.3f} (through knee {k_mkt0:.3f}), k_res {k_res:.3f} (through knee {k_res0:.3f}); test on {test}')
    T = pd.DataFrame([grade(te, 0.0, 'none'), grade(te, 0.20, '0.20 (prod)'), grade(te, 0.30, '0.30'), grade(te, 0.40, '0.40'),
                      grade(te, k_mkt0, f'k_mkt {k_mkt0:.2f}'), grade(te, k_res0, f'k_res {k_res0:.2f}')])
    pd.set_option('display.width', 250); print(T.to_string(index=False))

# bias of the raw model vs market and vs result by line band, both seasons (what the curve is trying to fix)
print('\n== raw model (no curve) vs market and vs result, curve-eligible home games, by MODEL spread band, both seasons')
el = R[R.ok].copy(); el['band'] = pd.cut(el.pred_base, [0, 10, 15, 20, 25, 30, 99], labels=['<10', '10-15', '15-20', '20-25', '25-30', '30+'])
el['mkt_minus_model'] = el.mkt - el.pred_base; el['result_minus_model'] = el.margin - el.pred_base; el['result_minus_mkt'] = el.margin - el.mkt
print(el.groupby('band', observed=True).agg(n=('margin', 'size'), mkt_minus_model=('mkt_minus_model', 'mean'), result_minus_model=('result_minus_model', 'mean'),
                                            result_minus_mkt_mean=('result_minus_mkt', 'mean'), result_minus_mkt_median=('result_minus_mkt', 'median'),
                                            fav_cover_rate=('result_minus_mkt', lambda s: (s > 0).mean())).round(2).to_string())
print('\n== 20+ MARKET lines, curve-eligible: dog cover rate by what the RAW model says')
big = el[el.mkt >= 20]; e = big.pred_base - big.mkt
for lab, m in (('model on fav by 2+', e >= 2), ('|e|<2', e.abs() < 2), ('model on dog 2-5', (e <= -2) & (e > -5)), ('model on dog 5+', e <= -5)):
    s = big[m]; print(f'  {lab:20s}: n {len(s):3d}, dog covers {(s.result_minus_mkt < 0).mean():.1%}, mean fav margin-mkt {s.result_minus_mkt.mean():+.2f}')
