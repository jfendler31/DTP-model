# Big-dog edges, rechecked (Nov 13, 2026, 1 AM)

**Jon:** the big underdogs dominating the top of the sheet feel like a systemic bias that can wreck a bankroll. Re-check it.

**Answer: he's right. The model's 20+ dog edges carry no information beyond "the market overprices big home favorites in November." My Nov 12 night read (haircut retired, take big-dog edges at face value) is reversed.**

Two seasons (2024-25, 2025-26 Nov–Dec), home favorites of 20+ at the close, production model (`data/research/prior_pull/preds_*.csv`):

| Cut | Result |
|---|---|
| Every 20+ home dog, no model | 379-334, **52.9%**; dog margin vs close +0.06 |
| Model on dog, edge 3+ | 156-127, 54.9% |
| Model on dog, edge <3 or on favorite | 51.6% |
| Difference | +3.3 pts, se 3.8, **z = 0.87** |
| Dog cover margin regressed on model edge toward dog (n=716) | slope **0.02 (se 0.08)** — prior-only edge 0.01, in-season part 0.05 (se 0.16) |
| Dog cover by model bucket | model on fav 3+: 50% · \|e\|<1: 53% · dog 1–3: 51% · dog 3–5: 55% · dog 5+: 55% — flat |
| CLV on model-on-dog edges, every line/edge bucket at 20+ | **−0.5 to −1.2** (market moves toward the favorite all day) |
| Vs the **open** (2025-26): model-on-dog 3+ | 80-68 (54%); all 20+ dogs 187-195 (49%) |
| This season Nov 2–11, 20+: all dogs / model-on-dog 3+ | 72-85 / 15-11, CLV −1.57 |

**Reading.** The dog's 53% at the close is a market effect (bettors push big favorites past the open; the close overshoots). Our model number sits 4–7 points short of the market on these games in every bucket; the size curve (0.2/pt beyond 10) closes part of it. The remaining "edge" is the prior pull (mechanical) plus the raw shortfall, neither of which ranks games — slope 0.02. A 7-point edge on a 32-point favorite is a 53% coin flip with negative CLV, same as a 3-point one.

**15–20 band:** model-on-dog 3+ went 30-21 raw (58.8%), 20-15 size-adjusted, and week-one 15–20 favorites didn't show the bias (51%). Small n, but this is where the in-season information may be doing work.

**Operating rules from here (runbook §5):**
1. 20+ dog edges are one bet type at ~53%: flat small sizing or pass, never ranked by edge size. ROI at −110 ≈ +1%.
2. Haircut stays; the week-of-season table describes the market bias, not model skill.
3. Reads and the morning summary present 20+ dogs as a group, below the 15–20 and sub-15 edges.
4. **Queued backtest:** refit the size curve by line band so the dog cover margin is ~0 at 20–25, 25–30, 30+, both seasons; check whether a steeper curve changes what sorts to the top without hurting the sub-20 edges.
