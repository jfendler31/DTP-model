"""Scoreboard check (Nov 11, 2026): each team's D-I results vs the closing line, with shooting luck taken out,
next to the in-season composite move. Diagnostic only - it feeds game reads, not the ratings.

Per team-game (team's point of view; close = home spread, so the team's spread is close if home, -close if away):
  raw vs close   = margin + team spread
  3P luck        = 3*(3PM - L3*3PA) - 3*(opp 3PM - L3*opp 3PA)            L3 = this season's D-I 3P%
  FT luck        = (FTM - x_team*FTA) - (opp FTM - x_opp*opp FTA)          x = each team's FT talent estimate
  adj vs close   = raw - 3P luck - FT luck
Team FT talent x (Jon, Nov 11 - opponent FT% is pure noise to a defense, own FT% is about half signal by ~200 FTA):
  projection  = average of this season's players' prior-season FT%, weighted by their FTA so far this season, each shrunk toward the
                prior-season D-I rate with 40 pseudo-attempts; players with no D-I history at 0.706 (2025-26 new-player rate);
                +0.9 pt for year-over-year improvement. Tested 2024-25 -> 2025-26: r 0.43 with the actual season FT% (team FT% a
                year earlier: 0.24).
  x = w*observed + (1-w)*projection, w = FTA/(FTA+220)  (split-half reliability of own FT% ~0.45-0.5 at ~205 FTA, Nov-Dec 2024-26)
  Non-D-I opponents and teams with no player data use the league rate.
Output: data/ratings/scoreboard_<asof>.csv, one row per team: games with a close, raw vs close, 3P luck, FT luck (own, opp),
adj vs close (total and per game), lam x adj per game (what the scoreboard alone would move the rating), composite move;
and (Nov 12) sb_move_adj = the opponent-adjusted scoreboard move vs our prior (same rating machinery as the composite, one
luck-adjusted net-points pillar), blend_move = 0.7 composite + 0.3 sb_move_adj, blend_delta = blend - composite. Use sb_move_adj /
blend_move in reads (the backtest found results land ~30% of the way from the composite toward it); scoreboard_move is vs the closes.
Usage: python jobs/scoreboard.py [--date YYYY-MM-DD]   (date = ratings asof; default from data/ratings_current.csv)"""
import os, glob, json, argparse
import numpy as np, pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument('--date'); a = ap.parse_args()
R = pd.read_csv('data/ratings_current.csv'); asof = a.date or str(R['asof'].iloc[0])
xw = {k.strip(): v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
G = pd.read_csv('data/games_2026-27.csv'); G = G[G.date < asof].copy()
G['ftm'] = G.pts - 2 * G.p2m - 3 * G.p3m; G['opp_ftm'] = G.opp_pts - 2 * G.opp_p2m - 3 * G.opp_p3m
G['kt'] = G.team.map(lambda t: xw.get(t, '')); G['ko'] = G.opp.map(lambda t: xw.get(t, ''))
D1 = G[G.kt.ne('') & G.ko.ne('')]
L3 = D1.p3m.sum() / D1.p3a.sum(); LFT = D1.ftm.sum() / D1.fta.sum()

# ---- FT talent per team (CBBD names)
FTM, FTA = 'freeThrows.made', 'freeThrows.attempted'
hist = sorted(glob.glob('data/players/history/season_stats_*.csv'))[-1]           # last completed season
H = pd.read_csv(hist); lg_prev = H[FTM].sum() / H[FTA].sum()
pp = H.groupby('athleteId').agg(m=(FTM, 'sum'), a=(FTA, 'sum')); pp['proj'] = (pp.m + 40 * lg_prev) / (pp.a + 40)
P = pd.concat([pd.read_csv(f) for f in glob.glob('data/players/players_*.csv')]).drop_duplicates(subset=['gameId', 'athleteId'])
P = P[P.date_ET < asof]
P = P.join(pp.proj, on='athleteId'); P['proj'] = P.proj.fillna(0.706) + 0.009
P['w'] = P['freeThrows.attempted'].fillna(0)
proj = P.groupby('team').apply(lambda g: (g.proj * g.w).sum() / g.w.sum() if g.w.sum() > 0 else np.nan, include_groups=False)
obs = G.groupby('team').agg(ftm=('ftm', 'sum'), fta=('fta', 'sum'))
X = {}
for t, r in obs.iterrows():
    pr = proj.get(t, np.nan); pr = LFT if pd.isna(pr) else pr
    w = r.fta / (r.fta + 220.0); X[t] = w * (r.ftm / r.fta if r.fta else pr) + (1 - w) * pr

# ---- closing lines from the grade log (KenPom names)
GL = pd.read_csv('data/grades/grade_log.csv', encoding='utf-8-sig'); GL = GL[GL.close.notna() & (GL.date < asof)]
CL = {(r.date, r.away, r.home): float(r.close) for r in GL.itertuples()}
rows = []
for r in D1.itertuples():
    if (r.date, r.ko, r.kt) in CL: home, away = r.kt, r.ko          # grade log's orientation decides (neutral sites can differ)
    elif (r.date, r.kt, r.ko) in CL: home, away = r.ko, r.kt
    else: continue
    c = CL[(r.date, away, home)]
    spread = c if home == r.kt else -c
    raw = (r.pts - r.opp_pts) + spread
    l3 = 3 * (r.p3m - L3 * r.p3a) - 3 * (r.opp_p3m - L3 * r.opp_p3a)
    own = r.ftm - X.get(r.team, LFT) * r.fta; opp = r.opp_ftm - X.get(r.opp, LFT) * r.opp_fta
    rows.append(dict(team=r.kt, date=r.date, opp=r.ko, raw=raw, l3=l3, ft_own=own, ft_opp=-opp, adj=raw - l3 - (own - opp)))
T = pd.DataFrame(rows)
S = T.groupby('team').agg(games=('raw', 'size'), raw_vs_close=('raw', 'sum'), luck_3p=('l3', 'sum'), luck_ft_own=('ft_own', 'sum'),
                          luck_ft_opp=('ft_opp', 'sum'), adj_vs_close=('adj', 'sum')).reset_index()
S['adj_per_game'] = S.adj_vs_close / S.games
RR = R.set_index('team')
S['n_games'] = S.team.map(RR.n_games); S['lam'] = S.team.map(RR.lam)
S['scoreboard_move'] = S.adj_per_game * S.lam                  # rating move the scoreboard alone implies (points)
S['composite_move'] = S.team.map(RR.move_pts)
S['gap'] = S.composite_move - S.scoreboard_move
inv = {v: k for k, v in xw.items()}
S['ft_talent'] = S.team.map(lambda t: X.get(inv.get(t, t), np.nan)); S['ft_proj'] = S.team.map(lambda t: proj.get(inv.get(t, t), np.nan))

# ---- opponent-adjusted scoreboard move and the 70/30 blend (Nov 12, Composite_vs_Scoreboard_Test_2026-11-12.md).
# Same rating machinery as the composite (ratings_core.rate: ridge SRS, z-scored, lam = N/(N+K), early method, opponent-current),
# one pillar = luck-adjusted net points per 100 possessions from the box. Measured against our prior, not the closes.
# Backtest (two seasons): results land ~30% of the way from the composite toward this number -> blend_move.
try:
    import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ratings_core as rc
    PR = pd.read_csv('data/prior_2026-27.csv'); teams = list(PR.team); tix = {t: i for i, t in enumerate(teams)}
    zp = PR.z_prior.to_numpy(float)
    XB = dict(xw); XB.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    GG = G[G.pts.notna() & G.opp_pts.notna()]
    rowof = {int(g): (x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]) for g, x in GG.groupby('gameId')}
    Gs = []
    for x in rc.build_games(GG, tix, XB, {}, 'box')[0]:
        r = rowof[x['gameId']]; poss = (r.poss + r.opp_poss) / 2
        net = (r.pts - r.opp_pts) - 3 * (r.p3m - L3 * r.p3a) + 3 * (r.opp_p3m - L3 * r.opp_p3a) \
            - (r.ftm - X.get(r.team, LFT) * r.fta) + (r.opp_ftm - X.get(r.opp, LFT) * r.opp_fta)
        Gs.append(dict(gameId=x['gameId'], date=x['date'], t=x['t'], o=x['o'], home=x['home'], sbm=100 * net / poss, n_poss=poss, src='box'))
    old = (rc.PILLARS, rc.W, rc.OPP_CURRENT)
    rc.PILLARS, rc.W, rc.OPP_CURRENT = ['sbm'], {'sbm': 1.0}, True
    try:
        ob = rc.rate(Gs, len(teams), zp, asof, game_wt=False)
    finally:
        rc.PILLARS, rc.W, rc.OPP_CURRENT = old
    SBM = pd.Series(9.5 * (ob['z_blend'] - zp), index=teams)
    have = set(S.team)
    extra = [t for t, nn in RR.n_games.items() if nn > 0 and t not in have]       # teams with games but no graded close
    if extra:
        S = pd.concat([S, pd.DataFrame(dict(team=extra, games=0, n_games=[RR.n_games[t] for t in extra], lam=[RR.lam[t] for t in extra],
                                            composite_move=[RR.move_pts[t] for t in extra]))], ignore_index=True)
    S['sb_move_adj'] = S.team.map(SBM)
    S['blend_move'] = 0.7 * S.composite_move + 0.3 * S.sb_move_adj
    S['blend_delta'] = S.blend_move - S.composite_move                             # add to the team's rating (points) for the blend
    print(f'opponent-adjusted scoreboard: {len(Gs)} games; largest |blend_delta|: '
          + ', '.join(f'{t} {d:+.2f}' for t, d in S.set_index('team').blend_delta.reindex(S.set_index('team').blend_delta.abs().sort_values(ascending=False).index).head(5).items()))
except Exception as e:                                                             # diagnostic only - never block the file
    print(f'opponent-adjusted scoreboard failed: {e}')

S = S.round(3).sort_values('team')
os.makedirs('data/ratings', exist_ok=True); out = f'data/ratings/scoreboard_{asof}.csv'; S.to_csv(out, index=False)
print(f'{out}: {len(S)} teams, {len(T)} team-games with a close; L3 {L3:.3f}, league FT {LFT:.3f}')
