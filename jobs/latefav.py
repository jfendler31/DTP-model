"""Late-game favorite study: data pull (research, not part of the daily card).

Question (Jon, Nov 6 2026): do sloppy favorites (high turnover rate, poor FT%) of roughly 6-12 points
win at the rate their line implies but cover less often, because the last minutes of a game that is
"just competitive enough" (pressing, fouling) shave the margin without flipping the result?

This job pulls what the test needs for past seasons and writes compact per-game files. It does not
analyse; jobs/latefav_analyze.py does.

Sources (CollegeBasketballData, one key: CBBD_API_KEY):
  /games/teams  (10-day windows)  box score per team-game: points, possessions, turnovers, FTA/FTM
  /lines        (10-day windows)  every provider's closing spread -> median = consensus close
  /plays/date   (one call per day) score and clock on every play -> margin at 8:00 / 4:00 / 2:00 left in
                                   regulation, regulation-end and final margin, and each side's turnovers,
                                   FTA/FTM and fouls in the last 4:00 of regulation

Outputs (data/research/latefav/):
  games_<season>.csv   one row per game: teams, venue, final score, consensus closing spread (home view),
                       each side's game box (poss, to, fta, ftm)
  late_<season>.csv    one row per game from play-by-play (see above)

Usage: python jobs/latefav.py --seasons 2025 2026     (CBBD season = the year it ends; 2026 = 2025-26)
Re-running skips dates already in late_<season>.csv.
"""
import os, sys, csv, time, argparse, statistics as st, datetime as dt, collections

import requests

OUT = 'data/research/latefav'
BASE = 'https://api.collegebasketballdata.com'


def getter():
    key = os.environ.get('CBBD_API_KEY')
    if not key:
        sys.exit('CBBD_API_KEY not set')
    hdr = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
    calls = [0]

    def get(path, **p):
        for i in range(6):
            try:
                r = requests.get(BASE + path, headers=hdr, params=p, timeout=180)
            except requests.RequestException as e:
                print(f'  network error {path} {p}: {e}', flush=True); time.sleep(2 ** i + 1); continue
            if r.status_code == 200:
                calls[0] += 1; time.sleep(0.3); return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** i + 1); continue
            raise RuntimeError(f'HTTP {r.status_code} on {path} {p}: {r.text[:200]}')
        raise RuntimeError(f'gave up on {path} {p}')
    get.calls = calls
    return get


def windows(a, b, days=10):
    d = a
    while d < b:
        e = min(d + dt.timedelta(days=days), b)
        yield d.isoformat(), e.isoformat()
        d = e


def g(d, *ks):
    for k in ks:
        if not isinstance(d, dict): return None
        d = d.get(k)
    return d


def write(path, rows, keys=None):
    if not rows: return
    keys = keys or list(rows[0].keys())
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    print(f'  wrote {path} ({len(rows)} rows)', flush=True)


# ------------------------------------------------------------------ games + lines
def pull_games(get, season, a, b):
    tg = {}
    for s, e in windows(a, b):
        for r in get('/games/teams', season=season, startDateRange=s, endDateRange=e):
            tg[(r.get('gameId'), r.get('isHome'))] = r
    lines = collections.defaultdict(list)
    for s, e in windows(a, b):
        for gm in get('/lines', season=season, startDateRange=s, endDateRange=e):
            for ln in gm.get('lines') or []:
                if ln.get('spread') is not None:
                    lines[gm.get('gameId')].append(float(ln['spread']))
    rows = []
    for (gid, is_home), r in tg.items():
        if not is_home and (gid, True) in tg:
            continue                                 # one row per game, from the home row
        ts, os_ = r.get('teamStats') or {}, r.get('opponentStats') or {}
        if is_home:
            hs, as_, home, away, hid, aid = ts, os_, r.get('team'), r.get('opponent'), r.get('teamId'), r.get('opponentId')
        else:                                        # neutral/away-only row: orient as listed
            hs, as_, home, away, hid, aid = os_, ts, r.get('opponent'), r.get('team'), r.get('opponentId'), r.get('teamId')
        sp = lines.get(gid)
        rows.append(dict(
            gameId=gid, season=season, date=(r.get('startDate') or '')[:10], neutral=r.get('neutralSite'),
            home=home, away=away, homeId=hid, awayId=aid,
            home_pts=g(hs, 'points', 'total'), away_pts=g(as_, 'points', 'total'),
            spread_home=st.median(sp) if sp else None, n_books=len(sp or []),
            home_poss=g(hs, 'possessions'), away_poss=g(as_, 'possessions'),
            home_to=g(hs, 'turnovers', 'total'), away_to=g(as_, 'turnovers', 'total'),
            home_fta=g(hs, 'freeThrows', 'attempted'), away_fta=g(as_, 'freeThrows', 'attempted'),
            home_ftm=g(hs, 'freeThrows', 'made'), away_ftm=g(as_, 'freeThrows', 'made'),
            home_pf=g(hs, 'fouls', 'total'), away_pf=g(as_, 'fouls', 'total')))
    rows.sort(key=lambda x: (x['date'], x['gameId']))
    return rows


# ------------------------------------------------------------------ play-by-play
LATE = 240           # last 4:00 of regulation
MARKS = {'m8': 480, 'm4': 240, 'm2': 120}


def classify(x):
    t = (x.get('playType') or '').lower()
    txt = (x.get('playText') or '').lower()
    if 'free throw' in t or 'freethrow' in t or 'free throw' in txt:
        return 'ftm' if ('made' in txt or (x.get('scoringPlay') and 'missed' not in txt)) else 'ftx'
    if 'turnover' in t or 'turnover' in txt:
        return 'to'
    if 'foul' in t and 'technical' not in t:
        return 'pf'
    return None


def late_row(gid, plays):
    plays = [x for x in plays if x.get('period') is not None and x.get('secondsRemaining') is not None
             and x.get('homeScore') is not None and x.get('awayScore') is not None]
    if not plays:
        return None
    plays.sort(key=lambda x: (x['period'], -x['secondsRemaining'], x.get('id') or 0))
    reg = [x for x in plays if x['period'] <= 2]
    if not reg or max(x['period'] for x in reg) < 2:
        return None
    row = dict(gameId=gid, date=str(plays[0].get('gameStartDate', ''))[:10],
               home=plays[0].get('team') if plays[0].get('isHomeTeam') else plays[0].get('opponent'),
               periods=max(x['period'] for x in plays))
    for name, sec in MARKS.items():
        before = [x for x in reg if x['period'] == 1 or x['secondsRemaining'] >= sec]
        row[name] = (before[-1]['homeScore'] - before[-1]['awayScore']) if before else 0
    row['reg_end'] = reg[-1]['homeScore'] - reg[-1]['awayScore']
    row['final'] = plays[-1]['homeScore'] - plays[-1]['awayScore']
    cnt = collections.Counter()
    for x in reg:
        if x['period'] == 2 and x['secondsRemaining'] < LATE:
            c = classify(x)
            if c and x.get('isHomeTeam') is not None:
                cnt[('h' if x['isHomeTeam'] else 'a') + '_' + c] += 1
    for s in 'ha':
        row[f'{s}_late_to'] = cnt[f'{s}_to']
        row[f'{s}_late_ftm'] = cnt[f'{s}_ftm']
        row[f'{s}_late_fta'] = cnt[f'{s}_ftm'] + cnt[f'{s}_ftx']
        row[f'{s}_late_pf'] = cnt[f'{s}_pf']
    return row


LATE_KEYS = ['gameId', 'date', 'home', 'periods', 'm8', 'm4', 'm2', 'reg_end', 'final',
             'h_late_to', 'h_late_ftm', 'h_late_fta', 'h_late_pf', 'a_late_to', 'a_late_ftm', 'a_late_fta', 'a_late_pf']


def log(season, line):
    with open(f'{OUT}/log_{season}.txt', 'a') as f:
        f.write(line + '\n')
    print(line, flush=True)


def pull_late(get, season, dates, games, probe=0):
    path = f'{OUT}/late_{season}.csv'
    have, rows = set(), []
    if os.path.exists(path):
        with open(path) as f:
            rows = list(csv.DictReader(f))
        have = {r['date'] for r in rows}
    expected = collections.Counter(x['date'] for x in games if x.get('spread_home') not in (None, ''))
    todo = [d for d in dates if d not in have]
    log(season, f'play-by-play: {len(todo)} dates to pull ({len(have)} already done)')
    for i, d in enumerate(todo, 1):
        try:
            data = get('/plays/date', date=d, utcOffset=-5)
        except Exception as e:
            log(season, f'{d}\tERROR\t{type(e).__name__}: {e}')
            continue
        by = collections.defaultdict(list)
        for x in data:
            by[x.get('gameId')].append(x)
        n0, bad = len(rows), 0
        for gid, ps in by.items():
            try:
                r = late_row(gid, ps)
            except Exception as e:
                bad += 1
                continue
            if r:
                r['date'] = d
                rows.append(r)
        log(season, f'{d}\tplays {len(data)}\tgames_in_pbp {len(by)}\tkept {len(rows) - n0}\t'
                    f'lined_games_that_date {expected.get(d, 0)}\tparse_errors {bad}')
        if i % 20 == 0:
            write(path, rows, LATE_KEYS)             # checkpoint
    write(path, rows, LATE_KEYS)
    if probe:                                         # are missing games simply absent from CBBD play-by-play?
        got = {str(r['gameId']) for r in rows}
        miss = [x for x in games if x.get('spread_home') not in (None, '') and str(x['gameId']) not in got][:probe]
        for x in miss:
            try:
                ps = get(f'/plays/game/{x["gameId"]}')
                log(season, f'probe {x["gameId"]} {x["date"]} {x["away"]} at {x["home"]}: /plays/game returned {len(ps)} plays')
            except Exception as e:
                log(season, f'probe {x["gameId"]}: ERROR {e}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', type=int, default=[2025, 2026])
    ap.add_argument('--skip-plays', action='store_true')
    ap.add_argument('--probe', type=int, default=0, help='check this many missing lined games via /plays/game')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    get = getter()
    for season in a.seasons:
        start, end = dt.date(season - 1, 11, 1), dt.date(season, 4, 10)
        print(f'== season {season} ({start}..{end})', flush=True)
        gp = f'{OUT}/games_{season}.csv'
        if os.path.exists(gp):
            with open(gp) as f:
                games = list(csv.DictReader(f))
            print(f'  games: {len(games)} (existing file)', flush=True)
        else:
            games = pull_games(get, season, start, end)
            write(gp, games)
            print(f'  games: {len(games)}, with a closing spread: {sum(1 for x in games if x["spread_home"] is not None)}',
                  flush=True)
        if not a.skip_plays:
            dates = sorted({x['date'] for x in games if x['date']})
            pull_late(get, season, dates, games, a.probe)
    print(f'CBBD calls this run: {get.calls[0]}', flush=True)


if __name__ == '__main__':
    main()
