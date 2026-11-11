"""KenPom API pull: today's ratings and FanMatch (inputs to the totals shadow log).

Docs: https://kenpom.com/api-documentation.php — GET https://kenpom.com/api.php?endpoint=<name>&...,
header Authorization: Bearer <KENPOM_API_KEY>. FanMatch is available for dates up to and including today.

Outputs (data/kenpom/):
  ratings_<date>.csv    endpoint=ratings&y=<season>: AdjOE / AdjDE / AdjTempo / APL_Off / APL_Def ... as of the pull
  ratings_current.csv   copy of the latest
  fanmatch_<date>.csv   endpoint=fanmatch&d=<date>: GameID, Visitor, Home, VisitorPred, HomePred, HomeWP, PredTempo
  preseason_<y>.csv     endpoint=archive&preseason=true&y=<y>: KenPom's preseason ratings for a past season (backtests)
  history/archive_<date>.csv  endpoint=archive&d=<date>&y=<season>: ratings as they stood on a past date (in-season rise/fall tests)

Usage: python jobs/kenpom.py [--date YYYY-MM-DD]   (default: today ET; season = 2027 for 2026-27)
"""
import os, sys, time, argparse, datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd, requests

OUT = 'data/kenpom'
ET = ZoneInfo('America/New_York')


def getter():
    key = os.environ.get('KENPOM_API_KEY', '').strip()
    if not key: sys.exit('KENPOM_API_KEY not set (repo Settings -> Secrets and variables -> Actions)')
    hdr = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
    def get(endpoint, **p):
        for i in range(4):
            try:
                r = requests.get('https://kenpom.com/api.php', headers=hdr, params=dict(endpoint=endpoint, **p), timeout=90)
            except requests.RequestException as e:
                print(f'  {endpoint} {p}: {type(e).__name__}, retry {i + 1}', flush=True); time.sleep(5 * (i + 1)); continue
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else data.get('data', data)
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(2 ** i + 2); continue
            sys.exit(f'KenPom {endpoint} {p}: HTTP {r.status_code} {r.text[:200]}')
        sys.exit(f'KenPom {endpoint} {p}: gave up')
    return get


def season_for(d):
    return d.year + 1 if d.month >= 7 else d.year


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date'); ap.add_argument('--fanmatch-only', action='store_true', help='past date: FanMatch only, leave the ratings files alone'); ap.add_argument('--height', action='store_true'); ap.add_argument('--height-year', type=int, help='past season (ending year): height/experience/bench/continuity table -> history/height_<y>.csv'); ap.add_argument('--preseason', type=int, help='season (ending year): archived preseason ratings -> preseason_<y>.csv'); ap.add_argument('--archive', help='YYYY-MM-DD: ratings as of that past date -> history/archive_<date>.csv'); ap.add_argument('--history', help='Y1-Y2: end-of-season ratings, four factors, misc stats, point distribution per season -> history/<endpoint>_<y>.csv (coach/scheme histories)')
    a = ap.parse_args()
    d = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(ET).date()
    y = season_for(d)
    os.makedirs(OUT, exist_ok=True)
    get = getter()

    if a.height_year:
        os.makedirs(f'{OUT}/history', exist_ok=True)
        h = pd.DataFrame(get('height', y=a.height_year)); h.to_csv(f'{OUT}/history/height_{a.height_year}.csv', index=False)
        print(f'height y={a.height_year}: {len(h)} teams'); return
    if a.history:
        y1, y2 = map(int, a.history.split('-')); os.makedirs(f'{OUT}/history', exist_ok=True)
        key = os.environ['KENPOM_API_KEY'].strip(); hdr = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
        for ep in ('ratings', 'four-factors', 'misc-stats', 'pointdist', 'height'):
            for yy in range(y1, y2 + 1):
                try:
                    r = requests.get('https://kenpom.com/api.php', headers=hdr, params=dict(endpoint=ep, y=yy), timeout=90)
                except requests.RequestException as e:
                    print(f'{ep} y={yy}: {type(e).__name__}'); continue
                if r.status_code != 200: print(f'{ep} y={yy}: HTTP {r.status_code} {r.text[:120]}'); break
                data = r.json(); data = data if isinstance(data, list) else data.get('data', data)
                df = pd.DataFrame(data); df.to_csv(f'{OUT}/history/{ep}_{yy}.csv', index=False)
                print(f'{ep} y={yy}: {len(df)} teams'); time.sleep(0.5)
        return
    if a.archive:
        ad = dt.date.fromisoformat(a.archive); os.makedirs(f'{OUT}/history', exist_ok=True)
        ar = pd.DataFrame(get('archive', d=str(ad), y=season_for(ad))); ar.to_csv(f'{OUT}/history/archive_{ad}.csv', index=False)
        print(f'archive {ad} (season {season_for(ad)}): {len(ar)} teams; columns {list(ar.columns)}'); return
    if a.preseason:
        p_ = pd.DataFrame(get('archive', preseason='true', y=a.preseason)); p_.to_csv(f'{OUT}/preseason_{a.preseason}.csv', index=False)
        print(f'preseason y={a.preseason}: {len(p_)} teams; columns {list(p_.columns)}'); return
    if a.height:
        h = pd.DataFrame(get('height', y=y)); h.to_csv(f'{OUT}/height_{d}.csv', index=False)
        print(f'height y={y}: {len(h)} teams; columns {list(h.columns)}'); return

    if a.fanmatch_only:
        fm = pd.DataFrame(get('fanmatch', d=str(d))); fm.to_csv(f'{OUT}/fanmatch_{d}.csv', index=False)
        print(f'fanmatch {d}: {len(fm)} games'); return

    rat = pd.DataFrame(get('ratings', y=y))
    rat.insert(0, 'pulled_ET', dt.datetime.now(ET).strftime('%Y-%m-%d %H:%M'))
    rat.to_csv(f'{OUT}/ratings_{d}.csv', index=False); rat.to_csv(f'{OUT}/ratings_current.csv', index=False)
    print(f'ratings y={y}: {len(rat)} teams, data through {rat.DataThrough.iloc[0] if "DataThrough" in rat else "?"}')

    fm = pd.DataFrame(get('fanmatch', d=str(d)))
    fm.to_csv(f'{OUT}/fanmatch_{d}.csv', index=False)
    print(f'fanmatch {d}: {len(fm)} games' + (f', PredTempo mean {pd.to_numeric(fm.PredTempo, errors="coerce").mean():.1f}' if len(fm) else ''))

    known = set(pd.read_csv('data/prior_2026-27.csv').team)
    miss = sorted((set(rat.TeamName) | set(fm.get('Visitor', [])) | set(fm.get('Home', []))) - known)
    if miss: print('KenPom names not in the prior (D-I teams should all match):', miss[:30])


if __name__ == '__main__':
    main()
