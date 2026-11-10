"""Teams that missed the closing spread by 10+ in each of their first two lined D-I games: what happened in game three?
Data: data/backtest/lines_<y>.csv (CBBD closing spreads, Nov-Dec 2024 and 2025) and, for this season, data/grades/grade_log.csv.
ATS margin = team margin + team's spread (negative spread = favored). Usage: python3 data/research/ats_streak.py"""
import pandas as pd, numpy as np

def team_games(lines):
    L = lines.dropna(subset=['spread_close', 'homeScore', 'awayScore']).copy()
    L['date'] = (pd.to_datetime(L.startDate) - pd.Timedelta(hours=5)).dt.date.astype(str)   # ET (fixed offset; only order matters)
    hm = L.homeScore - L.awayScore
    a = pd.DataFrame({'gameId': L.gameId, 'date': L.date, 'team': L.homeTeam, 'opp': L.awayTeam, 'home': True, 'spread': L.spread_close, 'ats': hm + L.spread_close})
    b = pd.DataFrame({'gameId': L.gameId, 'date': L.date, 'team': L.awayTeam, 'opp': L.homeTeam, 'home': False, 'spread': -L.spread_close, 'ats': -hm - L.spread_close})
    return pd.concat([a, b]).sort_values(['team', 'date', 'gameId'])

def summarize(tg, label):
    tg = tg.copy(); tg['n'] = tg.groupby('team').cumcount() + 1
    w = tg[tg.n <= 3].pivot_table(index='team', columns='n', values=['ats', 'spread'], aggfunc='first').dropna()
    w.columns = [f'{a}{b}' for a, b in w.columns]
    def line(d, name):
        a = d.ats3; cov = (a > 0).sum(); los = (a < 0).sum(); n = cov + los
        se = np.sqrt(0.25 / n) if n else np.nan
        print(f'  {name:42} n {len(d):4}  game-3 ATS {cov}-{los}-{(a == 0).sum()}  cover {cov / max(n, 1):.3f} (±{se:.3f})  mean ATS margin {a.mean():+.1f}')
    print(f'\n{label}: {len(w)} teams with 3 lined games')
    line(w, 'all teams (baseline)')
    for k in (10, 7, 5):
        line(w[(w.ats1 <= -k) & (w.ats2 <= -k)], f'0-2 ATS, missed by {k}+ both games')
    line(w[(w.ats1 <= -10) & (w.ats2 <= -10) & (w.spread3 < 0)], '  ...and favored in game 3')
    line(w[(w.ats1 <= -10) & (w.ats2 <= -10) & (w.spread3 > 0)], '  ...and an underdog in game 3')
    line(w[(w.ats1 >= 10) & (w.ats2 >= 10)], 'mirror: 2-0 ATS, covered by 10+ both games')
    line(w[(w.ats1 < 0) & (w.ats2 < 0)], '0-2 ATS, any margin')
    return w

ws = []
for y in (2025, 2026):
    ws.append(summarize(team_games(pd.read_csv(f'data/backtest/lines_{y}.csv')), f'{y - 1}-{str(y)[2:]} (Nov-Dec)'))
w = pd.concat(ws)
print('\nBoth seasons pooled:')
for name, d in [('all teams', w), ('0-2 ATS by 10+', w[(w.ats1 <= -10) & (w.ats2 <= -10)]), ('2-0 ATS by 10+', w[(w.ats1 >= 10) & (w.ats2 >= 10)])]:
    a = d.ats3; c, l = (a > 0).sum(), (a < 0).sum(); print(f'  {name:16} n {len(d):4}  {c}-{l}  cover {c / max(c + l, 1):.3f} (±{np.sqrt(.25 / max(c + l, 1)):.3f})  mean {a.mean():+.1f}')

# this season (grade log: CBBD close where present, else the 4 AM number)
g = pd.read_csv('data/grades/grade_log.csv'); g['line'] = g.close.fillna(g.ref)
g = g.dropna(subset=['line', 'home_margin'])
a = pd.DataFrame({'date': g.date, 'team': g.home, 'opp': g.away, 'spread': g.line, 'ats': g.home_margin + g.line})
b = pd.DataFrame({'date': g.date, 'team': g.away, 'opp': g.home, 'spread': -g.line, 'ats': -g.home_margin - g.line})
t = pd.concat([a, b]).sort_values(['team', 'date']); t['n'] = t.groupby('team').cumcount() + 1
first2 = t[t.n <= 2].groupby('team').filter(lambda d: len(d) == 2 and (d.ats <= -10).all()).team.unique()
print(f'\n2026-27 so far: {len(first2)} teams missed by 10+ in both of their first two lined games')
print(t[t.team.isin(first2) & (t.n <= 3)].pivot_table(index='team', columns='n', values='ats').round(1).to_string())
