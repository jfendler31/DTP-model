"""Grade the prior-pull fix variants from backtest_fix.py (both seasons, each season, by month, by line size, fav/dog).
Usage: python3 data/research/prior_pull/evaluate_fix.py > data/research/prior_pull/results.txt
"""
import numpy as np, pandas as pd

D = 'data/research/prior_pull'
R = pd.concat([pd.read_csv(f'{D}/preds_{s}.csv').assign(season=s) for s in (2025, 2026)], ignore_index=True)
R['month'] = R.date.str[5:7]
V = ['pred_prior', 'pred_base', 'pred_fix', 'pred_fix_k125', 'pred_fix_k150']
H = R[(~R.neutral) & R.close.notna()].copy()
H = H[H.open.isna() | ((H.open - H.close).abs() < 6)]
H['mkt'] = -H.close                      # home favored by this many


def ats(pred, df, lo=0):
    e = df[pred] + df.close; m = e.abs() >= lo
    res = np.sign(e[m]) * (df.margin[m] + df.close[m])
    w, l = int((res > 0).sum()), int((res < 0).sum())
    return w, l, (w / (w + l) if w + l else np.nan)


def clv(pred, df, lo=0):
    d = df[df.open.notna()]; e = d[pred] + d.open; m = e.abs() >= lo
    return (np.sign(e[m]) * (d.open[m] - d.close[m])).mean(), int(m.sum())


def table(df, H_, label):
    print(f'\n== {label}: {len(df)} games on margin; {len(H_)} home/away with a close')
    print(f'{"version":16s} {"MAE":>6s} {"ATS all":>15s} {"ATS 2+":>15s} {"ATS 3+":>15s} {"CLV 2+":>13s} {"CLV 3+":>13s}')
    for v in V:
        mae = (df.margin - df[v]).abs().mean()
        a0, a2, a3 = ats(v, H_), ats(v, H_, 2), ats(v, H_, 3)
        c2, n2 = clv(v, H_, 2); c3, n3 = clv(v, H_, 3)
        f = lambda a: f'{a[0]}-{a[1]} {a[2]:.1%}'
        print(f'{v:16s} {mae:6.3f} {f(a0):>15s} {f(a2):>15s} {f(a3):>15s} {c2:+6.2f} ({n2:4d}) {c3:+6.2f} ({n3:4d})')


table(R, H, 'POOLED Nov-Dec 2024-25 + 2025-26')
for s in (2025, 2026): table(R[R.season == s], H[H.season == s], f'season {s}')
for mo in ('11', '12'): table(R[R.month == mo], H[H.month == mo], f'month {mo}')
both3 = (R.n_home >= 3) & (R.n_away >= 3)
table(R[both3], H[(H.n_home >= 3) & (H.n_away >= 3)], 'both teams on SRS (3+ games)')

print('\n== By line size (home/away games with a close), model side vs close; "dog" = model on the dog side of the close')
print(f'{"lines":8s} {"version":16s} {"n":>5s} {"model-mkt":>10s} {"ATS 3+":>15s} {"ATS 3+ on dog":>16s} {"ATS 3+ on fav":>16s} {"CLV 3+":>8s}')
for lo, hi in ((0, 10), (10, 15), (15, 20), (20, 99)):
    S_ = H[(H.mkt.abs() >= lo) & (H.mkt.abs() < hi)]
    sg = np.sign(S_.mkt)
    for v in V:
        e = S_[v] + S_.close; m = e.abs() >= 3
        res = np.sign(e) * (S_.margin + S_.close)
        ondog = m & (np.sign(e) != sg); onfav = m & (np.sign(e) == sg)
        f = lambda mm: f'{int((res[mm] > 0).sum())}-{int((res[mm] < 0).sum())} {((res[mm] > 0).sum() / max(1, (res[mm] != 0).sum())):.1%}'
        gap = (sg * S_[v] - S_.mkt.abs()).mean()   # favorite terms: model's favorite margin minus market's
        c3, _ = clv(v, S_, 3)
        print(f'{lo}-{hi:<5d} {v:16s} {len(S_):5d} {gap:+10.2f} {f(m):>15s} {f(ondog):>16s} {f(onfav):>16s} {c3:+8.2f}')

print('\n== Does the fix remove the pull? slope of team move (pts) on z_prior, teams with 3-12 games, by variant')
for v in ['base', 'fix', 'fix_k125', 'fix_k150']:
    tm = pd.concat([R[['zp_home', f'mv_{v}_home', 'n_home']].set_axis(['zp', 'mv', 'n'], axis=1),
                    R[['zp_away', f'mv_{v}_away', 'n_away']].set_axis(['zp', 'mv', 'n'], axis=1)])
    tm = tm[tm.n.between(3, 12)]
    print(f'  {v:10s} slope {np.polyfit(tm.zp, tm.mv, 1)[0]:+.2f}  (mean |move| {tm.mv.abs().mean():.2f})')

print('\n== Regression (home/away, both on SRS): favorite margin minus close on (model minus close), favorite terms')
Hs = H[(H.n_home >= 3) & (H.n_away >= 3)]
for lo in (0, 15, 20):
    s = Hs[Hs.mkt.abs() >= lo]; sg = np.sign(s.mkt); y = sg * (s.margin - s.mkt)
    out = []
    for v in V:
        x = sg * s[v] - s.mkt; A = np.c_[x, np.ones(len(s))]; co = np.linalg.lstsq(A, y, rcond=None)[0]
        e = y - A @ co; se = np.sqrt(np.diag(np.linalg.inv(A.T @ A)) * e.var())
        out.append(f'{v[5:]} {co[0]:+.2f} ({se[0]:.2f})')
    print(f'  lines>={lo} n={len(s)}: ' + ' | '.join(out))
