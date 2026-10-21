"""The fitted strength model sits exactly at the bottom of its loss surface, and the drawn slices agree."""

from __future__ import annotations

import numpy as np

from crdeck.landscape import GRID, report, surface


def test_fit_reaches_the_exact_minimum(small_ctx):
    m = small_ctx.strength
    assert m.max_gradient < 1e-8          # L-BFGS, then exact Newton steps


def test_slice_bottom_is_the_fitted_point_and_its_gradient_is_zero(small_ctx):
    m = small_ctx.strength
    ka, kb = sorted(m.card_weights, key=lambda k: -m.feature_games.get(k, 0))[:2]
    s = surface(small_ctx, ka, kb)
    L = np.array(s["loss"])
    assert np.unravel_index(L.argmin(), L.shape) == (GRID // 2, GRID // 2)
    mid = len(s["grad_a"]) // 2
    assert abs(s["grad_a"][mid][mid]) < 1e-8 and abs(s["grad_b"][mid][mid]) < 1e-8
    assert np.allclose([s["a"][GRID // 2], s["b"][GRID // 2]], s["fitted"])
    # the gradient points uphill: away from the bottom on both sides
    assert s["grad_a"][0][mid] < 0 < s["grad_a"][-1][mid]


def test_descent_path_goes_downhill_to_the_bottom(small_ctx):
    s = report(small_ctx)["slices"][0]
    losses = [q[2] for q in s["path"]]
    assert all(b <= a + 1e-12 for a, b in zip(losses, losses[1:]))
    assert losses[-1] - s["fitted_loss"] < 0.05 * (losses[0] - s["fitted_loss"])
