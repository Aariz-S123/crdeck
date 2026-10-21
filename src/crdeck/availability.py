"""Which cards, forms and special slots a player in a given Trophy Road arena can use.

Sources (config/card_unlocks.yaml, written by scripts/fetch_wiki_unlocks.py from the Clash
Royale Wiki): the arena where each card unlocks, and the arenas that unlock the Evolution,
Hero and Wild slots. Players are never moved back to an earlier arena, so everything that
unlocks in an arena or earlier is available there.

Measured against the collected battles (2026-10-20), the slot rules held with no exceptions,
but 4-21% of decks in Arenas 3-13 held a card the wiki places in a later arena (cards also
come from chests and shards). So a card also counts as available in an arena when at least
`min_seen_decks` decks in that arena's battles used it ("seen early"), as the project owner chose.

Only single-arena Trophy Road models are restricted; Ranked and the mixed models are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yaml

from .config import CONFIG_DIR
from .parse import mode_groups
from .rules import DeckCard

MIN_SEEN_DECKS = 3


@dataclass(frozen=True)
class Availability:
    arena: str
    number: int                                   # 1 = Goblin Stadium, in the config's game order
    slots: frozenset[str]                         # special slots unlocked here
    unlock: dict[int, int] = field(default_factory=dict)       # card_id -> wiki unlock arena number
    unlock_name: dict[int, str] = field(default_factory=dict)  # card_id -> wiki unlock arena name
    seen_early: dict[int, int] = field(default_factory=dict)   # card_id -> decks here using it before its wiki arena
    slot_unlock: dict[str, int] = field(default_factory=dict)  # slot name -> arena number

    def card_ok(self, card_id: int) -> bool:
        return self.unlock.get(card_id, 0) <= self.number or card_id in self.seen_early

    def form_ok(self, e: DeckCard) -> bool:
        if not self.card_ok(e.card_id):
            return False
        if e.form == "evo":
            return "evo" in self.slots
        if e.form == "hero":
            return "hero" in self.slots
        return True

    def why_not(self, e: DeckCard, name: str) -> str:
        if not self.card_ok(e.card_id):
            return f"{name} unlocks at {self.unlock_name.get(e.card_id, 'a later arena')} (Arena {self.unlock.get(e.card_id)})"
        kind = {"evo": "Evolutions", "hero": "Heroes"}[e.form]
        return f"{kind} unlock at Arena {self.slot_unlock[e.form]}"


def load_unlocks() -> dict:
    path = CONFIG_DIR / "card_unlocks.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def for_group(ccfg: dict, mode: str, group: str | None, battles: pd.DataFrame, dib: pd.DataFrame,
              min_seen_decks: int = MIN_SEEN_DECKS) -> Availability | None:
    """Availability for one Trophy Road arena, or None when the model is not a single arena."""
    if mode != "trophy_road" or group is None:
        return None
    order = {g["name"]: g["order"] for g in mode_groups(ccfg, "trophy_road")}
    u = load_unlocks()
    if group not in order or not u:
        return None
    n = order[group]
    slot_unlock = {k: int(v) for k, v in u["slot_unlock_arena"].items()}
    unlock = {int(v["card_id"]): int(v["arena_number"]) for v in u["cards"].values()}
    names = {int(v["card_id"]): str(v["arena"]) for v in u["cards"].values()}
    keys = battles.loc[(battles["mode"] == mode) & (battles["group"] == group) & (battles["status"] == "OK"), "battle_key"]
    decks = dib.loc[dib["battle_key"].isin(keys), "deck_key"]
    seen: dict[int, int] = {}
    for k in decks:
        for cid in {int(x.split(":")[0]) for x in k.split("|") if x}:
            if unlock.get(cid, 0) > n:
                seen[cid] = seen.get(cid, 0) + 1
    seen = {c: v for c, v in seen.items() if v >= min_seen_decks}
    slots = frozenset(s for s, a in slot_unlock.items() if a <= n)
    return Availability(group, n, slots, unlock, names, seen, slot_unlock)
