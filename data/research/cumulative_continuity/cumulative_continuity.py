"""Cumulative-continuity test (Jon, Nov 11 2026).

Question: in low-portal leagues (Patriot, Ivy), do teams that lose several multi-year starters at once run below
their preseason KenPom rating in the first two-plus months, beyond what KenPom's catch-all continuity number says?

Inputs (all in the repo):
  data/players/history/season_stats_<y>.csv   CBBD per-player season stats (minutes, usage) for every D-I team
  data/kenpom/preseason_<y>.csv               KenPom preseason archive (AdjEM preseason + AdjEMFinal)
  data/kenpom/history/archive_<date>.csv      KenPom ratings as of a past date (Jan 3, Jan 17 of each season)
  data/kenpom/history/height_<y>.csv          KenPom Continuity (% of minutes returning), Exp
Measure, per team-season Y (the test season):
  departed  = players with 10%+ of the team's player-slot minutes in Y-1 who are not on the team in Y
  starter-seasons lost = for each departed player, number of seasons at the team (through Y-1) with 50%+ of slot minutes
  shared-years bonus   = for each season, (k-1) where k = number of departed players who were 50%+ that season together
  cum_loss = starter-seasons lost + shared-years bonus
Outcome: AdjEM on Jan 3 (and Jan 17, and final) minus preseason AdjEM. Negative = ran below preseason.
Usage: python data/research/cumulative_continuity/cumulative_continuity.py   (prints tables, writes team_seasons.csv next to it)
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(ROOT, '..', '..', '..'))
os.chdir(REPO)
XW = json.load(open('data/xwalk_cbbd_kp.json'))          # CBBD team name -> KenPom name
XW = {k.strip(): v.strip() for k, v in XW.items()}
LOW_PORTAL = {'Patriot', 'Ivy'}
MIN_SHARE_DEPART, STARTER_SHARE = 0.10, 0.50

stats = {}
for f in sorted(glob.glob('data/players/history/season_stats_*.csv')):
    y = int(re.search(r'(\d{4})', os.path.basename(f)).group(1)); s = pd.read_csv(f)
    s = s[s.team.notna() & s.minutes.notna()].copy()
    slot = s.groupby('team').minutes.transform('sum') / 5.0            # minutes available to one player slot
    s['share'] = s.minutes / slot
    stats[y] = s
years = sorted(stats)

rows = []
for Y in years[1:]:
    cur = stats[Y]; cur_ids = set(zip(cur.team, cur.athleteId))
    prev = stats[Y - 1]
    if Y - 2 in stats:   # a team with no season in Y-1 (the Ivy sat out 2020-21): its departures are measured from Y-2
        missing = set(stats[Y - 2].team) - set(prev.team)
        prev = pd.concat([prev, stats[Y - 2][stats[Y - 2].team.isin(missing)]])
    for team, g in prev.groupby('team'):
        dep = g[(g.share >= MIN_SHARE_DEPART) & ~g.apply(lambda r: (team, r.athleteId) in cur_ids, axis=1)]
        starter_seasons = 0; shared = 0; dep_share = dep.share.sum(); dep_usage_share = 0.0
        if len(g): dep_usage_share = (dep.minutes * dep.usage.fillna(0)).sum() / max((g.minutes * g.usage.fillna(0)).sum(), 1e-9)
        per_season = {}
        for yy in years:
            if yy > Y - 1: break
            h = stats[yy]; h = h[(h.team == team) & h.athleteId.isin(dep.athleteId) & (h.share >= STARTER_SHARE)]
            per_season[yy] = len(h); starter_seasons += len(h)
            if len(h) >= 2: shared += len(h) - 1
        conf = g.conference.mode().iloc[0] if g.conference.notna().any() else ''
        rows.append(dict(season=Y, team_cbbd=team, team=XW.get(team, team), conf=conf, low_portal=conf in LOW_PORTAL,
                         n_departed=len(dep), dep_min_share=round(dep_share, 3), dep_usage_share=round(dep_usage_share, 3),
                         starter_seasons_lost=starter_seasons, shared_bonus=shared, cum_loss=starter_seasons + shared,
                         departed=', '.join(f"{r['name']} ({sum(1 for yy in years if yy <= Y-1 and ((stats[yy].team==team)&(stats[yy].athleteId==r.athleteId)&(stats[yy].share>=STARTER_SHARE)).any())})" for _, r in dep.sort_values('minutes', ascending=False).iterrows())))
T = pd.DataFrame(rows)

# KenPom: preseason, archive dates, final, continuity
def kp_pre(y):
    f = f'data/kenpom/preseason_{y}.csv'
    if not os.path.exists(f): return None
    p = pd.read_csv(f); return p[['TeamName', 'ConfShort', 'AdjEM', 'RankAdjEM', 'AdjEMFinal', 'RankAdjEMFinal']].rename(columns={'TeamName': 'team', 'AdjEM': 'em_pre', 'RankAdjEM': 'rk_pre', 'AdjEMFinal': 'em_final', 'RankAdjEMFinal': 'rk_final'})
def kp_arch(y, md):
    f = f'data/kenpom/history/archive_{y}-{md}.csv'
    if not os.path.exists(f): return None
    a = pd.read_csv(f); col = 'AdjEM' if 'AdjEM' in a else [c for c in a.columns if c.lower().startswith('adjem')][0]
    return a[['TeamName', col]].rename(columns={'TeamName': 'team', col: f'em_{md}'})
def kp_cont(y):
    f = f'data/kenpom/history/height_{y}.csv'
    if not os.path.exists(f): return None
    h = pd.read_csv(f); return h[['TeamName', 'Continuity', 'Exp']].rename(columns={'TeamName': 'team', 'Continuity': 'kp_continuity', 'Exp': 'kp_exp'})

parts = []
for Y in sorted(T.season.unique()):
    t = T[T.season == Y].copy()
    for df in (kp_pre(Y), kp_arch(Y, '01-03'), kp_arch(Y, '01-17'), kp_cont(Y)):
        if df is not None: t = t.merge(df, on='team', how='left')
    parts.append(t)
T = pd.concat(parts, ignore_index=True)
for c in ('em_01-03', 'em_01-17', 'em_final'):
    if c in T: T['d_' + c[3:]] = T[c] - T.em_pre
T.to_csv(os.path.join(ROOT, 'team_seasons.csv'), index=False)

pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 60)
print(f"team-seasons: {len(T)}; seasons {sorted(T.season.unique())}; with preseason KP: {T.em_pre.notna().sum()}; with Jan 3 KP: {T.get('em_01-03', pd.Series(dtype=float)).notna().sum()}")
print("\nNavy check:"); print(T[T.team == 'Navy'][['season', 'n_departed', 'dep_min_share', 'starter_seasons_lost', 'shared_bonus', 'cum_loss', 'kp_continuity', 'departed']].to_string(index=False))

def summarize(df, label, outcome):
    df = df.dropna(subset=[outcome, 'cum_loss'])
    if len(df) < 8: print(f"{label}: n={len(df)} (too few)"); return
    q = df.cum_loss.quantile([1/3, 2/3]).values
    lo, mid, hi = df[df.cum_loss <= q[0]], df[(df.cum_loss > q[0]) & (df.cum_loss <= q[1])], df[df.cum_loss > q[1]]
    print(f"{label} ({outcome}): n={len(df)}  corr(cum_loss, outcome)={df.cum_loss.corr(df[outcome]):+.3f}  corr(kp_continuity, outcome)={df.kp_continuity.corr(df[outcome]):+.3f}" if df.kp_continuity.notna().any() else f"{label} ({outcome}): n={len(df)}  corr(cum_loss, outcome)={df.cum_loss.corr(df[outcome]):+.3f}")
    for nm, g in (('low cum_loss', lo), ('mid', mid), ('high cum_loss', hi)):
        print(f"   {nm:14s} n={len(g):3d}  cum_loss {g.cum_loss.mean():4.1f}  KP cont {g.kp_continuity.mean():5.1f}  mean {outcome} {g[outcome].mean():+5.2f}  (SE {g[outcome].std(ddof=1)/np.sqrt(len(g)):.2f})  below-preseason share {(g[outcome] < 0).mean():.2f}")
    # partial: residualize outcome and cum_loss on kp_continuity
    d2 = df.dropna(subset=['kp_continuity'])
    if len(d2) >= 12:
        X = np.column_stack([np.ones(len(d2)), d2.kp_continuity, d2.cum_loss]); b, *_ = np.linalg.lstsq(X, d2[outcome], rcond=None)
        res = d2[outcome] - X @ b; s2 = (res ** 2).sum() / (len(d2) - 3); cov = s2 * np.linalg.inv(X.T @ X)
        print(f"   regression {outcome} = a + b1*KPcontinuity + b2*cum_loss:  b1={b[1]:+.3f} (SE {np.sqrt(cov[1,1]):.3f})  b2={b[2]:+.3f} (SE {np.sqrt(cov[2,2]):.3f})  per extra starter-season lost")

T = T[T.season >= 2022]   # the portal era (Jon): 2021-22 onward
for outcome in [c for c in ('d_01-03', 'd_01-17', 'd_final') if c in T]:
    print('\n' + '=' * 20, outcome)
    summarize(T[T.low_portal], 'Patriot + Ivy', outcome)
    summarize(T[~T.low_portal], 'rest of D-I', outcome)
    summarize(T, 'all D-I', outcome)

print('\n==== Patriot + Ivy by season: mean d_01-03 for teams losing 2+ multi-year starters together (shared_bonus >= 2) vs the rest')
lp = T[T.low_portal].dropna(subset=['d_01-03'])
lp = lp.assign(multi=lp.shared_bonus >= 2)
print(lp.groupby(['season', 'multi'])['d_01-03'].agg(['count', 'mean']).round(2).unstack())
print('pooled:'); print(lp.groupby('multi')[['d_01-03', 'd_01-17', 'd_final']].agg(['count', 'mean']).round(2))
print('\n==== Patriot + Ivy: KP continuity terciles (the catch-all number on its own)')
q = lp.kp_continuity.quantile([1/3, 2/3]).values
for nm, g in (('low continuity', lp[lp.kp_continuity <= q[0]]), ('mid', lp[(lp.kp_continuity > q[0]) & (lp.kp_continuity <= q[1])]), ('high continuity', lp[lp.kp_continuity > q[1]])):
    print(f"   {nm:16s} n={len(g):3d} KP cont {g.kp_continuity.mean():.2f} cum_loss {g.cum_loss.mean():4.1f}  d_01-03 {g['d_01-03'].mean():+5.2f}  d_01-17 {g['d_01-17'].mean():+5.2f}  d_final {g['d_final'].mean():+5.2f}")
print('\n==== Patriot + Ivy, teams with cum_loss >= 12 (Navy 2026-27 would score 14):')
print(lp[lp.cum_loss >= 12].sort_values('cum_loss', ascending=False)[['season', 'team', 'cum_loss', 'kp_continuity', 'em_pre', 'd_01-03', 'd_01-17', 'd_final', 'departed']].to_string(index=False))
