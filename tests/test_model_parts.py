"""Model files in two parts (crdeck.explore.model_parts)."""

import json

from crdeck.explore import model_parts as mp


def test_split_then_load_gives_back_the_original_and_is_idempotent(tmp_path):
    original = {"meta": {"x": 1}, "cards": [1, 2], "deck_appearances": {"a|b": 3}, "test_deck_records": {"a|b": [2, 1]}, "strength": {"coef": [0.1]}}
    f = tmp_path / "ranked.json"
    f.write_text(json.dumps(original), encoding="utf-8")
    assert mp.split_file(f) is True
    main = json.loads(f.read_text(encoding="utf-8"))
    assert "deck_appearances" not in main and "test_deck_records" not in main and main["strength"] == {"coef": [0.1]}
    assert json.loads(mp.decks_path(f).read_text(encoding="utf-8")) == {"deck_appearances": {"a|b": 3}, "test_deck_records": {"a|b": [2, 1]}}
    assert mp.load(f) == original
    assert mp.split_file(f) is False and mp.load(f) == original          # a second split changes nothing


def test_split_all_skips_parts_and_an_unsplit_file_loads_as_it_is(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"deck_appearances": {}, "cards": []}), encoding="utf-8")
    (tmp_path / "b.parts.json").write_text(json.dumps({"parts": []}), encoding="utf-8")
    assert mp.split_all(tmp_path) == ["a.json"]
    assert mp.split_all(tmp_path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.decks.json", "a.json", "b.parts.json"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"cards": [], "deck_appearances": {"x": 1}}), encoding="utf-8")
    assert mp.load(old) == {"cards": [], "deck_appearances": {"x": 1}}
