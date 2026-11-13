"""Grade backtest_pillars.py variants. Paired comparisons against base (same games), per season and pooled; Nov only and
'both teams 3-6 games' (where opponent ratings are noisiest). ATS vs close; CLV vs open where opens exist (2025-26).
Usage: python3 data/research/pillar_adj/evaluate_pillars.py > data/research/pillar_adj/results.txt"""
import numpy as np, pandas as pd
D = 'data/research/pillar_adj'
R = pd.concat([pd.read_csv(f'{D}/preds_{s}.csv').assign(season=s) for s in (2024, 2025, 2026)], ignore_index=True)
V = [c[5:] for c in R.columns if c.startswith('pred_') and c != 'pred_prior']
# cross-check against the independent prior_pull backtest (same production model)
for s in (2025, 2026):
    O = pd.read_csv(f'data/research/prior_pull/preds_{s}.csv').set_index('gameId').pred_base
    x = R[R.season == s].set_index('gameId').pred_base
    j = pd.concat([O, x], axis=1, keys=['old', 'new']).dropna()
    print(f'cross-check {s}: {len(j)} games in both, max |pred_base diff| {(j.old - j.new).abs().max():.3f}')
R['nov'] = R.date.str[5:7] == '11'
R['early'] = R.n_home.between(3, 6) & R.n_away.between(3, 6)
ok = (~R.neutral) & R.close.notna() & (R.open.isna() | ((R.open - R.close).abs() < 6))


def ats(df, v, lo):
    e = df[f'pred_{v}'] + df.close; m = e.abs() >= lo
    res = np.sign(e[m]) * (df.margin[m] + df.close[m]); w, l = int((res > 0).sum()), int((res < 0).sum())
    return f'{w}-{l} {w / max(1, w + l):.1%}'


def clv(df, v, lo):
    d = df[df.open.notna()]; e = d[f'pred_{v}'] + d.open; m = e.abs() >= lo
    return f'{(np.sign(e[m]) * (d.open[m] - d.close[m])).mean():+.2f}' if m.sum() else '   -'


def table(sub, label):
    H = sub[ok.loc[sub.index]]
    base = (sub.margin - sub.pred_base).abs()
    print(f'\n== {label}: {len(sub)} games on margin, {len(H)} with a close')
    print(f'{"variant":13s} {"MAE":>7s} {"dMAE vs base (se)":>20s} {"ATS all":>15s} {"ATS 2+":>15s} {"ATS 3+":>15s} {"CLV 3+":>7s}')
    for v in V:
        a = (sub.margin - sub[f'pred_{v}']).abs(); d = a - base
        print(f'{v:13s} {a.mean():7.3f} {d.mean():+9.3f} ({d.std() / np.sqrt(len(d)):.3f}) {ats(H, v, 0):>15s} {ats(H, v, 2):>15s} {ats(H, v, 3):>15s} {clv(H, v, 3):>7s}')


table(R, 'POOLED three seasons, Nov-Dec')
table(R[R.season >= 2025], 'POOLED 2024-25 + 2025-26 (play-by-play factors, as production)')
for s in (2024, 2025, 2026): table(R[R.season == s], f'season {s}' + (' (box factors, garbage time in)' if s == 2024 else ''))
table(R[R.nov], 'November only, three seasons')
table(R[R.early], 'both teams 3-6 D-I games, three seasons')
for s in (2024, 2025, 2026): table(R[R.early & (R.season == s)], f'both teams 3-6 games, season {s}')

print('\n== Games where the variant moves the number by 1+ vs base (both on SRS): does the move help? (+ = variant closer to the result)')
for v in V[1:]:
    x = R[(R.n_home >= 3) & (R.n_away >= 3)]; dlt = x[f'pred_{v}'] - x.pred_base; m = dlt.abs() >= 1
    y = x[m]; gain = (y.margin - y.pred_base).abs() - (y.margin - y[f'pred_{v}']).abs()
    # slope: (margin - base) on (variant - base); 1 = variant fully right, 0 = no information, <0 = wrong way
    X = np.c_[dlt, np.ones(len(x))]; yy = x.margin - x.pred_base; co = np.linalg.lstsq(X, yy, rcond=None)[0]
    e = yy - X @ co; se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * e.var())
    by = ' '.join(f'{s}:{np.polyfit((x[f"pred_{v}"] - x.pred_base)[x.season == s], yy[x.season == s], 1)[0]:+.2f}' for s in (2024, 2025, 2026))
    print(f'  {v:13s} moved 1+: {int(m.sum()):4d} games, mean gain {gain.mean():+.3f} | slope of (margin-base) on (variant-base): {co[0]:+.2f} (se {se[0]:.2f}) [{by}]')
