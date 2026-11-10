"""Do big favorites with a better deep bench cover more? (Nov 10, Jon's Rutgers -24 question)
Bench quality = minutes-weighted per-40 win shares of a team's players ranked 6-8 and 9-10 by season minutes (CBBD season stats).
Sample: closing favorites of 15+ (consensus median), 2024-25 and 2025-26. Outcome: ATS margin; mechanism: margin change from 8:00 left to final
when the favorite leads by 15+ at 8:00. Controls: line and the favorite's top-5 quality. Bar (same as latefav): |t| > 2.5, same sign both seasons.
Caveat: season stats include the game itself, and deep-bench stats are piled up in blowouts, so leakage biases TOWARD finding an effect."""
import pandas as pd, numpy as np
import statsmodels.formula.api as smf
out = []
for season in [2025, 2026]:
    P = pd.read_csv(f'data/players/history/season_stats_{season}.csv')
    P = P[P.minutes > 0].copy(); P['ws40'] = P['winShares.totalPer40']
    rows = []
    for t, g in P.groupby('team'):
        g = g.sort_values('minutes', ascending=False).reset_index(drop=True)
        if len(g) < 10: continue
        w = lambda a, b: np.average(g.ws40[a:b], weights=g.minutes[a:b])
        rows.append(dict(team=t, top5=w(0, 5), s68=w(5, 8), s910=w(8, 10), share910=g.minutes[8:10].sum() / g.minutes.sum()))
    T = pd.DataFrame(rows).set_index('team')
    for c in ['top5', 's68', 's910']: T[c + '_z'] = (T[c] - T[c].mean()) / T[c].std()
    G = pd.read_csv(f'data/research/latefav/games_{season}.csv'); L = pd.read_csv(f'data/research/latefav/late_{season}.csv')
    G = G.dropna(subset=['spread_home']); G = G[G.spread_home.abs() >= 15]
    G['fav'] = np.where(G.spread_home < 0, G.home, G.away); G['dog'] = np.where(G.spread_home < 0, G.away, G.home)
    G['line'] = G.spread_home.abs(); G['fmargin'] = np.where(G.spread_home < 0, G.home_pts - G.away_pts, G.away_pts - G.home_pts)
    G['ats'] = G.fmargin - G.line; G = G[G.fav.isin(T.index) & G.dog.isin(T.index)]
    for c in ['top5_z', 's68_z', 's910_z', 'share910']: G[c] = G.fav.map(T[c]); G['dog_' + c] = G.dog.map(T[c])
    G = G.merge(L[['gameId', 'm8', 'final', 'reg_end']], on='gameId', how='left')
    sgn = np.where(G.spread_home < 0, 1, -1); G['lead8'] = sgn * G.m8; G['chg'] = sgn * (G.reg_end - G.m8)
    G['season'] = season; out.append(G)
D = pd.concat(out)
def fit(f, d, lab):
    m = smf.ols(f, d).fit(); r = {k: f"{m.params[k]:+.2f} [t {m.tvalues[k]:+.1f}]" for k in m.params.index if k.endswith('_z') or k == 'share910'}
    print(f'{lab:46s} n={int(m.nobs):5d}  ', r)
print('favorites of 15+:', D.groupby('season').size().to_dict(), '| cover rate', D.groupby('season').ats.apply(lambda s: round((s > 0).sum() / (s != 0).sum(), 3)).to_dict())
for s in [2025, 2026, None]:
    d = D if s is None else D[D.season == s]; lab = 'pooled' if s is None else str(s)
    fit('ats ~ line + top5_z + s68_z + s910_z + dog_s68_z + dog_s910_z', d, f'ATS margin, {lab}')
for s in [2025, 2026, None]:
    d = (D if s is None else D[D.season == s]); d = d[d.lead8 >= 15]; lab = 'pooled' if s is None else str(s)
    fit('chg ~ lead8 + line + top5_z + s68_z + s910_z + dog_s910_z', d, f'lead change 8:00->end, up 15+, {lab}')
# simple terciles of slots 9-10 for the favorite
D['t910'] = D.groupby('season').s910_z.transform(lambda s: pd.qcut(s, 3, labels=['weak', 'mid', 'strong']))
print(D.groupby(['season', 't910'], observed=True).agg(n=('ats', 'size'), cover=('ats', lambda s: round((s > 0).mean(), 3)), ats=('ats', 'mean'), line=('line', 'mean')).round(2).to_string())
