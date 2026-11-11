"""Player histories from CollegeBasketballData.
  --seasons 2023-2026   /stats/player/season for each season (all D-I players) -> data/players/history/season_stats_<y>.csv
  --rosters A,B         /teams/roster (ALL = every team) for the current season (height, weight, class, hometown) -> data/players/history/roster_<y>_<team>.csv
Usage: python jobs/player_hist.py --seasons 2023-2026 --rosters "Minnesota,Cincinnati" [--roster-season 2027]"""
import os, time, argparse
import pandas as pd, requests
ap = argparse.ArgumentParser(); ap.add_argument('--seasons'); ap.add_argument('--rosters'); ap.add_argument('--roster-season', type=int, default=2027)
a = ap.parse_args()
hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
def get(path, **p):
    for i in range(5):
        r = requests.get('https://api.collegebasketballdata.com' + path, headers=hdr, params=p, timeout=90)
        if r.status_code == 200: time.sleep(0.3); return r.json()
        if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
        print(path, p, r.status_code, r.text[:200]); return []
    return []
out = 'data/players/history'; os.makedirs(out, exist_ok=True)
if a.seasons:
    y1, y2 = map(int, a.seasons.split('-'))
    for y in range(y1, y2 + 1):
        df = pd.json_normalize(get('/stats/player/season', season=y))
        df.to_csv(f'{out}/season_stats_{y}.csv', index=False); print(f'season stats {y}: {len(df)} players; columns {list(df.columns)[:40]}')
if a.rosters:
    for t in [s.strip() for s in a.rosters.split(',') if s.strip()]:
        data = get('/teams/roster', season=a.roster_season) if t == 'ALL' else get('/teams/roster', season=a.roster_season, team=t)   # ALL = every D-I team
        rows = []
        for tm in data or []:
            for pl in tm.get('players') or []:
                rows.append({'team': tm.get('team'), **pl})
        df = pd.json_normalize(rows); df.to_csv(f"{out}/roster_{a.roster_season}_{t.replace(' ', '_')}.csv", index=False)
        print(f'roster {t}: {len(df)} players; columns {list(df.columns)}')
