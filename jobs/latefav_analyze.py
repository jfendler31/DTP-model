"""Late-game favorite study: analysis of data/research/latefav/ (from jobs/latefav.py).

Pre-registered before the data came back (Nov 6 2026):
  Sample   closing favorites of 6 to 12 points (consensus median spread), both seasons, Nov-Mar.
  Traits   the favorite's PRE-GAME season-to-date turnover rate (TO / possession) and FT% (FTM / FTA),
           from its own earlier games only; at least 5 earlier games. Each standardized within season.
           sloppy = z(TO rate) - z(FT%)   (high = turns it over and misses free throws)
  H1 (outcomes)  sloppier favorites cover less often than cleaner ones, while winning at least as often
                 as their line implies. Primary read: win residual (won - line-implied win prob) and cover
                 residual (covered - 0.5) by sloppy tercile, and regressions of each on sloppy, TO and FT.
  H2 (mechanism) favorites leading by 4-14 with 4:00 left in regulation: how much of the lead is lost by
                 the end of regulation, by sloppiness, controlling for the lead and the line.
  Bar      |t| > 2.5 and the same sign in both seasons, per Methodology_Rules.md. Anything else is
           labelled exploratory.

Line-implied win probability: Phi(line / sd), sd fitted by maximum likelihood on ALL closing favorites
of 1-25 points in the same season (so the 6-12 group is judged against the market-wide conversion).

Usage: python jobs/latefav_analyze.py   -> prints the report and writes data/research/latefav/results.md
"""
import sys, math
import numpy as np, pandas as pd
from scipy.stats import norm
from scipy.optimize import minimize_scalar

D = 'data/research/latefav'
SEASONS = [int(x) for x in __import__('os').environ.get('LF_SEASONS', '2025 2026').split()]
LO, HI, MIN_PRIOR = 6.0, 12.0, 5


def load(season):
    g = pd.read_csv(f'{D}/games_{season}.csv')
    l = pd.read_csv(f'{D}/late_{season}.csv')
    g = g.dropna(subset=['home_pts', 'away_pts'])
    for c in ['home_poss', 'away_poss', 'home_to', 'away_to', 'home_fta', 'away_fta', 'home_ftm', 'away_ftm']:
        g[c] = pd.to_numeric(g[c], errors='coerce')
    g['date'] = pd.to_datetime(g['date'])
    return g, l


def pregame_traits(g):
    """season-to-date TO rate and FT% for each team BEFORE each game (own earlier games only)"""
    rows = []
    for side, opp in (('home', 'away'), ('away', 'home')):
        rows.append(pd.DataFrame(dict(gameId=g.gameId, date=g.date, team=g[side], side=side,
                                      poss=g[f'{side}_poss'], to=g[f'{side}_to'],
                                      fta=g[f'{side}_fta'], ftm=g[f'{side}_ftm'])))
    t = pd.concat(rows).sort_values(['team', 'date', 'gameId'])
    for c in ['poss', 'to', 'fta', 'ftm']:
        t[f'c_{c}'] = t.groupby('team')[c].transform(lambda s: s.fillna(0).cumsum().shift(1).fillna(0))
    t['n_prior'] = t.groupby('team').cumcount()
    t['to_rate'] = t.c_to / t.c_poss.replace(0, np.nan)
    t['ft_pct'] = t.c_ftm / t.c_fta.replace(0, np.nan)
    return t[['gameId', 'side', 'n_prior', 'to_rate', 'ft_pct']]


def fit_sd(fav):
    """MLE sd for P(favorite wins) = Phi(line / sd)"""
    L, w = fav.line.to_numpy(), fav.win.to_numpy()
    nll = lambda s: -np.sum(w * norm.logcdf(L / s) + (1 - w) * norm.logsf(L / s))
    return minimize_scalar(nll, bounds=(5, 20), method='bounded').x


def build(season):
    g, late = load(season)
    g = g.dropna(subset=['spread_home'])
    g = g[g.spread_home != 0].copy()
    g['fav_home'] = g.spread_home < 0
    g['line'] = g.spread_home.abs()
    hm = g.home_pts - g.away_pts
    g['fav_margin'] = np.where(g.fav_home, hm, -hm)
    g['win'] = (g.fav_margin > 0).astype(int)
    g['cover'] = np.where(g.fav_margin > g.line, 1.0, np.where(g.fav_margin < g.line, 0.0, np.nan))
    g['ats'] = g.fav_margin - g.line
    tr = pregame_traits(pd.read_csv(f'{D}/games_{season}.csv').assign(date=lambda x: pd.to_datetime(x.date))
                        .dropna(subset=['home_pts', 'away_pts']))
    # attach favorite's traits
    th = tr[tr.side == 'home'].set_index('gameId'); ta = tr[tr.side == 'away'].set_index('gameId')
    for c in ['n_prior', 'to_rate', 'ft_pct']:
        g[f'fav_{c}'] = np.where(g.fav_home, g.gameId.map(th[c]), g.gameId.map(ta[c]))
    fav_all = g[(g.line >= 1) & (g.line <= 25)]
    sd = fit_sd(fav_all)
    g['p_line'] = norm.cdf(g.line / sd)
    g['win_resid'] = g.win - g.p_line
    # late margins (favorite view)
    late = late.copy()
    late['gameId'] = late.gameId.astype(g.gameId.dtype)
    g = g.merge(late[['gameId', 'm8', 'm4', 'm2', 'reg_end', 'final', 'periods', 'h_late_to', 'a_late_to',
                      'h_late_fta', 'a_late_fta', 'h_late_ftm', 'a_late_ftm']], on='gameId', how='left')
    sgn = np.where(g.fav_home, 1, -1)
    for c in ['m8', 'm4', 'm2', 'reg_end']:
        g[f'fav_{c}'] = g[c] * sgn
    g['fav_late_to'] = np.where(g.fav_home, g.h_late_to, g.a_late_to)
    g['fav_late_fta'] = np.where(g.fav_home, g.h_late_fta, g.a_late_fta)
    g['fav_late_ftm'] = np.where(g.fav_home, g.h_late_ftm, g.a_late_ftm)
    g['late_change'] = g.fav_reg_end - g.fav_m4
    g['season'] = season
    s = g[(g.line >= LO) & (g.line <= HI) & (g.fav_n_prior >= MIN_PRIOR)].dropna(subset=['fav_to_rate', 'fav_ft_pct']).copy()
    s['z_to'] = (s.fav_to_rate - s.fav_to_rate.mean()) / s.fav_to_rate.std()
    s['z_ft'] = (s.fav_ft_pct - s.fav_ft_pct.mean()) / s.fav_ft_pct.std()
    s['sloppy'] = s.z_to - s.z_ft
    s['sloppy'] = (s.sloppy - s.sloppy.mean()) / s.sloppy.std()
    s['terc'] = pd.qcut(s.sloppy, 3, labels=['clean', 'middle', 'sloppy'])
    return g, s, sd


def ols(y, X):
    X = np.column_stack([np.ones(len(X))] + [X[:, i] for i in range(X.shape[1])])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    n, k = X.shape
    # HC1 robust SE
    XtX = np.linalg.inv(X.T @ X)
    meat = (X * r[:, None] ** 2).T @ X
    V = XtX @ meat @ XtX * n / (n - k)
    return b, np.sqrt(np.diag(V))


def reg(df, y, xs):
    d = df.dropna(subset=[y] + xs)
    b, se = ols(d[y].to_numpy(float), d[xs].to_numpy(float))
    return {x: (b[i + 1], se[i + 1], b[i + 1] / se[i + 1]) for i, x in enumerate(xs)}, len(d)


def fmt(v, nd=1): return '—' if v is None or (isinstance(v, float) and math.isnan(v)) else f'{v:.{nd}f}'


def main():
    out, S = [], []
    out.append('# Late-game favorite study — results\n')
    for season in SEASONS:
        g, s, sd = build(season)
        S.append(s)
        out.append(f'## {season - 1}-{str(season)[2:]}\n')
        out.append(f'Closing favorites of {LO:g}-{HI:g} with {MIN_PRIOR}+ prior games: **{len(s)}** '
                   f'(of {int(((g.line >= LO) & (g.line <= HI)).sum())} in range). Market-wide win conversion sd = {sd:.1f}. '
                   f'Play-by-play matched: {s.fav_m4.notna().sum()}.\n')
        out.append('| Favorite type | n | Won | Line-implied | Win vs line | Covered | Avg ATS margin |')
        out.append('|---|---|---|---|---|---|---|')
        for t, d in s.groupby('terc', observed=True):
            out.append(f'| {t} | {len(d)} | {100*d.win.mean():.1f}% | {100*d.p_line.mean():.1f}% | '
                       f'{100*d.win_resid.mean():+.1f} pts | {100*d.cover.mean():.1f}% | {d.ats.mean():+.1f} |')
        out.append('')
        r1, n1 = reg(s, 'win_resid', ['sloppy'])
        r2, n2 = reg(s, 'cover', ['sloppy'])
        r3, n3 = reg(s, 'ats', ['sloppy'])
        r4, _ = reg(s, 'win_resid', ['z_to', 'z_ft'])
        r5, _ = reg(s, 'cover', ['z_to', 'z_ft'])
        out.append('Per 1 SD of sloppiness (robust t in brackets):')
        out.append(f'- win vs line: {100*r1["sloppy"][0]:+.1f} pts [t {r1["sloppy"][2]:+.1f}]')
        out.append(f'- cover rate: {100*r2["sloppy"][0]:+.1f} pts [t {r2["sloppy"][2]:+.1f}]')
        out.append(f'- ATS margin: {r3["sloppy"][0]:+.2f} [t {r3["sloppy"][2]:+.1f}]')
        out.append(f'- split: win vs line TO {100*r4["z_to"][0]:+.1f} [t {r4["z_to"][2]:+.1f}], '
                   f'FT {100*r4["z_ft"][0]:+.1f} [t {r4["z_ft"][2]:+.1f}]; '
                   f'cover TO {100*r5["z_to"][0]:+.1f} [t {r5["z_to"][2]:+.1f}], FT {100*r5["z_ft"][0]:+.1f} [t {r5["z_ft"][2]:+.1f}]\n')
        m = s[(s.fav_m4 >= 4) & (s.fav_m4 <= 14)]
        out.append(f'**Mechanism:** favorite ahead by 4-14 with 4:00 left: {len(m)} games.\n')
        out.append('| Favorite type | n | Lead at 4:00 | Lead change to end of regulation | Lost the game | Late TOs | Late FT% (FTA) |')
        out.append('|---|---|---|---|---|---|---|')
        for t, d in m.groupby('terc', observed=True):
            fta = d.fav_late_fta.sum()
            out.append(f'| {t} | {len(d)} | {d.fav_m4.mean():.1f} | {d.late_change.mean():+.2f} | {100*(1-d.win.mean()):.1f}% | '
                       f'{d.fav_late_to.mean():.2f} | {100*d.fav_late_ftm.sum()/max(fta,1):.1f}% ({fta/len(d):.1f}/g) |')
        r6, n6 = reg(m, 'late_change', ['sloppy', 'fav_m4', 'line'])
        r7, _ = reg(m, 'late_change', ['z_to', 'z_ft', 'fav_m4', 'line'])
        out.append(f'\nLead change per 1 SD sloppiness (controls: lead at 4:00, line): {r6["sloppy"][0]:+.2f} pts '
                   f'[t {r6["sloppy"][2]:+.1f}], n {n6}; split TO {r7["z_to"][0]:+.2f} [t {r7["z_to"][2]:+.1f}], '
                   f'FT {r7["z_ft"][0]:+.2f} [t {r7["z_ft"][2]:+.1f}]\n')
    A = pd.concat(S)
    out.append('## Both seasons pooled\n')
    r1, n = reg(A, 'win_resid', ['sloppy']); r2, _ = reg(A, 'cover', ['sloppy']); r3, _ = reg(A, 'ats', ['sloppy'])
    out.append(f'n {n}. Per 1 SD sloppiness: win vs line {100*r1["sloppy"][0]:+.1f} pts [t {r1["sloppy"][2]:+.1f}], '
               f'cover {100*r2["sloppy"][0]:+.1f} pts [t {r2["sloppy"][2]:+.1f}], ATS {r3["sloppy"][0]:+.2f} [t {r3["sloppy"][2]:+.1f}]\n')
    m = A[(A.fav_m4 >= 4) & (A.fav_m4 <= 14)]
    r6, n6 = reg(m, 'late_change', ['sloppy', 'fav_m4', 'line'])
    out.append(f'Mechanism pooled: lead change per 1 SD sloppiness {r6["sloppy"][0]:+.2f} [t {r6["sloppy"][2]:+.1f}], n {n6}\n')
    A.to_csv(f'{D}/sample_6to12.csv', index=False)
    txt = '\n'.join(out)
    open(f'{D}/results.md', 'w').write(txt)
    print(txt)


if __name__ == '__main__':
    main()
