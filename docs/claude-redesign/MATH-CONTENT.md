# Run 4: required mathematics content

Teach in the order: the user's question → plain-language answer → one current-data example → formula and caveats. Define every symbol. Use actual exported values for project examples. Each introductory explanation should fit in 80–120 words, with worked evidence and equations in disclosures; avoid truncating necessary qualifications to meet that target.

## Sigmoid: who wins a modeled matchup?

`P(A wins) = sigmoid(z) = 1 / (1 + exp(-z))`.

z is the modeled advantage: deck utility difference, plus rating difference when applicable. Equal-rating display sets rating difference to zero. Matchup prediction adds cross-deck interaction weights; these differ from within-deck pair terms. Show a real deck/opponent, computed advantage and probability. Explain averaging over the actual opponent set and weights to get the reported field/target estimate. This estimates outcomes from recorded patterns; it does not simulate gameplay.

Show the deck interval method actually used (covariance/delta method plus opponent sampling), not a generic bootstrap description. Distinguish this from bootstrap evaluation intervals, Wilson record intervals and Monte Carlo prediction bands. Coefficients are log-odds, not percentage-point effects or causal effects. Explain regularization, calibration, AUC and log loss only where needed with optional glossary links.

## Softmax: what style does the deck resemble?

The classifier uses card indicators, role counts, average elixir, win-condition count and spell count. Derive feature counts/order from current exports.

`z_s = w_s · x + b_s`

`p_s = exp(z_s - max(z)) / sum_t exp(z_t - max(z))`

Explain: styles receive scores; exponentials produce positive weights; division by their total produces probabilities summing to one. Subtracting the maximum improves numerical stability without changing the result.

Implement a real-deck table with all classifier classes: style, raw score, exponential weight, probability. Highlight the top class and threshold result. Populate it from the same feature construction as the engine, without a parallel approximation that drifts. Test against engine results. No temperature parameter or new softmax recommendation ranking.

Use “Predicted style: Cycle,” with the probability in a disclosure. Classifier probabilities describe learned labels, not wins or independently verified certainty. Distinguish the trained Hybrid class from the low-confidence fallback. Explain the small held-out label set and label provenance. The formula already appears in DOCX §8.9; the improvement is the worked explanation and correct UI integration.

## Monte Carlo: how much might a card be used next period?

One run represents a possible next-period observed usage share under the model. It is not a simulated battle, personal climb or complete next-season deck prediction.

Define usage share: fraction of deck appearances containing a card form; a battle contributes two appearances. Multiple cards occur together, so card shares do not sum to 100% and must not be softmax-normalized. Define collection periods from collection boundaries, separately from seasons.

Explain the actual sequence in forecast.py:

1. Bootstrap whole battles within past periods, producing plausible shares/win rates.
2. Refit `logit(s_next) = logit(s_now) + alpha + beta*(win_rate_now - 0.5)` on sampled prior transitions.
3. Use sigmoid to convert predicted log-odds back to share.
4. Add binomial observation noise for assumed next-period appearance count.
5. Repeat configured runs; report median and central 50%/90% simulation bands.
6. Compare predictions with later observed periods and a no-change baseline; separately inspect interval coverage.

Define logit, alpha and beta. Beta is estimated association, not a guarantee winning cards gain usage. Multiplying least-squares rows by sqrt(games) weights squared residuals by games. Backtests use observed target-period size; future forecasts assume the latest period's size. Read runs, seed and bootstrap count from settings (review snapshot: 2,000 / 42 / 300).

Mandatory display: current forecast state, current/history period dates, no-change comparison, mean MAE in percentage points, per-period comparison disclosure, nominal coverage and achieved historical coverage. The gate currently accepts mean MAE no worse than no change; it does not test significance or calibrated intervals. Keep the forecast experimental and clearly flag undercoverage. Do not change publication gates in this run.

Optional P1 visual: observed points plus exported median/quantile bands and no-change baseline; label observed versus predicted regions. If draws are unavailable, use quantiles; do not invent animated runs. Season readiness is a separate panel and not an implemented prediction engine.

Advanced caveats: variable period duration; last-30-battle truncation; changing players despite a consistent sampling source; repeated-player dependence; balance changes; independent marginal binomial draws that do not generate coherent eight-card decks. More simulations reduce simulation noise, not these modeling errors.

## Remaining explanation safeguards

Synergy is excess observed joint winning relative to the model's expectation; lift describes co-occurrence. Search score combines distinct terms and is not a probability. If showing scaled score points, scale every component consistently. Explain selection optimism: searching many candidates can exaggerate the best estimate.

Preserve existing embedding and loss-surface material. State that map proximity reflects co-occurrence, projection loses information, and full-dimensional distances drive decisions. Label the loss surface as a two-parameter slice, disclose vertical stretching and distinguish illustrative gradient descent from the actual optimizer. Do not introduce new scientific estimators or rewrite these implementations.

Documentation fixes target generator branches, not manual patching of its output. Verify “cards only” versus pairs, bootstrap versus delta interval, significance wording versus practical importance, page counts and forecast readiness against actual fields. Keep examples and prose synchronized with future exports.
