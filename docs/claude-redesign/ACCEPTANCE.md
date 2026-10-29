# Acceptance checks by run

Read the active subset plus the regression contract. Statuses are PASS, FAIL or BLOCKED; an omitted prerequisite is not a pass. Attach exact commands, outputs or manual evidence to PROMPT-PROGRESS.md. Tests should validate observable behavior or independent expected values, not mirror implementation blindly.

## Regression contract — every implementation run

Before editing, identify relevant baseline failures. After editing run affected existing tests and focused new tests. Run the full applicable suite once at the final run, or earlier when changes cross subsystems. Preserve assertions and old golden files.

Existing commands to inspect before use:

- `python -m pytest` (select relevant test files initially).
- `node scripts/check_web_engine.mjs` — requires per-mode models/goldens.
- `node scripts/sweep_web_engine.mjs` — inspect asset requirements first.
- `node tests/web/page_test.cjs` and `node tests/web/site_check.cjs` — use their documented invocation and installed jsdom dependency.

The review ZIP lacks most models, raw/label data and per-mode goldens. Do not run guaranteed-missing full checks repeatedly, install new dependencies silently, or replace historical success claims with invented fresh ones. Use the two available models for meaningful focused coverage and identify unverified scope.

Store reproducible before/after outputs for representative Ranked/Trophy Road inputs: legality, generated deck keys/order, objectives, estimated wins/intervals, archetypes and swaps. Existing engine calculations must remain identical within established tolerances. Run 2 adds a selector; it does not change these old outputs. Independent expected fixtures may be added; original goldens stay read-only.

## Run 1

- R1.1: Valid doctype, lang, viewport; 390/768/1440px layouts and 200% zoom have no page-wide overflow or clipped controls. Dark/light both usable.
- R1.2: Zero, one, three and attempted fourth pick; duplicate base/form choice; incompatible forms; clear; unavailable card. Input remains recoverable and rejection explains the next action.
- R1.3: Rapid mode changes and queued calculations cannot display an old mode's output; valid picks survive; removals are announced.
- R1.4: Refresh/deep links and malformed percent-encoded hash do not crash. Missing packaged model and unknown mode are differentiated; no silent deletion of configured modes.
- R1.5: Zero support means “no exact-deck test records,” not 0% wins. Intervals overlapping 50% mean no clear modeled edge, not proven equality. Style probabilities are not “percent sure.”
- R1.6: No numeric/generated recommendation changes against captured baseline. Keyboard/touch access to help and recovery; failed clipboard access offers readable copy text.

## Run 2

- R2.1: Every observed result belongs to the declared pool, matches all exact selected forms, passes existing legality/unlock checks, and has correctly scoped appearance counts.
- R2.2: Independent hand-constructed candidate fixtures verify ranking/ties/diversity and preservation of locked picks; Python and JS agree. Score fixtures reuse unchanged score functions, but expected selector order is independently calculated.
- R2.3: Empty pool, insufficient diverse results and no observed match have explicit states. No padding with fabricated decks; generated fallback requires a visible user choice.
- R2.4: Generated engine outputs match baseline exactly; generated cards are never labeled observed simply because some component cards have evidence.
- R2.5: Current mode/picks survive toggling sources, refresh and Explain/back navigation. Missing matchup/pool data does not break the generated path.
- R2.6: Support and all warnings remain accessible; absence from a capped pool is not equated with fewer than five appearances.

## Run 3

- R3.1: Explain supports empty/malformed deck link, ordinary deck and warned deck. Existing sections and analysis remain available after reorganizing.
- R3.2: Apply/Undo preserves selected cards and restores prior deck, URL and evidence; warnings recompute. Ordinary, embedding and tech-swap eligibility remain unchanged.
- R3.3: Displayed score decomposition sums in a consistent scale; percentage-point changes and composite score points have different labels.
- R3.4: Style, partial-card and exact-opponent searches show correct populations; empty target set and zero/small record denominators are handled. Style records are not described as exact-matchup records.
- R3.5: Retrospective labels and unseen-player distinctions match actual data flow; no new evaluation or training behavior.
- R3.6: Disclosures, controls and retained 3D tools have keyboard access or equivalent data alternatives; focus is preserved. Overview gives roles, major warning and available next action before technical tables.

## Run 4

- R4.1: Softmax worked scores match actual exported features/coefficients and Engine.predictArchetype(). Probabilities sum to one within 1e-9; max-subtraction is stable; uncertain threshold and Hybrid class remain distinct. No inference temperature added.
- R4.2: Sigmoid example matches engine output; styles, win estimates and usage forecasts never share misleading labels or units.
- R4.3: Test shown/blocked/not_better forecast states using isolated test fixtures, not edited exports. Period versus season states remain independent. UI uses exported settings, not hardcoded run counts.
- R4.4: Coverage summary uses sum(coverage × scored forms)/sum(scored forms), handles zero denominators, and identifies it as historical card-period coverage. MAE advantage is not called statistical significance. Bands/points use correct labels.
- R4.5: Generator branches reflect chosen model, interval method and forecast status. Missing inputs block regeneration, not justify invented DOCX content. Generated outputs, when possible, receive rendered inspection.
- R4.6: Final cross-page regression, preserved deep links, both themes, keyboard/zoom and recorded visual comparison. A newcomer heuristic walkthrough can explain deck purpose, support/weakness, sigmoid versus softmax versus Monte Carlo. Do not call this actual user research.
