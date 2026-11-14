"""Availability Tracker game-data refresh (Nov 14, 2026; was the manual claude/engine/build_avail_rs.py).
Rebuilds the tracker's computed rows (groups, minutes by game, team game dates) from the rotation store
(data/rotation/player_games.csv: every player-game with minutes, rebuilt each morning by the Rotation depth job) against the
BurnerBall depth charts in data/tracker/roster.json (copy of the artifact's roster.json).
Writes rows.json (the page fetches it; it replaces the old computed/rows database document, which was capped at 256 KB).
Groups: chart_out = chart note says INJ/ACL/RS/INEL and he has missed a game; dnp = first- or second-string player who missed a game;
light = chart starter under 10 min a game; deep = third string or lower who hasn't played; off_chart = 10+ min a game, not on the chart.
Usage: python3 tools/tracker_refresh.py --date D [--out /home/claude/rows.json]
Published by the 5:39 AM 'Refresh role cards page' scheduled task (publish_files, path rows.json) after the Role events run."""
import sys, os, re, json, difflib, argparse, collections, unicodedata
import pandas as pd
sys.path.insert(0, 'jobs')
from team_names import kp, pn

ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--out', default='/home/claude/rows.json'); a = ap.parse_args()
R = json.load(open('data/tracker/roster.json'))
def slug(x):
    x = unicodedata.normalize('NFKD', x).encode('ascii', 'ignore').decode().lower().replace('&', ' and ')
    return re.sub(r'^-+|-+$', '', re.sub(r'[^a-z0-9]+', '-', x))
def rid(team, player): return f'{slug(team)}--{slug(player)}'
bb2kp = {t: kp(t) for t in R['teams']}; kp2bb = {v: k for k, v in bb2kp.items() if v}
pg = pd.read_csv('data/rotation/player_games.csv')
B = pd.DataFrame({'gameId': pg.gameId, 'date_ET': pg.date, 'team_kp': pg.team.map(lambda t: kp(t) or t), 'name': pg.athlete, 'minutes': pg.min_raw.fillna(0)})
B = B[(B.team_kp.isin(kp2bb)) & (B.date_ET < a.date)].copy()
OUTNOTE = re.compile(r'INJ|ACL|\bRS\b|INEL')
rows, minutes, team_dates = [], {}, {}
for tk, x in B.groupby('team_kp'):
    tb = kp2bb[tk]; games = sorted(x.groupby('gameId').date_ET.first().items(), key=lambda kv: kv[1])
    gids = [g for g, _ in games]; team_dates[tb] = [d for _, d in games]
    chart = R['teams'][tb]['players']
    bnames = {pn(n): n for n in x.name.unique()}
    piv = x.pivot_table(index='name', columns='gameId', values='minutes', aggfunc='sum').reindex(columns=gids).fillna(0)
    mins = {n: [round(float(v), 1) for v in piv.loc[n]] for n in piv.index}
    matched = set()
    for name, slot, cls, tr, note in chart:
        k = pn(name); m = k if k in bnames else (difflib.get_close_matches(k, list(bnames), n=1, cutoff=0.85) or [None])[0]
        if m is None:   # last name + first initial, unique
            c = [b for b in bnames if b.split() and k.split() and b.split()[-1] == k.split()[-1] and b[0] == k[0]]; m = c[0] if len(c) == 1 else None
        bg = mins[bnames[m]] if m else [0.0] * len(gids)
        if m: matched.add(bnames[m])
        i = rid(tb, name); minutes[i] = bg
        mpg = round(sum(bg) / len(bg), 1) if bg else None
        depth = int(re.sub(r'\D', '', slot) or 9)
        missed = sum(1 for v in bg if v == 0)
        if OUTNOTE.search(note or '') and missed: grp = 'chart_out'
        elif depth <= 2 and missed: grp = 'dnp'
        elif depth == 1 and mpg is not None and mpg < 10: grp = 'light'
        elif depth >= 3 and missed == len(bg): grp = 'deep'
        else: continue
        rows.append(dict(id=i, team=tb, player=name, slot=slot, cls=cls, transfer=bool(tr), chart_note=note, games=len(bg), by_game=bg, mpg=mpg, group=grp))
    for n in set(x.name.unique()) - matched:
        bg = mins[n]; mpg = round(sum(bg) / len(bg), 1); i = rid(tb, n); minutes[i] = bg
        if mpg >= 10: rows.append(dict(id=i, team=tb, player=n, slot='', cls='', transfer=False, chart_note='', games=len(bg), by_game=bg, mpg=mpg, group='off_chart'))
doc = dict(rows=rows, minutes=minutes, team_dates=team_dates, snapshot=R['snapshot'], refreshed=a.date,
           games_through=max(d for v in team_dates.values() for d in v), teams_tracked=len(team_dates), tracked_teams=sorted(team_dates))
s = json.dumps(doc, separators=(',', ':'))
open(a.out, 'w').write(s)
print(f'tracker refresh {a.date}: {len(rows)} rows {dict(collections.Counter(r["group"] for r in rows))}, {len(team_dates)} teams, '
      f'games through {doc["games_through"]}, {len(s) // 1024} KB -> {a.out}; unmapped chart teams {[t for t, k in bb2kp.items() if not k]}')
