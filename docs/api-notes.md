# API notes (spec section 6)

Two kinds of evidence, kept separate:

- **Documented / assumed**: pre-2026 public API documentation as recalled by the assistant that wrote this project, used to write the code before any call was made.
- **Observed in my calls**: real responses fetched on 2026-10-18 (window `2026-10-w3`), saved under `data/raw/` and summarized in [api-notes-observed.md](api-notes-observed.md), which `python -m crdeck gate` regenerates.

## Setup record

| Item | Value |
| --- | --- |
| Key created at | developer.clashroyale.com (tier `developer/silver`) |
| IP registered for the key | 128.227.5.165 (keys are IP-bound; another network needs another key or IP entry) |
| Gate run (UTC) | 2026-10-18 |
| Collection | 2026-10-18: top 1000 global + top 200 of 12 countries = 2,894 players, 2,894 battle logs, 0 errors, 0 HTTP 429 |
| Raw files | `data/raw/2026-10-w3/` (git-ignored); every file's fetch time is in `data/raw_manifest.csv` (tracked) |

## Checklist

| Question | Documented / assumed | Observed in my calls | Where the code depends on it |
| --- | --- | --- | --- |
| `/cards` shape | `{"items": [...], "supportItems": [...]}` | Same. 123 `items` (deck cards) and 4 `supportItems` (tower troops: Tower Princess, Cannoneer, Dagger Duchess, Royal Chef) | `cards.attach_api` reads `items` only |
| Card fields | `id`, `name`, `elixirCost`, `rarity`, `maxLevel`, `iconUrls`, `maxEvolutionLevel` | Same. `elixirCost` is missing only on Mirror (variable cost) | label flag `elixir_variable` |
| Rarity values | common / rare / epic / legendary / champion | Same, lowercase: 29 / 31 / 33 / 22 / 8 | `is_champion = rarity == "champion"` |
| Form availability | `maxEvolutionLevel` present on cards with an Evolution | **Bitmask**: 1 = Evolution only (39 cards), 2 = Hero only (14), 3 = both (4: Knight, Valkyrie, Musketeer, Wizard); absent = neither. `iconUrls` gains `evolutionMedium` / `heroMedium` to match | `attach_api` sets `has_evolution` / `has_hero` from the bits |
| Leaderboard endpoint | `/locations/{id}/pathoflegend/players` | Works for `global` and country ids (e.g. 57000249 US). Items: `tag`, `name`, `rank`, `eloRating`, `expLevel`, `clan` | `api.pol_leaderboard`, `config/collection.yaml: leaderboard` |
| Battle log endpoint | `/players/%23TAG/battlelog` | Works | `api.encode_tag` |
| Battles per log | about 25–30 | **30** | collect daily to accumulate history |
| Ranked battle `type` | `pathOfLegend` | `pathOfLegend` (game mode `Ranked1v1_NewArena`). Other types seen: trail, tournament, friendly, clanMate, boatBattle, riverRacePvP, riverRaceDuel, clanMate2v2, PvP, unknown | `battles.battle_types` |
| `battleTime` format | `20261018T120000.000Z` | Same | `parse.TIME_FORMATS` |
| Sides | `team`, `opponent`, one player each in 1v1 | Same; 2v2 modes have two (status `NOT_1V1`) | `parse` |
| Side fields | `tag`, `crowns`, `startingTrophies`, `cards` | Also `globalRank` (top 500 only), `trophyChange`, `elixirLeaked`, `kingTowerHitPoints`, `princessTowersHitPoints`, `supportCards`, `clan` | `startingTrophies` = Path of Legends rating, used as the skill covariate |
| Deck card fields | `name`, `id`, `level`, `maxLevel`, `rarity`, `elixirCost`, `evolutionLevel` | Same plus `starLevel`, `maxEvolutionLevel`, `iconUrls`. Exactly 8 cards per side | `parse._side` |
| How Evolution form appears | `evolutionLevel > 0` | **`evolutionLevel: 1`** | `form_resolution.form_values` |
| How Hero form appears | unknown | **`evolutionLevel: 2`**. Hero form is observable | `form_resolution.form_values` |
| Slot position | unknown after the rework | **Position 0 = Evolution slot, 1 = Hero slot, 2 = Wild slot**, 3–7 normal. Base cards appear in empty special slots | `form_resolution.slot_positions`; `slot_cards.slot` |
| Card levels | rarity-relative | Rarity-relative (e.g. legendary `level 8 / maxLevel 8`). Top players are maxed: 0.01% of test battles had a gap over 1 level | level gap = mean(`maxLevel - level`) |
| Rate limits | 429 when throttled | None hit at a 0.15 s delay over ~2,900 requests | fixed delay plus backoff |
| Errors | 403 for wrong IP, 404 for unknown player | 403 without a key. No 404s among leaderboard players | `api.ApiClient.get` |

## Consequences applied

- `has_hero` now comes from the API bitmask. It corrected one label: the source CSV listed "Hero Barbarians", but Barbarians has `maxEvolutionLevel: 1` (Evolution only).
- Hero form is a separate feature (`card:hero`). `FORM_UNKNOWN` no longer occurs with the current config.
- The slot rules were checked against observed decks. See `config/deck_rules.yaml` and notebook 02.

## Battle modes observed (2026-10-19, two collection windows)

Inventory of every battle `type` / `gameMode.name` / `deckSelection` / `arena` in the collected logs (deduplicated 1v1 battles):

| Mode on the site | type | gameMode | deckSelection | arena | battles |
| --- | --- | --- | --- | --- | --- |
| Ranked | pathOfLegend | Ranked1v1_NewArena (+ NewArena2) | collection | Legendary Arena | 84,541 |
| Trophy Road | trail | Ladder | collection | Seasonal Arena II / I | 2,676 / 1,912 |
| Trophy Road | PvP | Ladder | collection | Little Prince's Tavern / Spirit Square | 133 / 71 |
| not modeled | trail | Challenge_AllCards_EventDeck_NoSet, 202610_Event_Spooky_Chess | eventDeck | | 5,421 / 4,044 |
| not modeled | trail, tournament, friendly | Chaos_1v1_Draft, Draft_Competitive, DraftMode, ... | draft, draftCompetitive | | |
| not modeled | friendly, clanMate, boatBattle, riverRacePvP, riverRaceDuel, tournament | Friendly, ClanWar_BoatBattle, CW_Battle_1v1, CW_Duel_1v1 (warDeckPick), Showdown_Friendly, ... | | | |

Other battle fields seen: `isLadderTournament`, `isHostedMatch`, `leagueNumber`, `tournamentTag`, `eventTag`, `boatBattleSide`, `boatBattleWon`, `modifiers`. Exact per-run counts are in the website's Model log (from `data/processed/run_log.json`).
