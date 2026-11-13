# Who keeps their better players in during decided minutes — 2026-27 through Nov 12

**Question (Jon, Nov 13):** on a percentage basis, which coaches have kept their better players on the floor once the game is decided?

**Measure.** D-I games the team won with 4+ low-leverage game-minutes (low = raw minutes − leverage-weighted minutes, `data/rotation`). "Better players" = the team's top five by competitive minutes across all its D-I games. `top5_share` = their low-leverage minutes ÷ (5 × low-leverage game-minutes). 100% = the top five never came out.

**Result.** 146 teams have a qualifying win; 83 have 15+ decided game-minutes. D-I mean 48%, median 48%.

- Keep them in (60%+): Boise St. (Rice) 75%, Boston College (Murray) 71%, Georgetown (Cooley) 70%, Dayton (Grant) 69%, Richmond (Mooney) 67%, Providence (Hodgson) 66%, Wright St. (Sargent) 64%, Tulsa (Konkol) 63%, N.C. State (Gainey) 63%, Utah St. (Jacobson) 62%, Florida St. (Loucks) 60%, Georgia Tech (Cross) 60%, Auburn (Pearl) 60%.
- Pull them (under 35%): North Carolina 21%, Iowa (McCollum) 26%, VCU (Martelli) 28%, South Carolina (Paris) 30%, Oregon 30%, Saint Mary's 31%, Xavier (Pitino) 34%.
- Also low among top teams: Marquette 37%, Alabama 38%, Saint Louis 38%, Houston 40%, Nebraska 40%, Duke 42%, Illinois 42%.

**Use.** The coach tendency tested at about +0.5 late margin (1.6 SE) in `garbage_starters.py` — a lean, not a rule. One to four games per team; the share falls as the margin grows, so compare teams with similar average margins. Full table: `data/research/garbage_starters/coach_table_2026-11-13.csv`; rerun `python3 data/research/garbage_starters/coach_table.py`.
