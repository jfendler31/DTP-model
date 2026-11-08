"""Old vs new in-season ratings on a past season, November-December, walk-forward with production's own math.

For every game date d (from the first date with 20+ prior D-I games), ratings are built from games before d and
predict d's games. Versions (jobs/ratings_core.py):
  box    old production inputs: CBBD box totals, every game equal weight
  cw     play-by-play competitive totals (leverage-weighted, OT kept), equal weight
  cw_gw  production from Nov 9: cw with each game weighted by its competitive possessions
  prior  preseason only (reference)
Prior: KenPom preseason AdjEM for that season (data/kenpom/preseason_<S>.csv), z-scored — not the live 3-system blend,
so absolute levels differ from production; the comparison between versions is what this measures.
K schedule: production's, shifted to the season's dates (8 through Nov 30, ramping toward 12).
Spread: 9.5 x (z_home - z_away) + KenPom HCA (current table; 0 on neutral floors).
Graded on: final margin (all D-I games); CBBD median closing spread (home/away games only — CBBD's neutral-site line
orientation is unreliable): ATS of the model side, overall and by edge band.
Inputs: data/backtest/{games,lines,game_factors}_<S>.csv. Outputs: data/backtest/results_<S>.csv (one row per game).
Usage: python jobs/backtest_ratings.py --season 2026
"""
import os, sys, json, argparse, collections, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratings_core import build_games, rate, load_factors

VERSIONS = {'box': ('box', False), 'cw': ('cw', False), 'cw_gw': ('cw', True)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--season', type=int, required=True); a = ap.parse_args()
    S = a.season; B = 'data/backtest'
    P = pd.read_csv(f'data/kenpom/preseason_{S}.csv')
    teams = list(P.TeamName); tix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    zp = ((P.AdjEM - P.AdjEM.mean()) / P.AdjEM.std(ddof=0)).to_numpy(float)
    X = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    X.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    XB = {}
    TG = pd.read_csv(f'{B}/games_{S}.csv')
    for nm in set(TG.team) | set(TG.opp):
        if nm in tix: XB[nm] = nm
        elif X.get(nm) in tix: XB[nm] = X[nm]
    HCA = dict(pd.read_csv('data/kp_hca.csv')[['team', 'hca']].values)
    FX = load_factors(f'{B}/game_factors_{S}.csv')
    L = pd.read_csv(f'{B}/lines_{S}.csv').set_index('gameId')
    TG = TG[TG.pts.notna() & TG.opp_pts.notna()]
    ALL = {v: build_games(TG, tix, XB, FX if src != 'box' else {}, src, collections.Counter())[0] for v, (src, _) in VERSIONS.items()}
    srcs = collections.Counter(x['src'] for x in ALL['cw'])
    print(f'season {S}: {len(ALL["box"])} D-I games; cw pillars from play-by-play {srcs["pbp"]}, box fallback {srcs["box"]}')
    home = TG[TG.isHome == True].drop_duplicates('gameId').set_index('gameId')

    rows = []
    dates = sorted({x['date'] for x in ALL['box']})
    for d in dates:
        past = {v: [x for x in G if x['date'] < d] for v, G in ALL.items()}
        if len(past['box']) < 20: continue
        live = (dt.date.fromisoformat(d).replace(year=dt.date.fromisoformat(d).year + (2027 - S))).isoformat()   # K schedule on 2026-27 dates
        Z = {v: rate(past[v], n, zp, live, game_wt=VERSIONS[v][1])['z_blend'] for v in VERSIONS}
        Z['prior'] = zp
        for x in ALL['box']:
            if x['date'] != d: continue
            r = home.loc[x['gameId']] if x['gameId'] in home.index else None
            if r is None: continue
            h, o = x['t'], x['o']; hca = HCA.get(teams[h], 2.84) if x['home'] else 0.0
            row = dict(date=d, gameId=x['gameId'], home=teams[h], away=teams[o], neutral=not x['home'], margin=r.pts - r.opp_pts,
                       n_games_home=sum(1 for g in past['box'] if h in (g['t'], g['o'])), n_games_away=sum(1 for g in past['box'] if o in (g['t'], g['o'])))
            for v, z in Z.items(): row[f'pred_{v}'] = round(9.5 * (z[h] - z[o]) + hca, 2)
            ln = L.loc[x['gameId']] if x['gameId'] in L.index else None
            row['close'] = None if ln is None or pd.isna(ln.spread_close) else float(ln.spread_close)   # home spread (negative = home favored)
            rows.append(row)
    R = pd.DataFrame(rows); R.to_csv(f'{B}/results_{S}.csv', index=False)

    print(f'{len(R)} games graded, {R.date.min()} to {R.date.max()}')
    print('\nfinal margin, all games            MAE    RMSE   bias')
    for v in ('prior', 'box', 'cw', 'cw_gw'):
        e = R.margin - R[f'pred_{v}']; print(f'  {v:6s}                          {e.abs().mean():6.2f} {np.sqrt((e ** 2).mean()):6.2f} {e.mean():+6.2f}')
    for a_, b_ in (('cw', 'box'), ('cw_gw', 'box'), ('cw_gw', 'cw')):
        dd = (R.margin - R[f'pred_{a_}']).abs() - (R.margin - R[f'pred_{b_}']).abs()
        print(f'  {a_} vs {b_}: |err| diff {dd.mean():+.3f} (se {dd.std() / np.sqrt(len(dd)):.3f})')
    for lo, hi, lab in ((dates[0], '2025-11-30' if S == 2026 else '2024-11-30', 'Nov'), ('2025-12-01' if S == 2026 else '2024-12-01', '9999', 'Dec')):
        s = R[(R.date >= lo) & (R.date <= hi)]
        print(f'  {lab}: n {len(s)}  MAE box {(s.margin - s.pred_box).abs().mean():.2f}  cw {(s.margin - s.pred_cw).abs().mean():.2f}  cw_gw {(s.margin - s.pred_cw_gw).abs().mean():.2f}')
    H = R[(~R.neutral) & R.close.notna()].copy()
    print(f'\nvs CBBD close, home/away games (n {len(H)}); market MAE {(H.margin + H.close).abs().mean():.2f}')
    print('  version  model-side ATS        edge>=2              edge>=3              MAE vs close line')
    for v in ('prior', 'box', 'cw', 'cw_gw'):
        side_home = H[f'pred_{v}'] > -H.close
        cover_home = H.margin + H.close
        res = np.where(cover_home == 0, np.nan, np.where(side_home, cover_home > 0, cover_home < 0)).astype(float)
        e_abs = (H[f'pred_{v}'] + H.close).abs()
        def pct(m): r = res[m & ~np.isnan(res)]; return f'{r.mean():.1%} ({len(r)})' if len(r) else '-'
        print(f'  {v:7s}  {pct(np.ones(len(H), bool)):20s} {pct((e_abs >= 2).to_numpy()):20s} {pct((e_abs >= 3).to_numpy()):20s} {e_abs.mean():.2f}')


if __name__ == '__main__':
    main()
