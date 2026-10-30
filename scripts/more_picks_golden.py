"""Python's answers to searches with 4 to 8 picked cards, for a parity check of the website engine.

The builder takes up to a full deck of picks since 2026-10-29 (the user's change; it was 0 to 3), but the
exported golden files (web/golden/, written by scripts/export_web.py) only hold searches with 0 to 3 picks.
This script asks the Python package the same questions with 4 to 8 picks and writes <out dir>/<slug>.json in
the golden format (searches and explanations) for scripts/check_web_engine.mjs to compare:

    python scripts/more_picks_golden.py <out dir> [slug ...]     (default: every exported mode)
    node scripts/check_web_engine.mjs <out dir>

Picks: the first 4 to 8 card forms, in a card order rotated per deck so that other cards come first, of each
mode's top three decks with no picks and its three most played observed decks. Each mode's models are read
from its model cache, read-only: a stale cache is skipped and listed, never retrained. Nothing exported changes.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from counter_eval import cached_context  # noqa: E402
from crdeck import counters as cm  # noqa: E402
from crdeck.config import Paths  # noqa: E402
from crdeck.embedding import embedding_swaps  # noqa: E402
from crdeck.explain import build_explanation  # noqa: E402
from crdeck.pipeline import _fingerprint  # noqa: E402
from crdeck.rules import parse_deck_key  # noqa: E402
from crdeck.search import Searcher, SeedError  # noqa: E402

WEB = ROOT / "web"


def record(ctx, s: Searcher, entries: list) -> tuple[dict, dict | None]:
    """One search as scripts/export_web.py's golden() writes it, and its top deck's explanation."""
    rec = {"seeds": [e.key for e in entries]}
    try:
        res = s.complete(entries)
    except SeedError as e:
        rec["error"] = str(e)
        return rec, None
    rec["decks"] = [{"key": d.key, "objective": d.objective, "win_prob": d.win_prob,
                     "mean_synergy": d.mean_synergy, "mean_log_lift": d.mean_log_lift} for d in res]
    top = res[0]
    x = build_explanation(top.entries, ctx)
    expl = {"key": top.key, "win_prob": x.score["meta_win_prob"], "interval": x.score["interval"],
            "archetype": x.archetype["label"], "probability": x.archetype["probability"],
            "warnings": [w["code"] for g in x.warnings for w in g["warnings"]],
            "data_quality": [d["state"] for d in x.data_quality],
            "synergy_top": [p["pair"] for p in x.synergy_top], "synergy_bottom": [p["pair"] for p in x.synergy_bottom]}
    rec["swaps"] = [{"replace": w["replace"], "with": w["with"], "new_deck_key": w["new_deck_key"],
                     "delta_objective": w["delta_objective"]} for w in s.swaps(top.entries, locked=entries)]
    if ctx.embedding is not None:
        rec["embedding_swaps"] = [{"new_deck_key": w["new_deck_key"], "distance": w["distance"],
                                   "delta_win_prob": w["delta_win_prob"]} for w in embedding_swaps(ctx, s, top.entries, entries)]
    return rec, expl


def main(out: Path, slugs: list[str]) -> None:
    paths = Paths.for_source("real")
    fp = _fingerprint(paths)
    index = json.loads((WEB / "modes.json").read_text(encoding="utf-8"))
    pool_cfg = cm.counters_config()["pool"]
    out.mkdir(parents=True, exist_ok=True)
    for m in [m for m in index["modes"] if m["status"] == "exported" and (not slugs or m["slug"] in slugs)]:
        t0 = time.time()
        ctx, why = cached_context(paths, m["slug"], fp)
        if ctx is None:
            print(m["slug"], "skipped:", why, flush=True)
            continue
        s, size = Searcher(ctx), ctx.rules.deck_size
        pool = cm.counter_pool(ctx, int(pool_cfg["min_battles"]), int(pool_cfg["max_decks"]))
        decks = [d.entries for d in s.complete([])] + [parse_deck_key(k) for k, _ in pool[:3]]
        golden: dict = {"searches": [], "explanations": []}
        for j, deck in enumerate(decks):
            cards = sorted(deck, key=lambda e: e.key)
            order = cards[j % size:] + cards[: j % size]
            for n in range(4, size + 1):
                rec, expl = record(ctx, s, order[:n])
                golden["searches"].append(rec)
                if expl is not None:
                    golden["explanations"].append(expl)
        (out / f"{m['slug']}.json").write_text(json.dumps(golden), encoding="utf-8")
        refused = sum("error" in r for r in golden["searches"])
        print(m["slug"], f"{time.time() - t0:.0f}s", f"{len(golden['searches'])} searches ({refused} refused) from {len(decks)} decks", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), sys.argv[2:])
