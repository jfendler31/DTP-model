"""Player box scores from CollegeBasketballData (/games/players) for a date range (ET dates, inclusive).
Writes data/players/players_<start>_<end>.csv, one row per player-game, nested stat blocks flattened (e.g. fieldGoals.made).
Usage: python jobs/players.py --start 2026-11-02 [--end 2026-11-02] [--season 2026 --team Minnesota]
Past-season or single-team pulls are written to data/players/history/."""
import os, time, argparse, datetime as dt
import pandas as pd, requests
ap = argparse.ArgumentParser(); ap.add_argument('--start', required=True); ap.add_argument('--end'); ap.add_argument('--season', type=int, default=2027); ap.add_argument('--team'); a = ap.parse_args()
end = a.end or a.start
hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
def get(path, **p):
    for i in range(5):
        r = requests.get('https://api.collegebasketballdata.com' + path, headers=hdr, params=p, timeout=60)
        if r.status_code == 200: time.sleep(0.3); return r.json()
        if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
        r.raise_for_status()
    raise SystemExit('gave up')
# UTC window wide enough to cover late ET tips
s = dt.date.fromisoformat(a.start); e = dt.date.fromisoformat(end) + dt.timedelta(days=2)
params = dict(season=a.season, startDateRange=s.isoformat(), endDateRange=e.isoformat())
if a.team: params['team'] = a.team
data = get('/games/players', **params)
rows = []
for gm in data:
    base = {k: v for k, v in gm.items() if k != 'players'}
    for pl in gm.get('players') or []:
        rows.append({**base, **pl})
df = pd.json_normalize(rows)
if len(df):
    et = pd.to_datetime(df.startDate, utc=True).dt.tz_convert('America/New_York')
    df.insert(0, 'date_ET', et.dt.strftime('%Y-%m-%d'))
    df = df[(df.date_ET >= a.start) & (df.date_ET <= end)]
# past seasons / single-team pulls go to data/players/history/ so this season's globs never pick them up
out = 'data/players' if a.season == 2027 and not a.team else 'data/players/history'
os.makedirs(out, exist_ok=True)
fn = f'{out}/players_{a.start}_{end}' + (f'_{a.team.replace(" ", "_")}' if a.team else '') + '.csv'; df.to_csv(fn, index=False)
print(fn, len(df), 'player rows,', df.gameId.nunique() if len(df) else 0, 'games'); print('columns:', list(df.columns))
