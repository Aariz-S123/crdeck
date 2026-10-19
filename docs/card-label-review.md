# Card label review (v2, 2026-10-18)

## v2: confirmed against the real API

The `/cards` response (2026-10-18) was joined to the labels:

- All 123 labeled cards matched an API card, and no API deck card was unlabeled.
- No battle in 58,179 had an unknown card.
- All 8 champions matched API rarity `champion`.
- All evolution and hero flags matched the API bitmask except one: **Barbarians has no Hero form** (`maxEvolutionLevel: 1`), so the source CSV's "Hero Barbarians" row is wrong.
- Every v1 correction (Minion Giant 4, Rune Giant 4, Ronin 5, Void 5, Suspicious Bush 2, Goblin Machine 5, Boss Bandit 6, Berserker 2, Archer Queen 5, Royal Hogs 5) agreed with the API.
- The API corrected 4 more costs the review hadn't touched: Barbarian Hut 6, Electro Dragon 5, Goblin Hut 4, Little Prince 3.

The label file now carries these values (`label_version: v2-api-confirmed`). Roles, targets and win-condition flags remain judgment calls. Review them and set your own `label_version`.

## v1

`data/labels/cards.csv` moved from `v0-draft` to `v1-assistant-reviewed`. This is an assistant's review against public sources. It is still not your sign-off: roles are judgment calls (spec §5). When you have checked the table, set `label_version` to your own version (e.g. `v2`).

Elixir and rarity in the label file are placeholders: once `/cards` is fetched, `crdeck.cards.attach_api` replaces them with the API values and lists every override. The corrections below matter mainly for warnings and role features, and for spotting mistakes in the source CSV.

## Checked against a published list

- **Evolutions (43 cards):** match the list on [elixirdeck.org (Oct 2026)](https://www.elixirdeck.org/en/cards/evolutions-and-heroes.html) exactly.
- **Champions (8):** Archer Queen, Boss Bandit, Golden Knight, Goblinstein, Little Prince, Mighty Miner, Monk, Skeleton King. These match the same list exactly.
- **Heroes:** the CSV gives 19. The list has 18 and does not include **Barbarians**, even though the CSV has a "Hero Barbarians" row. I kept `has_hero: true` because it is your data, and added a note. Check it in-game. If it's wrong, set it to false.

## Changes

| Card | Change | Source |
| --- | --- | --- |
| Cannoneer | **Removed.** It is a tower troop (a king-tower pick), not one of the 8 deck cards | [Liquipedia](https://liquipedia.net/clashroyale/Cannoneer), [Fandom](https://clashroyale.fandom.com/wiki/Cannoneer) |
| Minion Giant | 4 elixir (CSV 5); win condition; flying, attacks buildings only; role `tank` | [Supercell, Season 87](https://supercell.com/en/games/clashroyale/blog/release-notes/new-season-minion-academy/), [RoyaleAPI](https://royaleapi.com/blog/minion-giant-september-2026) |
| Rune Giant | 4 elixir (CSV 6); win condition; targets buildings | [Liquipedia](https://www.liquipedia.net/clashroyale/Rune_Giant), RoyaleAPI blog |
| Ronin | 5 elixir (CSV 3); ground-only melee; `mini_tank;tank_killer` | [noff.gg](https://www.noff.gg/clash-royale/card/ronin), [RoyaleTracker guide](https://royaletracker.gg/guides/clash-royale-ronin-guide) |
| Spirit Empress | `elixir_variable: true`: costs 3 (ground form) or 6 (flying form, hits air) depending on your elixir; `mini_tank;air_defense` | [RoyaleAPI](https://royaleapi.com/blog/spirit-empress-new-card-2025-july?lang=en) |
| Void | 5 elixir (CSV 3); `big_spell`. Reworked in August 2026 into a heavy single-target spell | [PlayNews](https://www.playnews.gg/en/guides/clash-royale-classic-cards-reworked-on-august-4-the-void-at-5-elixir-and-the-x-bow-s-fake-buff) |
| Vines | Removed `small_spell`: it stuns the 3 highest-HP targets and does not clear swarms | [RoyaleAPI](https://royaleapi.com/blog/vines-new-card-2025-september?lang=en) |
| Suspicious Bush | Troop, 2 elixir (CSV: 1-elixir spell); heads for buildings | [RoyaleAPI](https://royaleapi.com/card/suspicious-bush), [Sportskeeda](https://www.sportskeeda.com/esports/suspicious-bush-clash-royale-ability-stats) |
| Goblin Machine | 5 elixir (CSV 4); rocket hits air and ground; `mini_tank;splash` | [Sportskeeda](https://www.sportskeeda.com/esports/clash-royale-goblin-machine-ability-stats) |
| Boss Bandit | 6 elixir (CSV 4); ground only | [esports.net](https://www.esports.net/news/mobile-games/clash-royale-boss-bandit/) |
| Berserker | 2 elixir (CSV 4); `mini_tank;cycle` | [RoyaleAPI](https://royaleapi.com/blog/berserker-new-card-2025-february?lang=en) |
| Goblinstein | Confirmed: the monster targets buildings (win condition); the doctor hits air and ground | [RoyaleAPI](https://royaleapi.com/blog/goblinstein-new-card-2024-october?lang=fr) |
| Goblin Demolisher, Goblin Curse | Confirmed draft labels | Sportskeeda |
| Heal Spirit | Troop (CSV said spell) | assistant knowledge |
| Goblin Drill | Building (CSV said spell) | assistant knowledge |
| Archer Queen | 5 elixir (CSV 4) | assistant knowledge |
| Royal Hogs | 5 elixir (CSV 4; the CSV's own evolution row says 5) | assistant knowledge |

## Rows in the source CSV that are inconsistent but harmless

Evolution and hero forms cost the same as their base card. "Cycle cost" is a different number. So these form rows in `cards_meta.csv` look wrong, and the base value was kept:

- Electro Giant Evolution: 8 vs 7
- Hero Giant: 7 vs 5
- Ice Spirit Evolution: 2 vs 1
- Skeletons Evolution: 2 vs 1
- Royal Hogs Evolution: 5 vs 4. Here the evolution row is the one that is right.

Mortar Evolution is labeled a spell, and Skeleton Barrel appears twice.

## Your review checklist

1. Skim every row's `roles`. Rows with a `notes` entry first.
2. Decide on Hero Barbarians.
3. Set `label_version` to your own version.
4. Re-run `pytest` (it validates the label file).
