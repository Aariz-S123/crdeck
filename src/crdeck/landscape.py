"""The strength model's real training loss as a surface, for the "How the model learns" picture.

The fitted model minimizes (scikit-learn's objective, divided by C·N to read per battle):

    J(w) = mean over training battles of [ −y ln p − (1 − y) ln(1 − p) ]  +  ‖w‖² / (2 C N),   p = σ(wᵀx)

A full picture of J would need all 185 weights at once. The surface here is an honest 2D slice: two
card weights a and b vary around their fitted values while every other weight (and the rating term)
stays exactly as trained. Each grid point is J computed on the battles the final model is fitted on
(the training and validation windows together), and the gradient there is exact:

    ∂J/∂a = mean( (p − y) · x_a ) + a / (C N)        (same for b)

The descent path is plain gradient descent on this slice (step STEP / largest curvature), shown only
to illustrate what "following the gradient" means; the real fit is L-BFGS over all weights, finished
with exact Newton steps (crdeck.strength.CardModel.fit).
"""

from __future__ import annotations

import numpy as np

from .strength import rating_diff, sigmoid

GRID = 41
ARROWS = 9
PATH_STEPS = 40
STEP = 0.3       # descent step as a share of 1 / largest curvature: small enough that the path is visible


def _training_rows(model, df):
    X = model._vector_rows(df["deck_a"]) - model._vector_rows(df["deck_b"])
    from scipy import sparse
    if model.skill_control:
        X = sparse.hstack([X, sparse.csr_matrix(model._skill_scale * rating_diff(df).reshape(-1, 1))]).tocsr()
    return X.tocsc(), df["a_won"].astype(float).to_numpy()


def surface(ctx, key_a: str, key_b: str, half_width: float | None = None) -> dict:
    model = ctx.strength
    X, y = _training_rows(model, ctx.split.train_valid)  # the battles the final model is fitted on
    w = model.lr.coef_.ravel().astype(float)
    n, C = X.shape[0], float(model.C)
    ia, ib = model.index[key_a], model.index[key_b]
    xa, xb = X[:, ia].toarray().ravel(), X[:, ib].toarray().ravel()
    z0 = X @ w
    wa, wb = w[ia], w[ib]
    pen_rest = (w @ w - wa * wa - wb * wb) / (2 * C * n)
    # slice half-width: 4 standard errors of the larger of the two weights (Laplace), at least 0.05
    se = np.sqrt(np.clip(np.diag(model.cov)[[ia, ib]], 0, None))
    r = half_width or max(0.05, 4 * float(se.max()))
    ga, gb = np.linspace(wa - r, wa + r, GRID), np.linspace(wb - r, wb + r, GRID)
    loss = np.zeros((GRID, GRID))
    da = np.zeros((GRID, GRID))
    db = np.zeros((GRID, GRID))
    for i, a in enumerate(ga):
        base = z0 + (a - wa) * xa
        for j, b in enumerate(gb):
            z = base + (b - wb) * xb
            p = sigmoid(z)
            ll = np.logaddexp(0, z) - y * z        # = −y ln p − (1 − y) ln(1 − p), numerically stable
            loss[i, j] = ll.mean() + pen_rest + (a * a + b * b) / (2 * C * n)
            e = p - y
            da[i, j] = (e * xa).mean() + a / (C * n)
            db[i, j] = (e * xb).mean() + b / (C * n)
    # 2x2 curvature at the fitted point, for the descent step
    p0 = sigmoid(z0)
    v = p0 * (1 - p0)
    H = np.array([[(v * xa * xa).mean(), (v * xa * xb).mean()], [(v * xa * xb).mean(), (v * xb * xb).mean()]]) + np.eye(2) / (C * n)
    lr = STEP / float(np.linalg.eigvalsh(H).max())
    path, a, b = [], wa + 0.9 * r, wb + 0.9 * r   # a side corner in the default view, so the walk is visible
    for _ in range(PATH_STEPS + 1):
        z = z0 + (a - wa) * xa + (b - wb) * xb
        p = sigmoid(z)
        L = (np.logaddexp(0, z) - y * z).mean() + pen_rest + (a * a + b * b) / (2 * C * n)
        gA, gB = ((p - y) * xa).mean() + a / (C * n), ((p - y) * xb).mean() + b / (C * n)
        path.append([float(a), float(b), float(L), float(gA), float(gB)])
        a, b = a - lr * gA, b - lr * gB
    step = (GRID - 1) // (ARROWS - 1)
    return {"keys": [key_a, key_b], "fitted": [float(wa), float(wb)], "se": [float(x) for x in se],
            "games": [int(model.feature_games.get(key_a, 0)), int(model.feature_games.get(key_b, 0))],
            "a": [float(x) for x in ga], "b": [float(x) for x in gb],
            "loss": [[float(x) for x in row] for row in loss],
            "grad_a": [[float(da[i, j]) for j in range(0, GRID, step)] for i in range(0, GRID, step)],
            "grad_b": [[float(db[i, j]) for j in range(0, GRID, step)] for i in range(0, GRID, step)],
            "arrow_step": step, "fitted_loss": float(loss[GRID // 2, GRID // 2]),
            "path": path, "learning_rate": lr, "n_train": int(n), "C": C}


def report(ctx) -> dict:
    """Three slices of the Ranked model: the two most-played card forms, the two with the largest positive
    weights among forms with at least 1,000 training games, and the two with the most negative ones."""
    m = ctx.strength
    keys = [k for k in m.card_weights]
    games = m.feature_games
    by_games = sorted(keys, key=lambda k: -games.get(k, 0))
    common = [k for k in keys if games.get(k, 0) >= 1000]
    pos = sorted(common, key=lambda k: -m.card_weights[k])[:2]
    neg = sorted(common, key=lambda k: m.card_weights[k])[:2]
    out = []
    for label, (ka, kb) in (("The two most-played card forms", by_games[:2]), ("The two strongest common cards", pos),
                            ("The two weakest common cards", neg)):
        s = surface(ctx, ka, kb)
        s["label"] = label
        out.append(s)
    return {"slices": out, "objective": "mean log loss + ‖w‖² / (2 C N)", "path_note":
            f"plain gradient descent on this 2-weight slice, step {STEP} / largest curvature; the real fit is L-BFGS then Newton over all weights"}
