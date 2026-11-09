"""Torvik play-by-play shot mix (barttorvik.com teampbp.php / playerpbp.php) -> CSV.

Four pages per season (polite: one request every few seconds, ~4 per run):
  team_types    teampbp.php?year=Y&conlimit=All&view=types   tip-ins, layups/drives, floaters, hooks/post, pull-ups, spot-ups, and-1s (O and D)
  team_dist     teampbp.php?year=Y&conlimit=All               dunks, close twos, far twos, threes, and-1s (O and D)
  player_types  playerpbp.php?year=Y&conlimit=All&minrim=0&min2=0&min3=0&tot=0&view=types   per player: made-att, FG%, share, assisted %
  player_dist   playerpbp.php?year=Y&conlimit=All&minrim=0&min2=0&min3=0&tot=0             per player by distance
Raw pages are kept (gzipped) under data/torvik/raw/ so a parser change never needs a re-pull.
Outputs: data/torvik/<page>_<Y>.csv (latest) and, for the current season, data/torvik/snapshots/<page>_<Y>_<date>.csv.
Usage: python jobs/torvik_pbp.py [--years 2027] [--pages team_types,team_dist,player_types,player_dist] [--parse-only FILE.html --page KIND]"""
import argparse, datetime as dt, gzip, html as H, os, re, sys, time
import pandas as pd
BASE = 'https://barttorvik.com/'
PAGES = {
    'team_types':   ('teampbp.php',   dict(conlimit='All', view='types')),
    'team_dist':    ('teampbp.php',   dict(conlimit='All')),
    'player_types': ('playerpbp.php', dict(conlimit='All', minrim=0, min2=0, min3=0, tot=0, view='types')),
    'player_dist':  ('playerpbp.php', dict(conlimit='All', minrim=0, min2=0, min3=0, tot=0)),
}
UA = 'DTP-model research pull (personal, ~4 requests/day; github.com/jfendler31)'
CUR = 2027

def _txt(cell):
    cell = re.sub(r'<span[^>]*class="[^"]*mobileonly[^"]*"[^>]*>.*?</span>', ' ', cell, flags=re.S)
    cell = re.sub(r'<[^>]+>', ' ', H.unescape(cell)).replace('🎯', ' ')
    return ' '.join(cell.split())

def _cells(row, tag):
    out = []
    for attrs, body in re.findall(rf'<{tag}([^>]*)>(.*?)</{tag}>', row, re.S):
        if 'mobileonly' in attrs: continue
        span = int((re.search(r'colspan\s*=\s*["\']?(\d+)', attrs) or [0, 1])[1])
        title = (re.search(r"title\s*=\s*['\"]([^'\"]*)['\"]", attrs) or [0, ''])[1]
        out.append((_txt(body), span, title))
    return out

def parse(page_html):
    tab = max(re.findall(r'<table.*?</table>', page_html, re.S), key=len)
    head = re.search(r'<thead.*?</thead>', tab, re.S)
    hrows = re.findall(r'<tr.*?</tr>', head.group(0) if head else tab, re.S)
    hrows = [r for r in hrows if '<th' in r]
    first = [(t, span) for t, span, _ in _cells(hrows[0], 'th')]
    if any('Offense' in r for r in hrows):
        # team pages: one top-row group per shot type, 4 cells each (offense FG%/share, defense FG%/share; And-1s: tot/rate)
        cols = ['rank', 'team', 'conf']
        for t, span in first:
            if span != 4: continue
            k = re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')
            cols += [f'{k}|off_tot', f'{k}|off_rate', f'{k}|def_tot', f'{k}|def_rate'] if k.startswith('and_1') else \
                    [f'{k}|off_fg', f'{k}|off_share', f'{k}|def_fg', f'{k}|def_share']
    else:
        levels = []
        for r in hrows:
            names = []
            for t, span, _ in _cells(r, 'th'): names += [t] * span
            levels.append(names)
        width = max(len(l) for l in levels); cols = []
        for i in range(width):
            parts = []
            for l in levels:
                p = l[i] if i < len(l) else ''
                if p and (not parts or parts[-1] != p): parts.append(p)
            cols.append('|'.join(parts) or ('rank' if i == 0 else f'col{i}'))
    rows = []
    body = re.search(r'<tbody.*?</tbody>', tab, re.S)
    for r in re.findall(r'<tr.*?</tr>', body.group(0) if body else tab, re.S):
        cells = _cells(r, 'td')
        if len(cells) != len(cols): continue
        rec = {}
        for c, (t, _, title) in zip(cols, cells):
            rec[c] = t
            if re.fullmatch(r'\d+-\d+', title or ''): rec[c + '|made-att'] = title
        rows.append(rec)
    df = pd.DataFrame(rows)
    # rank-prefixed names ("121. Minnesota") -> clean; split made-att into numbers
    for c in df.columns:
        if df[c].astype(str).str.fullmatch(r'\d+\.\s+.+').mean() > 0.9: df[c] = df[c].str.replace(r'^\d+\.\s+', '', regex=True)
        s = df[c].astype(str)
        if s.str.fullmatch(r'\d+-\d+').mean() > 0.9:
            ma = s.str.split('-', expand=True).astype(float); df[c + '|made'] = ma[0]; df[c + '|att'] = ma[1]
        elif s.str.fullmatch(r'-?\d+(\.\d+)?').mean() > 0.9:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    # tidy: drop the "made-att" text columns once split; team pages -> <type>|off_made / off_att / def_made / def_att
    df = df[[c for c in df.columns if not (c.endswith('made-att') or (c.endswith('|Tot') and not pd.api.types.is_numeric_dtype(df[c])))]]
    df.columns = [re.sub(r'\|(off|def)_fg\|made-att\|(made|att)$', r'|\1_\2', c).replace('|Tot|made', '|made').replace('|Tot|att', '|att') for c in df.columns]
    return df

def fetch(page, year, sess):
    php, params = PAGES[page]
    r = sess.get(BASE + php, params={'year': year, **params}, timeout=120)
    print(f'{page} {year}: HTTP {r.status_code}, {len(r.content)/1e6:.2f} MB, {r.url}')
    r.raise_for_status()
    if '<table' not in r.text: raise SystemExit(f'{page} {year}: no table in response (bot check?) — first 300 chars: {r.text[:300]!r}')
    return r.text

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--years', default=str(CUR)); ap.add_argument('--pages', default=','.join(PAGES))
    ap.add_argument('--parse-only'); ap.add_argument('--page'); a = ap.parse_args()
    if a.parse_only:
        df = parse(open(a.parse_only, encoding='utf-8', errors='ignore').read()); print(df.shape); print(list(df.columns)); print(df.head(3).T.to_string()); return
    import requests
    sess = requests.Session(); sess.headers['User-Agent'] = UA
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date().isoformat()
    os.makedirs('data/torvik/raw', exist_ok=True); os.makedirs('data/torvik/snapshots', exist_ok=True)
    years = [int(y) for y in re.split(r'[,\s]+', a.years) if y]
    if len(years) == 1 and '-' in a.years: y1, y2 = map(int, a.years.split('-')); years = list(range(y1, y2 + 1))
    for y in years:
        for page in a.pages.split(','):
            page_html = fetch(page, y, sess)
            with gzip.open(f'data/torvik/raw/{page}_{y}_{today}.html.gz', 'wt', encoding='utf-8') as f: f.write(page_html)
            df = parse(page_html); df.insert(0, 'pulled', today); df.insert(0, 'season', y)
            df.to_csv(f'data/torvik/{page}_{y}.csv', index=False, encoding='utf-8-sig')
            if y == CUR: df.to_csv(f'data/torvik/snapshots/{page}_{y}_{today}.csv', index=False, encoding='utf-8-sig')
            print(f'  -> {len(df)} rows, {df.shape[1]} columns')
            time.sleep(6)
    # keep raw pages for the current day only for past seasons (they don't change); prune old current-season raws after 14 days
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=14)).isoformat()
    for fn in os.listdir('data/torvik/raw'):
        m = re.search(r'_(\d{4}-\d{2}-\d{2})\.html\.gz$', fn)
        if m and m.group(1) < cutoff: os.remove(f'data/torvik/raw/{fn}')

if __name__ == '__main__':
    main()
