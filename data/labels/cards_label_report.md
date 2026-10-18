# Card label bootstrap report

Source: `data/labels/source/cards_meta.csv` (187 rows).
Output: `data/labels/cards.csv` (124 base cards, 43 with Evolution, 19 with Hero form, 8 champions).

Roles, targets, win conditions and the champion list are **drafts** (label_version `v0-draft`).
Review them, fix anything you disagree with, and bump `label_version`.
Rows with a note need your attention first.

The meta columns in the source (rating, usage, win_rate, cwr) are not used by any model:
the models learn only from battles collected through the official API.

## Issues found in the source CSV

- Duplicate row `Skeleton Barrel`: kept first (55/8/52), dropped (36/2/45) [rating/usage/win_rate].
- Elixir mismatch: `Electro Giant Evolution` = 8 vs `Electro Giant` = 7; kept base value (API /cards overrides).
- Elixir mismatch: `Hero Giant` = 7 vs `Giant` = 5; kept base value (API /cards overrides).
- Elixir mismatch: `Ice Spirit Evolution` = 2 vs `Ice Spirit` = 1; kept base value (API /cards overrides).
- Type mismatch: `Mortar Evolution` = spell vs `Mortar` = building; kept base value.
- Elixir mismatch: `Royal Hogs Evolution` = 5 vs `Royal Hogs` = 4; kept base value (API /cards overrides).
- Elixir mismatch: `Skeletons Evolution` = 2 vs `Skeletons` = 1; kept base value (API /cards overrides).
