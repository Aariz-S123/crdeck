"""Shrinkage math, pair counting, INSUFFICIENT_SAMPLE (spec 7.1)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crdeck.synergy import (INSUFFICIENT_SAMPLE, OK, compute_synergy, expected_pair_wr, logit, shrunk_rate,
                            sigmoid)


def test_shrunk_rate_formula():
    # (wins + k g) / (games + k)
    assert shrunk_rate(30, 50, 50, 0.5) == pytest.approx((30 + 25) / 100)
    assert shrunk_rate(0, 0, 50, 0.5) == pytest.approx(0.5)  # no data -> global rate
    assert shrunk_rate(1000, 1000, 50, 0.5) == pytest.approx(1025 / 1050)


def test_expected_pair_wr_is_additive_in_log_odds():
    g = 0.5
    e = expected_pair_wr(0.6, 0.55, g)
    assert e == pytest.approx(sigmoid(logit(0.6) + logit(0.55) - logit(g)))
    assert expected_pair_wr(0.5, 0.6, 0.5) == pytest.approx(0.6)  # a neutral card adds nothing


def _sides(rows):
    return pd.DataFrame(rows, columns=["deck_key", "won"])


def test_counts_lift_and_insufficient_sample():
    # card ids 1..4; decks "1:base|2:base" etc.
    rows = ([("1:base|2:base|3:base", True)] * 150 + [("1:base|2:base|3:base", False)] * 90
            + [("1:base|4:base", True)] * 40 + [("1:base|4:base", False)] * 60
            + [("3:base|4:base", False)] * 60)
    syn = compute_synergy(_sides(rows), k=50, min_games=200, expected_from="marginal")
    p12 = syn.pair(1, 2)
    assert p12["games"] == 240 and p12["wins"] == 150 and p12["status"] == OK
    n = len(rows)
    rate1, rate2 = 340 / n, 240 / n
    assert p12["lift"] == pytest.approx((240 / n) / (rate1 * rate2))
    g = (150 + 40) / n
    assert p12["shrunk_wr"] == pytest.approx((150 + 50 * g) / (240 + 50))
    c = syn.cards.set_index("card_id")
    exp = expected_pair_wr(c.loc[1, "shrunk_wr"], c.loc[2, "shrunk_wr"], g)
    assert p12["expected_wr"] == pytest.approx(exp)
    assert p12["synergy"] == pytest.approx(p12["shrunk_wr"] - exp)
    assert p12["lo"] < p12["synergy"] < p12["hi"]

    p14 = syn.pair(1, 4)
    assert p14["games"] == 100 and p14["status"] == INSUFFICIENT_SAMPLE
    assert np.isnan(p14["synergy"]) and np.isnan(p14["lo"])
    assert syn.pair(2, 4) is None  # never seen together


def test_deck_pairs_and_mean_synergy_ignore_insufficient():
    rows = [("1:base|2:base", True)] * 300 + [("1:base|2:base", False)] * 200 + [("3:base|4:base", False)] * 500
    syn = compute_synergy(_sides(rows), k=50, min_games=200)
    dp = syn.deck_pairs([1, 2, 3])
    assert len(dp) == 3
    assert (dp["status"] == INSUFFICIENT_SAMPLE).sum() == 2  # (1,3) and (2,3) unseen
    m, n = syn.mean_synergy([1, 2, 3])
    assert n == 1 and m == pytest.approx(syn.pair(1, 2)["synergy"])


def test_without_partner_recovers_planted_synergy_where_marginal_double_counts():
    """Cards A, B almost always together with a true pair bonus; A alone is neutral.

    The marginal version folds the pair effect into A's and B's own rates, so the
    expected rate is inflated; the without-partner version compares against games
    where each card appears without the other.
    """
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(4000):
        r = rng.random()
        if r < 0.45:
            rows.append(("1:base|2:base", rng.random() < 0.6))  # together: 60%
        elif r < 0.5:
            rows.append(("1:base|5:base", rng.random() < 0.5))  # A without B: 50%
        elif r < 0.55:
            rows.append(("2:base|6:base", rng.random() < 0.5))  # B without A: 50%
        else:
            rows.append(("7:base|8:base", rng.random() < 0.45))
    wp = compute_synergy(_sides(rows), k=50, min_games=200, expected_from="without_partner").pair(1, 2)
    mg = compute_synergy(_sides(rows), k=50, min_games=200, expected_from="marginal").pair(1, 2)
    assert wp["synergy"] > 0.05
    assert wp["synergy"] > mg["synergy"]


def test_bad_expected_from():
    with pytest.raises(ValueError):
        compute_synergy(_sides([("1:base|2:base", True)]), expected_from="vibes")
