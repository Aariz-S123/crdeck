# crdeck: four-run Claude Code implementation plan

## Use this package

Place this folder at `docs/claude-redesign/` in the actual crdeck repository. It contains this controller, `FINDINGS.md`, `ACCEPTANCE.md`, and `MATH-CONTENT.md`. Run 1–4 instructions are sections within START-HERE.md, not separate run files. The included PROMPT-PROGRESS.md is an unfilled template: copy it to the repository root only if no progress log exists; preserve any existing progress. These files replace the earlier monolithic prompt; do not execute both.

Start Claude Code with:

> Read docs/claude-redesign/START-HERE.md and its Run 1 references. Execute Run 1 preflight only. Show the bounded change plan and baseline evidence, then wait before editing application files.

After reviewing that plan, say:

> Approve the Run 1 plan. Implement Run 1 only, run its checks, checkpoint the result, and stop.

For subsequent sessions, use:

> Read docs/claude-redesign/START-HERE.md and PROMPT-PROGRESS.md. Execute Run 2 only. Preserve the completed runs, run the assigned acceptance checks, checkpoint, and stop.

Replace 2 with 3 or 4 when ready. Starting a later run authorizes that run's stated scope; do not repeat the initial approval ceremony. Never advance automatically to another run. A fresh context may resume the active run from the progress log.

## Mission and defaults

Improve the existing crdeck website for someone unfamiliar with Clash Royale and statistics while preserving its scientific and engineering integrity. During implementation runs, do not stop at an audit, mockup, or list of suggestions. Deliver working, tested changes within the active run.

Primary flow: pick up to three cards → inspect eight-card options → understand support and weaknesses → explain or swap. Secondary flow: choose an opponent → inspect counters. Keep mathematics accessible through progressive disclosure.

Proceed with the defaults below. Ask only if a missing answer materially blocks correct work; record routine assumptions and continue. Missing REVIEW.md or crdeck-documentation.docx must be disclosed at the start: proceed from code and exported JSON, without inferring missing contents. Read repository instructions first.

## Truth rules — apply to every run

1. Code plus matching exports establish current behavior; prose contains claims to verify. Recheck snapshot findings against the live repository before changing anything.
2. Derive project numbers from actual data. Label invented teaching examples illustrative. Composite score is not probability; style probability is not win chance; association is not causation; AUC is not accuracy.
3. Every displayed metric needs its unit, population/time window, measured/model/imported/rule provenance, and correct uncertainty method. Zero observations is not zero wins. Absent pool membership is not proof a deck has never been played.
4. Preserve legality, locked picks, fixed seeds, deterministic tie-breaking, Python/JS numerical parity, and existing model coefficients/objective weights. Warnings remain advisory, not illegality.
5. Missing ZIP assets do not mean they never existed upstream. Historical logs are not freshly executed tests. Failures, skipped checks and missing prerequisites must be reported separately.
6. Do not claim increased player win rates or reliable forecast coverage from a UI improvement. Preserve caveats about sampling, selection optimism and player-skill proxies.

## Boundaries and checkpoints

No new runtime dependencies, framework migration, build step, network service, worker architecture, paid API, or deployment. Use the existing vanilla JS loading convention; isolated helper files are allowed without converting the project to ES modules. Both light and dark must render correctly; remove neither.

**Read-only throughout these runs:** `.env*`; raw/processed training data and labels; web/models/**; web/model.json; web/modes.json; existing golden files; dependency manifests/lockfiles; config/**; src/crdeck/rules.py, strength.py, matchup.py, synergy.py, archetype.py, forecast.py, seasons.py, dataset.py, pipeline.py; scripts/export_web.py. Do not run collect/build/evaluate/export or retraining commands. Reading secrets is unnecessary.

**Allowed by active run:** relevant web HTML/CSS/common.js; narrowly scoped engine.js changes only in Run 2; additive post-training recommendation helper and focused tests in Run 2; documentation/progress files; narrow scripts/make_docs.py fixes and its tests in Run 4. Existing scoring/search implementations are preserved. If a new helper invalidates training caches, stop that change rather than editing pipeline.py silently.

At preflight inspect git status. Never reset, stash, amend, overwrite or commit somebody else's changes. Before/after each run record HEAD and changed paths. After a passing run, stage only your completed changes explicitly and make one descriptive local commit; do not push or use `git add .`. If a commit would include unrelated staged work, stop before committing and report. If git is unavailable, keep a file manifest and scoped diff instead; do not initialize a repository. A blocked partial run is not a passing checkpoint.

Use `PROMPT-PROGRESS.md` at repository root with: active run; starting HEAD; planned paths; truth-table field mappings; decisions; completed items; checks and results; blockers; next exact action. Update at each coherent checkpoint. A new session reads it before editing. Proposed edits exceeding 12 application files or 800 added/deleted non-generated application lines in one checkpoint require a plan update and user review before continuing; documentation/test expansion is reported separately. These are review boundaries, not incentives to minify or weaken the work.

### Stop and report

Stop the affected change, preserve completed work, and continue only independent in-scope items when:

- A protected file, fitted coefficient, rule, scientific threshold or training cache behavior must change.
- A P0 depends on missing data/models or unavailable essential verification.
- Existing goldens would need replacement to make a regression disappear.
- Baseline and new regressions cannot be distinguished.
- Working functionality or unrelated user changes would be overwritten.
- A new dependency, service, retrain or data package becomes necessary.
- The review-size boundary would be exceeded.

Name the exact blocker, affected acceptance IDs and smallest next action. Never silently substitute a weaker implementation. If any P0 remains blocked, mark the run BLOCKED and do not advance. Missing models unrelated to the active acceptance subset do not block all work. Missing browser verification blocks visual sign-off, not independent source fixes.

## Priorities and run ownership

| Run | P0: required for this run | P1: after P0 | P2: backlog only |
|---|---|---|---|
| 1 | Baseline; viewport/shell; truthful labels; loading/error/state safety; two-theme preservation | Inline newcomer definitions | Navigation regrouping; card imagery |
| 2 | Observed/generated provenance; deterministic observed selector; exact picks; support/warnings; engine regression checks | None required | Comparison view |
| 3 | Action-first explanations and counters; working swaps/undo; retrospective labels | Three-layer evidence disclosures | New evaluation methods |
| 4 | Correct sigmoid/softmax/Monte Carlo teaching and status; softmax worked table; coverage disclosure; narrow generator fixes | Quantile forecast visual from exports | Generator rewrite; simulated-run animation |

P0 means required in its assigned run, not permission to implement future runs. P1 can be deferred explicitly when it threatens a P0. Do not begin P2. A documented source-input blocker can leave a regeneration step blocked without inventing its output.

## Run 1 — stable foundation, no recommendation-policy change

Read FINDINGS.md and ACCEPTANCE.md Run 1. Inspect all seven pages, common.js/app.css, applicable tests and exported schemas. Reproduce the no-pick Ranked result and record names, estimates, warnings and exact-deck support. Inventory model/fixture availability. Record existing failures before modifications.

**Preflight checkpoint:** show a maximum 10-item checklist, proposed file list, protected-file risks, current screenshots or exact browser blocker, and the metric truth table. Pause before application edits. This is the only mandatory pre-edit approval checkpoint.

After approval:

- Fix index.html document shell, language and viewport without changing scoring.
- State the eight-card/0–3-pick purpose. Add optional short definitions for elixir, win condition, mode and forms; derive rules from the project.
- Replace misleading “strongest,” “% sure,” unconditional wins-more-than-loses, and “About even” certainty with model-qualified wording. Display exact-deck support and warnings beside estimates. Keep style and performance separate.
- Distinguish missing model asset, insufficient data, no results and actual error; preserve input and offer actionable recovery. Do not delete production modes to accommodate the partial ZIP.
- Guard malformed hashes, stale async mode responses and delayed calculation results. Preserve valid picks/deep links; report removals. Keep diagnostic errors out of the primary user message.

Run assigned checks, record evidence, commit completed work, stop. Existing recommendations must remain numerically unchanged.

## Run 2 — recommendation provenance, one intentional policy change

Read Run 1 progress, relevant counters/search/engine code and ACCEPTANCE.md Run 2. The following is the only authorized recommendation-policy change:

Add explicit **Observed decks** and **Generated decks — experimental** choices. Default to Observed when an eligible exported pool exists. Preserve the existing beam search unchanged behind Generated. Do not silently switch sources; no observed match offers an explicit generated action or editing picks.

Reuse the exported capped/frequency-filtered real-deck pool, not test-window records as candidates. Require exact selected forms, legal/unlocked decks, existing general-builder objective and existing deterministic diversity/tie rules. Counts mean train-plus-validation deck appearances, not unique players. If no usable pool is exported, say so; keep Generated accessible without pretending there are observed options.

Implement selection in an isolated JS helper and equivalent additive Python post-training helper. Do not modify fit/scoring equations or production exports. Prove equivalence using focused shared fixtures derived from the supplied model, while leaving original goldens unchanged. Retain existing engine APIs and serialized URLs.

Results display: eight named cards and user picks; predicted style; main warning; observed/generated source; exact support period/count; model estimate/interval; Explain and Copy actions. Show all warnings without treating them as illegality. If no actual explanatory evidence exists, say so instead of generating strategic claims.

Finish this run before redesigning the full explanation page.

## Run 3 — decisions first, evidence on demand

Read relevant pages and ACCEPTANCE.md Run 3. No mathematical/ranking changes.

reason.html: first show deck, role summary derived from labels, up to three major warnings, one highest-ranked eligible swap and Apply/Undo. Show remaining warnings through an explicit count/disclosure. Below that use Overview → Evidence → Math disclosures; preserve all existing analysis and 3D tools. Keep swap policies distinct and locks intact. “No improving single swap found” is a local-search statement, not global optimality.

Counters: opponent selection before detailed evaluation; add one-sentence style definitions. Explain partial-card matching versus exact eight-card opponents. Keep a one-sentence evidence limitation near results; move detailed tables into disclosures. Distinguish target estimate, field estimate and measured style record. Label current evaluation retrospective: test-period opponent frequencies inform ranking. Distinguish unseen recommending-player sides from a fully player-disjoint retrained model. Replace unsupported absence/count and conservative-interval claims with precise wording.

Preserve current live/recent-opponent selection. **Do not implement prospective evaluation, dependence-aware confidence intervals or a new backtest path in these four runs.** Document those future research requirements in a backlog, including frozen prior inputs, group overlap, repeated players and style-mixture confounding. A “tested prospective path” is not a small documentation task and is deliberately deferred.

Keep current routes and copy/swap/undo intact. New navigation architecture and comparison UI are backlog items.

## Run 4 — teach the real models, repair stale documentation

Read MATH-CONTENT.md and ACCEPTANCE.md Run 4. Implement its required plain-language explanations and real-deck softmax table. Separate observed history, experimental next-period forecast and season readiness. Display at most three headline usage changes, then searchable detail. Derive state/thresholds/counts from exports, never hardcode the review snapshot.

Use up to two disclosure levels: overview → worked example/math. Preserve technical evidence without making it the primary selection task. Fix verified hardcoded generator claims with small data-driven branches; do not rewrite the generator or pipeline. Regenerate the DOCX only when its existing inputs and dependencies are available, then inspect the rendered output. Otherwise deliver generator tests and identify regeneration as blocked.

## Design and final-review contract

Keep existing palette/tokens as the starting point. Body text 16px minimum, line height 1.5–1.7; explanatory text measure 45–75 characters. Primary controls at least 44×44 CSS px; WCAG 2.2 AA is the target, not a claim established by an automated scan. Keyboard focus visible, definitions usable by touch/keyboard, no color-only state, reduced-motion respected. No animation is required; new transitions, if used, are 120–200ms and disabled with reduced motion.

Desktop ≥960px: picker beside results; mobile: compact picks, searchable list and visible “View results” action, then stacked decks. Preserve named cards without adding an image dependency. Both themes must be tested at 390px and 1440px, plus keyboard/200% zoom and a 768px smoke check.

For each run capture up to six relevant baseline views and the same six after changes, chosen before editing (two key surfaces × desktop light/mobile light/mobile dark). Additional theme/width smoke checks need no saved screenshot unless defective. Make one consolidated repair pass and one confirmation pass; unresolved P0s remain blocked. Never stop before essential functional validation merely because a screenshot quota was reached.

Final response must use this template:

## Run status
PASS | BLOCKED | FAIL, active run, completed/deferred IDs.
## Changed
User-visible improvements and reason.
## Files
Changed paths; commit and starting HEAD or non-git diff location.
## Checks run
Table: acceptance ID | exact command/manual action | pass/fail/blocked | evidence.
## Limitations
Missing inputs, unverified rendering, remaining scientific limits.
## Policy changes
None, or the exact observed/generated selection change; confirm protected model outputs unchanged.
## Next step
Next authorized run or exact blocker resolution. Do not execute it automatically.
