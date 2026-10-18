from __future__ import annotations

import numpy as np
import pandas as pd

from crdeck.rules import DeckCard, deck_key
from crdeck.strength import CardModel, ConstantBaseline, PopularityBaseline, evaluate, feature_key


def _battles(seed=0, n=3000):
    """Card 1 is strong; others neutral. Decks are random 8-subsets of 1..20."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        a = rng.choice(np.arange(1, 21), 8, replace=False)
        b = rng.choice(np.arange(1, 21), 8, replace=False)
        ua, ub = 1.5 * (1 in a), 1.5 * (1 in b)
        won = rng.random() < 1 / (1 + np.exp(-(ua - ub)))
        rows.append({"deck_a": deck_key([DeckCard(int(c)) for c in a]),
                     "deck_b": deck_key([DeckCard(int(c)) for c in b]),
                     "a_won": bool(won), "battle_time": pd.Timestamp("2026-10-01", tz="UTC") + pd.Timedelta(minutes=i)})
    return pd.DataFrame(rows)


def test_card_model_learns_strong_card_and_beats_baselines():
    df = _battles()
    train, test = df.iloc[:2400], df.iloc[2400:]
    m = CardModel(hero_observable=False, C=1.0).fit(train)
    w = m.card_weights
    assert max(w, key=w.get) == "1:base"
    ll = evaluate(m, test)["log_loss"]
    assert ll < evaluate(ConstantBaseline(), test)["log_loss"]
    assert ll < evaluate(PopularityBaseline().fit(train), test)["log_loss"]


def test_predictions_are_symmetric_and_deterministic():
    df = _battles(n=1000)
    m1 = CardModel(False, C=1.0).fit(df)
    m2 = CardModel(False, C=1.0).fit(df)
    p_ab = m1.predict_proba(df["deck_a"], df["deck_b"])
    p_ba = m1.predict_proba(df["deck_b"], df["deck_a"])
    assert np.allclose(p_ab, 1 - p_ba)
    assert np.allclose(m1.coef, m2.coef)


def test_hero_maps_to_base_when_not_observable():
    assert feature_key(DeckCard(5, "hero"), hero_observable=False) == "5:base"
    assert feature_key(DeckCard(5, "hero"), hero_observable=True) == "5:hero"
    assert feature_key(DeckCard(5, "evo"), hero_observable=False) == "5:evo"


def test_pair_features_are_used():
    df = _battles(n=1500)
    m = CardModel(False, C=1.0, pairs=[(1, 2)]).fit(df)
    assert (1, 2) in m.pair_weights
    with_pair = [DeckCard(c) for c in (1, 2, 3, 4, 5, 6, 7, 8)]
    assert m.utility(with_pair) == sum(m.card_weights.get(f"{c}:base", 0) for c in range(1, 9)) + m.pair_weights[(1, 2)]
