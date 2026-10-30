"""Forward check of the counter recommendations (docs/claude-redesign/EVAL-DESIGN.md): the paired cluster
bootstrap, the style-standardized rate, group membership, frozen pre-test inputs, and the rule that the
evaluation script never retrains."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crdeck import counters as cm
from crdeck.search import Searcher

ROOT = Path(__file__).resolve().parents[1]


def games_frame(rows):
    return pd.DataFrame(rows, columns=["battle_key", "side", "deck", "style", "won", "player", "opponent"])


def test_identical_groups_differ_by_exactly_zero_in_every_replicate():
    # every game counts for all three groups: paired resampling must give a difference of exactly 0
    rng = np.random.default_rng(1)
    g = games_frame([(f"b{i}", "A", "d", "S", int(rng.random() < 0.6), f"p{i % 7}", f"o{i}") for i in range(200)])
    res = cm.paired_bootstrap(g, np.ones((200, 3), dtype=np.int8), g["player"], n_boot=300, seed=3)
    assert res["vs_field"] == [0.0, 0.0, 0.0] and res["vs_all"] == [0.0, 0.0, 0.0]


def test_point_estimates_and_style_standardized_rate_by_hand():
    # counter: style S 8 of 10 won, style T 1 of 2; field: S 30 of 60, T 40 of 40; all = counter + field games
    rows, mem = [], []
    def add(n, wins, style, groups, tag):
        for i in range(n):
            rows.append((f"{tag}{i}", "A", tag, style, int(i < wins), f"{tag}{i}", f"x{tag}{i}"))
            mem.append(groups)
    add(10, 8, "S", (1, 0, 1), "c"); add(2, 1, "T", (1, 0, 1), "k")
    add(60, 30, "S", (0, 1, 1), "f"); add(40, 40, "T", (0, 1, 1), "h")
    g = games_frame(rows)
    res = cm.paired_bootstrap(g, np.array(mem, dtype=np.int8), g["player"], n_boot=200, seed=0)
    assert res["games"] == {"counter": 12, "field": 100, "all": 112} and res["wins"] == {"counter": 9, "field": 70, "all": 79}
    assert res["rate"]["counter"] == pytest.approx(0.75) and res["vs_field"][0] == pytest.approx(0.75 - 0.70)
    # both styles have fewer than FEW counter games (10 and 2), so none enters the automatic standardized rate
    assert res["standardized"]["styles"] == []
    res2 = cm.paired_bootstrap(g, np.array(mem, dtype=np.int8), g["player"], n_boot=200, seed=0, styles_inc=["S", "T"])
    assert res2["standardized"]["rate"]["counter"] == pytest.approx((0.8 + 0.5) / 2)
    assert res2["standardized"]["rate"]["field"] == pytest.approx((0.5 + 1.0) / 2)


def test_style_inclusion_needs_few_games_in_every_group():
    rows, mem = [], []
    for st, n in (("S", cm.FEW), ("T", cm.FEW - 1)):
        for i in range(n):
            rows.append((f"{st}{i}", "A", "d", st, i % 2, f"p{st}{i}", "o"))
            mem.append((1, 1, 1))
    g = games_frame(rows)
    res = cm.paired_bootstrap(g, np.array(mem, dtype=np.int8), g["player"], n_boot=50, seed=0)
    assert res["standardized"]["styles"] == ["S"]


def test_clustering_on_players_widens_the_range_when_players_repeat():
    # 40 players, 10 games each, every player wins all or nothing: player clusters must give a much wider
    # range for the counter-vs-field difference than treating each game as its own cluster
    rows, mem = [], []
    for p in range(40):
        for i in range(10):
            rows.append((f"b{p}-{i}", "A", "d", "S", int(p % 2 == 0), f"p{p}", f"o{p}-{i}"))
            mem.append((1 if p < 20 else 0, 0 if p < 20 else 1, 1))
    g = games_frame(rows)
    m = np.array(mem, dtype=np.int8)
    by_player = cm.paired_bootstrap(g, m, g["player"], n_boot=1000, seed=5)
    by_game = cm.paired_bootstrap(g, m, [None] * len(g), n_boot=1000, seed=5)
    w = lambda r: r["vs_field"][2] - r["vs_field"][1]  # noqa: E731
    assert by_game["clusters"] == len(g) and by_player["clusters"] == 40
    assert w(by_player) > 2 * w(by_game)


def test_same_seed_same_ranges():
    rng = np.random.default_rng(2)
    g = games_frame([(f"b{i}", "A", "d", "S", int(rng.random() < 0.5), f"p{i % 30}", f"o{i % 11}") for i in range(300)])
    m = np.array([(i % 3 == 0, i % 3 == 1, 1) for i in range(300)], dtype=np.int8)
    assert cm.paired_bootstrap(g, m, g["player"], 400, 9) == cm.paired_bootstrap(g, m, g["player"], 400, 9)


def test_memberships_count_only_styles_with_a_counter_list():
    g = games_frame([("b1", "A", "x", "S", 1, "p", "o"), ("b2", "A", "y", "S", 0, "p", "o"),
                     ("b3", "A", "x", "T", 1, "p", "o"), ("b4", "A", "z", "S", 1, "p", "o")])
    m = cm.memberships(g, {"S": ["x"]}, ["x", "y"])
    assert m.tolist() == [[1, 1, 1], [0, 1, 1], [0, 0, 0], [0, 0, 1]]


def test_verdict_words_follow_the_ranges():
    base = {"games": {"counter": 100}, "vs_field": [0.1, 0.02, 0.2], "vs_all": [0.1, 0.05, 0.2]}
    assert cm.check_verdict(base, 30) == "beats_strongest"
    assert cm.check_verdict(dict(base, vs_field=[0.1, -0.01, 0.2]), 30) == "beats_average"
    assert cm.check_verdict(dict(base, vs_field=[0.0, -0.1, 0.1], vs_all=[0.0, -0.1, 0.1]), 30) == "not_shown"
    assert cm.check_verdict(dict(base, games={"counter": 10}), 30) == "too_few"


# ---------------------------------------------------------------- on a real (synthetic) Context
@pytest.fixture(scope="module")
def setup(small_ctx):
    ctx = small_ctx
    pool = cm.counter_pool(ctx, 5, 400)
    return ctx, pool, cm.test_games(ctx, pool)


def test_test_games_match_the_exported_record_counting(setup):
    ctx, pool, games = setup
    rec, _ = cm.deck_records(ctx, pool, cm.new_player_sides(ctx))
    for d, by_style in list(rec.items())[:20]:
        mine = games[games["deck"] == d]
        assert len(mine) == sum(n for n, _ in by_style.values()) and int(mine["won"].sum()) == sum(w for _, w in by_style.values())
    assert games["player"].notna().all() and (games["player"] != games["opponent"]).all()


def test_retrospective_version_reproduces_backtest_counts(setup):
    ctx, pool, games = setup
    if not ctx.archetype.fitted:
        pytest.skip("synthetic labels too few for a style classifier")
    s = Searcher(ctx)
    styles = cm.opponent_sets(ctx, 10)["styles"]
    new = cm.new_player_sides(ctx)
    rec, rec_new = cm.deck_records(ctx, pool, new)
    bt = cm.backtest(ctx, ctx.matchup, s, pool, styles, rec, rec_new, 5, 3)
    v = cm.check_version(ctx, ctx.matchup, s, pool, styles, games, new, 5, 3, n_boot=50, seed=1)
    if bt is None:
        assert v["populations"]["all_players"]["games"]["all"] == 0
        return
    for g in cm.GROUPS:
        assert v["populations"]["all_players"]["games"][g] == bt["pooled"][g]["games"]
        assert v["populations"]["all_players"]["wins"][g] == bt["pooled"][g]["wins"]


def test_forward_inputs_come_only_from_the_validation_window(setup):
    ctx, pool, _ = setup
    valid = set(pd.concat([ctx.split.valid["deck_a"], ctx.split.valid["deck_b"]]))
    for decks in cm.style_sets(ctx, ctx.split.valid, 10).values():
        assert all(d in valid for d, _ in decks)
    f = cm.window_scorer(ctx, ctx.split.valid)
    assert f.scorer is not ctx.scorer and f.strength is ctx.strength and f.matchup is ctx.matchup   # models shared, not refitted
    assert len(f.scorer.opp_u) == min(ctx.cfg["deck_score"]["n_opponent_decks"], 2 * len(ctx.split.valid))


def test_the_script_never_trains(tmp_path, monkeypatch):
    # a stale cache is skipped with a reason; the script has no path to load_context or _train_context
    spec = importlib.util.spec_from_file_location("counter_eval", ROOT / "scripts" / "counter_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = (ROOT / "scripts" / "counter_eval.py").read_text(encoding="utf-8")
    assert "load_context(" not in src.split('"""', 2)[2] and "_train_context" not in src
    import pickle
    from crdeck.config import Paths
    paths = Paths(source="synthetic", root=tmp_path)
    paths.processed.mkdir(parents=True)
    with (paths.processed / "context_cache_x.pkl").open("wb") as f:
        pickle.dump(("old-fingerprint", object()), f)
    ctx, why = mod.cached_context(paths, "x", "new-fingerprint")
    assert ctx is None and "stale" in why
    assert mod.cached_context(paths, "missing", "fp") == (None, "no cached models")
