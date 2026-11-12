# Composite vs scoreboard — which in-season reading should move a rating? (Nov 12, 2026)

**Question (Jon, from Oklahoma St. at Texas A&M):** when the four-factor composite and the luck-adjusted scoreboard disagree about a team, how much should each count? In reads that day I had been crediting 25–50% of a composite move when the scoreboard didn't back it.

**Answer:** about **30% scoreboard / 70% composite**, consistently across methods and both seasons. My hand shrinks in reads were too harsh. The card itself (composite only) is not measurably worse than the blend against the close; no production change is warranted on this evidence.

## Method
Repo `data/research/comp_vs_sb/` (`comp_vs_sb.py`, `evaluate.py`, `results.txt`, `preds_<S>.csv`, `live_sb.py`).
- Walk-forward over the stored Nov–Dec backtest seasons (2024-25: 2,002 games; 2025-26: 2,075), same machinery as `jobs/backtest_ratings.py` (prior = KenPom preseason z; production K schedule).
- Four in-season readings, each run through `ratings_core.rate()` unchanged (ridge SRS, z-scored, λ = N/(N+K), early method for games 1–2):
  - `comp_T` production composite (play-by-play competitive pillars, game-weighted, opponent-current); `comp_F` same with opponent-prior.
  - `sb_box` scoreboard: luck-adjusted net points per 100 possessions from the full box (3P makes → D-I 3P% × attempts; FTs → FT talent × attempts; FT talent = prior-season team FT% shrunk 60% to the D-I mean).
  - `sb_cw` the same luck-adjusted net from competitive possessions.
- `comp_F` reproduces the stored `results_<S>.csv` cw_gw predictions exactly (max difference 0.00).
- Graded on margin (all D-I games), ATS vs the CBBD close (home/away games only, 3,420), CLV vs the open (2025-26 only; 2024-25 has no opens).

## Results (pooled, both seasons)
| Version | Margin MAE | ATS vs close, 3+ edges | CLV, 3+ edges (2025-26) |
|---|---|---|---|
| Prior only | 9.676 | 802-752 (51.6%) | −0.00 |
| **Composite (production)** | **9.329** | **508-430 (54.2%)** | +0.25 |
| Scoreboard (box) | 9.413 | 574-528 (52.1%) | +0.39 |
| 75/25 composite/scoreboard | 9.330 | 496-437 (53.2%) | +0.32 |
| 50/50 | 9.347 | 509-452 (53.0%) | +0.35 |

Composite alone beat the close on 3+ edges in both seasons (53.1%, 55.0%). The scoreboard alone is worse on margin and ATS, but the **market moves toward it** (higher CLV): the market prices points, so scoreboard-type edges close up; the composite's possession-battle information is what is left over at the close.

**The weight, three ways:**
- Margin regression: margin = prior + 0.74 × composite move + 0.31 × scoreboard move (se 0.105 each) → scoreboard ≈ 30% of the in-season weight.
- Team level, vs the close: a team's result vs the composite's number moves −0.29 pts per point that its composite move exceeds its scoreboard move (se 0.11; 2024-25 −0.26, 2025-26 −0.32). −1 would mean "scoreboard right", 0 "composite right" → **≈30%**.
- By gap size: when the two disagree by 2–3 points, results land ~0.85 pts toward the scoreboard from the composite; at 3+, ~0.76 pts — about 20–30% of the way.

**Asymmetry (suggestive, not robust):** teams whose composite runs ≥1.5 above their scoreboard (avg gap 2.2) did 0.93 pts worse than the composite's number vs the close (n = 833); the mirror case did +0.37 (n = 861). Piecewise slopes: −0.69 (se 0.26) when composite > scoreboard, −0.23 (se 0.26) when below. Use ~30% generally; up to ~40% when the composite is well above the scoreboard.

**Opponent-current early method (queued backtest, answered here):** neutral — MAE 9.329 vs 9.330, ATS 3+ 54.2% vs 54.1%, CLV identical. Keep it.

## How to use it
- **In reads:** in-season credit = composite move − 0.3 × (composite move − scoreboard move), using the **opponent-adjusted scoreboard move from `live_sb.py`** — not the `scoreboard_<date>.csv` "vs close" numbers, which measure against the market rather than our prior. `python3 data/research/comp_vs_sb/live_sb.py --date D --w 0.3 --card cards/card_D.csv` prints both moves per team and each card game re-priced at the blend.
- **Card:** no change on this evidence (blend ties on margin, slightly worse on ATS vs close, better on CLV; all within noise).
- Nov 12 card at the 70/30 blend: Oklahoma St. edge 3.9 → 2.9 (at −7.5); Kansas City 4.2 → 3.4; Towson 3.9 → 3.5; LMU 5.9 → 5.3; Mercer 7.0 → 6.6; NMSU 4.1 → 3.4; Richmond 1.3 → 0.0.
