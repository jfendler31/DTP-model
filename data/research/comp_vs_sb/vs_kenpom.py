"""Does the composite add anything beyond KenPom's in-season rating? (Nov 12, 2026)

Inputs: preds_<S>.csv (walk-forward composite / scoreboard / prior predictions, from comp_vs_sb.py) and KenPom archive
snapshots data/kenpom/history/archive_<date>.csv (weekly, Nov-Dec 2024-25 and 2025-26). For each game, KenPom's rating is the
latest snapshot on or before the game date (so 0-6 days stale; the composite uses games through the day before).
KenPom spread built like ours: 9.5 x (z_home - z_away) + KenPom HCA (0 neutral), z = AdjEM z-scored within the snapshot.
Also a scale-fitted version (margin ~ AdjEM diff + HCA) so the scale isn't the issue.
Tests: head-to-head MAE and ATS vs the close; cover-margin regressions with both edges in; team-level: the composite's move vs
KenPom's own in-season move (snapshot - preseason), and whether the residual predicts results vs the close.
Usage: python3 data/research/comp_vs_sb/vs_kenpom.py > data/research/comp_vs_sb/vs_kenpom.txt
"""
import glob, numpy as np, pandas as pd

D = 'data/research/comp_vs_sb'
HCA = dict(pd.read_csv('data/kp_hca.csv')[['team', 'hca']].values)
rows = []
for S in (2025, 2026):
    R = pd.read_csv(f'{D}/preds_{S}.csv'); R['season'] = S
    arch = {}
    for f in sorted(glob.glob(f'data/kenpom/history/archive_{S - 1}-1*.csv')):
        a = pd.read_csv(f); d = f[-14:-4]
        a['z'] = (a.AdjEM - a.AdjEM.mean()) / a.AdjEM.std(ddof=0)
        arch[d] = dict(z=dict(zip(a.TeamName, a.z)), em=dict(zip(a.TeamName, a.AdjEM)))
    P = pd.read_csv(f'data/kenpom/preseason_{S}.csv'); pz = (P.AdjEM - P.AdjEM.mean()) / P.AdjEM.std(ddof=0)
    PZ = dict(zip(P.TeamName, pz)); PEM = dict(zip(P.TeamName, P.AdjEM))
    dates = sorted(arch)
    for r in R.itertuples():
        use = [d for d in dates if d <= r.date]
        if not use: continue
        d = use[-1]; A = arch[d]
        if r.home not in A['z'] or r.away not in A['z']: continue
        hca = 0.0 if r.neutral else HCA.get(r.home, 2.84)
        rows.append(dict(season=S, date=r.date, home=r.home, away=r.away, neutral=r.neutral, margin=r.margin, close=r.close,
                         n_home=r.n_home, n_away=r.n_away, snap=d, stale=(pd.Timestamp(r.date) - pd.Timestamp(d)).days,
                         pred_prior=r.pred_prior, pred_comp=r.pred_comp_T, pred_sb=r.pred_sb_box,
                         pred_kp=9.5 * (A['z'][r.home] - A['z'][r.away]) + hca, kp_emdiff=A['em'][r.home] - A['em'][r.away], hca=hca,
                         kp_mv_home=9.5 * (A['z'][r.home] - PZ[r.home]), kp_mv_away=9.5 * (A['z'][r.away] - PZ[r.away]),
                         comp_mv_home=r.mv_comp_T_home, comp_mv_away=r.mv_comp_T_away,
                         sb_mv_home=r.mv_sb_box_home, sb_mv_away=r.mv_sb_box_away))
G = pd.DataFrame(rows)
# scale-fitted KenPom spread: margin ~ emdiff + hca
A_ = np.column_stack([G.kp_emdiff, G.hca]); b, *_ = np.linalg.lstsq(A_, G.margin, rcond=None)
G['pred_kp_fit'] = A_ @ b
print(f'{len(G)} games with a KenPom snapshot; stale days mean {G.stale.mean():.1f}; KenPom scale fit: margin = {b[0]:.3f} x AdjEM diff + {b[1]:.2f} x HCA')
H = G[(~G.neutral) & G.close.notna()].copy(); H['cover'] = H.margin + H.close


def ats(pred, df, lo=0):
    e = df[pred] + df.close; m = e.abs() >= lo
    res = np.sign(e[m]) * df.cover[m]; w, l = (res > 0).sum(), (res < 0).sum()
    return f'{w}-{l} {w / (w + l):.1%}' if w + l else '-'


def table(df, h, label):
    print(f'\n== {label}: {len(df)} games on margin, {len(h)} home/away vs close')
    print(f'{"version":14s} {"MAE":>6s} {"ATS all":>16s} {"ATS 2+":>16s} {"ATS 3+":>16s}')
    for v in ('pred_prior', 'pred_kp', 'pred_kp_fit', 'pred_comp', 'pred_sb'):
        print(f'{v:14s} {(df.margin - df[v]).abs().mean():6.3f} {ats(v, h):>16s} {ats(v, h, 2):>16s} {ats(v, h, 3):>16s}')
    for w in (.25, .5, .75):
        df[f'bl{w}'] = (1 - w) * df.pred_kp + w * df.pred_comp; h[f'bl{w}'] = (1 - w) * h.pred_kp + w * h.pred_comp
        print(f'{"kp+comp " + str(w):14s} {(df.margin - df[f"bl{w}"]).abs().mean():6.3f} {ats(f"bl{w}", h):>16s} {ats(f"bl{w}", h, 2):>16s} {ats(f"bl{w}", h, 3):>16s}')


table(G, H, 'ALL (KenPom snapshot 0-6 days old)')
f2 = G.stale <= 1; table(G[f2].copy(), H[H.stale <= 1].copy(), 'FRESH: games 0-1 days after a snapshot')
for S in (2025, 2026): table(G[G.season == S].copy(), H[H.season == S].copy(), f'season {S}')
late = G.n_home.ge(5) & G.n_away.ge(5); table(G[late].copy(), H[H.n_home.ge(5) & H.n_away.ge(5)].copy(), 'both teams 5+ games')


def reg(y, cols, df, label):
    A = np.column_stack([np.ones(len(df))] + [df[c] for c in cols]); bb, *_ = np.linalg.lstsq(A, y, rcond=None)
    s2 = ((y - A @ bb) ** 2).sum() / (len(df) - A.shape[1]); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print(f'  {label}: ' + ', '.join(f'{c} {v:+.3f} (se {s:.3f})' for c, v, s in zip(['const'] + cols, bb, se)))


print('\n== Cover-margin regressions (home/away games; edge = pred + close, >0 means the model likes the home side vs the line)')
for v in ('pred_kp', 'pred_comp', 'pred_sb'): H[f'e_{v}'] = H[v] + H.close
reg(H.cover, ['e_pred_kp'], H, 'KenPom alone')
reg(H.cover, ['e_pred_comp'], H, 'composite alone')
reg(H.cover, ['e_pred_kp', 'e_pred_comp'], H, 'both')
reg(H.cover, ['e_pred_kp', 'e_pred_comp', 'e_pred_sb'], H, 'all three')
Hf = H[H.stale <= 1]; reg(Hf.cover, ['e_pred_kp', 'e_pred_comp'], Hf, f'both, fresh snapshots only (n {len(Hf)})')
print('\n== Margin regressions (all games)')
reg(G.margin, ['pred_kp'], G, 'KenPom'); reg(G.margin, ['pred_comp'], G, 'composite'); reg(G.margin, ['pred_kp', 'pred_comp'], G, 'both')
G['d_comp'] = G.pred_comp - G.pred_prior; G['d_kp'] = G.pred_kp - G.pred_prior; G['d_sb'] = G.pred_sb - G.pred_prior
reg(G.margin - G.pred_prior, ['d_kp', 'd_comp'], G, 'margin - prior ~ KenPom move + composite move')
reg(G.margin - G.pred_prior, ['d_kp', 'd_comp', 'd_sb'], G, '... + scoreboard move')

print('\n== Team level: composite move vs KenPom\'s own in-season move (snapshot - preseason), points on our scale')
T = pd.concat([pd.DataFrame(dict(season=H.season, team=H.home, n=H.n_home, kp=H.kp_mv_home, comp=H.comp_mv_home, sb=H.sb_mv_home, stale=H.stale,
                                 res=H.cover - (H.pred_comp + H.close), res_kp=H.cover - (H.pred_kp + H.close))),
               pd.DataFrame(dict(season=H.season, team=H.away, n=H.n_away, kp=H.kp_mv_away, comp=H.comp_mv_away, sb=H.sb_mv_away, stale=H.stale,
                                 res=-(H.cover - (H.pred_comp + H.close)), res_kp=-(H.cover - (H.pred_kp + H.close))))])
print(f'  corr(composite move, KenPom move) {T[["comp", "kp"]].corr().iloc[0, 1]:.3f}; corr(scoreboard move, KenPom move) {T[["sb", "kp"]].corr().iloc[0, 1]:.3f}; '
      f'SD comp {T.comp.std():.2f}, kp {T.kp.std():.2f}, sb {T.sb.std():.2f}')
A = np.column_stack([np.ones(len(T)), T.kp]); bb, *_ = np.linalg.lstsq(A, T.comp, rcond=None); T['comp_resid'] = T.comp - A @ bb
print(f'  composite move = {bb[0]:+.2f} + {bb[1]:.3f} x KenPom move; residual SD {T.comp_resid.std():.2f}')
reg(T.res_kp, ['comp_resid'], T, "team's result vs KenPom's number ~ composite residual (what KenPom didn't have)")
reg(T.res_kp, ['kp', 'comp_resid'], T, '... with KenPom move itself in')
for lo, hi in ((-99, -1.5), (-1.5, -0.5), (-0.5, 0.5), (0.5, 1.5), (1.5, 99)):
    m = T.comp_resid.between(lo, hi, inclusive='left')
    print(f'    composite residual {lo:+.1f}..{hi:+.1f}: n {m.sum():5d}  result vs KenPom number {T.res_kp[m].mean():+.2f}')
