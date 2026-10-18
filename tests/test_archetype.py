from __future__ import annotations

import pandas as pd
import pytest

from crdeck.archetype import (NO_LABELS, UNCERTAIN, ArchetypeLabelError, ArchetypeModel, load_labels,
                              suggest_decks_to_label)
from crdeck.rules import parse_deck_key


def test_unfitted_model_reports_no_labels(cards, C):
    m = ArchetypeModel(cards)
    p = m.predict([C("Hog Rider")])
    assert p.label == NO_LABELS and p.probability is None


def test_label_validation(tmp_path):
    p = tmp_path / "a.csv"
    pd.DataFrame([{"deck_key": "1:base", "archetype": "Turbo", "split": "train", "labeled_at": "", "notes": ""}]).to_csv(p, index=False)
    with pytest.raises(ArchetypeLabelError, match="unknown archetypes"):
        load_labels(p)
    pd.DataFrame([{"deck_key": "1:base", "archetype": "Cycle", "split": "dev", "labeled_at": "", "notes": ""}]).to_csv(p, index=False)
    with pytest.raises(ArchetypeLabelError, match="split"):
        load_labels(p)
    assert load_labels(tmp_path / "missing.csv").empty


def test_fit_predict_and_uncertain_threshold(small_ctx):
    labels = small_ctx.archetype_labels
    assert small_ctx.archetype.fitted
    k = labels.loc[labels["split"] == "heldout", "deck_key"].iloc[0]
    p = small_ctx.archetype.predict(parse_deck_key(k))
    assert p.label in set(labels["archetype"]) | {UNCERTAIN}
    strict = ArchetypeModel(small_ctx.cards, threshold=1.01).fit(labels)
    assert strict.predict(parse_deck_key(k)).label == UNCERTAIN
    ev = small_ctx.archetype.evaluate_heldout(labels)
    assert ev["heldout_decks"] == 20 and 0 <= ev["accuracy"] <= 1


def test_suggest_decks_to_label(small_ctx):
    out = suggest_decks_to_label(small_ctx.decks, small_ctx.cards, n_clusters=4, per_cluster=3, seed=1)
    assert 1 <= len(out) <= 12
    assert {"deck_key", "cards", "archetype", "split"} <= set(out.columns)
    assert (out["archetype"] == "").all()
