# Balance watch: design, fixed before any result

Written 2026-11-16, before any code in `src/crdeck/balance/` was run on real battles. The git commit time of this file is the proof. It follows `docs/fable-brief/BLUEPRINT.md` Sections 2, 4, 5.2 and 6.4 to 6.8; where this file is more exact than the blueprint, this file is what the code implements ("Points made exact", at the end).

Later changes go at the bottom as dated corrections. Nothing above a correction is edited after a result is seen.

## 1. What is predicted

**Question.** For the next official balance update: which cards are most likely to be nerfed, and which to be buffed?

**Answer shape.** Two ranked lists (possible nerfs, possible buffs) in tiers: "Watch closely", "Possible", "No signal", "Not enough data". Never a probability. Only one update (2026-10-19) has battles from before it, and nothing can be calibrated on one event.

**Unit.** The base card (`card_id`). Evolution and Hero forms are added up into their card. The official notes say base changes also reach the other forms "most of the time", and the labels keep the form, so a per-form analysis stays possible later.

**Horizon.** "The next update", not a number of days. Update dates are irregular (2026-08-04, 09-16 or 09-23, 10-06, 10-19), so a fixed horizon would hold zero, one or two updates. If no date is announced the page says so.

**Direction is part of the target.** A card listed as a possible buff that gets nerfed is a miss.

### Labels (per card per update)

`nerf`, `buff`, `rework` (both directions in one update), `fix`, `addition`, `none`. They come from `config/balance/events.yaml` through `crdeck.balance.events.card_labels`.

- A hit is a `nerf` on the nerf list or a `buff` on the buff list.
- `rework` counts only in the secondary "changed at all" number.
- `fix` and `addition` never count.
- A card changed in two updates has one label in each.

### What is left out

- Any forecast of usage after a change that has not happened.
- Announcement text from before the cutoff.
- Third-party win-rate data.
- Grand Challenge claims. The data has no Grand Challenge battles. "Top players" here always means leaderboard players' Path of Legends battles.
- TimesFM and the Monte Carlo forecast. They forecast usage, not the developers' choice, and there are no labelled updates to learn how one maps to the other. A forecast feature is the first ablation candidate at gate G1.
- Watch-list output never enters a forecast, a deck score or a counter ranking. A test checks that those modules do not import `crdeck.balance.watch`.

## 2. Cutoff, window and leakage

- **Cutoff T.** A list is computed for a cutoff T (default: 00:00 UTC of the day it is run) and frozen as a snapshot file.
- **Known at T.** A battle counts only if it was played before T **and** fetched by T (`RankedData.known_at`).
- **Last update.** `E_last` is the newest calendar event before T that holds a nerf, buff or rework, whatever its source. Releases and bug-fix events do not move it.
- **Window.** `W = [max(T - 14 days, day after E_last), T)`, whole UTC days. Battles played on the effective day of any event with a balance change are left out of every window, because the hour of an update is unknown.
- **Scoring cutoff.** The snapshot scored for an update is the newest one whose T is at least 24 hours before the update's earliest public day (its announcement day if one is recorded, else its effective day). A snapshot is never rebuilt after the fact. If none exists, the update is "not scored (no snapshot)".

## 3. Who counts, and when a card is listed

- **Top players.** Sides of Path of Legends battles from the leaderboard sample (`RankedData.core`). Usage counts sides of battles with status OK, DRAW or MIRROR, as the usage pages do. The win edge uses OK battles with a known rating gap.
- **Every league and arena.** Ranked and Trophy Road sides with `RankedData.weights` (each league and arena with enough sides counts the same). Shown for comparison only. It never enters the score.
- **Eligible at T:** the card is in the saved card list, it was released at least 14 days before T, and it has at least 300 top sides in W. Otherwise its tier is "Not enough data" with the reason (`too_few_games` or `new_card`).
- **Status of the whole list.**
  - `insufficient`: W is shorter than 7 days, or W holds fewer than 50,000 top sides. No list is made.
  - `stale`: more than 45 days have passed since both the newest calendar event and the day the official notes were last checked (`checked_on`).
  - `preview`: otherwise. The page calls it a research preview until gate G1.

## 4. Signals

All in W, top players, known at T. `N` is the number of cards in the card list, `n` the number of top sides in W.

| Signal | Definition | Uncertainty |
|---|---|---|
| Usage `usage_top` | share of top sides whose deck holds any form of the card | player bootstrap, 5th to 95th percentile |
| **U** | `ln((usage_top + 0.5/n) / (8/N))`: usage relative to the average card. Usage shares add up to 8, so the average card is at `8/N` | |
| Raw edge `edge_raw` | mean, over rating-known OK top sides holding the card, of `won - expected`, where `expected` is the win chance from the rating gap alone | player bootstrap gives its standard error `se` |
| **E** | `edge_raw` shrunk toward 0: `E = tau2 / (tau2 + se^2) * edge_raw`, with `tau2 = max(0, variance of edge_raw across cards - mean of se^2)` | posterior sd `sqrt(tau2 * se^2 / (tau2 + se^2))`; the 90% range is `E ± 1.645` of it |
| **M** | `logit(usage in the last 7 days of W) - logit(usage in the 7 days before)`, each with `+0.5/n`. 0 and flagged when W is shorter than 14 days | |
| **R** | 1 if the card or one of its forms was released in the 60 days before T (calendar `addition` entries, or first seen in a saved card list), else 0 | |

Shown but not scored: `usage_all`, `days_since_change`, the last labelled change, sides and players.

**The rating expectation.** `crdeck.strength.RatingBaseline` (the project's existing rating-only logistic regression), fitted on the rating-known OK top battles of W known at T. Not a second rating model.

**Player bootstrap.** Each player gets an independent Poisson(1) weight per draw, and all of that player's sides carry it (1,000 draws, seed 42). This is the usual vectorised stand-in for resampling players with replacement: the two agree in expectation and for large player counts. The rating fit is not redone per draw.

Assumptions, each with its test:

| Assumption | Test |
|---|---|
| Top Path of Legends usage and edge stand in for what the developers watch | the track record at G1; an ablation that ranks by `usage_all` |
| The rating gap removes enough of player skill from the edge | compare edges with and without the adjustment; large moves mean confounding |
| A 14-day window with a 7-day minimum | ablate 7, 14 and 21 days at G1 |
| Robust z-scores and the fixed weights below | the ablations of Section 7 |
| Sides of one player are dependent; players are independent | compare with the opponent as the resampled unit |

## 5. The score (fixed now)

`z(x)` is a robust z-score across eligible cards: `(x - median) / (1.4826 * MAD)`, clipped to ±4. If the MAD is 0, every z is 0.

```
nerf_score = max(0, z(E)) + max(0, z(U)) + 0.5 * max(0, z(M)) + 0.5 * R
buff_score = max(0, -z(E)) + max(0, -z(U)) + 0.5 * max(0, -z(M))
```

The weights 1, 1, 0.5 and 0.5 are fixed here and are **not** tuned on the 2026-10-19 pilot or on anything else before gate G1. E and U are the two numbers Supercell has named (use rate and win rate, 2017 statement). M and R are secondary. R is only on the nerf side, on the hypothesis that new releases mostly get trimmed.

**Direction.** A card belongs to the direction with its higher score. Equal scores: no direction.

**Tiers.** Within a direction, cards are ranked by score, highest first (ties by card id).
- "Watch closely": rank 1 to 5 and score above 1.0.
- "Possible": rank 1 to 15 and score above 0.5, and not "Watch closely".
- "No signal": everything else that is eligible.

K = 15 is the evaluation depth: about 12% of 123 cards, near the 11 cards changed on 2026-10-19.

**Reasons** shown with a card come from fixed sentence templates, one per signal, written only when that signal's z is at least 1 in the card's direction (or R is 1).

**Reference ranges.** The 45 to 55% win-rate band and the 7 to 9% usage band are community-reported, not official. They are drawn as labelled reference ranges only. They are not rules and do not enter the score. (In the exported Ranked stats, 122 of 123 cards already sit inside 45 to 55%.)

## 6. Protocol

1. **Pre-register.** This file, committed before any run.
2. **Daily snapshot.** `scripts/balance_watch.py` writes `web/balance_watch.json` and `docs/balance/snapshots/<cutoff day>.json`. An existing snapshot is never overwritten. The owner commits snapshots; the commit time shows when a list existed.
3. **Scoring.** When new official notes appear: enter the event in the calendar, then `python scripts/balance_watch.py --score <event id>`. It picks the snapshot by the scoring-cutoff rule and adds one row to `docs/balance/track_record.json`.
4. **Pilot (one time, an anecdote).** The 2026-10-19 update is scored from a list rebuilt with T = 2026-10-18 00:00 UTC. The project's first collection was after that day, so the pilot uses battles **played** before T but **fetched** later: the "fetched by T" rule is waived for it and for nothing else, and it is marked `pilot: true`. It could not have been made at the time. Its window (2026-10-07 to 10-17) over-weights less active players, whose last 30 battles reach further back. If it fails the status rule of Section 3 it is reported as `insufficient` and not scored. **No weight, threshold or rule changes after seeing it.**
5. **Walk-forward (for a fitted model, later).** Train on all updates before update k, test on k, expanding. The newest three updates stay untouched until the decision.

### Baselines, scored at every update with the same K

1. Random: expected hits@K = K × (labels in that direction) / (eligible cards).
2. Usage only: nerf list = highest U, buff list = lowest U.
3. Win edge only: highest E, lowest E.
4. The 45 to 55% band rule (a hypothesis): nerf = raw top win rate above 55%, buff = below 45%, ordered by distance from the band. Expected to be nearly empty at the top level.
5. Recency: cards changed at `E_last`, in the direction they were last moved, most recently released first.
6. Trend: highest M, lowest M.

### Metrics

- Per update and direction: hits@5, hits@15, recall@15, average precision over eligible cards, number of labels.
- Across updates: sums, and how many updates the score beats each baseline in.
- Secondary: "changed at all" hits@15 (any of nerf, buff, rework).
- No accuracy figure (about 8 changed cards in 123).
- Uncertainty is over updates, never over card rows, and only with 6 or more updates.

### Ablations (at G1 and G2 only)

Drop each of E, U, M, R in turn; replace U with usage relative to the card's role; add deck concentration; add the TimesFM usage forecast. A part stays only if dropping it lowers summed hits@15. With 6 updates that is weak evidence and is described that way.

### Gates

| Gate | Condition | What the page may show |
|---|---|---|
| G0 (now) | none | tiers, "research preview, not yet tested on any update", signal values with ranges |
| G1 | 6 or more scored updates, and the score's summed hits@15 (nerf + buff) beats usage-only and random in at least 4 of 6 | adds the track record sentence |
| G2 | 10 or more updates, 100 or more directional labels, a logistic model beats the score's ranking on log loss walk-forward, Brier skill above 0 | probabilities, with a reliability chart |
| Reject | the G1 rule fails | the usage-only fallback, with no nerf or buff wording |

Six updates is the smallest count where "ahead in 4 of 6" is more than a coin flip usually gives (exact binomial p of about 0.34 for 4 or more of 6), so G1 allows a track record and no claim.

### Leakage tests

- Changing battles played after T moves no signal.
- Battles on an effective day are left out.
- `--score` refuses a snapshot whose cutoff is too late.
- The seed is 42 and a rerun gives the same file apart from `generated_at`.

## Points made exact (2026-11-16, before any run)

These settle places where the blueprint left a choice. None was chosen after looking at a result.

1. `E_last` and the excluded days come from events with a nerf, buff or rework from any source, not only scoreable ones: a community-reported update still changed the cards.
2. `N` in U is the number of cards in the saved card list, not the number of eligible cards. It only shifts U by a constant, which the z-score removes.
3. A card with fewer than 100 rating-known top sides in W has no edge: its E is 0 with an "edge unknown" flag, and it is left out of the shrinkage spread.
4. Tiers: a card at rank 1 to 5 with a score between 0.5 and 1.0 is "Possible", not "No signal".
5. Lists for hits@K are the top K cards of a direction by score among eligible cards, whatever their tier, cut short if fewer cards have that direction. A baseline's list is its top K by its own ordering.
6. `stale` uses the later of the newest calendar event and `checked_on`.
7. The "changed last update, waiting for new data" state of the blueprint cannot occur separately: fewer than 7 days of battles since an update already makes the whole list `insufficient`.
8. Player of a side: the side's own player tag, for both sides of a battle.
9. The pilot's waiver of the "fetched by T" rule (Section 6, step 4).

## Corrections

None yet.
