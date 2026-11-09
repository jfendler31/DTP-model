"""Shared in-season rating math — used by jobs/ratings.py (production) and jobs/ratings_shadow.py, so the two can't drift.

Game inputs: one record per D-I vs D-I game (home-row perspective) with the five pillars, built either from CBBD box
totals or from the play-by-play competitive totals in data/pbp/game_factors.csv (jobs/pbp_factors.py).
"""
import collections, datetime as dt
import numpy as np, pandas as pd

W = {'net2pt': .32, 'netreb': .26, 'netto': .24, 'net3pt': .10, 'netfta': .08}; PILLARS = list(W)
RIDGE, EARLY_N = 0.5, 3
COLS = ('p2m', 'p2a', 'p3m', 'p3a', 'fta', 'fga', 'orb', 'drb', 'to', 'poss')
REB_TEAM = False        # 2025-26 on: box rebounds exclude team rebounds; so do ours (player rebounds match box to 0.00).
                        # 2024-25 box counts include them — backtests of that season pass reb_team=True.
GATE = dict(fga=4, fta=3, to=3, reb=4)   # max |raw pbp - box| per team for a game to use its play-by-play totals


def K_of(d):
    d = dt.date.fromisoformat(d); k = 8 + 4 * (d - dt.date(2026, 12, 1)).days / 45
    return float(min(max(k, 8), 12))


def pillars(s, o):
    return dict(net2pt=s['p2m'] / s['p2a'] - o['p2m'] / o['p2a'], net3pt=s['p3m'] / s['p3a'] - o['p3m'] / o['p3a'],
                netreb=s['orb'] / (s['orb'] + o['drb']) - o['orb'] / (o['orb'] + s['drb']),
                netfta=s['fta'] / s['fga'] - o['fta'] / o['fga'], netto=o['to'] / o['poss'] - s['to'] / s['poss'])


def usable(d):
    return d is not None and all(pd.notna(d[k]) for k in COLS) and min(d['p2a'], d['p3a'], d['fga'], d['poss']) > 0


def load_factors(path):
    import os
    if not os.path.exists(path): return {}
    F = pd.read_csv(path)
    return {(int(r.gameId), r.team): r for r in F.itertuples(index=False)}


def pbp_side(FX, gid, team, v, reb_team=None):
    rt = REB_TEAM if reb_team is None else reb_team
    r = FX.get((int(gid), team))
    if r is None: return None
    g = lambda s: float(getattr(r, f'{s}_{v}'))
    d = dict(p2m=g('p2m'), p2a=g('p2a'), p3m=g('p3m'), p3a=g('p3a'), fta=g('fta'), to=g('to'), poss=g('poss'),
             orb=g('orb') + (g('orbt') if rt else 0), drb=g('drb') + (g('drbt') if rt else 0))
    d['fga'] = d['p2a'] + d['p3a']
    return d


def gate(bs, bo, ps, po):
    """[] if raw play-by-play agrees with the box score for both teams, else the failing checks"""
    fails = []
    for b_, p_ in ((bs, ps), (bo, po)):
        d = dict(fga=abs(p_['p2a'] - b_['p2a']) + abs(p_['p3a'] - b_['p3a']), fta=abs(p_['fta'] - b_['fta']),
                 to=abs(p_['to'] - b_['to']), reb=abs(p_['orb'] - b_['orb']) + abs(p_['drb'] - b_['drb']))
        fails += [k for k, lim in GATE.items() if d[k] > lim]
    return fails


def build_games(TG, tix, XB, FX, src, log=None, reb_team=None):
    """TG: games_2026-27.csv rows already filtered to finished games before the as-of date.
    src: 'box' or a game_factors version ('raw', 'cw', 'cc'). Each game also carries n_poss (possessions behind its
    pillars: competitive possessions for play-by-play games, box possessions otherwise) for optional game weighting.
    log: Counter for source counts. Returns (games, unmapped team names)."""
    G, unmapped = [], set()
    for gid, x in TG.groupby('gameId'):
        r = x[x.isHome == True].iloc[0] if (x.isHome == True).any() else x.iloc[0]
        tm, op = XB.get(r.team) or (r.team if r.team in tix else None), XB.get(r.opp) or (r.opp if r.opp in tix else None)
        if tm not in tix or op not in tix:
            for nm, k in ((r.team, tm), (r.opp, op)):
                if k not in tix: unmapped.add(nm)
            continue
        bs, bo = {c: r[c] for c in COLS}, {c: r['opp_' + c] for c in COLS}
        if not (usable(bs) and usable(bo)): continue
        bs, bo = {k: float(v) for k, v in bs.items()}, {k: float(v) for k, v in bo.items()}
        base = dict(gameId=int(gid), date=r.date, t=tix[tm], o=tix[op], home=not (pd.notna(r.neutral) and bool(r.neutral)))
        s_ = o_ = None
        if src != 'box':
            ps, po = pbp_side(FX, gid, r.team, 'raw', reb_team), pbp_side(FX, gid, r.opp, 'raw', reb_team)
            if ps is None or po is None: tag = 'box (no play-by-play)'
            elif gate(bs, bo, ps, po): tag = 'box (play-by-play failed check)'
            else:
                s_, o_ = pbp_side(FX, gid, r.team, src, reb_team), pbp_side(FX, gid, r.opp, src, reb_team)
                tag = 'play-by-play' if usable(s_) and usable(o_) else 'box (too few competitive possessions)'
                if tag != 'play-by-play': s_ = o_ = None
        else:
            tag = 'box'
        if log is not None: log[tag] += 1
        if s_ is not None:
            G.append({**base, **pillars(s_, o_), 'n_poss': (s_['poss'] + o_['poss']) / 2, 'src': 'pbp'})
        else:
            G.append({**base, **pillars(bs, bo), 'n_poss': (bs['poss'] + bo['poss']) / 2, 'src': 'box'})
    return G, unmapped


def rate(G, n, zp, asof, game_wt=False):
    """production rating math. game_wt: weight each game by its possessions (mean weight 1) in the SRS and in the
    games-1-2 fit and averaging; off = every game counts equally (production through Nov 8).
    Returns dict(z_blend, z_in, surprise, N, lam, method, K, fit)."""
    N = np.zeros(n)
    for x in G: N[x['t']] += 1; N[x['o']] += 1
    mask = N > 0
    w = np.array([x['n_poss'] for x in G], float) if game_wt and len(G) else np.ones(len(G))
    if len(G): w = w / w.mean()
    sw = np.sqrt(w)
    def srs(p, sd):
        A = np.zeros((len(G), n + 1)); y = np.zeros(len(G))
        for i, x in enumerate(G):
            A[i, x['t']] = 1; A[i, x['o']] = -1; A[i, n] = 1.0 if x['home'] else 0.0
            y[i] = float(np.clip(x[p], -3 * sd, 3 * sd))
        A, y = A * sw[:, None], y * sw
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
        X = np.column_stack([hm, gap]); (a_h, b), *_ = np.linalg.lstsq(X * sw[:, None], c * sw, rcond=None)
        res = (c - X @ np.array([a_h, b])) / b
        acc = collections.defaultdict(list)
        for x, r, wi in zip(G, res, w): acc[x['t']].append((r, wi)); acc[x['o']].append((-r, wi))
        for i, v in acc.items(): surprise[i] = sum(r * wi for r, wi in v) / sum(wi for _, wi in v)
        zb = np.where(method == 'early', zp + lam * np.nan_to_num(surprise), zb)
        r2 = 1 - np.var(c - X @ np.array([a_h, b])) / np.var(c)
        fit = f'composite = {a_h:.3f}*home + {b:.3f}*prior gap (z), R^2 {r2:.2f}'
    return dict(z_blend=zb, z_in=np.where(mask, z_in, np.nan), surprise=surprise, N=N, lam=lam, method=method, K=K, fit=fit)


def frame(teams, zp, out, asof):
    zb = out['z_blend']
    return pd.DataFrame(dict(team=teams, n_games=out['N'].astype(int), K=out['K'], lam=out['lam'].round(3), prior_wt=(1 - out['lam']).round(3),
                             z_prior=zp.round(4), z_inseason=np.round(out['z_in'], 4), surprise=np.round(out['surprise'], 4),
                             method=out['method'], z_blend=zb.round(4), move_pts=((zb - zp) * 9.5).round(2), asof=asof))
