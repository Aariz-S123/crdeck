# crdeck: Clash Royale ML deck builder

A personal deck-building assistant. Give it 0–3 cards and it returns legal 8-card decks with an archetype, an estimated win rate (with sample size and uncertainty), synergy evidence, advisory warnings and swap suggestions, all learned from top-player battles collected through the official API. Spec: [docs/spec.md](docs/spec.md).

Learning project; not affiliated with Supercell. It does not find "the best deck." Win rates describe top-player battles in the sampled window, not your games, and synergy scores are correlations, not proven combos.

## Status

| Phase (spec §11) | State |
| --- | --- |
| 1. Gate | Code done; **needs your API key**. Card table: 123 deck cards, labels reviewed against public sources (`v1-assistant-reviewed`, see [docs/card-label-review.md](docs/card-label-review.md)), awaiting your sign-off |
| 2. Rules | Done: `rules.py` plus 22 legality tests. Two slot rules are still unconfirmed in-game; evidence is in `config/deck_rules.yaml` |
| 3. Data | Code done (client, cache, collection, parse, dedupe). No real battles collected yet |
| 4. Baselines | Done (50%, popularity), time split fixed |
| 5. Models | Done: synergy, strength, archetype. Archetype needs your labels on real decks (`label --interactive`) |
| 6. Search | Done: completion, swaps, explanations |
| 7. Demo | Done: all 7 notebooks run restart-and-run-all clean, with identical outputs across two fresh runs (synthetic data) |

93 tests pass (`pytest`). Every model result so far comes from **synthetic** data (below). No number in this repo describes the real game yet.

## Setup

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # (Windows; use .venv/bin/python on macOS/Linux)
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pytest
```

## Real data, step by step

1. Create a key at developer.clashroyale.com for your **current public IP** (keys are IP-bound; find the IP with `curl https://api.ipify.org`). Save `CR_API_KEY=...` in `.env` (see `.env.example`).
2. `python -m crdeck gate`: fetches `/cards`, the Path of Legends leaderboard and one battle log. It writes [docs/api-notes-observed.md](docs/api-notes-observed.md), covering field inventories, time format, 429s and any unknown card fields (a Hero-form marker would show up here), and suggests config changes. Apply them in `config/collection.yaml` and fill the "observed" column of [docs/api-notes.md](docs/api-notes.md).
3. Review `data/labels/cards.csv` using the checklist in [docs/card-label-review.md](docs/card-label-review.md), then set your own `label_version`.
4. `python -m crdeck collect --window auto`: battle logs for the top players under a window named after today's UTC date. Cached and resumable. A log holds only recent battles, so run it once a day for a while to reach tens of thousands of battles; `build` merges every window and deduplicates.
   To run it daily on Windows, schedule it with Task Scheduler (adjust the path):
   ```
   schtasks /Create /SC DAILY /ST 20:00 /TN crdeck-collect /TR "C:\Users\simty\crdeck\.venv\Scripts\python.exe -m crdeck collect --window auto"
   ```
   The key only works from the IP it was registered for, so a laptop that changes networks will get 403s on some days. Those show up in the collect summary.
5. `python -m crdeck build`: rebuilds `data/interim` and `data/processed` from raw data plus labels. It also writes `data/raw_manifest.csv` (tracked in git), which records every raw file's window and fetch time, since `data/raw` itself is not committed.
6. `python -m crdeck label --interactive`: shows decks spread across k-means clusters and asks for an archetype. The first 20 go to the held-out split (spec §7.3), then 60–80 go to train. Answers are saved as you go; quit and resume any time.
7. `python -m crdeck evaluate`: prints the held-out report and saves model outputs to `data/processed/` (synergy pairs, card weights, model comparison, evaluation.json). Then open the notebooks.

`python -m crdeck suggest "Hog Rider" "Knight@evo"` prints decks with full explanations. Forms: `@evo`, `@hero`.

Models are cached in `data/processed/context_cache.pkl` and retrained automatically when data, labels, configs or code change. Set `CRDECK_NO_CACHE=1` to force a retrain.

## Synthetic data (pipeline testing only)

```bash
python -m crdeck synthetic
python -m crdeck build --source synthetic
python -m crdeck suggest --source synthetic "Hog Rider"
CRDECK_DATA_SOURCE=synthetic python scripts/run_notebooks.py --twice   # run-all + determinism check
```

Generated battles go to `data/synthetic/` (git-ignored), and every output is labeled SYNTHETIC. They use real card names so decks are readable, but card strengths and pair bonuses are random and planted (`data/synthetic/truth.json`), which is how the tests check the models recover a known signal. This is never a fallback: the default source is `real`, and with no real data every step stops with an error saying what to run.

## Layout

```
config/          deck_rules.yaml (slot rules + evidence), collection.yaml (API, window, forms, split), model.yaml
data/labels/     cards.csv (labels), source/cards_meta.csv (your original CSV), archetype_labels.csv
data/raw/        immutable API responses, one file per request (git-ignored)
src/crdeck/      cards, rules (only legality code), api (only network code), collect, parse, dataset, synergy,
                 strength, archetype, labeling, search, explain, evaluate, pipeline, synthetic, cli
tests/           pytest: rules, parsing/dedupe, shrinkage, search invariants, API client, pipeline, tooling
notebooks/       01_cards … 07_demo (generated by scripts/make_notebooks.py; committed without outputs)
docs/            spec.md, api-notes.md, card-label-review.md, model-notes.md (choices and deviations)
```

## Where this departs from the spec

See [docs/model-notes.md](docs/model-notes.md). In short:

- Synergy's expected rate uses each card's games without its partner, which fixes double counting.
- Completion adds a co-occurrence term tuned on the validation window.
- L2 strength is tuned on validation.
- The score interval includes model uncertainty.
- An `UNSEEN_DECK` flag marks extrapolated scores.
