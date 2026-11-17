"""The derivative snapshot behind the custom loss surfaces (crdeck.explore.landscape_snapshot), merged from the
loss-surface branch without touching crdeck/landscape.py, and its website file (crdeck.explore.loss_surface)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from crdeck import landscape
from crdeck.explore import landscape_snapshot as ls
from crdeck.explore import loss_surface
from crdeck.explore.landscape_snapshot import packed_index, snapshot, unpack
from crdeck.landscape import _training_rows, report, surface


# ---------------------------------------------------------------- the derivative snapshot behind custom pairs

def _objective(ctx):
    """The full regularized objective as a function of all weights, written out independently of snapshot()."""
    model = ctx.strength
    X, y = _training_rows(model, ctx.split.train_valid)
    n, C = X.shape[0], float(model.C)
    return lambda w: float((np.logaddexp(0, X @ w) - y * (X @ w)).mean() + (w @ w) / (2 * C * n)), model.lr.coef_.ravel().astype(float)


def test_packed_index_covers_the_upper_triangle_once():
    m = 7
    seen = sorted(packed_index(i, j, m) for i in range(m) for j in range(i, m))
    assert seen == list(range(m * (m + 1) // 2))
    assert all(packed_index(i, j, m) == packed_index(j, i, m) for i in range(m) for j in range(m))
    # the same order as numpy's row-major upper triangle
    iu = np.triu_indices(m)
    assert [packed_index(i, j, m) for i, j in zip(*iu)] == list(range(len(iu[0])))


def test_snapshot_covers_every_card_form_and_unpacks_symmetric(small_ctx):
    model = small_ctx.strength
    s = snapshot(small_ctx)
    m = model.n_card_features
    assert s["keys"] == sorted(model.card_weights) and len(s["keys"]) == m      # card forms only: no pair or rating column
    assert len(s["weights"]) == len(s["g"]) == m and len(s["h_packed"]) == m * (m + 1) // 2
    assert np.allclose(s["weights"], [model.card_weights[k] for k in s["keys"]])
    assert np.all(np.isfinite(s["h_packed"])) and np.isfinite(s["J0"])
    H = unpack(s["h_packed"], m)
    assert np.array_equal(H, H.T)
    for i, j in [(0, 0), (0, m - 1), (3, 5), (m - 1, m - 1)]:
        assert H[i, j] == s["h_packed"][packed_index(i, j, m)]
    assert np.linalg.eigvalsh(H).min() > 0      # the fitted point is a minimum along every card-form direction
    assert s["half_width"] == ls.LOCAL_HALF_WIDTH and s["C"] == float(model.C)


def test_snapshot_matches_the_exact_slice_and_finite_differences(small_ctx):
    model = small_ctx.strength
    s = snapshot(small_ctx)
    J, w = _objective(small_ctx)
    m = len(s["keys"])
    H = unpack(s["h_packed"], m)
    # J0 is the exact surface's value at its centre (same battles, same penalty, pair and rating terms included)
    ka, kb = s["keys"][0], s["keys"][1]
    ex = surface(small_ctx, ka, kb)
    assert abs(s["J0"] - ex["fitted_loss"]) < 1e-12 and abs(s["J0"] - J(w)) < 1e-12
    assert s["n_train"] == ex["n_train"]
    # central differences of the objective itself (step 1e-4)
    h = 1e-4
    rng = np.random.default_rng(3)
    idx = sorted(set([0, 1, m - 1] + list(rng.choice(m, 4, replace=False))))
    for i in idx:
        e = np.zeros_like(w); e[model.index[s["keys"][i]]] = h
        assert abs((J(w + e) - J(w - e)) / (2 * h) - s["g"][i]) < 1e-7
    for i, j in [(idx[0], idx[0]), (idx[0], idx[1]), (idx[1], idx[-1]), (idx[-1], idx[-1])]:
        ei = np.zeros_like(w); ei[model.index[s["keys"][i]]] = h
        ej = np.zeros_like(w); ej[model.index[s["keys"][j]]] = h
        fd = (J(w + ei + ej) - J(w + ei - ej) - J(w - ei + ej) + J(w - ei - ej)) / (4 * h * h)
        assert abs(fd - H[i, j]) < 1e-6
    # the quadratic tracks the exact slice near the fitted point (local approximation, not global)
    ia, ib = 0, 1
    for u, v in [(5, 25), (30, 12), (20, 20)]:
        d = np.array([ex["a"][u] - ex["fitted"][0], ex["b"][v] - ex["fitted"][1]])
        Hab = np.array([[H[ia, ia], H[ia, ib]], [H[ia, ib], H[ib, ib]]])
        q = s["J0"] + np.dot([s["g"][ia], s["g"][ib]], d) + 0.5 * d @ Hab @ d
        rise = ex["loss"][u][v] - ex["fitted_loss"]
        assert abs(q - ex["loss"][u][v]) <= 0.05 * rise + 1e-12


def test_snapshot_leaves_the_exact_presets_unchanged(small_ctx):
    before = json.dumps(report(small_ctx))
    snapshot(small_ctx)
    assert json.dumps(report(small_ctx)) == before
    labels = [s["label"] for s in report(small_ctx)["slices"]]
    assert labels == ["The two most-played card forms", "The two strongest common cards", "The two weakest common cards"]


def test_export_file_is_small_aggregate_and_computed_once(small_ctx):
    calls = []
    text, ref = loss_surface.export(small_ctx, snapshot=lambda ctx: calls.append(1) or ls.snapshot(ctx))
    assert len(calls) == 1
    size = len(text.encode("utf-8"))
    assert size < 500_000 and ref["bytes"] == size and ref["file"] == "loss_surface.json"
    j = json.loads(text)
    m = len(j["forms"])
    assert j["schema_version"] == 1 and j["source_mode"] == "ranked" and j["snapshot_id"] == ref["snapshot_id"] and ref["forms"] == m
    assert set(j) == {"schema_version", "source_mode", "objective", "approximation", "packing", "n_train", "C", "half_width",
                      "J0", "forms", "weights", "g", "h_packed", "snapshot_id"}       # aggregates only: no battle rows
    assert len(j["weights"]) == len(j["g"]) == m and len(j["h_packed"]) == m * (m + 1) // 2
    assert [f[0] for f in j["forms"]] == sorted(small_ctx.strength.card_weights)
    assert all(f[3] in ("troop", "spell", "building") and f[3] == small_ctx.cards[int(f[0].split(":")[0])].card_type for f in j["forms"])
    s = ls.snapshot(small_ctx)
    assert np.allclose(j["h_packed"], s["h_packed"], rtol=1e-9, atol=0) and abs(j["J0"] - s["J0"]) < 1e-15
    # the identity is a hash of the content: the same model gives the same id
    assert loss_surface.export(small_ctx)[1]["snapshot_id"] == ref["snapshot_id"]


def test_landscape_module_is_untouched_so_no_retrain():
    """The branch edited crdeck/landscape.py, which is fingerprinted. Here it must stay byte-identical to the trained
    version (commit f18911e), and the snapshot code lives in a subpackage the fingerprint doesn't read."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "show", "f18911e:src/crdeck/landscape.py"], cwd=root, capture_output=True, check=True).stdout
    norm = lambda b: b.replace(bytes([13, 10]), bytes([10]))  # noqa: E731  (CRLF to LF)
    assert norm((root / "src" / "crdeck" / "landscape.py").read_bytes()) == norm(head)
    assert not hasattr(landscape, "snapshot")
