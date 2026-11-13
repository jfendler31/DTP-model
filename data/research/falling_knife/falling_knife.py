"""Falling knives (Jon, Nov 13, 2026): do teams that have fallen hard vs their prior after a few games keep falling — against
the close (market under-reacts) and against our model (our K too slow)? Worse for year-zero (low-continuity) teams?

Data: production walk-forward predictions (data/research/prior_pull/preds_<S>.csv; pred_base, mv_base_* = the team's move vs
prior entering the game), 2024-25 and 2025-26, Nov 1-Nov 30 (K = 8 throughout), team has 3-8 D-I games entering.
One row per team-game. ats_close = team margin + its closing spread (team perspective, + = covered); vs_model = team margin
minus our model's team margin. In-season-only signal: s = (z_in - z_prior) in rating pts = move / lam, lam = n/(n+8).
Continuity: KenPom end-of-season Continuity (share of minutes returning), data/kenpom/history/height_<S>.csv.
Usage: python3 data/research/falling_knife/falling_knife.py"""
import numpy as np, pandas as pd

rows = []
for S in (2025, 2026):
    R = pd.read_csv(f'data/research/prior_pull/preds_{S}.csv')
    R = R[R.close.notna() & (R.date < f'{S - 1}-12-01')]
    R = R[R.open.isna() | ((R.open - R.close).abs() < 6)]
    C = pd.read_csv(f'data/kenpom/history/height_{S}.csv').set_index('TeamName').Continuity
    for side, sg in (('home', 1), ('away', -1)):
        o = 'away' if side == 'home' else 'home'
        d = pd.DataFrame({'season': S, 'date': R.date, 'team': R[side], 'opp': R[o], 'n': R[f'n_{side}'], 'n_opp': R[f'n_{o}'],
                          'mv': R[f'mv_base_{side}'], 'mv_opp': R[f'mv_base_{o}'],
                          'line': sg * R.close,                       # team's spread (+ = dog)
                          'ats_close': sg * (R.margin + R.close), 'vs_model': sg * (R.margin - R.pred_base),
                          'vs_prior': sg * (R.margin - R.pred_prior)})
        d['cont'] = d.team.map(C)
        rows.append(d)
D = pd.concat(rows, ignore_index=True)
D = D[D.n.between(3, 8)].copy()
D['lam'] = D.n / (D.n + 8); D['sig'] = D.mv / D.lam                 # in-season reading vs prior, rating pts
print(f'{len(D)} team-games, Nov, teams with 3-8 games; continuity matched {D.cont.notna().mean():.0%}')


def reg(df, y, xs):
    X = np.c_[df[xs].values, np.ones(len(df))]; co = np.linalg.lstsq(X, df[y], rcond=None)[0]
    e = df[y] - X @ co; se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * e.var())
    return ' '.join(f'{x} {c:+.2f} ({s:.2f})' for x, c, s in zip(xs, co, se))


rec = lambda s: f'{(s > 0).sum()}-{(s < 0).sum()} {(s > 0).sum() / max(1, (s != 0).sum()):.0%}'
print('\n== Slope of next-game result on the team move to date (team-games; + = falling teams keep falling)')
for y in ('ats_close', 'vs_model', 'vs_prior'):
    print(f'  {y:9s} on mv (move entering game): {reg(D, y, ["mv"])}')
print('  (vs_prior slope should be ~+1 x share of the move that is real; vs_model slope >0 means our move is too small)')

print('\n== By move bucket (move vs prior entering the game, pts): ATS vs close, mean vs close, mean vs our model')
D['b'] = pd.cut(D.mv, [-99, -3, -2, -1, 1, 2, 3, 99], labels=['<=-3', '-3..-2', '-2..-1', '-1..1', '1..2', '2..3', '>=3'])
print(D.groupby('b', observed=True).agg(n=('ats_close', 'size'), ats=('ats_close', rec), vs_close=('ats_close', 'mean'),
                                         vs_model=('vs_model', 'mean')).round(2).to_string())

print('\n== Fallers (move <= -2) by season')
f = D[D.mv <= -2]
for S in (2025, 2026):
    x = f[f.season == S]; print(f'  {S}: n {len(x)}, ATS vs close {rec(x.ats_close)}, vs close {x.ats_close.mean():+.2f}, vs model {x.vs_model.mean():+.2f}')

print('\n== Fallers as underdogs by line')
for lo, hi in ((0, 10), (10, 20), (20, 99)):
    x = f[(f.line > lo) & (f.line <= hi)] if lo else f[f.line <= 10]
    if lo == 0: x = f[(f.line > 0) & (f.line <= 10)]
    print(f'  dog +{lo}-{hi}: n {len(x)}, ATS {rec(x.ats_close)}, vs close {x.ats_close.mean():+.2f}, vs model {x.vs_model.mean():+.2f}')
x = f[f.line <= 0]; print(f'  favorite: n {len(x)}, ATS {rec(x.ats_close)}, vs close {x.ats_close.mean():+.2f}, vs model {x.vs_model.mean():+.2f}')

print('\n== Continuity interaction (low = bottom third of D-I continuity that season)')
D['lowc'] = D.groupby('season').cont.transform(lambda s: s <= s.quantile(1 / 3))
for lab, m in (('low continuity', D.lowc), ('mid/high', ~D.lowc)):
    x = D[m & D.cont.notna()]
    print(f'  {lab:15s} n {len(x)}: ats_close on mv {reg(x, "ats_close", ["mv"])} | vs_model on mv {reg(x, "vs_model", ["mv"])}')
    y = x[x.mv <= -2]; print(f'     fallers (mv<=-2): n {len(y)}, ATS {rec(y.ats_close)}, vs close {y.ats_close.mean():+.2f}, vs model {y.vs_model.mean():+.2f}')
D['mvxlow'] = D.mv * D.lowc
print(f'  pooled with interaction: ats_close {reg(D[D.cont.notna()], "ats_close", ["mv", "mvxlow"])}')
print(f'                           vs_model  {reg(D[D.cont.notna()], "vs_model", ["mv", "mvxlow"])}')

print('\n== Is the market more bearish than our model on fallers? (our team margin minus market team margin; + = market more bearish)')
for lab, x in (('fallers mv<=-2', f), ('mv<=-3', D[D.mv <= -3]), ('everyone', D)):
    print(f'  {lab:15s}: {(x.ats_close - x.vs_model).mean():+.2f}  (n {len(x)})')
