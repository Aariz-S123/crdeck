"""Modes (Ranked / Trophy Road / other) from type + gameMode + deckSelection, mode-filtered models, run log."""

from __future__ import annotations

import pytest

from crdeck import parse as P
from crdeck.config import collection_config
from crdeck.parse import FormConfig, ModeRules, mode_slug, modes_for, parse_battlelog
from tests.test_parse import DECK1, DECK2, side


def battle(cards, btype, gm, sel="collection", arena="Legendary Arena", t="20261019T120000.000Z"):
    return {"battleTime": t, "type": btype, "gameMode": {"name": gm}, "deckSelection": sel, "arena": {"name": arena},
            "team": [side(cards, "#AAA", DECK1, 2)], "opponent": [side(cards, "#BBB", DECK2, 1)]}


@pytest.fixture(scope="module")
def rules():
    return ModeRules.from_collection(collection_config())


@pytest.mark.parametrize("btype,gm,sel,want", [
    ("pathOfLegend", "Ranked1v1_NewArena", "collection", "ranked"),
    ("pathOfLegend", "Ranked1v1_NewArena2", "collection", "ranked"),
    ("trail", "Ladder", "collection", "trophy_road"),
    ("PvP", "Ladder", "collection", "trophy_road"),
    ("trail", "Challenge_AllCards_EventDeck_NoSet", "eventDeck", "other"),   # event deck, not the player's
    ("trail", "Chaos_1v1_Draft", "draft", "other"),                         # draft
    ("tournament", "Draft_Competitive", "draftCompetitive", "other"),
    ("friendly", "Friendly", "collection", "other"),                        # own deck, but a friendly
    ("riverRaceDuel", "CW_Duel_1v1", "warDeckPick", "other"),
    ("pathOfLegend", "Ranked1v1_NewArena", "draft", "other"),               # deck selection must be collection
])
def test_mode_assignment(rules, btype, gm, sel, want):
    assert rules.assign({"type": btype, "gameMode": {"name": gm}, "deckSelection": sel}) == want


def test_parse_records_mode_arena_and_filters_other(cards, rules):
    bs = [battle(cards, "pathOfLegend", "Ranked1v1_NewArena", t="20261019T120000.000Z"),
          battle(cards, "trail", "Ladder", arena="Seasonal Arena II", t="20261019T130000.000Z"),
          battle(cards, "trail", "Chaos_1v1_Draft", sel="draft", t="20261019T140000.000Z")]
    b, d, _ = parse_battlelog(bs, "#AAA", "", cards, FormConfig(), modes=rules)
    got = [(x["mode"], x["arena"], x["status"]) for x in b]
    assert got == [("ranked", "Legendary Arena", P.OK), ("trophy_road", "Seasonal Arena II", P.OK),
                   ("other", "Legendary Arena", P.FILTERED_TYPE)]


def test_combined_modes_and_slugs():
    cfg = collection_config()
    assert modes_for(cfg, "all") == ["ranked", "trophy_road"]
    assert modes_for(cfg, "ranked") == ["ranked"]
    assert mode_slug("trophy_road", "Seasonal Arena II") == "trophy_road__seasonal_arena_ii"


def test_mode_filtered_context_and_not_enough_data(small_ctx):
    from crdeck.pipeline import NoDataError, load_context
    c = small_ctx.counts
    assert c["modes"]["trophy_road"]["OK"] > 0 and c["modes"]["ranked"]["OK"] > 0
    tr = load_context(paths=small_ctx.paths, mode="trophy_road", cache=False)
    assert tr.mode == "trophy_road" and tr.slug == "trophy_road"
    n_tr = len(tr.split.train) + len(tr.split.valid) + len(tr.split.test)
    assert n_tr == c["modes"]["trophy_road"]["OK"]
    assert len(small_ctx.split.train) + len(small_ctx.split.valid) + len(small_ctx.split.test) == c["modes"]["ranked"]["OK"]
    with pytest.raises(NoDataError, match="not enough data"):
        load_context(paths=small_ctx.paths, mode="trophy_road", arena="Spirit Square", cache=False)


def test_run_log_build_section(small_ctx):
    from crdeck import runlog
    log = runlog.read(small_ctx.paths)
    b = log["build"]
    assert b["battles_after_dedupe"] == small_ctx.counts["battles_after_dedupe"]
    assert b["windows"] and b["windows"][0]["battle_logs"] > 0
    assert "ranked" in b["modes"] and b["written_at"]
