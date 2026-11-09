"""Weekly calibration report from data/grades/grade_log.csv (Nov 9, 2026).
CLV and capture rate (CLV / avg edge) by 4 AM edge band, overall and split by model-on-favorite vs dog
and by line size (15+ vs under). Drops rows with a bad reference (|ref - close| >= 6: a mismatched line,
e.g. Merrimack at Appalachian St., Nov 2: ref -8.5 vs close +3.25).
Usage: python3 data/research/calibration/calibration_report.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]"""
import argparse, numpy as np, pandas as pd
a = argparse.ArgumentParser(); a.add_argument('--start'); a.add_argument('--end'); a = a.parse_args()
g = pd.read_csv('data/grades/grade_log.csv')
if a.start: g = g[g.date >= a.start]
if a.end: g = g[g.date <= a.end]
bad = g[(g.ref - g.close).abs() >= 6]
if len(bad): print('dropped (bad reference):', ', '.join(f'{r.date} {r.away} at {r.home} ref {r.ref} close {r.close}' for r in bad.itertuples()))
g = g.drop(bad.index)
g['band'] = pd.cut(g.edge, [0, 1, 2, 3, 99], right=False, labels=['<1', '1-2', '2-3', '3+'])
home = g.side == g.home
g['model_on'] = np.where(np.where(home, g.ref < 0, g.ref > 0), 'favorite', 'dog')
g['line'] = np.where(g.ref.abs() >= 15, '15+', 'under 15')
def s(d):
    return pd.Series({'n': len(d), 'avg_edge': round(d.edge.mean(), 2), 'clv': round(d.clv.mean(), 2),
                      'capture': round(d.clv.mean() / d.edge.mean(), 2), 'ats': f"{(d.res_ref=='W').sum()}-{(d.res_ref=='L').sum()}-{(d.res_ref=='P').sum()}"})
print(f'{g.date.min()} to {g.date.max()}: {len(g)} games, CLV {g.clv.mean():+.2f}')
for keys, lab in [(['band'], 'All'), (['band', 'model_on'], 'Model on favorite vs dog'), (['band', 'line'], 'Line 15+ vs under 15')]:
    print(f'\n{lab}:'); print(g.groupby(keys, observed=True).apply(s, include_groups=False).to_string())
