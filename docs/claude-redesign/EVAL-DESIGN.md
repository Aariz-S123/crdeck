# Forward check of the counter recommendations: design, fixed before any result

Written 2026-10-29, before any number of this check was computed. It is committed on its own so the
commit records that the design came first. Results and code follow in later commits; this file is not
edited after them (corrections, if any, go in a new section at the end, dated, with the reason).

Background: BACKLOG.md items 1, 2 and 4, and finding 9 in FINDINGS.md. The existing check
(`crdeck.counters.backtest`, shown on the Counters page) is retrospective, and its difference ranges
treat the compared groups as independent although they share decks, battles and players.

## Question

When the counter page's inputs are frozen before the test window, do its top counter decks win against
their target style more often in the test window than (a) the decks the deck builder scores highest
overall and (b) all eligible pool decks? How sure can we be, once shared decks, shared battles and
repeated players are allowed for?

## Two versions, one piece of code

Both versions use the same exported models (strength, matchup, synergy, archetype classifier; all fitted
before the test window), the same real-deck pool (`counter_pool`: training and validation windows), the
same configuration (`config/counters.yaml`: `backtest.top`, `backtest.min_games`, `opponents_per_set`)
and the same outcome counting. They differ only in two inputs:

| Input | Retrospective (as exported today) | Forward (new) |
|---|---|---|
| Opponent decks standing for each style | most-played test-window decks of that style | most-played **validation-window** decks of that style (the latest battles before the test window) |
| Opponent sample of the general score (ranks the "highest-scoring general decks") | `n_opponent_decks` decks drawn from the test window | the same number drawn from the **validation window**, same seed, same procedure (`MetaScorer`) |

Everything a forward recommendation uses is then known before the test window starts.

## Outcome and groups

- Unit: one side of one test-window battle whose deck is in the pool ("a game"), with the opponent's deck
  style from the archetype classifier and the result (won or not).
- For each style s: counter group = the `top` pool decks ranked best against s's opponent decks
  (`_Scorer.rank`); field group = the `top` pool decks with the highest general score; all group =
  every pool deck. A game counts for a group when its deck is in that group's list for the style the
  opponent was classified as. A game can count for several groups (shared decks); that is kept.
- Pooled win rate of a group = its wins / its games, over every usable style (not `HYBRID / UNCERTAIN`,
  not `NO_LABELS`). Differences: counter − field and counter − all, in percentage points.
- Two populations: every player, and players who never appear in the training or validation battles
  (`new_player_sides`). The headline uses the unseen players when the counter group has at least
  `backtest.min_games` of their games, as the existing check does.

## Uncertainty

- **Primary: paired cluster bootstrap over players.** The cluster is the player whose deck it is.
  Each of 2,000 replicates (seed 42) draws as many players as there are, with replacement, keeps all
  their games, and recomputes every group's pooled rate and both differences from that same draw, so
  the groups stay paired and shared decks or battles stay shared. Ranges are the 5th and 95th
  percentiles of the replicates (90%). Point estimates are the full-sample values.
- **Sensitivity: the same, clustered on the opponent's player.** A battle is two games, and opponents
  repeat too; two-way clustering is not attempted. Both ranges are reported, whichever is wider.
- Time blocks are not used: the test windows span about two days, too few blocks for a block bootstrap.
- No significance test is added. A range that clears zero is described as such, nothing more.

## Style mixture

Pooled rates depend on how many games each group played against each style. A second, style-standardized
number is reported: the plain mean of the per-style win rates, each style weighted equally, over the
styles where every group has at least 30 games in the full sample (the page's existing "few games"
line). That set of styles is fixed once, before resampling; each replicate recomputes the same mean.
Its difference ranges come from the same paired replicates.

## Verdict (same wording as the existing check)

On the headline population, with the primary ranges: `too_few` if the counter group has fewer than
`backtest.min_games` games; `beats_strongest` if the 90% range of counter − field is above zero;
otherwise `beats_average` if the range of counter − all is above zero; otherwise `not_shown`.
The verdict is computed for both versions, so the effect of the retrospective inputs is visible.

## Scope

- Modes: every exported mode with a counter pool whose cached models load with an unchanged
  fingerprint. A mode whose cache is stale is skipped and listed; nothing is retrained.
- Nothing exported today changes: models, pool, configuration, `web/models/**` and `web/modes.json`
  stay as they are. Results go to a new file, `web/counter_eval.json`, written by
  `scripts/counter_eval.py`, and the Counters page shows them next to the existing check, labelled.
- Not done here (still in BACKLOG.md): the combined design that retrains with the test players removed
  (it needs retraining), and two-way clustering.

## Known limits, stated in advance

- The validation window is short, so in small modes some styles have no forward opponent decks and drop out.
- Style labels come from the classifier, for both the opponent sets and the outcome counting.
- The "unseen players" population uses the same models; it is not a player-disjoint retrain.
- Players were sampled by the collector (leaderboard and arena sampling), not at random from everyone.
