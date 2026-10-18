"""Interactive archetype labeling (spec 7.3).

    python -m crdeck label --interactive

Shows decks from the k-means worklist one at a time and appends each answer to
the archetype label file right away, so you can stop and resume any time.
The first `heldout_target` labels go to split "heldout" (label these before
fitting or tuning anything); after that, labels go to "train".
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from .archetype import ARCHETYPES, LABEL_COLUMNS, load_labels
from .cards import CardTable
from .explain import avg_elixir, describe_entry
from .rules import parse_deck_key

HELP = "  ".join(f"{i}={a}" for i, a in enumerate(ARCHETYPES, 1)) + "  s=skip  q=quit"


def deck_summary(deck_key: str, cards: CardTable) -> str:
    entries = parse_deck_key(deck_key)
    lines = []
    for e in sorted(entries, key=lambda e: (cards[e.card_id].elixir or 0) if e.card_id in cards else 0):
        if e.card_id not in cards:
            lines.append(f"  <unknown card {e.card_id}>")
            continue
        c = cards[e.card_id]
        tags = ", ".join(([] if not c.is_win_condition else ["WIN CONDITION"]) + list(c.roles))
        el = "?" if c.elixir is None or c.elixir_variable else f"{c.elixir:g}"
        lines.append(f"  {describe_entry(e, cards):32s} {el:>2}  {tags}")
    ae = avg_elixir(entries, cards)
    lines.append(f"  avg elixir {ae:.2f}" if ae is not None else "  avg elixir n/a")
    return "\n".join(lines)


def next_split(labels: pd.DataFrame, heldout_target: int) -> str:
    return "heldout" if (labels["split"] == "heldout").sum() < heldout_target else "train"


def append_label(path: Path, deck_key: str, archetype: str, split: str, notes: str = "") -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LABEL_COLUMNS)
        w.writerow([deck_key, archetype, split, date.today().isoformat(), notes])


def run(worklist: pd.DataFrame, cards: CardTable, labels_path: Path, heldout_target: int = 20,
        ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> dict:
    """Label decks from `worklist` (needs a deck_key column). Returns counts."""
    labels = load_labels(labels_path)
    done = set(labels["deck_key"])
    todo = [k for k in worklist["deck_key"] if k not in done]
    counts = {"labeled": 0, "skipped": 0, "remaining": len(todo)}
    say(f"{len(done)} decks already labeled "
        f"({(labels['split'] == 'heldout').sum()} heldout / {(labels['split'] == 'train').sum()} train); "
        f"{len(todo)} in the worklist.")
    for i, k in enumerate(todo, 1):
        split = next_split(labels, heldout_target)
        say(f"\nDeck {i}/{len(todo)}  (this label goes to: {split})")
        say(deck_summary(k, cards))
        while True:
            ans = ask(f"{HELP}\n> ").strip().lower()
            if ans in {"q", "quit"}:
                counts["remaining"] = len(todo) - i + 1
                return counts
            if ans in {"s", "skip", ""}:
                counts["skipped"] += 1
                break
            if ans.isdigit() and 1 <= int(ans) <= len(ARCHETYPES):
                arch = ARCHETYPES[int(ans) - 1]
                append_label(labels_path, k, arch, split)
                labels = pd.concat([labels, pd.DataFrame([{"deck_key": k, "archetype": arch, "split": split,
                                                           "labeled_at": date.today().isoformat(), "notes": ""}])],
                                   ignore_index=True)
                counts["labeled"] += 1
                break
            say("  not understood")
    counts["remaining"] = 0
    return counts
