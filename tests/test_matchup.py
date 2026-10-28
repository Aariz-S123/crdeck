"""Matchup model: recovers a planted counter and stays antisymmetric (counter cards and decks: test_counters.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crdeck.matchup import MatchupModel, pair_counts

FILLER = [f"{100 + i}:base" for i in range(20)]


def planted_battles(n=6000, seed=0):
    """Card 1 beats card 2 (75% when 1's deck meets 2's deck). Cards 1 and 2 also meet other cards
    (coin flips), so a card's own strength and its matchup can be told apart; every other battle is a coin flip."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n):
        a = list(rng.choice(FILLER, 7, replace=False))
        b = list(rng.choice(FILLER, 7, replace=False))
        kind = t % 5
        if kind == 0:
            a.append("1:base"); b.append("2:base"); p = 0.75
        elif kind == 1:
            a.append("2:base"); b.append("1:base"); p = 0.25
        elif kind == 2:
            a.append("1:base"); b.append(str(rng.choice(FILLER))); p = 0.5
        elif kind == 3:
            a.append("2:base"); b.append(str(rng.choice(FILLER))); p = 0.5
        else:
            a.append(str(rng.choice(FILLER))); b.append(str(rng.choice(FILLER))); p = 0.5
        rows.append({"battle_key": f"b{t}", "battle_time": pd.Timestamp("2026-10-01") + pd.Timedelta(minutes=t),
                     "deck_a": "|".join(sorted(set(a))), "deck_b": "|".join(sorted(set(b))), "a_won": bool(rng.random() < p),
                     "rating_diff": 0.0})
    return pd.DataFrame(rows)


def test_recovers_a_planted_counter_and_is_antisymmetric():
    df = planted_battles()
    m = MatchupModel(C=1.0, min_pair_battles=500, min_card_games=20).fit(df)
    assert ("1:base", "2:base") in m.K and m.K[("1:base", "2:base")] > 0.6          # true effect: logit(0.75) ≈ 1.1
    assert m.k("1:base", "2:base") == -m.k("2:base", "1:base")
    A, B = ["1:base"] + FILLER[:7], ["2:base"] + FILLER[7:14]
    assert abs(m.z(A, B) + m.z(B, A)) < 1e-12
    assert m.win_vs(A, [("|".join(B), 1)]) > 0.6
    assert m.max_gradient < 1e-8


def test_pair_counts_need_opposite_sides():
    df = pd.DataFrame([{"deck_a": "1:base|2:base", "deck_b": "3:base"}])
    assert pair_counts(df) == {("1:base", "3:base"): 1, ("2:base", "3:base"): 1}
