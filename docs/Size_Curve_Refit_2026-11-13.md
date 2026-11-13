# Size-curve refit — walk-forward, two seasons (Nov 13, 2026, ~2 AM)

**Question (Jon):** should the card's size curve (0.20 pt per point beyond 10, buy games only) be steeper so 20+ dogs stop sorting to the top?

**Answer: no. The curve adds no accuracy at any slope, and a steeper one costs ATS. Keep 0.20. The fix for the sheet is presentation (20+ games as their own tier), not a steeper curve.**

Script `data/research/size_curve/fit_curve.py`, results `results.txt`. Production walk-forward predictions (`prior_pull/preds_<S>.csv`), home non-conference games with a close, curve applied exactly as `card.py` does. Fit on one season, grade on the other.

**Fitted slopes:** least squares of (market − raw model) on (model − 10)+: **0.006 in 2024-25, 0.148 in 2025-26.** Fit to results instead of the market: 0.03 / 0.12. Both below production's 0.20.

**Held-out grading, model side vs the close, 3+ edges:**

| Curve | 2025-26 all 3+ | 15–20 3+ | 20+ 3+ (on dog) | 2024-25 all 3+ | 15–20 3+ | 20+ 3+ (on dog) |
|---|---|---|---|---|---|---|
| none | 279-228, **55.0%** | 26-28 | 111-91 (107-89) | 229-202, **53.1%** | 28-20 | 65-53 (50-38) |
| 0.20 (production) | 247-220, 52.9% | 34-44 | 66-62 (34-27) | 263-250, 51.3% | 35-34 | 82-71 (20-11) |
| 0.30 | 256-246, 51.0% | 40-44 | 68-81 (15-13) | 292-291, 50.1% | 38-38 | 105-99 (12-6) |
| 0.40 | 293-293, 50.0% | 45-51 | 92-116 (8-7) | 322-321, 50.1% | 47-46 | 123-117 (8-4) |

What the curve does: it removes 20+ dog edges (which cover 53–55% for market reasons) and creates favorite-side edges at 15–25 that cover 44–48%. Steeper = more of the second. Sub-15 edges are untouched by any slope.

**20+ market lines: the raw model's sign is uninformative.** Dog covers 53.6% when the model is within 2 of the market, 53.3% when the model is on the dog by 2–5, 54.0% on the dog by 5+; 45.5% (n=66) when the model is on the favorite by 2+. Mean favorite margin vs the close: −0.2 to −0.8 in every bucket.

**Where the raw model sits vs the market at 20+, by week (both seasons):** 0.7 short in week 1, 1.4 in week 2, 2.9 in week 3, ~2.7 from then on — the gap opens as teams reach 3 games (prior pull). After the 0.20 curve: −2.7 (over) in week 1, −2.0 in week 2, **≈0 from week 3 on.** So production's curve is about right from week 3 in the backtest. **Correction to the Nov 13 recheck doc:** I wrote there that the raw model was "4–7 short in every bucket"; that came from a table with a join bug (duplicate indices across seasons). The right figures are 0.7–2.0 short at 20–30 and 2.0–4.8 at 30+, both seasons.

**This season (grade log, 4 AM number, 20+ home favorites):** size-adjusted model within ~0.5 of the market on average every day Nov 2–11. Tonight's early sheet is 3.2 short on 22 games because nine of them are 30+ lines, where the shortfall is largest and the curve closes least.

**Recommendation.**
1. Curve stays at 0.20. Not a prediction tool — a suppression tool that is about right from week 3.
2. Card change for Jon to approve: add a `tier` column (`<15`, `15–20`, `20+`) and sort the Betting Sheet by tier then edge, so 20+ games sit in their own block below the rest. No number changes.
3. Big-dog rule (runbook §5) stands: 20+ dog edges are one bet type at ~53%, flat small or pass.
