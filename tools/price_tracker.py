"""Price tracker absences for overrides (Nov 13, 2026). Runbook §3 'Price an injury / status', automated for a list.
For each (team, player, weight): EvanMiya team_value() with vs without (cascade on top of the team's active overrides and
earlier rows in the list), priced share (EM team-rating test on the Oct 20 file; Torvik = in projected top 10 with minutes;
KenPom unknown -> unpriced), in-season overlap J = value x (1 - lam x share of D-I games missed), lam = N/(N+8).
Usage: python3 tools/price_tracker.py <torvik_fragility_csv> "Team|Player|weight" ...   (weight: out 1, doubtful .75, gtd .5)
Prints spread value and delta_pts; writes nothing."""
import sys, glob, numpy as np, pandas as pd
sys.path.insert(0, 'jobs')
from absence_sweep import team_value, make_fixer
from team_names import pn
SD = pd.read_csv('data/prior_2026-27.csv').prior_pts.std()
P = pd.read_csv('data/prior_2026-27.csv').set_index('team')
fix = make_fixer(P.index)
MAN = {'Miami (Fla.)': 'Miami FL', 'Florida International': 'FIU'}
E = pd.read_csv('data/evanmiya/ratings_2026-27.csv'); E['kp'] = E.team.map(lambda t: MAN.get(t) or fix(t)); E['pk'] = E.name.map(pn)
O20 = pd.read_csv('data/evanmiya/player_ratings_2026-10-20.csv'); O20['kp'] = O20.team.map(lambda t: MAN.get(t) or fix(t)); O20['pk'] = O20.name.map(pn)
TV = pd.read_csv(sys.argv[1]); TV['pk'] = TV.player.map(pn)
B = pd.concat([pd.read_csv(f, low_memory=False) for f in glob.glob('data/players/players_2026-11-*.csv')]).drop_duplicates(['gameId', 'athleteId'])
B['pk'] = B.name.map(pn)
R = pd.read_csv('data/ratings_current.csv').set_index('team')
OV = pd.read_csv('data/overrides.csv', dtype=str).fillna('')
D = sys.argv[-1] if sys.argv[-1].startswith('20') else None
act = OV[(OV.expires.isin(['', 'until cleared', 'season'])) | (OV.expires >= (D or '2026-11-13'))]
act = act[~act.player.str.startswith('(venue)')]
# EM team-rating test fit (Oct 20 player file vs EM team bpr in the prior)
tv0 = O20.groupby('kp').bpr.apply(lambda s: team_value(list(s)))
j = pd.concat([tv0, P.bpr], axis=1, keys=['tv', 'em']).dropna(); b1, b0 = np.polyfit(j.tv, j.em, 1)
outs = {}
for t, g in act.groupby('team'): outs[t] = set(g.player.map(pn))
print(f'EM test: em_bpr = {b1:.2f} x team_value + {b0:.2f}; SD(prior_pts) {SD:.2f}')
for arg in [a for a in sys.argv[2:] if '|' in a]:
    team, player, w = arg.split('|'); w = float(w); k = pn(player)
    roster = E[E.kp == team]
    if k not in set(roster.pk): print(f'{team} — {player}: NOT IN EVANMIYA FILE (EM removed him or never rated); check Torvik'); continue
    prev = outs.get(team, set())
    keep = roster[~roster.pk.isin(prev)]
    v = team_value(list(keep.bpr)) - team_value(list(keep[keep.pk != k].bpr))
    bpr = float(roster[roster.pk == k].bpr.iloc[0]); rank = int((roster.bpr > bpr).sum()) + 1
    # priced share
    r0 = O20[O20.kp == team]
    if k in set(r0.pk):
        with_, wo = b1 * team_value(list(r0.bpr)) + b0, b1 * team_value(list(r0[r0.pk != k].bpr)) + b0
        em_counts = abs(P.bpr[team] - with_) <= abs(P.bpr[team] - wo); em_txt = f'EM {"counts" if em_counts else "removed"} (actual {P.bpr[team]:.1f}, with {with_:.1f}, without {wo:.1f})'
    else: em_counts, em_txt = False, 'EM: not in Oct 20 file -> removed'
    tvr = TV[(TV.team == team) & (TV.pk == k)]
    tv_counts = len(tvr) > 0 and float(tvr.min_pct.iloc[0]) > 0
    share = 0.45 * em_counts + 0.35 + 0.20 * tv_counts
    # overlap
    tb = B[B.team == team] if (B.team == team).any() else B[B.team.map(lambda x: fix(x) or x) == team]
    gids = tb.gameId.unique(); N = int(R.n_games[team]); lam = N / (N + 8)
    played = tb[(tb.pk == k) & (tb.minutes > 0)].gameId.nunique()
    di = tb[tb.opponentConference.notna()].gameId.nunique()
    miss = max(N - played, 0) / N if N else 0
    adj = share * (1 - lam * miss) * w
    sp = v / 10.35 * 9.5 * adj; dp = v / 10.35 * SD * adj
    print(f'{team} — {player} (w {w}): BPR {bpr:.2f} (#{rank}), value {v:.2f} = {v / 10.35 * 9.5:.2f} spread full | {em_txt}; '
          f'Torvik {"counts" if tv_counts else "no"} -> unpriced {share:.2f} | played {played} of {N} D-I games, lam {lam:.2f} | '
          f'SPREAD {sp:.2f}, delta_pts {-dp:.2f}' + (f' | on top of {sorted(prev)}' if prev else ''))
    outs.setdefault(team, set()).add(k)
