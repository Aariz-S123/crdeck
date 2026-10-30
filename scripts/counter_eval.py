"""Forward check of the counter recommendations for every exported mode (design, fixed before any result:
docs/claude-redesign/EVAL-DESIGN.md). Writes web/counter_eval.json, which the Counters page shows next to
the exported (retrospective) check.

Each mode's models are read from its model cache, read-only: a mode whose cache fingerprint no longer matches
the data, labels, config and code is skipped and listed, never retrained (this script does not call
load_context, which would retrain). Nothing exported today is changed.

For each mode, two versions run through the same code (crdeck.counters.check_version):
  retrospective  opponent decks per style and the general score's opponent sample from the test window,
                 as exported (its counts must equal the exported check's; recorded as matches_export)
  forward        both from the validation window, so every input is known before the test window

    python scripts/counter_eval.py [slug ...]        (default: every exported mode)
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

from crdeck import counters as cm  # noqa: E402
from crdeck.config import Paths  # noqa: E402
from crdeck.pipeline import _fingerprint  # noqa: E402
from crdeck.search import Searcher  # noqa: E402

WEB = ROOT / "web"
N_BOOT, SEED = 2000, 42


def cached_context(paths: Paths, slug: str, fp: str):
    """(ctx, None) from the mode's model cache, or (None, why) when it is missing or stale. Never trains."""
    f = paths.processed / f"context_cache_{slug}.pkl"
    if not f.exists():
        return None, "no cached models"
    with f.open("rb") as fh:
        saved, ctx = pickle.load(fh)
    if saved != fp:
        return None, "cached models are stale (fingerprint changed); not retrained"
    return ctx, None


def r5(x):
    """Round floats (also inside lists and dicts) to 5 decimals for a compact file."""
    if isinstance(x, float):
        return round(x, 5)
    if isinstance(x, list):
        return [r5(v) for v in x]
    if isinstance(x, dict):
        return {k: r5(v) for k, v in x.items()}
    return x


def slim(v: dict) -> dict:
    """What the page needs from a version: drop the per-style deck lists."""
    return {k: x for k, x in v.items() if k not in ("counter", "field")}


def run_mode(ctx, exported: dict) -> dict:
    cfg = cm.counters_config()
    top, min_games, per_set = int(cfg["backtest"]["top"]), int(cfg["backtest"]["min_games"]), int(cfg["opponents_per_set"])
    pool = cm.counter_pool(ctx, int(cfg["pool"]["min_battles"]), int(cfg["pool"]["max_decks"]))
    if not pool:
        return {"skipped": "no real-deck pool"}
    games, new_sides = cm.test_games(ctx, pool), cm.new_player_sides(ctx)
    s_retro = Searcher(ctx)
    retro = cm.check_version(ctx, ctx.matchup, s_retro, pool, cm.opponent_sets(ctx, per_set)["styles"], games, new_sides,
                             top, min_games, N_BOOT, SEED, cm.pool_evaluations(s_retro, pool))
    fctx = cm.window_scorer(ctx, ctx.split.valid)
    s_fwd = Searcher(fctx)
    fwd = cm.check_version(fctx, ctx.matchup, s_fwd, pool, cm.style_sets(ctx, ctx.split.valid, per_set), games, new_sides,
                           top, min_games, N_BOOT, SEED, cm.pool_evaluations(s_fwd, pool))
    # the retrospective version must reproduce the exported check's counts exactly
    bt = (exported.get("matchup") or {}).get("backtest")
    match = None
    if bt:
        mine = retro["populations"]["all_players"]
        match = all(mine["games"][g] == bt["pooled"][g]["games"] and mine["wins"][g] == bt["pooled"][g]["wins"] for g in cm.GROUPS)
    return {"test_window": list(ctx.split.window("test")), "valid_window": list(ctx.split.window("valid")),
            "pool_decks": len(pool), "games": len(games), "matches_export": match,
            "retrospective": slim(retro), "forward": slim(fwd),
            "forward_same_counter_decks": sum(len(set(retro["counter"].get(st, [])) & set(v)) for st, v in fwd["counter"].items()),
            "forward_same_field_decks": len(set(retro["field"]) & set(fwd["field"]))}


def main(slugs: list[str]) -> None:
    paths = Paths.for_source("real")
    fp = _fingerprint(paths)
    index = json.loads((WEB / "modes.json").read_text(encoding="utf-8"))
    modes = [m for m in index["modes"] if m["status"] == "exported" and (not slugs or m["slug"] in slugs)]
    out = {"written_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "design": "docs/claude-redesign/EVAL-DESIGN.md",
           "settings": {"replicates": N_BOOT, "seed": SEED, "few": cm.FEW, "interval": 0.9}, "modes": {}}
    target = WEB / "counter_eval.json"
    if slugs and target.exists():
        out["modes"] = json.loads(target.read_text(encoding="utf-8")).get("modes", {})
    for m in modes:
        t0 = time.time()
        ctx, why = cached_context(paths, m["slug"], fp)
        if ctx is None:
            out["modes"][m["slug"]] = {"skipped": why}
        elif ctx.matchup is None:
            out["modes"][m["slug"]] = {"skipped": "no matchup model"}
        else:
            exported = json.loads((WEB / m["file"]).read_text(encoding="utf-8")) if (WEB / m["file"]).exists() else {}
            out["modes"][m["slug"]] = r5(run_mode(ctx, exported))
        res = out["modes"][m["slug"]]
        print(m["slug"], f"{time.time() - t0:.0f}s", res.get("skipped") or
              f"retro {res['retrospective']['verdict']} / forward {res['forward']['verdict']} (matches export: {res['matches_export']})", flush=True)
    target.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("wrote", target)


if __name__ == "__main__":
    main(sys.argv[1:])
