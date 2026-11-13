"""Big home favorites vs the close by week of the season (Jon's recollection, Nov 12, 2026: big dogs start hitting after week one).
Part 1: all home favorites by line band and week, from the stored lines (2023-24, 2024-25, 2025-26 Nov-Dec).
Part 2: the production model's model-on-dog 3+ edges at 20+ by week (prior_pull/preds_*.csv; 'week' there counts from the
first day with 20 games, so it runs ~3 days behind the lines table). Part 3: 2025-26 open->close move on 20+ favorites.
Usage: python3 data/research/prior_pull/bigdog_by_week.py"""
import pandas as pd, numpy as np
rows = []
for S in (2024, 2025, 2026):
    L = pd.read_csv(f'data/backtest/lines_{S}.csv'); G = pd.read_csv(f'data/backtest/games_{S}.csv')
    di = set(G.team) | set(G.opp); neu = G.drop_duplicates('gameId').set_index('gameId').neutral
    L = L[L.spread_close.notna() & L.homeScore.notna() & L.homeTeam.isin(di) & L.awayTeam.isin(di)].copy()
    L = L[~L.gameId.map(neu).fillna(False).astype(bool)]
    L['date'] = (pd.to_datetime(L.startDate) - pd.Timedelta(hours=5)).dt.date
    d0 = L.date.min(); L['week'] = [(d - d0).days // 7 + 1 for d in L.date]
    L['margin'] = L.homeScore - L.awayScore
    L['fav_cover'] = np.where(L.spread_close < 0, L.margin + L.spread_close, -(L.margin + L.spread_close))
    L['line'] = L.spread_close.abs(); L['season'] = S; rows.append(L)
A = pd.concat(rows); A = A[A.week <= 8]
rec = lambda s: (lambda w, l: f'{w}-{l} {w / (w + l):.0%}' if w + l else '-')((s.fav_cover > 0).sum(), (s.fav_cover < 0).sum())
for lo, hi, lab in [(20, 99, '20+'), (15, 20, '15-20'), (10, 15, '10-15')]:
    print(f'\n== home favorites {lab}: FAVORITE vs close by week (week 1 = opening week)')
    s = A[(A.line >= lo) & (A.line < hi)]
    t = s.groupby('week').apply(lambda x: pd.Series({'n': len(x), 'fav': rec(x), 'fav margin-line': round(x.fav_cover.mean(), 2)}))
    for S in (2024, 2025, 2026): t[str(S)] = s[s.season == S].groupby('week').apply(rec)
    print(t.to_string())
R = pd.concat([pd.read_csv(f'data/research/prior_pull/preds_{s}.csv').assign(season=s) for s in (2025, 2026)])
R = R[(~R.neutral) & R.close.notna()]; R = R[R.open.isna() | ((R.open - R.close).abs() < 6)]
R['date'] = pd.to_datetime(R.date); R['week'] = R.groupby('season').date.transform(lambda d: (d - d.min()).dt.days // 7 + 1)
R['mkt'] = -R.close; R['edge'] = R.pred_base + R.close; R['res'] = np.sign(R.edge) * (R.margin + R.close)
dog = (np.sign(R.edge) != np.sign(R.mkt)) & (R.edge.abs() >= 3)
print('\n== production model, home favorites 20+: model-on-DOG 3+ edges by week (2024-25 + 2025-26)')
print(R[(R.mkt.abs() >= 20) & dog].groupby('week').apply(lambda x: f'{(x.res > 0).sum()}-{(x.res < 0).sum()}').to_string())
o = R[(R.season == 2026) & R.open.notna() & (R.mkt.abs() >= 20)].copy(); o['fav_move'] = np.sign(o.mkt) * (o.open - o.close)
print('\n== 2025-26, home favorites 20+: open->close move toward the favorite, by week'); print(o.groupby('week').fav_move.agg(['count', 'mean']).round(2).to_string())
