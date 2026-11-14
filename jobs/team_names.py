"""Team / player name helpers (repo copy, Nov 10): kp() maps a BurnerBall (tracker) / CBBD team name to the KenPom spelling used
in data/prior_2026-27.csv and data/overrides.csv; pn() normalizes a player name (ascii, lowercase, suffixes Jr/Sr/II-V dropped)."""
import json, re, unicodedata, sys
import pandas as pd
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'jobs'))
from absence_sweep import make_fixer
_P = pd.read_csv(os.path.join(ROOT, 'data/prior_2026-27.csv')); _K = set(_P.team); _fix = make_fixer(_P.team)
_XB = {k: v.strip() for k, v in json.load(open(os.path.join(ROOT, 'data/xwalk_cbbd_kp.json'))).items()}
_MAN = {"Miami (FL)": "Miami FL", "Miami": "Miami FL", "Miami (OH)": "Miami OH", "NC State": "N.C. State", "UConn": "Connecticut", "Ole Miss": "Mississippi",
        "Hawai'i": "Hawaii", "UMASS": "Massachusetts", "PIttsburgh": "Pittsburgh", "FAU": "Florida Atlantic", "MTSU": "Middle Tennessee", "UIW": "Incarnate Word",
        "(LSU) New Orleans": "LSU New Orleans", "New Orleans": "LSU New Orleans", "Boston U": "Boston University", "N.C. A&T": "North Carolina A&T", "ULM": "Louisiana Monroe",
        "UL Monroe": "Louisiana Monroe", "UMES": "Maryland Eastern Shore", "SEMO": "Southeast Missouri", "Long Island": "LIU", "Long Island University": "LIU",
        "Mount Saint Mary's": "Mount St. Mary's", "Central Connecticut State": "Central Connecticut", "Tennessee-Martin": "Tennessee Martin", "UT Martin": "Tennessee Martin",
        "St. Thomas (MN)": "St. Thomas", "St. Thomas-Minnesota": "St. Thomas", "William and Mary": "William & Mary", "Tarleton": "Tarleton St.", "UIC": "Illinois Chicago",
        "Nicholls": "Nicholls", "Sam Houston": "Sam Houston St.", "App State": "Appalachian St.", "Seattle U": "Seattle", "Omaha": "Nebraska Omaha", "Kansas City": "Kansas City",
        "IU Indianapolis": "IU Indy", "UTRGV": "UT Rio Grande Valley", "Texas A&M-Corpus Christi": "Texas A&M Corpus Chris", "SE Louisiana": "Southeastern Louisiana",
        "Cal State Northridge": "CSUN", "Cal State Fullerton": "Cal St. Fullerton", "Cal State Bakersfield": "Cal St. Bakersfield", "California Baptist": "Cal Baptist",
        "San José State": "San Jose St.", "San Jose State": "San Jose St.", "SIU Edwardsville": "SIUE", "Southern Miss": "Southern Miss", "Gardner-Webb": "Gardner Webb",
        "Bethune-Cookman": "Bethune Cookman", "Arkansas-Pine Bluff": "Arkansas Pine Bluff", "American University": "American", "South Carolina Upstate": "USC Upstate",
        "Florida International": "FIU", "Queens University": "Queens", "UAlbany": "Albany", "Grambling": "Grambling St.", "Louisiana-Monroe": "Louisiana Monroe",
        "Purdue Fort Wayne": "Purdue Fort Wayne", "Fort Wayne": "Purdue Fort Wayne", "Detroit Mercy": "Detroit Mercy", "USC Upstate": "USC Upstate", "FGCU": "Florida Gulf Coast"}
def kp(n):
    n = str(n).strip()
    if n in _K: return n
    for c in (_MAN.get(n), _XB.get(n), _XB.get(_MAN.get(n, '')), _fix(n), _fix(_MAN.get(n, '') or n)):
        if c and c in _K: return c
    return None
def pn(x):
    x = unicodedata.normalize('NFKD', str(x or '')).encode('ascii', 'ignore').decode().lower()
    x = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', x)
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', x.replace("'", '').replace('’', ''))).strip()

# ---- Nov 14 (Jon): fuzzy player match. Exact pn() match first; otherwise same last name + compatible first name
# (one a prefix of the other — Josh/Joshua, Cam/Cameron — or a common nickname — Joe/Joseph, Mike/Michael), unique within the team.
_NICK = {'joe': 'joseph', 'joey': 'joseph', 'mike': 'michael', 'jim': 'james', 'jimmy': 'james', 'jamie': 'james', 'tony': 'anthony',
         'bob': 'robert', 'rob': 'robert', 'bobby': 'robert', 'bill': 'william', 'will': 'william', 'billy': 'william', 'liam': 'william',
         'charlie': 'charles', 'chuck': 'charles', 'andy': 'andrew', 'drew': 'andrew', 'dre': 'andre', 'tre': 'trevon', 'trey': 'trevon',
         'dj': 'dj', 'aj': 'aj', 'cj': 'cj', 'tj': 'tj', 'jj': 'jj', 'rj': 'rj', 'bj': 'bj', 'kj': 'kj', 'pj': 'pj', 'mj': 'mj',
         'dan': 'daniel', 'danny': 'daniel', 'matt': 'matthew', 'nate': 'nathan', 'nick': 'nicholas', 'zach': 'zachary', 'zack': 'zachary',
         'sam': 'samuel', 'ben': 'benjamin', 'alex': 'alexander', 'chris': 'christopher', 'tom': 'thomas', 'tommy': 'thomas', 'ed': 'edward',
         'eddie': 'edward', 'ty': 'tyler', 'jon': 'jonathan', 'johnny': 'john', 'jack': 'john', 'kenny': 'kenneth', 'ken': 'kenneth',
         'greg': 'gregory', 'steve': 'steven', 'stevie': 'steven', 'cam': 'cameron', 'josh': 'joshua', 'jake': 'jacob', 'gabe': 'gabriel',
         'manny': 'emmanuel', 'izzy': 'isaiah', 'zeke': 'ezekiel', 'eli': 'elijah', 'ike': 'isaac', 'nico': 'nicolas', 'max': 'maxwell'}
def _parts(x):
    p = pn(x).split()
    if len(p) >= 3 and all(len(t) == 1 for t in p[:2]): p = [p[0] + p[1]] + p[2:]          # "b j edwards" -> "bj edwards"
    return p
def _first_ok(a, b):
    if a == b or a.startswith(b) or b.startswith(a): return min(len(a), len(b)) >= 2 or a == b
    return _NICK.get(a, a) == _NICK.get(b, b)
def same_player(a, b):
    if pn(a) == pn(b): return True
    pa, pb = _parts(a), _parts(b)
    if len(pa) < 2 or len(pb) < 2: return False
    return pa[-1] == pb[-1] and _first_ok(pa[0], pb[0])
def match_name(name, candidates):
    """Return the one candidate that is the same player as `name` (exact pn first, then same_player if unique), else None."""
    c = list(candidates); k = pn(name)
    ex = [x for x in c if pn(x) == k]
    if ex: return ex[0]
    fz = [x for x in c if same_player(name, x)]
    return fz[0] if len(set(map(pn, fz))) == 1 else None
