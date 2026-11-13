# Falling knives — do early fallers keep falling? (Nov 13, 2026)

**Jon:** teams that have fallen hard early (Troy, Bradley) seem to keep falling; for a year-zero outfit we don't know where the bottom is.

**Answer: they keep falling against the market, not against our number.** Two seasons (2024-25, 2025-26), November, teams with 3–8 D-I games, 2,572 team-games (`data/research/falling_knife/falling_knife.py`, `results.txt`).

- **Vs the close:** next-game ATS margin rises 0.22 pt per point of the team's move to date (se 0.11). Teams down 3+ vs their prior went **104-137 (43%)** vs the close, −2.0/game. The market under-reacts to early moves.
- **Vs our model:** slope **0.00 (se 0.11)**; vs the prior, slope 1.00 — the move to date is fully real and our K = 8 sizes it right on average. On fallers (move ≤ −2) our number is already **0.8 more bearish than the market**.
- **Extreme fallers vs our model:** move ≤ −3: −1.2/game (n 241, ~1.7 SE); but the −3 to −2 bucket is +1.3. Suggestive, not established.
- **Low continuity (bottom third):** vs-model slope +0.16 (se 0.17) vs −0.09 for the rest; interaction +0.25 (se 0.22). Same direction as the Nov 9 year-zero finding, ~1 SE.
- **Fallers as 20+ dogs:** n = 21 (13-8). Too few to say anything.

**Use in reads:** a faller is usually a bet *against* the team, and our model already leans that way. When our model is on a faller's side anyway (Troy +22.5, Nov 13: move −3.3, in-season-only rank 333rd, continuity 7.5% / 284th), take ~1 to 1.5 off the edge for a move of −3 or worse in a low-continuity team. A flag, not a rule; recheck with this season's games in December.

**Risers, by continuity (added Nov 13, ULM question).** Teams up 3+ vs prior ran −0.64 vs our model overall (n 204, se 0.88), but the shortfall sits in mid/high-continuity teams (−1.00, n 117); low-continuity risers ran about even (−0.16, n 87; up 2+: +0.56, n 177). **Don't apply a riser haircut to low-continuity / new-coach teams** — for them the year-zero weighting (runbook §5) points the other way. All of these are ~1 SE.
