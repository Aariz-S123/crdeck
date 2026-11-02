# crdeck: Clash Royale ML deck builder

A personal deck-building assistant. Give it 0–8 cards (all 8 checks a deck you already play) and it returns legal 8-card decks with an archetype, an estimated win rate (with sample size and uncertainty), synergy evidence, advisory warnings and swap suggestions, all learned from top-player battles collected through the official API. Spec: [docs/spec.md](docs/spec.md).

Learning project; not affiliated with Supercell. It does not find "the best deck." Win rates describe top-player battles in the sampled window, not your games, and synergy scores are correlations, not proven combos.

## Status

All spec phases (section 11, 1–7) are done on real data.

| Phase | State |
| --- | --- |
| 1. Gate | Done. Real `/cards`, leaderboard and battle log observed ([docs/api-notes.md](docs/api-notes.md)). Card table: 123 deck cards, all matched to the API (`v2-api-confirmed`) |
| 2. Rules | Done. 22 legality tests; slot rules checked against 2,613 real ranked decks (two champions allowed, champions can go Wild) |
| 3. Data | Done. 2,894 top Path of Legends players (global top 1000 + top 200 of 12 countries), 80,365 deduplicated battles, 58,179 usable ranked battles |
| 4. Baselines | Done. 50%, popularity and rating-only baselines, time split |
| 5. Models | Done. Synergy, skill-controlled strength, archetype (108 labeled real decks, 20 held out) |
| 6. Search | Done. Completion, swaps, explanations |
| 7. Demo | Done. `notebooks/07_demo.ipynb`: Hog Rider → three legal Hog–Earthquake cycle decks with full explanations |

219 tests pass (`pytest`, 2026-11-02). All 7 notebooks run restart-and-run-all on real data with identical outputs across two fresh runs (`scripts/run_notebooks.py --twice`).

## Results (held-out top-player battles from 2026-10-18 20:42 to 2026-10-19 01:36 UTC)

| Model | Result | Baseline | Note |
| --- | --- | --- | --- |
| Deck strength | log loss 0.69280, AUC 0.521 | 50%: 0.69315 · popularity: 0.69302 · rating only: 0.69302 | Better on point estimates, **not statistically clear** (bootstrap intervals include 0). Deck choice barely moves win odds at this level |
| Completion | recall@10 0.92 | popular fill 0.25 | Optimistic: the weight rule was revised after seeing test results |
| Archetype | 0.95 on 20 held-out decks | majority 0.40 | Labels are the assistant's drafts; relabel with `label --interactive` |
| Synergy | AUC 0.519 | lift 0.490 · popularity 0.510 | Small margin |

Details, caveats and every departure from the spec: [docs/model-notes.md](docs/model-notes.md).

## Setup

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Windows; use .venv/bin/python on macOS/Linux)
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pytest
```

## Website

The deck builder also runs as a small website that runs the trained model in the browser. Each page has one job:

| Page | What it shows |
| --- | --- |
| `web/index.html` (Build a deck) | Pick up to eight cards, a full deck (with short definitions of card types and forms, Clear picks, and a Try an example pick: the mode's most-played card form). With all eight picked there is nothing to add, so it shows that deck as "Your deck", scored the same way, in either source. **Observed decks** (default): real decks from the mode's pool (played at least 5 times in the training battles, legal and unlocked) that hold your picks, ranked by the builder's score. **Generated decks · experimental**: new combinations from the beam search. Each deck shows its warnings first, its exact-deck test record and appearances, its predicted style with a plain-language description, the estimate with its 90% model range, and "Why it ranks here" (the score's three parts and the strongest pair). A side-by-side comparison of the options names no winner |
| `web/reason.html` (Why this deck) | Opened from a deck: an "At a glance" overview (predicted style, roles from the card labels, main warnings, the best single swap with before/after, Apply/Undo; picked cards are kept out of swaps unless the reader presses "Let swaps replace my picks", a choice kept in the link), then three layers drawn the first time they are opened: all score swaps, evidence (card weights, model vs real results, pairs, deck checks; every chart has a question title, a takeaway and a table version), and math and model details (score formula, card map) |
| `web/cards.html` (All cards) | Every row of `data/labels/source/cards_meta.csv` and every card form, led by name, role, elixir, status and the measured games and win rate; the regression weights and your CSV's numbers are separate views, each stating its source. `cards.html#<mode>~~<card>` opens it on one card |
| `web/meta.html` (Card usage trends) | Card usage trends among sampled Ranked players: observed history (headline changes only when both periods are big enough, all changes, a card lookup, table versions of the charts), the experimental next-period forecast with its real state and track record (error vs no change, 90% band coverage), drawn next to the history with its bands and a no-change line whenever the export has forecast rows, and a pointer to season readiness |
| `web/future.html` (Future meta) | The track record first (did the TimesFM usage forecast beat assuming no change, did its ranges hold, did decks picked against simulated next fields win more than simple rules, among players new to each deck), then which signals go with a deck winning or being adopted, tested on later battles; card and style forecasts with Monte Carlo bands; real decks to consider with their math, matchups and what the forecast changes; what moved when a new season started. Reads `web/future_meta.json`, built offline; the design was committed before any result ([docs/future-meta/DESIGN.md](docs/future-meta/DESIGN.md)) |
| `web/seasons.html` (Season readiness) | The most-played ranked decks up to the latest collection (dated) with their trend, new cards / Evolutions / Heroes between saved card lists, and how many seasons are collected toward a next-season prediction (none is built) |
| `web/counters.html` (Find counters) | Pick a deck style or the cards you face first (kept in the link); then counter cards (each matchup with its 90% range) and 3 real counter decks with a tech swap, labelled as estimate vs the opponents, general estimate, and measured style-wide record. The checks come last: the forward check (inputs fixed before the later battles, paired bootstrap ranges, `web/counter_eval.json`) and the exported retrospective one, with a row that counts every style equally |
| `web/model.html` (How it works) | How the model is built, as one five-step story, held-out results against baselines, "Three models, three questions" (sigmoid win estimates, softmax style probabilities and the Monte Carlo usage forecast, each with a worked example from real data), limits, a glossary with examples from the current data, and the full run log |

- The menu has four destinations: Build a deck, Find counters, Explore trends (usage trends, the future meta, season readiness and All cards, with their own sub-menu) and How it works. Old page addresses still work.
- `python scripts/future_meta.py` writes `web/future_meta.json` (about 10 minutes the first time, 2 once its work in `data/processed/future_meta/` is cached). It parses the newest raw logs itself and leaves `data/interim` and the model caches alone, so it never forces a retrain. TimesFM 2.5 runs on the CPU in its own environment, once: `py -3.12 -m venv .venv-timesfm`, then `.venv-timesfm/Scripts/python -m pip install -r requirements-timesfm.txt`. The first run downloads about 925 MB of weights from Hugging Face. Rerun it after each new collection.
- `web/common.js` and `web/app.css` are shared by all pages; `web/engine.js` is a JavaScript port of the scoring, search, legality, warnings, archetype and explanation code. `web/observed.js` picks the observed decks (Python twin: `crdeck.counters.observed_decks`, a post-training function, so it never forces a retrain). `web/learn.js` builds the worked examples on How it works and Usage trends from the same exports and engine code.
- `python scripts/export_web.py` writes `web/modes.json` (modes, meta history, run log), one model per mode in `web/models/`, and Python's own answers for test cases in `web/golden/`.
- `python scripts/counter_eval.py` writes `web/counter_eval.json`: the forward check of the counter ranking for every mode (design fixed first in `docs/claude-redesign/EVAL-DESIGN.md`). It reads the cached models only and skips a mode whose cache is stale; it never retrains. Run it after an export.
- The Why this deck page also has a **card map**: every card form as a learned vector (SVD of positive PMI from the training decks, size chosen on validation), a rotatable 3D PCA picture, and swaps that stay close to the deck in the full-dimensional space and raise the win rate (`src/crdeck/embedding.py`). Each regular swap shows its score math written out.
- In a single Trophy Road arena the builder only offers what a player there could own: card unlock arenas and slot unlocks come from the Clash Royale Wiki (`python scripts/fetch_wiki_unlocks.py` writes `config/card_unlocks.yaml`), plus cards that at least 3 decks in that arena's battles already use.
- Pages pass the mode, deck and picked cards in the link's `#` part (plus `~g` when generated decks were chosen), so a "Why this deck" link can be shared. Old links still work.
- `node scripts/sweep_web_engine.mjs` seeds the engine with every card form, and with 4 to 9 cards of real decks, and checks every result (legal decks, seeds kept, a full set of picks returned as itself, a ninth card refused, legal swaps, breakdowns that add up).
- `node scripts/check_web_engine.mjs` checks that the port agrees with Python on 3,000 random decks (legality and slots) plus searches, swaps and explanations. Python remains the source of truth; re-run the export and the check after retraining. The exported golden files only hold searches with 0 to 3 picks, so `python scripts/more_picks_golden.py <dir>` writes Python's answers for 4 to 8 picks (cached models only, never retrains) and `node scripts/check_web_engine.mjs <dir>` compares them.
- Headless page checks (jsdom): `cd tests/web && npm install` once, then `node page_test.cjs` (every page, a few minutes) or `node site_check.cjs` (every mode on every page, about 15 minutes). `run1_test.cjs` to `run5_test.cjs` check the 2026-10-29 redesign (bad links and load states, observed/generated decks, the explanation and counters layout, the worked math against the engine, and Run 5's navigation, comparison, lazy layers, chart tables, link state and forward check); `picks_test.cjs` checks picking up to a full deck (both sources, 4 to 7 picks, keyboard focus, and letting swaps replace picks). Run them after an export.
- To view it locally, serve the folder (`python -m http.server -d web`) and open http://localhost:8000.

The spec (section 3) listed a web UI as deferred; it was built on request after the core results were in.

**Redesign (2026-10-29).** The site was reworked for newcomers in four runs, following `docs/claude-redesign/START-HERE.md`. What changed, every check run and the remaining limits are in `PROMPT-PROGRESS.md`; research left for later is in `docs/claude-redesign/BACKLOG.md`. No model was retrained and no export changed; the one intended change in what is recommended is that the builder shows observed decks by default. A fifth run, on request, added the items the four runs had deferred (four-destination menu, comparison view, Try an example, lazy layers, chart tables, the All cards views, the forecast picture, counter links) and the forward counter check. Afterwards the user decided against official card art (cards keep their text names) and raised the builder's pick limit from 3 to a full deck of 8.

## Using it

```bash
python -m crdeck suggest "Hog Rider"                 # decks + explanations; forms: "Knight@evo", "Knight@hero"
python -m crdeck evaluate                            # held-out report; saves outputs to data/processed/
python -m crdeck label --interactive                 # review / relabel archetypes (held-out first)
```

Or open `notebooks/07_demo.ipynb`.

## Refreshing the data

1. `.env` holds `CR_API_KEY=...`. The key is tied to the IP it was registered for; check yours with `curl https://api.ipify.org`. Never commit `.env` (it is git-ignored).
2. `python -m crdeck gate`: re-checks the API format and regenerates [docs/api-notes-observed.md](docs/api-notes-observed.md) with config suggestions. Run it if Supercell changes the API.
3. `python -m crdeck collect --window auto`: battle logs for the leaderboards in `config/collection.yaml`. Logs hold only the last 30 battles, so run it daily to widen the time window. To schedule it on Windows, use `scripts/daily_collect.py`, which does the same collection, falls back to the last good player list when the leaderboards are empty or refilling, retries a dropped connection, and logs to `data/collect_daily.log`. In PowerShell:
   ```powershell
   $action = New-ScheduledTaskAction -Execute "C:\Users\simty\crdeck\.venv\Scripts\pythonw.exe" -Argument "scripts\daily_collect.py" -WorkingDirectory "C:\Users\simty\crdeck"
   $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6)
   Register-ScheduledTask -TaskName crdeck-collect -Action $action -Settings $settings -Trigger (New-ScheduledTaskTrigger -Daily -At 8pm) -Force
   ```
   For lower arenas, also run `python -m crdeck collect --arenas --window auto`: it finds players in every Trophy Road arena through clan search (and their ladder opponents), up to `arena_sample.players_per_arena` each, and prints how many each arena got. Those logs are kept apart (`battlelog_arena/`) and are not used for the meta history.
   When a season starts, the leaderboards can answer with no players and `collect` stops with "leaderboards returned no players" (seen on 2026-11-02). `python scripts/collect_known_players.py` then fetches the logs of the players on the newest lists with enough players, into the same layout. The scheduled script does this by itself.
4. Refresh order: `collect` → `build` → `evaluate` → `python scripts/export_web.py` → `node scripts/check_web_engine.mjs` → `node scripts/sweep_web_engine.mjs`. `python scripts/future_meta.py` can run after any collection, on its own. The export re-runs the evaluation for any mode whose saved one is stale. Then the notebooks. Models retrain automatically when data, labels, configs or code change (cache: `data/processed/context_cache_<mode>.pkl`; `CRDECK_NO_CACHE=1` forces a retrain); the counter page's `src/crdeck/counters.py` and `config/counters.yaml` run after training and never trigger a retrain. `data/raw_manifest.csv` records every raw file's fetch time; like `data/raw`, it is not committed, because its file names are player tags.
5. Re-check notebook 02's slot audit and notebook 06's co-occurrence tuning after each new window.

## Synthetic data (pipeline testing only)

`python -m crdeck synthetic` and `--source synthetic` run everything on generated battles in `data/synthetic/` (git-ignored, labeled SYNTHETIC everywhere, never a fallback). Tests use it to check that the models recover a planted signal.

## Layout

```
config/          deck_rules.yaml (slot rules + evidence), collection.yaml (API, leaderboards, forms, split), model.yaml
data/labels/     cards.csv, archetype_labels.csv, source/cards_meta.csv (your original CSV)
data/raw/        immutable API responses; data/raw_manifest.csv lists them with fetch times (both git-ignored)
src/crdeck/      cards, rules (only legality code), api (only network code), collect, parse, dataset, synergy,
                 strength, archetype, labeling, search, explain, evaluate, pipeline, synthetic, cli
src/crdeck/futuremeta/  data, forecasting, decks, quality, report, timesfm_runner (a subpackage, so it can't trigger a retrain)
tests/           pytest: rules, parsing/dedupe, shrinkage, search invariants, API client, pipeline, tooling
notebooks/       01_cards … 07_demo (generated by scripts/make_notebooks.py; committed without outputs)
docs/            spec.md, api-notes.md, api-notes-observed.md, card-label-review.md, model-notes.md
```
