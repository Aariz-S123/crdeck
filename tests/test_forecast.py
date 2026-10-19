"""Forecast machinery on constructed share data: the gate, the backtest and the drift fit.
(Constructed numbers here only test the code; no forecast is ever shown from them.)"""

from __future__ import annotations

import numpy as np
import pandas as pd

from crdeck.forecast import MIN_PERIODS, backtest, collection_periods, fit_drift, monte_carlo


def stats_from_dynamics(P=6, K=40, beta=6.0, n=20000, seed=0):
    """Shares evolving by the replicator rule with true win rates; bootstrap draws = binomial noise."""
    rng = np.random.default_rng(seed)
    s = rng.uniform(0.03, 0.4, K)
    wr_true = rng.uniform(0.46, 0.54, K)
    share, wr, games = [], [], []
    for p in range(P):
        obs = rng.binomial(n, s) / n
        g = obs * n
        share.append(obs); wr.append(rng.binomial(g.astype(int), wr_true) / np.maximum(g, 1)); games.append(g)
        s = 1 / (1 + np.exp(-(np.log(s / (1 - s)) + beta * (wr_true - 0.5))))
    share, wr, games = np.array(share), np.array(wr), np.array(games)
    B = 200
    sb = np.clip(share[:, None, :] + rng.normal(0, 1, (P, B, K)) * np.sqrt(share * (1 - share) / n)[:, None, :], 0, 1)
    wb = np.clip(wr[:, None, :] + rng.normal(0, 1, (P, B, K)) * np.sqrt(wr * (1 - wr) / np.maximum(games, 1))[:, None, :], 0, 1)
    return {"share": share, "wr": wr, "games": games, "share_boot": sb, "wr_boot": wb}, [n] * P


def test_fit_drift_recovers_beta():
    st, _ = stats_from_dynamics(beta=6.0)
    a, b = fit_drift(st["share"], st["wr"], st["games"], [0, 1, 2], min_games=200)
    assert 3.0 < b < 9.0


def test_backtest_beats_no_change_when_dynamics_exist():
    st, n = stats_from_dynamics(beta=8.0)
    bt = backtest(st, n, runs=300, seed=1, min_games=200)
    assert len(bt) == 4  # periods 2..5
    assert bt["mae_points_monte_carlo"].mean() < bt["mae_points_no_change"].mean()
    assert bt["coverage_90"].mean() > 0.6


def test_backtest_does_not_beat_no_change_without_dynamics():
    st, n = stats_from_dynamics(beta=0.0, seed=3)
    bt = backtest(st, n, runs=300, seed=1, min_games=200)
    # with no real dynamics the forecast can only add noise; it should not clearly beat no change
    assert bt["mae_points_monte_carlo"].mean() >= bt["mae_points_no_change"].mean() * 0.9


def test_monte_carlo_is_seeded():
    st, n = stats_from_dynamics()
    a = monte_carlo(st, 2, [0, 1], n[3], runs=50, seed=7, min_games=200)
    b = monte_carlo(st, 2, [0, 1], n[3], runs=50, seed=7, min_games=200)
    assert np.array_equal(a, b)


def test_periods_do_not_overlap_and_minimum_is_three():
    m = pd.DataFrame({"window_id": ["w1", "w1", "w2", "w3"], "kind": ["battlelog"] * 4,
                      "fetched_at": ["2026-10-19T01:00:00Z", "2026-10-19T01:30:00Z", "2026-10-20T01:30:00Z", "2026-10-21T02:00:00Z"]})
    per = collection_periods(m, 24)
    assert list(per["window_id"]) == ["w1", "w2", "w3"]
    assert (per["start"].iloc[1:].to_numpy() == per["end"].iloc[:-1].to_numpy()).all()
    assert (per["end"].iloc[0] - per["start"].iloc[0]).total_seconds() == 24 * 3600
    assert MIN_PERIODS == 3
