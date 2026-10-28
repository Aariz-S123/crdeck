# crdeck: Clash Royale ML deck builder

A personal deck-building assistant. Give it 0–3 cards and it returns legal 8-card decks with an archetype, an estimated win rate (with sample size and uncertainty), synergy evidence, advisory warnings and swap suggestions, all learned from top-player battles collected through the official API. Spec: [docs/spec.md](docs/spec.md).

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

94 tests pass (`pytest`). All 7 notebooks run restart-and-run-all on real data with identical outputs across two fresh runs (`scripts/run_notebooks.py --twice`).

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
| `web/index.html` (Build decks) | Pick up to three cards, get three legal decks with style, estimated win rate and range, and deck checks |
| `web/reason.html` (Why this deck) | Opened from a deck: a plain-language summary, card weights, model vs real results, card pairs, warnings, swaps with their breakdown, raw score |
| `web/cards.html` (All cards) | Every row of `data/labels/source/cards_meta.csv` and every card form: status, battle stats, regression weight, your CSV's numbers |
| `web/meta.html` (Meta) | Ranked usage history, biggest movers, deck styles per period, forecast status and assumptions |
| `web/seasons.html` (Next season) | Today's most-played ranked decks with their trend, new cards / Evolutions / Heroes between saved card lists, and a next-season prediction that stays locked until 3 seasons are collected and it beats "no change" on a held-out season |
| `web/counters.html` (Counters) | Pick a deck style or the cards you face; shows counter cards (with each matchup and its 90% range) and 3 counter decks that are real decks (played at least 5 times, legal, unlocked) ranked against them by the card-vs-card matchup model, each with its real record against the style after training and one like-for-like tech swap, plus a held-out check of the ranking (docs/model-notes.md §17) |
| `web/model.html` (How it works) | How the model is built, held-out results against baselines, limits, a glossary, and the full run log |

- `web/common.js` and `web/app.css` are shared by all pages; `web/engine.js` is a JavaScript port of the scoring, search, legality, warnings, archetype and explanation code.
- `python scripts/export_web.py` writes `web/modes.json` (modes, meta history, run log), one model per mode in `web/models/`, and Python's own answers for test cases in `web/golden/`.
- The Why this deck page also has a **card map**: every card form as a learned vector (SVD of positive PMI from the training decks, size chosen on validation), a rotatable 3D PCA picture, and swaps that stay close to the deck in the full-dimensional space and raise the win rate (`src/crdeck/embedding.py`). Each regular swap shows its score math written out.
- In a single Trophy Road arena the builder only offers what a player there could own: card unlock arenas and slot unlocks come from the Clash Royale Wiki (`python scripts/fetch_wiki_unlocks.py` writes `config/card_unlocks.yaml`), plus cards that at least 3 decks in that arena's battles already use.
- Pages pass the mode, deck and picked cards in the link's `#` part, so a "Why this deck" link can be shared.
- `node scripts/sweep_web_engine.mjs` seeds the engine with every card form and checks every result (legal decks, seeds kept, legal swaps, breakdowns that add up).
- `node scripts/check_web_engine.mjs` checks that the port agrees with Python on 3,000 random decks (legality and slots) plus searches, swaps and explanations. Python remains the source of truth; re-run the export and the check after retraining.
- Headless page checks (jsdom): `cd tests/web && npm install` once, then `node page_test.cjs` (every page, a few minutes) or `node site_check.cjs` (every mode on every page, about 15 minutes). Run them after an export.
- To view it locally, serve the folder (`python -m http.server -d web`) and open http://localhost:8000.

The spec (section 3) listed a web UI as deferred; it was built on request after the core results were in.

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
3. `python -m crdeck collect --window auto`: battle logs for the leaderboards in `config/collection.yaml`. Logs hold only the last 30 battles, so run it daily to widen the time window. To schedule it on Windows:
   ```
   schtasks /Create /SC DAILY /ST 20:00 /TN crdeck-collect /TR "C:\Users\simty\crdeck\.venv\Scripts\python.exe -m crdeck collect --window auto"
   ```
   For lower arenas, also run `python -m crdeck collect --arenas --window auto`: it finds players in every Trophy Road arena through clan search (and their ladder opponents), up to `arena_sample.players_per_arena` each, and prints how many each arena got. Those logs are kept apart (`battlelog_arena/`) and are not used for the meta history.
4. Refresh order: `collect` → `build` → `evaluate` → `python scripts/export_web.py` → `node scripts/check_web_engine.mjs` → `node scripts/sweep_web_engine.mjs`. The export re-runs the evaluation for any mode whose saved one is stale. Then the notebooks. Models retrain automatically when data, labels, configs or code change (cache: `data/processed/context_cache_<mode>.pkl`; `CRDECK_NO_CACHE=1` forces a retrain); the counter page's `src/crdeck/counters.py` and `config/counters.yaml` run after training and never trigger a retrain. `data/raw_manifest.csv` (tracked) records every raw file's fetch time, since `data/raw` itself is not committed.
5. Re-check notebook 02's slot audit and notebook 06's co-occurrence tuning after each new window.

## Synthetic data (pipeline testing only)

`python -m crdeck synthetic` and `--source synthetic` run everything on generated battles in `data/synthetic/` (git-ignored, labeled SYNTHETIC everywhere, never a fallback). Tests use it to check that the models recover a planted signal.

## Layout

```
config/          deck_rules.yaml (slot rules + evidence), collection.yaml (API, leaderboards, forms, split), model.yaml
data/labels/     cards.csv, archetype_labels.csv, source/cards_meta.csv (your original CSV)
data/raw/        immutable API responses (git-ignored); data/raw_manifest.csv lists them with fetch times
src/crdeck/      cards, rules (only legality code), api (only network code), collect, parse, dataset, synergy,
                 strength, archetype, labeling, search, explain, evaluate, pipeline, synthetic, cli
tests/           pytest: rules, parsing/dedupe, shrinkage, search invariants, API client, pipeline, tooling
notebooks/       01_cards … 07_demo (generated by scripts/make_notebooks.py; committed without outputs)
docs/            spec.md, api-notes.md, api-notes-observed.md, card-label-review.md, model-notes.md
```
