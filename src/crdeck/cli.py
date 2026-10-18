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
    c.add_argument("--window", default=None, help='window id for the raw cache; "auto" = today (UTC)')
    s = sub.add_parser("synthetic")
    s.add_argument("--battles", type=int, default=20_000)
    s.add_argument("--players", type=int, default=300)
    for name in ("build", "evaluate", "suggest", "label"):
        p = sub.add_parser(name)
        p.add_argument("--source", choices=["real", "synthetic"], default=None)
        if name == "suggest":
            p.add_argument("seeds", nargs="*")
        if name == "label":
            p.add_argument("--interactive", action="store_true", help="label decks one by one in the terminal")
    args = ap.parse_args(argv)

    if args.cmd == "gate":
        from .collect import gate, write_observed_notes
        obs = gate()
        print(json.dumps(obs, indent=2, default=str))
        print(f"\nwrote {write_observed_notes(obs)}; copy findings into docs/api-notes.md")
    elif args.cmd == "collect":
        from .collect import collect
        print(json.dumps(collect(args.players, window_id=args.window), indent=2))
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
        from .pipeline import save_model_outputs
        ctx = load_context(args.source, verbose=True)
        rep = full_report(ctx)
        for f in save_model_outputs(ctx, rep):
            print("wrote", f)
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
        from .archetype import load_labels, suggest_decks_to_label
        from .cards import load_card_table
        from .config import Paths, model_config
        from .pipeline import load_interim
        paths = Paths.for_source(args.source)
        cfg = model_config()
        cards = load_card_table(paths.processed / "cards.parquet")
        _, _, decks, _ = load_interim(paths)
        labels = load_labels(paths.archetype_labels)
        ac = cfg["archetype"]
        out = suggest_decks_to_label(decks, cards, ac["n_clusters"], ac["per_cluster"], cfg["seed"], set(labels["deck_key"]))
        path = paths.processed / "archetype_worklist.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False)
        print(paths.banner())
        print(f"wrote {len(out)} decks to {path}")
        if args.interactive:
            from .labeling import run
            print(run(out, cards, paths.archetype_labels, heldout_target=ac["heldout_target"]))
        else:
            print(f"label them with `python -m crdeck label --interactive`, or copy rows into {paths.archetype_labels}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
