"""Weekly K sanity check: blend vs prior-only vs in-season-only, on graded games (trailing window).
For each game on date D, ratings are the snapshot data/ratings/ratings_<D>.csv (built that morning from games before D).
Home spread = 9.5*(z_home - z_away) + HCA (true home only). Scores each version against the final margin (MAE, RMSE)
and the CBBD close (MAE to close; ATS vs close when the version disagrees with the close by >= 2).
usage: python3 data/research/k_check/k_sanity.py [--start D] [--end D]"""
import sys, glob, pandas as pd, numpy as np
a = dict(zip(sys.argv[1::2], sys.argv[2::2])); G = pd.read_csv('data/grades/grade_log.csv', encoding='utf-8-sig')
G = G[(G.date >= a.get('--start', '0')) & (G.date <= a.get('--end', '9'))]
h = pd.read_csv('data/kp_hca.csv'); h['team'] = h.team.str.strip(); H = dict(zip(h.team, h.hca))
rows = []
for d, g in G.groupby('date'):
    f = f'data/ratings/ratings_{d}.csv'
    try: R = pd.read_csv(f).set_index('team')
    except FileNotFoundError: continue
    for x in g.itertuples():
        if x.home not in R.index or x.away not in R.index or pd.isna(x.home_margin): continue
        hca = H.get(x.home, 3.0) if x.venue == 'H' else 0.0
        r = dict(date=d, away=x.away, home=x.home, margin=x.home_margin, close=x.close, nh=R.at[x.home, 'n_games'], na=R.at[x.away, 'n_games'])
        for k, c in [('blend', 'z_blend'), ('prior', 'z_prior'), ('inseason', 'z_inseason')]:
            zh, za = R.at[x.home, c], R.at[x.away, c]
            r[k] = np.nan if pd.isna(zh) or pd.isna(za) else 9.5 * (zh - za) + hca      # predicted home margin
        rows.append(r)
D = pd.DataFrame(rows); D = D[(D.nh > 0) | (D.na > 0)]      # at least one team has in-season data
D['inseason_ok'] = (D.nh > 0) & (D.na > 0)
def score(S, lab):
    out = []
    for k in ['blend', 'prior', 'inseason']:
        e = S[k] - S.margin; c = S.dropna(subset=['close'])
        cm = -c.close                                        # close as predicted home margin
        dis = c[(c[k] - cm).abs() >= 2]; win = np.sign(dis[k] - (-dis.close)) == np.sign(dis.margin - (-dis.close))
        push = dis.margin == -dis.close
        out.append(dict(set=lab, version=k, n=S[k].notna().sum(), MAE=e.abs().mean(), RMSE=np.sqrt((e ** 2).mean()), bias=e.mean(),
                        MAE_to_close=(c[k] - cm).abs().mean(), ats_n=int((~push).sum()), ats_w=int((win & ~push).sum())))
    c = S.dropna(subset=['close']); e = -c.close - c.margin
    out.append(dict(set=lab, version='close', n=len(c), MAE=e.abs().mean(), RMSE=np.sqrt((e ** 2).mean()), bias=e.mean(), MAE_to_close=0, ats_n=0, ats_w=0))
    return pd.DataFrame(out)
T = pd.concat([score(D, 'all games, one+ team with games'), score(D[D.inseason_ok], 'both teams with games')])
T['ats_pct'] = (T.ats_w / T.ats_n.replace(0, np.nan)).round(3)
print(f"{D.date.min()} to {D.date.max()}: {len(D)} games"); print(T.round(2).to_string(index=False))
by = D.assign(e_b=(D.blend - D.margin).abs(), e_p=(D.prior - D.margin).abs(), e_i=(D.inseason - D.margin).abs()).groupby('date')[['e_b', 'e_p', 'e_i']].mean().round(2)
print('MAE by day (blend / prior / in-season):'); print(by.to_string())
D.to_csv(f'data/research/k_check/k_sanity_{D.date.max()}.csv', index=False)
