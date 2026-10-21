"""Arena availability: wiki unlocks, cards seen early, slot unlocks, and the search respecting them."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from crdeck.availability import MIN_SEEN_DECKS, Availability, for_group, load_unlocks
from crdeck.config import collection_config
from crdeck.rules import DeckCard, check_partial
from crdeck.search import Searcher, SeedError

SLOT_UNLOCK = {"evo": 3, "hero": 5, "wild": 10}


def av(number, unlock, seen=None, slots=None):
    slots = slots if slots is not None else {s for s, a in SLOT_UNLOCK.items() if a <= number}
    return Availability("Test Arena", number, frozenset(slots), unlock, {c: f"Arena{n}" for c, n in unlock.items()},
                        seen or {}, SLOT_UNLOCK)


def test_cards_unlock_by_arena_or_when_seen_early():
    a = av(4, {1: 0, 2: 4, 3: 7, 4: 9}, seen={4: 12})
    assert a.card_ok(1) and a.card_ok(2)            # Training Camp, and this arena
    assert not a.card_ok(3)                         # later arena, never seen here
    assert a.card_ok(4)                             # later arena, but decks here use it
    assert "Arena7" in a.why_not(DeckCard(3, "base"), "Card 3")


def test_forms_follow_slot_unlocks():
    a = av(4, {1: 0})
    assert a.form_ok(DeckCard(1, "base")) and a.form_ok(DeckCard(1, "evo"))
    assert not a.form_ok(DeckCard(1, "hero"))
    assert a.why_not(DeckCard(1, "hero"), "x") == "x: Heroes unlock at Arena 5"
    assert not av(2, {1: 0}).form_ok(DeckCard(1, "evo"))


def test_low_arena_rules_lose_slots(cards, rules):
    evo_ids = [cid for cid in cards.ids if cards[cid].has_evolution][:2]
    champ = next(cid for cid in cards.ids if cards[cid].is_champion)
    only_evo = rules.with_slots({"evo"})
    assert [s.name for s in only_evo.special_slots] == ["evo"]
    two_evos = [DeckCard(i, "evo") for i in evo_ids]
    assert check_partial(two_evos, cards, rules).legal          # Evolution slot + Wild slot
    assert not check_partial(two_evos, cards, only_evo).legal   # no Wild slot below Arena 10
    assert not check_partial([DeckCard(champ, "base")], cards, rules.with_slots(set())).legal


def test_seen_early_needs_min_decks():
    cfg = collection_config()
    u = load_unlocks()
    late = next(v["card_id"] for v in u["cards"].values() if v["arena_number"] > 5)
    battles = pd.DataFrame([{"battle_key": f"b{i}", "mode": "trophy_road", "group": "Spell Valley", "status": "OK"} for i in range(4)])
    dib = pd.DataFrame([{"battle_key": f"b{i}", "deck_key": f"{late}:base|1:base" if i < MIN_SEEN_DECKS else "1:base"} for i in range(4)])
    a = for_group(cfg, "trophy_road", "Spell Valley", battles, dib)
    assert a.number == 4 and a.slots == frozenset({"evo"}) and a.seen_early == {late: MIN_SEEN_DECKS}
    fewer = for_group(cfg, "trophy_road", "Spell Valley", battles, dib.assign(deck_key="1:base").iloc[:1])
    assert late not in fewer.seen_early
    assert for_group(cfg, "ranked", "Master I", battles, dib) is None
    assert for_group(cfg, "trophy_road", None, battles, dib) is None


def test_search_refuses_locked_picks_and_never_uses_locked_cards(small_ctx):
    s0 = Searcher(small_ctx)
    keep: set[int] = set()
    for e in s0.candidates:  # 12 distinct normal cards stay unlocked, everything else is locked
        if e.form == "base" and not small_ctx.cards[e.card_id].is_champion and len(keep) < 12:
            keep.add(e.card_id)
    unlock = {cid: (0 if cid in keep else 99) for cid in small_ctx.cards.ids}
    a = av(4, unlock)
    ctx = dataclasses.replace(small_ctx, availability=a, rules=small_ctx.rules.with_slots(a.slots))
    s = Searcher(ctx)
    assert s.candidates and all(a.form_ok(e) for e in s.candidates)
    locked = next(DeckCard(cid, "base") for cid in small_ctx.cards.ids if cid not in keep)
    with pytest.raises(SeedError, match="not unlocked in Test Arena"):
        s.complete([locked])
    for d in s.complete([]):
        assert all(a.form_ok(e) for e in d.entries)
