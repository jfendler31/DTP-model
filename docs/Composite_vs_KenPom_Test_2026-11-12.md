# Does the composite add anything beyond KenPom's in-season rating? (Nov 12, 2026)

**Question (Jon):** is the in-season composite capturing something KenPom and/or the market isn't?

**Answer: yes, clearly.** Starting from the same preseason number (KenPom's), our in-season update beat KenPom's in-season update on margin, and beat it badly against the closing line, in both backtest seasons. The part of our move that KenPom's own move doesn't share is worth about 0.65 points per point against KenPom's number. Against the close it's worth about 0.34 per point once KenPom's number is known. KenPom's in-season moves in November–December overshoot: the market fades them, and teams KenPom moved up did about 0.28 points worse than KenPom's number per point of move.

## Method
Repo `data/research/comp_vs_sb/vs_kenpom.py` → `vs_kenpom.txt`. KenPom archive snapshots at roughly weekly dates (`data/kenpom/history/archive_<date>.csv`): 2024-11-07 … 2024-12-30 and 2025-11-06 … 2025-12-29, 9 per season. For each game in the two-season walk-forward (`preds_<S>.csv`), KenPom's rating = the latest snapshot on or before the game date (0–6 days stale, mean 3.1). KenPom spread built like ours: 9.5 × (z_home − z_away) + KenPom HCA; a scale-fitted version (0.772 × AdjEM diff) gives the same picture. Both methods start from KenPom's preseason rating, so this isolates the in-season update. Snapshots check out: correlation with KenPom preseason 0.994 on Nov 6, 0.923 on Dec 29.

## Results (4,012 games on margin; 3,364 home/away games against the close)

| Rating | Margin MAE | ATS vs close, all | ATS vs close, 3+ edges |
|---|---|---|---|
| KenPom preseason (the prior) | 9.674 | 51.5% | 51.7% |
| **KenPom in-season snapshot** | 9.436 | **48.5%** | **48.9% (824)** |
| **Our composite** | **9.318** | 51.4% | **54.4% (927)** |
| Scoreboard (luck-adjusted points) | 9.404 | 50.5% | 52.3% |
| 75% composite / 25% KenPom | 9.315 | 50.7% | 54.0% |

- Both seasons the same: composite 53.9% / 54.7% on 3+ edges; KenPom 49.9% / 48.1%.
- Not staleness: same-day and next-day snapshots only (1,027 games) → KenPom 50.2% on 3+, composite 55.9%. KenPom's distance from the close doesn't grow with snapshot age (2.0–2.2 pts at every age).
- Once both teams have 5+ games (1,933 games), KenPom's in-season number is 46.8% on 3+ edges; the composite 55.1%.
- Mixing KenPom's in-season number into the composite doesn't help: 75/25 ties on margin and is slightly worse ATS.

**Regressions.** Cover margin ~ KenPom edge + composite edge: KenPom −0.31 (se 0.10), composite +0.34 (se 0.09). Margin ~ KenPom + composite: 0.29 KenPom, 0.73 composite (se 0.08 each). Margin − prior ~ KenPom move + composite move + scoreboard move: 0.30 / 0.44 / 0.31.

**Team level.** Our composite move correlates 0.80 with KenPom's own move (snapshot − preseason) and is smaller (SD 2.3 vs 2.8 pts). Composite move ≈ 0.66 × KenPom move + residual (SD 1.4). The residual — what our method sees that KenPom's doesn't — predicts a team's result against KenPom's number at **+0.65 per point (se 0.11)**, monotonic:

| Composite residual vs KenPom's move | n | Result vs KenPom's number |
|---|---|---|
| below −1.5 | 868 | −1.67 |
| −1.5 to −0.5 | 1,487 | −0.71 |
| −0.5 to +0.5 | 2,101 | +0.28 |
| +0.5 to +1.5 | 1,347 | +0.74 |
| above +1.5 | 925 | +1.00 |

KenPom's own move, with the residual in: **−0.28 per point (se 0.05)** — KenPom's November–December moves overshoot by about a quarter.

## Why (the likely mechanism)
KenPom's in-season rating is built from adjusted efficiency margin — points, including three-point and free-throw results — with a preseason weight that decays quickly. The composite grades the possession battle (2PT%, rebounding, turnovers), gives threes a .10 weight, and drops garbage time. In the first two months, three-point and FT luck is most of the noise in points, so a points-based update moves too far on noise; the market, which also sees points, has learned to fade KenPom's early moves. What's left at the close is what the composite is built on.

## What it means
- **No production change.** The card already uses the composite alone; KenPom enters only through the preseason prior (35%), which is fine.
- **Reads:** "KenPom today" in the system check is a weak-to-negative signal in Nov–Dec. Support from KenPom today should not count as independent confirmation; KenPom today disagreeing with us is not a reason to shrink. The runbook's "KenPom credit at half-weight" is too generous — treat KenPom's in-season move as ~0 relative to the composite.
- **This season's 24-39 on 3+ edges (through Nov 11)** sits against two seasons at 54%; the backtest says keep betting the method.
- Not tested: whether this persists past December (KenPom's preseason weight is gone by then and the composite's K rises); the stores end Dec 31.
