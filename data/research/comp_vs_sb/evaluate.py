"""Grade the composite / scoreboard blends from comp_vs_sb.py (both seasons pooled, and each season).
Usage: python3 data/research/comp_vs_sb/evaluate.py > data/research/comp_vs_sb/results.txt
"""
import numpy as np, pandas as pd

D = 'data/research/comp_vs_sb'
R = pd.concat([pd.read_csv(f'{D}/preds_{s}.csv').assign(season=s) for s in (2025, 2026)], ignore_index=True)
R['month'] = R.date.str[5:7]
WS = (0, .25, .5, .75, 1)
for sb in ('sb_box', 'sb_cw'):
    for w in WS:
        R[f'pred_{sb}_w{int(w * 100)}'] = (1 - w) * R.pred_comp_T + w * R[f'pred_{sb}']
H = R[(~R.neutral) & R.close.notna()].copy()                 # CBBD neutral-site orientation unreliable
H['cover'] = H.margin + H.close                              # home cover margin
H = H[H.open.isna() | ((H.open - H.close).abs() < 6)]       # drop bad references, as in the grade log (2024-25 has no opens)


def ats(pred, df, lo=0, ref='close'):
    e = df[pred] + df[ref]                                   # >0: model on home vs that line
    m = e.abs() >= lo
    res = np.sign(e[m]) * (df.margin[m] + df[ref][m])
    w, l = (res > 0).sum(), (res < 0).sum()
    return w, l, (w / (w + l) if w + l else np.nan)


def clv(pred, df, lo=0):
    d = df[df.open.notna()]; e = d[pred] + d.open; m = e.abs() >= lo
    return (np.sign(e[m]) * (d.open[m] - d.close[m])).mean(), m.sum()


def table(df, H_, label):
    print(f'\n== {label}: {len(df)} games graded on margin; {len(H_)} home/away with a close')
    print(f'{"version":22s} {"MAE":>6s} {"ATS all":>15s} {"ATS 2+":>15s} {"ATS 3+":>15s} {"CLV 2+ (open)":>15s} {"CLV 3+":>12s}')
    for v in ['pred_prior', 'pred_comp_F', 'pred_comp_T', 'pred_sb_box', 'pred_sb_cw'] + \
             [f'pred_{sb}_w{int(w * 100)}' for sb in ('sb_box', 'sb_cw') for w in (.25, .5, .75)]:
        mae = (df.margin - df[v]).abs().mean()
        a0, a2, a3 = ats(v, H_), ats(v, H_, 2), ats(v, H_, 3)
        c2, n2 = clv(v, H_, 2); c3, n3 = clv(v, H_, 3)
        f = lambda a: f'{a[0]}-{a[1]} {a[2]:.1%}'
        print(f'{v:22s} {mae:6.3f} {f(a0):>15s} {f(a2):>15s} {f(a3):>15s} {c2:+7.2f} ({n2:4d}) {c3:+6.2f} ({n3})')


table(R, H, 'POOLED 2024-25 + 2025-26, Nov-Dec')
for s in (2025, 2026):
    table(R[R.season == s], H[H.season == s], f'season {s}')
for mo in ('11', '12'):
    table(R[R.month == mo], H[H.month == mo], f'month {mo} (both seasons)')

# ---- regression: what weight does the data put on each in-season reading, beyond the close?
print('\n== Regressions (pooled home/away games). y = home cover margin (margin + close)')
X = pd.DataFrame({'comp_edge': H.pred_comp_T + H.close, 'sb_minus_comp': H.pred_sb_box - H.pred_comp_T})
for cols in (['comp_edge'], ['comp_edge', 'sb_minus_comp']):
    A = np.column_stack([np.ones(len(H))] + [X[c] for c in cols]); b, res, *_ = np.linalg.lstsq(A, H.cover, rcond=None)
    s2 = ((H.cover - A @ b) ** 2).sum() / (len(H) - A.shape[1]); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print('  ' + ', '.join(f'{c} {bb:+.3f} (se {ss:.3f})' for c, bb, ss in zip(['const'] + cols, b, se)))
print('  -> implied weight on scoreboard vs composite = coef(sb_minus_comp) / coef(comp_edge)')
# margin regression (no market): how should the two moves combine to predict the margin?
Rm = R.copy()
Am = np.column_stack([np.ones(len(Rm)), Rm.pred_prior, Rm.pred_comp_T - Rm.pred_prior, Rm.pred_sb_box - Rm.pred_prior])
b, *_ = np.linalg.lstsq(Am, Rm.margin, rcond=None)
s2 = ((Rm.margin - Am @ b) ** 2).sum() / (len(Rm) - 4); se = np.sqrt(np.diag(s2 * np.linalg.inv(Am.T @ Am)))
print('  margin ~ prior + comp_move + sb_move: ' + ', '.join(f'{c} {bb:+.3f} (se {ss:.3f})' for c, bb, ss in zip(['const', 'prior', 'comp_move', 'sb_move'], b, se)))

# ---- cuts by the size and direction of the gap
print('\n== When the two readings disagree (game-level gap = pred_sb_box - pred_comp_T, home perspective)')
H['gap'] = H.pred_sb_box - H.pred_comp_T; R['gap'] = R.pred_sb_box - R.pred_comp_T
for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 99)):
    m = H.gap.abs().between(lo, hi, inclusive='left'); mm = R.gap.abs().between(lo, hi, inclusive='left')
    sub = R[mm]
    mae = {v: (sub.margin - sub[v]).abs().mean() for v in ('pred_comp_T', 'pred_sb_box', 'pred_sb_box_w50')}
    # where they're on opposite sides of the close: who wins?
    hh = H[m]; ec, es = hh.pred_comp_T + hh.close, hh.pred_sb_box + hh.close; split = np.sign(ec) != np.sign(es)
    sbwin = (np.sign(es[split]) * hh.cover[split] > 0).sum(); cwin = (np.sign(ec[split]) * hh.cover[split] > 0).sum()
    # does the cover residual lean toward the scoreboard's side of the composite?
    lean = (np.sign(hh.gap) * (hh.cover - ec)).mean()
    print(f'  |gap| {lo}-{hi}: n {mm.sum()} MAE comp {mae["pred_comp_T"]:.3f} sb {mae["pred_sb_box"]:.3f} 50/50 {mae["pred_sb_box_w50"]:.3f}'
          f' | split sides vs close {split.sum()}: sb side {sbwin}-{cwin} | result vs comp, toward sb: {lean:+.2f} pts (n {m.sum()})')

# ---- the OSU pattern: composite well above scoreboard for a team, against weak opponents so far
print('\n== Team-level: composite move minus scoreboard move, by past-opponent strength')
T = []
for side, op in (('home', 'away'), ('away', 'home')):
    s = 1 if side == 'home' else -1
    T.append(pd.DataFrame(dict(season=H.season, date=H.date, team=H[side], n=H[f'n_{side}'],
                               gap_team=H[f'mv_comp_T_{side}'] - H[f'mv_sb_box_{side}'],
                               gap_opp=H[f'mv_comp_T_{op}'] - H[f'mv_sb_box_{op}'],
                               res=s * (H.cover - (H.pred_comp_T + H.close)))))   # team's result vs the composite's number
T = pd.concat(T)
# past opponents' mean preseason z for each team-date
allg = pd.concat([R[['season', 'date', 'home', 'zp_away']].rename(columns={'home': 'team', 'zp_away': 'oz'}),
                  R[['season', 'date', 'away', 'zp_home']].rename(columns={'away': 'team', 'zp_home': 'oz'})])
allg = allg.sort_values('date')
def past_opp(r):
    g = allg[(allg.season == r.season) & (allg.team == r.team) & (allg.date < r.date)]
    return g.oz.mean() if len(g) else np.nan
T['opp_z'] = T.apply(past_opp, axis=1)
T['tier'] = pd.cut(T.opp_z, [-9, -0.75, 0, 9], labels=['weak opps', 'middle', 'strong opps'])
T['gb'] = pd.cut(T.gap_team, [-99, -1.5, -0.5, 0.5, 1.5, 99], labels=['comp << sb', 'comp < sb', 'even', 'comp > sb', 'comp >> sb'])
print(T.groupby(['gb'], observed=True).res.agg(['count', 'mean']).round(2).to_string())
print(T.groupby(['tier', 'gb'], observed=True).res.agg(['count', 'mean']).round(2).to_string())
print('  res = team result vs the composite\'s number, ATS terms (negative = team did worse than the composite said)')
A = np.column_stack([np.ones(len(T)), T.gap_team]); b, *_ = np.linalg.lstsq(A, T.res, rcond=None)
s2 = ((T.res - A @ b) ** 2).sum() / (len(T) - 2); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
print(f'  res ~ gap_team: slope {b[1]:+.3f} (se {se[1]:.3f})  [-1 would mean the scoreboard is right, 0 the composite]')
for nb in ((1, 2), (3, 5), (6, 99)):
    t = T[T.n.between(*nb)]; A = np.column_stack([np.ones(len(t)), t.gap_team]); b, *_ = np.linalg.lstsq(A, t.res, rcond=None)
    s2 = ((t.res - A @ b) ** 2).sum() / (len(t) - 2); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print(f'    games played {nb[0]}-{nb[1] if nb[1] < 99 else "+"}: n {len(t)} slope {b[1]:+.3f} (se {se[1]:.3f})')

# ---- asymmetry: is the scoreboard more informative when the composite is above it?
print('\n== Asymmetry (team level): slope of res on gap, separately for composite above / below the scoreboard')
for lab, t in (('comp > sb (gap > 0)', T[T.gap_team > 0]), ('comp < sb (gap < 0)', T[T.gap_team < 0])):
    A = np.column_stack([np.ones(len(t)), t.gap_team]); b, *_ = np.linalg.lstsq(A, t.res, rcond=None)
    s2 = ((t.res - A @ b) ** 2).sum() / (len(t) - 2); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print(f'  {lab}: n {len(t)} mean gap {t.gap_team.mean():+.2f} slope {b[1]:+.3f} (se {se[1]:.3f}) intercept {b[0]:+.2f}')
print(T.groupby('gb', observed=True).gap_team.mean().round(2).to_string())
for s in (2025, 2026):
    t = T[T.season == s]; A = np.column_stack([np.ones(len(t)), t.gap_team]); b, *_ = np.linalg.lstsq(A, t.res, rcond=None)
    s2 = ((t.res - A @ b) ** 2).sum() / (len(t) - 2); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print(f'  season {s}: slope {b[1]:+.3f} (se {se[1]:.3f})')
