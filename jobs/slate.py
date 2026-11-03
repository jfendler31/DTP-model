"""Daily slate from ESPN's public scoreboard (stopgap until the CBBD schedule feed is wired).
Writes data/slate_<date>.csv in the card's format: date, tip_ET, away, home, venue (H/N), site.
Team names are mapped to KenPom spelling (the names in data/prior_2026-27.csv). Games with a team that
can't be mapped (non-D-I opponents, unknown spellings) are left out and listed in the log.
Usage: python jobs/slate.py [--date YYYY-MM-DD] [--force]   (skips if the slate file already exists unless --force)"""
import os, sys, json, argparse, datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd, requests
sys.path.insert(0, os.path.dirname(__file__)); from absence_sweep import make_fixer
ET = ZoneInfo('America/New_York')
ap = argparse.ArgumentParser(); ap.add_argument('--date'); ap.add_argument('--force', action='store_true'); a = ap.parse_args()
day = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
out_f = f'data/slate_{day}.csv'
if os.path.exists(out_f) and not a.force: print(out_f, 'already exists - skipping'); sys.exit(0)

P = pd.read_csv('data/prior_2026-27.csv'); K = set(P.team); fix = make_fixer(P.team)
xa = json.load(open('data/xwalk_oddsapi_cbbd.json')); xb = json.load(open('data/xwalk_cbbd_kp.json'))
EXTRA = {'New Haven Chargers': 'New Haven', 'West Florida Argonauts': 'West Florida', 'New Orleans Privateers': 'LSU New Orleans',
         'Miami Hurricanes': 'Miami FL', 'Miami (OH) RedHawks': 'Miami OH', 'Queens University Royals': 'Queens',
         'Wright St Raiders': 'Wright St.', 'Air Force Falcons': 'Air Force'}
LOC = {'UConn': 'Connecticut', 'Ole Miss': 'Mississippi', 'Miami': 'Miami FL', 'Miami (OH)': 'Miami OH', 'NC State': 'N.C. State',
       "Hawai'i": 'Hawaii', 'San José State': 'San Jose St.', 'App State': 'Appalachian St.', 'UMass': 'Massachusetts',
       'Texas A&M-Corpus Christi': 'Texas A&M Corpus Chris', 'East Texas A&M': 'East Texas A&M', 'UT Martin': 'Tennessee Martin',
       'Southeast Missouri State': 'Southeast Missouri', 'SE Louisiana': 'Southeastern Louisiana', 'UL Monroe': 'Louisiana Monroe',
       'Long Island University': 'LIU', 'St. Thomas-Minnesota': 'St. Thomas', 'UAlbany': 'Albany', 'Omaha': 'Nebraska Omaha',
       'Purdue Fort Wayne': 'Purdue Fort Wayne', 'IU Indianapolis': 'IU Indy', "Mount St. Mary's": "Mount St. Mary's",
       'Loyola Maryland': 'Loyola MD', 'Loyola Chicago': 'Loyola Chicago', 'Sam Houston': 'Sam Houston St.',
       'Grambling': 'Grambling St.', 'Kansas City': 'UMKC', 'California Baptist': 'Cal Baptist', 'Pennsylvania': 'Penn',
       'Florida International': 'FIU', 'Seattle U': 'Seattle', 'McNeese': 'McNeese', 'Nicholls': 'Nicholls',
       'Gardner-Webb': 'Gardner Webb', 'Bethune-Cookman': 'Bethune Cookman', 'Arkansas-Pine Bluff': 'Arkansas Pine Bluff',
       'Maryland-Eastern Shore': 'Maryland Eastern Shore', 'Southern Miss': 'Southern Miss', 'Saint Francis': 'Saint Francis'}
def kp(display, loc):
    if display in EXTRA: return EXTRA[display]
    c = xb.get(xa.get(display, ''), None)
    if c in K: return c
    for n in (LOC.get(loc), loc, loc.replace('State', 'St.'), loc.replace('Saint ', 'St. ')):
        if n and n in K: return n
        f = n and fix(n)
        if f: return f
    return None

ymd = day.replace('-', '')
r = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard',
                 params=dict(dates=ymd, groups=50, limit=500), timeout=60)
r.raise_for_status(); ev = r.json().get('events', [])
rows, skipped = [], []
for e in ev:
    c = e['competitions'][0]; t = dt.datetime.fromisoformat(e['date'].replace('Z', '+00:00')).astimezone(ET)
    if t.strftime('%Y-%m-%d') != day: continue
    side = {x['homeAway']: x['team'] for x in c['competitors']}
    aw, hm = (kp(side[s].get('displayName', ''), side[s].get('location', '')) for s in ('away', 'home'))
    if not aw or not hm:
        skipped.append(f"{side['away'].get('displayName')} @ {side['home'].get('displayName')}"); continue
    v = c.get('venue', {}); city = v.get('address', {}).get('city', '')
    rows.append(dict(date=day, tip_ET=f"{t:%a %b} {t.day} {t:%-I:%M %p}", away=aw, home=hm,
                     venue='N' if c.get('neutralSite') else 'H', site=f"{v.get('fullName', '')}, {city}".strip(', ')))
S = pd.DataFrame(rows, columns=['date', 'tip_ET', 'away', 'home', 'venue', 'site'])
S.to_csv(out_f, index=False)
print(f'{out_f}: {len(S)} games ({int((S.venue == "N").sum())} neutral); {len(skipped)} left out (team not in KenPom list):')
for s in skipped: print('   ', s)
