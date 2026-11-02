# Future meta recommender: design, fixed before any result

Written 2026-11-02, before any number of this feature was computed. It is committed on its own so the
commit records that the design came first. Code and results follow in later commits; this file is not
edited after them (corrections, if any, go in a new section at the end, dated, with the reason).

Known before writing this: the older replicator forecast's results in `docs/model-notes.md` section 12,
and that TimesFM 2.5 reads a series in patches of 32 points. Nothing about TimesFM on this data, and
nothing about the new deck ranking, had been run.

## Three questions

1. **What makes a meta deck good?** Which measured signals, known at the end of one period, go with a deck
   winning more or being used more in the next period, on battles the fit never saw?
2. **Can usage be predicted?** Do TimesFM and Monte Carlo predict the next periods' card usage better than
   simple baselines, and do their ranges hold the real share as often as they claim?
3. **Does predicting help a recommendation?** Do decks ranked against the simulated next field win more in
   the next period than decks picked by simpler rules?

"Meta" keeps its existing meaning: usage share among Ranked deck appearances. "Good" is never one number.
It is reported separately as winning (at equal rating) and as being adopted (usage), because a deck can be
popular without winning more.

## Data

- Ranked battles from leaderboard players' logs only, as in `crdeck.forecast` (one fixed kind of player),
  through the newest raw collection. Parsed into `data/processed/future_meta/`. `data/interim` and the model
  caches are not touched, so no exported model goes stale and nothing retrains.
- Periods: `crdeck.forecast.collection_periods` over every collection, then any period with fewer than 5,000
  battles merges into the next one. A small last period is dropped from scoring and reported as in progress.
- Usage share: `crdeck.forecast` definition (MIRROR and DRAW battles count). Win measures use OK battles only.
- Adjusted win rate of a group of games: 0.5 + (wins - expected wins) / games, where expected wins come from a
  rating-only logistic regression fitted on battles before the origin. It answers "did these decks win more
  than their rating gap predicts?" with no deck model involved.

## Forecast (question 2)

Every forecast is made at an **origin**: the end of a period, using nothing after it. Targets are 1, 2 and 3
periods ahead. Card forms are scored when they had at least 200 appearances in the period ending at the
origin (never chosen by looking at the target). The first origin has two periods behind it.

| Method | Definition |
|---|---|
| No change | the last period's share |
| Last 3 mean | mean of the last up to 3 periods' shares |
| Replicator Monte Carlo | the existing `crdeck.forecast.monte_carlo`, one period ahead only |
| TimesFM hourly (**primary**) | TimesFM 2.5 on hourly usage share up to the origin (hours with fewer than 200 appearances are gaps, up to 512 hours), mean of the hourly predictions over the target period's hours |
| TimesFM periods | TimesFM 2.5 on the period series itself, listed for comparison |

Hourly is primary because it gives the model a real-time axis across uneven collections and more than one
patch of history. This is decided here and not changed by results.

TimesFM 2.5 (`google/timesfm-2.5-200m-pytorch`, Apache-2.0 weights) runs on CPU, in its own environment,
`.venv-timesfm`, pinned in `requirements-timesfm.txt`. Settings: `normalize_inputs`, continuous quantile head,
`force_flip_invariance`, `infer_is_positive`, `fix_quantile_crossing`, all true. Its input is the raw share.

### Monte Carlo over TimesFM

2,000 runs, seed 42. Run r gives card form k the share `sigmoid(L_k + gamma_h * sigma_k * Z_kr)`:

- `L_k` is the logit of the TimesFM median. `sigma_k` is the logit distance between its 10% and 90% quantiles,
  divided by 2.563, so TimesFM says which cards are more uncertain.
- `gamma_h` is one calibration number per horizon: the 90th percentile of `|real logit - L_k| / sigma_k`,
  divided by 1.645, over earlier origins whose target had already been seen at this origin, so it never uses
  the future. It needs at least 2 such earlier forecasts; before that it is 1 and that origin is left out of
  the coverage numbers.
- `Z_kr = sqrt(0.75) * W_kr + sqrt(0.25) * e_kr`, with e independent standard normal. W mixes the earlier
  standardized misses with random normal weights and rescales per card to variance 1, so cards that missed
  together earlier tend to move together in a run. With fewer than 3 earlier forecasts, W is also independent.
- Each run's shares are rescaled so all forms sum to 8 cards per deck; forms not scored stay at their last share.

### Forecast measures and gate

- Measures: mean absolute error in share points per target period, then the plain mean over target periods;
  how many target periods each method beats no change; how often the 50% and 90% bands hold the real share.
- **Gate:** the forecast "passes" only if the primary method's mean error one period ahead is below no change
  AND it beats no change in more than half of the target periods. A pass does not need significance. The older
  gate in section 12 of the model notes passed on one 23-battle period, which is why this one counts periods
  and why small periods merge.
- The forecast is drawn on the new page either way, because showing it is the page's purpose. If the gate fails,
  the page says so first and labels the forecast experimental.

## Deck estimate and recommendation (question 3)

**Models.** For origin T (the end of period T-1): a `crdeck.matchup.MatchupModel` fitted on leaderboard OK
battles up to the end of period T-2, C = 0.01, the existing `min_pair_battles` and `min_card_games`. Period T-1 is
then held out from it, so a deck's record there is out of sample. C comes from the 2026-10-24 selection; that
small look-ahead is stated on the page. No retraining of exported models.

**Estimate in a field.** With card weights w, matchup weights K and card shares s:

    z(A | s) = sum_{i in A} w_i - sum_j s_j w_j + sum_{i in A} sum_j s_j K(i, j) + delta_A
    estimate(A | s) = sigmoid(z(A | s))

This is the exact mean log-odds of deck A against a field with shares s, at equal rating, since the mean
over opponent decks of a sum over their cards depends only on each card's share. Taking the sigmoid of the mean
log-odds approximates the mean of the sigmoids; the size of that gap on the real field is measured and reported.

**Own record, delta_A.** For each deck's games in period T-1, residual = won - model probability (with the rating
term), information = p(1-p), raw estimate = sum residual / sum information, variance v = 1 / sum information.
Empirical Bayes: tau^2 = max(0, mean squared raw estimate - mean v) over decks with at least 30 games, around
their precision-weighted mean mu. Posterior mean mu-adjusted: `shrink * (raw - mu)`, posterior variance `shrink * v`,
shrink = tau^2 / (tau^2 + v). Few games means the deck's own record barely counts.

**Candidates.** Real decks with at least 30 OK games over the last 3 periods before the origin, legal under
`crdeck.rules`.

**Monte Carlo.** Each of the 2,000 runs takes that run's card shares (one period ahead) and a draw of delta_A from
its posterior. Reported per deck: mean estimate, 90% range, chance of being above 50%, chance of being in the top
10 candidates, and the change caused by the forecast field against the current field.

**Lists.** Each list takes the top 10 (primary; top 30 secondary) under `crdeck.counters.observed_decks` with
`min_diff` 2, so listed decks differ by at least 2 cards, the rule the deck builder already uses.

| List | Ranks by |
|---|---|
| Future field (**the recommender**) | mean Monte Carlo estimate |
| Current field | the same estimate with last period's shares, no forecast |
| Cards only | the current-field estimate without delta |
| Last record | last 3 periods' adjusted win rate |
| Most played | last period's appearances |
| All candidates | no selection; the reference group |

**Outcome.** Adjusted win rate in target period T, pooled over every origin (T >= 3, since a model needs period
T-2 and a record needs T-1). Two populations: **players new to the deck** (**primary**: no earlier game with that exact
deck before the origin; this is what a person taking a recommendation would be) and all players. If the primary
population has fewer than 200 games in any compared list, the page says it is too few to judge.

**Ranges.** Paired bootstrap resampling players, 2,000 replicates, seed 42, keeping every player's games together
across lists. A difference is "clear" only when the whole 90% range is on one side of 0.

**Range check.** For candidates with at least 20 games in the target period: does a 90% range, combining the Monte
Carlo spread and binomial noise for that game count, hold their adjusted win rate? Reported, whatever it says.

**Verdict.** Stated for "Future field beats Most played", "beats Last record", "beats All candidates" and "beats
Current field" (that last one is whether the forecast itself helps). Each is clear better, clear worse or not clear.

## What makes a deck good (question 1)

**Rows.** One per deck and transition t to t+1, for decks with at least 30 OK games in period t, using a matchup
model fitted up to the end of period t-1. Every feature uses data up to the end of t only. A test checks this by changing
later battles and confirming that no feature moves.

| Signal | Definition |
|---|---|
| Own record | posterior mean of delta in period t |
| Card strength | sum of the deck's card weights minus the field's mean |
| Field fit | matchup term, sum_{i in A} sum_j s_j K(i, j), with period t's shares |
| Usage | log usage share |
| Momentum | change in logit share from t-1 to t (smoothed with 0.5 games) |
| Breadth | distinct players / games |
| Return rate | of the deck's players in t-1, the share who played it in t (add-one smoothed) |
| Player rating | mean rating of its players minus the period mean, per 100 |
| Elixir | average elixir cost |
| Spells, buildings, win conditions, air defense, splash | counts from the card labels |
| Evolutions, heroes | counts of those forms |
| Style | predicted style, one indicator each (one block) |

**Targets.** (a) Next-period edge: adjusted win rate in t+1 minus 0.5, in points, for decks with at least 10 games
there, weighted by those games. (b) Next-period usage growth: change in logit share, t to t+1, smoothed with 0.5
games so disappearing decks count, weighted by the square root of games in t.

**Model.** Weighted ridge regression on standardized signals, alpha 10, chosen here and not tuned. Being linear,
it adds up exactly per deck: coefficient x (value - mean), which is the per-deck explanation on the page.

**Out of time.** Forward chaining: fit on all earlier transitions (at least 2), predict the next. Out-of-time R^2 against
predicting the training mean, pooled and per transition. Challenger: `HistGradientBoostingRegressor` (max_depth 3,
learning_rate 0.05, max_iter 200, min_samples_leaf 20, seed 42); if it clearly beats the ridge, the page says the
linear explanation misses something. Secondary: correlation of the edge model's prediction with new-to-deck players'
results.

**Which signals count.** Coefficient per 1 standard deviation with a 90% range from a bootstrap of decks (1,000
replicates, seed 42). Drop-one test: remove a signal (the style block as one) and measure the change in out-of-time R^2.
A signal "holds up" only if its range excludes 0 AND removing it lowers out-of-time R^2. Every sentence on the page about
what makes a deck good is generated from these tests. If out-of-time R^2 is not above 0, the page says the signals did not
predict that target.

## Page

A new static page, `web/future.html`, under Explore trends, reading `web/future_meta.json`. TimesFM and Monte Carlo run
offline; the site gains no runtime dependency. Order: verdict, what makes a deck good, usage forecast, decks to consider
with their explanation, track record, assumptions. Every chart has a question title, a takeaway and a table version. No
"best deck" claims. Deck lists say "to consider". Not published anywhere without the owner's approval.

## Limits known in advance

- A season-level forecast still cannot be tested: logs hold a player's last 30 battles, so past seasons cannot be
  collected after the fact. This horizon is days.
- Few periods exist, so backtests are small and their results can change as collection continues.
- Long gaps between collections fill older hours mostly with less active players.
- New cards or balance changes have no history; no model here can see them coming.
- Association in any signal is not proof of cause.

## Corrections and additions

**2026-11-02, before any result on real data.**

- **Stricter "holds up" rule.** A test on constructed noise showed the rule above lets several signals pass by chance,
  because about 20 are tested at once with 90% ranges. A signal now holds up only if its **99%** range excludes 0 AND removing
  it lowers out-of-time R^2. Charts still draw the 90% range, and the page states the stricter rule.
- **Two more forecast families, reported only.** The same forecast code also runs on deck styles and on single decks (the 60
  most used at each origin, plus the listed decks at the live origin). Neither affects the gate, which stays on card forms.
- **Season start.** The leaderboards answered with no players on 2026-11-02, as a new season began, so that day's logs were
  fetched for the players on the newest non-empty lists (`scripts/collect_known_players.py`). The final period therefore crosses a
  season start, with the same players. It stays in the backtest: a forecast should be tested on the hard case too.

**2026-11-02, after a preview run on partial data, before the final run.**

- **The replicator baseline gets the same time cut.** The preview fed it every battle fetched at any time, unlike every other
  method, and that visibly flattered it (one target period's input was fetched mostly after its origin). It now reads only battles
  fetched by the origin, as this design's opening rule requires. Nothing about the primary method or the gate changed.
- **One more number, reported only.** The preview's top estimates sat well above what past picks won. The page now shows the mean
  estimate of past picks next to what they really won, so the selection effect is measured rather than only warned about.
- **Wording.** TimesFM's own ranges turned out too wide, so calibration narrows them on this data. The page describes the direction
  the data shows. The calibration rule itself is unchanged.

**2026-11-02, after the first full run, before the results were used.**

- **An origin must know enough battles to be a forecast time.** The merge rule above counts a period's battles as finally seen, but
  an origin only knows those fetched by then. Interrupted collections left two origins with almost nothing: the end of P5 knew 4,852
  battles and the end of P9 knew 384, so at the latter only 2 card forms could be scored, and their misses swung every average. An origin
  knowing fewer than 5,000 battles of its latest period is now skipped by every method, in the forecast, the deck check and the signal
  analysis, and the page says which ones. The period can still be a target for earlier origins. On the full run's numbers the gate
  failed with or without this rule (by hand, without P5 and P9: mean error 0.443 against 0.427 for no change, better in 2 of 6
  periods), so it does not flatter the primary method. It does remove a mean error that looked below no change only because of those
  2 card forms.

**2026-11-02, reported only.** While checking the page, the data showed the season change sharply at about 09:00 UTC on 2026-11-02:
ratings vanish from battle logs, a new Evolution jumps from 0% to about 7% of decks, and usage moves about twice as much as usual. The
newest period mixes both sides. The page now measures this directly: equal spans of hours on each side, each card's share since then, and
each listed deck's raw games since then. Forecasts, periods, the gate and the deck check are unchanged.

**2026-11-02, a data validity correction after inspecting the listed decks.**

- **Win measures need a known rating gap.** The top picks' records came almost entirely from the hours after the season reset, when logs hold
  no ratings, so those battles counted as evenly rated. Battles without a known rating gap now count toward usage only: the matchup fits, own
  records, the rating-only model and every adjusted win rate leave them out. Before the reset, about 1 to 3% of battles lacked a gap, so backtest
  numbers move slightly. The rule was chosen for what it means, not for how it scores, and the gate and the deck check are read as they come.
- **One more number, reported only.** The sampled players' own win rate either side of the reset, to show whether their results jumped.
