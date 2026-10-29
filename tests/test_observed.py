"""Observed-deck selector (crdeck.counters.observed_decks): the hand-worked cases shared with the website
(tests/fixtures/observed_selector.json, also run by tests/web/run2_test.cjs against web/observed.js)."""

import json
from pathlib import Path

import pytest

from crdeck.counters import observed_decks

FIX = json.loads((Path(__file__).parent / "fixtures" / "observed_selector.json").read_text(encoding="utf8"))


@pytest.mark.parametrize("case", FIX["cases"], ids=[c["name"] for c in FIX["cases"]])
def test_observed_selector_matches_hand_worked_cases(case):
    pool = [(d, n) for d, n, _ in FIX["pool"]]
    objectives = {d: obj for d, _, obj in FIX["pool"]}
    got = observed_decks(pool, objectives, case["seeds"], case["n_results"], case["min_diff"])
    assert got == case["expect"]


def test_every_observed_deck_holds_every_seed_and_comes_from_the_pool():
    pool = [(d, n) for d, n, _ in FIX["pool"]]
    objectives = {d: obj for d, _, obj in FIX["pool"]}
    keys = {d for d, _ in pool}
    for seeds in (["1:base"], ["2:base", "3:base"], []):
        for d in observed_decks(pool, objectives, seeds, 10, 1):
            assert d in keys and set(seeds) <= set(d.split("|"))


def test_observed_decks_is_post_training():
    # the helper lives in counters.py, which the model cache fingerprint leaves out (pipeline.POST_TRAINING)
    from crdeck.pipeline import POST_TRAINING
    assert "counters.py" in POST_TRAINING
