from __future__ import annotations

from crdeck.config import model_config
from crdeck.explain import build_explanation, group_warnings, render_text, structural_warnings

WCFG = model_config()["warnings"]


def names(C, ns):
    return [C(n) for n in ns]


def test_spell_warnings_grouped_into_one_root_cause(C, cards):
    d = names(C, ["Hog Rider", "Musketeer", "Ice Spirit", "Skeletons", "Cannon", "Knight", "Valkyrie", "Ice Golem"])
    ws = structural_warnings(d, cards, WCFG)
    codes = {w.code for w in ws}
    assert {"NO_SPELL", "NO_SMALL_SPELL"} <= codes
    groups = group_warnings(ws)
    spell = [g for g in groups if g["group"] == "spells"]
    assert len(spell) == 1 and len(spell[0]["warnings"]) == 2


def test_air_warnings_are_one_group(C, cards):
    d = names(C, ["Hog Rider", "Fireball", "The Log", "Skeletons", "Cannon", "Knight", "Valkyrie", "Ice Golem"])
    groups = group_warnings(structural_warnings(d, cards, WCFG))
    air = [g for g in groups if g["group"] == "air"]
    assert len(air) == 1 and air[0]["warnings"][0]["code"] == "NO_AIR_DEFENSE"
    assert "Balloon" in air[0]["root_cause"]


def test_elixir_warning_reports_rule_and_observed_value(C, cards):
    d = names(C, ["Golem", "P.E.K.K.A", "Lightning", "Rocket", "Three Musketeers", "Royal Recruits", "Elixir Collector", "Mega Knight"])
    ws = {w.code: w for w in structural_warnings(d, cards, WCFG)}
    w = ws["ELIXIR_HIGH"]
    assert w.observed > 4.5 and "rule <= 4.5" in w.message
    assert "DUPLICATE_ROLE_BIG_SPELL" in ws and "DUPLICATE_ROLE_TANK" in ws


def test_balanced_deck_has_no_structural_warnings(C, cards):
    d = names(C, ["Hog Rider", "Fireball", "The Log", "Musketeer", "Ice Spirit", "Cannon", "Archers", "Skeletons"])
    assert structural_warnings(d, cards, WCFG) == []


def test_explanation_has_every_required_part(small_ctx):
    from crdeck.search import Searcher, parse_seed
    s = Searcher(small_ctx)
    d = s.complete([parse_seed("Hog Rider", small_ctx.cards)])[0]
    x = build_explanation(d.entries, small_ctx, s.objective_dict(d))
    assert x.legality["legal"] is True
    assert set(x.score) >= {"meta_win_prob", "interval", "test_battles_exact_deck", "test_window", "opponent_decks"}
    assert x.score["interval"][0] <= x.score["meta_win_prob"] <= x.score["interval"][1]
    assert x.archetype["label"]
    for p in x.synergy_top:
        assert set(p) >= {"lift", "games", "shrunk_wr", "interval"}
        assert p["games"] >= small_ctx.synergy.min_games
    assert "objective" in x.objective and "formula" in x.objective
    assert "SYNTHETIC" in x.source
    states = {d_["state"] for d_ in x.data_quality}
    assert states <= {"INSUFFICIENT_SAMPLE", "UNKNOWN_CARD", "FORM_UNKNOWN", "LOW_CARD_DATA", "UNSEEN_DECK"}
    text = render_text(x)
    assert "Est. win rate" in text and "Legal: True" in text
