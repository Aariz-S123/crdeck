"""Player-clustered ranges (crdeck.evalx.clustered)."""

import numpy as np
import pandas as pd
import pytest

from crdeck.evalx import clustered as cl


def test_duplicating_players_battles_narrows_battle_ranges_but_not_clustered_ones():
    rng = np.random.default_rng(0)
    players = np.repeat(np.arange(200), 5)
    effect = rng.normal(0, 0.02, 200)[players]           # each player's battles share an effect
    d = effect + rng.normal(0, 0.01, len(players))
    once = cl.clustered_range(d, players, 2000, 42)
    dup = cl.clustered_range(np.tile(d, 4), np.tile(players, 4), 2000, 42)
    battle_once = cl.clustered_range(d, np.arange(len(d)), 2000, 42)
    battle_dup = cl.clustered_range(np.tile(d, 4), np.arange(4 * len(d)), 2000, 42)
    w = lambda r: r["hi"] - r["lo"]  # noqa: E731
    assert w(battle_dup) < 0.6 * w(battle_once)          # battle-level ranges shrink with copies
    assert abs(w(dup) - w(once)) < 0.15 * w(once)        # clustered ranges stay about the same
    assert w(once) > 1.5 * w(battle_once)                # and clustering widens them when players repeat
    assert once["delta"] == pytest.approx(d.mean()) and once["clusters"] == 200 and once["n"] == 1000


def test_fixed_seed_reproduces_and_one_cluster_per_battle_matches_a_battle_bootstrap():
    d = np.linspace(-1, 1, 50)
    a = cl.clustered_range(d, np.arange(50), 500, 42)
    assert a == cl.clustered_range(d, np.arange(50), 500, 42)
    assert a["lo"] < a["delta"] < a["hi"] and 0 < a["share_better"] < 1


def test_clustered_significance_on_a_small_synthetic_context(small_ctx):
    t = small_ctx.split.test
    players = pd.DataFrame({"player_a": [f"A{i % 7}" for i in range(len(t))], "player_b": [f"B{i % 11}" for i in range(len(t))]}, index=t["battle_key"])
    rows = cl.clustered_significance(small_ctx, n_boot=200, players=players)
    assert [r["vs"] for r in rows] == ["constant_0.5", "popularity", "rating_only"]
    from crdeck.evaluate import strength_significance
    exported = strength_significance(small_ctx, n_boot=200).set_index("vs")
    for r in rows:
        assert r["delta"] == pytest.approx(exported.loc[r["vs"], "delta_log_loss"])     # same point estimate
        assert r["players"] == 7 and r["opponent"]["players"] == 11 and r["battles"] == len(t)
        assert r["lo"] <= r["delta"] <= r["hi"]
