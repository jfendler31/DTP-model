"""Pull current NCAAB spreads/totals from The Odds API, one row per game per book, and save to data/lines/.
Book keys: williamhill_us = Caesars. Uses 2 credits per run (regions=us, markets=spreads,totals)."""
import os, datetime as dt
from zoneinfo import ZoneInfo
import requests, pandas as pd
ET = ZoneInfo('America/New_York')
r = requests.get('https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds',
                 params=dict(apiKey=os.environ['ODDS_API_KEY'].strip(), regions='us', markets='spreads,totals', oddsFormat='american'), timeout=60)
r.raise_for_status()
now = dt.datetime.now(ET)
rows = []
for g in r.json():
    tip = dt.datetime.fromisoformat(g['commence_time'].replace('Z', '+00:00')).astimezone(ET)
    for b in g.get('bookmakers', []):
        rec = dict(pulled_ET=now.strftime('%Y-%m-%d %H:%M'), tip_ET=tip.strftime('%Y-%m-%d %H:%M'), away=g['away_team'], home=g['home_team'],
                   book=b['key'], book_updated=b.get('last_update', ''), home_spread=None, home_price=None, total=None, over_price=None)
        for mk in b.get('markets', []):
            for o in mk.get('outcomes', []):
                if mk['key'] == 'spreads' and o['name'] == g['home_team']: rec['home_spread'], rec['home_price'] = o.get('point'), o.get('price')
                if mk['key'] == 'totals' and o['name'] == 'Over': rec['total'], rec['over_price'] = o.get('point'), o.get('price')
        rows.append(rec)
df = pd.DataFrame(rows)
os.makedirs('data/lines', exist_ok=True)
out = f"data/lines/lines_{now:%Y-%m-%d_%H%M}.csv"
df.to_csv(out, index=False)
print(out, len(df), 'rows,', df[['away', 'home']].drop_duplicates().shape[0] if len(df) else 0, 'games; credits left', r.headers.get('x-requests-remaining'))
