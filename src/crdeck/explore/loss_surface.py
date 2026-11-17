"""web/loss_surface.json: the Ranked model's card-form weights, gradient and packed Hessian (aggregates only, no battle
rows), for the approximate custom loss surfaces on How it works. Written by scripts/loss_surface_export.py from the
cached Ranked model, and by scripts/export_web.py after a full export."""

from __future__ import annotations

import hashlib
import json
import math

from . import landscape_snapshot as ls

FILE_NAME = "loss_surface.json"
MAX_BYTES = 500_000


def _r6(x: float) -> float:
    return float(f"{float(x):.10g}")


def export(ctx, snapshot=None) -> tuple[str, dict]:
    """(file text, reference for modes.json). `snapshot` defaults to landscape_snapshot.snapshot."""
    s = (snapshot or ls.snapshot)(ctx)
    m = len(s["keys"])
    forms = []
    for k, games in zip(s["keys"], s["games"]):
        cid, form = k.split(":")
        c = ctx.cards[int(cid)]
        if c.card_type not in ("troop", "spell", "building"):
            raise ValueError(f"loss surface: {k} has card type {c.card_type!r}")
        forms.append([k, c.name, form, c.card_type, int(games)])
    nums = [s["J0"], s["C"], *s["weights"], *s["g"], *s["h_packed"]]
    if not all(math.isfinite(x) for x in nums) or len(s["h_packed"]) != m * (m + 1) // 2 or len(s["g"]) != m:
        raise ValueError("loss surface: invalid derivative snapshot")
    body = {"schema_version": 1, "source_mode": "ranked",
            "objective": "mean log loss + ‖w‖² / (2 C N); other weights fixed at their fitted values",
            "approximation": "J ≈ J0 + g·d + ½ dᵀ H d, d = weights − fitted weights",
            "packing": "upper triangle of H, row by row: index(i, j) = i·m − i·(i − 1)/2 + (j − i), i ≤ j",
            "n_train": s["n_train"], "C": s["C"], "half_width": s["half_width"], "J0": s["J0"],
            "forms": forms, "weights": [_r6(x) for x in s["weights"]], "g": [_r6(x) for x in s["g"]],
            "h_packed": [_r6(x) for x in s["h_packed"]]}
    sid = hashlib.sha256(json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()[:16]
    text = json.dumps({**body, "snapshot_id": sid}, separators=(",", ":"), allow_nan=False)
    size = len(text.encode("utf-8"))
    if size >= MAX_BYTES:
        raise ValueError(f"loss surface: {size} bytes, over the {MAX_BYTES} limit")
    return text, {"file": FILE_NAME, "snapshot_id": sid, "bytes": size, "forms": m}
