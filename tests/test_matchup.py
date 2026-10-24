"""Matchup model: recovers a planted counter, stays antisymmetric, ranks counter cards, searches legal decks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crdeck.matchup import MatchupModel, counter_cards, counter_search, decks_with, pair_counts
from crdeck.rules import DeckCard, check_deck
from crdeck.search import Searcher

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


def test_counter_cards_rank_the_planted_counter_first():
    m = MatchupModel(C=1.0, min_pair_battles=500, min_card_games=20).fit(planted_battles())
    opp = [["2:base|" + "|".join(FILLER[:7]), 10]]
    top = counter_cards(m, ["1:base"] + FILLER, opp, 3)
    assert top[0]["card"] == "1:base" and top[0]["effect"] > 0
    t = top[0]["best_against"][0]
    assert t["card"] == "2:base" and t["ci90"][0] > 0 and t["share"] == 1.0


def test_decks_with_keeps_only_decks_holding_every_card():
    all_decks = [["1:base|2:base", 5], ["1:base|3:base", 4], ["2:base", 3]]
    assert decks_with(all_decks, ["1:base"], 10) == [["1:base|2:base", 5], ["1:base|3:base", 4]]


def test_counter_search_returns_legal_decks_holding_the_picks(small_ctx):
    split = small_ctx.split
    m = MatchupModel(C=0.1, min_pair_battles=50, min_card_games=20).fit(split.train_valid)
    s = Searcher(small_ctx)
    opp = [[d, 1] for d in split.test["deck_b"].head(5)]
    seed = s.candidates[0]
    res = counter_search(small_ctx, m, s, opp, [seed], n_results=3, beam_width=20, min_diff=2)
    assert res
    for r in res:
        assert check_deck(r["entries"], small_ctx.cards, small_ctx.rules).legal
        assert any(e == seed for e in r["entries"])
        keys = [f"{e.card_id}:{e.form}" for e in r["entries"]]
        assert abs(r["win_vs"] - m.win_vs(keys, opp)) < 1e-9
    assert [r["win_vs"] for r in res] == sorted((r["win_vs"] for r in res), reverse=True)
