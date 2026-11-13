# Should the noisy pillars be opponent-adjusted this early? (Nov 13, 2026)

**Question (Jon, from ULM):** ULM's net 3PT% pillar was +1.8 raw but +15.6 after opponent adjustment (z +1.85), the largest piece of its in-season rating. With 3-game samples, is opponent-adjusting 3PT (and FTA rate) adding noise?

**Answer: no. Production (opponent-adjusted, ridge 0.5 on every pillar) beat every alternative in all three seasons. No change. The haircut I took off ULM for this is withdrawn.**

**Method** (`data/research/pillar_adj/backtest_pillars.py`, `evaluate_pillars.py`, `results.txt`). Walk-forward Nov–Dec, 2023-24 (box factors), 2024-25 and 2025-26 (play-by-play factors, as production); 5,984 games. The harness is a copy of `ratings_core.rate()` with per-pillar options; its base variant is asserted equal to production on every date (max difference 0) and matches the independent Nov 12 backtest to 0.005. Variants change only the in-season pillar ratings.

| Variant | MAE (3 seasons) | vs base (se) | 2023-24 | 2024-25 | 2025-26 | ATS 3+ vs close | Teams 3–6 games: vs base (se) |
|---|---|---|---|---|---|---|---|
| **base (production)** | **9.260** | — | 9.110 | 9.268 | 9.389 | 720-608, 54.2% | — |
| 3PT raw (no opponent adj.) | 9.275 | +0.015 (0.004) | +0.009 | +0.007 | +0.028 | 722-616, 54.0% | +0.031 (0.009) |
| 3PT and FTA raw | 9.273 | +0.014 (0.006) | +0.007 | +0.011 | +0.022 | 712-613, 53.7% | +0.031 (0.013) |
| 3PT ridge 2 | 9.264 | +0.004 (0.001) | +0.002 | +0.001 | +0.009 | 721-606, 54.3% | +0.008 (0.003) |
| 3PT ridge 5 | 9.267 | +0.008 (0.002) | +0.004 | +0.003 | +0.016 | 719-610, 54.1% | +0.014 (0.006) |
| 3PT+FTA ridge 2 / 5 | 9.264 / 9.268 | +0.004 / +0.008 | | | | 54.1% / 53.7% | +0.007 / +0.014 |
| 3PT weight 0 | 9.279 | +0.019 (0.010) | +0.011 | +0.038 | +0.010 | 808-692, 53.9% | +0.030 (0.019) |
| Ridge 1 / 2 on all pillars | 9.264 / 9.279 | +0.005 / +0.019 | | | | 53.8% / 53.1% | +0.005 / +0.020 |
| No opponent adj. at all | 9.375 | +0.115 (0.026) | +0.100 | +0.089 | +0.155 | 901-822, 52.3% | +0.142 (0.051) |

- Every variant is worse on margin in every season; none improves ATS on 3+ edges beyond noise (best +0.1 pt of win rate).
- Direction test: where a variant moves the number, regress (result − base) on (variant − base). Raw 3PT: **−1.19 (se 0.49)**; ridge variants −1.2 to −4.2. Moving toward the un-adjusted number is the wrong direction — the opponent adjustment on threes carries information even at 3–6 games.
- The 3PT pillar earns its .10 weight: dropping it costs MAE in all three seasons.
- Scale: raw 3PT differs from production by 1+ point in only 31 games of ~4,400; across D-I today the SD of the difference is 0.2 and ULM (−0.7) is one of the two largest of 364 (with Georgia).

**For reads:** an extreme opponent-adjusted pillar on a 3-game team is not grounds for a haircut. The scoreboard blend (70/30) remains the tested check on a composite that looks too high.
