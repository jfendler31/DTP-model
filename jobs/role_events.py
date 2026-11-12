"""Player-level shot / rebound / turnover events from CBBD play-by-play, for role cards (Nov 12, 2026).

One compact row per relevant play (shots incl. free throws, rebounds, turnovers, steals, blocks, fouls), with the
shooter, CBBD's shot range / made / assisted / assister, and the elapsed-seconds clock used by jobs/tempo.py and
jobs/rotation.py, so rows join to data/tempo/possessions_*.csv.gz (possession start type, leverage).
Writes data/roles/events_<YYYY-MM>.csv.gz, one file per month (re-runs replace those games).
Fetch mirrors jobs/rotation.py: /plays/date a day either side of the range, keep games by ET tip date, gap-fill
missing games from /plays/game.
Usage: python jobs/role_events.py --start 2026-11-01 --end 2026-11-11
"""
import os, sys, json, argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rotation import api, by_game, et_date, make_clock

OUT = 'data/roles'
KEEP = ('shot', 'jumper', 'layup', 'dunk', 'tip', 'hook', 'freethrow', 'rebound', 'turnover', 'steal', 'block', 'foul')


def g(d, *ks):
    for k in ks:
        if not isinstance(d, dict): return None
        d = d.get(k)
    return d


def rows_for(gid, plays, date):
    elapsed, _ = make_clock(plays)
    out = []
    for x in plays:
        pt = (x.get('playType') or '').lower().replace(' ', '')
        if not (x.get('shootingPlay') or any(k in pt for k in KEEP)): continue
        si = x.get('shotInfo') if isinstance(x.get('shotInfo'), dict) else {}
        parts = x.get('participants') or []
        p0 = parts[0] if parts else {}
        try: t = elapsed(x.get('period') or 1, x.get('secondsRemaining') or 0)
        except Exception: t = None
        out.append(dict(
            gameId=gid, date=date, id=x.get('id'), period=x.get('period'), t=t,
            team=x.get('team'), opp=x.get('opponent'), isHome=x.get('isHomeTeam'),
            playType=x.get('playType'), playText=(x.get('playText') or '')[:140],
            shooting=x.get('shootingPlay'), scoring=x.get('scoringPlay'), value=x.get('scoreValue'),
            pid=g(si, 'shooter', 'id') or p0.get('id'), player=g(si, 'shooter', 'name') or p0.get('name'),
            p2=(parts[1].get('name') if len(parts) > 1 else None),
            made=si.get('made'), range=si.get('range'), assisted=si.get('assisted'),
            ast_id=g(si, 'assistedBy', 'id'), ast_name=g(si, 'assistedBy', 'name'),
            x=g(si, 'location', 'x'), y=g(si, 'location', 'y'),
            home_score=x.get('homeScore'), away_score=x.get('awayScore')))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--start', required=True); ap.add_argument('--end'); ap.add_argument('--gap-fill', type=int, default=400)
    a = ap.parse_args(); start = a.start; end = a.end or a.start
    os.makedirs(OUT, exist_ok=True)
    get = api(); games = {}
    for d in pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=1), pd.Timestamp(end) + pd.Timedelta(days=1)):
        data = get('/plays/date', date=d.strftime('%Y-%m-%d'), utcOffset=-5)
        if data is None: print(f'{d:%Y-%m-%d}: date feed failed'); continue
        for gid, pl in by_game(data).items():
            if start <= et_date(pl[0]['gameStartDate']) <= end:
                have = games.setdefault(gid, {})
                for x in pl: have[x['id']] = x
        print(f'{d:%Y-%m-%d}: {len(data)} plays', flush=True)
    games = {gid: list(v.values()) for gid, v in games.items()}
    n_date = len(games)
    if os.path.exists('data/games_2026-27.csv') and a.gap_fill:
        box = pd.read_csv('data/games_2026-27.csv')
        want = box[(box.date >= start) & (box.date <= end)].gameId.astype(int).unique().tolist()
        missing = [x for x in want if x not in games]
        for x in missing[:a.gap_fill]:
            pl = get(f'/plays/game/{x}')
            if pl: games[x] = pl
        print(f'gap fill: {len(games) - n_date} of {len(missing)} missing games fetched')
    rows = []
    for gid, pl in games.items():
        pl = sorted(pl, key=lambda x: int(x.get('id') or 0))
        rows += rows_for(gid, pl, et_date(pl[0]['gameStartDate']))
    E = pd.DataFrame(rows)
    if not len(E): print('no events'); return
    E['month'] = E.date.str[:7]
    for m, e in E.groupby('month'):
        f = f'{OUT}/events_{m}.csv.gz'
        old = pd.read_csv(f) if os.path.exists(f) else pd.DataFrame()
        if len(old): old = old[~old.gameId.isin(e.gameId)]
        pd.concat([old, e.drop(columns='month')], ignore_index=True).sort_values(['date', 'gameId', 'id']).to_csv(f, index=False, compression='gzip')
    sh = E[E.shooting == True]
    print(f'{len(games)} games, {len(E)} events, {len(sh)} shots; range filled {sh.range.notna().mean():.1%}, '
          f'assisted flag filled {sh.assisted.notna().mean():.1%}, assister named on made assisted shots '
          f'{sh[(sh.assisted == True)].ast_name.notna().mean():.1%}')


if __name__ == '__main__':
    main()
