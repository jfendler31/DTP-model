# Handoff: take garbage time out of the in-season ratings

*Written Nov 8, 2026 from the daily-ops chat. Jon's decision (Nov 8): "I want garbage time out." This chat builds it in this repo. Start by reading the project docs `claude/Daily_Ops_Runbook.md`, `claude/Current_Files.md` and `claude/Tempo_Tracker_2026-27.md`. (This file lives in the repo because the project was out of room on Nov 8.)*

## 1. The problem
`jobs/ratings.py` builds every team's in-season rating from **CBBD box-score team totals**, i.e. every possession of every game, garbage time included. Bench-vs-bench possessions in blowouts mostly measure players who won't decide that team's competitive games, and how hard the leading team kept pressing.

**How much garbage time there is (2026-27 D-I games through Nov 7, from `data/tempo/possessions_2026-11.csv.gz`, `lev` column):**
- 300 D-I games; mean competitive share (mean `lev`) 0.82; 40 games under 0.60.
- Central Connecticut at Syracuse (Nov 5): 46% of possessions low-leverage (`lev` < 0.5). Arkansas vs Arkansas-Pine Bluff: 37%. Virginia vs Drexel / Northeastern: 22% / 25%. Temple vs CCSU: 17%. Dartmouth at Marist: 0% (99% competitive).

**Worked example (CCSU).** CCSU's whole in-season move (−2.0) came from two games: four-factor surprise −2.05 at Syracuse, −0.06 at Temple (games-1–2 method, averaged, λ = 0.2). Garbage time began at 17:21 of the 2nd half with Syracuse +27. Competitive 74 possessions: Syracuse +27 (+0.73 per possession pair). Garbage 62 possessions: +26 (+0.84). Whole game +53 (+0.78). So a competitive-only version moves CCSU only ~0.1–0.2 here, because the game was already lopsided. The effect varies game to game; don't generalize from this one.

**Why the systematic bias is smaller than it first looks.** In games 1–2 a team moves by its surprise against what the priors expected, and that expectation regression was fit on composites that include garbage time too, so the average dilution is inside it. The main gain is less noise and fewer game-specific distortions, not removing a steady tilt. The SRS path (from game 3) has no such offset.

## 2. How the ratings work now (decisions in force; runbook §4)
- Pillars and weights: net 2PT% .32, OREB rate .26, TO rate .24, 3PT% .10, FTA rate .08 (`W` in `jobs/ratings.py`). Each pillar clipped at ±3 game SD.
- From game 3: per-pillar ridge SRS (opponent/home-adjusted, `RIDGE` 0.5), composite z, blended with `z_prior` at λ = N/(N+K); K = 8 through Nov 30, ramp to 12 by Jan 15. Final margin is not an input.
- Games 1–2 (option 2b): composite = a·home + b·(prior gap) fit across all games (Nov 8 fit on 300 games: a 0.077, b 0.365); a team's surprise = residual / b, averaged over its games; rating = z_prior + λ × surprise.
- Games vs non-D-I opponents don't count. A team with no D-I games stays at its prior.
- Card size curve (`jobs/card.py`): 0.20 pt per point of model spread beyond 10, **from Nov 8 only in non-conference games with the model favorite at home** (`size_curve` flag; Jon: it was fit on buy-game mismatches, 169 of 171 Nov 2–6 10+ games were home games). It was fit on week-one results that include garbage time, so it may be partly compensating.

## 3. Data available
- **CBBD play-by-play** is already pulled by `jobs/rotation.py` and `jobs/tempo.py`: date feed first, then `/plays/game/{id}` for the games the date feed skips (it returns about half a day's games). Reuse that fetch; don't write a third one.
- **Leverage weights already exist** in the tempo/rotation jobs (`lev`, plus flags `half_end`, `short_clock`, `foul_seq`, `ot`). Use the same definition so "garbage time" means one thing everywhere. Exact definition and the raw-vs-competitive gate test: project doc `claude/Tempo_Tracker_2026-27.md`.
- **What's missing:** the possession file has outcomes (`end_type`: made_fg / miss / to / ft …) and start types, but **no 2PT/3PT split, no FTA count, no offensive/defensive rebound credit**. A competitive-only composite needs a fuller parse of the plays: per team per game, over competitive possessions (or leverage-weighted): 2PM/2PA, 3PM/3PA, FTA, FGA, ORB, DRB, TO, possessions, both sides.
- Box Out (repo jfendler31/Boxout) has its own nightly play-by-play pull; it doesn't feed DTP-model and shouldn't be wired in.

## 4. Open decisions (put these to Jon; don't decide for him)
1. **Hard cutoff vs leverage weighting.** Drop possessions below a threshold, or weight every possession by `lev`. Weighting avoids a cliff at the threshold; a cutoff is easier to explain.
2. **Threshold** if a cutoff: reuse the tempo/rotation "competitive" definition unless there's a reason not to.
3. **Free throws in foul sequences, end-of-half heaves, OT:** follow the tempo job's treatment unless Jon wants otherwise.
4. **Rollout:** shadow first (both versions side by side) vs switch straight away. Recommended: shadow a few days, then switch on Jon's call.

## 5. Build plan (suggested)
1. Extend `jobs/tempo.py` (or add `jobs/pbp_factors.py`) to write `data/pbp/game_factors.csv`: one row per team-game, raw and competitive four-factor totals, keyed by CBBD gameId.
2. In `jobs/ratings.py`, add a switch (e.g. `FACTOR_SRC = 'box' | 'competitive'`): use competitive totals where available, fall back to box totals for games missing play-by-play, log how many games used each.
3. Refit what depends on the composite: the games-1–2 regression (refits each run) for sure; check whether K and the size curve still fit, ideally in the two-season backtest.
4. **Shadow run:** write a second ratings file (e.g. `data/ratings_competitive.csv`) and a card column/edge for it without changing `data/ratings_current.csv`, so Jon can see how much ratings and edges move. Production ratings change only when Jon approves the switch.
5. **Proper validation** needs the 2024-25 and 2025-26 CBBD game stores (not built yet; also needed for option 3, the K re-sweep and the size-curve sweep). Built from play-by-play, one pull covers all four.

## 6. Constraints
- Don't change `data/ratings_current.csv`, the card's model numbers, or the 4:15 AM pipeline until Jon approves the switch. `card.yml` runs on `triggers/card.txt` pushes; pushing code doesn't trigger it.
- Jobs run on GitHub Actions via one-line pushes to `triggers/` (check for another chat's pending line first). Trigger files are passed whole as arguments: one line only, no comment lines (a `# refresh` line broke four player-box runs on Nov 7).
- Commit messages end with the session's Co-Authored-By / Claude-Session lines.
- Jon's conventions: lead with the answer; KenPom spelling; spreads on the half, model and edges to the tenth; no BET/PASS labels.

## 7. Other Nov 8 changes the runbook doesn't have yet
- **Betting Sheet tab** ships header-row ARRAYFORMULAs in Jon's Nov 7 form (`={"Header"; IF(F2:F500 …)}`), bounded to row 500, with cached results written by `jobs/xlsx_cache.py` (Google's import shows cached array results instead of recalculating). New column L `Size curve`.
- **J sign:** the sheet computes edge = market − (model + J), so J is home-spread points: a home-team absence is **positive**, an away-team absence negative. The runbook line saying the reverse is wrong; Jon's own Nov 7 entries used the correct sign.
- **Size curve** restricted as in §2.
- Override added: Penn St. Roberts Blums out (broken finger, a few weeks), −0.60.

## 8. Status (Nov 8, afternoon) — shadow built and running
- **Built:** `jobs/pbp_factors.py` (called inside `jobs/tempo.py`, same fetch and possessions) writes `data/pbp/game_factors.csv`: per team-game 2PT/3PT made/att, FTM/FTA, player and team rebounds, turnovers, possessions, in three versions — `raw`, `cw` (lev-weighted, tempo's structural drops: ot / half_end / short_clock / foul_seq) and `cc` (lev ≥ 0.5 cutoff, same drops). Each event takes the weight of its possession (rebounds: the missing team's possession; and-1 FTs: the shooter's possession just ended); events no possession covers take the leverage at the play.
- `jobs/ratings_shadow.py` runs at the end of every **Tempo tracker** run (`continue-on-error`): production math on `box`, `pbp_raw`, `cw`, `cc` → `data/ratings_shadow/` (`ratings_<v>_<date>.csv`, `compare_current.csv`, `card_<date>.csv`, `check_<date>.csv`). Self-check: `box` reproduces `data/ratings_current.csv` exactly (max |z diff| 0.0000 on Nov 8). Production untouched.
- **Parser vs box (Nov 1–7, 600 D-I team-games):** 2PA/3PA/FGM/FTA/ORB/DRB/TO all within 0.02 per team-game on average; box rebounds exclude team rebounds (`REB_TEAM = False`). Only possessions differ (parsed vs CBBD's formula, mean −0.6). All 300 games passed the gate. `pbp_raw` vs box: mean |Δ| 0.05 pts, max 0.5 — parse noise is negligible.
- **Nov 8 effect:** `cw` vs production mean |Δ| 0.48 pts per team (90th pct 1.1, max 3.8, Le Moyne); `cc` 0.52; `cw` vs `cc` 0.14. Today's card: 15 of 29 games move 0.5+ (max 2.1, Campbell at WMU: edge 2.9 → 0.8).
- **Out-of-sample (tiny):** ratings as of Nov 5/6/7 predicting those days' final margins, 150 games: MAE box 8.58, cw 8.54, cc 8.52 (cw − box −0.04, se 0.06). In the 19 games where cw moved the prediction 1+ pt, it moved toward the result 14 times. Not evidence yet.
- **Design issue found — stopping effect.** A blowout's competitive window is, by construction, the run that created the lead, and the game stops counting once the margin crosses the line. Each game is one equal-weight observation of rates, so a 25-competitive-possession blowout (Le Moyne–Creighton, Nov 5) counts as much as a 70-possession close game and reads more extreme than the full game. Signs: early-fit slope 0.365 → 0.379 and R² 0.57 → 0.54 under `cw`. Candidate fix (Jon's call): weight each game in the SRS / early fit by its competitive possessions, or shrink each game's competitive rates toward its raw rates by competitive share.

## 9. Switched (Nov 8, evening) — Jon's decisions
- **Leverage-weighted** (not cutoff). **Overtime kept** (tempo drops it; the ratings don't — OT possessions take their leverage). Heaves (`half_end`), possessions starting under 35 s in a period (`short_clock`) and late intentional-foul possessions (`foul_seq`) stay out, as in tempo.
- **Each game weighted by its competitive possessions** (mean weight 1) in the SRS and in the games-1–2 fit and averaging — the fix for the stopping effect (§8). Nov 5–7 out-of-sample, 150 games: MAE box 8.58, equal-weight cw 8.54, game-weighted 8.50 (game-weighted − cw −0.046, se 0.019). Early-fit slope back to 0.351 (box 0.365, equal-weight cw 0.379).
- **Production:** `jobs/ratings.py` `FACTOR_SRC = 'cw'`, `GAME_WT = True`; shared math in `jobs/ratings_core.py` (box mode reproduces the old production ratings exactly). Box totals stay the fallback for a game with no play-by-play or whose raw play-by-play fails the box check (`GATE`); the run prints the counts. `data/ratings_current.csv` rebuilt for Nov 8 on the new inputs (the Nov 8 card itself was built on the old ones).
- **Card job order:** `ratings.py --games-only` (box pull) → `tempo.py` (play-by-play for yesterday, 15-min timeout; writes `data/pbp/game_factors.csv`) → `ratings.py --offline` → card. Late games CBBD hasn't posted play-by-play for by 4:15 use box totals that morning and switch to play-by-play the next day.
- **Shadow** (`jobs/ratings_shadow.py`, end of every Tempo tracker run): production (`cw_gw`, self-checked against `ratings_current.csv`) vs equal-weight `cw` vs old `box`; `data/ratings_shadow/card_<date>.csv` shows each card game's model under all three.
- **Size curve:** still fits. On Nov 5–7 home favorites with 10+ model spreads (86 games), the favorite beat the model by +3.5 under box and +3.3 under the new ratings — the curve isn't double-counting garbage time. K unchanged; both wait on the two-season sweep.
- Nov 8 effect vs the old ratings: mean |Δ| 0.47 pts per team, 90th pct 1.1, max 3.9 (Le Moyne −3.9, LSU New Orleans −2.9, New Haven −2.6, Tulsa +2.2).

## 10. Backtest, 2025-26 November–December (Nov 8)
`jobs/backtest_ratings.py --season 2026` → `data/backtest/results_2026.csv`. Walk-forward daily with `ratings_core.py` (production math), prior = KenPom preseason AdjEM z (`data/kenpom/preseason_2026.csv`, pulled with `kenpom.py --preseason`), production K schedule shifted to the season, current KenPom HCA. 2,182 D-I games, 2,167 with play-by-play pillars; 2,075 graded (Nov 4–Dec 31).
- **Final margin MAE:** prior 9.85, box 9.42, cw 9.40, **cw_gw 9.39**. cw_gw − box −0.033 (se 0.023); cw_gw − cw −0.008 (se 0.009). Nov 9.67 → 9.63, Dec 9.13 → 9.11.
- **vs CBBD close, home/away (1,773 games; market MAE 9.15):** model-side ATS box 50.0%, cw 50.5%, cw_gw 50.9%; edge ≥3: box 53.7% (497), cw_gw 54.9% (505).
- Read: same direction as the live week, about a third the size, not significant on one season. 2024-25 pull waits on the CBBD Tier 3 upgrade (Jon); then the same run for `--season 2025`.

### 2024-25 November–December (Nov 9) and the two-season read
Feed differences fixed first (2024-25 logs team rebounds as player-less "Team Offensive/Defensive Rebound" plays and FTs without "n of m"; the box counts *include* team rebounds that season, so `backtest_ratings.py` uses `reb_team=True` for S ≤ 2025). After the fix play-by-play rebounds match box to +0.4 / +0.3 per team-game; 2,026 of 2,078 games use play-by-play pillars. Raw plays kept as the `backtest-raw` workflow artifact (re-parse with `--from-raw --raw-run <id>`, no CBBD calls).
- **Final margin MAE:** prior 9.49, box 9.27, cw 9.26, cw_gw 9.27 (cw_gw − box −0.004, se 0.023; cw_gw − cw +0.011, se 0.010). Nov 9.49 → 9.54 (worse), Dec 9.01 → 8.94 (better).
- **vs close, home/away (1,655):** model-side ATS box 49.9%, cw 51.1%, cw_gw 51.7%; edge ≥3 51.8% → 52.8%.
- **Two-season read:** garbage time out is neutral-to-slightly-better on margin both seasons (−0.033, −0.004) and improves model-side ATS both seasons (+0.9, +1.8 pts); December better both years, November mixed. **Game weighting does not replicate on margin** (−0.008, +0.011 vs equal weight; both within noise) though its ATS is a hair better both years. Neither season reverses the switch.
