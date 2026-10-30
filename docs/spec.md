# Clash Royale ML Deck Builder: solo build specification

Revision 1, 18 October 2026. Solo project, Jupyter-first. This is planning guidance. Nothing here has been tested yet, including the API field formats.

## 1. Product and intended user

The tool is a personal deck-building assistant. It learns card synergies, archetypes and deck strength from real top-player battles, and it always explains its recommendations.

**Product promise:** Given 0–8 cards you want to play, the tool suggests legal 8-card decks, names the archetype, estimates strength from real battle data, and suggests swaps. It shows the evidence behind each suggestion. With all 8 picked, the one legal deck is that deck itself, so the tool scores it as it is. (The limit was 0–3 until the user raised it to a full deck on 2026-10-29.)

### Key distinctions

- **Legality is a hard rule; everything else is advisory.** An illegal deck is never output. A low synergy score, a missing air defense or a high elixir average produces a warning but does not block the deck.
- A predicted win rate describes top-player battles in the sampled window. It is not a promise about your games.
- A synergy score means two cards appear together and win together more than expected in the data. It does not prove a causal combo. Popular cards co-occur partly because they are popular.
- Archetype labels are descriptive categories. A deck can be a hybrid.
- Existing tools (RoyaleAPI, RoyaleTracker, DeckShop and others) already do meta decks and deck builders. This is a learning project with a careful implementation, not a new invention.

### Signature demonstration

You pick Hog Rider. The tool returns three legal decks that respect the slot rules. Each has an archetype label (e.g. Cycle), an estimated win rate with sample size and uncertainty, the top three synergy pairs with their evidence, and one advisory warning such as "no building against tanks." You then swap a card and the score and warnings recompute.

## 2. Slot rules (the game's current rules)

These go in `config/deck_rules.yaml`, not hard-coded, because Supercell has changed them three times in a year.

- Every deck has exactly 8 cards, with no duplicates.
- Since the 16 March 2026 update, ranked, events and challenges use three special slots: one Evolution slot (Evolutions only), one Hero slot (Heroes and Champions), and one Wild slot (any special form).
- A card with both Evolution and Hero forms unlocked can switch its active ability when placed in the Wild slot.
- So a deck holds at most two Evolutions, and only by spending the Wild slot on an Evolution instead of a Hero.
- A card can appear in only one form per deck: base, Evolution or Hero, never two of these.
- Champions and Heroes must sit in the Hero or Wild slot.

**Unresolved, verify in-game before encoding:**

- Can a deck hold two champions (Hero slot plus Wild slot)? One guide says one Evolution plus two Heroes or Champions is allowed, but it doesn't clearly address two champions. The old rule was one champion. Default to `max_champions: 1` until confirmed.
- Sources describe the Wild slot inconsistently: some say Evolution or Hero, the official post says any form. Treat it as accepting Evolution, Hero or Champion, and keep it configurable.

A legal deck may leave special slots empty. A base card can always sit in a normal slot even if you own its Evolution.

## 3. Scope

### Must ship (in this order)

1. Card table with your hand-labeled roles (section 5).
2. Deck legality validator plus tests.
3. API data collection: top Path of Legends players, then their battle logs, stored raw and deduplicated.
4. Synergy model: pair statistics with sample sizes and shrinkage.
5. Deck strength model: predicts which deck wins a battle.
6. Deck completion: seed cards plus empty slots in, ranked legal decks out.
7. Archetype classifier: hand-labeled seed set plus clustering.
8. Swap suggestions: for each card in a deck, the best legal replacement and its score change.
9. Explanations for every output (section 8).
10. Evaluation on time-held-out data against simple baselines.

### Deferred

- Balance-change handling and staleness flags. The schema still records battle dates so this can be added without re-collecting data.
- Card levels and personal collection filtering.
- Matchup-specific counter advice ("what beats this deck").
- Web app or UI beyond notebooks.
- 2v2, draft modes, and Trophy Road below the arenas where special slots unlock.

### Out of scope

- Scraping any stat site. RoyaleAPI has explicitly asked people not to scrape it and to use the official API instead.
- Gameplay advice (placement, timing).
- Any claim of "best deck" beyond what the data window supports.

## 4. Architecture

Use Python 3.12 with pandas, numpy, scikit-learn, pyarrow, requests, PyYAML and pytest. PyTorch is added only if card embeddings beat the simpler models. Pin versions in `requirements.txt` from day one.

Notebooks are for exploring and presenting. Reusable logic lives in a package so it can be tested. If a function is copied into two notebooks, it belongs in `src/`.

```text
config/deck_rules.yaml        Slot rules, max champions, deck size
config/collection.yaml        Rank range, battle types, date window, rate limits
data/raw/                     Immutable API JSON, one file per request, dated
data/interim/                 Parsed, deduplicated battles (parquet)
data/processed/               Feature tables, model outputs
data/labels/                  Your card roles and archetype seed labels (CSV)
src/crdeck/cards.py           Card table loading and validation
src/crdeck/rules.py           Legality validator (the only one)
src/crdeck/api.py             The only network client
src/crdeck/parse.py           Raw JSON to battle and deck records
src/crdeck/synergy.py         Pair statistics
src/crdeck/strength.py        Win prediction model
src/crdeck/archetype.py       Archetype classification
src/crdeck/search.py          Deck completion and swaps
src/crdeck/explain.py         Builds explanation objects
tests/                        pytest, including fixed fixture battles
notebooks/01_cards.ipynb      ... 07_demo.ipynb
```

Notebooks import from `crdeck`. Only `rules.py` decides legality. Search, completion and swaps all call it; none reimplement it.

The API key goes in `.env`, which is listed in `.gitignore`. Never print the key or commit the raw request headers.

## 5. Data model

### Card table (`data/labels/cards.csv`)

Start from your existing card list and add these columns.

| Field | Source | Notes |
| --- | --- | --- |
| `card_id` | API `/cards` | Canonical key. Join on the ID, never the name. |
| `name` | API | |
| `elixir` | API | Mirror's cost is variable, so flag it with `elixir_variable: true`. |
| `rarity` | API | common / rare / epic / legendary / champion |
| `card_type` | You | troop / spell / building |
| `has_evolution`, `has_hero`, `is_champion` | API if present, else you | Verify what `/cards` returns before hand-filling. |
| `is_win_condition` | You | Hog Rider, Golem, X-Bow, Graveyard, etc. |
| `roles` | You | Semicolon list: `small_spell`, `big_spell`, `air_defense`, `tank`, `mini_tank`, `splash`, `building`, `cycle`, `tank_killer` |
| `targets` | You | ground / air_ground / buildings |
| `label_version` | You | Bump this when you change labels. |

Roles are your judgment. They power advisory warnings and features, but they are not ground truth.

### Battle and deck records

| Entity | Fields |
| --- | --- |
| **Battle** | `battle_key`, `battle_time` (UTC), `battle_type`, `game_mode`, `source_player_tag`, `fetched_at` |
| **DeckInBattle** | `battle_key`, `side` (A/B), `player_tag`, `deck_key`, `won` (bool), `crowns`, `trophies_or_rank` if available |
| **Deck** | `deck_key`, 8 `card_id`s, plus each card's form (base / evo / hero) and slot if the API exposes it |
| **SlotCard** | `deck_key`, `card_id`, `form`, `slot` (normal / evo / hero / wild / unknown) |

Rules for these records:

- **`deck_key`:** sorted `card_id:form` pairs joined into one string, so card order doesn't create fake duplicate decks.
- **`battle_key`:** both player tags (sorted) plus `battle_time`. The same battle shows up in both players' logs and must be counted once.
- **Mirror and invalid battles:** drop mirror matches (identical deck keys) from win models, since they carry no signal. Drop draws, or store them separately.
- **Unknown cards:** a card ID not in your table means the record is kept with status `UNKNOWN_CARD` and excluded from models until you add it.

## 6. API integration gate (do this first)

Do this before writing any models.

1. Create a key at developer.clashroyale.com. Keys are tied to IP addresses, so a key made at home may fail on campus Wi-Fi. Record which IP you registered.
2. Call `/cards` and save the full response. Record exactly how evolutions, heroes and champions are represented, and which of the fields in section 5 exist.
3. Fetch the Path of Legends leaderboard and one battle log. Record:
   - how a Hero-form or Evolution-form card appears in battle deck JSON (an evolution level field? a separate flag?);
   - whether slot position is recorded;
   - the time format;
   - how many battles one log returns;
   - the rate-limit behavior.
4. Write what you found in `docs/api-notes.md`, separating "documented" from "observed in my calls."
5. If hero form can't be told apart from base form in battle data, record that limitation. The model then treats hero/base as unknown rather than guessing.

Player tags start with `#`, which must be URL-encoded as `%23`. Cache every raw response. Respect rate limits with a fixed delay and backoff. Never re-fetch what's already in `data/raw/` for the same window.

## 7. Model definitions

These are starting points chosen for being explainable and testable. They are not validated choices; section 10 decides whether they hold up.

### 7.1 Pair synergy

For each card pair (i, j), using the training window only:

```text
co_rate(i,j)   = decks containing both / all decks
lift(i,j)      = co_rate(i,j) / (rate(i) * rate(j))
pair_wins, pair_games = battles where one side's deck has both i and j
shrunk_wr(i,j) = (pair_wins + k * global_wr) / (pair_games + k)      # k = 50 to start
synergy(i,j)   = shrunk_wr(i,j) - expected_wr(i,j)
```

`expected_wr` comes from the two cards' individual shrunk win rates, combined additively in log-odds. The pair score is therefore "better together than separately," not just "both cards are good."

- **Minimum sample:** pairs with fewer than 200 games return `INSUFFICIENT_SAMPLE` and get no synergy score. Some stat sites use a similar 200-game cutoff; that's a precedent, not proof the number is right.
- **Always report alongside the score:** lift, sample size and an interval. Never report a synergy score alone.

### 7.2 Deck strength

- **Baseline:** logistic regression on `x = card_vector(deck_A) - card_vector(deck_B)`, where the card vector is one-hot by `card_id:form`. Each card gets one learned weight; the predicted probability is that A wins.
- **Second model:** add the top-N pair features from 7.1, or gradient-boosted trees, kept only if it beats the baseline on held-out log loss.
- **Deck score:** the deck's average predicted win probability against the opponent-deck distribution in the test window. This is "win rate against the current meta," not against everything.
- **Known confounders, documented not hidden:**
  - Skill: top players choose certain decks.
  - Levels: they aren't modeled, but level gaps exist in battles. Store them, and if the data shows level gaps, test whether filtering large gaps changes results.

### 7.3 Archetypes

- **Labels:** hand-label about 60–100 real decks with one primary archetype: Beatdown, Cycle, Control, Siege, Bait, Bridge Spam, Graveyard, Hybrid.
- **Train/test split:** label a held-out 20 decks before tuning anything, so the expected results are fixed before you see the model's output.
- **Model:** a classifier on card one-hots plus role counts and average elixir. Use clustering on deck vectors (e.g. k-means on card embeddings) only to find decks worth labeling.
- **Output:** top label plus probability. If the top probability is below 0.5, show `HYBRID / UNCERTAIN` instead of forcing a label.

### 7.4 Completion and swaps

- **Completion:** beam search (width 50 to start). Start from the seed cards, add one card at a time, and keep only partial decks that can still become legal. Score full decks by deck strength plus a small synergy term. The weights are config, and they're reported in the output.
- **Swaps:** for each card, try every legal replacement and report the top 3 by score change, with the reason (which pairs gained or lost).
- **Structural checks are advisory warnings, not filters:**
  - no win condition;
  - no air defense;
  - no spell;
  - average elixir outside 2.6–4.5;
  - two or more cards with the same narrow role.

  One exception: "require a win condition" can be toggled as a hard filter in config. It is off by default.

## 8. Explanations

Every recommended deck returns an explanation object containing:

- Legality result, and which slot each special card occupies.
- Archetype plus probability.
- Deck score, interval, number of test battles behind it, and the data window dates.
- Top 3 and bottom 3 synergy pairs, each with lift, games and shrunk win rate.
- Advisory warnings, each with the rule and its observed value (e.g. "avg elixir 4.7, rule ≤ 4.5").
- Data-quality states: `INSUFFICIENT_SAMPLE`, `UNKNOWN_CARD`, `FORM_UNKNOWN` (hero/base not distinguishable). `STALE_AFTER_BALANCE` is reserved for later.

Correlated warnings are grouped. "No air defense" and "weak to Balloon" are one root cause, not two separate problems.

## 9. Code rules

1. **Notebooks:** they import from `crdeck`. Restart-and-run-all must work before a notebook counts as done.
2. **Raw data:** never edited. Every processed table can be rebuilt from `data/raw` plus `data/labels` by one command or notebook.
3. **Randomness:** fixed seeds everywhere there's randomness.
4. **Splits:** split by time. Train on earlier battles and test on later ones. Never split randomly, because the same players and decks in the same week leak.
5. **Tests:** written for the legality validator (every slot rule, both legal and illegal cases), deduplication, deck-key canonicalization, shrinkage math, and search never returning an illegal deck.
6. **Fallbacks:** none. If the API fails, the notebook says so; it does not substitute old data without labeling it.
7. **Git:** commit small changes. `data/raw` stays out of git if it's large; record its fetch dates instead.

## 10. Evaluation and acceptance criteria

### Metrics

| Model | Metric | Must beat |
| --- | --- | --- |
| Deck strength | Log loss and AUC on later-week battles | Always predicting 50%; a "more popular deck wins" baseline |
| Completion | Mask 2 cards from real held-out top decks; recall@10 of the true cards | Most-popular-card fill |
| Archetype | Accuracy on the pre-labeled held-out 20 | Majority class |
| Synergy | Do high-synergy pairs predict held-out wins better than lift alone? | Popularity-only ranking |

Report results as "held-out top-player battles from [dates]." These numbers measure the model against that data, not your personal win rate.

### Required test cases

| Case | Expected behavior |
| --- | --- |
| 9 cards, or a duplicate card | Rejected by the validator |
| Two evolutions plus one hero | Legal (Evo slot, Wild slot, Hero slot) |
| Three evolutions | Rejected |
| Champion in a normal slot | Rejected |
| Two champions | Follows `max_champions` in config; tested both ways |
| Same card as base and as evo | Rejected |
| Same battle fetched from both players' logs | Counted once |
| Mirror match | Excluded from win models |
| Card ID not in table | `UNKNOWN_CARD`, excluded, reported in counts |
| Rare pair under 200 games | `INSUFFICIENT_SAMPLE`, no score shown |
| Seed with 3 cards | Every output is legal and contains all 3 seeds |
| Seed with 8 cards (a legal deck) | That deck is the only output; a 9th card is refused |
| Seed that can't be legal (e.g. 3 champions) | Clear error, not an empty result |
| Deck with no air defense | Recommended if scored well, but carries a warning |
| Re-running a notebook | Same outputs, given same data and seeds |

## 11. Phases (solo, no fixed clock)

1. **Gate:** API key, `/cards`, one battle log, `api-notes.md`. Card table plus your role labels.
2. **Rules:** `rules.py` plus all legality tests passing.
3. **Data:** leaderboard and battle-log collection for one window (aim for tens of thousands of deduplicated battles), parse, dedupe, sanity counts.
4. **Baselines:** popularity and 50% baselines, time split fixed.
5. **Models:** synergy, then strength, then archetype (label the held-out set first).
6. **Search:** completion and swaps plus explanations.
7. **Demo notebook:** the signature demonstration end to end, restart-and-run-all clean.
8. **Later:** balance-change handling, levels, counters, UI.

Don't start a later phase while an earlier phase's tests fail.

## 12. Honest claims

- **Say:** it learns from top-player battles via the official API, explains its reasoning, and never outputs an illegal deck.
- **Don't say:** "best deck," guaranteed win rate, causal synergy, or that it's novel.
- Not affiliated with Supercell. Follow Supercell's fan content policy if you ever publish it.

## 13. Copy-paste coding prompt (Claude Code or Codex)

```text
You are helping me build a solo Python/Jupyter project: an ML Clash Royale
deck builder. Read docs/spec.md, docs/api-notes.md if present,
config/deck_rules.yaml, requirements.txt, and the existing src/crdeck code
before editing.

Rules: reusable logic goes in src/crdeck, notebooks import it. Only
rules.py decides deck legality; never reimplement it. Only api.py makes
network calls. Never print or commit the API key. Never edit data/raw.
Split train/test by time, never randomly. Use fixed random seeds.

Invariants: no illegal deck is ever output; legality is a hard rule and
synergy/structure checks are advisory warnings; small samples return
INSUFFICIENT_SAMPLE instead of a score; the same battle is counted once;
unknown cards and unknown hero/base forms are reported, not guessed.
No fake fallback data. No claims of "best deck" or win guarantees.

First tell me which files you'll change and anything missing that blocks
correct work. Then make the smallest working change, add pytest tests for
it, run pytest, and report: files changed, tests run and results, what is
still stubbed, and the next step. Documented API behavior and behavior
observed in real calls are different evidence; label which is which.
```

## 14. Sources

- Supercell, mid-March 2026 update (slot rework): https://supercell.com/en/games/clashroyale/blog/News/mid-march-update
- Timesaver, evolutions explained (Sept 2026): https://timesaver.gg/blog/clash-royale-evolutions-explained-september-2026
- Alviran, evolutions/heroes/champions guide: https://alviran.net/blog/clash-royale-evolutions-heroes-champions-card-types-guide/
- RoyaleAPI forum on scraping: https://discuss.royaleapi.com/t/royaleapi-scrape/50033
- RoyaleTracker about page: https://royaletracker.gg/about
- Royale Insights: https://www.producthunt.com/products/royale-insights
- Seemeta evolution/hero tiers: https://seemeta.com/en/clash-royale/evolutions
