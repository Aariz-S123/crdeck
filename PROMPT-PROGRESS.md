# crdeck redesign progress

Controller: `docs/claude-redesign/START-HERE.md` (with FINDINGS.md, ACCEPTANCE.md, MATH-CONTENT.md).
Authorization (user, 2026-10-29): preflight, then Runs 1–4 in order without pausing between runs; scope
boundaries, protected files, validation and blocker rules still apply. Local commits only, no push.

## Current state

- Active run: **none: Runs 1–5 complete** (Run 5's final rules sweep: see "Run 5 after")
- Run 1: **PASS** (all P0 items; P1 newcomer definitions done)
- Run 2: **PASS** (all P0 items; comparison view is P2 backlog, not started)
- Run 3: **PASS** (P0 items and P1 three-layer disclosures; new evaluation methods are backlog)
- Run 4: **PASS** (P0 items; P1 forecast quantile visual deferred: the export has no forecast rows to draw, see below)
- Run 5: **PASS** (user, 2026-10-29: "Carefully reread what was mentioned in the revamp spec and implement all of them"): every item Runs 1–4 deferred, from START-HERE, BACKLOG.md and the original monolithic prompt (`Downloads/Claude-Code-crdeck-Redesign-Prompt.md`, which START-HERE replaced), including the forward counter check. Not done: card imagery (no approved image source; the runs' rule is no image dependency) and the combined retrain design (needs retraining). See "Run 5" below.
- Starting HEAD: `9b3ab4da2f7d30845ca8938d9891256ec7a59b51` (main, "Docs: final Trophy Road counter backtest numbers")
- Working-tree changes already present: none except the untracked prompt pack `docs/claude-redesign/` (extracted 2026-10-29 from `Downloads/crdeck-claude-prompt-pack.zip`, the only copy, all five files)
- Inputs: REVIEW.md is not in the repository (it lives at `C:\Users\simty\crdeck-review\REVIEW.md`; read only as claims; its "no softmax" statement is wrong, see finding 1). `docs/crdeck-documentation.docx` is in the repository.
- This is the full local project, not the review ZIP: all 44 mode models (`web/models/`) and 44 per-mode goldens (`web/golden/`) are present, so parity, sweep, page and site checks can run for real.

## Run 1 plan (preflight checkpoint)

Checklist:
1. index.html: valid document shell (doctype, `<html lang="en">`, head/body, `<meta name="viewport">`). No scoring change.
2. Builder intro: one sentence on what a deck is and the 0–3 picks; optional "New to Clash Royale?" disclosure with short definitions (card, deck, elixir, win condition, card forms and slots, game mode), slot facts read from `E.m.rules` and availability, not hardcoded.
3. Wording: "strongest decks it can find" → "highest-scoring options under this model"; "style guess N% sure" → "Predicted style: X" (probability moved to a disclosure, labelled as the classifier's label probability); `UI.verdict` "Wins more than it loses / Loses more than it wins / About even" → "Model estimate above 50% / below 50% / Range includes 50%: no clear modeled edge"; "Learn from" → "Game mode" with a note that it picks the battle data and unlock rules, not your account.
4. Support beside every builder estimate: exact-deck test record ("no exact-deck test records" when 0, never 0% wins), appearances in this mode's collected battles, and the estimate's population (sampled opponent decks from the test window, equal rating). Warnings stay visible; "Passes every deck check" no longer reads as a quality claim.
5. Error states in common.js: distinguish missing model file (HTTP 404), unknown/too-small mode in link, malformed link, and real failure; keep raw messages in a developer `<details>`; offer Retry / choose another mode. No configured mode is removed.
6. Safety: `readHash` survives malformed percent-encoding; stale mode loads cannot render over a newer choice (load version guard); delayed builder runs are cancelled or ignored when picks/mode changed.
7. Picks: a removed or reformed pick is announced in a status region; fourth pick, duplicate base/form and incompatible forms keep input and explain the next step (existing behaviour kept, wording checked).
8. Clipboard failure shows the card list in a selectable field instead of only "Copy blocked".
9. Keep both themes; touch targets for new controls ≥ 44 px; help usable by keyboard and touch (`<details>`, no hover-only).
10. Checks: engine snapshot before/after identical; existing page_test, site_check, check_web_engine, pytest; new focused jsdom test for Run 1 cases; screenshots + layout measurements after.

Proposed files (application): `web/index.html`, `web/common.js`, `web/app.css`, `web/reason.html` (verdict/"best version"/support wording only). Possibly `web/counters.html` only if a shared-wording change surfaces there (no counters redesign in Run 1). Tests/evidence: `tests/web/run1_test.cjs` (new), `docs/claude-redesign/evidence/**`. Estimated well under 12 files / 800 changed lines.

Protected-file risks: none planned. `web/engine.js` is untouched in Run 1; no protected export, config, model or pipeline file is edited; nothing is retrained or exported.

## Run 2 plan (starting HEAD 70a9c94)

Checklist:
1. `web/observed.js` (new, global `CRObserved`, also `module.exports`): pure `select(rows, seedKeys, nResults, minDiff)` (exact selected forms; sort by −tie(objective) then deck key; greedy diversity identical to `Engine.complete`: each pick differs from every earlier one by ≥ min_diff card ids) and `observedDecks(E, seeds)` building rows from `E.counterPool()` with `E.evaluate().objective`, re-checking `checkDeck` and `isAvailable`, and returning an explicit state: `no_pool`, `hero_unobservable`, `no_match`, `few`, `ok`.
2. `src/crdeck/counters.py`: additive `observed_decks(pool, objectives, seeds, n_results, min_diff)` with the same rules (post-training file, excluded from the cache fingerprint; no change to existing functions).
3. Shared fixture `tests/fixtures/observed_selector.json` (hand-built candidates, objectives, seeds, expected order computed by hand, ties and diversity cases); `tests/test_observed.py` (Python) and `tests/web/run2_test.cjs` (JS) both run it; JS test also checks real Ranked/Trophy Road results: pool membership, exact forms, legality/unlocks, diversity, counts scope, generated path unchanged vs engine snapshot.
4. Builder: source choice "Observed decks" (default when the mode exports a pool) / "Generated decks — experimental" (existing `E.complete`, unchanged). No silent switching: an empty observed result shows its reason plus an explicit "Show generated decks" button.
5. Observed card: "Observed deck" tag with train+validation appearance count (not unique players), exact-deck test record and all-window appearances (Run 1), predicted style, all warnings, estimate/range, Explain and Copy. Generated card: "Generated by the model — experimental".
6. Link state: optional 4th hash part `o`/`g` for the source (old links without it still work and default to Observed); reason.html back link keeps it.
7. Wording for pool absence: "not among the N pool decks" never "played fewer than 5 times".
8. Checks: run2_test, test_observed, engine snapshot identical, run1_test, page_test, site_check, check_web_engine, pytest; screenshots.

Files: `web/observed.js` (new), `web/index.html`, `web/common.js` (token/readHash 4th part), `web/reason.html` (back link), `src/crdeck/counters.py` (additive function), tests: `tests/fixtures/observed_selector.json`, `tests/test_observed.py`, `tests/web/run2_test.cjs`. `web/engine.js` not expected to change.

## Run 5 scope (starting HEAD e19ef9b)

Reread: START-HERE.md, ACCEPTANCE.md, FINDINGS.md, MATH-CONTENT.md, BACKLOG.md and the original monolithic prompt in
Downloads. The user's instruction authorizes what the four runs held back ("Do not begin P2", "do not implement
prospective evaluation … in these four runs"). Still in force: protected files and exports, no retraining, no new
dependency, no fabricated results, tests not weakened. Gap inventory (all done unless marked):

1. Navigation: four destinations (Build a deck, Find counters, Explore trends, How it works), Explore sub-menu with usage trends, season readiness and All cards; old routes kept; contextual card links to All cards.
2. Mode bar: sort order, usable-group count, battle windows and the train/tune/test split behind "About these battles"; mode, group and freshness stay visible.
3. Builder picker: Clear picks; Try an example (the mode's most-played usable card form, labelled as an example); visible type definitions; Base/EVO/HERO definition from the rules and unlocks; "early" explained in visible text; Clear the search.
4. Builder results: editorial style description (labelled, not model output); "Why it ranks here" (score parts in score points, strongest pair, not causal); comparison view (shared/different cards, elixir, warnings, record, estimates, no winner); selection-optimism note for both sources.
5. Explanation page: layers filled on first open (map last); question chart titles, takeaways, units, "Show as a table" for card weights and calibration; card links; association wording for weights; Beta/Wilson/model range names; map closeness ≠ synergy, projection loses information, tables as the non-3D alternative; percentage points in the nearest-card table; reduced-motion scrolling.
6. Counters: style or cards kept in the link (old links work); "strongest"/"all real decks" labels fixed; every-style-counted-equally row; symbols defined; card links; Clear the search.
7. All cards: name, role, elixir, status, measured games and win rate first; model weights and the user's CSV as separate views with their own provenance and dates.
8. Trends and seasons: forecast picture (observed points, median, 50%/90% bands, no-change line, observed vs forecast region) when the export has forecast rows; table versions of the charts; quiet lookup status instead of a live region; dated "most-played decks"; no "unlocks" wording.
9. How it works: one five-step story; glossary with synergy vs lift, regularization, splits, beam search, bootstrap, delta method, Wilson, logit/sigmoid, selection optimism, with current-data examples; loss-surface symbols defined; slice and illustration labels; glossary links.
10. Shared: Escape hides tooltips; scrolling tables get a name and tab stop; 44 px small buttons; 75-character measure; consolidated picker styles; one light-theme contrast fix.
11. Forward counter check (BACKLOG 1, 2, 4): design committed first (1131921, `docs/claude-redesign/EVAL-DESIGN.md`), then code, tests, results and page.
12. Not done: card imagery (decision for the user), combined retrain design (BACKLOG 3; needs retraining), two-way clustering.

## Source-of-truth mappings

| Displayed quantity | Source field/computation | Unit | Population/window | Interval method | Limitations |
|---|---|---|---|---|---|
| Builder/Explain "estimated win rate" | `Engine.score` → `explain().score.meta_win_prob` = mean over `scorer.opp_u` of σ(u − u_o) | probability (%) | 2,000 opponent deck appearances sampled (seed) from the mode's **test window**; equal player rating | `score.interval`: 90% normal approx., sd = hypot(delta-method sd from `strength.cov`, opponent-sampling sd) | model estimate; selection optimism of the search not covered; opponent sample is from the evaluation window |
| Deck score / objective | `evaluate().objective` = win_prob + 0.5·mean synergy + 0.05·mean log-lift (`config.search`) | composite score (not a probability) | as above + training synergy/lift | none | ranking quantity only |
| Exact-deck test record | `test_deck_records[key]` = [battles, wins] | count | this mode's test window, deck sides | none shown | 0 = no records in that window, not 0% wins, not "never played" |
| Deck appearances | `deck_appearances[key]` (`side_rows(mb)`) | count of deck sides | all usable battles of this mode, all windows | – | not unique players; absent key = not in this mode's collected battles |
| Predicted style | `predictArchetype` softmax over 8 classes, threshold `archetype.threshold` (0.5) → else "Mixed style" (UNCERTAIN) | label; probability of label | classifier fit on hand labels | none | label probability, not certainty or win chance; Hybrid class ≠ below-threshold fallback |
| Warnings | `structuralWarnings` (`config.warnings`) | rule | deck composition | – | advisory, not illegality |
| Card games (picker) | `forms[].games` | games | this mode | – | – |
| Facts bar | `entry.ok_battles`, count of `deck_appearances` keys, `meta.counts.last_battle` | count/time | this mode | – | snapshot date shown |
| Counter-deck "played N times" | `matchup.pool[i][1]` | deck appearances | **train + validation** windows | – | capped (3,000) and ≥5 filter; not unique players |
| Counter style record | `matchup.pool[i][2][style]` = [games, wins] | count | test window vs classified style | Wilson in backtest | style-wide, not exact matchup; ranking used test-window opponent mix (retrospective) |
| Forecast (meta) | `modes.json.meta` status/backtest/forecast/settings | share points | collection periods | Monte Carlo 50/90% bands | Run 4 |

## Decisions and scope

- Screenshots: Chrome headless via DevTools protocol (`docs/claude-redesign/evidence/shots.mjs`, Node 22 built-in WebSocket, no new dependency) with real mobile emulation and explicit `prefers-color-scheme`. Plain `--screenshot` was rejected: Windows dark theme leaked into "light" shots and desktop Chrome cannot make a 390 px window.
- Six views per run, chosen before editing: builder and deck explanation × desktop light 1440 / mobile light 390 / mobile dark 390. Extra layout-only checks: 768, 200% zoom, desktop dark.

## Completed changes

### Run 1 (web/index.html, web/common.js, web/app.css, web/reason.html; tests/web/run1_test.cjs)
- index.html: doctype, `<html lang="en">`, head/body, responsive viewport meta (the claude meta tag kept alongside).
- Builder intro states the 8-card deck and 0–3 picks; "New to Clash Royale? Six terms" disclosure (card, deck, elixir, win condition, forms and slots, game mode). Deck size, slot rules and champion limit are read from `model.rules`/availability; win-condition examples from the card table.
- Wording: "strongest decks it can find" → "highest-scoring options under this model"; "style guess N% sure" → heading "Predicted style: X" with the classifier probability explained in a disclosure (label probability, not win chance or certainty; below-threshold case named as no style reaching the threshold); verdict pills → "Model estimate above 50%" / "below 50%" / "Range includes 50%: no clear modeled edge"; "Learn from" → "Game mode" + note that it selects battle data/unlocks, not the user's account; "already found its best version" → local-search statement; "Passes every deck check" → "No deck-check warnings"; builder footer no longer says estimates describe "top players".
- Each builder deck: warnings first, then exact-deck test record ("No exact-deck test records … (window)" when 0), appearances in this mode's collected battles, then "Estimated wins against sampled opponents" with "90% model range" and the opponent population (2,000 sampled test-window decks, equal rating). One results-level note on selection optimism and that the model does not play the game. Headline number reduced from 2rem to 1.625rem.
- common.js: `readHash` survives malformed percent-encoding and counts unreadable card codes (page notes "Part of this link couldn't be read"); `LoadError` kinds (missing / network / bad_data); `failed()` gives a plain message, a next step, Retry, and the raw message under "Technical details"; missing modes.json vs missing model file vs drawing error are distinct; the mode bar is drawn before loading so another mode can be chosen after a failure; a load-sequence guard drops stale mode loads; render errors no longer say "data files did not load". No configured mode is removed.
- Builder: build-number guard so delayed builds for old picks/modes are ignored; errors keep picks and explain; clipboard failure shows the list selected in a field.
- app.css: nav links, chips, selects, buttons and disclosure summaries ≥ 44 px tall; styles for the glossary, mode note and technical details.
- Mobile: "See the suggested decks ↓" button (≤ 920 px).

### Run 2 (web/observed.js new; web/index.html, web/common.js, web/reason.html; src/crdeck/counters.py additive; tests)
- **Policy change (the only one authorized):** the builder shows **Observed decks** by default when the mode exports a real-deck pool, and **Generated decks · experimental** (the unchanged beam search, `Engine.complete`) on request. Observed = decks of `matchup.pool` (played ≥ `pool_min_battles` times in train+valid, legal and unlocked; capped by the export) that contain every picked card form, re-checked with `checkDeck`/`isAvailable`, ranked by the builder's objective `evaluate().objective` at 1e-10 precision then deck key, thinned with `min_diff_cards` exactly like `Engine.complete`; `n_results` from config. Python twin `crdeck.counters.observed_decks`.
- States: `no_pool`, `hero_unobservable`, `no_match`, `few` (never padded) each have a message and an explicit "Show generated decks · experimental" button; no silent switching. Pool-absence text says the deck "may still have been played", never "fewer than 5".
- Deck cards carry a provenance tag ("Observed deck" with "N appearances in this mode's training battles (training and validation windows) … uses, not players" / "Generated by the model · experimental"), plus Run 1's warnings, exact-deck test record, appearances, style and estimate.
- Links: optional 4th hash part `g` only for Generated; Observed links are unchanged from before, so old links and the existing test regexes still hold. reason.html keeps the source in its own hash and its back link.
- Picks are validated (`checkPartial`) before the pool search, giving the same refusals as before.
- Test harness change: page_test.cjs, site_check.cjs and run1_test.cjs now inline `observed.js` like engine.js/common.js (no assertion changed). run1_test pins `~g` where it compares the builder with `Engine.complete`, because Observed is now the default.
- Engine untouched: `web/engine.js` not edited; engine snapshot identical to the Run 1 baseline.

### Run 3 (web/reason.html, web/counters.html, web/app.css; docs/model-notes.md one sentence; docs/claude-redesign/BACKLOG.md; tests/web/run3_test.cjs)
- reason.html: new "At a glance" overview right after the deck and short version: roles from the hand-made card labels (win condition, spells, air defense, answers to tanks, tanks, average elixir), up to three major warnings with the rest behind "N more", and "Best next step": the highest-scoring eligible score swap (locks respected) with before/after score points, estimated wins in percentage points, warnings added/removed, the new deck's evidence (test record and appearances), Apply, and Undo (always shown after a swap). If no swap raises the score it says so as a local check. Below: three `<details>` layers "All score swaps", "Evidence" (charts, pairs, deck checks, data quality) and "Math and model details" (score formula, card map in 3D). All existing analysis is still rendered; layer open state survives a swap. Swap rows now say "score … pts · est. wins … pp"; swap math ends in "score points"; score called a ranking number, not a probability. Whole-page `aria-live` removed; a small status line announces swaps; focus moves to the overview heading after Apply/Undo. Card-map and counter tech swaps named as different rules.
- counters.html: order is now opponent choice → evidence-status line → results → trust check. One-sentence plain-language style descriptions (marked "not model output"). Partial cards vs exact 8-card opponent explained with the real `opponents_per_set`. Labels: "estimate vs X" / "general estimate vs sampled field" / measured "won N of M vs Style decks in the later battles" (style-wide; "(few games)" under 30; "no record, not zero wins"). Counter-card effects described as learned patterns, not one-on-one fights; "percentage points" units. Tech-swap text: in the pool with its count, or "isn't among this mode's N pool decks … may still have been played". Trust check: labelled retrospective with the reason (test-window opponent mix), "highest-scoring general decks", "all eligible pool decks", "only players who don't appear in the training battles (models not retrained)" vs "models retrained without any player…", tables in a disclosure, no difference interval claimed. Errors keep the choice and hide raw text under technical details; real clipboard fallback; footer no longer says "top-player battles".
- app.css: every `details.more` and `details.layer` shows ▸/▾ (flex summaries had lost the browser marker on all pages).
- docs/model-notes.md §17: "only makes it wider" replaced with the dependence caveat and the retrospective note.
- docs/claude-redesign/BACKLOG.md: prospective evaluation, dependence-aware intervals, the two new-player checks, style-mixture confounding; P2 product items.
- No math, ranking, export or engine change (snapshot identical).

### Run 4 (web/learn.js new; web/model.html, web/meta.html, web/seasons.html, web/common.js nav labels; scripts/doc_claims.py new, scripts/make_docs.py; docs/crdeck-documentation.docx regenerated; tests)
- `web/learn.js` (global `CRLearn`): `softmaxTable` (same arithmetic as `Engine.predictArchetype`, from `archetypeFeatures`), `sigmoidExample` (one sampled opponent decoded from `scorer.opp_rows`, plus the mean over all, which equals `Engine.score`), `forecastSummary` (state incl. shown-but-empty, mean MAE MC vs no change, periods better, coverage = Σ coverage × forms / Σ forms, null when nothing scored).
- How it works: new section "Three models, three questions": sigmoid / softmax / Monte Carlo, each a short plain explanation with a worked example from a real deck of the current mode (first observed deck) in a disclosure: sigmoid z, probability, average over 2,000 sampled opponents, interval method named (delta method + opponent sampling; not bootstrap or Wilson); softmax table for all 8 classes (raw score, e^(z−max), probability), threshold result, Hybrid vs Mixed fallback, held-out label check, no temperature; Monte Carlo definition of share and period, one run, settings from the export, real state, coverage vs nominal, MAE gate not significance, the six steps incl. √games weighting and backtest vs live next_n, caveats. Side-by-side contrast list. Stale wording fixed: "battles of top players", "Win rates describe top players", "% confidence", glossary entries (90% range methods, percentage points, AUC, log loss, calibration, association, score points).
- Card usage trends (meta.html): renamed; "meta" defined; three parts: Observed history (headline ≤3 changes, only when both periods have ≥ settings.min_games appearances and the 90% range clears zero; tiny-period warning), "Look up a card" search that draws history on demand, Experimental next-period forecast (true state incl. "nothing to forecast right now", exported settings, coverage notice, per-period table with dates/battles/forms/errors/coverage, n/a when nothing scored), Season readiness pointer. Raw backtest table replaced by the labelled one.
- Season readiness (seasons.html): renamed; says no next-season prediction is built; removed "Ready to backtest"/"When it unlocks" implications.
- Nav: "Meta" → "Usage trends", "Next season" → "Season readiness" (page_test's menu-link check updated to the new label, same assertion).
- Docs generator: `scripts/doc_claims.py` (deck interval method, model choice from the exported name, edge wording from the interval, page count, forecast status for blocked / not_better / shown / shown-but-empty with weighted coverage); `make_docs.py` uses it and fixes counters wording (highest-scoring general decks, eligible pool decks, retrospective, unseen-player row is not a retrain) and the page list. DOCX regenerated (python-docx from the session's local copy) and its text inspected.
- Documentation (user request, 2026-10-29): README website table, helper files, link format, redesign tests and a redesign pointer; docs/model-notes.md §4 (opponent part of the deck range is the analytic standard error, not a bootstrap), §9 (observed/generated policy, redesign record), §12 (stale "with 2 periods it is not shown" replaced with the current state, gate wording, backtest vs live size), §14 renamed Season readiness without the automatic-prediction implication; Word page table updated for the builder, explanation and counters; DOCX regenerated again and its text checked (all new sentences present, no stale claim).
- Findings confirmed in Run 4 preflight: the export's forecast is "shown" yet empty (P8 has 23 battles after an interrupted collection, below min_games 200); the only backtest period where the forecast beat no change is that 23-battle period; weighted coverage 45.9% (per period 34–85%).

### Run 5 (web/common.js, app.css, index.html, reason.html, counters.html, cards.html, meta.html, seasons.html, model.html; src/crdeck/counters.py additive; scripts/counter_eval.py, doc_claims.py, make_docs.py; web/counter_eval.json; tests; docs)
- Everything in the Run 5 scope list above, items 1–11. Engine untouched (`web/engine.js` not edited; snapshot identical); no export, model, config or protected file changed; nothing retrained.
- Forward counter check: `crdeck.counters` gained `style_sets`, `window_scorer`, `check_lists`, `test_games`, `memberships`, `paired_bootstrap`, `check_verdict`, `check_version` (post-training file, outside the cache fingerprint); `scripts/counter_eval.py` loads each mode's cached models from the pickle only when its fingerprint matches (never `load_context`, so it cannot retrain) and writes `web/counter_eval.json` (133 KB). All 44 modes ran; in every one the retrospective version reproduces the exported check's counts exactly; forward and retrospective verdicts agree in 43 of 44 (Trophy Road: not shown → better than an average deck, with the population switching to every player because only 26 unseen-player games remain); 38 modes have too few counter games either way. Numbers: docs/model-notes.md §17.
- `counters.py` docstring no longer says the independent-groups difference range "only makes it wider".
- Docs: README (pages, menu, script, tests, test count 183), model-notes §17 (forward check), BACKLOG (what Run 5 closed), Word document regenerated (forward-check paragraph from `doc_claims.forward_check`, website table, a bracket fix) and its text checked; "right now" without a date replaced by "in this export".
- Test changes: page_test, site_check and run3_test open the layers before checking their charts (lazy layers; every assertion kept); page_test's menu label "Counters" → "Find counters". New: `tests/web/run5_test.cjs`, `tests/test_counter_eval.py` (11), 3 doc_claims tests.

Not done in Run 1 (explicitly deferred): "Try an example" action and comparison view (not Run 1 P0); model.html still says "Win rates describe top players" (Run 4 teaching page); counters.html "strongest" wording (Run 3).

## Checks and evidence

Baseline (before any edit), `docs/claude-redesign/evidence/run1-before/`:
- `engine.json`: engine snapshot (Ranked, Trophy Road × no pick / 1 / 3 picks; keys, objectives, estimates, intervals, styles, warnings, support, swaps, embedding swaps; first counter style).
- No-pick Ranked reproduces finding 6: 56.0% [54.1, 57.9] Cycle (p 0.92); 57.1% [55.2, 59.0] Cycle (0.61); 58.2% [56.0, 60.4] below-threshold mixed (0.50); all NO_AIR_DEFENSE, 0 exact-deck test battles, 0 appearances in this mode's battles. No-pick Trophy Road: 87.0–87.2%, all with warnings, 0 exact support.
- `layout.json` + 6 screenshots: builder on a 390 px phone lays out 980 px wide (no viewport meta, no doctype) — finding 7 confirmed; deck explanation fits 390 px (wide tables scroll inside their own boxes). No script errors.

Baseline tests (before edits): pytest 151 passed; check_web_engine "all 137367 checks agree with Python"; page_test `fails: []`; site_check "44 modes x 4 pages + 2 pages + 10 edge links, no problems found". No pre-existing failures.

Run 1 after (`docs/claude-redesign/evidence/run1-after/`):

| Acceptance ID | Exact command/manual action | Result | Evidence |
|---|---|---|---|
| R1.1 | `node docs/claude-redesign/evidence/shots.mjs …/run1-after` and `VIEWS=tablet-light,zoom200-light,desktop-dark …/extra` (Chrome DevTools emulation, cache disabled); run1_test shell check on all 7 pages | PASS | layout.json: builder 390 px wide at 390 (was 980), overflow 0 px at 390/768/1440/200% zoom, light and dark, both pages; all pages have doctype, lang, viewport. Wide tables on reason.html scroll inside their own boxes. |
| R1.2 | `cd tests/web && node run1_test.cjs` | PASS | one pick, three picks, refused 4th, form change, three Evolutions (no slot) kept + explained, clear, locked card in Bone Pit refused with reason |
| R1.3 | run1_test (Trophy Road load delayed 1.5 s, Ranked chosen after) | PASS | Ranked facts and Ranked's exact decks for the kept pick; mutation check: with the guard lines removed the same test fails 3 ways |
| R1.4 | run1_test: `#ranked~~26000021b-zz-%E0%A4%A`, `#no_such_mode~~`, missing `models/trophy_road.json` | PASS | link note + readable pick kept, no script error; "wasn't recognized" note; "model file … isn't in this copy" + Retry + technical details, all 3 mode chips still present, recovery by choosing Ranked |
| R1.5 | run1_test text checks on builder and reason | PASS | no "% sure", "Wins more than it loses", "About even", "strongest decks it can find", "best version"; zero support stated as "No exact-deck test records"; pills match each deck's own range |
| R1.6 | `node docs/claude-redesign/evidence/engine_snapshot.cjs …/run1-after/engine.json` + `cmp` with run1-before; run1_test clipboard rejection | PASS | engine snapshot byte-identical; no-pick decks equal `Engine.complete([])`; blocked clipboard shows the 8-card list selected. Keyboard/touch: help and recovery use native `<details>`/`<button>` (not exercised by a key-press script). |
| regression | `.venv/Scripts/python -m pytest -q`; `node scripts/check_web_engine.mjs`; `node page_test.cjs`; `node site_check.cjs` | PASS | 151 passed; 137,367 checks agree; `fails: []`; no problems found (44 modes) |

Run 2 after (`docs/claude-redesign/evidence/run2-after/`):

| Acceptance ID | Exact command/manual action | Result | Evidence |
|---|---|---|---|
| R2.1 | `cd tests/web && node run2_test.cjs` (real Ranked, Trophy Road, Goblin Stadium × no pick / most-played pick / an Evolution pick / three picks) | PASS | every observed deck in the exported pool, holds the exact picked forms, legal and unlocked, count equals the pool's train+valid count, objective equals `E.evaluate`; UI text scopes counts as training-window uses, not players |
| R2.2 | `.venv/Scripts/python -m pytest tests/test_observed.py` and run2_test fixture section on `tests/fixtures/observed_selector.json` | PASS | 6 hand-worked cases (ties with float noise, same card ids in different forms, diversity, min_diff 1 vs 2, no match, no seeds) agree in Python and JS |
| R2.3 | run2_test: Electro Dragon + Goblin Machine in Ranked (no pool deck), Knight (Evolution) in Master III (2 decks), Ranked served without `matchup` | PASS | explicit no-match / "Only 2 pool decks hold …, nothing was added" / "no real-deck pool" states; no padding; generated only after pressing the button |
| R2.4 | run2_test toggle + engine snapshot `cmp` with run1-before | PASS | generated decks equal `Engine.complete`, all tagged "Generated by the model · experimental"; snapshot identical |
| R2.5 | run2_test: `#ranked~~28000015b~g` → Explain link → reason back link; old link `#ranked~~28000015b`; no-pool export | PASS | `…~28000015b~g` kept through Explain and back; old link opens observed decks with the pick; generated path works without a pool |
| R2.6 | run2_test text checks | PASS | warnings and support shown on every observed card; pool absence "may still have been played", no "fewer than" |
| regression | pytest; check_web_engine; run1_test; page_test; site_check | PASS | 159 passed; 137,367 checks agree; `fails: []` ×2; 44 modes no problems |
| visual | `node docs/claude-redesign/evidence/shots.mjs …/run2-after` (+ `states/`: no-match, generated) | PASS | overflow 0 px at 390/1440 in light and dark for builder, reason, no-match and generated views |

Run 3 after (`docs/claude-redesign/evidence/run3-after/`):

| Acceptance ID | Exact command/manual action | Result | Evidence |
|---|---|---|---|
| R3.1 | `cd tests/web && node run3_test.cjs` | PASS | empty link and `#ranked~1b-2b~` handled; warned no-pick deck shows overview + all 7 section headings, ≥4 charts, 3D map |
| R3.2 | run3_test: best swap on a pool deck with 2 locked picks, Apply then Undo | PASS | picks kept and still in the deck, hash restored by Undo, overview warnings recomputed; score/card-map swap lists equal `Engine.swaps`/`embeddingSwaps` |
| R3.3 | run3_test parses every swap's math line | PASS | three parts sum to the total within rounding, in "score points"; rows say "pts" and "pp" |
| R3.4 | run3_test counters: style, partial cards, exact 8-card deck, two cards with no shared deck | PASS | order opponent → results → trust check; editorial style line; target vs field estimate labels; style-wide record wording; "this exact deck"; no style record shown for exact decks; empty opponent set explained |
| R3.5 | run3_test verdict text | PASS | "retrospective" with reason; unseen-player row vs retrained row named apart; no "only makes it wider"/"strongest decks" |
| R3.6 | run3_test + screenshots | PASS | overview before 3 layers; native details; map tabindex 0; no page-wide live region; focus to overview heading after Apply |
| regression | pytest; check_web_engine; run1/run2_test; page_test; site_check; engine snapshot `cmp` | PASS | 159 passed; 137,367 agree; all `fails: []`; 44 modes no problems; snapshot identical |
| visual | `shots.mjs` reason + counters ×3 views | PASS | 0 px overflow; disclosure arrows visible; dark mode readable |

Run 4 after (`docs/claude-redesign/evidence/run4-after/`), the final full run:

| Acceptance ID | Exact command/manual action | Result | Evidence |
|---|---|---|---|
| R4.1 | `cd tests/web && node run4_test.cjs` | PASS | softmax table equals `predictArchetype` on 18 real decks in Ranked, Trophy Road and Master III (both threshold fallbacks and confident labels); sums to 1 within 1e-9; +1000 on every intercept changes nothing; feature count 135 = 123 + 9 + 3 from the export; no temperature parameter |
| R4.2 | run4_test | PASS | sigmoid example mean equals `Engine.score`; the page's worked average equals the deck's estimate; interval named delta method + opponent sampling; styles, wins and usage worded apart |
| R4.3 | run4_test with blocked / not_better / shown (runs set to 1,234) / shown-but-empty fixtures served in place of modes.json | PASS | each state worded correctly; the exported run count is used; season readiness separate and stated as not built |
| R4.4 | run4_test + hand-made fixture | PASS | coverage weighted by card forms scored (0.7 on the fixture); zero denominators give no coverage and n/a cells; "not 90%" and "not a significance test" shown |
| R4.5 | `python -m pytest tests/test_doc_claims.py`; `PYTHONPATH=<local python-docx> python scripts/make_docs.py`; text check of the DOCX | PASS | 10 branch tests; DOCX regenerated and inspected: new sentences present, stale claims ("a bootstrap gives…", "five-page", "cards only at C", "stays hidden", "strongest decks overall", "top ranked players") gone |
| R4.6 | full suite: pytest; check_web_engine; run1–run4 tests; page_test; site_check; `node scripts/sweep_web_engine.mjs`; engine snapshot `cmp`; screenshots | PASS | 169 passed; 137,367 checks agree; all `fails: []`; 44 modes no problems; sweep 16,905 searches and 150,141 swaps, no problems (7,816 s); snapshot identical to the pre-redesign baseline; 0 px overflow on How it works, Usage trends and Season readiness at 390 and 1440, light and dark (before shots from commit 4787d0e in run4-before/) |

Newcomer walkthrough (heuristic, not user research): from the builder a first-time reader sees what a deck is and what the picks do, gets three observed decks with their main weakness first, can tell the measured test record from the model estimate (tags and wording), opens one deck to see roles, warnings and the best next step, and on How it works can read in order that the sigmoid gives win estimates, softmax gives style-label probabilities, and Monte Carlo gives next-period usage shares, each with real numbers.

Run 5 after (`docs/claude-redesign/evidence/run5-after/`):

| Acceptance ID | Exact command/manual action | Result | Evidence |
|---|---|---|---|
| R5.1 navigation | `cd tests/web && node run5_test.cjs`; `node page_test.cjs` | PASS | four destinations in order; Explore sub-menu on its three pages with the page and section marked; menu label checks |
| R5.2 picker | run5_test | PASS | type definition follows the filter; form definition from the rules (Ranked) and unlocks (Bone Pit: base only); example = most-played usable card form recomputed from `strength.feature_games`, in the link; Clear picks clears, announces, resets the link; Clear the search restores 184 forms; "early" explained |
| R5.3 builder results | run5_test | PASS | style description matches each deck's label and is marked editorial; "Why it ranks here" parts add up (±0.02) and equal the engine; strongest pair named with its caveat; comparison's shared cards and estimates recomputed from the deck links; no winner named; first pill is still the estimate verdict |
| R5.4 explanation | run5_test; run3_test; page_test | PASS | layers empty until opened, map not drawn until its layer opens; table versions (8 weights, all calibration bins) with card links; takeaway names the top-weight card; Beta range named; pp in the nearest-card table; reduced motion gives non-smooth scrolling |
| R5.5 counters | run5_test | PASS | `#ranked~~~~Siege` selects Siege; style and card choices written to and restored from the link; old `#ranked` works; equal-weight row equals a recomputation from the export (styles with ≥ 30 games in every group); no old labels; card links |
| R5.6 All cards | run5_test; page_test; site_check | PASS | default columns Card, Role, Elixir, Status, Games, Real win rate; 187 rows in every view; model and CSV views with their provenance; `cards.html#ranked~~26000021b` opens on Hog Rider |
| R5.7 trends and seasons | run5_test (forecast fixture served in place of modes.json; file on disk untouched) | PASS | 6 forecast cells with no-change lines, region labels and a table version; live export: no picture, 7 charts as before; lookup announces a short status, no live region; seasons dated, no "right now", no "unlocks" |
| R5.8 How it works | run5_test | PASS | five-step story; 14 glossary terms present; regularization example = selected C from the log; split counts from the export; N and C from the landscape slice |
| R5.9 shared and accessibility | run5_test; `node docs/claude-redesign/evidence/keys.mjs …/keys.json` (real Tab presses in Chrome); contrast of token pairs; `OPEN_DETAILS=1 VIEWS=mobile-light,desktop-dark,zoom200-light,tablet-light node …/shots.mjs` on all 7 pages | PASS | Escape hides tooltips; a scrolling table box gets role, name and tab stop; small buttons 44 px; keyboard: every focus stop on all 7 pages shows a focus indicator, no trap, Shift+Tab steps back; contrast: dark theme ≥ 5.78:1, light ≥ 4.5:1 after `--wild` #0b7a6d → #0a766a (was 4.45:1); 0 px overflow and no script errors on 28 views with every disclosure open, incl. 200% zoom on every page |
| R5.10 forward check | `pytest tests/test_counter_eval.py`; `python scripts/counter_eval.py` (all modes); run5_test | PASS | design committed first (1131921); 11 tests (paired groups give exactly 0, hand-computed rates, clustering widens ranges when players repeat, fixed seed, inclusion rule, membership, verdict words, counting equals `deck_records`, retrospective equals `backtest`, forward inputs only from the validation window, script never trains); 44 of 44 modes match the export; page shows it with a copy-without-file fallback |
| regression | `.venv/Scripts/python -m pytest`; `node scripts/check_web_engine.mjs`; run1–run5 tests; page_test; site_check; engine snapshot `cmp` with run1-before | PASS | 183 passed; all 137,367 checks agree; all `fails: []`; 44 modes x 4 pages + 2 pages + 10 edge links, no problems; engine snapshot identical to the pre-redesign baseline |
| regression, rules sweep | `node scripts/sweep_web_engine.mjs` | see below | started before the checkpoint commits; its result is recorded below when it finishes |

Screenshots (local only, git-ignored): `docs/claude-redesign/evidence/run1-before/*.png`, `run1-after/*.png`, `run1-after/extra/*.png`.

## Checkpoints

- Run 1 start: HEAD 9b3ab4d. Changed: web/app.css, web/common.js, web/index.html, web/reason.html (207+/69−); new tests/web/run1_test.cjs; PROMPT-PROGRESS.md; docs/claude-redesign/** (prompt pack + evidence).

- Run 2 start: HEAD 70a9c94 (Run 1 commit). Changed: web/observed.js (new), web/index.html, web/common.js, web/reason.html, src/crdeck/counters.py (additive `observed_decks`); tests: tests/fixtures/observed_selector.json, tests/test_observed.py, tests/web/run2_test.cjs (new), tests/web/run1_test.cjs, page_test.cjs, site_check.cjs (inline observed.js).

- Run 3 start: HEAD d060f8b (Run 2 commit). Changed: web/reason.html, web/counters.html, web/app.css, docs/model-notes.md (one sentence), docs/claude-redesign/BACKLOG.md (new), tests/web/run3_test.cjs (new).

- Run 5 start: HEAD e19ef9b (Run 4 commit). Checkpoints: 1131921 (forward-check design only, before any result), then the forward check (src/crdeck/counters.py additive, scripts/counter_eval.py, tests/test_counter_eval.py, web/counter_eval.json), then the site, tests, docs and evidence. Size: 10 application files, +730/−177 lines in all; split across the two code commits so each stays under the 12-file / 800-line review boundary.

- Run 4 start: HEAD 4787d0e (Run 3 commit). Changed: web/learn.js (new), web/model.html, web/meta.html, web/seasons.html, web/common.js; scripts/doc_claims.py (new), scripts/make_docs.py, docs/crdeck-documentation.docx; README.md, docs/model-notes.md; tests: tests/web/run4_test.cjs, tests/test_doc_claims.py (new), tests/web/page_test.cjs (menu label + inline learn.js), tests/web/site_check.cjs (inline learn.js).

## Blockers

None for Run 1. Note for later runs: a new top-level `src/crdeck/*.py` would change the training-cache fingerprint (pipeline.py hashes every top-level .py except counters.py/counters.yaml), so Run 2's Python helper goes in `src/crdeck/counters.py`.

## Remaining limitations

- Card imagery is not added: the repository has no card images and no image source is approved (the raw API responses hold icon URLs on Supercell's server, but hotlinking or copying them is the user's call). Cards keep their text names.
- The forecast picture is drawn only when the export has forecast rows; the current export has none (the latest period has 23 battles), so the live page explains that instead. It was checked with a fixture.
- The forward counter check uses the validation window for its inputs and one-way player clustering; two-way clustering and the combined retrain design (BACKLOG item 3) are not done. The exported retrospective check stays as exported and is shown next to the forward one.
- The builder still takes 0–3 picks, as every version of the spec says ("pick up to three cards"); the user's question about picking 8 cards is a separate decision.
- The shared Artifact copy of the site was not republished (not asked); it predates Run 5.
- Screenshots stay local (git-ignored).

## Next exact action

None. Runs 1–5 are done and committed (no push). Open decisions for the user: card imagery source, an 8-card "check my own deck" entry, and whether to republish the shared Artifact. A fresh daily collection would give the forecast a normal-sized latest period.
