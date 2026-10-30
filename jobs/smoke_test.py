"""Plumbing test for the daily card: Odds API key, rotation numbers, Gmail sending.
Pulls every upcoming NCAAB game with spreads/totals, writes one row per game (consensus = most common number
across books, on the half-point), and emails the CSV. Uses 2 Odds API credits."""
import os, io, smtplib, statistics, collections, datetime as dt
from email.message import EmailMessage
from zoneinfo import ZoneInfo
import requests, pandas as pd

ET = ZoneInfo('America/New_York')
r = requests.get('https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds',
                 params=dict(apiKey=os.environ['ODDS_API_KEY'].strip(), regions='us', markets='spreads,totals',
                             oddsFormat='american', includeRotationNumbers='true'), timeout=60)
r.raise_for_status()
left = r.headers.get('x-requests-remaining')
games = r.json()

def mode_half(xs):
    if not xs: return None
    c = collections.Counter(xs).most_common()
    top = [v for v, n in c if n == c[0][1]]
    m = top[0] if len(top) == 1 else statistics.median(xs)
    return round(m * 2) / 2

rows = []
for g in games:
    home, away = g['home_team'], g['away_team']
    hs, tot = [], []
    for b in g.get('bookmakers', []):
        for mk in b.get('markets', []):
            for o in mk.get('outcomes', []):
                if mk['key'] == 'spreads' and o['name'] == home and o.get('point') is not None: hs.append(o['point'])
                if mk['key'] == 'totals' and o['name'] == 'Over' and o.get('point') is not None: tot.append(o['point'])
    tip = dt.datetime.fromisoformat(g['commence_time'].replace('Z', '+00:00')).astimezone(ET)
    rows.append(dict(rot_away=g.get('away_rotation_number'), rot_home=g.get('home_rotation_number'),
                     tip_ET=tip.strftime('%a %b %-d %-I:%M %p'), away=away, home=home,
                     home_spread=mode_half(hs), total=mode_half(tot), n_books=len(g.get('bookmakers', []))))
df = pd.DataFrame(rows).sort_values('tip_ET') if rows else pd.DataFrame(columns=['note'])
with_rot = int(df['rot_away'].notna().sum()) if rows else 0
buf = io.StringIO(); df.to_csv(buf, index=False)

msg = EmailMessage()
msg['Subject'] = f'DTP card smoke test: {len(rows)} games, {with_rot} with ROTs'
msg['From'] = os.environ['GMAIL_USER'].strip(); msg['To'] = os.environ['CARD_TO'].strip()
msg.set_content(f'Games returned: {len(rows)}\nGames with rotation numbers: {with_rot}\n'
                f'Odds API credits remaining: {left}\nRun at {dt.datetime.now(ET):%a %b %-d %-I:%M %p} ET\n')
msg.add_attachment(buf.getvalue().encode('utf-8-sig'), maintype='text', subtype='csv', filename='smoke_test.csv')
with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
    s.login(os.environ['GMAIL_USER'].strip(), os.environ['GMAIL_APP_PASSWORD'].replace(' ', '').strip())
    s.send_message(msg)
print(f'sent: {len(rows)} games, {with_rot} with ROTs, credits left {left}')
