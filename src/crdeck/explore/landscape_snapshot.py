"""Second-order picture of the Ranked model's loss around its fitted weights, for the custom loss surfaces on How it
works (any pair of card forms, drawn as an approximation).

Moved here from the loss-surface branch (agents/20261112T115234Z-520f12) so that crdeck/landscape.py stays exactly as
trained: a subpackage is outside crdeck.pipeline._fingerprint, so this never forces a retrain. It only reads the
fitted model through crdeck.landscape's helpers.

J0, the gradient and the card-form Hessian at the fitted point, computed once. The website draws a custom pair from
the local quadratic J ≈ J0 + g·d + ½ dᵀ H d and labels it approximate; the three exact slices of
crdeck.landscape.report() are unchanged.
"""

from __future__ import annotations

import numpy as np
from scipy import sparse

from ..landscape import _training_rows
from ..strength import sigmoid

LOCAL_HALF_WIDTH = 0.05   # custom (approximate) slices: ± this many log-odds around each fitted weight


def packed_index(i: int, j: int, m: int) -> int:
    """Position of H[i, j] in the upper triangle of an m×m symmetric matrix stored row by row."""
    if i > j:
        i, j = j, i
    return i * m - i * (i - 1) // 2 + (j - i)


def snapshot(ctx) -> dict:
    """Same objective and battles as crdeck.landscape.surface(), at the full fitted prediction z = X w (pair weights and
    the rating term included and held fixed). For the card-form weights c:

        J0 = mean( ln(1 + e^z) − y z ) + ‖w‖² / (2 C N)
        g  = X_cᵀ (p − y) / N + w_c / (C N)
        H  = X_cᵀ diag(p (1 − p)) X_c / N + I / (C N)

    H is the card-form block of the mean-objective Hessian with every other weight fixed (not the inverse covariance),
    returned as its upper triangle, row by row (packed_index)."""
    model = ctx.strength
    X, y = _training_rows(model, ctx.split.train_valid)
    w = model.lr.coef_.ravel().astype(float)
    n, C = X.shape[0], float(model.C)
    m = int(model.n_card_features)
    keys = [None] * m
    for k, i in model.index.items():
        if i < m:
            keys[i] = k
    z = X @ w
    p = sigmoid(z)
    j0 = float((np.logaddexp(0, z) - y * z).mean() + (w @ w) / (2 * C * n))
    Xc = X[:, :m]
    wc = w[:m]
    g = np.asarray(Xc.T @ (p - y)).ravel() / n + wc / (C * n)
    H = (Xc.T @ sparse.diags(p * (1 - p)) @ Xc).toarray() / n + np.eye(m) / (C * n)
    iu = np.triu_indices(m)   # row-major upper triangle: the order packed_index describes
    return {"keys": keys, "weights": [float(x) for x in wc], "J0": j0, "g": [float(x) for x in g],
            "h_packed": [float(x) for x in H[iu]], "n_train": int(n), "C": C,
            "games": [int(model.feature_games.get(k, 0)) for k in keys], "half_width": LOCAL_HALF_WIDTH}


def unpack(h_packed, m: int) -> np.ndarray:
    H = np.zeros((m, m))
    H[np.triu_indices(m)] = h_packed
    return H + np.triu(H, 1).T
