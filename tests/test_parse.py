"""Parsing, dedupe and statuses on fixed fixture battles."""

from __future__ import annotations

import json

import pytest

from crdeck import parse as P
from crdeck.dataset import model_battles, time_split
from crdeck.parse import FormConfig, dedupe, parse_battlelog, parse_files

DECK1 = ["Hog Rider", "Fireball", "The Log", "Ice Spirit", "Skeletons", "Cannon", "Musketeer", "Knight"]
DECK2 = ["Golem", "Baby Dragon", "Lightning", "Mega Minion", "Tornado", "Lumberjack", "Barbarian Barrel", "Night Witch"]


def side(cards, tag, names, crowns, evo=()):
    out = []
    for n in names:
        c = {"name": n, "id": cards.by_name(n).card_id, "level": 14, "maxLevel": 16}
        if n in evo:
            c["evolutionLevel"] = 1
        out.append(c)
    return {"tag": tag, "crowns": crowns, "startingTrophies": 2500, "cards": out}


def battle(cards, t="20261010T120000.000Z", a=("#AAA", DECK1, 2), b=("#BBB", DECK2, 1), btype="pathOfLegend", evo_a=()):
    return {"battleTime": t, "type": btype, "gameMode": {"name": "Ranked"},
            "team": [side(cards, a[0], a[1], a[2], evo_a)], "opponent": [side(cards, b[0], b[1], b[2])]}


def flip(b):
    return {**b, "team": b["opponent"], "opponent": b["team"]}


FC = FormConfig(evo_field="evolutionLevel", hero_field=None)


def run(cards, logs):
    allb, alld, alls = [], [], []
    for tag, body in logs:
        b, d, s = parse_battlelog(body, tag, "2026-10-18T00:00:00Z", cards, FC, ["pathOfLegend"])
        allb += b; alld += d; alls += s
    return dedupe(allb, alld, alls)


def test_same_battle_from_both_logs_counted_once(cards):
    b = battle(cards)
    parsed = run(cards, [("#AAA", [b]), ("#BBB", [flip(b)])])
    assert len(parsed.battles) == 1
    assert parsed.counts["duplicates_removed"] == 1
    assert len(parsed.decks_in_battle) == 2
    assert parsed.battles["status"].item() == P.OK


def test_sides_are_canonical_and_winner_correct(cards):
    b = battle(cards, a=("#ZZZ", DECK1, 3), b=("#AAA", DECK2, 0))
    parsed = run(cards, [("#ZZZ", [b])])
    d = parsed.decks_in_battle.set_index("side")
    assert d.loc["A", "player_tag"] == "#AAA"
    assert bool(d.loc["A", "won"]) is False
    assert bool(d.loc["B", "won"]) is True
    assert parsed.battles["battle_key"].item() == "#AAA|#ZZZ|2026-10-10T12:00:00Z"


def test_mirror_match_excluded(cards):
    b = battle(cards, b=("#BBB", DECK1, 0))
    parsed = run(cards, [("#AAA", [b])])
    assert parsed.battles["status"].item() == P.MIRROR
    assert model_battles(parsed.battles, parsed.decks_in_battle).empty


def test_draw_excluded(cards):
    b = battle(cards, a=("#AAA", DECK1, 1), b=("#BBB", DECK2, 1))
    parsed = run(cards, [("#AAA", [b])])
    assert parsed.battles["status"].item() == P.DRAW
    assert parsed.decks_in_battle["won"].isna().all()


def test_unknown_card_kept_flagged_and_counted(cards):
    b = battle(cards)
    b["opponent"][0]["cards"][0] = {"name": "Mystery", "id": 1234567, "level": 1, "maxLevel": 1}
    parsed = run(cards, [("#AAA", [b])])
    assert parsed.battles["status"].item() == P.UNKNOWN_CARD
    assert parsed.counts["unknown_card_ids"] == [1234567]
    assert parsed.counts["status"][P.UNKNOWN_CARD] == 1
    assert model_battles(parsed.battles, parsed.decks_in_battle).empty


def test_deck_key_ignores_card_order_and_detects_evo(cards):
    b1 = battle(cards, t="20261010T120000.000Z", evo_a=("Knight",))
    b2 = battle(cards, t="20261010T130000.000Z", a=("#AAA", list(reversed(DECK1)), 2), evo_a=("Knight",))
    parsed = run(cards, [("#AAA", [b1, b2])])
    keys = parsed.decks_in_battle.query("player_tag == '#AAA'")["deck_key"].unique()
    assert len(keys) == 1
    assert f"{cards.by_name('Knight').card_id}:evo" in keys[0]


def test_form_unknown_flag_for_hero_capable_cards(cards):
    parsed = run(cards, [("#AAA", [battle(cards)])])
    d = parsed.decks_in_battle.set_index("player_tag")
    assert bool(d.loc["#AAA", "form_unknown"])  # Knight and Musketeer have hero forms


def test_hero_field_when_observable(cards):
    b = battle(cards)
    b["team"][0]["cards"][-1]["heroLevel"] = 1  # Knight
    bb, d, _ = parse_battlelog([b], "#AAA", "", cards, FormConfig("evolutionLevel", "heroLevel"))
    assert any(k.endswith(":hero") for k in d[0]["deck_key"].split("|"))


def test_other_statuses(cards):
    bad_time = battle(cards, t="yesterday")
    friendly = battle(cards, t="20261010T140000.000Z", btype="friendly")
    two_v_two = battle(cards, t="20261010T150000.000Z")
    two_v_two["team"].append(two_v_two["team"][0])
    short = battle(cards, t="20261010T160000.000Z")
    short["team"][0]["cards"] = short["team"][0]["cards"][:7]
    parsed = run(cards, [("#AAA", [bad_time, friendly, two_v_two, short])])
    assert sorted(parsed.battles["status"]) == sorted([P.BAD_TIME, P.FILTERED_TYPE, P.NOT_1V1, P.BAD_DECK])


def test_parse_time_formats():
    assert P.parse_time("20261010T120000.000Z").hour == 12
    assert P.parse_time("2026-10-10T12:00:00Z").tzinfo is not None
    assert P.parse_time("nope") is None


def test_parse_files_reads_wrapped_raw_and_skips_404(cards, tmp_path):
    b = battle(cards)
    (tmp_path / "AAA.json").write_text(json.dumps({"status": 200, "fetched_at": "x", "body": [b]}))
    (tmp_path / "BBB.json").write_text(json.dumps({"status": 200, "fetched_at": "y", "body": [flip(b)]}))
    (tmp_path / "CCC.json").write_text(json.dumps({"status": 404, "fetched_at": "z", "body": {"reason": "notFound"}}))
    parsed = parse_files(sorted(tmp_path.glob("*.json")), cards, FC, ["pathOfLegend"])
    assert parsed.counts["files"] == 3 and parsed.counts["files_without_battles"] == 1
    assert parsed.counts["battles_after_dedupe"] == 1


def test_time_split_is_chronological(cards):
    logs = [battle(cards, t=f"202610{d:02d}T120000.000Z") for d in range(1, 21)]
    parsed = run(cards, [("#AAA", logs)])
    mb = model_battles(parsed.battles, parsed.decks_in_battle)
    s = time_split(mb, 0.7, 0.15)
    assert s.train["battle_time"].max() < s.valid["battle_time"].min()
    assert s.valid["battle_time"].max() < s.test["battle_time"].min()
    assert len(s.train) + len(s.valid) + len(s.test) == 20
