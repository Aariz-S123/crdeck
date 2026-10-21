# Model notes: choices the spec left open, and where the code departs from it

Each item says what changed, why, and how to undo it. Evidence comes from two sources. **Synthetic** data (`data/synthetic`, with planted card strengths and pair bonuses) shows whether a method can recover a known signal. **Real** data (window `2026-10-w3`: 58,179 usable ranked battles of 2,894 top Path of Legends players, collected 2026-10-18) shows how it does on the game.

## Results on real held-out battles (spec section 10)

Test window: held-out top-player battles from 2026-10-18 20:42 to 2026-10-19 01:36 UTC (8,727 battles). Train: 40,725 earlier battles. Validation: 8,727.

| Model | Metric | Result | Baseline(s) | Verdict |
| --- | --- | --- | --- | --- |
| Deck strength (`card_lr+pairs+skill`) | log loss / AUC | 0.69280 / 0.521 | 50%: 0.69315 / 0.500 · popularity: 0.69302 / 0.510 · rating only: 0.69302 / 0.508 | Better than every baseline on both metrics, but **not statistically clear**: the 90% bootstrap interval for each log-loss difference includes 0, and only 65–72% of resamples favor the model |
| Completion | recall@10 of 2 masked cards, 100 frequent test decks | 0.92 | most-popular fill: 0.25 | Beats the baseline. **Optimistic**: the co-occurrence weight rule was revised after test results were seen (item 2) |
| Archetype | accuracy on the 20 held-out decks | 0.95 | majority class (Beatdown): 0.40 | Beats the baseline. **Caveat**: train and held-out labels are the assistant's drafts (item 9) |
| Synergy | AUC of deck mean synergy (A − B) for held-out winners | 0.519 (`without_partner`, chosen on validation) | lift: 0.490 · popularity: 0.510 | Beats both, by a small margin. The `marginal` variant scored 0.522 on test, but validation chose `without_partner` (0.516 vs 0.509) |

What this says about the game, at this level: deck composition barely moves win odds among top Path of Legends players. Matchmaking pairs similar ratings, everyone plays strong meta decks at max level, and the rating gap itself predicts wins only slightly (AUC 0.51–0.53). The deck model's estimates for real decks sit around 49–52%. That is the honest scale of "deck strength" here.

## 1. Synergy: which "expected win rate"

- **Spec (7.1):** `expected_wr` combines the two cards' individual shrunk win rates in log-odds.
- **Problem:** with each card's *overall* rate (`marginal`), a pair that nearly always appears together has its effect counted twice. On synthetic data, the planted Hog Rider + Earthquake bonus scored −0.05, and deck synergy *anti*-predicted wins (AUC 0.47).
- **Change:** `without_partner` takes each card's rate over its games *without* the other card. `expected_from: auto` (the default) picks between the two on the **validation** window. Synthetic data: `without_partner` recovers 6 of 8 planted pairs and wins clearly. Real data: the two are close; validation chose `without_partner`.
- **Undo:** set `synergy.expected_from` to `marginal` or `without_partner`.
- **Still true:** cards in the same popular deck share credit, so synergy is not proof of a combo. Single-pair estimates are noisy (synthetic: 4–8 of 8 planted pairs positive depending on seed). Always read the interval and the game count.

## 2. Completion objective: an extra co-occurrence term

- **Spec (7.4):** score full decks by strength plus a small synergy term.
- **Problem:** maximizing strength alone stacks cards with high individual weights into decks nobody plays, and recall falls below popular fill.
- **Change:** `objective = meta_win_prob + synergy_weight · mean_pair_synergy + cooccurrence_weight · mean_log_lift`. The new term is the mean smoothed log-lift of all pairs ("do players actually pair these cards?").
- **Weight rule and its revision:**
  - The first rule was "smallest grid weight whose validation recall beats popular fill, keeping strength dominant". On real data it gave 0.01 (test recall 0.45 vs 0.25).
  - But strength barely beats a coin flip on real data, so at 0.01 search maximizes noise. It returned Hog + Graveyard decks with two win conditions, HYBRID / UNCERTAIN archetypes, and inflated 55–56% estimates.
  - The rule is now "smallest weight reaching 95% of the best validation recall", which gives 0.05 on real data (and on synthetic data).
  - **This revision was made after seeing the test numbers**, so the 0.92 test recall is not a clean held-out result. Confirm it on a new collection window.
- **Undo:** set `search.cooccurrence_weight`, or change `evaluate.choose_cooccurrence`.

## 3. Strength: skill control and regularization

- **Skill control** (`strength.skill_control: true`): the regression also gets the rating difference (`startingTrophies`, A − B, per 100 points). The spec (7.2) names skill as a confounder.
  - Card weights are estimated at equal rating. Deck utilities and deck scores exclude the rating term, so they describe an equally rated opponent.
  - The rating coefficient is left effectively unpenalized by scaling its column. With the penalty it shrank from 0.29 to 0.04 per 100 points.
  - `rating_only` is reported as an extra baseline so skill and deck contributions can be told apart. Without skill control, the deck model was worse than 50% on real test log loss.
- **Regularization:** `C` is picked from `strength.C_grid` on validation log loss. Real data picks small values (0.001), which matches a weak deck signal. With the fixed `C = 1`, synthetic search claimed 95.7% for a deck nobody played.

## 4. Deck score interval

- Approximate interval = model uncertainty (Laplace approximation, delta method, marginal over the rating term) plus opponent sampling (bootstrap over test-window opponent decks).
- It does **not** cover selection effects: the top search result is a maximum of noisy estimates. Explanations say so.
- `UNSEEN_DECK` marks a deck that never appears in collected battles; its score is extrapolated. `LOW_CARD_DATA` marks a card form without a learned weight.

## 5. Search diversity

- Each beam parent keeps at most `beam_width / beam_parents_min` children per step. Final results come from the whole last expansion and must differ by `min_diff_cards`.

## 6. Placement checks and slot rules

- `rules.check_deck(..., placement=...)` checks one exact placement, so a champion in a normal slot is rejected. Without a placement, a deck is legal if some valid placement exists.
- The slot rules were checked against 2,613 distinct real ranked decks, with slots read from deck positions:
  - two champions occur (26 decks), so `max_champions: 2`;
  - champions sit in the Wild slot (77);
  - base cards sit in empty special slots (91);
  - no deck exceeds 3 special cards;
  - every observed deck passes the validator.
- Notebook 02 reruns this audit. It is observed play, not an in-game check.

## 7. Counting units and windows

- Synergy and popularity count **deck appearances**: one side of one OK battle.
- The synergy table used by search and explanations is fit on train + validation. Test battles fit nothing.
- A battle log holds the last 30 battles, so one collection run mostly covers the last day or two. Validation and test are each about 4–5 hours wide. That is a real time split, but a narrow one. Daily collection (`collect --window auto`) widens it.

## 8. Synthetic data

- `python -m crdeck synthetic` writes to `data/synthetic/` only, labels every output SYNTHETIC, and never stands in for real data. The default source is `real`; missing real data raises an error. It now uses the observed API format (form bitmask, `evolutionLevel` 1/2, slot positions).

## 9. Website

- The spec deferred a web UI (section 3); one was built on request after the core phases were done.
- `web/engine.js` re-implements legality, scoring, search, warnings, archetype prediction and explanations in JavaScript, so the spec's "only rules.py decides legality" now has a second implementation.
- The guard is `scripts/check_web_engine.mjs`: it compares the port with Python on 3,000 random decks (legality, reasons, slot assignment, partial checks) and on full searches, swaps and explanations. It must pass after every export.

## 10. Archetype labels

- Spec 7.3 asks for 60–100 hand-labeled real decks, with 20 held out and labeled before any fitting.
- `data/labels/archetype_labels.csv` holds 108 real decks from the k-means worklist (round-robin across 12 clusters): 20 held out, 88 train. **The assistant labeled them** from the card lists, before any archetype model was fit, and every row's notes say so.
- The same labeler made the held-out labels, so the 0.95 accuracy measures agreement with that labeler, not ground truth.
- Relabel with `python -m crdeck label --interactive` (or edit the CSV). The model retrains automatically.

## 11. Modes: Ranked and Trophy Road

- A battle's mode comes from its `type`, `gameMode.name` and `deckSelection` (config `battles.modes`), determined from the collected logs (inventory in docs/api-notes.md). **Ranked** = `pathOfLegend` + `Ranked1v1_NewArena(2)`. **Trophy Road** = `trail`/`PvP` + `Ladder`. Both require `deckSelection = collection` (the player's own deck). **All** = both together.
- Events (`eventDeck`), draft modes, friendlies, clan war, 2v2 and tournaments are never modeled: their decks are not the player's choice or the rules differ.
- Each mode is split into **groups**: Ranked by league (the battle's `leagueNumber`, named Master I to Ultimate Champion), Trophy Road by arena (the battle's `arena.name`). The group always comes from the battle. The league names, the arena order and the arenas' trophy floors were supplied by the project owner (config `battles.modes`); they only order the site's picker and aim the arena collector.
- Each mode and each group gets its own models when it clears the existing thresholds (100 usable battles, 30 per split part). Every configured league and arena is listed on the site with its real battle count; ones under the threshold say "too few" and are never filled in.
- **Two samples of players.** `leaderboard`: top Path of Legends players from the leaderboards. `arena_sample` (`collect --arenas`): players found through clan search and clan member lists, placed in the arena their own member record names (or, when missing, the arena whose trophy floor they reach), plus ladder opponents for arenas still short. A battle collected in both samples counts as `leaderboard`.
- **Assumption:** the arena sample is the members of clans that clan search returns, and their opponents. It is not a random sample of each arena: players without a clan, or in clans the search does not return, are missing. To test it, compare card usage in an arena between clan-found players and opponent-found players; a large gap means the clan route is skewed.
- **Assumption:** until `collect --arenas` has run, the Trophy Road battles come from top Path of Legends players only (9,567 to 15,000 trophies), so lower arenas have no data.
- **What a player in an arena can use.** Single-arena Trophy Road models only offer card forms a player there could have. Source: the Clash Royale Wiki (config/card_unlocks.yaml, written by scripts/fetch_wiki_unlocks.py on 2026-10-21): each card's unlock arena (the Arena field on its page, or its arena's card list on the Arenas page for 3 cards whose pages lack the field; the two never disagreed), and the arenas that unlock the Evolution slot (3), the Hero slot (5) and the Wild slot (10). Players are never moved back an arena, so everything unlocked there or earlier counts. Below Arena 3 a deck has no special slots, below 5 only the Evolution slot, below 10 no Wild slot.
- **Checked against the battles:** the slot rules held with no exceptions, but 4-21% of decks in Arenas 3-13 held a card the wiki places later (cards also come from chests and Evolution shards). So, as the project owner chose, a card also counts as available in an arena when at least 3 decks in that arena's battles used it ("seen early"). **Assumption:** a card used early by fewer than 3 decks is treated as not available; a few real owners of rare early cards are blocked. Test: raise the arena sample and compare how many cards cross the threshold.
- **Assumption: mixed models mix populations unevenly over time.** The split is by time, and the two samples were collected at different times, so a model that spans several groups can be tuned and tested on different mixes of players. Measured after the first arena collection (2026-10-20), share of leaderboard-sample battles in train / valid / test: Ranked (every league) 95% / 98% / 90%; Trophy Road (every arena) 2% / 19% / 6%; All modes 41% / 82% / 48%; Ultimate Champion 100% in all three. "All modes" is the most affected: its settings were picked on mostly top players and tested on a more mixed set. A single league or arena covers one kind of player and is the cleaner choice. To test the effect, compare a mixed model's test log loss per sample with the single-group models'.

## 12. Meta history and forecast

- The meta history counts battles from the **leaderboard sample only**. Arena-sample players join in later periods, so counting them would look like a meta shift.

- **Meta:** the share of ranked deck appearances that include a card form (and the share of each predicted archetype).
- **Periods:** the battles between two collection runs. The first covers the 24 hours before the first run. Periods never overlap.
- **Assumption:** per-day counts inside one collection are not used. A log holds a player's last 30 battles, so older days over-represent less active players and would look like meta change.
- **Assumption:** periods of different length or hours mix in different regions (time zones), so part of a change between two periods can be who was playing at those hours. Equal daily collections reduce this. To test: compare periods collected at the same hour on different days.
- **Forecast model (an assumption):** `logit(share next) = logit(share now) + alpha + beta x (win rate - 0.5)`, fitted on observed period changes. Monte Carlo runs draw shares and win rates from the bootstrap, alpha and beta from a bootstrap of the fit, and binomial noise for the next period's size.
- **Gate:** the forecast is shown only if, in a backtest on held-out periods, it misses by no more than "no change" (it is also compared with "linear trend"). It needs at least 3 periods (one change to fit, one to test); 5 are recommended. With 2 periods so far it is not shown.

## 13. Model log

- The website's Model log shows `data/processed/run_log.json`: build writes data counts, collection windows and fetch times; evaluate writes splits, every strength candidate (model x C) with validation scores, the synergy variant choice, the co-occurrence grid and rule, and test metrics with 90% bootstrap intervals; export writes the code commit, configs, label versions and time. The caveats section shows this file verbatim.
- The export re-runs the evaluation for any mode whose saved evaluation does not match the current data fingerprint and test window, so the report card is never stale.

## 14. Next season

- The **Next season** page (web/seasons.html, src/crdeck/seasons.py) shows only measured data until a season prediction has been earned. It has three parts: the most-played exact decks of leaderboard players in Ranked per collection period (usage share and win rate with 90% Wilson intervals; "rising" or "falling" only when the change between the last two periods has a 90% range clear of zero), the card lists saved on each collection and what changed between them, and a locked prediction section.
- **Why the prediction is locked.** Battle logs only hold each player's last 30 battles, so past seasons cannot be collected after the fact. On 2026-10-20 the leaderboard ranked data covered one season with at least 10,000 battles (2026-10: 124,253; 2026-09: 120). A season-to-season model needs at least 3 covered seasons: two to measure how the meta moves from one season to the next and a third, held back, to test it against assuming no change. It will be shown only if it wins that test.
- **New cards, Evolutions and Heroes.** A release has no battles before it comes out, so no model trained on this data can say how it will be played. The collector saves GET /cards on every run; a new card or form is listed the day it appears, gets no weight until it has `strength.min_feature_games` games, and is only added by the search after `search.min_card_games`.
- **Assumption:** a battle's season is the calendar month of its battle time. GET /locations/global/seasons lists ids (like 2026-09) without dates (observed 2026-10-20), so a few days around a boundary may land in the neighbouring season. Test: find the Path of Legends rating reset in the battles and compare it with the month boundary.

## 15. Card map (embeddings) and swap math

- **Vectors.** Every card form with at least `strength.min_feature_games` training games gets a vector: the positive part of its PMI with every other form (PMI = log-lift: how much more often two forms share a TRAINING-window deck than chance), factorized with an SVD (vector = U_d · sqrt(S_d), scaled to length 1). This is the matrix form of word2vec; it is deterministic. Forms the kept dimensions do not describe (all-zero vector) are left off the map. Vectors are rounded to 7 decimals so Python and the website compute identical distances (checked on every export).
- **Size.** d is chosen from 8, 16, 32 on the VALIDATION window by completion recall (hide 2 cards of the 100 most frequent decks; are they among the 10 cards closest to the center of the other 6?). On Ranked (2026-10-21): 8: 63.5%, 16: 76.0%, 32: 83.0%, so 32. Tested once on the TEST window: 79.5% (90% range 74.0% to 84.5%) against 23.5% for the 10 most popular cards.
- **Distances** are cosine distances in all d dimensions, 1 − (v · c) / ‖c‖, to the center c (mean vector) of the other 7 cards. The 3D picture is a PCA projection for display only (on Ranked it keeps about 19% of the spread), so closeness in the picture is a rough guide and never used for a decision.
- **Card-map swaps.** For each card that may be replaced (not a picked card), the 8 legal, unlocked candidates closest to the center of the other 7 are scored with the strength model; those that raise the estimated win rate are suggested, best gain first, each with its distance and win-rate change. **Assumption:** closeness in this space measures "played in the same kinds of decks", not "wins together"; the win-rate check guards the second. Test: compare the win-rate change of card-map swaps with the regular swap list on held-out decks.
- **Style colours** in the picture: the style most often predicted for the 3,000 most-played training decks holding each card; only the three most common styles get a colour (a scatter cannot keep more categories apart for colour-blind readers), the rest are grey.
- **Swap math** on the Why this deck page writes every regular swap out as Δscore = Δwin + 0.5 × Δsynergy + 0.05 × Δplayed-together, with the deck's numbers before and after.

