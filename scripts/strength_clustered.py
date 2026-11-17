"""Player-clustered ranges for the win model against its baselines, every exported mode (BLUEPRINT 9.3).

    python scripts/strength_clustered.py [slug ...]      (default: every exported mode)

Writes web/strength_clustered.json: {"written_at", "settings", "modes": {slug: [row per baseline] | {"skipped": why}}}.
The builder's estimate gate (UI.estimateGate) uses the clustered range when this file is present.

Models come from each mode's cache, read-only. A mode whose cache fingerprint no longer matches is skipped and listed,
never retrained (this script never calls load_context).
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.config import Paths  # noqa: E402
from crdeck.evalx import clustered as cl  # noqa: E402
from crdeck.pipeline import _fingerprint  # noqa: E402

WEB = ROOT / "web"


def cached_context(paths: Paths, slug: str, fp: str):
    f = paths.processed / f"context_cache_{slug}.pkl"
    if not f.exists():
        return None, "no cached models"
    with f.open("rb") as fh:
        saved, ctx = pickle.load(fh)
    if saved != fp:
        return None, "cached models are stale (fingerprint changed); not retrained"
    return ctx, None


def r6(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, list):
        return [r6(v) for v in x]
    if isinstance(x, dict):
        return {k: r6(v) for k, v in x.items()}
    return x


def main(slugs: list[str]) -> int:
    paths = Paths.for_source("real")
    fp = _fingerprint(paths)
    index = json.loads((WEB / "modes.json").read_text(encoding="utf-8"))
    modes = [m for m in index["modes"] if m["status"] == "exported" and (not slugs or m["slug"] in slugs)]
    target = WEB / "strength_clustered.json"
    out = {"written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "settings": {"replicates": cl.N_BOOT, "seed": cl.SEED, "interval": 0.9, "unit": "player of side A", "sensitivity": "player of side B"},
           "modes": json.loads(target.read_text(encoding="utf-8")).get("modes", {}) if slugs and target.exists() else {}}
    for m in modes:
        t0 = time.time()
        ctx, why = cached_context(paths, m["slug"], fp)
        out["modes"][m["slug"]] = {"skipped": why} if ctx is None else (r6(cl.clustered_significance(ctx)) or {"skipped": "no player table"})
        res = out["modes"][m["slug"]]
        if isinstance(res, list):
            c = next(r for r in res if r["vs"] == "constant_0.5")
            print(f"{m['slug']}: vs coin flip {c['delta']:+.5f} (90% {c['lo']:+.5f} to {c['hi']:+.5f}), {c['players']} players, {c['battles']} battles; {time.time() - t0:.0f}s", flush=True)
        else:
            print(m["slug"], res["skipped"], flush=True)
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
