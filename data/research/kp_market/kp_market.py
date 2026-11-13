"""Discord claim (Nov 13, 2026): (1) the market is more detached from KenPom this November than in past years; (2) KenPom
adjusts faster for low-continuity ("year zero") teams; (3) the market doesn't follow KenPom on those teams.
KenPom spread (home margin) = (AdjEM_h - AdjEM_a) x mean(AdjTempo)/100 + KenPom HCA (0 neutral), from the latest snapshot on
or before the game date. Past seasons: weekly archive snapshots (data/kenpom/history/archive_*.csv), preseason files, closes
from the backtest store. This season: daily ratings files (Nov 6+), preseason = prior file's kp column, closes from grade_log.
Usage: python3 data/research/kp_market/kp_market.py"""
import glob, json, numpy as np, pandas as pd
HCA = dict(pd.read_csv('data/kp_hca.csv')[['team', 'hca']].values)
X = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}; X.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})


def snaps(S):
    out = {}
    if S == 2027:
        for f in sorted(glob.glob('data/kenpom/ratings_2026-11-*.csv')):
            out[f[-14:-4]] = pd.read_csv(f).set_index('TeamName')[['AdjEM', 'AdjTempo']]
        p = pd.read_csv('data/prior_2026-27.csv').set_index('team'); pre = pd.DataFrame({'AdjEM': p.kp, 'AdjTempo': p.adj_tempo})
        cont = pd.read_csv('data/kenpom/height_2026-11-10.csv').set_index('TeamName').Continuity
    else:
        for f in sorted(glob.glob(f'data/kenpom/history/archive_{S - 1}-1[12]-*.csv')):
            out[f[-14:-4]] = pd.read_csv(f).set_index('TeamName')[['AdjEM', 'AdjTempo']]
        pre = pd.read_csv(f'data/kenpom/preseason_{S}.csv').set_index('TeamName')[['AdjEM', 'AdjTempo']]
        cont = pd.read_csv(f'data/kenpom/history/height_{S}.csv').set_index('TeamName').Continuity
    return out, pre, cont


def games(S):
    """home-row games: date, home, away, neutral, margin, close (KenPom names)"""
    if S == 2027:
        g = pd.read_csv('data/grades/grade_log.csv', encoding='utf-8-sig')
        g = g[(g.ref - g.close).abs() < 6]
        return pd.DataFrame({'date': g.date, 'home': g.home, 'away': g.away, 'neutral': g.venue != 'H', 'margin': g.home_margin, 'close': g.close})
    T = pd.read_csv(f'data/backtest/games_{S}.csv'); L = pd.read_csv(f'data/backtest/lines_{S}.csv').set_index('gameId')
    T = T[(T.isHome == True) & T.pts.notna()].drop_duplicates('gameId')
    T['close'] = T.gameId.map(L.spread_close); T['open'] = T.gameId.map(L.spread_open)
    T = T[T.close.notna() & (T.open.isna() | ((T.open - T.close).abs() < 6))]
    return pd.DataFrame({'date': T.date, 'home': T.team.map(lambda t: X.get(t, t)), 'away': T.opp.map(lambda t: X.get(t, t)),
                         'neutral': T.neutral.fillna(False).astype(bool), 'margin': T.pts - T.opp_pts, 'close': T.close})


def spread(R, h, a, neutral):
    return (R.AdjEM[h] - R.AdjEM[a]) * (R.AdjTempo[h] + R.AdjTempo[a]) / 200 + (0 if neutral else HCA.get(h, 2.84))


def build(S, weekly=None):
    sn, pre, cont = snaps(S); G = games(S); rows = []
    keys = sorted(sn) if weekly is None else weekly
    for g in G.itertuples():
        k = [d for d in keys if d <= g.date]
        if not k or g.home not in pre.index or g.away not in pre.index: continue
        R = sn[k[-1]]
        if g.home not in R.index or g.away not in R.index: continue
        rows.append(dict(season=S, date=g.date, snap=k[-1], home=g.home, away=g.away, mkt=-g.close, margin=g.margin,
                         kp=spread(R, g.home, g.away, g.neutral), pre=spread(pre, g.home, g.away, g.neutral),
                         c_h=cont.get(g.home, np.nan), c_a=cont.get(g.away, np.nan)))
    D = pd.DataFrame(rows); D['stale'] = (pd.to_datetime(D.date) - pd.to_datetime(D.snap)).dt.days
    return D


def reg(y, Xc, names):
    A = np.c_[np.column_stack(Xc), np.ones(len(y))]; co = np.linalg.lstsq(A, y, rcond=None)[0]
    e = y - A @ co; se = np.sqrt(np.diag(np.linalg.inv(A.T @ A)) * e.var())
    return ' '.join(f'{n} {c:+.2f} ({s:.2f})' for n, c, s in zip(names, co, se))


# validate the spread formula against FanMatch this season
D27 = build(2027)
fm = pd.concat([pd.read_csv(f) for f in glob.glob('data/kenpom/fanmatch_2026-11-*.csv')])
fm['fm'] = fm.HomePred - fm.VisitorPred
j = D27[D27.stale == 0].merge(fm[['DateOfGame', 'Home', 'Visitor', 'fm']], left_on=['date', 'home', 'away'], right_on=['DateOfGame', 'Home', 'Visitor'])
print(f'formula vs FanMatch (same-day snapshot, n {len(j)}): mean diff {(j.kp - j.fm).mean():+.2f}, mean |diff| {(j.kp - j.fm).abs().mean():.2f} (FanMatch is rounded to whole points)')

print('\n== (1) Is the market further from KenPom this year? Same snapshot timing in each season (a ~Nov 6-7 snapshot for the next 4 days,')
print('   a ~Nov 10-11 snapshot for the next 3 days). mean |market - KenPom now|, |market - KenPom preseason|, |KenPom now - preseason|')
W = {2025: [('2024-11-07', '2024-11-07', '2024-11-10'), ('2024-11-11', '2024-11-11', '2024-11-13')],
     2026: [('2025-11-06', '2025-11-06', '2025-11-09'), ('2025-11-10', '2025-11-10', '2025-11-12')],
     2027: [('2026-11-06', '2026-11-06', '2026-11-09'), ('2026-11-10', '2026-11-10', '2026-11-12')]}
ALL = {}
for S in (2025, 2026, 2027):
    D = build(S, weekly=[w[0] for w in W[S]]); ALL[S] = D
    for snap, a, b in W[S]:
        for lab, x in (('all lines', D[(D.snap == snap) & D.date.between(a, b)]),):
            for cut, y in (('all', x), ('<15', x[x.mkt.abs() < 15]), ('15+', x[x.mkt.abs() >= 15])):
                print(f'  {S - 1}-{str(S)[2:]} snap {snap[5:]} games {a[5:]}..{b[5:]} lines {cut:3s}: n {len(y):3d}  |mkt-KP| {(y.mkt - y.kp).abs().mean():.2f}  |mkt-pre| {(y.mkt - y.pre).abs().mean():.2f}  '
                      f'|KP-pre| {(y.kp - y.pre).abs().mean():.2f}  bias mkt-KP toward fav {(np.sign(y.mkt) * (y.mkt - y.kp)).mean():+.2f}')
x = D27[(D27.stale == 0) & (D27.date >= '2026-11-10')]
print(f'  this season, same-day KenPom, Nov 10-12: n {len(x)}  |mkt-KP| {(x.mkt - x.kp).abs().mean():.2f}  (<15: {(x.mkt - x.kp)[x.mkt.abs() < 15].abs().mean():.2f})')

print('\n== (2) Does KenPom move faster for low-continuity teams? Team level: KenPom AdjEM move from preseason vs the team\'s average')
print('   result vs KenPom-preseason expectation (pts/game, D-I games before the snapshot). Slope by continuity tercile.')
def team_level(S, snapdate):
    sn, pre, cont = snaps(S); R = sn[snapdate]
    if S == 2027: T = pd.read_csv('data/games_2026-27.csv')
    else: T = pd.read_csv(f'data/backtest/games_{S}.csv')
    T = T[T.pts.notna() & (T.date < snapdate)].copy(); T['t'] = T.team.map(lambda t: X.get(t, t)); T['o'] = T.opp.map(lambda t: X.get(t, t))
    T = T[T.t.isin(pre.index) & T.o.isin(pre.index)]
    neu = T.neutral.fillna(False).astype(bool)
    exp = [spread(pre, t, o, n) if h else -spread(pre, o, t, n) for t, o, h, n in zip(T.t, T.o, T.isHome == True, neu)]
    T['res'] = np.clip(T.pts - T.opp_pts - np.array(exp), -30, 30)
    a = T.groupby('t').res.agg(['mean', 'size'])
    return pd.DataFrame({'season': S, 'move': (R.AdjEM - pre.AdjEM).reindex(a.index), 'res': a['mean'], 'n': a['size'], 'cont': cont.reindex(a.index)}).dropna()
TL = pd.concat([team_level(2025, '2024-11-18'), team_level(2026, '2025-11-17'), team_level(2027, '2026-11-13')])
TL['terc'] = TL.groupby('season').cont.transform(lambda s: pd.qcut(s.rank(method='first'), 3, labels=['low', 'mid', 'high']))
for S in (2025, 2026, 2027):
    t = TL[(TL.season == S) & (TL.n >= 2)]
    print(f'  {S - 1}-{str(S)[2:]} (n {len(t)}, median games {t.n.median():.0f}): ' + ' | '.join(
        f'{k}: slope {np.polyfit(v.res, v.move, 1)[0]:.3f}, mean |move| {v.move.abs().mean():.2f}' for k, v in t.groupby('terc', observed=True)))
    t = t.assign(low=(t.terc == 'low').astype(float), zero=(t.cont <= 0.02).astype(float))
    print('     pooled: move ~ ' + reg(t.move.values, [t.res, t.res * t.low, t.res * (t.n - t.n.mean())], ['res', 'res x low-continuity', 'res x games']))
    print('     pooled: move ~ ' + reg(t.move.values, [t.res, t.res * t.zero, t.res * (t.n - t.n.mean())], ['res', 'res x continuity<=2%', 'res x games']))

print('\n== (3) Does the market follow KenPom\'s moves, and who is right? November games (snapshot <= 6 days old).')
for S in (2025, 2026, 2027):
    D = build(S); D = D[(D.date.str[5:7] == '11') & (D.stale <= 6)].copy()
    D['minc'] = D[['c_h', 'c_a']].min(axis=1); q = pd.concat([D.c_h, D.c_a]).quantile(1 / 3)
    D['kpmv'] = D.kp - D.pre; D['mkmv'] = D.mkt - D.pre; D['gap'] = D.kp - D.mkt; D['y'] = D.margin - D.mkt
    for lab, x in (('all games', D), ('a low-continuity team involved', D[D.minc <= q]), ('both teams mid/high continuity', D[D.minc > q]), ('a team with continuity <= 2%', D[D.minc <= 0.02])):
        if len(x) < 25: print(f'  {S - 1}-{str(S)[2:]} {lab}: n {len(x)} (too few)'); continue
        fol = np.polyfit(x.kpmv, x.mkmv, 1)[0]
        r = np.sign(x.gap) * x.y; b2 = x.gap.abs() >= 2; b3 = x.gap.abs() >= 3
        rec = lambda m: f'{int((r[m] > 0).sum())}-{int((r[m] < 0).sum())}'
        print(f'  {S - 1}-{str(S)[2:]} {lab:32s} n {len(x):4d} | mean |KP move| {x.kpmv.abs().mean():.2f} | market follows {fol:.2f} of it | '
              f'(result - market) on (KP - market): {reg(x.y.values, [x.gap], ["slope"]).split(" const")[0]} | KP side vs close, gap 2+: {rec(b2)}, 3+: {rec(b3)}')
