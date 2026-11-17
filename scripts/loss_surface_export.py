"""Write web/loss_surface.json from the cached Ranked model, without a retrain or a full export.

    python scripts/loss_surface_export.py

The Ranked model is read from its cache only when the cache fingerprint matches (as scripts/counter_eval.py does);
otherwise the script stops and says so. It also records the file's reference under "loss_surface" in web/modes.json,
which How it works reads.
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.config import Paths  # noqa: E402
from crdeck.explore import loss_surface  # noqa: E402
from crdeck.pipeline import _fingerprint  # noqa: E402

WEB = ROOT / "web"


def main() -> int:
    paths = Paths.for_source("real")
    f = paths.processed / "context_cache_ranked.pkl"
    if not f.exists():
        raise SystemExit("no cached Ranked model; run a full export instead")
    with f.open("rb") as fh:
        saved, ctx = pickle.load(fh)
    if saved != _fingerprint(paths):
        raise SystemExit("the cached Ranked model is stale (fingerprint changed); not retrained here")
    text, ref = loss_surface.export(ctx)
    (WEB / loss_surface.FILE_NAME).write_text(text, encoding="utf-8")
    modes = WEB / "modes.json"
    index = json.loads(modes.read_text(encoding="utf-8"))
    index["loss_surface"] = ref
    modes.write_text(json.dumps(index, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"wrote web/{loss_surface.FILE_NAME} ({ref['bytes'] / 1e3:.0f} kB, {ref['forms']} card forms, id {ref['snapshot_id']}); modes.json updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
