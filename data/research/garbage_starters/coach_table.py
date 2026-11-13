"""Which coaches keep their better players on the floor in decided minutes? (Jon, Nov 13, 2026.)
This season, D-I games the team WON with 4+ low-leverage game-minutes (low = min_raw - min_lev, data/rotation).
"Better players" = the team's top 5 by competitive (leverage-weighted) minutes over all its D-I games.
top5_share = their low-leverage minutes / (5 x low-leverage game-minutes): 100% = the top five never came out,
0% = they never played a decided minute. Writes coach_table_<date>.csv. Usage: python3 .../coach_table.py"""
import json, glob, pandas as pd, numpy as np
pg = pd.read_csv('data/rotation/player_games.csv'); tg = pd.read_csv('data/rotation/team_games.csv')
tg = tg[tg.reliable & tg.d1_game]; pg = pg.merge(tg[['gameId', 'team']], on=['gameId', 'team'])
pg['low'] = pg.min_raw - pg.min_lev
top = pg.groupby(['team', 'athleteId']).min_lev.sum().reset_index().sort_values('min_lev', ascending=False).groupby('team').head(5)
top['top5'] = True; pg = pg.merge(top[['team', 'athleteId', 'top5']], how='left', on=['team', 'athleteId']).fillna({'top5': False})
tg['low_game_min'] = (tg.team_min_raw - tg.team_min_lev) / 5
W = tg[(tg.final_margin > 0) & (tg.low_game_min >= 4)]
p = pg.merge(W[['gameId', 'team', 'low_game_min']], on=['gameId', 'team'])
t5 = p[p.top5].groupby('team').low.sum()
o = W.groupby('team').agg(games=('gameId', 'size'), decided_min=('low_game_min', 'sum'), avg_margin=('final_margin', 'mean')).join(t5.rename('top5_low'))
o['top5_share'] = o.top5_low / (5 * o.decided_min)
X = {v.strip(): k for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
K = pd.read_csv(sorted(glob.glob('data/kenpom/ratings_2026-*.csv'))[-1]).set_index('TeamName')
INV = {k: v for v, k in X.items()}
o['kp'] = [INV.get(t, t) for t in o.index]; o['coach'] = o.kp.map(K.Coach); o['kp_rank'] = o.kp.map(K.RankAdjEM)
o = o.reset_index().sort_values('top5_share', ascending=False)
o[['kp', 'coach', 'kp_rank', 'games', 'decided_min', 'avg_margin', 'top5_share']].round(3).to_csv('data/research/garbage_starters/coach_table_2026-11-13.csv', index=False)
q = o[o.decided_min >= 15]
print(f'teams with a qualifying win: {len(o)}; with 15+ decided game-minutes: {len(q)}; D-I mean share {np.average(q.top5_share, weights=q.decided_min):.1%}; median {q.top5_share.median():.1%}')
f = lambda d: d[['kp', 'coach', 'kp_rank', 'games', 'decided_min', 'avg_margin', 'top5_share']].round({'decided_min': 0, 'avg_margin': 0, 'top5_share': 3}).to_string(index=False)
print('KEEP THEM IN'); print(f(q.head(20))); print('PULL THEM'); print(f(q.tail(20)))
print('TOP-60 KENPOM'); print(f(q[q.kp_rank <= 60].sort_values('top5_share', ascending=False)))
