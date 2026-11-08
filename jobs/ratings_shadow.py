"""Shadow ratings beside production — changes nothing production reads. Math: jobs/ratings_core.py (same as jobs/ratings.py).

Versions:
  cw_gw  production from Nov 9: play-by-play competitive totals (leverage-weighted, OT in), each game weighted by its
         competitive possessions — must reproduce data/ratings_current.csv (self-check)
  cw     same totals, every game equal weight
  box    the old production inputs (CBBD box totals, garbage time in, equal weight)

Outputs (data/ratings_shadow/):
  ratings_<version>_<date>.csv              same columns as production (cw and box)
  compare_<date>.csv, compare_current.csv   one row per team: z and points under each version
  card_<date>.csv                           today's card games: model home spread and edge under each version
  check_<date>.csv                          raw play-by-play vs box per team-game (the gate)
Usage: python jobs/ratings_shadow.py [--date YYYY-MM-DD]
"""
import os, sys, json, argparse, collections, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratings_core import build_games, rate, frame, load_factors, pbp_side, COLS

ET = ZoneInfo('America/New_York')
OUT = 'data/ratings_shadow'
VERSIONS = {'cw_gw': ('cw', True), 'cw': ('cw', False), 'box': ('box', False)}
SWITCH = '2026-11-09'     # first card built on cw_gw ratings


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date'); a = ap.parse_args()
    asof = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
    os.makedirs(OUT, exist_ok=True)
    TG = pd.read_csv('data/games_2026-27.csv')
    P = pd.read_csv('data/prior_2026-27.csv'); teams = list(P.team); tix = {t: i for i, t in enumerate(teams)}
    zp = P.z_prior.to_numpy(float); n = len(teams)
    XB = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    XB.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    FX = load_factors('data/pbp/game_factors.csv')
    TG = TG[(TG.date < asof) & TG.pts.notna() & TG.opp_pts.notna()]

    # parser check: raw play-by-play vs box, per team-game
    chk = []
    for r in TG.itertuples(index=False):
        p_ = pbp_side(FX, r.gameId, r.team, 'raw')
        if p_ is None: continue
        chk.append(dict(gameId=int(r.gameId), date=r.date, team=r.team, **{f'box_{c}': getattr(r, c) for c in COLS},
                        **{f'pbp_{c}': p_[c] for c in COLS}))
    C = pd.DataFrame(chk)
    if len(C):
        C.to_csv(f'{OUT}/check_{asof}.csv', index=False)
        print('raw play-by-play vs box per team-game, mean |diff|: ' +
              ', '.join(f"{c} {(C[f'pbp_{c}'] - C[f'box_{c}']).abs().mean():.2f}" for c in ('p2a', 'p3a', 'fta', 'orb', 'drb', 'to', 'poss')))

    res = {}
    for v, (src, gw) in VERSIONS.items():
        log = collections.Counter()
        G, _ = build_games(TG, tix, XB, FX if src != 'box' else {}, src, log)
        out = rate(G, n, zp, asof, game_wt=gw); res[v] = out['z_blend']
        print(f'  {v:6s} {len(G)} games ({", ".join(f"{k} {c}" for k, c in log.most_common())}); early fit {out["fit"]}')
        if v != 'cw_gw': frame(teams, zp, out, asof).to_csv(f'{OUT}/ratings_{v}_{asof}.csv', index=False)
        if v == 'cw_gw': Nn = out['N']
    prod = pd.read_csv('data/ratings_current.csv')
    if str(prod['asof'].iloc[0]) == asof:
        pz = prod.set_index('team').z_blend.reindex(teams).to_numpy(float)
        print(f"self-check vs data/ratings_current.csv: max |z diff| {np.nanmax(np.abs(np.round(res['cw_gw'], 4) - pz)):.4f} (0 = cw_gw reproduces production)")
    else:
        print(f"self-check skipped: ratings_current.csv is as of {prod['asof'].iloc[0]}, shadow as of {asof}")

    cmp = pd.DataFrame(dict(team=teams, n_games=Nn.astype(int), z_prior=zp.round(4), **{f'z_{v}': res[v].round(4) for v in VERSIONS}))
    cmp['prod_minus_box_pts'] = ((res['cw_gw'] - res['box']) * 9.5).round(2)
    cmp['prod_minus_cw_pts'] = ((res['cw_gw'] - res['cw']) * 9.5).round(2)
    cmp['asof'] = asof
    cmp.to_csv(f'{OUT}/compare_{asof}.csv', index=False); cmp.to_csv(f'{OUT}/compare_current.csv', index=False)
    g = cmp[cmp.n_games > 0]
    for c in ('prod_minus_box_pts', 'prod_minus_cw_pts'):
        print(f'  {c:17s} {len(g)} teams: mean |delta| {g[c].abs().mean():.2f} pts, 90th pct {g[c].abs().quantile(.9):.2f}, max {g[c].abs().max():.2f}')
    top = g.reindex(g.prod_minus_box_pts.abs().sort_values(ascending=False).index).head(10)
    print('largest moves, production vs box (pts):'); print(top[['team', 'n_games', 'prod_minus_box_pts', 'prod_minus_cw_pts']].to_string(index=False))

    # today's card under each version: the card's model numbers come from the production ratings of that morning;
    # the other versions differ from it by their rating deltas (overrides and HCA unchanged)
    cf = f'cards/card_{asof}.csv'
    if os.path.exists(cf):
        cd = pd.read_csv(cf); Z = {v: dict(zip(teams, res[v])) for v in VERSIONS}
        base = 'cw_gw' if asof >= SWITCH else 'box'          # which version the card's own model numbers were built on
        rows = []
        for c in cd.itertuples(index=False):
            if c.away not in Z['box'] or c.home not in Z['box'] or pd.isna(c.model_home_spread): continue
            row = dict(tip_ET=c.tip_ET, away=c.away, home=c.home, venue=c.venue, market_home_spread=c.market_home_spread, model_card=c.model_home_spread)
            for v in VERSIONS:
                dz = (Z[v][c.home] - Z[base][c.home]) - (Z[v][c.away] - Z[base][c.away])
                m = round(float(c.model_home_spread) - 9.5 * dz, 1); row[f'model_{v}'] = m
                row[f'edge_{v}'] = None if pd.isna(c.market_home_spread) else round(float(c.market_home_spread) - m, 1)
            rows.append(row)
        if rows:
            CD = pd.DataFrame(rows); CD.to_csv(f'{OUT}/card_{asof}.csv', index=False, encoding='utf-8-sig')
            print(f'card {asof}: {len(CD)} games; mean |model change| production vs box {(CD.model_cw_gw - CD.model_box).abs().mean():.2f}, '
                  f'vs equal-weight cw {(CD.model_cw_gw - CD.model_cw).abs().mean():.2f}')


if __name__ == '__main__':
    main()
