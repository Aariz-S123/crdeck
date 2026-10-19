"""Export the trained model for the website, plus golden test vectors.

    python scripts/export_web.py            # real data (default)
    python scripts/export_web.py synthetic  # synthetic data

Writes:
  web/model.json   everything web/engine.js needs to score, search and explain decks
  web/golden.json  Python's own answers for a set of seeds and random decks, which
                   scripts/check_web_engine.mjs compares against the JS port

Python stays the source of truth: the website is a port, and the golden check is
what keeps its legality decisions and scores identical to crdeck.rules / search.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.explain import build_explanation  # noqa: E402
from crdeck.pipeline import load_context  # noqa: E402
from crdeck.rules import DeckCard, check_deck, check_partial, deck_key  # noqa: E402
from crdeck.search import Searcher, SeedError, parse_seed  # noqa: E402

OUT = ROOT / "web"


def r6(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return float(f"{float(x):.10g}")


def clean(x):
    """Replace NaN/inf with None recursively, so the output is valid JSON."""
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def export_model(ctx) -> dict:
    cards = ctx.cards
    st = ctx.strength
    syn = ctx.synergy
    am = ctx.archetype
    card_list = []
    for cid in cards.ids:
        c = cards[cid]
        card_list.append({
            "id": cid, "name": c.name, "elixir": c.elixir, "elixir_variable": c.elixir_variable,
            "rarity": c.rarity, "type": c.card_type, "evo": c.has_evolution, "hero": c.has_hero,
            "champion": c.is_champion, "wincon": c.is_win_condition, "roles": list(c.roles), "targets": c.targets,
        })
    keys = [None] * len(st.index)
    for k, i in st.index.items():
        keys[i] = k
    form_keys = {f"{cid}:{f}" for cid in cards.ids for f in cards[cid].allowed_forms()}
    pairs_ok = syn.pairs
    syn_pairs = [[int(r.card_i), int(r.card_j), int(r.games), r6(r.lift), r6(r.shrunk_wr), r6(r.synergy), r6(r.lo),
                  r6(r.hi), r.status == "OK"] for r in pairs_ok.itertuples()]
    opp_rows = [list(map(int, ctx.scorer.opp_X[i].indices)) for i in range(ctx.scorer.opp_X.shape[0])]
    model = {
        "meta": {
            "source": ctx.paths.source,
            "banner": ctx.paths.banner(),
            "train_window": ctx.split.window("train"),
            "test_window": ctx.split.window("test"),
            "test_battles_total": len(ctx.split.test),
            "strength_model": st.name,
            "skill_control": bool(st.skill_control),
            "counts": {k: ctx.counts.get(k) for k in ("battles_after_dedupe", "distinct_decks", "first_battle", "last_battle")},
            "ok_battles": int(ctx.counts["status"].get("OK", 0)),
        },
        "cards": card_list,
        "rules": {"deck_size": ctx.rules.deck_size, "max_champions": ctx.rules.max_champions,
                  "special_slots": [{"name": s.name, "accepts": list(s.accepts)} for s in ctx.rules.special_slots]},
        "hero_observable": bool(ctx.hero_observable),
        "strength": {
            "keys": keys,
            "coef": [r6(x) for x in st.coef],
            "n_card_features": st.n_card_features,
            "pairs": [list(p) for p in st.pairs],
            "feature_games": {k: int(st.feature_games.get(k, 0)) for k in sorted(form_keys)},
            "min_feature_games": st.min_feature_games,
            "cov": [[r6(x) for x in row] for row in st.cov],
        },
        "scorer": {"opp_u": [r6(x) for x in ctx.scorer.opp_u], "opp_rows": opp_rows, "interval": ctx.scorer.interval},
        "synergy": {
            "card_ids": [int(c) for c in syn.cards["card_id"]],
            "min_games": syn.min_games,
            "expected_from": syn.expected_from,
            "matrix": [[r6(x) for x in row] for row in syn.syn_matrix],
            "log_lift": [[r6(x) for x in row] for row in syn.log_lift],
            "pairs": syn_pairs,
        },
        "archetype": {
            "fitted": bool(am.fitted),
            "threshold": am.threshold,
            "card_ids": list(am.card_index.keys()),
            "roles": sorted({r for c in card_list for r in c["roles"]} | set(__import__("crdeck.cards", fromlist=["ROLES"]).ROLES)),
            "classes": list(am.classes) if am.fitted else [],
            "coef": [[r6(x) for x in row] for row in am.lr.coef_] if am.fitted else [],
            "intercept": [r6(x) for x in am.lr.intercept_] if am.fitted else [],
        },
        "config": {"search": ctx.cfg["search"], "warnings": ctx.cfg["warnings"]},
        "deck_appearances": {k: int(v) for k, v in ctx.deck_appearances.items()},
        "test_deck_records": {k: list(v) for k, v in ctx.test_deck_records.items()},
    }
    from crdeck.archetype import ROLE_LIST
    model["archetype"]["roles"] = ROLE_LIST
    ev = ctx.paths.processed / "evaluation.json"
    if ev.exists():
        model["evaluation"] = json.loads(ev.read_text(encoding="utf-8")).get("evaluation")
    return model


def golden(ctx) -> dict:
    s = Searcher(ctx)
    cards = ctx.cards
    seed_sets = [["Hog Rider"], ["Golem", "Night Witch"], ["X-Bow"], [], ["Knight@evo", "Musketeer@hero", "Fireball"],
                 ["Archer Queen", "Golden Knight"], ["Archers@evo", "Bats@evo", "Zap@evo"], ["Hog Rider@evo"]]
    out = {"searches": [], "legality": [], "explanations": []}
    for seeds in seed_sets:
        entries = [parse_seed(x, cards) for x in seeds]
        rec = {"seeds": [e.key for e in entries]}
        try:
            res = s.complete(entries)
            rec["decks"] = [{"key": d.key, "objective": d.objective, "win_prob": d.win_prob,
                             "mean_synergy": d.mean_synergy, "mean_log_lift": d.mean_log_lift} for d in res]
            top = res[0]
            x = build_explanation(top.entries, ctx)
            out["explanations"].append({
                "key": top.key, "win_prob": x.score["meta_win_prob"], "interval": x.score["interval"],
                "archetype": x.archetype["label"], "probability": x.archetype["probability"],
                "warnings": [w["code"] for g in x.warnings for w in g["warnings"]],
                "data_quality": [d["state"] for d in x.data_quality],
                "synergy_top": [p["pair"] for p in x.synergy_top], "synergy_bottom": [p["pair"] for p in x.synergy_bottom],
            })
            sw = s.swaps(top.entries, locked=entries)
            rec["swaps"] = [{"replace": w["replace"], "with": w["with"], "new_deck_key": w["new_deck_key"],
                             "delta_objective": w["delta_objective"]} for w in sw]
        except SeedError as e:
            rec["error"] = str(e)
        out["searches"].append(rec)
    rng = np.random.default_rng(0)
    pool = [DeckCard(cid, f) for cid in cards.ids for f in cards[cid].allowed_forms()]
    for _ in range(3000):
        n = int(rng.choice([6, 7, 8, 8, 8, 9]))
        deck = [pool[i] for i in rng.choice(len(pool), n, replace=False)]
        r = check_deck(deck, cards, ctx.rules)
        rp = check_partial(deck[: max(1, n - 3)], cards, ctx.rules)
        out["legality"].append({"deck": [e.key for e in deck], "legal": r.legal, "reasons": r.reasons,
                                "slots": r.slots, "partial_legal": rp.legal})
    return out


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "real"
    ctx = load_context(source)
    OUT.mkdir(exist_ok=True)
    model = export_model(ctx)
    (OUT / "model.json").write_text(json.dumps(clean(model), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    (OUT / "golden.json").write_text(json.dumps(clean(golden(ctx)), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print("wrote", OUT / "model.json", f"{(OUT / 'model.json').stat().st_size / 1e6:.2f} MB")
    print("wrote", OUT / "golden.json")


if __name__ == "__main__":
    main()
