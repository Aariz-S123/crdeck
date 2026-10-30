# Backlog: research and product work deliberately not done in Runs 1–4

These items came out of the redesign review. Runs 1–4 label the current behaviour honestly but do not change
how anything is evaluated or trained. Each item below needs its own design, specified before any new
numbers are looked at.

**Run 5 (2026-10-29, at the user's request "implement all of them").** Done: items 1, 2 and 4 below, as
the forward check (design fixed first: `EVAL-DESIGN.md`; code `crdeck.counters.check_version`,
`scripts/counter_eval.py`; results `web/counter_eval.json`, shown on the Counters page), and every product
item except card imagery. Still open: item 3 (it needs retraining), two-way clustering, and card imagery
(no image source is in the repository or approved; the runs' rule is "no image dependency"). Details and
checks: `PROMPT-PROGRESS.md`, Run 5.

## Counter evaluation (research)

1. **Prospective (strictly forward) evaluation of counter recommendations.** Today `counters.opponent_sets()`
   picks each style's opponent decks from the test window, and `backtest()` ranks the pool against those
   sets before scoring test-window outcomes. Outcomes are never used for ranking, but the opponent mix is.
   A forward test must freeze, before the evaluation window: the candidate pool, the opponent mixture per
   style (e.g. from train+valid only), the configuration, and the ranking inputs; then score later
   outcomes only. Keep the current "recent opponents" mode as a separate, clearly labelled use case.
2. **Dependence-aware uncertainty for the comparison columns.** The counter / highest-scoring / all-pool
   groups share decks and battles, players repeat, and style mixes differ between groups. The old note
   that treating them as independent "only makes it wider" is not established. Options to study: paired
   resampling over an independent unit (player or time block) that keeps every compared policy's overlap,
   clustering by player, and stratifying or standardizing by opponent style before pooling. Choose the
   method on design grounds, not on which gives favourable intervals.
3. **Two different "new player" checks.** `counters.new_player_sides()` keeps games by players who do not
   appear in the training battles, scored by the same models. The matchup evaluation's `player_disjoint`
   row retrains without those players. The pages now label them differently; a combined design (retrain
   and rank with test players removed) would be the clean version.
4. **Style-mixture confounding.** Pooled win shares over styles depend on how many games each style has.
   Report per-style results (already in a disclosure) and a style-standardized pooled number.

## Product (P2, not started)

- Comparison view for the three builder options (shared/different cards, elixir, warnings, support,
  estimates) without declaring a winner from point-estimate differences.
- Navigation regrouping into Build / Counters / Explore trends / How it works, keeping old routes.
- Card imagery from a legitimate source, with text names kept as the identifier.
- Counter selection stored in the link (style or cards) without breaking old links.
- "Try an example" pick on the builder.
- Lazy rendering of the card map and charts inside closed layers.
