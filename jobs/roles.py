"""Player role cards from play-by-play (Nov 12, 2026).

Inputs: data/roles/events_*.csv.gz (jobs/role_events.py), data/tempo/possessions_*.csv.gz (possession start type and
leverage), data/rotation/player_games.csv (raw and leverage minutes), data/players/history/roster_2027_ALL.csv
(position, height). D-I vs D-I games only; every event weighted by its possession's leverage (garbage time ~0), minutes
are leverage minutes, so the numbers describe competitive basketball.

Per player: usage %, assist %, TO %, shot mix (rim / mid / three) and how much of each is assisted, putbacks, transition
shots, OREB / DREB / STL / BLK per 40, top assist partners; then rule-based role labels (see LABELS below).
Writes data/roles/roles_current.csv (players) and data/roles/assist_pairs.csv. Print one team:
  python jobs/roles.py --team "Oklahoma St."
"""
import os, glob, argparse, json
import numpy as np, pandas as pd

OUT = 'data/roles'
PUTBACK_S, TRANS_S = 4, 7
MIN_LEV = 20          # leverage minutes before a player gets labels


def load():
    E = pd.concat([pd.read_csv(f, low_memory=False) for f in sorted(glob.glob(f'{OUT}/events_*.csv.gz'))], ignore_index=True)
    P = pd.concat([pd.read_csv(f) for f in sorted(glob.glob('data/tempo/possessions_*.csv.gz'))], ignore_index=True)
    PG = pd.read_csv('data/rotation/player_games.csv')
    R = pd.read_csv('data/players/history/roster_2027_ALL.csv')
    return E, P, PG, R


def kind(r):
    pt = str(r.playType).lower().replace(' ', '')
    if 'freethrow' in pt or str(r.range).lower() in ('free_throw', 'freethrow'): return 'ft'
    if 'block' in pt: return 'blk'
    if 'steal' in pt: return 'stl'
    if 'turnover' in pt: return 'to'
    if 'offensiverebound' in pt: return 'oreb'
    if 'defensiverebound' in pt: return 'dreb'
    if 'foul' in pt: return 'foul'
    if r.shooting == True or any(k in pt for k in ('jumper', 'layup', 'dunk', 'tip', 'hook', 'jumpshot')): return 'fga'
    return 'other'


def zone(r):
    rg = str(r.range).lower()
    if 'three' in rg: return 'three'
    if 'rim' in rg or 'layup' in rg or 'dunk' in rg: return 'rim'
    if 'jump' in rg: return 'mid'
    pt = str(r.playType).lower(); tx = str(r.playText).lower()
    if 'three point' in tx or r.value == 3: return 'three'
    if any(k in pt for k in ('layup', 'dunk', 'tip')): return 'rim'
    return 'mid'


def build():
    E, P, PG, R = load()
    E = E[E.t.notna() & E.team.notna()].copy()
    E['k'] = E.apply(kind, axis=1)
    E = E[E.k != 'other']
    # possession for each event: offense events (fga, ft, to, oreb) belong to the acting team's possession;
    # defensive events (dreb, stl, blk) to the opponent's possession
    E['off_team'] = np.where(E.k.isin(['dreb', 'stl', 'blk']), E.opp, E.team)
    P = P[P.d1_game == True][['gameId', 'team', 't0', 'dur', 'start_type', 'lev']].rename(columns={'team': 'off_team'})
    P['t0'] = P.t0.astype(float); E['t'] = E.t.astype(float)
    E = E.sort_values('t'); P = P.sort_values('t0')
    M = pd.merge_asof(E, P, left_on='t', right_on='t0', by=['gameId', 'off_team'], direction='backward', tolerance=60)
    M = M[M.lev.notna()].copy()                                   # D-I vs D-I possessions only
    M['w'] = M.lev.clip(0, 1)
    M['made'] = M.made.astype('boolean')
    M['assisted'] = M.assisted.astype('boolean')
    M['zone'] = np.where(M.k == 'fga', M.apply(zone, axis=1), None)
    tx = M.playText.astype(str).str.lower()
    M['sub'] = np.select([tx.str.contains('pullup|step back'), tx.str.contains('floating'), tx.str.contains('hook|turnaround'),
                          tx.str.contains('tip in'), tx.str.contains('dunk'), tx.str.contains('driving')],
                         ['pullup', 'floater', 'post', 'tip', 'dunk', 'drive'], 'other')
    M['since'] = M.t - M.t0
    M['trans'] = (M.k == 'fga') & M.start_type.isin(['dreb', 'steal']) & (M.since <= TRANS_S)
    # putback: a shot within PUTBACK_S seconds of the same player's offensive rebound
    ore = M[M.k == 'oreb'][['gameId', 'pid', 't']].rename(columns={'t': 't_or'}).sort_values('t_or')
    sh = M[M.k == 'fga'].sort_values('t')
    sh = pd.merge_asof(sh, ore, left_on='t', right_on='t_or', by=['gameId', 'pid'], direction='backward', tolerance=PUTBACK_S)
    M = M.merge(sh[['id', 't_or']], on='id', how='left'); M['putback'] = (M.k == 'fga') & M.t_or.notna()

    # minutes and team totals (leverage)
    PG = PG[PG.gameId.isin(M.gameId.unique())]
    mins = PG.groupby(['team', 'athleteId', 'athlete']).agg(min_lev=('min_lev', 'sum'), min_raw=('min_raw', 'sum'), gp=('gameId', 'nunique')).reset_index()
    tmin = PG.groupby('team').min_lev.sum()
    f = M[M.k == 'fga']; w = lambda m: (M.w * m)
    T = pd.DataFrame({
        'fga': f.groupby('team').w.sum(), 'fgm': f[f.made == True].groupby('team').w.sum(),
        'fta': M[M.k == 'ft'].groupby('team').w.sum(), 'to': M[M.k == 'to'].groupby('team').w.sum(),
        'oreb': M[M.k == 'oreb'].groupby('team').w.sum(), 'dreb': M[M.k == 'dreb'].groupby('team').w.sum()}).fillna(0)
    T['used'] = T.fga + 0.44 * T.fta + T.to
    opp_or = M[M.k == 'oreb'].groupby('opp').w.sum(); opp_dr = M[M.k == 'dreb'].groupby('opp').w.sum()
    T['or_chances'] = T.oreb + T.index.map(opp_dr).fillna(0); T['dr_chances'] = T.dreb + T.index.map(opp_or).fillna(0)
    T['min'] = tmin

    AST = M[(M.k == 'fga') & (M.made == True) & M.ast_id.notna()].groupby(['team', 'ast_id']).w.sum()
    S = []
    for (team, pid), x in M[M.pid.notna()].groupby(['team', 'pid']):
        fx = x[x.k == 'fga']
        d = dict(team=team, pid=int(pid), player=x.player.dropna().iloc[0] if x.player.notna().any() else None,
                 fga=fx.w.sum(), fgm=fx[fx.made == True].w.sum(), fta=x[x.k == 'ft'].w.sum(),
                 ftm=x[(x.k == 'ft') & (x.made == True)].w.sum(), to=x[x.k == 'to'].w.sum(),
                 oreb=x[x.k == 'oreb'].w.sum(), dreb=x[x.k == 'dreb'].w.sum(), stl=x[x.k == 'stl'].w.sum(), blk=x[x.k == 'blk'].w.sum(),
                 putback=fx[fx.putback].w.sum(), trans=fx[fx.trans].w.sum(), n_fga_raw=len(fx))
        for z in ('rim', 'mid', 'three'):
            zx = fx[fx.zone == z]
            d[f'{z}_a'] = zx.w.sum(); d[f'{z}_m'] = zx[zx.made == True].w.sum()
            d[f'{z}_ast'] = zx[(zx.made == True) & (zx.assisted == True)].w.sum()
        for st in ('pullup', 'floater', 'post', 'drive', 'dunk'):
            d[f'{st}_a'] = fx[fx['sub'] == st].w.sum()
        d['ast'] = float(AST.get((team, pid), 0.0))
        S.append(d)
    S = pd.DataFrame(S)
    S = S.merge(mins, left_on=['team', 'pid'], right_on=['team', 'athleteId'], how='left')
    S = S[S.min_lev.fillna(0) > 0].copy()
    S['share'] = S.min_lev / S.team.map(T['min']) * 5                  # fraction of team floor time
    S['usg'] = 100 * (S.fga + 0.44 * S.fta + S.to) / (S.share * S.team.map(T.used))
    S['ast_pct'] = 100 * S.ast / (S.share * S.team.map(T.fgm) - S.fgm).clip(lower=0.5)
    S['to_pct'] = 100 * S.to / (S.fga + 0.44 * S.fta + S.to).clip(lower=0.5)
    S['or_pct'] = 100 * S.oreb / (S.share * S.team.map(T.or_chances)).clip(lower=0.5)
    S['dr_pct'] = 100 * S.dreb / (S.share * S.team.map(T.dr_chances)).clip(lower=0.5)
    for c in ('stl', 'blk', 'putback', 'trans'): S[f'{c}40'] = 40 * S[c] / S.min_lev
    for z in ('rim', 'mid', 'three'):
        S[f'{z}_sh'] = S[f'{z}_a'] / S.fga.clip(lower=0.5)
        S[f'{z}_pct'] = S[f'{z}_m'] / S[f'{z}_a'].replace(0, np.nan)
        S[f'{z}_astd'] = S[f'{z}_ast'] / S[f'{z}_m'].replace(0, np.nan)
    for st in ('pullup', 'floater', 'post', 'drive', 'dunk'): S[f'{st}_sh'] = S[f'{st}_a'] / S.fga.clip(lower=0.5)
    S['astd'] = (S.rim_ast + S.mid_ast + S.three_ast) / S.fgm.replace(0, np.nan)
    S['efg'] = (S.fgm + 0.5 * S.three_m) / S.fga.replace(0, np.nan)
    S['ft_rate'] = S.fta / S.fga.replace(0, np.nan)
    Rr = R[R.team.notna()].drop_duplicates('id').set_index('id')
    S['pos'] = S.pid.map(Rr.position); S['ht'] = S.pid.map(Rr.height)
    S['big'] = (S.pos.isin(['Center']) | ((S.pos == 'Forward') & (S.ht >= 80)) | (S.ht >= 82))
    S['guard'] = (S.pos == 'Guard') | (S.ht <= 76)
    # team usage rank among players with real minutes
    S['usg_rank'] = S[S.min_lev >= MIN_LEV].groupby('team').usg.rank(ascending=False)
    S['labels'] = S.apply(labels, axis=1)
    XW = {k.strip(): v.strip() for k, v in json.load(open('data/xwalk_cbbd_kp.json')).items()}
    S['team_cbbd'] = S.team; S['team'] = S.team.map(lambda t: XW.get(t, t))
    S = S.sort_values(['team', 'min_lev'], ascending=[True, False])
    keep = ['team', 'team_cbbd', 'player', 'pid', 'pos', 'ht', 'gp', 'min_raw', 'min_lev', 'labels', 'usg', 'usg_rank', 'ast_pct', 'to_pct',
            'efg', 'ft_rate', 'rim_sh', 'mid_sh', 'three_sh', 'rim_pct', 'mid_pct', 'three_pct', 'rim_astd', 'mid_astd', 'three_astd',
            'astd', 'pullup_sh', 'floater_sh', 'post_sh', 'drive_sh', 'dunk_sh', 'putback40', 'trans40', 'or_pct', 'dr_pct', 'stl40', 'blk40', 'fga', 'n_fga_raw']
    S[keep].round(3).to_csv(f'{OUT}/roles_current.csv', index=False)
    # assist pairs
    a = M[(M.k == 'fga') & (M.made == True) & M.ast_id.notna()]
    A = a.groupby(['team', 'ast_name', 'player', 'zone']).w.sum().reset_index().rename(columns={'w': 'n'})
    A['team'] = A.team.map(lambda t: XW.get(t, t))
    A = A[A.n >= 0.5].sort_values(['team', 'n'], ascending=[True, False]); A.round(2).to_csv(f'{OUT}/assist_pairs.csv', index=False)
    print(f'{len(S)} players, {S.team.nunique()} teams, {int((S.min_lev >= MIN_LEV).sum())} with {MIN_LEV}+ leverage minutes')
    return S, A


def labels(r):
    """Rule-based roles. Thresholds are first cuts on 2-4 games; see Roles doc."""
    if not (r.min_lev >= MIN_LEV and r.n_fga_raw >= 6): return 'limited sample'
    L = []
    unast = 1 - (r.astd if pd.notna(r.astd) else 0.5)
    if r.usg >= 23 and r.ast_pct >= 20 and unast >= 0.55: L.append('lead engine')
    elif r.ast_pct >= 20 and r.usg < 23: L.append('connector' if r.to_pct < 22 else 'playmaker (loose)')
    if r.usg >= 22 and unast >= 0.6 and r.ast_pct < 20: L.append('self-creating scorer')
    if not r.big and r.rim_sh >= 0.45 and (1 - (r.rim_astd if pd.notna(r.rim_astd) else 0.5)) >= 0.6: L.append('slasher')
    if r.three_sh >= 0.55 and (r.three_astd if pd.notna(r.three_astd) else 1) >= 0.75: L.append('spot-up shooter')
    if (r.three_sh >= 0.4) and (r.three_astd if pd.notna(r.three_astd) else 1) < 0.5 and not r.big: L.append('pull-up shooter')
    if r.big and r.three_sh >= 0.35: L.append('stretch big')
    if r.big and r.rim_sh >= 0.6 and (r.rim_astd if pd.notna(r.rim_astd) else 0) >= 0.5: L.append('rim runner')
    if r.post_sh >= 0.2 and r.usg >= 16: L.append('post scorer')
    elif r.big and r.rim_sh >= 0.5 and (r.rim_astd if pd.notna(r.rim_astd) else 1) < 0.5 and r.usg >= 18: L.append('interior scorer')
    if r.pullup_sh + r.floater_sh >= 0.25 and 'pull-up shooter' not in L and not r.big: L.append('off-dribble jumpers')
    if r.or_pct >= 10: L.append('glass')
    if r.putback40 >= 2: L.append('putbacks')
    if r.blk40 >= 2.5: L.append('rim protector')
    if r.stl40 >= 3.5: L.append('pickpocket')
    if r.trans40 >= 4: L.append('transition')
    if r.usg < 14 and not L: L.append('low-usage role player')
    if not L: L.append('balanced')
    return '; '.join(L)


def card(S, A, team):
    x = S[(S.team == team) | (S.team_cbbd == team)]
    if not len(x): print(f'no rows for {team}'); return
    print(f'\n=== {team} (D-I games, competitive possessions) ===')
    cols = ['player', 'pos', 'ht', 'gp', 'min_lev', 'usg', 'ast_pct', 'to_pct', 'efg', 'rim_sh', 'mid_sh', 'three_sh', 'rim_astd', 'three_astd', 'post_sh', 'pullup_sh',
            'or_pct', 'putback40', 'trans40', 'stl40', 'blk40', 'labels']
    y = x[cols].copy()
    for c in ('rim_sh', 'mid_sh', 'three_sh', 'rim_astd', 'three_astd', 'efg', 'post_sh', 'pullup_sh'): y[c] = (100 * y[c]).round(0)
    for c in ('usg', 'ast_pct', 'to_pct', 'or_pct', 'putback40', 'trans40', 'stl40', 'blk40', 'min_lev'): y[c] = y[c].round(1)
    with pd.option_context('display.width', 250, 'display.max_colwidth', 60):
        print(y.to_string(index=False))
    a = A[A.team == team].head(8)
    if len(a): print('top assist links:', '; '.join(f'{r.ast_name} -> {r.player} ({r.zone}) {r.n:.1f}' for r in a.itertuples()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--team', action='append'); ap.add_argument('--no-build', action='store_true')
    a = ap.parse_args()
    if a.no_build and os.path.exists(f'{OUT}/roles_current.csv'):
        S = pd.read_csv(f'{OUT}/roles_current.csv'); A = pd.read_csv(f'{OUT}/assist_pairs.csv')
    else:
        S, A = build()
    for t in a.team or []: card(S, A, t)
