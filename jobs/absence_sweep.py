"""
Absence sweep: injury / eligibility / suspension adjustments for the frozen prior.

Two steps.
  1) candidates  — propose who might be out, from the EvanMiya player export (awaiting_decision flags),
                   Jon's eligibility rulings, and the BurnerBall injury notes. Rotation players only (team top 8 by BPR).
       python3 absence_sweep.py candidates --players ratings_2026-27.csv --elig eligibility_overrides.csv \
              --burnerball burnerball_YYYY-MM-DD.csv --out absences_candidates.csv
     Jon edits the result into absences.csv: set status (out / doubtful / questionable / in), expires,
     and, where he knows it, priced_kp / priced_em / priced_tv (Y = that site already removed the player).

  2) sweep — value each absence, detect which sites already priced it (team-rating drop between the two
             site files), and write a draft overrides file for the part the sites have NOT priced.
       python3 absence_sweep.py sweep --players ratings_2026-27.csv --absences absences.csv \
              --old Three_Preseason_Sites_Oct11.xlsx --new Three_Preseason_Sites_Oct31.xlsx \
              --prior prior_2026-27.csv --out overrides_draft.csv

Method (Oct 23, 2026; tested on Auburn).
  Player value: EvanMiya BPR (per-100). Team value = sum over the top eight by BPR of BPR x minutes/40, with the
  skills-board minutes curve 32/30/28/26/24/19/15/12. Absence value = team value without the player(s) minus with;
  replacements are whoever moves into the top eight. Status weights: out 1.0, doubtful 0.75, questionable 0.5, in 0.
  Each site's share: priced fraction f_s = clip(observed team drop old->new / expected drop, 0, 1), in that site's own
  SD units (Torvik on the Barthag logit). A Y/N in priced_kp/em/tv overrides the auto-detection (use it for absences
  a site already priced before the old file, e.g. KP's long-term injury removals in his Oct 11 release).
  Residual (z) = absence z-value x sum_s w_s (1 - f_s), weights 45 EM / 35 KP / 20 Torvik (the prior blend).
  Override in prior_pts units = residual z x SD(prior_pts); spread effect = residual z x 9.5 (locked scale).
  Output is one row per player (team, player, status, delta_pts, expires, reason); the ratings job sums the non-expired
  rows per team and applies sum(delta_pts) / SD(prior_pts) to z_prior. Delete a row when the player returns.
  Note: sizing through z gives ~25% more than the per-possession shortcut (BPR x poss/100) used in the Oct 23 Auburn
  chat test, because EvanMiya's team scale is compressed relative to KenPom's (SD 10.3 vs 12.6). The z route is the one
  consistent with how EM enters the prior (as a z-score).
"""
import argparse, re, sys, unicodedata
import numpy as np, pandas as pd, openpyxl

W = {'em': 0.45, 'kp': 0.35, 'tv': 0.20}
CURVE = [32, 30, 28, 26, 24, 19, 15, 12]
STATUS_W = {'out': 1.0, 'doubtful': 0.75, 'questionable': 0.5, 'in': 0.0, 'pending': 0.0}  # pending = Jon has not ruled -> no override
INJ_NOTES = {'INJ', 'INJ-OFS', 'ACL', 'INJ-RS', 'INJ-DEC', 'JUCO) (INJ'}
INEL_NOTES = {'INEL'}

MAN = {'Miami (Fla.)': 'Miami FL', 'Miami (OH)': 'Miami OH', 'NC State': 'N.C. State', 'Ole Miss': 'Mississippi',
       'McNeese State': 'McNeese', 'McNeese St.': 'McNeese', 'Saint Bonaventure': 'St. Bonaventure',
       'St. Thomas (MN)': 'St. Thomas', 'College of Charleston': 'Charleston', 'Florida International': 'FIU',
       'Louisiana-Lafayette': 'Louisiana', 'California Baptist': 'Cal Baptist', 'Arkansas-Little Rock': 'Little Rock',
       'Fort Wayne': 'Purdue Fort Wayne', 'Long Island': 'LIU', 'Texas A&M-Corpus Christi': 'Texas A&M Corpus Chris',
       'Southeast Missouri State': 'Southeast Missouri', 'Southeast Missouri St.': 'Southeast Missouri',
       'SIU Edwardsville': 'SIUE', 'Southern Mississippi': 'Southern Miss', 'Cal State Northridge': 'CSUN',
       'Cal St. Northridge': 'CSUN', 'Detroit': 'Detroit Mercy', 'Missouri-Kansas City': 'Kansas City', 'UMKC': 'Kansas City',
       'Texas-Rio Grande Valley': 'UT Rio Grande Valley', 'Nicholls State': 'Nicholls', 'Nicholls St.': 'Nicholls',
       'New Orleans': 'LSU New Orleans', 'Omaha': 'Nebraska Omaha', 'Loyola Maryland': 'Loyola MD',
       'Prairie View': 'Prairie View A&M', 'Grambling': 'Grambling St.', 'South Carolina Upstate': 'USC Upstate',
       'UConn': 'Connecticut', 'Seattle U': 'Seattle', 'Cal State Bakersfield': 'Cal St. Bakersfield',
       'Cal State Fullerton': 'Cal St. Fullerton', "Saint Mary's (CA)": "Saint Mary's", 'Loyola (MD)': 'Loyola MD',
       'Loyola Chicago': 'Loyola Chicago', 'Pitt': 'Pittsburgh', 'UNC': 'North Carolina', 'Southern California': 'USC'}


def norm_player(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[.'’]", '', s)
    s = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def make_fixer(kp_names):
    K = set(kp_names)
    def fix(n):
        n = str(n).strip()
        if n in K: return n
        if n in MAN and MAN[n] in K: return MAN[n]
        for c in (n.replace(' State', ' St.'), n.replace('-', ' '), n.replace('-', ' ').replace(' State', ' St.')):
            if c in K: return c
        return None
    return fix


def load_sites(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    kp = pd.DataFrame([r[:3] for r in wb['KenPom'].iter_rows(min_row=2, values_only=True) if r[0]], columns=['team', 'conf', 'kp'])
    fix = make_fixer(kp.team)
    tv = pd.DataFrame([r[:4] for r in wb['Torvik'].iter_rows(min_row=2, values_only=True) if r[1] and r[1] != 'Team'],
                      columns=['rk', 'team', 'conf', 'barthag'])
    em = pd.DataFrame([r[:3] for r in wb['EvanMiya'].iter_rows(min_row=2, values_only=True) if r[1]], columns=['rk', 'team', 'bpr'])
    tv['team'] = tv.team.map(fix); em['team'] = em.team.map(fix)
    d = kp.merge(tv[['team', 'barthag']], on='team', how='left').merge(em[['team', 'bpr']], on='team', how='left')
    for c in ('kp', 'barthag', 'bpr'): d[c] = pd.to_numeric(d[c].astype(str).str.lstrip('=+'), errors='coerce')
    d['tv'] = np.log(d.barthag / (1 - d.barthag))
    return d.set_index('team')[['kp', 'bpr', 'tv']].rename(columns={'bpr': 'em'}), fix


def team_value(bprs):
    b = sorted(bprs, reverse=True)[:8]
    return sum(x * m / 40 for x, m in zip(b, CURVE))


def candidates(a):
    pl = pd.read_csv(a.players)
    kp_names = pd.read_csv(a.prior).team if a.prior else None
    fix = make_fixer(kp_names) if kp_names is not None else (lambda x: x)
    pl['kp_team'] = pl.team.map(fix)
    pl['key'] = pl.name.map(norm_player)
    pl['team_rank'] = pl.groupby('team').bpr.rank(ascending=False, method='first').astype(int)
    rot = pl[pl.team_rank <= 8]
    elig = pd.read_csv(a.elig) if a.elig else pd.DataFrame(columns=['name', 'team', 'status', 'note'])
    elig['key'] = elig.name.map(norm_player)
    cleared = set(elig[elig.status.str.lower() == 'eligible'].key)
    rows = []
    for r in rot[rot.awaiting_decision == True].itertuples():
        if r.key in cleared: continue
        rows.append(dict(team=r.kp_team, name=r.name, em_bpr=round(r.bpr, 2), team_rank=r.team_rank, source='eligibility pending',
                         reason='awaiting eligibility decision', status='pending', priced_kp='', priced_em='', priced_tv=''))
    # EvanMiya flags added in the Oct 28 export: inelig_now (ineligible at present) and season_out (out for the year)
    for col, why, exp in (('inelig_now', 'EvanMiya: ineligible now', ''), ('season_out', 'EvanMiya: out for season', 'season')):
        if col not in rot.columns: continue
        for r in rot[rot[col] == True].itertuples():
            if r.key in cleared: continue
            rows.append(dict(team=r.kp_team, name=r.name, em_bpr=round(r.bpr, 2), team_rank=r.team_rank, source=f'EvanMiya {col}',
                             reason=why, status='out', priced_kp='', priced_em='', priced_tv='', expires=exp))
    for r in elig[elig.status.str.lower().isin(['ineligible', 'suspended', 'out'])].itertuples():
        m = rot[rot.key == r.key]
        if len(m):
            rows.append(dict(team=m.kp_team.iloc[0], name=m.name.iloc[0], em_bpr=round(m.bpr.iloc[0], 2), team_rank=int(m.team_rank.iloc[0]),
                             source='Jon ruling', reason=f'{r.status}: {r.note}', status='out', priced_kp='', priced_em='', priced_tv=''))
    if a.burnerball:
        bb = pd.read_csv(a.burnerball)
        bb = bb[bb.note.isin(INJ_NOTES | INEL_NOTES)]
        bb['key'] = bb.player.map(norm_player); bb['kp_team'] = bb.team.map(fix)
        for r in bb.itertuples():
            m = rot[(rot.key == r.key) & (rot.kp_team == r.kp_team)]
            if not len(m): continue
            season = r.note in ('INJ-OFS', 'ACL')
            rows.append(dict(team=r.kp_team, name=m.name.iloc[0], em_bpr=round(m.bpr.iloc[0], 2), team_rank=int(m.team_rank.iloc[0]),
                             source=f'BurnerBall {r.snapshot}', reason=f'chart note {r.note}', status='out',
                             priced_kp='Y' if season else '', priced_em='', priced_tv=''))
    c = pd.DataFrame(rows).drop_duplicates(['team', 'name'])
    if 'expires' not in c.columns: c['expires'] = ''
    c['expires'] = c.expires.fillna(''); c['jon_note'] = ''
    c = c.sort_values(['em_bpr'], ascending=False)
    c.to_csv(a.out, index=False, encoding='utf-8-sig')
    print(f'{len(c)} candidates -> {a.out}  (rotation players only; edit status/priced_*/expires, save as absences.csv)')


def sweep(a):
    old, fix = load_sites(a.old); new, _ = load_sites(a.new)
    SD = {s: old[s].std() for s in ('kp', 'em', 'tv')}
    prior = pd.read_csv(a.prior); SDP = prior.prior_pts.std()
    pl = pd.read_csv(a.players); pl['kp_team'] = pl.team.map(fix); pl['key'] = pl.name.map(norm_player)
    ab = pd.read_csv(a.absences).fillna('')
    ab['key'] = ab.name.map(norm_player); ab['w'] = ab.status.str.lower().map(STATUS_W).fillna(0)
    out, detail = [], []
    for team, g in ab[ab.w > 0].groupby('team'):
        roster = pl[pl.kp_team == team]
        if roster.empty: print('no EvanMiya roster for', team, file=sys.stderr); continue
        full = team_value(roster.bpr)
        # expected value of the absences, probability-weighted one player at a time on top of the certain-outs
        missing = []
        for r in g.itertuples():
            if not (roster.key == r.key).any(): print('player not in EvanMiya export:', r.name, team, file=sys.stderr)
        out_keys = set(g[g.w >= 1].key)
        base = team_value(roster[~roster.key.isin(out_keys)].bpr)
        val = base - full
        for r in g[g.w < 1].itertuples():
            val += r.w * (team_value(roster[~roster.key.isin(out_keys | {r.key})].bpr) - base)
        z_exp = val / SD['em']               # expected drop in z (EvanMiya team-BPR units as the common currency)
        # per-player marginal values, rescaled so they sum to the joint value (keeps the replacement-cascade interaction)
        marg = {r.key: r.w * (team_value(roster[roster.key != r.key].bpr) - full) for r in g.itertuples()}
        tot = sum(marg.values()) or 1.0
        mz = {k: v / tot * z_exp for k, v in marg.items()}           # per-player expected z drop
        # per-site priced fraction, per player: Y -> 1, N -> 0, blank -> auto from the team's observed move
        # (observed move net of the Y-flagged players, divided by the expected drop of the blank-flagged players)
        unpriced = {k: 0.0 for k in mz}; notes = []
        for s_ in ('em', 'kp', 'tv'):
            flag = {r.key: str(getattr(r, f'priced_{s_}')).strip().upper() for r in g.itertuples()}
            obs = (new.loc[team, s_] - old.loc[team, s_]) / SD[s_] if team in new.index else 0.0
            e_y = sum(mz[k] for k in mz if flag[k] == 'Y'); e_auto = sum(mz[k] for k in mz if flag[k] not in ('Y', 'N'))
            f_auto = float(np.clip((obs - e_y) / e_auto, 0, 1)) if e_auto < 0 else 0.0
            for k in mz:
                f = 1.0 if flag[k] == 'Y' else 0.0 if flag[k] == 'N' else f_auto
                unpriced[k] += W[s_] * (1 - f)
            notes.append(f'{s_.upper()} moved {obs:+.2f} z vs expected {z_exp:+.2f}; auto-priced {f_auto:.0%}'
                         + (f', manual Y for {sum(1 for k in mz if flag[k]=="Y")}' if e_y else ''))
        resid = {k: mz[k] * unpriced[k] for k in mz}
        resid_z = sum(resid.values()); delta = resid_z * SDP
        share = resid_z / z_exp if z_exp else 0.0
        for r in g.itertuples():
            out.append(dict(team=team, player=r.name, status=r.status, delta_pts=round(resid[r.key] * SDP, 2),
                            expires=r.expires or 'until cleared', reason=f'{r.name} {r.status}; unpriced share {unpriced[r.key]:.0%}'))
        who = '; '.join(f'{r.name} ({r.status})' for r in g.itertuples())
        detail.append(dict(team=team, players=who, absence_value_per100=round(val, 2), expected_z=round(z_exp, 3),
                           unpriced_share=round(share, 2), override_pts=round(delta, 2), spread_pts=round(resid_z * 9.5, 1),
                           site_check=' | '.join(notes)))
    pd.DataFrame(out).to_csv(a.out, index=False, encoding='utf-8-sig')
    det = pd.DataFrame(detail).sort_values('override_pts')
    det.to_csv(a.out.replace('.csv', '_detail.csv'), index=False, encoding='utf-8-sig')
    pd.set_option('display.width', 250, 'display.max_colwidth', 120)
    print(det.to_string(index=False))
    print(f'\n{len(detail)} teams / {len(out)} player rows -> {a.out} (draft; Jon approves before the Nov 2 freeze)')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest='cmd', required=True)
    c = sp.add_parser('candidates'); c.add_argument('--players', required=True); c.add_argument('--elig'); c.add_argument('--burnerball')
    c.add_argument('--prior'); c.add_argument('--out', default='absences_candidates.csv')
    s = sp.add_parser('sweep'); s.add_argument('--players', required=True); s.add_argument('--absences', required=True)
    s.add_argument('--old', required=True); s.add_argument('--new', required=True); s.add_argument('--prior', required=True)
    s.add_argument('--out', default='overrides_draft.csv')
    a = p.parse_args(); (candidates if a.cmd == 'candidates' else sweep)(a)
