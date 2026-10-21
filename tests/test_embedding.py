"""Card embeddings: PPMI factorization, planted structure, held-out check, and card-map swaps."""

from __future__ import annotations

import numpy as np
import pandas as pd

from crdeck.embedding import NEAR, TOP_SWAPS, CardEmbedding, embedding_swaps, factorize, ppmi, train
from crdeck.rules import check_deck
from crdeck.search import Searcher

GROUP_A = ["1:base", "2:base", "3:base", "4:base"]
GROUP_B = ["5:base", "6:base", "7:base", "8:base"]
KEYS = GROUP_A + GROUP_B


def planted_decks(n=400, seed=0):
    """Each deck draws 3 of the 4 cards of one group: cards of a group are played together far more than
    chance, cards of different groups never."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        home = GROUP_A if i % 2 else GROUP_B
        out.append("|".join(sorted(rng.choice(home, 3, replace=False))))
    return pd.Series(out)


def test_ppmi_is_symmetric_positive_and_zero_on_the_diagonal():
    m = ppmi(planted_decks(), KEYS)
    assert np.allclose(m, m.T) and (m >= 0).all() and np.allclose(np.diag(m), 0)
    assert m[0, 1] > m[0, 4]          # same-group pairs share decks more than chance


def test_factorized_vectors_have_unit_length_and_recover_the_groups():
    v = factorize(ppmi(planted_decks(), KEYS), 2)
    assert v.shape == (8, 2) and np.allclose(np.linalg.norm(v, axis=1), 1)
    sim = v @ v.T
    within = np.mean([sim[i, j] for i in range(4) for j in range(4) if i != j])
    across = np.mean([sim[i, j] for i in range(4) for j in range(4, 8)])
    assert within > across + 0.5


def test_distance_is_cosine_to_the_center_in_full_dimensions():
    e = CardEmbedding(3, ["1:base", "2:base"], np.array([[1.0, 0, 0], [0, 1.0, 0]]))
    c = np.array([1.0, 1.0, 0]) / 2
    assert abs(e.distance(np.array([1.0, 0, 0]), c) - (1 - 1 / np.sqrt(2))) < 1e-12
    assert abs(e.distance(np.array([0, 0, 1.0]), c) - 1.0) < 1e-12


def test_trained_on_train_window_chosen_on_validation_tested_on_test(small_ctx):
    emb = train(small_ctx)
    assert emb is not None and emb.dim in {c["dim"] for c in emb.choice}
    assert sum(c["selected"] for c in emb.choice) == 1
    assert {"recall", "recall_popular", "recall_ci90"} <= set(emb.evaluation)
    assert emb.pca3.shape == (len(emb.keys), 3) and len(emb.pca_explained) == 3
    assert np.allclose(np.linalg.norm(emb.vectors, axis=1), 1, atol=1e-6)
    assert np.array_equal(emb.vectors, np.round(emb.vectors, 7))        # exactly what the website gets


def test_card_map_swaps_are_legal_near_and_raise_the_win_rate(small_ctx):
    small_ctx.embedding = train(small_ctx)
    s = Searcher(small_ctx)
    deck = s.complete([])[0].entries
    locked = deck[:1]
    base = s.evaluate(deck).win_prob
    sw = embedding_swaps(small_ctx, s, deck, locked)
    assert len(sw) <= TOP_SWAPS
    for w in sw:
        assert w["replace_entry"] != locked[0]
        new = [e for e in deck if e != w["replace_entry"]] + [w["with_entry"]]
        assert check_deck(new, small_ctx.cards, small_ctx.rules).legal
        assert w["delta_win_prob"] > 0 and abs(s.evaluate(new).win_prob - base - w["delta_win_prob"]) < 1e-12
        assert 0 <= w["distance"] <= 2
    assert [w["delta_win_prob"] for w in sw] == sorted((w["delta_win_prob"] for w in sw), reverse=True)
    assert NEAR >= 1
