"""Model files in two parts, so pages that don't explain decks download less (BLUEPRINT 8.8).

web/models/<slug>.json keeps everything the engine needs to start; web/models/<slug>.decks.json holds the two big
per-deck tables, `deck_appearances` and `test_deck_records` (about 5 MB of the 9 MB Ranked file). The builder, deck,
counters and How it works pages load both and merge them (web/common.js, loadMode); Card usage trends, Future meta,
Season readiness and All cards load the main part only.

A model file written before the split still works everywhere: the decks part is simply missing and nothing is merged.
"""

from __future__ import annotations

import json
from pathlib import Path

DECK_KEYS = ("deck_appearances", "test_deck_records")


def decks_path(main: Path) -> Path:
    return main.with_name(main.stem + ".decks.json")


def is_main(path: Path) -> bool:
    """A main model file (not a decks part, not a split piece list)."""
    return path.suffix == ".json" and not path.name.endswith((".decks.json", ".parts.json"))


def _dump(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def split_file(main: Path) -> bool:
    """Move the per-deck tables of one model file into its decks part. Returns False when there was nothing to move
    (already split). The two files merged give back exactly the original object."""
    main = Path(main)
    body = json.loads(main.read_text(encoding="utf-8"))
    if not any(k in body for k in DECK_KEYS):
        return False
    part = {k: body.pop(k) for k in DECK_KEYS if k in body}
    _dump(decks_path(main), part)
    _dump(main, body)
    return True


def load(main: Path) -> dict:
    """A model file with its decks part merged back in, whichever form it is stored in."""
    main = Path(main)
    body = json.loads(main.read_text(encoding="utf-8"))
    dp = decks_path(main)
    if dp.exists():
        body.update(json.loads(dp.read_text(encoding="utf-8")))
    return body


def split_all(models_dir: Path) -> list[str]:
    """Split every main model file in a folder. Returns the names that changed."""
    return [f.name for f in sorted(Path(models_dir).glob("*.json")) if is_main(f) and split_file(f)]
