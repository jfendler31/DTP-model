# Discord claim: "the market is fully detached from KenPom; KenPom adjusts faster for year-zero teams; the market disagrees" (Nov 13, 2026)

Tested with stored KenPom snapshots (weekly archives Nov 2024 and Nov 2025, daily files this season), closing lines, and KenPom continuity. Script and output: repo `data/research/kp_market/`. KenPom spread = AdjEM gap × tempo + his home court; it matches FanMatch to 0.4 on 287 games.

**1. "Detached like never before" — no, except on big favorites.** Mean |closing line − KenPom|, same snapshot timing each year:

| Window | 2024-25 | 2025-26 | 2026-27 |
|---|---|---|---|
| ~Nov 6–9, all games | 2.3 | 2.7 | 2.8 |
| ~Nov 10–12, all games | 2.2 | 2.8 | 2.8 |
| Lines under 15 | 1.8 / 1.8 | 2.1 / 2.0 | 1.8 / 2.0 |
| Lines 15+ | 3.2 / 2.7 | 3.6 / 3.7 | 4.1 / 4.0 |

Same as last year overall and under 15. At 15+ the gap is ~0.4 wider than last year and all one direction: the market has the favorite 3.8 points bigger than KenPom (3.1–3.4 last year).

**2. "KenPom adjusts faster for year-zero teams" — no.** KenPom's rating move per point of results-vs-preseason-expectation is the same in every continuity tercile, in all three seasons (2026-27: low 0.25, mid 0.28, high 0.27; interaction −0.02, se 0.02; teams with continuity ≤2%: −0.03, se 0.02). His speed depends on games played (≈0.22 per point after 2 games, 0.30 after 3, 0.38 after 4 — same this year as the last two), not on roster turnover.

**3. "The market disagrees with that approach" — the market tracks KenPom's moves about one-for-one, and more so for low-continuity teams.** Share of KenPom's move from preseason that shows up in the closing line: all games 0.95 / 0.92 / 1.18 (2024-25 / 2025-26 / this year); games with a low-continuity team 1.06 / 0.99 / 1.13; both teams mid/high continuity 0.82 / 0.81 / 1.24; a team at ≤2% continuity 1.26 / 1.10 / 1.47. If anything the market moves *more* than KenPom on year-zero teams.

**Who has been right when they differ by 3+ (November, vs the close):** KenPom's side 156-136 in 2024-25, 207-161 in 2025-26, **50-63 this season**. 86–99% of those are the underdog, so this is the big-favorite bias again (`BigDog_Recheck_2026-11-13.md`), not information about year-zero teams. For games with a ≤2%-continuity team: 15-17, 53-38, 13-18.

**Read:** the gap the poster is seeing is the market's November premium on big favorites, a little larger this year. It isn't KenPom treating new rosters differently, and it isn't the market ignoring early results on them. Our own handling stands (KenPom today ≈ 0 weight in reads; year-zero weighting from our own tests).
