"""Availability Tracker 'Playing today' data (Nov 14, 2026; Jon).
Builds the document the tracker page reads at computed/today: today's games (tip, opponent, venue, card spread from the
team's side) keyed by the tracker's team spelling, and each player's importance on those teams:
EvanMiya BPR, team BPR rank, and full spread value if out (team_value with vs without, on top of the team's active
overrides — runbook §3 step 1-2, no priced-share or overlap factors; this is a sort key, not a J).
Usage: python3 tools/tracker_today.py --date D [--out /home/claude/today.json]
The 4:15 scheduled task publishes the JSON as today.json in the Availability Tracker artifact (publish_files, mode patch)."""
import sys, os, json, argparse, datetime as dt
import pandas as pd
sys.path.insert(0, 'jobs')
from absence_sweep import team_value, make_fixer
from team_names import pn

ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--out', default='/home/claude/today.json'); ap.add_argument('--top', type=int, default=10); a = ap.parse_args()
D = a.date
P = pd.read_csv('data/prior_2026-27.csv').set_index('team'); fix = make_fixer(P.index)
MAN = {'Miami (Fla.)': 'Miami FL', 'Florida International': 'FIU'}
E = pd.read_csv('data/evanmiya/ratings_2026-27.csv'); E['kp'] = E.team.map(lambda t: MAN.get(t) or fix(t)); E['pk'] = E.name.map(pn)
TM = pd.read_csv('data/tracker/team_map.csv')            # tracker spelling -> KenPom spelling
to_tr = {}
for r in TM.itertuples(index=False): to_tr.setdefault(r.kp, r.tracker)
S = pd.read_csv(f'data/slate_{D}.csv')
C = pd.read_csv(f'cards/card_{D}.csv') if os.path.exists(f'cards/card_{D}.csv') else None
OV = pd.read_csv('data/overrides.csv', dtype=str).fillna('')
act = OV[OV.expires.isin(['', 'until cleared', 'season']) | (OV.expires >= D)]
outs = {t: set(g.player.map(pn)) for t, g in act.groupby('team')}

def tip(s):
    try: return dt.datetime.strptime(s.split(' ', 1)[1] + f' {D[:4]}', '%b %d %I:%M %p %Y').strftime('%-I:%M %p')
    except Exception: return s
games, players = {}, {}
for g in S.itertuples(index=False):
    row = None
    if C is not None:
        m = C[(C.away == g.away) & (C.home == g.home)]
        row = m.iloc[0] if len(m) else None
    for side, team, opp in (('away', g.away, g.home), ('home', g.home, g.away)):
        tr = to_tr.get(team)
        if not tr: continue
        loc = 'vs' if g.venue == 'N' else ('vs' if side == 'home' else 'at')
        mdl = mkt = None
        if row is not None:
            sgn = 1 if side == 'home' else -1
            if pd.notna(row.model_home_spread_adj): mdl = round(sgn * float(row.model_home_spread_adj), 1)
            if pd.notna(row.market_home_spread): mkt = round(sgn * float(row.market_home_spread), 1)
        games[tr] = {'tip': tip(g.tip_ET), 'opp': to_tr.get(opp, opp), 'loc': loc + (' (N)' if g.venue == 'N' else ''), 'model': mdl, 'market': mkt}
        R = E[E.kp == team]
        if not len(R): continue
        keep = R[~R.pk.isin(outs.get(team, set()))]
        base = team_value(list(keep.bpr))
        rank = R.bpr.rank(ascending=False, method='first').astype(int)
        lst = []
        for p, b, rk, pk in zip(R.name, R.bpr, rank, R.pk):
            v = base - team_value(list(keep[keep.pk != pk].bpr)) if pk in set(keep.pk) else \
                team_value(list(keep.bpr) + [b]) - base                     # already out: what he'd add back
            lst.append([p, round(float(b), 1), int(rk), round(v / 10.35 * 9.5, 1)])
        players[tr] = [x for x in sorted(lst, key=lambda x: x[2]) if x[2] <= a.top]   # outside the top 10 the curve value is ~0
doc = {'date': D, 'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'games': games, 'players': players}
s = json.dumps(doc, separators=(',', ':'))
json.dump(doc, open(a.out, 'w'), separators=(',', ':'))
print(f'tracker today {D}: {len(games)} teams, {sum(len(v) for v in players.values())} players, {len(s) // 1024} KB -> {a.out}')
