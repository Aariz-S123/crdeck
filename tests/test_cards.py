from __future__ import annotations

import pandas as pd
import pytest

from crdeck.cards import CardTable, CardTableError, attach_api, load_labels, normalize_name
from crdeck.config import CARD_LABELS


def test_normalize_name():
    assert normalize_name("P.E.K.K.A") == "pekka"
    assert normalize_name("X-Bow") == "xbow"
    assert normalize_name("Mini P.E.K.K.A") == "minipekka"


def test_real_label_file_is_valid():
    df = load_labels(CARD_LABELS)
    assert len(df) > 100
    assert df["name"].map(normalize_name).is_unique
    assert df.loc[df["name"] == "Mirror", "elixir_variable"].item()
    champs = set(df.loc[df["is_champion"], "name"])
    assert {"Archer Queen", "Golden Knight", "Mighty Miner"} <= champs


def test_invalid_labels_are_rejected(tmp_path):
    df = pd.read_csv(CARD_LABELS, dtype=str, keep_default_na=False)
    df.loc[0, "roles"] = "teleporter"
    df.loc[1, "targets"] = "everything"
    p = tmp_path / "bad.csv"
    df.to_csv(p, index=False)
    with pytest.raises(CardTableError) as e:
        load_labels(p)
    assert "teleporter" in str(e.value) and "everything" in str(e.value)


def test_attach_api_joins_on_name_once_and_reports():
    labels = load_labels(CARD_LABELS)
    body = {"items": [
        {"name": "Hog Rider", "id": 26000021, "elixirCost": 4, "rarity": "Rare", "maxLevel": 14},
        {"name": "Archer Queen", "id": 26000072, "elixirCost": 5, "rarity": "Champion", "maxLevel": 6},
        {"name": "Knight", "id": 26000000, "elixirCost": 3, "rarity": "Common", "maxLevel": 16, "maxEvolutionLevel": 1},
        {"name": "Brand New Card", "id": 26999999, "elixirCost": 3, "rarity": "Epic"},
    ]}
    table, rep = attach_api(labels, body)
    assert set(table["card_id"]) == {26000021, 26000072, 26000000}
    assert "Brand New Card" in rep.api_without_labels
    assert any("Archer Queen" in x for x in rep.elixir_overrides)
    t = CardTable(table)
    assert t[26000072].is_champion and t[26000072].elixir == 5
    assert t[26000000].has_evolution and t[26000000].rarity == "common"
    assert t.by_name("hog rider").card_id == 26000021
    assert len(rep.labels_without_api) == len(labels) - 3


def test_card_table_requires_ids():
    labels = load_labels(CARD_LABELS)
    with pytest.raises(CardTableError):
        CardTable(labels)


def test_allowed_forms(cards):
    k = cards.by_name("Knight")
    assert k.allowed_forms() == ("base", "evo", "hero")
    assert cards.by_name("Hog Rider").allowed_forms() == ("base",)
