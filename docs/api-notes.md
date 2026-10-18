# API notes (spec section 6)

Two kinds of evidence, kept separate:

- **Documented / assumed**: from the public Clash Royale API documentation as it stood before 2026, recalled by the assistant that wrote this project. **None of it has been checked against the current API.** The code is written against these assumptions and marks each one VERIFY.
- **Observed in my calls**: fill this in from `python -m crdeck gate` output. Until it is filled in, treat every row below as unverified.

## Setup record

| Item | Value |
| --- | --- |
| Key created at | developer.clashroyale.com |
| IP registered for the key | _fill in_ (keys are IP-bound; home vs campus Wi-Fi differ) |
| Gate run date (UTC) | _fill in_ |
| Raw files | `data/raw/<window id>/cards/cards.json`, `leaderboard/global.json`, `battlelog/<TAG>.json` |

## Checklist

| Question | Documented / assumed (unverified) | Observed in my calls | Where the code depends on it |
| --- | --- | --- | --- |
| `/cards` shape | `{"items": [...], "supportItems": [...]}`; items have `id`, `name`, `elixirCost`, `rarity`, `maxLevel`, `iconUrls`, and `maxEvolutionLevel` on cards with an Evolution | _fill in_ | `cards.attach_api` |
| Rarity values | `common`, `rare`, `epic`, `legendary`, `champion` (case may differ) | _fill in_ | `is_champion` comes from `rarity == champion` |
| Hero availability in `/cards` | Unknown. Heroes arrived with the 2026 slot rework; no field known | _fill in_ | `has_hero` stays a hand label until a field is found |
| Leaderboard endpoint | `/locations/global/pathoflegend/players` or `/locations/global/pathoflegend/{seasonId}/rankings/players` | _fill in_ | `api.ApiClient.pol_leaderboard`, `config/collection.yaml: leaderboard` |
| Leaderboard item fields | `tag`, `name`, `rank`, `eloRating` / `trophies`, `clan` | _fill in_ | only `tag` is used |
| Battle log endpoint | `/players/%23TAG/battlelog` (tag `#` URL-encoded) | _fill in_ | `api.encode_tag` |
| Battles per log | About 25–30 most recent battles | _fill in_ | collection depth: collect repeatedly across a window for more battles |
| Battle `type` for ranked | `pathOfLegend` | _fill in_ | `config/collection.yaml: battles.battle_types` |
| `battleTime` format | `20261018T120000.000Z` (UTC) | _fill in_ | `parse.TIME_FORMATS` |
| Sides | `team` and `opponent`, one player each in 1v1 | _fill in_ | `parse.NOT_1V1` otherwise |
| Deck card fields | `name`, `id`, `level`, `maxLevel`, `rarity`, `elixirCost`, `evolutionLevel` (present when the Evolution form is used), `maxEvolutionLevel`, `iconUrls` | _fill in_ | `parse.card_form` |
| How Evolution form appears | `evolutionLevel > 0` on the card in the battle deck | _fill in_ | `config: form_resolution.evo_field` |
| How Hero form appears | **Unknown** | _fill in_ | `config: form_resolution.hero_field` (null = indistinguishable; see below) |
| Slot position recorded? | Card order in the deck array; pre-2026 the first slot(s) were the evolution slot(s). Unknown after the rework | _fill in_ | `parse` records `position`; `slot` is `unknown` |
| Champions in battle data | Appear as normal cards with rarity `champion` | _fill in_ | champion status comes from the card table |
| Crowns / winner | `crowns` on each side; more crowns wins; equal is a draw | _fill in_ | `parse` |
| Trophies / rank | `startingTrophies` on each side (may be absent in Path of Legends) | _fill in_ | stored as `trophies_or_rank` |
| Rate limits | HTTP 429 when throttled; documented limits not published precisely | _fill in_ | fixed delay + exponential backoff (`config: api`) |
| Errors | 403 for wrong IP or bad key (`reason: accessDenied` / `accessDenied.invalidIp`), 404 for unknown player | _fill in_ | `api.ApiClient.get` |

## Known limitation until observed: Hero form

If Hero form can't be told apart from base form in battle data, then:

- `form_resolution.hero_field` stays `null`;
- every hero-capable card is recorded as `base`, and decks containing one carry `form_unknown`;
- the strength model maps any `hero` entry onto the base feature;
- search does not propose Hero forms on its own (you can still seed one with `Card@hero`);
- explanations show `FORM_UNKNOWN` for these cards.

Once a distinguishing field is observed, set `hero_field` to its name, re-run `python -m crdeck build`, and the hero forms become separate features.

## Observed output from `python -m crdeck gate`

_Paste the JSON summary here (it contains no key and no headers)._
