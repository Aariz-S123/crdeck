"""The counter deck builder's core (crdeck.counters.builder_*), on the hand-made cases shared with the website
(tests/fixtures/counter_builder.json, also run by tests/web/counterbuild_test.cjs against web/counterbuild.js)."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from crdeck import counters as cm

FIX = json.loads((Path(__file__).parent / "fixtures" / "counter_builder.json").read_text(encoding="utf-8"))
K = {(a, b): k for a, b, k in FIX["pairs"]}
MODEL = SimpleNamespace(w=FIX["w"], k=lambda i, j: 0.0 if i == j else (K.get((i, j), 0.0) if i < j else -K.get((j, i), 0.0)))


@pytest.mark.parametrize("case", FIX["cases"], ids=[c["name"] for c in FIX["cases"]])
def test_fits_and_ranking_match_the_fixture(case):
    rows = []
    for key, z, fit in case["fits"]:
        gz, gfit = cm.builder_field_fit(key.split("|"), case["picks"], MODEL)
        assert gz == pytest.approx(z, abs=1e-12) and gfit == pytest.approx(fit, abs=1e-12)
        rows.append(key)
    assert cm.builder_shares(case["picks"]) == case["share"]


def test_one_fit_by_hand():
    """Deck {1, 6, 7, 8, 12, 13, 15, 20} against picks {5, 6, 9} at share 1, written out term by term."""
    w, case = FIX["w"], FIX["cases"][0]
    deck = ["1:base", "6:base", "7:base", "8:base", "12:base", "13:base", "15:base", "20:base"]
    own = sum(w[c] for c in deck)
    field = w["5:base"] + w["6:base"] + w["9:base"]
    # pairs that touch a pick: K(1,5)=0.08, K(1,6)=0.03 (deck 1 vs pick 6), K(6,6)=0 (same card), K(6,?)... deck 6 vs pick 5: −K(5,6)=0, deck 7 vs 5,6,9: none
    cross = 0.08 + 0.03
    z = own - field + cross
    gz, gfit = cm.builder_field_fit(deck, case["picks"], MODEL)
    assert gz == pytest.approx(z, abs=1e-12) and gfit == pytest.approx(1 / (1 + math.exp(-z)), abs=1e-12)


@pytest.mark.parametrize("case", FIX["cases"], ids=[c["name"] for c in FIX["cases"]])
def test_rank_matches_the_fixture(case):
    by_key = {k: (z, fit) for k, z, fit in case["fits"]}
    # synergy and lift come with the fixture's deck order (the same six decks in every case)
    decks = [k for k, _, _ in case["fits"]]
    rows = [{"key": k, "fit": by_key[k][1], "mean_synergy": s, "mean_log_lift": li} for k, s, li in zip(decks, [0.010, 0.012, -0.004, 0.020, 0.000, 0.006], [0.40, 0.35, 0.10, 0.80, 0.20, 0.55])]
    got = cm.builder_rank(rows, FIX["synergy_weight"], FIX["cooccurrence_weight"], case["n_results"], case["min_diff"])
    assert [r["key"] for r in got] == case["expect"]
    assert [r["score"] for r in got] == pytest.approx(case["scores"], abs=1e-12)
    ids = [{int(x.split(":")[0]) for x in r["key"].split("|")} for r in got]
    assert all(len(a - b) >= case["min_diff"] for i, a in enumerate(ids) for b in ids[:i])


def test_float_noise_ties_go_to_the_key():
    got = cm.builder_rank(FIX["ties"]["rows"], FIX["synergy_weight"], FIX["cooccurrence_weight"], 3, 1)
    assert [r["key"] for r in got] == FIX["ties"]["expect"]


@pytest.mark.parametrize("case", FIX["elixir"])
def test_elixir_bounds(case):
    got = cm.builder_elixir_bounds([tuple(d) for d in case["decks"]])
    assert (list(got) if got else None) == case["expect"]


@pytest.mark.parametrize("case", FIX["exact"])
def test_exact_path_rule(case):
    assert cm.builder_use_exact(["x"] * case["picks"], case["decks"]) is case["expect"]


def test_shares():
    assert cm.builder_shares(["a"] * 16) == 0.5 and cm.builder_shares(["a"] * 8) == 1.0 and cm.builder_shares(["a"] * 3) == 1.0 and cm.builder_shares([]) == 0.0


# ---------------------------------------------------------------- the forward check (crdeck.evalx.counter_builder_check)

def test_forward_check_runs_on_a_small_context_and_reproduces(small_ctx):
    from crdeck.evalx import counter_builder_check as cbc
    from crdeck.search import Searcher
    if small_ctx.matchup is None:
        pytest.skip("no matchup model in the small context")
    pool = cm.counter_pool(small_ctx, 2, 500)
    a = cbc.run(small_ctx, small_ctx.matchup, Searcher(small_ctx), pool, queries=40, replicates=200, min_overlap=2)
    b = cbc.run(small_ctx, small_ctx.matchup, Searcher(small_ctx), pool, queries=40, replicates=200, min_overlap=2)
    assert a == b                                                   # fixed seeds
    if "skipped" in a:
        return
    assert a["verdict"] in ("better", "not_shown", "too_few") and set(a["games"]) == set(cbc.LISTS)
    if a["vs_random"]:
        d, lo, hi = a["vs_random"]
        assert lo <= hi and d == pytest.approx(a["rate"]["builder"] - a["rate"]["random"])


def test_norms_match_the_websites_strict_rule(cards):
    from crdeck.config import model_config
    from crdeck.evalx import counter_builder_check as cbc
    from crdeck.rules import DeckCard
    cfg = {"warnings": model_config()["warnings"]}
    tanks = [c for c in cards.ids if "tank" in cards[c].roles][:2]
    assert len(tanks) == 2
    assert not cbc.passes_norms([DeckCard(t) for t in tanks], cards, cfg)   # two tanks: refused, like Engine.suggestionRule
