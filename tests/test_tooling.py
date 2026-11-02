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
    assert (paths.processed / "context_cache_ranked.pkl").exists()
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
    pairs = pd.read_csv(tmp_path / "processed" / "synergy_pairs_ranked.csv")
    assert {"name_i", "name_j", "synergy", "games", "status"} <= set(pairs.columns)
    ev = json.loads((tmp_path / "processed" / "evaluation_ranked.json").read_text())
    assert ev["source"] == "synthetic" and ev["evaluation"]["table"] == [{"a": 1}]


# ---------------------------------------------------------------- the scheduled collection

def _script(name):
    import importlib.util
    from crdeck.config import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _calls(*results):
    """A stand-in for a collection: each call returns or raises the next result, and the calls are counted."""
    state = {"n": 0}

    def call():
        out = results[state["n"]]
        state["n"] += 1
        if isinstance(out, Exception):
            raise out
        return out
    return call, state


def test_daily_collection_needs_no_fallback_on_a_normal_day():
    daily = _script("daily_collect")
    collect, c = _calls({"players": 2800, "errors": []})
    known, k = _calls()
    slept = []
    assert daily.run(collect, known, slept.append) == 0
    assert (c["n"], k["n"], slept) == (1, 0, [])


def test_daily_collection_falls_back_when_the_leaderboards_are_empty_or_refilling():
    from crdeck.api import ApiError
    daily = _script("daily_collect")
    collect, _ = _calls(ApiError("leaderboards returned no players"))
    known, k = _calls({"players": 2877, "errors": []})
    assert daily.run(collect, known, lambda s: None) == 0 and k["n"] == 1
    collect, c = _calls({"players": 40, "errors": []})
    known, k = _calls({"players": 2877, "errors": []})
    assert daily.run(collect, known, lambda s: None) == 0 and (c["n"], k["n"]) == (1, 1)


def test_daily_collection_retries_a_dropped_connection_and_too_many_failed_logs():
    daily = _script("daily_collect")
    collect, c = _calls(OSError("connection dropped"), {"players": 2800, "errors": ["x"] * 51}, {"players": 2800, "errors": ["x"] * 2})
    known, k = _calls()
    slept = []
    assert daily.run(collect, known, slept.append, wait_seconds=5) == 0
    assert (c["n"], k["n"], slept) == (3, 0, [5, 5])


def test_daily_collection_gives_up_with_a_failing_exit_code():
    from crdeck.api import ApiError
    daily = _script("daily_collect")
    collect, c = _calls(ApiError("403 from /players"), ApiError("403 from /players"), ApiError("403 from /players"))
    known, k = _calls()
    slept = []
    assert daily.run(collect, known, slept.append, wait_seconds=1) == 1
    assert (c["n"], k["n"], slept) == (3, 0, [1, 1])      # another API error is not an empty leaderboard


def _board(raw, window, name, tags):
    d = raw / window / "leaderboard"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({"body": {"items": [{"tag": t} for t in tags]}}), encoding="utf-8")


def test_known_players_takes_the_newest_list_with_enough_players(tmp_path):
    import pytest
    from crdeck.api import ApiError
    script = _script("collect_known_players")
    _board(tmp_path, "2026-10-30", "a", ["#A", "#B", "#C"])
    _board(tmp_path, "2026-10-30", "b", ["#C", "#D"])
    _board(tmp_path, "2026-11-01", "a", ["#Z"])          # still refilling
    _board(tmp_path, "2026-11-02", "a", [])              # empty
    tags, source = script.known_players(tmp_path, min_players=3)
    assert source == "2026-10-30" and tags == ["#A", "#B", "#C", "#D"]
    with pytest.raises(ApiError):
        script.known_players(tmp_path, min_players=10)
