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
- Each mode, and each Trophy Road arena, gets its own models when it clears the existing thresholds (100 usable battles, 30 per split part). Smaller arenas are listed as "not enough data".
- **Assumption:** the Trophy Road battles come from the same top Path of Legends players (9,567 to 15,000 trophies), so they describe the top of Trophy Road, not lower arenas. Testing lower arenas needs players sampled by arena (clan search + clan members), at least ~5,000 ladder battles per arena.

## 12. Meta history and forecast

- **Meta:** the share of ranked deck appearances that include a card form (and the share of each predicted archetype).
- **Periods:** the battles between two collection runs. The first covers the 24 hours before the first run. Periods never overlap.
- **Assumption:** per-day counts inside one collection are not used. A log holds a player's last 30 battles, so older days over-represent less active players and would look like meta change.
- **Assumption:** periods of different length or hours mix in different regions (time zones), so part of a change between two periods can be who was playing at those hours. Equal daily collections reduce this. To test: compare periods collected at the same hour on different days.
- **Forecast model (an assumption):** `logit(share next) = logit(share now) + alpha + beta x (win rate - 0.5)`, fitted on observed period changes. Monte Carlo runs draw shares and win rates from the bootstrap, alpha and beta from a bootstrap of the fit, and binomial noise for the next period's size.
- **Gate:** the forecast is shown only if, in a backtest on held-out periods, it misses by no more than "no change" (it is also compared with "linear trend"). It needs at least 3 periods (one change to fit, one to test); 5 are recommended. With 2 periods so far it is not shown.

## 13. Model log

- The website's Model log shows `data/processed/run_log.json`: build writes data counts, collection windows and fetch times; evaluate writes splits, every strength candidate (model x C) with validation scores, the synergy variant choice, the co-occurrence grid and rule, and test metrics with 90% bootstrap intervals; export writes the code commit, configs, label versions and time. The caveats section shows this file verbatim.
- The export re-runs the evaluation for any mode whose saved evaluation does not match the current data fingerprint and test window, so the report card is never stale.
