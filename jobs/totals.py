"""Totals shadow log: the validated TIS totals formula on the live tempo profiles, logged for every game, graded next day.

Formula (TIS_GE_Handoff.md, GE retired):
  ModelTotal = 2 * (PossBase + k * ImpDirDom) * PPP_game + BiasAdj
  PossBase  = KenPom FanMatch PredTempo
  ImpDirDom = NetTIS of the team with the larger StrengthDom (winner-take-all; both zero -> the average)
  k         = 1.40 if ImpDirDom < 0, else 0.0
  PPP_game  = (AdjOE_home + AdjDE_away + AdjOE_away + AdjDE_home) / 4 / 100   (KenPom ratings pulled that morning)
  BiasAdj   = clip((160 - raw) / 30, 0, 1)
Run twice per game: on the raw profiles (every possession, as in 2025-26) and on the competitive profiles
(leverage-weighted, buzzer / short-clock / foul-sequence / OT possessions out) from jobs/tempo.py.

Market number: the card's consensus total at ~4:15 AM ET (cards/card_<date>.csv) — the early number.
Rule flag (validated 2025-26): model UNDER the early number, early total 145-160, net efficiency gap < 10,
and both teams with 9+ D-I games in the tempo store (the old profiles' minimum).

Outputs (data/totals/):
  shadow_<date>.csv   that day's games
  shadow_log.csv      every day; final total, CBBD open/close totals and results filled in on later runs

Usage: python jobs/totals.py [--date YYYY-MM-DD]     (default today ET; needs data/kenpom/*_<date>.csv from jobs/kenpom.py)
"""
import os, sys, json, time, argparse, statistics as st, datetime as dt
from zoneinfo import ZoneInfo

import numpy as np, pandas as pd

OUT = 'data/totals'
ET = ZoneInfo('America/New_York')
K_UNDER, K_OVER = 1.40, 0.0
RULE_LO, RULE_HI, RULE_GAP, RULE_GAMES = 145, 160, 10, 9


def model_total(poss, imp, ppp):
    if any(pd.isna(v) for v in (poss, imp, ppp)): return np.nan
    raw = 2 * (poss + (K_UNDER if imp < 0 else K_OVER) * imp) * ppp
    return raw + min(1.0, max(0.0, (160 - raw) / 30))


def imp_dir(ph, pa, tag):
    sh, sa = ph.get(f'StrengthDom_{tag}'), pa.get(f'StrengthDom_{tag}')
    nh, na = ph.get(f'NetTIS_{tag}'), pa.get(f'NetTIS_{tag}')
    if any(pd.isna(v) for v in (sh, sa, nh, na)): return np.nan, ''
    if sh + sa == 0: return (nh + na) / 2, 'neither'
    return (nh, 'home') if sh >= sa else (na, 'away')


def build(d):
    card_f, fm_f = f'cards/card_{d}.csv', f'data/kenpom/fanmatch_{d}.csv'
    rat_f = f'data/kenpom/ratings_{d}.csv' if os.path.exists(f'data/kenpom/ratings_{d}.csv') else 'data/kenpom/ratings_current.csv'
    for f in (card_f, fm_f, rat_f):
        if not os.path.exists(f): sys.exit(f'missing {f}')
    C = pd.read_csv(card_f, encoding='utf-8-sig')
    FM = pd.read_csv(fm_f)
    R = pd.read_csv(rat_f).set_index('TeamName')
    T = pd.read_csv('data/tempo/teams_current.csv').set_index('team')
    fm = {frozenset((r.Visitor, r.Home)): r for r in FM.itertuples()}

    rows, unmatched = [], []
    for g in C.itertuples():
        f = fm.get(frozenset((g.away, g.home)))
        if f is None: unmatched.append(f'{g.away} at {g.home}'); continue
        ph = T.loc[g.home].to_dict() if g.home in T.index else {}
        pa = T.loc[g.away].to_dict() if g.away in T.index else {}
        rh = R.loc[g.home] if g.home in R.index else None
        ra = R.loc[g.away] if g.away in R.index else None
        ppp = np.nan if rh is None or ra is None else (rh.AdjOE + ra.AdjDE + ra.AdjOE + rh.AdjDE) / 400
        gap = np.nan if rh is None or ra is None else abs((rh.AdjOE - rh.AdjDE) - (ra.AdjOE - ra.AdjDE))
        poss = float(f.PredTempo)
        hp, vp = (f.HomePred, f.VisitorPred) if f.Home == g.home else (f.VisitorPred, f.HomePred)
        total = pd.to_numeric(g.total, errors='coerce')
        rec = dict(date=d, tip_ET=g.tip_ET, away=g.away, home=g.home, venue=g.venue, early_total=total,
                   kp_total=round(hp + vp, 1), kp_tempo=round(poss, 1), ppp_game=round(ppp, 4) if pd.notna(ppp) else np.nan,
                   net_eff_gap=round(gap, 1) if pd.notna(gap) else np.nan,
                   games_away=int(pa.get('games', 0) or 0), games_home=int(ph.get('games', 0) or 0))
        for tag in ('raw', 'comp'):
            imp, who = imp_dir(ph, pa, tag)
            m = model_total(poss, imp, ppp)
            rec[f'imp_{tag}'] = round(imp, 3) if pd.notna(imp) else np.nan
            rec[f'dom_{tag}'] = g.home if who == 'home' else g.away if who == 'away' else who
            rec[f'model_{tag}'] = round(m, 1) if pd.notna(m) else np.nan
            rec[f'diff_{tag}'] = round(m - total, 1) if pd.notna(m) and pd.notna(total) else np.nan
            rec[f'lean_{tag}'] = '' if pd.isna(rec[f'diff_{tag}']) or rec[f'diff_{tag}'] == 0 else ('U' if rec[f'diff_{tag}'] < 0 else 'O')
        mature = min(rec['games_away'], rec['games_home']) >= RULE_GAMES
        for tag in ('raw', 'comp'):
            rec[f'rule_{tag}'] = bool(rec[f'lean_{tag}'] == 'U' and pd.notna(total) and RULE_LO <= total < RULE_HI
                                      and pd.notna(gap) and gap < RULE_GAP and mature)
        rows.append(rec)
    S = pd.DataFrame(rows)
    if unmatched: print(f'{len(unmatched)} card games not in FanMatch:', '; '.join(unmatched[:15]))
    return S


# ----------------------------------------------------------------- grading
def grade(log):
    """fill final totals from the box-score store and CBBD open/close totals for ungraded past dates"""
    today = dt.datetime.now(ET).strftime('%Y-%m-%d')
    todo = log[(log.date < today) & log.final_total.isna()] if 'final_total' in log else log[log.date < today]
    if not len(todo): return log
    xw = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    G = pd.read_csv('data/games_2026-27.csv')
    G['kt'], G['ko'] = G.team.map(xw), G.opp.map(xw)
    fin = {(r.date, frozenset((r.kt, r.ko))): r.pts + r.opp_pts for r in G.dropna(subset=['kt', 'ko']).itertuples()}
    oc = cbbd_totals(sorted(todo.date.unique()), xw)
    for i in todo.index:
        key = (log.at[i, 'date'], frozenset((log.at[i, 'away'], log.at[i, 'home'])))
        if key in fin: log.at[i, 'final_total'] = fin[key]
        if key in oc: log.at[i, 'cbbd_open'], log.at[i, 'cbbd_close'] = oc[key]
    for tag in ('raw', 'comp'):
        lean, ft, et = log[f'lean_{tag}'], log.final_total, log.early_total
        res = np.where(ft.isna() | et.isna() | (lean == ''), '',
                       np.where(ft == et, 'P', np.where((ft < et) == (lean == 'U'), 'W', 'L')))
        log[f'result_{tag}'] = res
    return log


def cbbd_totals(dates, xw):
    key = os.environ.get('CBBD_API_KEY', '').strip()
    if not key or not dates: return {}
    import requests
    hdr = {'Authorization': f'Bearer {key}', 'Accept': 'application/json'}
    out = {}
    try:
        r = requests.get('https://api.collegebasketballdata.com/lines', headers=hdr, timeout=180,
                         params=dict(season=2027, startDateRange=dates[0], endDateRange=(dt.date.fromisoformat(dates[-1]) + dt.timedelta(days=1)).isoformat()))
        r.raise_for_status()
    except Exception as e:
        print('CBBD lines unavailable for grading:', e); return {}
    for g in r.json():
        ln = g.get('lines') or []
        o = [float(x['overUnderOpen']) for x in ln if x.get('overUnderOpen') is not None]
        c = [float(x['overUnder']) for x in ln if x.get('overUnder') is not None]
        h, a = xw.get(g.get('homeTeam', '')), xw.get(g.get('awayTeam', ''))
        sd = g.get('startDate') or ''
        if not (h and a and sd): continue
        d = pd.Timestamp(sd).tz_convert('America/New_York').strftime('%Y-%m-%d') if pd.Timestamp(sd).tzinfo else sd[:10]
        out[(d, frozenset((a, h)))] = (st.median(o) if o else np.nan, st.median(c) if c else np.nan)
    return out


def record(df, mask, label):
    s = df[mask]
    w, l, p = (s == 'W').sum(), (s == 'L').sum(), (s == 'P').sum()
    return f'{label}: {w}-{l}' + (f'-{p}' if p else '') + (f'  ({w / (w + l):.1%})' if w + l else '')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date'); a = ap.parse_args()
    d = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
    os.makedirs(OUT, exist_ok=True)
    S = build(d)
    S.to_csv(f'{OUT}/shadow_{d}.csv', index=False)
    lf = f'{OUT}/shadow_log.csv'
    log = pd.read_csv(lf) if os.path.exists(lf) else pd.DataFrame()
    if len(log): log = log[log.date != d]
    log = pd.concat([log, S], ignore_index=True)
    for c in ('final_total', 'cbbd_open', 'cbbd_close'):
        if c not in log: log[c] = np.nan
    log = grade(log).sort_values(['date', 'tip_ET']).reset_index(drop=True)
    log.to_csv(lf, index=False)

    print(f'{d}: {len(S)} games; model on both profiles for {S.model_comp.notna().sum()}; '
          f'rule (comp) {int(S.rule_comp.sum())}, rule (raw) {int(S.rule_raw.sum())}; '
          f'teams with {RULE_GAMES}+ games: {int(((S.games_away >= RULE_GAMES) & (S.games_home >= RULE_GAMES)).sum())} games')
    g = log[log.final_total.notna()]
    if len(g):
        print(f'graded so far: {len(g)} games through {g.date.max()}')
        for tag in ('comp', 'raw'):
            r = g[f'result_{tag}']
            print('  ' + ' | '.join([record(r, g[f'lean_{tag}'] != '', f'{tag} all'), record(r, g[f'lean_{tag}'] == 'U', 'UNDER'),
                                     record(r, g[f'rule_{tag}'], 'rule')]))
        print(f'  mean final - early total {(g.final_total - g.early_total).mean():+.1f}; '
              f'model_comp - final {(g.model_comp - g.final_total).mean():+.1f} (MAE {(g.model_comp - g.final_total).abs().mean():.1f}); '
              f'kp_total - final {(g.kp_total - g.final_total).mean():+.1f} (MAE {(g.kp_total - g.final_total).abs().mean():.1f})')
    # parser cross-check: our raw offensive APL against KenPom's own APL_Off
    try:
        R = pd.read_csv('data/kenpom/ratings_current.csv').set_index('TeamName')
        T = pd.read_csv('data/tempo/teams_current.csv').set_index('team')
        j = T.join(R[['APL_Off', 'APL_Def']], how='inner')
        j = j[j.games >= 2]
        print(f'tempo vs KenPom APL (teams with 2+ games, n={len(j)}): off r {j.off_apl_raw.corr(j.APL_Off):.2f} '
              f'(ours {j.off_apl_raw.mean():.1f} vs KP {j.APL_Off.mean():.1f}), def r {j.def_apl_raw.corr(j.APL_Def):.2f}')
    except Exception as e:
        print('APL cross-check skipped:', e)


if __name__ == '__main__':
    main()
