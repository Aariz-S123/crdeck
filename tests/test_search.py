"""Search never returns an illegal deck; seeds are honored; errors are clear (spec 9.5, section 10)."""

from __future__ import annotations

import copy

import pytest

from crdeck.explain import build_explanation, has_win_condition
from crdeck.rules import check_deck, parse_deck_key
from crdeck.search import Searcher, SeedError, parse_seed


def test_three_seeds_all_outputs_legal_and_contain_seeds(small_ctx):
    ctx = small_ctx
    s = Searcher(ctx)
    seeds = [parse_seed(x, ctx.cards) for x in ("Hog Rider", "Knight@evo", "Fireball")]
    res = s.complete(seeds)
    assert len(res) >= 1
    for d in res:
        assert check_deck(d.entries, ctx.cards, ctx.rules).legal
        assert len(d.entries) == 8
        for e in seeds:
            assert e in d.entries


def test_empty_seed_and_one_seed(small_ctx):
    s = Searcher(small_ctx)
    for seeds in ([], [parse_seed("Golem", small_ctx.cards)]):
        res = s.complete(seeds)
        assert res and all(check_deck(d.entries, small_ctx.cards, small_ctx.rules).legal for d in res)


def test_results_are_diverse(small_ctx):
    res = Searcher(small_ctx).complete([parse_seed("Hog Rider", small_ctx.cards)])
    ids = [{e.card_id for e in d.entries} for d in res]
    md = small_ctx.cfg["search"]["min_diff_cards"]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            assert len(ids[i] - ids[j]) >= md


def test_impossible_seed_raises_clear_error(small_ctx):
    s = Searcher(small_ctx)
    with pytest.raises(SeedError, match="champions"):
        s.complete([parse_seed(x, small_ctx.cards) for x in ("Archer Queen", "Golden Knight", "Mighty Miner")])
    with pytest.raises(SeedError, match="cannot be placed"):
        s.complete([parse_seed(x, small_ctx.cards) for x in ("Archers@evo", "Bats@evo", "Zap@evo")])
    with pytest.raises(SeedError, match="no evo form"):
        s.complete([parse_seed("Hog Rider@evo", small_ctx.cards)])


def test_require_win_condition_filter(small_ctx):
    ctx = copy.copy(small_ctx)
    ctx.cfg = copy.deepcopy(small_ctx.cfg)
    ctx.cfg["search"]["require_win_condition"] = True
    res = Searcher(ctx).complete([parse_seed("Valkyrie", ctx.cards)])
    assert all(has_win_condition(d.entries, ctx.cards) for d in res)


def test_deck_without_air_defense_is_recommended_with_warning(small_ctx):
    """Warnings are advisory: a top-scoring no-air deck is still returned, and flagged."""
    ctx = copy.copy(small_ctx)
    ctx.cfg = copy.deepcopy(small_ctx.cfg)
    ctx.cfg["search"]["synergy_weight"] = 0.0  # objective = win prob only, monotone in utility
    strength = copy.deepcopy(small_ctx.strength)
    ctx.strength = strength
    pool = [e for e in Searcher(small_ctx).candidates
            if e.form == "base" and not ctx.cards[e.card_id].is_champion
            and "air_defense" not in ctx.cards[e.card_id].roles]
    boosted = pool[:8]
    assert len(boosted) == 8
    for e in boosted:
        strength.card_weights[f"{e.card_id}:base"] = 0.5
    res = Searcher(ctx, cooccurrence_weight=0.0).complete([])
    top = res[0]
    assert {e.card_id for e in top.entries} == {e.card_id for e in boosted}
    x = build_explanation(top.entries, ctx)
    assert x.legality["legal"]
    groups = {g["group"]: g for g in x.warnings}
    assert "air" in groups and groups["air"]["warnings"][0]["code"] == "NO_AIR_DEFENSE"


def test_swaps_are_legal_and_ranked(small_ctx):
    ctx = small_ctx
    s = Searcher(ctx)
    deck = s.complete([parse_seed("Hog Rider", ctx.cards)])[0]
    swaps = s.swaps(deck.entries, locked=[parse_seed("Hog Rider", ctx.cards)])
    assert swaps
    assert all(sw["replace"] != "Hog Rider" for sw in swaps)
    for sw in swaps:
        assert check_deck(parse_deck_key(sw["new_deck_key"]), ctx.cards, ctx.rules).legal
        assert sw["reason"]
    by_card: dict[str, list[float]] = {}
    for sw in swaps:
        by_card.setdefault(sw["replace"], []).append(sw["delta_objective"])
    for deltas in by_card.values():
        assert deltas == sorted(deltas, reverse=True) and len(deltas) <= ctx.cfg["search"]["top_swaps"]


def test_search_is_deterministic(small_ctx):
    seeds = [parse_seed("Golem", small_ctx.cards)]
    a = Searcher(small_ctx).complete(seeds)
    b = Searcher(small_ctx).complete(seeds)
    assert [d.key for d in a] == [d.key for d in b]
