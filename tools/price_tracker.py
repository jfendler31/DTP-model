"""Price tracker absences for overrides (Nov 13, 2026; engine moved to jobs/price_core.py Nov 14 so the 4:15 sync prices the same way).
Runbook §3 'Price an injury / status'. Each (team, player, weight) cascades on top of the team's active overrides and earlier rows.
Usage: python3 tools/price_tracker.py [<torvik_fragility_csv>] "Team|Player|weight" ... [YYYY-MM-DD]   (weight: out 1, doubtful .75, gtd .5)
Prints spread value and delta_pts; writes nothing. The Torvik file defaults to data/torvik/torvik_fragility_players_all_2026-10-23.csv."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'jobs'))
from price_core import Pricer, TV_DEFAULT

args = sys.argv[1:]
tv = args.pop(0) if args and args[0].endswith('.csv') else TV_DEFAULT
D = args.pop() if args and args[-1][:2] == '20' and '|' not in args[-1] else '2026-11-13'
P = Pricer(D, tv)
print(f'EM test: em_bpr = {P.b1:.2f} x team_value + {P.b0:.2f}; SD(prior_pts) {P.SD:.2f}')
for arg in args:
    team, player, w = arg.split('|'); r = P.price(team, player, float(w))
    if not r['ok']: print(f'{team} — {player}: {r["text"]}'); continue
    print(f'{team} — {player} (w {w}): {r["text"]} | SPREAD {r["spread"]:.2f}, delta_pts {-r["delta"]:.2f}'
          + (f' | on top of {r["cascade"]}' if r['cascade'] else ''))
