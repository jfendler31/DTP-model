"""Grade a day's card against CBBD closing spreads and final scores.

For each game on cards/card_<D>.csv (the card as built, normally the 4:15 AM run):
  reference number = the card's market_home_spread (the 4 AM number); for games the card had no line for (extra board),
                     the CBBD opening spread (median across books), flagged ref_src='cbbd_open'
  model side       = side of the reference vs the card's size-adjusted model (model_home_spread_adj, as built that day)
  close            = CBBD closing spread, median across books (the `spread` field of /lines)
  result           = model side ATS vs the reference number and vs the close (W / L / P), from data/finals/finals_<D>.csv
  clv              = points the reference beat the close by, on the model side (+ = the market moved toward the model)

Writes data/grades/grade_<D>.csv and keeps one row per game in data/grades/grade_log.csv (a date's rows are replaced on
regrade). Prints the day and the season to date by edge band. Spreads are home-team spreads (negative = home favored).

  python jobs/grade.py                      # yesterday (America/New_York)
  python jobs/grade.py --date 2026-11-07
  python jobs/grade.py --start 2026-11-02 --end 2026-11-08
Needs CBBD_API_KEY. Finals come from jobs/slate.py --finals (the workflow runs it first).
"""
import os, sys, json, argparse, statistics as st, datetime as dt
import numpy as np, pandas as pd

ET = dt.timezone(dt.timedelta(hours=-5))
try:
    from zoneinfo import ZoneInfo; ET = ZoneInfo('America/New_York')
except Exception:
    pass
OUT = 'data/grades'
BANDS = [(-0.01, 1, '<1'), (1, 2, '1-2'), (2, 3, '2-3'), (3, 99, '3+')]


def cbbd_lines(start, end):
    key = os.environ.get('CBBD_API_KEY', '').strip()
    if not key: sys.exit('CBBD_API_KEY missing')
    import requests
    r = requests.get('https://api.collegebasketballdata.com/lines', timeout=180,
                     headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
                     params=dict(season=2027, startDateRange=start, endDateRange=(dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()))
    r.raise_for_status()
    xw = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    out = {}
    for g in r.json():
        ln = g.get('lines') or []
        c = [float(x['spread']) for x in ln if x.get('spread') is not None]
        o = [float(x['spreadOpen']) for x in ln if x.get('spreadOpen') is not None]
        h, a, sd = xw.get(g.get('homeTeam', '')), xw.get(g.get('awayTeam', '')), g.get('startDate') or ''
        if not (h and a and sd): continue
        ts = pd.Timestamp(sd)
        d = (ts.tz_convert('America/New_York') if ts.tzinfo else ts).strftime('%Y-%m-%d')
        out[(d, h, a)] = dict(close=st.median(c) if c else np.nan, open=st.median(o) if o else np.nan, n_books=len(c))
    return out


def res(home_margin, line, side_home):
    if pd.isna(line) or pd.isna(home_margin): return ''
    cov = home_margin + line
    return 'P' if cov == 0 else ('W' if (cov > 0) == side_home else 'L')


def grade_day(d, L):
    cf, ff = f'cards/card_{d}.csv', f'data/finals/finals_{d}.csv'
    if not (os.path.exists(cf) and os.path.exists(ff)):
        print(d, 'missing', cf if not os.path.exists(cf) else ff); return pd.DataFrame()
    C, F = pd.read_csv(cf, encoding='utf-8-sig'), pd.read_csv(ff, encoding='utf-8-sig')
    F = F[F.status == 'STATUS_FINAL']
    rows = []
    for g in C.itertuples():
        f = F[((F.away == g.away) & (F.home == g.home)) | ((F.away == g.home) & (F.home == g.away))]
        if f.empty: continue
        f = f.iloc[0]
        hm = (f.home_pts - f.away_pts) if f.home == g.home else (f.away_pts - f.home_pts)
        cb = L.get((d, g.home, g.away))
        flip = False
        if cb is None and (d, g.away, g.home) in L:          # CBBD lists a neutral game the other way round
            cb, flip = L[(d, g.away, g.home)], True
        close = np.nan if cb is None else (-cb['close'] if flip else cb['close'])
        opn = np.nan if cb is None else (-cb['open'] if flip else cb['open'])
        ref, src = g.market_home_spread, 'card'
        if pd.isna(ref): ref, src = opn, 'cbbd_open'
        model = g.model_home_spread_adj
        if pd.isna(ref) or pd.isna(model): continue
        e = ref - model; side_home = e > 0
        clv = np.nan if pd.isna(close) else ((ref - close) if side_home else (close - ref))
        rows.append(dict(date=d, tip_ET=g.tip_ET, away=g.away, home=g.home, venue=g.venue, ref_src=src, ref=ref,
                         model_raw=g.model_home_spread, model_adj=model, edge=round(abs(e), 1),
                         side=g.home if side_home else g.away, close=close, n_books=0 if cb is None else cb['n_books'],
                         home_margin=hm, res_ref=res(hm, ref, side_home), res_close=res(hm, close, side_home),
                         clv=None if pd.isna(clv) else round(clv, 1)))
    return pd.DataFrame(rows)


def rec(s):
    w, l, p = (s == 'W').sum(), (s == 'L').sum(), (s == 'P').sum()
    return f'{w}-{l}' + (f'-{p}' if p else '') + (f' ({w / (w + l):.0%})' if w + l else '')


def summary(D, label):
    if D.empty: print(label, 'no games'); return
    c = pd.to_numeric(D.clv, errors='coerce')
    print(f'\n{label}: {len(D)} games | vs reference {rec(D.res_ref)} | vs close {rec(D.res_close)} | '
          f'CLV {c.mean():+.2f} over {c.notna().sum()} with a close ({(c > 0).sum()} toward / {(c < 0).sum()} away / {(c == 0).sum()} flat)')
    for lo, hi, nm in BANDS:
        x = D[(D.edge > lo) & (D.edge <= hi)]
        if len(x):
            cx = pd.to_numeric(x.clv, errors='coerce')
            print(f'  edge {nm:>4}: n {len(x):3d}  vs ref {rec(x.res_ref):14s} vs close {rec(x.res_close):14s} CLV {cx.mean():+.2f}')
    for src, x in D.groupby('ref_src'):
        print(f'  ref {src}: n {len(x)}  vs ref {rec(x.res_ref)}  CLV {pd.to_numeric(x.clv, errors="coerce").mean():+.2f}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date'); ap.add_argument('--start'); ap.add_argument('--end')
    a = ap.parse_args()
    if a.start:
        days = pd.date_range(a.start, a.end or a.start).strftime('%Y-%m-%d').tolist()
    else:
        days = [a.date or (dt.datetime.now(ET).date() - dt.timedelta(days=1)).isoformat()]
    L = cbbd_lines(days[0], days[-1])
    os.makedirs(OUT, exist_ok=True)
    logf = f'{OUT}/grade_log.csv'
    log = pd.read_csv(logf) if os.path.exists(logf) else pd.DataFrame()
    for d in days:
        G = grade_day(d, L)
        if G.empty: continue
        # sign check: the card's 4 AM number and CBBD's close should mostly agree in sign
        both = G[(G.ref_src == 'card') & G.close.notna() & (G.ref.abs() >= 3)]
        if len(both) >= 5 and (np.sign(both.ref) != np.sign(both.close)).mean() > 0.5:
            sys.exit(f'{d}: CBBD spreads look inverted vs the card - check the sign convention before grading')
        G.to_csv(f'{OUT}/grade_{d}.csv', index=False, encoding='utf-8-sig')
        if not log.empty: log = log[log.date != d]
        log = pd.concat([log, G], ignore_index=True)
        miss = G.close.isna().sum()
        summary(G, f'{d}' + (f' ({miss} without a CBBD close)' if miss else ''))
    if not log.empty:
        log = log.sort_values(['date', 'tip_ET']); log.to_csv(logf, index=False, encoding='utf-8-sig')
        summary(log, f'Season to date ({log.date.min()} to {log.date.max()})')


if __name__ == '__main__':
    main()
