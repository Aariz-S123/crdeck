"""Legality validator: every slot rule, legal and illegal (spec 9.5, section 10 table)."""

from __future__ import annotations

import pytest

from crdeck import rules as R
from crdeck.rules import DeckRules, check_deck, check_partial, deck_key, parse_deck_key

FILLER = ["Hog Rider", "Fireball", "The Log", "Ice Spirit", "Skeletons", "Cannon", "Golem", "Electro Spirit",
          "Goblins", "Ice Golem", "Giant"]


def deck(C, specials, n=8):
    """specials: list of DeckCard; fill to n with base filler cards not already used."""
    used = {e.card_id for e in specials}
    out = list(specials)
    for name in FILLER:
        if len(out) >= n:
            break
        e = C(name)
        if e.card_id not in used:
            out.append(e)
            used.add(e.card_id)
    return out


def test_plain_base_deck_is_legal(C, cards, rules):
    r = check_deck(deck(C, []), cards, rules)
    assert r.legal, r.details
    assert r.slots == {}


def test_nine_cards_rejected(C, cards, rules):
    d = deck(C, [], n=8) + [C("Goblins")]
    assert len(d) == 9
    r = check_deck(d, cards, rules)
    assert not r.legal and R.WRONG_SIZE in r.reasons


def test_seven_cards_rejected(C, cards, rules):
    r = check_deck(deck(C, [], n=7), cards, rules)
    assert not r.legal and R.WRONG_SIZE in r.reasons


def test_duplicate_card_rejected(C, cards, rules):
    d = deck(C, [], n=7) + [C("Hog Rider")]
    r = check_deck(d, cards, rules)
    assert not r.legal and R.DUPLICATE_CARD in r.reasons


def test_same_card_base_and_evo_rejected(C, cards, rules):
    d = deck(C, [C("Knight", "evo")], n=7) + [C("Knight")]
    r = check_deck(d, cards, rules)
    assert not r.legal and R.DUPLICATE_CARD in r.reasons


def test_same_card_evo_and_hero_rejected(C, cards, rules):
    d = deck(C, [C("Knight", "evo")], n=7) + [C("Knight", "hero")]
    r = check_deck(d, cards, rules)
    assert not r.legal and R.DUPLICATE_CARD in r.reasons


def test_two_evolutions_plus_one_hero_is_legal(C, cards, rules):
    d = deck(C, [C("Archers", "evo"), C("Bats", "evo"), C("Musketeer", "hero")])
    r = check_deck(d, cards, rules)
    assert r.legal, r.details
    assert sorted(r.slots.values()) == ["evo", "hero", "wild"]
    assert r.slots[C("Musketeer", "hero").key] == "hero"


def test_three_evolutions_rejected(C, cards, rules):
    d = deck(C, [C("Archers", "evo"), C("Bats", "evo"), C("Zap", "evo")])
    r = check_deck(d, cards, rules)
    assert not r.legal and R.NO_SLOT_FOR_SPECIALS in r.reasons


def test_two_heroes_plus_evo_is_legal(C, cards, rules):
    d = deck(C, [C("Knight", "hero"), C("Musketeer", "hero"), C("Archers", "evo")])
    assert check_deck(d, cards, rules).legal


def test_two_heroes_two_evos_rejected(C, cards, rules):
    d = deck(C, [C("Knight", "hero"), C("Musketeer", "hero"), C("Archers", "evo"), C("Bats", "evo")])
    assert not check_deck(d, cards, rules).legal


def test_champion_needs_a_special_slot(C, cards, rules):
    # evo + wild-evo + hero fill every special slot; the champion has nowhere to go
    d = deck(C, [C("Archers", "evo"), C("Bats", "evo"), C("Musketeer", "hero"), C("Archer Queen")])
    r = check_deck(d, cards, rules)
    assert not r.legal and R.NO_SLOT_FOR_SPECIALS in r.reasons


def test_champion_in_normal_slot_rejected_by_placement(C, cards, rules):
    d = deck(C, [C("Archer Queen")])
    placement = {e.key: "normal" for e in d}
    placement[d[1].key] = "hero"  # a base card in the hero slot is fine
    r = check_deck(d, cards, rules, placement=placement)
    assert not r.legal and R.BAD_PLACEMENT in r.reasons
    placement = {e.key: ("hero" if e == C("Archer Queen") else "normal") for e in d}
    placement[d[-1].key] = "wild"  # 7 normal cards would exceed the 5 normal slots
    placement[d[-2].key] = "evo"
    assert check_deck(d, cards, rules, placement=placement).legal


def test_placement_rejects_evo_in_hero_slot_and_double_use(C, cards, rules):
    d = deck(C, [C("Archers", "evo"), C("Bats", "evo")])
    p = {e.key: "normal" for e in d}
    p[C("Archers", "evo").key] = "hero"
    p[C("Bats", "evo").key] = "evo"
    p[d[2].key] = "wild"
    r = check_deck(d, cards, rules, placement=p)
    assert not r.legal and any("cannot sit in the hero slot" in x for x in r.details)
    p[C("Archers", "evo").key] = "evo"
    r = check_deck(d, cards, rules, placement=p)
    assert not r.legal and any("holds both" in x for x in r.details)


def test_champion_with_evo_and_hero_is_legal(C, cards, rules):
    d = deck(C, [C("Archer Queen"), C("Archers", "evo")])
    assert check_deck(d, cards, rules).legal
    # champion + hero: hero slot and wild slot
    d = deck(C, [C("Archer Queen"), C("Knight", "hero"), C("Bats", "evo")])
    assert check_deck(d, cards, rules).legal


def test_two_champions_follows_max_champions(C, cards, rules):
    d = deck(C, [C("Archer Queen"), C("Golden Knight")])
    r1 = check_deck(d, cards, rules.with_max_champions(1))
    assert not r1.legal and R.TOO_MANY_CHAMPIONS in r1.reasons
    r2 = check_deck(d, cards, rules.with_max_champions(2))
    assert r2.legal, r2.details
    assert sorted(r2.slots.values()) == ["hero", "wild"]


def test_config_default_max_champions_is_one(rules):
    assert rules.max_champions == 1


def test_wild_slot_accepts_is_configurable(C, cards):
    narrow = DeckRules.from_dict({
        "deck_size": 8, "max_champions": 1,
        "special_slots": [{"name": "evo", "accepts": ["evo"]}, {"name": "hero", "accepts": ["hero", "champion"]},
                          {"name": "wild", "accepts": ["evo", "hero"]}],
    })
    two_champs = deck(C, [C("Archer Queen"), C("Golden Knight")])
    assert check_deck(two_champs, cards, rules_default_two_champs()).legal
    assert not check_deck(two_champs, cards, narrow.with_max_champions(2)).legal  # wild refuses champions here
    # champion + hero still fits: champion in hero slot, hero in wild
    r = check_deck(deck(C, [C("Archer Queen"), C("Knight", "hero")]), cards, narrow)
    assert r.legal and r.slots[C("Archer Queen").key] == "hero"


def rules_default_two_champs():
    return DeckRules.load().with_max_champions(2)


def test_form_not_available_rejected(C, cards, rules):
    d = deck(C, [C("Hog Rider", "evo")])
    r = check_deck(d, cards, rules)
    assert not r.legal and R.FORM_NOT_AVAILABLE in r.reasons
    d = deck(C, [C("Archers", "hero")])
    assert R.FORM_NOT_AVAILABLE in check_deck(d, cards, rules).reasons


def test_invalid_form_and_unknown_card(C, cards, rules):
    d = deck(C, [], n=7) + [R.DeckCard(123, "base")]
    assert R.UNKNOWN_CARD in check_deck(d, cards, rules).reasons
    d = deck(C, [C("Knight", "golden")])
    assert R.INVALID_FORM in check_deck(d, cards, rules).reasons


def test_empty_special_slots_are_fine(C, cards, rules):
    d = deck(C, [C("Knight", "hero")])
    assert check_deck(d, cards, rules).legal


def test_partial_checks(C, cards, rules):
    assert check_partial([C("Hog Rider"), C("Knight", "evo")], cards, rules).legal
    three_champs = [C("Archer Queen"), C("Golden Knight"), C("Mighty Miner")]
    r = check_partial(three_champs, cards, rules)
    assert not r.legal and R.TOO_MANY_CHAMPIONS in r.reasons
    r = check_partial(three_champs, cards, rules.with_max_champions(3))
    assert not r.legal and R.NO_SLOT_FOR_SPECIALS in r.reasons  # only 2 slots take champions
    assert not check_partial([C("Archers", "evo"), C("Bats", "evo"), C("Zap", "evo")], cards, rules).legal


def test_deck_key_is_order_independent(C):
    a = [C("Hog Rider"), C("Knight", "evo"), C("Zap")]
    assert deck_key(a) == deck_key(list(reversed(a)))
    assert deck_key(a) != deck_key([C("Hog Rider"), C("Knight"), C("Zap")])
    assert sorted(parse_deck_key(deck_key(a))) == sorted(a)
