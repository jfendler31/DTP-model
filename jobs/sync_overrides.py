"""Override sync — runs in the Daily card job right before card.py (Nov 10, Jon: "player tracking runs before the 4:15 card").

Rules (Jon, Nov 10): the box score controls. Overrides stay Jon's call to PRICE; this only retires them and flags gaps.
  1. Box score: an active override whose player logged minutes in a game on/after the override's `since` date is expired
     (expires = that game's date, reason notes the game). Venue rows are left alone.
  2. Tracker (secondary, only for players who haven't played): a visible tracker note that says playing / elig_tro / coach,
     updated on/after `since`, expires the override. A hidden note is not a status change.
  Flags (no changes, listed in the card email and data/tracker/sync_<date>.txt):
  - tracker says out, but the player has played after the day of that note -> update the tracker
  - tracker out-status for a team on today's slate, new or changed in the last 2 days, with no active override -> price it?
  - override expired by date in the last 3 days while the tracker still has him out and he hasn't played -> renew?
New overrides get `since` = the card date they first appear (filled in here if blank).
Usage: python jobs/sync_overrides.py [--date YYYY-MM-DD] [--offline]   (--offline: use stored data/players/*.csv, no API)"""
import os, sys, glob, argparse, datetime as dt, time
from zoneinfo import ZoneInfo
import pandas as pd, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from team_names import kp, pn

ap = argparse.ArgumentParser(); ap.add_argument('--date'); ap.add_argument('--offline', action='store_true'); a = ap.parse_args()
D = a.date or dt.datetime.now(ZoneInfo('America/New_York')).date().isoformat()
day = lambda s, k: (dt.date.fromisoformat(s) + dt.timedelta(days=k)).isoformat()
OUT = {'injured', 'out_season', 'ineligible', 'suspended', 'left', 'redshirt', 'personal'}
AVAIL = {'playing', 'elig_tro', 'eligibility', 'coach'}
OPEN = ('', 'until cleared', 'season')
log, changed = [], 0

O = pd.read_csv('data/overrides.csv', dtype=str).fillna('')
if 'since' not in O.columns: O['since'] = ''
O.loc[O.since == '', 'since'] = D
is_active = lambda r: r.expires in OPEN or r.expires >= D
is_venue = lambda r: r.player.startswith('(venue)')

# ---- box scores since the oldest active override (capped at 21 days), through yesterday
act = O[[is_active(r) and not is_venue(r) for r in O.itertuples()]]
start = max(min(act.since) if len(act) else day(D, -7), day(D, -21)); end = day(D, -1)
B = pd.DataFrame()
try:
    if a.offline:
        B = pd.concat([pd.read_csv(f, low_memory=False) for f in glob.glob('data/players/players_*.csv')], ignore_index=True)
    elif start <= end:
        hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
        for i in range(4):
            r = requests.get('https://api.collegebasketballdata.com/games/players', headers=hdr, timeout=90,
                             params=dict(season=2027, startDateRange=start, endDateRange=day(end, 2)))
            if r.status_code == 200: break
            time.sleep(2 ** i + 1)
        r.raise_for_status()
        rows = [{**{k: v for k, v in g.items() if k != 'players'}, **p} for g in r.json() for p in (g.get('players') or [])]
        B = pd.json_normalize(rows)
        if len(B): B.insert(0, 'date_ET', pd.to_datetime(B.startDate, utc=True).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d'))
    if len(B):
        B = B[(B.date_ET >= start) & (B.date_ET <= end) & (pd.to_numeric(B.minutes, errors='coerce').fillna(0) > 0)].copy()
        B['team_kp'] = B.team.map(lambda t: kp(t) or t); B['pk'] = B.name.map(pn)
        B = B.drop_duplicates(['gameId', 'team_kp', 'pk']).sort_values('date_ET')
except Exception as e:
    log.append(f'! box scores unavailable ({e}); box-score rule skipped today'); B = pd.DataFrame()
def played(team, player, since):
    if not len(B): return None
    x = B[(B.team_kp == team) & (B.pk == pn(player)) & (B.date_ET >= since)]
    return x.iloc[0] if len(x) else None

# ---- tracker export (written by the 4:15 scheduled task)
T = pd.DataFrame()
if os.path.exists('data/tracker/player_status.csv'):
    T = pd.read_csv('data/tracker/player_status.csv', dtype=str).fillna('')
    T['hidden'] = T.hidden.str.lower().eq('true'); T['pk'] = T.player.map(pn)
    log.append(f'tracker export: {len(T)} notes, latest edit {T.updated_et.max()}')
else:
    log.append('! no tracker export found (data/tracker/player_status.csv); tracker rule and flags skipped')
def tnote(team, player):
    if not len(T): return None
    x = T[(T.team == team) & (T.pk == pn(player)) & ~T.hidden]
    return x.iloc[0] if len(x) else None

# ---- rules 1-2: retire overrides
for i, r in O.iterrows():
    if is_venue(r) or not is_active(r): continue
    g = played(r.team, r.player, r.since)
    if g is not None:
        O.at[i, 'expires'] = min(g.date_ET, day(D, -1))
        O.at[i, 'reason'] = f"{r.reason} | auto-expired {D}: played {int(float(g.minutes))} min {g.date_ET} vs {g.opponent} (box score)"
        log.append(f'expired  {r.team} — {r.player} ({r.delta_pts}): played {int(float(g.minutes))} min {g.date_ET} vs {g.opponent}'); changed += 1; continue
    t = tnote(r.team, r.player)
    if t is not None and t.status in AVAIL and t.updated_et >= r.since:
        O.at[i, 'expires'] = min(t.updated_et, day(D, -1))
        O.at[i, 'reason'] = f"{r.reason} | auto-expired {D}: tracker says {t.status} ({t.updated_et}{': ' + t.details if t.details else ''})"
        log.append(f'expired  {r.team} — {r.player} ({r.delta_pts}): tracker says {t.status} ({t.updated_et})'); changed += 1

# ---- flags
slate = f'data/slate_{D}.csv'
teams = set(pd.read_csv(slate)[['away', 'home']].stack()) if os.path.exists(slate) else set()
live = {(r.team, pn(r.player)) for r in O.itertuples() if is_active(r) and not is_venue(r)}
if len(T):
    for t in T[~T.hidden & T.status.isin(OUT)].itertuples():
        g = played(t.team, t.player, day(t.updated_et, 1) if t.updated_et else start)   # strictly after the note's date
        if g is not None:
            log.append(f'tracker  {t.team} — {t.player}: tracker says {t.status}, but played {int(float(g.minutes))} min {g.date_ET} vs {g.opponent} — update the tracker')
        elif t.team in teams and (t.team, t.pk) not in live and t.updated_et >= day(D, -2):
            log.append(f'unpriced {t.team} — {t.player}: {t.status}{" (" + t.details + ")" if t.details else ""}, tracker {t.updated_et}, plays today, no override')
    for r in O.itertuples():
        if is_venue(r) or r.expires in OPEN or not (day(D, -3) <= r.expires < D) or 'auto-expired' in r.reason: continue
        if r.delta_pts in ('', '0', '0.0', '0.00', '-0.00'): continue
        t = tnote(r.team, r.player)
        if t is not None and t.status in OUT and played(r.team, r.player, r.since) is None and (r.team, pn(r.player)) not in live:
            log.append(f'renew?   {r.team} — {r.player} ({r.delta_pts}): override expired {r.expires}, tracker still {t.status} ({t.updated_et})')

O.to_csv('data/overrides.csv', index=False)
os.makedirs('data/tracker', exist_ok=True)
summary = f'Player sync {D}: {changed} override(s) expired; box scores {start} to {end}.\n' + '\n'.join(log)
open(f'data/tracker/sync_{D}.txt', 'w').write(summary + '\n')
print(summary)
