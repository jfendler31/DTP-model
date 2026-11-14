"""Override sync — runs in the Daily card job right before card.py (Nov 10, Jon: "player tracking runs before the 4:15 card").

Rules (Jon, Nov 10): the box score controls. Nov 14 (Jon): every out-type tracker status for a team on today's slate that has no
active override is now PRICED here (jobs/price_core.py, the same math as tools/price_tracker.py) and written as an override;
the status stays Jon's call. Player names match exact-then-fuzzy (team_names.match_name: Joe/Joseph, Josh/Joshua).
  1. Box score: an active override whose player logged minutes in a game on/after the override's `since` date is expired
     (expires = that game's date, reason notes the game). Venue rows are left alone.
  2. Tracker (secondary, only for players who haven't played): a visible tracker note that says playing / elig_tro / coach,
     updated on/after `since`, expires the override. A hidden note is not a status change.
  Flags (no changes, listed in the card email and data/tracker/sync_<date>.txt):
  - tracker says out, but the player has played after the day of that note -> update the tracker
  - tracker out-status for a team on today's slate with no active override (any age; Nov 13) -> priced and written (Nov 14),
    expires 'season' for out_season / left / redshirt, else 'until cleared'; since = the card date
  - override expired by date (last 3 days, or any time if his team plays today) while the tracker still has him out and he hasn't played -> renew?
New overrides get `since` = the card date they first appear (filled in here if blank).
Usage: python jobs/sync_overrides.py [--date YYYY-MM-DD] [--offline]   (--offline: use stored data/players/*.csv, no API)"""
import os, sys, glob, argparse, datetime as dt, time
from zoneinfo import ZoneInfo
import pandas as pd, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from team_names import kp, pn, match_name, same_player
from price_core import Pricer

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
    tb = B[B.team_kp == team]; m = match_name(player, tb.name.unique())
    if m is None: return None
    x = tb[(tb.name == m) & (tb.date_ET >= since)]
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
    tt = T[(T.team == team) & ~T.hidden]; m = match_name(player, list(tt.player))
    x = tt[tt.player == m] if m is not None else tt.iloc[0:0]
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
def has_override(team, player):
    return any(same_player(player, r.player) for r in O.itertuples() if r.team == team and is_active(r) and not is_venue(r))
O.to_csv('data/overrides.csv', index=False)          # rule 1-2 changes on disk before pricing reads the active set
SEASON = {'out_season', 'left', 'redshirt'}
pricer, priced = None, 0
if len(T):
    for t in T[~T.hidden & T.status.isin(OUT)].itertuples():
        g = played(t.team, t.player, day(t.updated_et, 1) if t.updated_et else start)   # strictly after the note's date
        if g is not None:
            log.append(f'tracker  {t.team} — {t.player}: tracker says {t.status}, but played {int(float(g.minutes))} min {g.date_ET} vs {g.opponent} — update the tracker')
        elif t.team in teams and not has_override(t.team, t.player):
            # Nov 13 (Jon): every out-status for a team playing today with no active override, whatever its age.
            # Nov 14 (Jon): price it and write the override (was: flag only).
            note = f'{t.status}{" (" + t.details + ")" if t.details else ""}, tracker {t.updated_et}'
            try:
                pricer = pricer or Pricer(D, box=B)
                r = pricer.price(t.team, t.player, 1.0)
            except Exception as e:
                r = dict(ok=False, text=f'pricing error {e}')
            if not r['ok']:
                log.append(f'unpriced {t.team} — {t.player}: {note}, plays today — {r["text"]}'); continue
            row = dict(team=t.team, player=t.player, status='out', delta_pts=f'{-r["delta"]:.2f}', expires='season' if t.status in SEASON else 'until cleared',
                       reason=f'auto-priced {D} from tracker ({note}); {r["text"]}' + (f'; on top of {", ".join(r["cascade"])}' if r['cascade'] else ''), since=D)
            O = pd.concat([O, pd.DataFrame([row])], ignore_index=True); priced += 1
            log.append(f'priced   {t.team} — {t.player}: {note} -> {r["spread"]:.1f} spread (delta_pts {row["delta_pts"]}, {row["expires"]})')
    for r in O.itertuples():
        # Nov 11: any date-expired override the tracker still has out is flagged when the team plays today (Grahovac missed the 3-day window);
        # otherwise only those expired in the last 3 days
        if is_venue(r) or r.expires in OPEN or not r.expires < D or 'auto-expired' in r.reason: continue
        if not (r.expires >= day(D, -3) or r.team in teams): continue
        if r.delta_pts in ('', '0', '0.0', '0.00', '-0.00'): continue
        t = tnote(r.team, r.player)
        if t is not None and t.status in OUT and played(r.team, r.player, r.since) is None and not has_override(r.team, r.player):
            log.append(f'renew?   {r.team} — {r.player} ({r.delta_pts}): override expired {r.expires}, tracker still {t.status} ({t.updated_et})')

O.to_csv('data/overrides.csv', index=False)
os.makedirs('data/tracker', exist_ok=True)
summary = f'Player sync {D}: {changed} override(s) expired, {priced} priced from the tracker; box scores {start} to {end}.\n' + '\n'.join(log)
open(f'data/tracker/sync_{D}.txt', 'w').write(summary + '\n')
print(summary)
