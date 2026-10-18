# Model notes: choices the spec left open, and where the code departs from it

Each item says what changed, why, and how to undo it. Evidence so far comes only from **synthetic** data (`data/synthetic`, battles generated with planted card strengths and pair bonuses). Re-check every item on real data.

## 1. Synergy: "expected win rate" uses games without the partner

- **Spec (7.1):** `expected_wr` combines the two cards' individual shrunk win rates in log-odds.
- **Problem:** with the cards' *overall* rates (`expected_from: marginal`), a pair that nearly always appears together gets its effect counted twice: once inside each card's own rate, then again when the rates are combined. On synthetic data, the planted Hog Rider + Earthquake bonus (+0.12 log-odds) scored −0.05, and deck-level synergy *anti*-predicted held-out wins (AUC 0.468).
- **Change:** default `expected_from: without_partner`, so each card's rate is taken over its games *without* the other card. That is the literal meaning of "better together than separately." On the same data, 6 of 8 planted pairs now score positive with intervals above zero. Across the two synthetic draws so far, synergy predicts held-out winners better than lift or popularity (AUC 0.51–0.56, vs 0.48–0.49 for lift and 0.50 for popularity); the marginal version stays below chance (0.47).
- **Undo:** set `synergy.expected_from: marginal` in `config/model.yaml`. Notebook 05 and `evaluate.synergy_eval` always report both variants.
- **Still true:** pairs that live in the same popular deck share credit; plenty of unplanted pairs score high. Synergy here is not proof of a combo.
- **Noise:** individual pair estimates are noisy when each deck is played by few players, because player skill (a spec-named confounder) is mixed into deck results. On synthetic data with 400 players and 16k battles, 4 to 8 of the 8 planted pairs came out positive, depending on the seed. What held in every run is that planted pairs average above the median pair. Read single pair scores together with their interval and games, and expect real-data results to be at least this noisy.

## 2. Completion objective: an extra co-occurrence term

- **Spec (7.4):** score full decks by strength plus a small synergy term.
- **Problem:** strength plus synergy alone stacks cards with high individual weights into decks nobody plays. Completion recall@10 was 0.18–0.31, against 0.52 for popular-card fill.
- **Change:** `objective = meta_win_prob + synergy_weight · mean_pair_synergy + cooccurrence_weight · mean_log_lift`. The new term is the mean smoothed log-lift over all pairs in the deck, i.e. "do players actually pair these cards?" Its weight is the smallest grid value whose **validation-window** recall beats popular fill (`evaluate.choose_cooccurrence`). That was 0.05 on both synthetic draws, which gave test recall 0.66–0.71 vs 0.46–0.52 for popular fill.
- **Undo:** `search.cooccurrence_weight: 0`.
- **Trade-off:** a higher weight gives more conventional decks with lower predicted strength. Notebook 06 shows the grid.

## 3. Strength: L2 strength chosen on validation

- `C` is picked from `strength.C_grid` by validation log loss, separately for the card and card+pairs models. With the fixed `C = 1`, search exploited rarely seen cards and claimed a 95.7% win rate for a deck nobody had played. Tuned (`C = 0.01` on synthetic), the top Hog Rider deck sits around 70–73%. That is still optimistic: see item 4.

## 4. Deck score interval

- Approximate interval = model uncertainty (Laplace approximation of the logistic regression coefficients, delta method) plus opponent sampling (bootstrap over test-window opponent decks).
- It does **not** cover selection effects. The top result of a search is the maximum of many noisy estimates, so it is biased upward. Explanations say so.
- New data-quality state `UNSEEN_DECK`: the exact deck never appears in collected battles, so its score is extrapolated from its cards. `LOW_CARD_DATA` marks a card form with too few training games to have a learned weight.

## 5. Search diversity

- Each beam parent may contribute at most `beam_width / beam_parents_min` children per step. Final results come from the whole last expansion and must differ by `min_diff_cards`. Without this, the beam collapsed onto near-copies and returned fewer than 3 decks.

## 6. Placement checks

- `rules.check_deck(..., placement=...)` checks one exact placement (`{entry_key: evo | hero | wild | normal}`), so "champion in a normal slot" is rejected explicitly. Without a placement, a deck is legal if *some* valid placement exists, and the result reports one.
- Base, non-champion cards may sit in an empty special slot. Spec section 2 says special slots can stay empty; it does not forbid base cards in them. VERIFY in-game.

## 7. Counting units

- Synergy and popularity count **deck appearances**: one side of one OK battle. A battle where both sides hold a pair counts that pair twice, once as a win and once as a loss.
- The synergy table used by search and explanations is fit on train + validation; test battles are never used to fit anything.
- Archetype "held-out 20" must be labeled before fitting (spec 7.3). The synthetic label file uses each deck's template of origin and is marked as not hand labels.

## 8. Synthetic data

- `python -m crdeck synthetic` writes raw-format files to `data/synthetic/` only. Every output there is labeled SYNTHETIC, and the API client refuses to write into that root.
- It exists to (a) run the whole pipeline before an API key exists and (b) check that the models recover a planted signal. It is never a fallback: with `CRDECK_DATA_SOURCE=real` (the default) and no real data, every step raises an error saying what to run.
