"""Composite vs scoreboard: which in-season reading should move the rating? (Nov 12, 2026, Jon's question from OSU/A&M.)

Walk-forward over a stored backtest season (Nov-Dec), same machinery as jobs/backtest_ratings.py, four in-season readings:
  comp_T   production composite (cw pillars, game-weighted), games 1-2 judged vs opponents' CURRENT rating (OPP_CURRENT True)
  comp_F   same, games 1-2 judged vs opponents' preseason prior (Nov 3-10 production)  -> also answers the queued
           opponent-current backtest
  sb_box   "scoreboard": luck-adjusted net points per 100 possessions from the full-game box
           (3P makes replaced by D-I 3P% x attempts; FTs replaced by FT talent x attempts), one pillar, every game equal
  sb_cw    same luck-adjusted net, but from leverage-weighted competitive possessions (play-by-play), game-weighted
Each reading is run through ratings_core.rate() unchanged (ridge SRS, z-scored, lam = N/(N+K), games 1-2 early method),
so the only difference between versions is what the in-season number is built from. Predictions:
  pred_v = 9.5 x (z_home - z_away) + KenPom HCA (0 neutral). Blends are linear in the predictions.
FT talent: prior-season KenPom team FT% shrunk 60% toward the D-I mean (year-to-year r ~0.2-0.4).
Prior: KenPom preseason AdjEM z (as in backtest_ratings.py).
Output: data/research/comp_vs_sb/preds_<S>.csv (one row per game).
Usage: python3 data/research/comp_vs_sb/comp_vs_sb.py --season 2026
"""
import os, sys, json, argparse, collections, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, 'jobs')
import ratings_core as rc
from ratings_core import build_games, rate, load_factors

OUT = 'data/research/comp_vs_sb'


def rate_with(G, n, zp, live, game_wt, pillars, w, opp_current):
    oldP, oldW, oldO = rc.PILLARS, rc.W, rc.OPP_CURRENT
    rc.PILLARS, rc.W, rc.OPP_CURRENT = pillars, w, opp_current
    try:
        return rate(G, n, zp, live, game_wt=game_wt)
    finally:
        rc.PILLARS, rc.W, rc.OPP_CURRENT = oldP, oldW, oldO


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--season', type=int, required=True); a = ap.parse_args()
    S = a.season; B = 'data/backtest'
    P = pd.read_csv(f'data/kenpom/preseason_{S}.csv')
    teams = list(P.TeamName); tix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    zp = ((P.AdjEM - P.AdjEM.mean()) / P.AdjEM.std(ddof=0)).to_numpy(float)
    X = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    X.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    TG = pd.read_csv(f'{B}/games_{S}.csv')
    XB = {}
    for nm in set(TG.team) | set(TG.opp):
        if nm in tix: XB[nm] = nm
        elif X.get(nm) in tix: XB[nm] = X[nm]
    HCA = dict(pd.read_csv('data/kp_hca.csv')[['team', 'hca']].values)
    FX = load_factors(f'{B}/game_factors_{S}.csv')
    L = pd.read_csv(f'{B}/lines_{S}.csv').set_index('gameId')
    TG = TG[TG.pts.notna() & TG.opp_pts.notna()].copy()
    RT = S <= 2025

    # ---- luck constants
    TG['ftm'] = TG.pts - 2 * TG.p2m - 3 * TG.p3m; TG['opp_ftm'] = TG.opp_pts - 2 * TG.opp_p2m - 3 * TG.opp_p3m
    d1 = TG[TG.team.map(XB.get).notna() & TG.opp.map(XB.get).notna()]
    L3 = d1.p3m.sum() / d1.p3a.sum(); LFT = d1.ftm.sum() / d1.fta.sum()
    M = pd.read_csv(f'data/kenpom/history/misc-stats_{S - 1}.csv')
    ftp = dict(zip(M.TeamName, M.FTPct / (100 if M.FTPct.max() > 1 else 1)))
    FTT = {t: 0.4 * ftp[t] + 0.6 * LFT if t in ftp else LFT for t in teams}
    print(f'season {S}: D-I 3P% {L3:.4f}, FT% {LFT:.4f}, FT talent from {S - 1} for {sum(t in ftp for t in teams)} teams')

    # ---- base games (production cw pillars) and the scoreboard pillar per game
    G_cw = build_games(TG, tix, XB, FX, 'cw', collections.Counter(), reb_team=RT)[0]
    FXr = pd.read_csv(f'{B}/game_factors_{S}.csv'); FXr = {(int(r.gameId), r.team): r for r in FXr.itertuples(index=False)}
    rowof = {}
    for gid, x in TG.groupby('gameId'):
        rowof[int(gid)] = x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]

    def sb_box(gid, t, o):
        r = rowof[gid]; poss = (r.poss + r.opp_poss) / 2
        net = (r.pts - r.opp_pts) - 3 * (r.p3m - L3 * r.p3a) + 3 * (r.opp_p3m - L3 * r.opp_p3a) \
            - (r.ftm - FTT[teams[t]] * r.fta) + (r.opp_ftm - FTT[teams[o]] * r.opp_fta)
        return 100 * net / poss, poss

    def sb_cw(gid, t, o):
        r = rowof[gid]; s, q = FXr.get((gid, r.team)), FXr.get((gid, r.opp))
        if s is None or q is None or s.poss_cw < 5: return None
        f = lambda z, k: float(getattr(z, f'{k}_cw'))
        net = (2 * f(s, 'p2m') + 3 * L3 * f(s, 'p3a') + FTT[teams[t]] * f(s, 'fta')) \
            - (2 * f(q, 'p2m') + 3 * L3 * f(q, 'p3a') + FTT[teams[o]] * f(q, 'fta'))
        poss = (f(s, 'poss') + f(q, 'poss')) / 2
        return 100 * net / poss, poss

    G_box, G_sbc = [], []
    for x in G_cw:
        v, p = sb_box(x['gameId'], x['t'], x['o'])
        G_box.append(dict(gameId=x['gameId'], date=x['date'], t=x['t'], o=x['o'], home=x['home'], sbm=v, n_poss=p, src='box'))
        c = sb_cw(x['gameId'], x['t'], x['o'])
        if c is None: c = (v, p)                                  # box fallback, as production does for pillars
        G_sbc.append(dict(gameId=x['gameId'], date=x['date'], t=x['t'], o=x['o'], home=x['home'], sbm=c[0], n_poss=c[1], src='cw'))
    print(f'{len(G_cw)} D-I games')

    home = TG[TG.isHome == True].drop_duplicates('gameId').set_index('gameId')
    ver = {
        'comp_T': (G_cw, True, rc.PILLARS, rc.W, True),
        'comp_F': (G_cw, True, rc.PILLARS, rc.W, False),
        'sb_box': (G_box, False, ['sbm'], {'sbm': 1.0}, True),
        'sb_cw':  (G_sbc, True, ['sbm'], {'sbm': 1.0}, True),
    }
    rows = []
    for d in sorted({x['date'] for x in G_cw}):
        past = {v: [x for x in g[0] if x['date'] < d] for v, g in ver.items()}
        if len(past['comp_T']) < 20: continue
        live = (dt.date.fromisoformat(d).replace(year=dt.date.fromisoformat(d).year + (2027 - S))).isoformat()
        out = {v: rate_with(past[v], n, zp, live, g[1], g[2], g[3], g[4]) for v, g in ver.items()}
        Ncount = out['comp_T']['N']
        for x in G_cw:
            if x['date'] != d or x['gameId'] not in home.index: continue
            r = home.loc[x['gameId']]; h, o = x['t'], x['o']; hca = HCA.get(teams[h], 2.84) if x['home'] else 0.0
            row = dict(date=d, gameId=x['gameId'], home=teams[h], away=teams[o], neutral=not x['home'], margin=r.pts - r.opp_pts,
                       n_home=int(Ncount[h]), n_away=int(Ncount[o]), zp_home=round(zp[h], 3), zp_away=round(zp[o], 3),
                       pred_prior=round(9.5 * (zp[h] - zp[o]) + hca, 2))
            for v, res in out.items():
                z = res['z_blend']; row[f'pred_{v}'] = round(9.5 * (z[h] - z[o]) + hca, 2)
                row[f'mv_{v}_home'] = round(9.5 * (z[h] - zp[h]), 2); row[f'mv_{v}_away'] = round(9.5 * (z[o] - zp[o]), 2)
            ln = L.loc[x['gameId']] if x['gameId'] in L.index else None
            row['open'] = None if ln is None or pd.isna(ln.spread_open) else float(ln.spread_open)
            row['close'] = None if ln is None or pd.isna(ln.spread_close) else float(ln.spread_close)
            rows.append(row)
        print(d, len(rows), flush=True) if d.endswith(('01', '15')) else None
    R = pd.DataFrame(rows); os.makedirs(OUT, exist_ok=True); R.to_csv(f'{OUT}/preds_{S}.csv', index=False)
    print(f'{len(R)} games, {R.date.min()} to {R.date.max()} -> {OUT}/preds_{S}.csv')


if __name__ == '__main__':
    main()
