"""Live scoreboard rating next to the production composite, same machinery as comp_vs_sb.py, for a card date.
Prints each team's composite move, scoreboard move and a blended move; and the card's games re-priced at the blend.
Usage: python3 data/research/comp_vs_sb/live_sb.py --date 2026-11-12 [--w 0.3] [--card cards/card_2026-11-12.csv]
"""
import sys, json, argparse, collections
import numpy as np, pandas as pd
sys.path.insert(0, 'jobs'); sys.path.insert(0, 'data/research/comp_vs_sb')
import ratings_core as rc
from ratings_core import build_games, load_factors
from comp_vs_sb import rate_with

ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--w', type=float, default=0.3)
ap.add_argument('--card'); a = ap.parse_args()
P = pd.read_csv('data/prior_2026-27.csv'); teams = list(P.team); tix = {t: i for i, t in enumerate(teams)}
zp = P.z_prior.to_numpy(float); n = len(teams)
XB = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
XB.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
TG = pd.read_csv('data/games_2026-27.csv'); TG = TG[(TG.date < a.date) & TG.pts.notna() & TG.opp_pts.notna()].copy()
TG['ftm'] = TG.pts - 2 * TG.p2m - 3 * TG.p3m; TG['opp_ftm'] = TG.opp_pts - 2 * TG.opp_p2m - 3 * TG.opp_p3m
G = build_games(TG, tix, XB, load_factors('data/pbp/game_factors.csv'), 'cw', collections.Counter())[0]
d1 = TG[TG.team.map(lambda t: XB.get(t, t) in tix) & TG.opp.map(lambda t: XB.get(t, t) in tix)]
L3 = d1.p3m.sum() / d1.p3a.sum(); LFT = d1.ftm.sum() / d1.fta.sum()
SB = pd.read_csv(f'data/ratings/scoreboard_{a.date}.csv'); FTT = dict(zip(SB.team, SB.ft_talent))
rowof = {int(g): (x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]) for g, x in TG.groupby('gameId')}
Gs = []
for x in G:
    r = rowof[x['gameId']]; poss = (r.poss + r.opp_poss) / 2
    ft, fo = FTT.get(teams[x['t']], LFT), FTT.get(teams[x['o']], LFT)
    net = (r.pts - r.opp_pts) - 3 * (r.p3m - L3 * r.p3a) + 3 * (r.opp_p3m - L3 * r.opp_p3a) - (r.ftm - ft * r.fta) + (r.opp_ftm - fo * r.opp_fta)
    Gs.append(dict(gameId=x['gameId'], date=x['date'], t=x['t'], o=x['o'], home=x['home'], sbm=100 * net / poss, n_poss=poss, src='box'))
oc = rate_with(G, n, zp, a.date, True, rc.PILLARS, rc.W, True)
os_ = rate_with(Gs, n, zp, a.date, False, ['sbm'], {'sbm': 1.0}, True)
T = pd.DataFrame(dict(team=teams, n=oc['N'].astype(int), mv_comp=9.5 * (oc['z_blend'] - zp), mv_sb=9.5 * (os_['z_blend'] - zp)))
T['mv_blend'] = (1 - a.w) * T.mv_comp + a.w * T.mv_sb; T['delta'] = T.mv_blend - T.mv_comp
R = pd.read_csv(f'data/ratings/ratings_{a.date}.csv').set_index('team')
chk = (T.set_index('team').mv_comp - R.move_pts).abs().max()
print(f'as of {a.date}: D-I 3P% {L3:.4f}; composite moves reproduce production to {chk:.2f} pts; w = {a.w}')
T = T.round(2); T.to_csv(f'data/research/comp_vs_sb/live_moves_{a.date}.csv', index=False)
if a.card:
    C = pd.read_csv(a.card); D = T.set_index('team').delta
    C['blend_shift'] = -(C.home.map(D).fillna(0) - C.away.map(D).fillna(0))
    C['blend_shift'] = np.where((C.size_curve == 1) & (C.model_home_spread.abs() > 10), C.blend_shift * 1.2, C.blend_shift)
    C['model_blend'] = (C.model_home_spread_adj + C.blend_shift).round(1)
    C['edge_card'] = (C.market_home_spread - C.model_home_spread_adj).round(1); C['edge_blend'] = (C.market_home_spread - C.model_blend).round(1)
    M = T.set_index('team')
    for s in ('home', 'away'):
        C[f'comp_{s}'] = C[s].map(M.mv_comp); C[f'sb_{s}'] = C[s].map(M.mv_sb)
    pd.set_option('display.width', 250)
    print(C[['away', 'home', 'market_home_spread', 'model_home_spread_adj', 'model_blend', 'edge_card', 'edge_blend',
             'comp_away', 'sb_away', 'comp_home', 'sb_home']].sort_values('edge_card', key=abs, ascending=False).to_string(index=False))
