"""Forward check of the counter deck builder for every exported mode (crdeck.evalx.counter_builder_check; experimental).

    python scripts/counter_builder_eval.py [slug ...]      (default: every exported mode)

Adds a "builder" entry to each mode in web/counter_eval.json and keeps everything else in that file. The Find counters
page shows its verdict under the builder's decks. Models come from each mode's cache, read-only: a stale cache is
skipped, never retrained.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from counter_eval import cached_context, r5  # noqa: E402
from crdeck import counters as cm  # noqa: E402
from crdeck.config import Paths  # noqa: E402
from crdeck.evalx import counter_builder_check as cbc  # noqa: E402
from crdeck.pipeline import _fingerprint  # noqa: E402
from crdeck.search import Searcher  # noqa: E402

WEB = ROOT / "web"


def main(slugs: list[str]) -> int:
    paths = Paths.for_source("real")
    fp = _fingerprint(paths)
    index = json.loads((WEB / "modes.json").read_text(encoding="utf-8"))
    target = WEB / "counter_eval.json"
    body = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"modes": {}}
    body.setdefault("builder_settings", {"queries": cbc.QUERIES, "replicates": cbc.REPLICATES, "seed": cbc.SEED, "min_overlap": cbc.MIN_OVERLAP,
                                         "min_games": cbc.MIN_GAMES, "design": "crdeck/evalx/counter_builder_check.py docstring; docs/fable-brief/BLUEPRINT.md 8.4.1"})
    cfg = cm.counters_config()
    for m in [m for m in index["modes"] if m["status"] == "exported" and (not slugs or m["slug"] in slugs)]:
        t0 = time.time()
        ctx, why = cached_context(paths, m["slug"], fp)
        if ctx is None or ctx.matchup is None:
            res = {"skipped": why or "no matchup model"}
        else:
            pool = cm.counter_pool(ctx, int(cfg["pool"]["min_battles"]), int(cfg["pool"]["max_decks"]))
            res = cbc.run(ctx, ctx.matchup, Searcher(ctx), pool) if pool else {"skipped": "no real-deck pool"}
        body["modes"].setdefault(m["slug"], {})["builder"] = r5(res)
        print(m["slug"], f"{time.time() - t0:.0f}s", res.get("skipped") or f"{res['verdict']}: builder {res['games']['builder']} games, vs random {res.get('vs_random')}", flush=True)
    target.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
