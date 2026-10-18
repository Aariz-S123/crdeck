"""Deck legality validator: the only code that decides legality (spec sections 2, 4).

Model: each deck entry is (card_id, form) with form in base / evo / hero.
An entry's slot kind is:
- "evo"      if form == "evo"
- "hero"     if form == "hero"
- "champion" if the card is a champion (base form)
- None       otherwise (a normal card; fits any slot)
Every entry with a kind must be matched to a distinct special slot that accepts
that kind. Normal cards fill the rest, including unused special slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Iterable

import yaml

from .cards import FORMS, CardTable
from .config import CONFIG_DIR

# Reason codes
WRONG_SIZE = "WRONG_SIZE"
TOO_MANY_CARDS = "TOO_MANY_CARDS"
DUPLICATE_CARD = "DUPLICATE_CARD"
UNKNOWN_CARD = "UNKNOWN_CARD"
INVALID_FORM = "INVALID_FORM"
FORM_NOT_AVAILABLE = "FORM_NOT_AVAILABLE"
TOO_MANY_CHAMPIONS = "TOO_MANY_CHAMPIONS"
NO_SLOT_FOR_SPECIALS = "NO_SLOT_FOR_SPECIALS"
BAD_PLACEMENT = "BAD_PLACEMENT"
NORMAL = "normal"


@dataclass(frozen=True, order=True)
class DeckCard:
    card_id: int
    form: str = "base"

    @property
    def key(self) -> str:
        return f"{self.card_id}:{self.form}"

    @classmethod
    def parse(cls, key: str) -> "DeckCard":
        cid, form = key.split(":")
        return cls(int(cid), form)


@dataclass(frozen=True)
class SpecialSlot:
    name: str
    accepts: frozenset[str]


@dataclass(frozen=True)
class DeckRules:
    deck_size: int
    special_slots: tuple[SpecialSlot, ...]
    max_champions: int

    @classmethod
    def from_dict(cls, d: dict) -> "DeckRules":
        slots = tuple(SpecialSlot(s["name"], frozenset(s["accepts"])) for s in d["special_slots"])
        return cls(deck_size=int(d["deck_size"]), special_slots=slots, max_champions=int(d["max_champions"]))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DeckRules":
        path = Path(path) if path else CONFIG_DIR / "deck_rules.yaml"
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))

    def with_max_champions(self, n: int) -> "DeckRules":
        return DeckRules(self.deck_size, self.special_slots, n)


@dataclass
class LegalityResult:
    legal: bool
    reasons: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    # entry key -> special slot name, for entries that need a special slot
    slots: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.legal


def slot_kind(entry: DeckCard, cards: CardTable) -> str | None:
    if entry.form == "evo":
        return "evo"
    if entry.form == "hero":
        return "hero"
    c = cards.get(entry.card_id)
    if c is not None and c.is_champion:
        return "champion"
    return None


def _assign(kinds: list[tuple[str, str]], slots: tuple[SpecialSlot, ...]) -> dict[str, str] | None:
    """Match (entry_key, kind) pairs to distinct slots. Deterministic: first valid assignment."""
    if len(kinds) > len(slots):
        return None
    if not kinds:
        return {}
    for perm in permutations(range(len(slots)), len(kinds)):
        if all(kinds[i][1] in slots[s].accepts for i, s in enumerate(perm)):
            return {kinds[i][0]: slots[s].name for i, s in enumerate(perm)}
    return None


_KIND_ORDER = {"evo": 0, "hero": 1, "champion": 2}


def _check_placement(entries: list[DeckCard], placement: dict[str, str], cards: CardTable, rules: DeckRules,
                     fail) -> dict[str, str]:
    """Verify a given placement {entry_key: slot name or "normal"}. Returns special-slot assignments."""
    slots = {s.name: s for s in rules.special_slots}
    n_normal = rules.deck_size - len(rules.special_slots)
    used: dict[str, str] = {}
    normal = 0
    for e in entries:
        where = placement.get(e.key)
        kind = slot_kind(e, cards)
        name = describe(e, cards)
        if where is None:
            fail(BAD_PLACEMENT, f"{name} has no slot in the placement")
            continue
        if where == NORMAL:
            normal += 1
            if kind is not None:
                fail(BAD_PLACEMENT, f"{name} is a {kind} and cannot sit in a normal slot")
            continue
        if where not in slots:
            fail(BAD_PLACEMENT, f"{name}: unknown slot {where!r}")
            continue
        if where in used:
            fail(BAD_PLACEMENT, f"slot {where} holds both {used[where]} and {name}")
            continue
        used[where] = name
        if kind is not None and kind not in slots[where].accepts:
            fail(BAD_PLACEMENT, f"{name} ({kind}) cannot sit in the {where} slot (accepts {sorted(slots[where].accepts)})")
    if normal > n_normal:
        fail(BAD_PLACEMENT, f"{normal} cards in normal slots; only {n_normal} exist")
    return {e.key: placement[e.key] for e in entries if slot_kind(e, cards) is not None and placement.get(e.key) in slots}


def describe(e: DeckCard, cards: CardTable) -> str:
    return cards.name(e.card_id) + ("" if e.form == "base" else f" ({e.form})")


def _check(entries: Iterable[DeckCard], cards: CardTable, rules: DeckRules, complete: bool,
           placement: dict[str, str] | None = None) -> LegalityResult:
    entries = list(entries)
    reasons: list[str] = []
    details: list[str] = []

    def fail(code: str, msg: str) -> None:
        if code not in reasons:
            reasons.append(code)
        details.append(msg)

    n = len(entries)
    if complete and n != rules.deck_size:
        fail(WRONG_SIZE, f"deck has {n} cards; rule is exactly {rules.deck_size}")
    if not complete and n > rules.deck_size:
        fail(TOO_MANY_CARDS, f"partial deck has {n} cards; max {rules.deck_size}")

    seen: dict[int, DeckCard] = {}
    for e in entries:
        if e.card_id in seen:
            fail(DUPLICATE_CARD, f"card {cards.name(e.card_id)} appears twice ({seen[e.card_id].form} and {e.form})")
        seen[e.card_id] = e
        if e.form not in FORMS:
            fail(INVALID_FORM, f"{cards.name(e.card_id)}: form {e.form!r} not in {FORMS}")
            continue
        c = cards.get(e.card_id)
        if c is None:
            fail(UNKNOWN_CARD, f"card id {e.card_id} not in card table")
            continue
        if e.form not in c.allowed_forms():
            fail(FORM_NOT_AVAILABLE, f"{c.name} has no {e.form} form")

    n_champ = sum(1 for e in entries if (c := cards.get(e.card_id)) is not None and c.is_champion)
    if n_champ > rules.max_champions:
        fail(TOO_MANY_CHAMPIONS, f"{n_champ} champions; max_champions is {rules.max_champions}")

    if placement is not None:
        assignment = _check_placement(entries, placement, cards, rules, fail)
        return LegalityResult(legal=not reasons, reasons=reasons, details=details, slots=assignment)

    kinds = sorted(
        ((e.key, k) for e in entries if (k := slot_kind(e, cards)) is not None),
        key=lambda t: (_KIND_ORDER[t[1]], t[0]),
    )
    assignment = _assign(kinds, rules.special_slots)
    if assignment is None:
        counts: dict[str, int] = {}
        for _, k in kinds:
            counts[k] = counts.get(k, 0) + 1
        fail(
            NO_SLOT_FOR_SPECIALS,
            f"special cards {counts} cannot be placed in slots "
            + ", ".join(f"{s.name}({'/'.join(sorted(s.accepts))})" for s in rules.special_slots),
        )
        assignment = {}

    return LegalityResult(legal=not reasons, reasons=reasons, details=details, slots=assignment)


def check_deck(entries: Iterable[DeckCard], cards: CardTable, rules: DeckRules,
               placement: dict[str, str] | None = None) -> LegalityResult:
    """Full legality check of a complete deck.

    Without `placement`, the deck is legal if some placement of its special cards
    into special slots exists (the returned `slots` is one such placement).
    With `placement` ({entry_key: "evo" | "hero" | "wild" | "normal"}), that exact
    placement is checked, e.g. a champion placed in a normal slot is rejected.
    """
    return _check(entries, cards, rules, complete=True, placement=placement)


def check_partial(entries: Iterable[DeckCard], cards: CardTable, rules: DeckRules) -> LegalityResult:
    """Can this partial deck still become legal by adding cards?

    Adding a normal card never breaks a constraint, so a partial deck can be
    completed iff it passes every check except the exact size (given enough
    distinct normal cards exist, which any real card pool satisfies).
    """
    return _check(entries, cards, rules, complete=False)


def deck_key(entries: Iterable[DeckCard]) -> str:
    """Canonical deck key: sorted card_id:form pairs (spec section 5)."""
    return "|".join(sorted(e.key for e in entries))


def parse_deck_key(key: str) -> list[DeckCard]:
    return [DeckCard.parse(k) for k in key.split("|") if k]
