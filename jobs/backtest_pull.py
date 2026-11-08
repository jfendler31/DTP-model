"""Backtest stores for past seasons, November-December only (Jon, Nov 8): box scores, CBBD lines and the
play-by-play four-factor totals the live ratings use, so the old (box) and new (competitive, game-weighted)
ratings can be compared on two spent seasons.

Per season S (CBBD season = the year it ends; 2025 = 2024-25, 2026 = 2025-26), Nov 1 through Dec 31:
  data/backtest/games_<S>.csv          team-game box rows, same columns as data/games_2026-27.csv (+ conference fields)
  data/backtest/lines_<S>.csv          one row per game: median home spread open/close and total open/close across books
  data/backtest/game_factors_<S>.csv   jobs/pbp_factors.py output (raw / cw / cc), same as data/pbp/game_factors.csv
  data/backtest/done_<S>.txt           dates whose play-by-play is stored (re-runs skip them)

Play-by-play: /plays/date per date, then /plays/game/{id} for D-I vs D-I games (both teams carry a conference)
that the date feed left out. --max-calls caps CBBD calls per run (the plan's call allowance is shared with the
daily pipeline); a run that hits the cap stops after the current date and the next run resumes.
Usage: python jobs/backtest_pull.py --season 2025 [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--max-calls N] [--no-box]
"""
import os, sys, json, time, argparse, statistics as st, datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rotation import by_game, et_date
from tempo import parse_game
from pbp_factors import game_factors

ET = ZoneInfo('America/New_York')
OUT = 'data/backtest'
CALLS = 0


def api():
    import requests
    hdr = {'Authorization': f"Bearer {os.environ['CBBD_API_KEY'].strip()}", 'Accept': 'application/json'}
    def get(path, **p):
        global CALLS
        for i in range(5):
            CALLS += 1
            try:
                r = requests.get('https://api.collegebasketballdata.com' + path, headers=hdr, params=p, timeout=300)
            except requests.RequestException as e:
                print(f'  {path} {p}: {type(e).__name__}, retry {i + 1}', flush=True); time.sleep(5 * (i + 1)); continue
            if r.status_code == 200: time.sleep(0.3); return r.json()
            if r.status_code == 401: raise SystemExit('CBBD 401 - check the CBBD_API_KEY secret')
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 1); continue
            print(f'  {path} {p}: HTTP {r.status_code}', flush=True); return None
        print(f'  gave up on {path} {p}', flush=True); return None
    return get


def g(x, *ks):
    for k in ks: x = x.get(k) if isinstance(x, dict) else None
    return x

def side(s):
    return dict(pts=g(s, 'points', 'total'), poss=g(s, 'possessions'), p2m=g(s, 'twoPointFieldGoals', 'made'), p2a=g(s, 'twoPointFieldGoals', 'attempted'),
                p3m=g(s, 'threePointFieldGoals', 'made'), p3a=g(s, 'threePointFieldGoals', 'attempted'), fta=g(s, 'freeThrows', 'attempted'),
                fga=g(s, 'fieldGoals', 'attempted'), orb=g(s, 'rebounds', 'offensive'), drb=g(s, 'rebounds', 'defensive'), to=g(s, 'turnovers', 'total'))


def pull_box(get, season, start, end):
    rows, seen, d = [], set(), start
    while d <= end:
        e = min(d + dt.timedelta(days=10), end + dt.timedelta(days=1))
        for r in get('/games/teams', season=season, startDateRange=d.isoformat(), endDateRange=e.isoformat()) or []:
            k = (r.get('gameId'), r.get('teamId'))
            if k in seen: continue
            seen.add(k)
            t = dt.datetime.fromisoformat(str(r.get('startDate')).replace('Z', '+00:00')).astimezone(ET)
            rec = dict(gameId=r.get('gameId'), date=t.strftime('%Y-%m-%d'), seasonType=r.get('seasonType'), team=r.get('team'), opp=r.get('opponent'),
                       isHome=r.get('isHome'), neutral=r.get('neutralSite'), conf=r.get('conference'), opp_conf=r.get('opponentConference'))
            rec.update(side(r.get('teamStats'))); rec.update({'opp_' + k: v for k, v in side(r.get('opponentStats')).items()})
            rows.append(rec)
        d = e
    TG = pd.DataFrame(rows)
    TG = TG[(TG.date >= start.isoformat()) & (TG.date <= end.isoformat())]
    return TG


def pull_lines(get, season, start, end):
    out, d = [], start
    while d <= end:
        e = min(d + dt.timedelta(days=10), end + dt.timedelta(days=1))
        for x in get('/lines', season=season, startDateRange=d.isoformat(), endDateRange=e.isoformat()) or []:
            ln = x.get('lines') or []
            med = lambda k: st.median([float(l[k]) for l in ln if l.get(k) is not None]) if any(l.get(k) is not None for l in ln) else None
            out.append(dict(gameId=x.get('gameId') or x.get('id'), startDate=x.get('startDate'), homeTeam=x.get('homeTeam'), awayTeam=x.get('awayTeam'),
                            homeScore=x.get('homeScore'), awayScore=x.get('awayScore'), n_books=len(ln),
                            spread_open=med('spreadOpen'), spread_close=med('spread'), total_open=med('overUnderOpen'), total_close=med('overUnder'),
                            providers='|'.join(str(l.get('provider')) for l in ln)))
        d = e
    L = pd.DataFrame(out)
    return L.drop_duplicates('gameId') if len(L) else L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, required=True); ap.add_argument('--start'); ap.add_argument('--end')
    ap.add_argument('--max-calls', type=int, default=1800); ap.add_argument('--no-box', action='store_true')
    a = ap.parse_args()
    S = a.season
    start = dt.date.fromisoformat(a.start) if a.start else dt.date(S - 1, 11, 1)
    end = dt.date.fromisoformat(a.end) if a.end else dt.date(S - 1, 12, 31)
    os.makedirs(OUT, exist_ok=True)
    get = api()
    f_games, f_lines, f_fac, f_done = (f'{OUT}/{n}_{S}.{x}' for n, x in (('games', 'csv'), ('lines', 'csv'), ('game_factors', 'csv'), ('done', 'txt')))

    if a.no_box and os.path.exists(f_games):
        TG = pd.read_csv(f_games)
    else:
        TG = pull_box(get, S, dt.date(S - 1, 11, 1), dt.date(S - 1, 12, 31)); TG.to_csv(f_games, index=False)
        L = pull_lines(get, S, dt.date(S - 1, 11, 1), dt.date(S - 1, 12, 31)); L.to_csv(f_lines, index=False)
        print(f'season {S}: {TG.gameId.nunique()} games in the box store, {len(L)} with lines ({CALLS} calls)', flush=True)
    d1 = TG[TG.conf.notna() & TG.opp_conf.notna() & (TG.isHome == True)]
    done = set(open(f_done).read().split()) if os.path.exists(f_done) else set()
    fac_old = pd.read_csv(f_fac) if os.path.exists(f_fac) else pd.DataFrame()

    cache = {}                                           # date feed responses, so each date is fetched once
    d = start
    while d <= end:
        ds = d.isoformat()
        if ds in done: d += dt.timedelta(days=1); continue
        want = d1[d1.date == ds].gameId.astype(int).unique().tolist()
        if not want: done.add(ds); d += dt.timedelta(days=1); continue
        if CALLS + 2 + len(want) > a.max_calls:
            print(f'stopping before {ds}: {CALLS} calls used, cap {a.max_calls} (next run resumes here)', flush=True); break
        games = {}
        for q in (d, d + dt.timedelta(days=1)):          # an ET evening can spill into the next date's feed
            qs = q.isoformat()
            if qs not in cache:
                cache.clear() if len(cache) > 2 else None
                cache[qs] = by_game(get('/plays/date', date=qs, utcOffset=-5) or [])
            for gid, pl in cache[qs].items():
                if int(gid) in want and et_date(pl[0]['gameStartDate']) == ds:
                    have = games.setdefault(int(gid), {})
                    for x in pl: have[x['id']] = x
        games = {gid: list(v.values()) for gid, v in games.items()}
        miss = [gid for gid in want if gid not in games]
        for gid in miss:
            pl = get(f'/plays/game/{gid}')
            if pl: games[gid] = pl
        rows = []
        for gid, plays in games.items():
            try:
                poss, meta = parse_game(gid, plays)
                if not poss: continue
                for f in game_factors(gid, plays, poss, meta): f['date'] = ds; rows.append(f)
            except Exception as e:
                print(f'  {ds} game {gid}: {type(e).__name__}: {e}', flush=True)
        if rows:
            new = pd.DataFrame(rows)
            if len(fac_old): fac_old = fac_old[~fac_old.gameId.isin(new.gameId)]
            fac_old = pd.concat([fac_old, new], ignore_index=True).sort_values(['date', 'gameId', 'team'])
            fac_old.to_csv(f_fac, index=False)
        done.add(ds); open(f_done, 'w').write('\n'.join(sorted(done)) + '\n')
        print(f'{ds}: {len(want)} D-I games, date feed {len(want) - len(miss)}, per-game {len(miss)}, parsed {len(rows) // 2}; calls so far {CALLS}', flush=True)
        d += dt.timedelta(days=1)
    left = sum(1 for i in range((end - start).days + 1) if (start + dt.timedelta(days=i)).isoformat() not in done)
    print(f'season {S}: {len(done)} dates stored, {left} left in {start}..{end}; {CALLS} CBBD calls this run', flush=True)


if __name__ == '__main__':
    main()
