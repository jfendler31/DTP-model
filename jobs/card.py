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
    if str(R['asof'].iloc[0]) <= card_date:
        Z = dict(zip(R.team, R.z_blend)); ZI = dict(zip(R.team, R.z_inseason)); PW = dict(zip(R.team, R.prior_wt)); NG = dict(zip(R.team, R.n_games))
        RSRC = f"prior + in-season blend (games before {R['asof'].iloc[0]}, K={R['K'].iloc[0]:.1f})"
MIN_G_INSEASON = 5   # in-season-only edge shown once both teams have this many D-I games
notes = collections.defaultdict(list); Z0 = dict(Z)   # Z0 = rating before overrides
if os.path.exists('data/overrides.csv'):
    O = pd.read_csv('data/overrides.csv').fillna('')
    for r in O.itertuples():
        if str(r.expires) not in ('', 'until cleared', 'season') and str(r.expires) < card_date: continue
        if r.team in Z and str(r.delta_pts) not in ('', 'nan'):
            Z[r.team] += float(r.delta_pts) / SDP; notes[r.team].append(f'{r.player} {r.status} ({float(r.delta_pts):+.1f})')
        elif r.team in Z: notes[r.team].append(f'{r.player} {r.status}')
h = pd.read_csv('data/kp_hca.csv'); h['team'] = h.team.str.strip(); H = dict(zip(h.team, h.hca)); H.setdefault('LSU New Orleans', H.get('New Orleans', 2.3))
def model(aw, hm, v): return round(-(9.5 * (Z[hm] - Z[aw]) + (H.get(hm, 3.0) if v == 'H' else 0.0)), 1)
# card-only size curve (Nov 7): model spread widened SIZE_K per point beyond SIZE_KNEE. Nov 1 version was 0.15 beyond 15; Nov 2-6
# (244 games) favorites beat the model by ~+4 on every bucket from 15 up (least-squares k 0.25 from a knee of 10), the backtest said
# 1-3 pts on 20+. 0.20 from 10 sits between them (20 -> +2.0, 25 -> +3.0, 30 -> +4.0). Provisional until the two-season sweep.
SIZE_K, SIZE_KNEE = 0.20, 10
def size_adj(m): return round(m + (1 if m > 0 else -1) * SIZE_K * max(abs(m) - SIZE_KNEE, 0), 1)
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
# ---- workbook: Betting Sheet tab (first) + Ratings tab + Card tab (sortable; numbers stored as numbers)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
ZP = dict(zip(P.team, P.z_prior)); CONF = dict(zip(P.team, P.conf)); TEMPO = dict(zip(P.team, P.adj_tempo))
PR = pd.DataFrame({'Team': list(Z)})
PR['Conf'] = PR.Team.map(CONF)
PR['Rating'] = (PR.Team.map(Z) * 9.5).round(1)
PR['Prior'] = (PR.Team.map(ZP) * 9.5).round(1)
PR['In-season only'] = (PR.Team.map(ZI) * 9.5).round(1) if ZI else None
PR['Move vs prior'] = ((PR.Team.map(Z0) - PR.Team.map(ZP)) * 9.5).round(1)
PR['Override adj'] = ((PR.Team.map(Z) - PR.Team.map(Z0)) * 9.5).round(1)
PR['D-I games'] = PR.Team.map(NG).fillna(0).astype(int) if NG else 0
PR['Prior weight'] = PR.Team.map(PW).fillna(1.0) if PW else 1.0
PR['HCA'] = PR.Team.map(H)
PR['KP tempo'] = PR.Team.map(TEMPO).round(1)
PR['Overrides'] = PR.Team.map(lambda t: '; '.join(notes[t]))
PR = PR.sort_values('Rating', ascending=False).reset_index(drop=True); PR.insert(0, 'Rank', PR.index + 1)
PR['Prior rank'] = PR.Prior.rank(ascending=False, method='min').astype(int)
wb = Workbook(); hdr_font = Font(bold=True, color='FFFFFF'); hdr_fill = PatternFill('solid', fgColor='1F3A5F')
def sheet(ws, df, widths, fmts):
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in row])
    for c in ws[1]: c.font, c.fill, c.alignment = Font(name='Helvetica', size=12, bold=True, color='FFFFFF'), hdr_fill, Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[1].height = 34
    for i, col in enumerate(df.columns, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 12)
        for (c,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
            c.font, c.alignment = Font(name='Helvetica', size=12), Alignment(horizontal='center', vertical='center')
            if col in fmts: c.number_format = fmts[col]
    ws.freeze_panes = 'B2' if 'Rank' in df.columns else 'A2'; ws.auto_filter.ref = ws.dimensions
# Card tab in Jon's layout (Nov 6): sorted by size-adjusted edge, Helvetica 12, centered; working columns hidden but kept
CARD_COLS = ['tip_ET', 'away', 'home', 'venue', 'model', 'market', 'n_books', 'total', 'edge', 'model_size_adj', 'edge_size_adj',
             'edge_inseason_only', 'prior_wt_away', 'prior_wt_home', 'notes', 'market_home_spread', 'model_home_spread', 'edge_size',
             'model_home_spread_adj', 'edge_size_adj_num', 'adj_home', 'abbr_away', 'abbr_home']
CARD_HDR = {'away': 'Away', 'home': 'Home', 'edge_size_adj': 'Edge Size Adj', 'market_home_spread': 'Market Home Spread',
            'model_home_spread': 'Model Home Spread', 'model_home_spread_adj': 'Home Spread Adj', 'edge_size_adj_num': 'Edge Size Adj',
            'adj_home': 'Adj To Home Side'}
CARD_HIDE = {'model', 'market', 'n_books', 'total', 'edge', 'model_size_adj', 'edge_inseason_only', 'prior_wt_away', 'prior_wt_home', 'notes', 'edge_size',
             'abbr_away', 'abbr_home'}
CARD_W = {'tip_ET': 22, 'away': 21, 'home': 21, 'venue': 9, 'edge_size_adj': 19, 'market_home_spread': 11, 'model_home_spread': 11,
          'model_home_spread_adj': 11, 'edge_size_adj_num': 11, 'notes': 40, 'adj_home': 13}
CARD_NUM = {'market_home_spread', 'model_home_spread', 'model_home_spread_adj', 'edge_size_adj_num', 'edge_size', 'adj_home'}
CD = C.assign(adj_home=None, abbr_away=C.away.map(abbr), abbr_home=C.home.map(abbr))[CARD_COLS].copy()
CD['_k'] = pd.to_numeric(CD.edge_size_adj_num, errors='coerce')
CD = CD.sort_values('_k', ascending=False, na_position='last').drop(columns='_k')
ws = wb.active; ws.title = 'Card'
BODY = Font(name='Helvetica', size=12); HEAD = Font(name='Helvetica', size=12, bold=True, color='FFFFFF')
MID = Alignment(horizontal='center', vertical='center'); MIDW = Alignment(horizontal='center', vertical='center', wrap_text=True)
ws.append([CARD_HDR.get(c, c) for c in CARD_COLS])
for row in CD.itertuples(index=False):
    vals = []
    for c, v in zip(CARD_COLS, row):
        if isinstance(v, float) and pd.isna(v): v = None
        elif c in CARD_NUM and v not in (None, ''):
            try: v = float(v)
            except (TypeError, ValueError): pass
        vals.append(v)
    ws.append(vals)
# Live formulas (Nov 7): the label (K), the size-adjusted model (S) and the numeric edge (T) recompute from whatever is in
# Market Home Spread (P), Model Home Spread (Q) and Adj To Home Side (U), so a pasted current line or a manual adjustment
# flips the side and re-sizes the edge in place. Values in the CSV stay as built.
COL = {c: get_column_letter(i) for i, c in enumerate(CARD_COLS, 1)}
P_, Q_, S_, U_, A_, H_ = (COL[c] for c in ('market_home_spread', 'model_home_spread', 'model_home_spread_adj', 'adj_home', 'abbr_away', 'abbr_home'))
for r in range(2, ws.max_row + 1):
    fin = f'({S_}{r}+N({U_}{r}))'
    ws[f'{S_}{r}'] = f'=IF({Q_}{r}="","",ROUND({Q_}{r}+SIGN({Q_}{r})*{SIZE_K}*MAX(ABS({Q_}{r})-{SIZE_KNEE},0),1))'
    ws[f'{COL["edge_size_adj_num"]}{r}'] = f'=IF({P_}{r}="","",ROUND(ABS({P_}{r}-{fin}),1))'
    ws[f'{COL["edge_size_adj"]}{r}'] = (f'=IF({P_}{r}="","",IF(ABS({P_}{r}-{fin})<0.05,"-",IF({P_}{r}-{fin}>0,{H_}{r},{A_}{r})'
                                        f'&" "&TEXT(ABS({P_}{r}-{fin}),"0.0")))')
for c in ws[1]: c.font, c.fill, c.alignment = HEAD, hdr_fill, MIDW
ws.row_dimensions[1].height = 48
for i, col in enumerate(CARD_COLS, 1):
    L = get_column_letter(i); ws.column_dimensions[L].width = CARD_W.get(col, 12)
    if col in CARD_HIDE: ws.column_dimensions[L].hidden = True
    for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
        cell.font, cell.alignment = BODY, MID
        if col in CARD_NUM: cell.number_format = '0.0'
for r in range(2, ws.max_row + 1): ws.row_dimensions[r].height = 18
ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
cols = ['Rank', 'Team', 'Conf', 'Rating', 'Prior', 'Prior rank', 'Move vs prior', 'In-season only', 'D-I games', 'Prior weight',
        'Override adj', 'HCA', 'KP tempo', 'Overrides']
MMDD = card_date[5:7] + '-' + card_date[8:10]
sheet(wb.create_sheet(f'Ratings {MMDD}'), PR[cols], {'Team': 22, 'Overrides': 50, 'In-season only': 13, 'Move vs prior': 12},
      {'Rating': '0.0', 'Prior': '0.0', 'Move vs prior': '+0.0;-0.0;0.0', 'In-season only': '0.0', 'Prior weight': '0%',
       'Override adj': '+0.0;-0.0;0.0', 'HCA': '0.0', 'KP tempo': '0.0'})
# ---- Betting Sheet tab (Nov 8): Jon's Google Sheet layout, first tab. A tip, B away, C home, D venue, E label, F market home
# spread, G raw model home spread, H size-adjusted model, I edge, J his adjustment (home-spread pts: a home-team absence is
# positive, an away-team absence negative), K notes. E/H/I are ARRAYFORMULAs anchored in the HEADER row in the exact form
# Jon's Nov 7 Google tab used and exported: ={"Header"; IF(F2:F500 ...)}. Anchored in row 1, a sort of rows 2+ can't move
# them (a row-2 anchor rode down with the Santa Clara row on Nov 7 and blanked rows 2-5); per-row formulas (Nov 8 morning)
# didn't edit/sort the way Jon works in Sheets. Bounded ranges (2:500) because open-ended F2:F refs import as #REF from xlsx.
# Colour scale on I as on Jon's Nov 7 tab: min red / 2 white / max green.
from openpyxl.formatting.rule import ColorScaleRule
BS = C.assign(tip_dt=pd.to_datetime(C.tip_ET.str.replace(r'^\w+ ', '', regex=True) + f' {card_date[:4]}', format='%b %d %I:%M %p %Y',
                                errors='coerce'), edge_k=pd.to_numeric(C.edge_size_adj_num, errors='coerce'))
BS = BS.sort_values(['edge_k', 'tip_dt'], ascending=[False, True], na_position='last')
bs = wb.create_sheet(f'Betting Sheet {MMDD}', 0)
BS_HDR = ['tip_ET', 'Away', 'Home', 'venue', 'Edge Size Adj', 'Market Home Spread', 'Model Home Spread', 'Home Spread Adj',
          'Edge Size Adj', 'Adj To Home Side', 'Notes']
bs.append(BS_HDR)
def num(v):
    try: return None if v in (None, '') or (isinstance(v, float) and pd.isna(v)) else float(v)
    except (TypeError, ValueError): return None
for g in BS.itertuples(index=False):
    bs.append([None if pd.isna(g.tip_dt) else g.tip_dt.to_pydatetime(), g.away, g.home, g.venue, None, num(g.market_home_spread),
               num(g.model_home_spread), None, None, None, g.notes if isinstance(g.notes, str) and g.notes else None])
last = bs.max_row + 15            # formatted rows (slate + 15 spare); the arrays run to row BS_N
BS_N = 500
from openpyxl.worksheet.formula import ArrayFormula
_R = lambda c: f'{c}2:{c}{BS_N}'
_d = f'{_R("F")}-({_R("H")}+{_R("J")})'
bs['H1'] = ArrayFormula(f'H1:H{BS_N}', f'={{"Home Spread Adj"; IF({_R("G")}="","",ROUND({_R("G")}+SIGN({_R("G")})*{SIZE_K}'
                                         f'*(ABS({_R("G")})>{SIZE_KNEE})*(ABS({_R("G")})-{SIZE_KNEE}),1))}}')
bs['I1'] = ArrayFormula(f'I1:I{BS_N}', f'={{"Edge Size Adj"; IF({_R("F")}="","",ROUND(ABS({_d}),1))}}')
bs['E1'] = ArrayFormula(f'E1:E{BS_N}', f'={{"Edge Size Adj"; IF({_R("F")}="","",IF(ABS({_d})<0.05,"-",IF({_d}>0,{_R("C")},{_R("B")})'
                                         f'&" "&TEXT(ABS({_d}),"0.0")))}}')
for c in bs[1]: c.font, c.fill, c.alignment = HEAD, hdr_fill, MIDW
bs.row_dimensions[1].height = 48
for L, w in zip('ABCDEFGHIJK', (16, 22, 22, 8, 24, 11, 11, 11, 10, 11, 40)): bs.column_dimensions[L].width = w
for row in bs.iter_rows(min_row=2, max_row=last, max_col=11):
    for cell in row:
        cell.font, cell.alignment = BODY, MID
        if cell.column_letter == 'A': cell.number_format = 'ddd mmm d h:mm am/pm'
        elif cell.column_letter in 'FGHIJ': cell.number_format = '0.0'
bs.conditional_formatting.add(f'I2:I{BS_N}', ColorScaleRule(start_type='min', start_color='FFE67C73',
                              mid_type='num', mid_value=2, mid_color='FFFFFFFF', end_type='max', end_color='FF57BB8A'))
bs.freeze_panes = 'A2'; bs.auto_filter.ref = f'A1:K{BS_N}'
wb.move_sheet(f'Ratings {MMDD}', offset=1 - wb.sheetnames.index(f'Ratings {MMDD}'))
wb.active = 0
xfn = f'cards/card_{card_date}.xlsx'; wb.save(xfn)
lined = int(C.market.ne('').sum())
print(f'{fn}: {len(C)} games, {lined} with lines')
if a.no_email: sys.exit(0)
msg = EmailMessage()
msg['Subject'] = f"DTP card — {dt.datetime.strptime(card_date, '%Y-%m-%d'):%a %b %-d} — {len(C)} games"
msg['From'] = os.environ['GMAIL_USER'].strip(); msg['To'] = os.environ['CARD_TO'].strip()
msg.set_content(f"Ratings: {RSRC} + overrides. Lines as of {asof} (consensus = most common number across books).\n"
                f"{len(C)} games, {lined} with lines. Workbook attached (Betting Sheet, Ratings and Card tabs); CSV of the card (tip-time order) also attached.\n"
                f"Betting Sheet tab: your Google Sheet layout, sorted by edge. Type the current line in F and your adjustment in J; E/H/I are array formulas in the header row (rows 2-500), so sorting rows 2+ and adding games below both work.\n"
                f"Ratings tab: points vs an average D-I team on a neutral floor (9.5 per SD), prior + in-season blend + overrides.\n"
                f"edge_size_adj: model spread widened {SIZE_K} pt per point beyond {SIZE_KNEE} (size curve, Nov 7); regular edge unchanged.\n"
                f"Card tab: Edge Size Adj, Home Spread Adj and the label recompute from Market Home Spread, Model Home Spread and Adj To Home Side.\n")
msg.add_attachment(open(xfn, 'rb').read(), maintype='application', subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                   filename=os.path.basename(xfn))
msg.add_attachment(open(fn, 'rb').read(), maintype='text', subtype='csv', filename=os.path.basename(fn))
with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
    s.login(os.environ['GMAIL_USER'].strip(), os.environ['GMAIL_APP_PASSWORD'].replace(' ', '').strip()); s.send_message(msg)
print('emailed')
