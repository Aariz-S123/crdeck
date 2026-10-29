# Verified snapshot findings — recheck against the live repository

Snapshot reviewed: supplied October 2026 source/exports. These are investigation anchors, not frozen production numbers.

Known findings from the supplied snapshot that must be addressed:

1. **Softmax exists.** web/engine.js, predictArchetype(), computes exponentials of class scores after subtracting their maximum, then normalizes. src/crdeck/archetype.py uses multiclass LogisticRegression.predict_proba(). REVIEW.md's blanket statement that softmax is absent is wrong. The DOCX already includes the softmax formula in §8.9, but lacks an accessible worked explanation.
2. **Sigmoid and softmax serve different purposes.** Strength/matchup win estimates use sigmoid. Softmax classifies deck styles. Neither is the Monte Carlo forecast.
3. **The next-period forecast is shown in this export.** web/modes.json.meta.status is `shown`: eight collection periods, six backtest transitions, mean error about 1.001 percentage points versus 1.034 for no change. The DOCX's claims that it is hidden or needs another period contradict this export.
4. **Next-season is separate.** modes.json.seasons.status is `blocked`, with one sufficiently covered season out of three required. src/crdeck/seasons.py supplies history/readiness, not an implemented future-season prediction engine. Do not imply that collecting enough seasons automatically implements one.
5. **Forecast uncertainty is problematic.** In the six exported backtests, the Monte Carlo median is slightly worse than no change in five periods and better in the last. Nominal 90% bands cover roughly 46% of scored card-period outcomes overall, weighted by card_forms_scored; per-period coverage ranges about 34–85%. The overall MAE advantage is not evidence of well-calibrated intervals or a statistically established advantage.
6. **Default builder results need a credibility fix.** Executing Engine.complete([]) on the supplied ranked.json produced three decks with NO_AIR_DEFENSE and zero exact-deck test battles, with estimates about 56.0%, 57.1%, and 58.2%. Zero exact-deck test battles is not proof a deck was never played anywhere. Show the precise support status. Do not turn these generated options into authoritative recommendations through prettier styling.
7. **Mobile baseline defect:** index.html lacks the normal viewport meta tag used by the other pages. Add a valid document shell, language, and responsive viewport; the claude-specific meta tag is not a substitute.
8. **Document generator contains stale prose:** e.g. a generic “bootstrap” explanation for a deck interval actually computed using covariance/delta method plus opponent sampling; “cards only” when the export says card_lr+pairs+skill; “edge not clear” alongside a log-loss difference interval entirely below zero; “five-page website” despite seven HTML pages. Fix generator logic, not just the rendered document.
9. **Retrospective inputs affect counter evaluation.** counters.opponent_sets() uses test-window deck frequencies, and backtest() ranks against those sets. The candidate pool comes from train_valid. This is not test-outcome training, but the selection is informed by the evaluation period's opponent mix. Do not describe the complete recommendation policy as a strict prospective holdout.

The supplied ZIP includes only Ranked and Trophy Road models and omits raw data, label files, per-mode golden fixtures, and other large files. Missing packaged files are not evidence that the original project never had them. Do not claim old check-results were rerun.

