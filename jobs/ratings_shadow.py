"""Shadow ratings with garbage time out — runs beside production, changes nothing production reads.

Same math as jobs/ratings.py (four-factor ridge SRS from game 3, option 2b in games 1-2, lam = N/(N+K)), run four ways:
  box      the production inputs (CBBD box totals) — must reproduce data/ratings_current.csv (self-check, printed)
  pbp_raw  play-by-play totals, every possession — the parser control: differences from box are parse noise
  cw       competitive, leverage-weighted (tempo definition: lev weight, ot / half_end / short_clock / foul_seq out)
  cc       competitive, hard cutoff (lev >= 0.5, same structural drops)
A game whose raw play-by-play totals don't agree with its box score (GATE below), or that has no play-by-play,
uses its box totals in every version; counts are printed.

Inputs: data/games_2026-27.csv (written by the morning ratings run), data/pbp/game_factors.csv (jobs/tempo.py),
        data/prior_2026-27.csv, data/xwalk_cbbd_kp.json; cards/card_<date>.csv if it exists.
Outputs (data/ratings_shadow/):
  ratings_<version>_<date>.csv   same columns as production
  compare_<date>.csv, compare_current.csv   one row per team: z and points under each version, deltas vs box
  card_<date>.csv                today's card games: model home spread and edge under each version
  check_<date>.csv               raw play-by-play vs box, per team-game (the gate)
Usage: python jobs/ratings_shadow.py [--date YYYY-MM-DD]
"""
import os, json, argparse, collections, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

ET = ZoneInfo('America/New_York')
W = {'net2pt': .32, 'netreb': .26, 'netto': .24, 'net3pt': .10, 'netfta': .08}; PILLARS = list(W)
RIDGE, EARLY_N = 0.5, 3
OUT = 'data/ratings_shadow'
VERSIONS = ('box', 'pbp_raw', 'cw', 'cc')
REB_TEAM = False        # count dead-ball team rebounds in the play-by-play rebound totals (set from the box check)
GATE = dict(fga=4, fta=3, to=3, reb=4)   # max |raw pbp - box| per team-game for the play-by-play versions to use a game
SIZE_K, SIZE_KNEE = 0.20, 10


def K_of(d):
    d = dt.date.fromisoformat(d); k = 8 + 4 * (d - dt.date(2026, 12, 1)).days / 45
    return float(min(max(k, 8), 12))


def pillars(s, o):
    """s, o: dicts with p2m p2a p3m p3a fta fga orb drb to poss for the team and its opponent"""
    return dict(net2pt=s['p2m'] / s['p2a'] - o['p2m'] / o['p2a'], net3pt=s['p3m'] / s['p3a'] - o['p3m'] / o['p3a'],
                netreb=s['orb'] / (s['orb'] + o['drb']) - o['orb'] / (o['orb'] + s['drb']),
                netfta=s['fta'] / s['fga'] - o['fta'] / o['fga'], netto=o['to'] / o['poss'] - s['to'] / s['poss'])


def ok(d):
    return all(pd.notna(d[k]) for k in ('p2m', 'p2a', 'p3m', 'p3a', 'fta', 'fga', 'orb', 'drb', 'to', 'poss')) and \
        min(d['p2a'], d['p3a'], d['fga'], d['poss']) > 0


def rate(G, n, zp, asof):
    """production rating math (jobs/ratings.py), returns (z_blend, z_in, surprise, N, lam, method, fit text)"""
    N = np.zeros(n)
    for x in G: N[x['t']] += 1; N[x['o']] += 1
    mask = N > 0
    def srs(p, sd):
        A = np.zeros((len(G), n + 1)); y = np.zeros(len(G))
        for i, x in enumerate(G):
            A[i, x['t']] = 1; A[i, x['o']] = -1; A[i, n] = 1.0 if x['home'] else 0.0
            y[i] = float(np.clip(x[p], -3 * sd, 3 * sd))
        reg = np.eye(n + 1) * RIDGE; reg[n, n] = 0
        return np.linalg.solve(A.T @ A + reg, A.T @ y)[:n]
    def zs(v):
        out = np.zeros(n)
        if mask.sum() > 2: m, s = v[mask].mean(), v[mask].std(); out[mask] = (v[mask] - m) / (s if s > 0 else 1)
        return out
    if len(G) >= 2:
        comp = sum(W[p] * zs(srs(p, np.std([x[p] for x in G]) or 1.0)) for p in PILLARS); z_in = zs(comp)
    else:
        z_in = np.zeros(n)
    K = K_of(asof); lam = N / (N + K)
    zb = lam * z_in + (1 - lam) * zp
    method = np.where(N >= EARLY_N, 'srs', np.where(N > 0, 'early', 'prior'))
    surprise = np.full(n, np.nan); fit = ''
    if len(G) >= 20:
        SDG = {p: (np.std([x[p] for x in G]) or 1.0) for p in PILLARS}
        c = np.array([sum(W[p] * float(np.clip(x[p], -3 * SDG[p], 3 * SDG[p])) / SDG[p] for p in PILLARS) for x in G])
        gap = np.array([zp[x['t']] - zp[x['o']] for x in G]); hm = np.array([1.0 if x['home'] else 0.0 for x in G])
        X = np.column_stack([hm, gap]); (a_h, b), *_ = np.linalg.lstsq(X, c, rcond=None)
        res = (c - X @ np.array([a_h, b])) / b
        acc = collections.defaultdict(list)
        for x, r in zip(G, res): acc[x['t']].append(r); acc[x['o']].append(-r)
        for i, v in acc.items(): surprise[i] = np.mean(v)
        zb = np.where(method == 'early', zp + lam * np.nan_to_num(surprise), zb)
        r2 = 1 - np.var(c - X @ np.array([a_h, b])) / np.var(c)
        fit = f'{a_h:.3f}*home + {b:.3f}*gap, R^2 {r2:.2f}'
    return zb, np.where(mask, z_in, np.nan), surprise, N, lam, method, K, fit


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date'); a = ap.parse_args()
    asof = a.date or dt.datetime.now(ET).strftime('%Y-%m-%d')
    os.makedirs(OUT, exist_ok=True)
    TG = pd.read_csv('data/games_2026-27.csv')
    P = pd.read_csv('data/prior_2026-27.csv'); teams = list(P.team); tix = {t: i for i, t in enumerate(teams)}
    zp = P.z_prior.to_numpy(float); n = len(teams)
    XB = {k: v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    XB.update({'New Orleans': 'LSU New Orleans', 'Miami': 'Miami FL'})
    fpath = 'data/pbp/game_factors.csv'
    F = pd.read_csv(fpath) if os.path.exists(fpath) else pd.DataFrame(columns=['gameId', 'team'])
    FX = {(int(r.gameId), r.team): r for r in F.itertuples(index=False)}

    def pbp_side(gid, team, v):
        r = FX.get((int(gid), team))
        if r is None: return None
        g = lambda s: float(getattr(r, f'{s}_{v}'))
        d = dict(p2m=g('p2m'), p2a=g('p2a'), p3m=g('p3m'), p3a=g('p3a'), fta=g('fta'), to=g('to'), poss=g('poss'),
                 orb=g('orb') + (g('orbt') if REB_TEAM else 0), drb=g('drb') + (g('drbt') if REB_TEAM else 0))
        d['fga'] = d['p2a'] + d['p3a']
        return d

    TG = TG[(TG.date < asof) & TG.pts.notna() & TG.opp_pts.notna()]
    G = {v: [] for v in VERSIONS}; src = collections.Counter(); checks = []
    for gid, x in TG.groupby('gameId'):
        r = x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]
        tm, op = XB.get(r.team) or (r.team if r.team in tix else None), XB.get(r.opp) or (r.opp if r.opp in tix else None)
        if tm not in tix or op not in tix: continue
        cols = ('p2m', 'p2a', 'p3m', 'p3a', 'fta', 'fga', 'orb', 'drb', 'to', 'poss')
        bs, bo = {c: r[c] for c in cols}, {c: r['opp_' + c] for c in cols}
        if not (ok(bs) and ok(bo)): continue
        bs, bo = {k: float(v) for k, v in bs.items()}, {k: float(v) for k, v in bo.items()}
        base = dict(gameId=int(gid), date=r.date, t=tix[tm], o=tix[op], home=not bool(r.neutral))
        G['box'].append({**base, **pillars(bs, bo)})
        # gate: raw play-by-play must agree with the box score for both teams
        ps, po = pbp_side(gid, r.team, 'raw'), pbp_side(gid, r.opp, 'raw')
        use = False
        if ps and po:
            fails = []
            for nm, b_, p_ in ((r.team, bs, ps), (r.opp, bo, po)):
                d = dict(fga=abs(p_['p2a'] - b_['p2a']) + abs(p_['p3a'] - b_['p3a']), fta=abs(p_['fta'] - b_['fta']),
                         to=abs(p_['to'] - b_['to']), reb=abs(p_['orb'] - b_['orb']) + abs(p_['drb'] - b_['drb']))
                rr = pbp_side(gid, nm, 'raw'); fac = FX[(int(gid), nm)]
                checks.append(dict(gameId=int(gid), date=r.date, team=nm, **{f'box_{c}': b_[c] for c in cols},
                                   **{f'pbp_{c}': p_[c] for c in cols}, orbt=fac.orbt_raw, drbt=fac.drbt_raw, n_orphan=fac.n_orphan,
                                   **{f'd_{k}': v for k, v in d.items()}))
                fails += [k for k, lim in GATE.items() if d[k] > lim]
            use = not fails
            src['pbp' if use else 'gate_fail'] += 1
            if fails: src.update(f'fail_{k}' for k in set(fails))
        else:
            src['no_pbp'] += 1
        for v, key in (('pbp_raw', 'raw'), ('cw', 'cw'), ('cc', 'cc')):
            s_, o_ = (pbp_side(gid, r.team, key), pbp_side(gid, r.opp, key)) if use else (None, None)
            if s_ and o_ and ok(s_) and ok(o_):
                G[v].append({**base, **pillars(s_, o_)})
            else:
                if use: src[f'{v}_fallback_zero'] += 1
                G[v].append({**base, **pillars(bs, bo)})

    print(f'shadow ratings as of {asof}: {len(G["box"])} D-I games; sources {dict(src)}')
    C = pd.DataFrame(checks)
    if len(C):
        C.to_csv(f'{OUT}/check_{asof}.csv', index=False)
        print('raw play-by-play vs box, per team-game (mean diff / mean |diff|):')
        for c in ('p2a', 'p3a', 'p2m', 'p3m', 'fta', 'orb', 'drb', 'to', 'poss'):
            dd = C[f'pbp_{c}'] - C[f'box_{c}']
            print(f'  {c:5s} {dd.mean():+.2f} / {dd.abs().mean():.2f}')
        for c, t in (('orb', 'orbt'), ('drb', 'drbt')):
            print(f'  {c}+team rebounds: {(C[f"pbp_{c}"] + C[t] - C[f"box_{c}"]).mean():+.2f} / {(C[f"pbp_{c}"] + C[t] - C[f"box_{c}"]).abs().mean():.2f}')

    res = {}
    for v in VERSIONS:
        zb, zin, sur, N, lam, method, K, fit = rate(G[v], n, zp, asof)
        res[v] = zb
        print(f'  {v:8s} early-game fit: {fit}')
        R = pd.DataFrame(dict(team=teams, n_games=N.astype(int), K=K, lam=lam.round(3), prior_wt=(1 - lam).round(3), z_prior=zp.round(4),
                              z_inseason=np.round(zin, 4), surprise=np.round(sur, 4), method=method, z_blend=zb.round(4),
                              move_pts=((zb - zp) * 9.5).round(2), asof=asof))
        if v != 'box': R.to_csv(f'{OUT}/ratings_{v}_{asof}.csv', index=False)
        if v == 'box': Nn = N
    # self-check against production
    prod = pd.read_csv('data/ratings_current.csv')
    if str(prod['asof'].iloc[0]) == asof:
        pz = prod.set_index('team').z_blend.reindex(teams).to_numpy(float)
        print(f'self-check vs data/ratings_current.csv: max |z diff| {np.nanmax(np.abs(np.round(res["box"], 4) - pz)):.4f} (0 = reproduces production)')
    else:
        print(f'self-check skipped: ratings_current.csv is as of {prod['asof'].iloc[0]}, shadow as of {asof}')

    cmp = pd.DataFrame(dict(team=teams, n_games=Nn.astype(int), z_prior=zp.round(4), **{f'z_{v}': res[v].round(4) for v in VERSIONS}))
    for v in ('pbp_raw', 'cw', 'cc'): cmp[f'd_{v}_pts'] = ((res[v] - res['box']) * 9.5).round(2)
    cmp['d_cw_vs_raw_pts'] = ((res['cw'] - res['pbp_raw']) * 9.5).round(2)
    cmp['d_cc_vs_raw_pts'] = ((res['cc'] - res['pbp_raw']) * 9.5).round(2)
    cmp['asof'] = asof
    cmp.to_csv(f'{OUT}/compare_{asof}.csv', index=False); cmp.to_csv(f'{OUT}/compare_current.csv', index=False)
    g = cmp[cmp.n_games > 0]
    for c in ('d_pbp_raw_pts', 'd_cw_pts', 'd_cc_pts', 'd_cw_vs_raw_pts', 'd_cc_vs_raw_pts'):
        print(f'  {c:17s} teams with games {len(g)}: mean |delta| {g[c].abs().mean():.2f} pts, 90th pct {g[c].abs().quantile(.9):.2f}, max {g[c].abs().max():.2f}')
    top = g.reindex(g.d_cw_pts.abs().sort_values(ascending=False).index).head(12)
    print('largest cw moves vs production (pts):'); print(top[['team', 'n_games', 'd_pbp_raw_pts', 'd_cw_pts', 'd_cc_pts']].to_string(index=False))

    # today's card under each version (model numbers only; overrides and HCA unchanged, so the change is the rating delta)
    cf = f'cards/card_{asof}.csv'
    if os.path.exists(cf):
        cd = pd.read_csv(cf); Z = {v: dict(zip(teams, res[v])) for v in VERSIONS}
        conf = dict(zip(P.team, P.conf)) if 'conf' in P else {}
        out = []
        for c in cd.itertuples(index=False):
            if c.away not in Z['box'] or c.home not in Z['box'] or pd.isna(c.model_home_spread): continue
            row = dict(tip_ET=c.tip_ET, away=c.away, home=c.home, venue=c.venue, market_home_spread=c.market_home_spread,
                       model_box=c.model_home_spread)
            for v in ('pbp_raw', 'cw', 'cc'):
                dz = (Z[v][c.home] - Z['box'][c.home]) - (Z[v][c.away] - Z['box'][c.away])
                m = round(float(c.model_home_spread) - 9.5 * dz, 1); row[f'model_{v}'] = m
                row[f'edge_{v}'] = None if pd.isna(c.market_home_spread) else round(float(c.market_home_spread) - m, 1)
            row['edge_box'] = None if pd.isna(c.market_home_spread) else round(float(c.market_home_spread) - float(c.model_home_spread), 1)
            out.append(row)
        if out:
            CD = pd.DataFrame(out); CD['cw_minus_box'] = (CD.model_cw - CD.model_box).round(1)
            CD.to_csv(f'{OUT}/card_{asof}.csv', index=False, encoding='utf-8-sig')
            print(f'card {asof}: {len(CD)} games; model spread change cw vs box: mean |{CD.cw_minus_box.abs().mean():.2f}|, '
                  f'max {CD.cw_minus_box.abs().max():.1f}; games moving 0.5+: {(CD.cw_minus_box.abs() >= 0.5).sum()}')


if __name__ == '__main__':
    main()
