"""Gate observations, collection windows, leaderboard ranks, labeling, cache, saved outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from crdeck.api import ApiClient
from crdeck.archetype import load_labels, suggest_decks_to_label
from crdeck.collect import auto_window_id, gate, suggest_config, write_observed_notes
from crdeck.config import Paths
from crdeck.labeling import run as label_run
from tests.test_api import CFG, KEY, FakeResp, FakeSession


def _gate_client(tmp_path, card_extra=None):
    card = {"name": "Knight", "id": 26000000, "level": 14, "maxLevel": 16, "evolutionLevel": 1}
    card.update(card_extra or {})
    side = lambda tag, crowns: {"tag": tag, "crowns": crowns, "cards": [card] * 8}
    responses = [
        FakeResp(200, {"items": [{"name": "Knight", "id": 26000000, "elixirCost": 3, "rarity": "common", "maxEvolutionLevel": 1}]}),
        FakeResp(200, {"items": [{"tag": "#AAA", "name": "a", "rank": 1}]}),
        FakeResp(200, [{"type": "pathOfLegend", "battleTime": "20261018T120000.000Z",
                        "team": [side("#AAA", 1)], "opponent": [side("#BBB", 0)]}]),
    ]
    paths = Paths(source="real", root=tmp_path)
    return ApiClient(paths=paths, cfg=CFG, session=FakeSession(responses), key=KEY, sleep=lambda s: None)


def test_gate_flags_new_card_fields_and_writes_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("crdeck.collect.collection_config", lambda: {**CFG, "leaderboard": {"location_id": "global", "season_id": None, "limit": 50}})
    obs = gate(_gate_client(tmp_path, {"heroLevel": 1}))
    assert obs["unknown_deck_card_fields"] == ["heroLevel"]
    assert any("hero_field" in s for s in obs["config_suggestions"])
    assert obs["battlelog"]["n_battles"] == 1 and obs["throttled_429"] == 0
    out = write_observed_notes(obs, tmp_path / "observed.md")
    text = out.read_text(encoding="utf-8")
    assert "heroLevel" in text and KEY not in text and "Suggested config changes" in text


def test_suggest_config_flags_missing_type_and_evo_field():
    obs = {"battlelog": {"battle_types": {"ranked1v1": 3}, "deck_card_fields": {"id": 8}, "cards_per_side": {8: 2}},
           "leaderboard": {"n_items": 5}, "unknown_deck_card_fields": []}
    s = suggest_config(obs)
    assert any("pathOfLegend" in x and "ranked1v1" in x for x in s)
    assert any("evo_field" in x for x in s)


def test_auto_window_id():
    assert auto_window_id(datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)) == "2026-10-18"


def test_window_override_changes_cache_dir(tmp_path):
    c = ApiClient(paths=Paths(source="real", root=tmp_path), cfg=CFG, key=KEY, window_id="2026-10-19")
    assert c.window_dir == tmp_path / "raw" / "2026-10-19"


def test_leaderboard_rank_fill(tmp_path):
    from crdeck.pipeline import leaderboard_ranks
    d = tmp_path / "raw" / "w1" / "leaderboard"
    d.mkdir(parents=True)
    (d / "global.json").write_text(json.dumps({"status": 200, "body": {"items": [{"tag": "#A", "rank": 3}, {"tag": "#B", "rank": 9}]}}))
    d2 = tmp_path / "raw" / "w2" / "leaderboard"
    d2.mkdir(parents=True)
    (d2 / "global.json").write_text(json.dumps({"status": 200, "body": {"items": [{"tag": "#A", "rank": 1}]}}))
    assert leaderboard_ranks(Paths(source="real", root=tmp_path)) == {"#A": 1.0, "#B": 9.0}


def test_worklist_is_round_robin_across_clusters(small_ctx):
    out = suggest_decks_to_label(small_ctx.decks, small_ctx.cards, n_clusters=4, per_cluster=3, seed=1)
    k = out["cluster"].nunique()
    assert out["cluster"].head(k).nunique() == k


def test_interactive_labeling_heldout_first_and_resumable(small_ctx, tmp_path):
    work = suggest_decks_to_label(small_ctx.decks, small_ctx.cards, n_clusters=3, per_cluster=3, seed=1)
    path = tmp_path / "labels.csv"
    answers = iter(["2", "x", "1", "s", "q"])
    said = []
    r = label_run(work, small_ctx.cards, path, heldout_target=1, ask=lambda _: next(answers), say=said.append)
    assert r["labeled"] == 2 and r["skipped"] == 1
    labs = load_labels(path)
    assert list(labs["split"]) == ["heldout", "train"]
    assert list(labs["archetype"]) == ["Cycle", "Beatdown"]
    assert any("not understood" in s for s in said)
    answers = iter(["q"])
    label_run(work, small_ctx.cards, path, heldout_target=1, ask=lambda _: next(answers), say=said.append)
    assert len(load_labels(path)) == 2  # resumed without duplicating


def test_context_cache_reused_and_invalidated(small_ctx, tmp_path):
    import shutil
    from crdeck.pipeline import load_context
    root = tmp_path / "copy"
    shutil.copytree(small_ctx.paths.root, root)
    paths = Paths(source="synthetic", root=root)
    a = load_context(paths=paths)
    b = load_context(paths=paths)
    assert (paths.processed / "context_cache.pkl").exists()
    assert list(a.strength.coef) == list(b.strength.coef)
    with paths.archetype_labels.open("a", encoding="utf-8") as f:  # change an input -> retrain
        f.write("")
    labels = paths.archetype_labels.read_text(encoding="utf-8").splitlines()
    paths.archetype_labels.write_text("\n".join(labels[:-1]) + "\n", encoding="utf-8")
    c = load_context(paths=paths)
    assert len(c.archetype_labels) == len(a.archetype_labels) - 1


def test_save_model_outputs(small_ctx, tmp_path):
    import copy
    from crdeck.pipeline import save_model_outputs
    ctx = copy.copy(small_ctx)
    ctx.paths = Paths(source="synthetic", root=tmp_path)
    files = save_model_outputs(ctx, {"note": "x", "table": pd.DataFrame([{"a": 1}])})
    assert all(f.exists() for f in files)
    pairs = pd.read_csv(tmp_path / "processed" / "synergy_pairs.csv")
    assert {"name_i", "name_j", "synergy", "games", "status"} <= set(pairs.columns)
    ev = json.loads((tmp_path / "processed" / "evaluation.json").read_text())
    assert ev["source"] == "synthetic" and ev["evaluation"]["table"] == [{"a": 1}]
