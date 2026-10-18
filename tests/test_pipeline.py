"""End-to-end on small SYNTHETIC data: reproducibility, no fallbacks, signal recovery."""

from __future__ import annotations

import json

import numpy as np
import pytest

from crdeck.config import Paths
from crdeck.pipeline import NoDataError, build, load_context
from crdeck.synthetic import SynthConfig, generate


def test_build_counts_and_dedupe(small_ctx):
    c = small_ctx.counts
    assert c["battle_rows_before_dedupe"] == 2 * c["battles_after_dedupe"]
    assert c["status"]["OK"] > 0
    for s in ("MIRROR", "DRAW", "FILTERED_TYPE"):
        assert c["status"].get(s, 0) > 0
    assert c["unknown_card_ids"] == [99_999_999] or c["status"].get("UNKNOWN_CARD", 0) == 0


def test_rerun_gives_identical_outputs(tmp_path):
    outs = []
    for i in range(2):
        paths = Paths(source="synthetic", root=tmp_path / f"run{i}")
        generate(SynthConfig(n_players=60, n_battles=2500, seed=5), paths=paths)
        counts = build(paths=paths, verbose=False)
        ctx = load_context(paths=paths)
        outs.append((counts["status"], ctx.strength.coef.copy(), ctx.model_comparison["log_loss"].tolist()))
    assert outs[0][0] == outs[1][0]
    assert np.allclose(outs[0][1], outs[1][1])
    assert np.allclose(outs[0][2], outs[1][2])


def test_missing_real_data_raises_instead_of_substituting(tmp_path):
    paths = Paths(source="real", root=tmp_path)
    with pytest.raises(NoDataError, match="gate"):
        build(paths=paths, verbose=False)
    with pytest.raises(FileNotFoundError):
        load_context(paths=paths)


def test_card_model_beats_baselines_on_test(small_ctx):
    comp = small_ctx.model_comparison
    test = comp[comp["part"] == "test"].set_index("model")
    chosen = comp.loc[comp["selected"], "model"].iloc[0]
    assert test.loc[chosen, "log_loss"] < test.loc["constant_0.5", "log_loss"]
    assert test.loc[chosen, "log_loss"] < test.loc["popularity", "log_loss"]


def test_planted_synergy_scores_above_typical_pairs(tmp_path):
    """Individual pair estimates are noisy when deck choice is tied to player skill: across
    seeds 11-14 with 400 players, 4 to 8 of the 8 planted pairs came out positive. What held
    in every run is that planted pairs average above the median pair. Seed 12 was the
    weakest of those runs, so it is the one tested."""
    paths = Paths(source="synthetic", root=tmp_path)
    generate(SynthConfig(n_players=400, n_battles=16000, seed=12), paths=paths)
    build(paths=paths, verbose=False)
    ctx = load_context(paths=paths, cache=False)
    truth = json.loads((paths.root / "truth.json").read_text())
    planted = [r["synergy"] for p in truth["planted_synergy"]
               if (r := ctx.synergy.pair(p["a_id"], p["b_id"])) is not None and r["status"] == "OK"]
    scored = ctx.synergy.pairs.query("status == 'OK'")["synergy"]
    assert len(planted) == 8
    assert np.mean(planted) > scored.median()


def test_build_writes_raw_manifest(small_ctx):
    import pandas as pd
    m = pd.read_csv(small_ctx.paths.root / "raw_manifest.csv")
    assert {"cards", "battlelog", "leaderboard"} <= set(m["kind"])
    assert m["fetched_at"].notna().all() and (m["status"] == 200).all()
