"""Daily card: model vs market for the day's slate, emailed as CSV.
Monday Nov 2 build: slate comes from data/slate_<card_date>.csv (opening-night sheet); ratings = frozen preseason prior
(data/prior_2026-27.csv) + data/overrides.csv. From Nov 3 the slate comes from CBBD and ratings from the nightly job.
Usage (Actions): python jobs/card.py            -> today's card (ET), pulls The Odds API, emails
Local test:      python jobs/card.py --snapshot data/lines/x.csv --date 2026-11-02 --no-email"""
import os, sys, io, json, argparse, smtplib, collections, statistics, datetime as dt
from email.message import EmailMessage
from zoneinfo import ZoneInfo
import pandas as pd, requests
sys.path.insert(0, os.path.dirname(__file__)); from team_abbr import abbr; from absence_sweep import make_fixer
ET = ZoneInfo('America/New_York'); NOW = dt.datetime.now(ET)
ap = argparse.ArgumentParser(); ap.add_argument('--snapshot'); ap.add_argument('--date'); ap.add_argument('--no-email', action='store_true'); a = ap.parse_args()
card_date = a.date or NOW.strftime('%Y-%m-%d')
slate_f = f'data/slate_{card_date}.csv'
if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and os.path.exists(f'cards/card_{card_date}.csv'):
    print('card for', card_date, 'already sent - skipping'); sys.exit(0)
if not os.path.exists(slate_f): print('no slate file for', card_date, '- nothing to do'); sys.exit(0)
S = pd.read_csv(slate_f).fillna('')
S = S[S.date == card_date] if 'date' in S else S
# ---- ratings: frozen prior + overrides
P = pd.read_csv('data/prior_2026-27.csv'); Z = dict(zip(P.team, P.z_prior)); SDP = P.prior_pts.std()
ZI, PW, NG, RSRC = {}, {}, {}, 'preseason prior (frozen)'
if os.path.exists('data/ratings_current.csv'):          # nightly ratings job: prior blended with in-season composite
    R = pd.read_csv('data/ratings_current.csv')
    if str(R.asof.iloc[0]) <= card_date:
        Z = dict(zip(R.team, R.z_blend)); ZI = dict(zip(R.team, R.z_inseason)); PW = dict(zip(R.team, R.prior_wt)); NG = dict(zip(R.team, R.n_games))
        RSRC = f'prior + in-season blend (games before {R.asof.iloc[0]}, K={R.K.iloc[0]:.1f})'
MIN_G_INSEASON = 5   # in-season-only edge shown once both teams have this many D-I games
notes = collections.defaultdict(list)
if os.path.exists('data/overrides.csv'):
    O = pd.read_csv('data/overrides.csv').fillna('')
    for r in O.itertuples():
        if str(r.expires) not in ('', 'until cleared', 'season') and str(r.expires) < card_date: continue
        if r.team in Z and str(r.delta_pts) not in ('', 'nan'):
            Z[r.team] += float(r.delta_pts) / SDP; notes[r.team].append(f'{r.player} {r.status} ({float(r.delta_pts):+.1f})')
        elif r.team in Z: notes[r.team].append(f'{r.player} {r.status}')
h = pd.read_csv('data/kp_hca.csv'); h['team'] = h.team.str.strip(); H = dict(zip(h.team, h.hca)); H.setdefault('LSU New Orleans', H.get('New Orleans', 2.3))
def model(aw, hm, v): return round(-(9.5 * (Z[hm] - Z[aw]) + (H.get(hm, 3.0) if v == 'H' else 0.0)), 1)
SIZE_K = 0.15   # card-only size adjustment (Nov 1): +0.15 pt per point of model spread beyond 15; locked conversion unchanged
def size_adj(m): return round(m + (1 if m > 0 else -1) * SIZE_K * max(abs(m) - 15, 0), 1)
# ---- lines
if a.snapshot:
    L = pd.read_csv(a.snapshot); asof = os.path.basename(a.snapshot)
else:
    r = requests.get('https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds', timeout=60,
                     params=dict(apiKey=os.environ['ODDS_API_KEY'].strip(), regions='us', markets='spreads,totals', oddsFormat='american'))
    r.raise_for_status(); rows = []
    for g in r.json():
        for b in g.get('bookmakers', []):
            rec = dict(away=g['away_team'], home=g['home_team'], book=b['key'], home_spread=None, total=None)
            for mk in b.get('markets', []):
                for o in mk.get('outcomes', []):
                    if mk['key'] == 'spreads' and o['name'] == g['home_team']: rec['home_spread'] = o.get('point')
                    if mk['key'] == 'totals' and o['name'] == 'Over': rec['total'] = o.get('point')
            rows.append(rec)
    L = pd.DataFrame(rows); asof = NOW.strftime('%-I:%M %p ET')
    os.makedirs('data/lines', exist_ok=True); L.to_csv(f"data/lines/card_{NOW:%Y-%m-%d_%H%M}.csv", index=False)
xa = json.load(open('data/xwalk_oddsapi_cbbd.json')); xb = json.load(open('data/xwalk_cbbd_kp.json')); K = set(P.team); fix = make_fixer(P.team)
EXTRA = {'New Haven Chargers': 'New Haven', 'West Florida Argonauts': 'West Florida', 'New Orleans Privateers': 'LSU New Orleans', 'Miami Hurricanes': 'Miami FL',
         'Miami (OH) RedHawks': 'Miami OH', 'Queens University Royals': 'Queens', 'Wright St Raiders': 'Wright St.', 'Air Force Falcons': 'Air Force'}
def kp(n):
    if n in EXTRA: return EXTRA[n]
    c = xb.get(xa.get(n, ''), None)
    if c in K: return c
    w = str(n).split()
    for k in range(len(w) - 1, 0, -1):
        f = fix(' '.join(w[:k]))
        if f: return f
def mode_half(xs):
    xs = [x for x in xs if pd.notna(x)]
    if not xs: return None
    c = collections.Counter(xs).most_common(); top = [v for v, n in c if n == c[0][1]]
    return round((top[0] if len(top) == 1 else statistics.median(xs)) * 2) / 2
L['a'] = L.away.map(kp); L['h'] = L.home.map(kp)
G = {frozenset((x, y)): dict(h=y, cons=mode_half(list(g.home_spread)), tot=mode_half(list(g.total)), n=int(g.home_spread.notna().sum()))
     for (x, y), g in L.dropna(subset=['a', 'h']).groupby(['a', 'h'])}
def ins_edge(g, hs):
    if not ZI: return 'n/a (no in-season ratings)'
    if min(NG.get(g.away, 0), NG.get(g.home, 0)) < MIN_G_INSEASON: return f'n/a (<{MIN_G_INSEASON} games)'
    if hs is None: return ''
    mi = -(9.5 * (ZI[g.home] - ZI[g.away]) + (H.get(g.home, 3.0) if g.venue == 'H' else 0.0)); e = hs - mi
    return '-' if abs(e) < 0.05 else (f'{abbr(g.home)} {e:.1f}' if e > 0 else f'{abbr(g.away)} {-e:.1f}')
out = []
for g in S.itertuples():
    m = model(g.away, g.home, g.venue); x = G.get(frozenset((g.away, g.home)))
    hs = None if not x or x['cons'] is None else (x['cons'] if x['h'] == g.home else -x['cons'])
    e = None if hs is None else hs - m
    ma = size_adj(m); ea = None if hs is None else hs - ma
    side = lambda v: 'PK' if v == 0 else (f'{abbr(g.home)} -{abs(v):g}' if v < 0 else f'{abbr(g.away)} -{v:g}')
    out.append({'tip_ET': g.tip_ET, 'away': g.away, 'home': g.home, 'venue': g.venue,
                'model': 'PK' if m == 0 else (f'{abbr(g.home)} -{abs(m):.1f}' if m < 0 else f'{abbr(g.away)} -{m:.1f}'),
                'market': '' if hs is None else side(hs), 'n_books': 0 if not x else x['n'], 'total': '' if not x else x['tot'],
                'edge': '' if e is None else ('-' if abs(e) < 0.05 else (f'{abbr(g.home)} {e:.1f}' if e > 0 else f'{abbr(g.away)} {-e:.1f}')),
                'model_size_adj': 'PK' if ma == 0 else (f'{abbr(g.home)} -{abs(ma):.1f}' if ma < 0 else f'{abbr(g.away)} -{ma:.1f}'),
                'edge_size_adj': '' if ea is None else ('-' if abs(ea) < 0.05 else (f'{abbr(g.home)} {ea:.1f}' if ea > 0 else f'{abbr(g.away)} {-ea:.1f}')),
                'edge_inseason_only': ins_edge(g, hs), 'prior_wt_away': f"{PW.get(g.away, 1.0):.0%}", 'prior_wt_home': f"{PW.get(g.home, 1.0):.0%}",
                'notes': '; '.join(notes[g.away] + notes[g.home]),
                'model_home_spread': m, 'market_home_spread': hs, 'edge_size': None if e is None else round(abs(e), 1),
                'model_home_spread_adj': ma, 'edge_size_adj_num': None if ea is None else round(abs(ea), 1)})
C = pd.DataFrame(out)
C['_t'] = pd.to_datetime(C.tip_ET.str.replace(r'^\w+ ', '', regex=True) + f' {card_date[:4]}', format='%b %d %I:%M %p %Y', errors='coerce')
C = C.sort_values('_t').drop(columns='_t')
os.makedirs('cards', exist_ok=True); fn = f'cards/card_{card_date}.csv'; C.to_csv(fn, index=False, encoding='utf-8-sig')
lined = int(C.market.ne('').sum())
print(f'{fn}: {len(C)} games, {lined} with lines')
if a.no_email: sys.exit(0)
msg = EmailMessage()
msg['Subject'] = f"DTP card — {dt.datetime.strptime(card_date, '%Y-%m-%d'):%a %b %-d} — {len(C)} games"
msg['From'] = os.environ['GMAIL_USER'].strip(); msg['To'] = os.environ['CARD_TO'].strip()
msg.set_content(f"Ratings: {RSRC} + overrides. Lines as of {asof} (consensus = most common number across books).\n"
                f"{len(C)} games, {lined} with lines. Tip-time order. CSV attached.\n"
                f"edge_size_adj: model spread widened 0.15 pt per point beyond 15 (big-mismatch correction); regular edge unchanged.\n")
msg.add_attachment(open(fn, 'rb').read(), maintype='text', subtype='csv', filename=os.path.basename(fn))
with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
    s.login(os.environ['GMAIL_USER'].strip(), os.environ['GMAIL_APP_PASSWORD'].replace(' ', '').strip()); s.send_message(msg)
print('emailed')
