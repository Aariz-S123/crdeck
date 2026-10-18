"""Command line: python -m crdeck <command> [--source real|synthetic]

  gate        API gate (spec 6): /cards, leaderboard, one battle log; prints observations
  collect     battle logs for top leaderboard players (resumable; cached files skipped)
  synthetic   generate SYNTHETIC data under data/synthetic (pipeline testing only)
  build       rebuild interim tables from raw + labels
  evaluate    held-out evaluation report
  suggest     complete a deck from seed cards, e.g. suggest "Hog Rider" "Knight@evo"
  label       write an archetype labeling worklist (k-means picks) to processed/
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="crdeck")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate")
    c = sub.add_parser("collect")
    c.add_argument("--players", type=int, default=None)
    s = sub.add_parser("synthetic")
    s.add_argument("--battles", type=int, default=20_000)
    s.add_argument("--players", type=int, default=300)
    for name in ("build", "evaluate", "suggest", "label"):
        p = sub.add_parser(name)
        p.add_argument("--source", choices=["real", "synthetic"], default=None)
        if name == "suggest":
            p.add_argument("seeds", nargs="*")
    args = ap.parse_args(argv)

    if args.cmd == "gate":
        from .collect import gate
        print(json.dumps(gate(), indent=2, default=str))
    elif args.cmd == "collect":
        from .collect import collect
        print(json.dumps(collect(args.players), indent=2))
    elif args.cmd == "synthetic":
        from .synthetic import SynthConfig, generate
        print("Generating SYNTHETIC data (not real battles) under data/synthetic/")
        print(json.dumps(generate(SynthConfig(n_players=args.players, n_battles=args.battles)), indent=2))
    elif args.cmd == "build":
        from .pipeline import build
        build(args.source)
    elif args.cmd == "evaluate":
        from .evaluate import full_report
        from .pipeline import load_context
        ctx = load_context(args.source, verbose=True)
        rep = full_report(ctx)
        with pd.option_context("display.width", 160):
            for k, v in rep.items():
                print(f"\n== {k} ==")
                print(v.to_string(index=False) if isinstance(v, pd.DataFrame) else json.dumps(v, indent=2, default=str))
    elif args.cmd == "suggest":
        from .explain import build_explanation, render_text
        from .pipeline import load_context
        from .search import Searcher, parse_seed
        ctx = load_context(args.source)
        searcher = Searcher(ctx)
        seeds = [parse_seed(x, ctx.cards) for x in args.seeds]
        for i, d in enumerate(searcher.complete(seeds), 1):
            print(f"\n--- Deck {i} ---")
            print(render_text(build_explanation(d.entries, ctx, searcher.objective_dict(d))))
    elif args.cmd == "label":
        from .archetype import suggest_decks_to_label
        from .pipeline import load_context
        ctx = load_context(args.source)
        ac = ctx.cfg["archetype"]
        done = set(ctx.archetype_labels["deck_key"]) if ctx.archetype_labels is not None else set()
        out = suggest_decks_to_label(ctx.decks, ctx.cards, ac["n_clusters"], ac["per_cluster"], ctx.cfg["seed"], done)
        path = ctx.paths.processed / "archetype_worklist.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False)
        print(f"wrote {len(out)} decks to {path}; copy rows into {ctx.paths.archetype_labels} with an archetype and split")
    return 0


if __name__ == "__main__":
    sys.exit(main())
