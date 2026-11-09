"""Shot-mix matchup from the Torvik tables in data/torvik/ (see jobs/torvik_pbp.py).
For each side: the offense's shot mix (share, FG%) next to what the opposing defense allows, with D-I percentiles,
then each team's players (if a player table for that season is present).
Usage: python jobs/shotmix_matchup.py "Minnesota" "Cincinnati" [--season 2027] [--players-season 2026]"""
import argparse, glob, os
import pandas as pd
ap = argparse.ArgumentParser(); ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('--season', type=int, default=2027); ap.add_argument('--players-season', type=int)
a = ap.parse_args()
def load(kind, y):
    f = f'data/torvik/{kind}_{y}.csv'
    return pd.read_csv(f).set_index('team') if os.path.exists(f) else None
pd.set_option('display.width', 220)
for kind in ('team_dist', 'team_types'):
    d = load(kind, a.season)
    if d is None: print(f'(no data/torvik/{kind}_{a.season}.csv)'); continue
    types = sorted({c.split('|')[0] for c in d.columns if c.endswith('|off_share') and not c.startswith('and_1')},
                   key=lambda t: list(d.columns).index(f'{t}|off_share'))
    pct = d.rank(pct=True, numeric_only=True)
    for o, x in ((a.a, a.b), (a.b, a.a)):
        if o not in d.index or x not in d.index: print(f'{kind}: team not found ({o} / {x})'); continue
        rows = []
        for t in types:
            rows.append({'shot': t,
                         f'{o} share': d.at[o, f'{t}|off_share'], 'pct': round(100 * pct.at[o, f'{t}|off_share']),
                         f'{x} D allows': d.at[x, f'{t}|def_share'], 'pct ': round(100 * pct.at[x, f'{t}|def_share']),
                         'D-I med': round(d[f'{t}|off_share'].median(), 1),
                         f'{o} FG%': d.at[o, f'{t}|off_fg'], f'{x} D FG%': d.at[x, f'{t}|def_fg'], 'D-I med FG%': round(d[f'{t}|off_fg'].median(), 1)})
        print(f'\n{kind} {a.season}: {o} offense vs {x} defense'); print(pd.DataFrame(rows).to_string(index=False))
ps = a.players_season or a.season
for kind in ('player_types', 'player_dist'):
    files = [f for f in [f'data/torvik/{kind}_{ps}.csv'] + glob.glob(f'data/torvik/{kind}_{ps}_*.csv') if os.path.exists(f)]
    if not files: continue
    p = pd.concat(pd.read_csv(f) for f in files).drop_duplicates(['Player', 'Team'])
    for t in (a.a, a.b):
        q = p[p.Team == t]
        if not len(q): continue
        att = [c for c in q.columns if c.endswith('|att')]
        q = q.assign(FGA=q[att].sum(axis=1)).sort_values('FGA', ascending=False)
        keep = ['Player', 'FGA'] + [c for c in q.columns if c.endswith(('|Share', '|FG%', '|eFG%')) and not c.startswith(('Tip-Ins', 'Hooks'))] + [c for c in ("TOT|Ast'd", 'TOT|And-1%') if c in q]
        out = q[keep].rename(columns=lambda c: c.replace('Layups & Drives', 'Lay/Drv').replace('Pull-Up / Step-Back', 'PullUp').replace('Spot-Up / Jumpers', 'SpotUp').replace('Floaters', 'Float'))
        print(f'\n{kind} {ps}: {t}'); print(out.to_string(index=False))
