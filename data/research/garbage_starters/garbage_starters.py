"""Do coaches who leave their starters in during garbage time grow leads late? (Jon, Nov 13, 2026 — ASU / Bennett.)
This season's D-I games (data/rotation/*.csv, data/roles/events_2026-11.csv.gz). Leader = team up 15+ with 10:00 left (no OT).
late = leader's margin change over the last 10 minutes. star_share = top-3 (by minutes) players' share of the game's
low-leverage minutes (min_raw - min_lev). Same-game star_share is endogenous (coaches leave starters in when the lead shrinks),
so the test uses the team's tendency = leave-one-out mean star_share in its OTHER games it won with 4+ low-leverage minutes.
Usage: python3 data/research/garbage_starters/garbage_starters.py"""
import numpy as np, pandas as pd
pg = pd.read_csv('data/rotation/player_games.csv'); tg = pd.read_csv('data/rotation/team_games.csv')
e = pd.read_csv('data/roles/events_2026-11.csv.gz', usecols=['gameId', 't', 'team', 'isHome', 'home_score', 'away_score'])
e = e.dropna(subset=['home_score', 'away_score']).sort_values(['gameId', 't'])
hm = e[e.isHome == True].groupby('gameId').team.first()
rows = []
for gid, g in e.groupby('gameId'):
    if gid not in hm.index or g.t.max() > 2400: continue
    x = g[g.t <= 1800]; m10 = (x.home_score.iloc[-1] - x.away_score.iloc[-1]) if len(x) else 0
    rows.append((gid, hm[gid], m10, g.home_score.iloc[-1] - g.away_score.iloc[-1]))
M = pd.DataFrame(rows, columns=['gameId', 'home', 'm10', 'mf'])
T = tg[tg.reliable].copy(); T['low_game_min'] = (T.team_min_raw - T.team_min_lev) / 5
pg['low'] = pg.min_raw - pg.min_lev
top = pg.sort_values('min_raw', ascending=False).groupby(['gameId', 'team']).head(3).groupby(['gameId', 'team']).low.sum().rename('top3_low')
T = T.join(top, on=['gameId', 'team']); T['star_share'] = T.top3_low / (3 * T.low_game_min)
B = T[(T.low_game_min >= 4) & (T.final_margin > 0)][['gameId', 'team', 'star_share']]
T = T.merge(M, on='gameId'); T['sg'] = np.where(T.team == T.home, 1, -1)
T['lead10'] = T.sg * T.m10; T['late'] = T.sg * (T.mf - T.m10)
L = T[(T.lead10 >= 15) & T.d1_game].copy()
print(f'same-game (endogenous): late on star_share, n {len(L)}:', np.polyfit(L.dropna(subset=["star_share"]).star_share, L.dropna(subset=["star_share"]).late, 1)[0].round(2))
L['tend'] = L.apply(lambda r: B[(B.team == r.team) & (B.gameId != r.gameId)].star_share.mean(), axis=1); L = L.dropna(subset=['tend'])
X = np.c_[L.tend, L.lead10, np.ones(len(L))]; co = np.linalg.lstsq(X, L.late, rcond=None)[0]
r = L.late - X @ co; se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * r.var())
print(f'n {len(L)}: late = {co[0]:.2f} (se {se[0]:.2f}) x tendency + {co[1]:.2f} x lead10')
L['q'] = pd.qcut(L.tend, 3, labels=['pulls starters', 'mid', 'keeps starters in'])
print(L.groupby('q', observed=True).agg(n=('late', 'size'), tend=('tend', 'mean'), lead10=('lead10', 'mean'), late=('late', 'mean')).round(2).to_string())
