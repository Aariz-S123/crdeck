"""Export the trained models for the website, plus golden test vectors.

    python scripts/export_web.py            # real data (default)
    python scripts/export_web.py synthetic  # synthetic data

Refresh order: collect -> build -> evaluate -> export -> check -> sweep.
This export re-runs the evaluation for any mode whose saved evaluation does not match the
current data, labels, configs and code (data fingerprint), so the site never shows a stale
report card.

Writes:
  web/modes.json            every mode (Ranked, Trophy Road, All, then every league and arena) with
                            status (exported / not enough data), meta history and forecast,
                            and the run log for the Model log page
  web/models/<slug>.json    everything web/engine.js needs for one mode
  web/golden/<slug>.json    Python's own answers for that mode, which
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

from crdeck import runlog  # noqa: E402
from crdeck.config import Paths, collection_config, model_config  # noqa: E402
from crdeck.evaluate import full_report  # noqa: E402
from crdeck.explain import build_explanation  # noqa: E402
from crdeck.forecast import meta_report  # noqa: E402
from crdeck.seasons import season_report  # noqa: E402
from crdeck.landscape import report as landscape_report  # noqa: E402
from crdeck.parse import mode_groups, mode_label, mode_slug  # noqa: E402
from crdeck.pipeline import MIN_BATTLES, NoDataError, _fingerprint, load_context, save_model_outputs  # noqa: E402
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
    model["form_stats"] = form_stats(ctx)
    model["csv_rows"] = csv_rows(ctx, model["form_stats"])
    model["evaluation"] = fresh_evaluation(ctx)
    model["meta"].update({"mode": ctx.mode, "group": ctx.group, "mode_label": ctx.mode_label, "slug": ctx.slug})
    model["forms"] = forms_list(ctx, model["form_stats"])
    model["availability"] = availability_dict(ctx)
    model["embedding"] = embedding_dict(ctx)
    return model


def embedding_dict(ctx) -> dict | None:
    """Card vectors for the card map and embedding swaps (crdeck.embedding); None if not trained."""
    e = ctx.embedding
    if e is None:
        return None
    from crdeck.embedding import NEAR, TOP_SWAPS
    return {"dim": e.dim, "keys": e.keys, "vectors": [[round(float(x), 7) for x in row] for row in e.vectors],
            "pca3": [[round(float(x), 4) for x in row] for row in e.pca3], "pca_explained": e.pca_explained,
            "style": e.style, "choice": e.choice, "evaluation": e.evaluation, "near": NEAR, "top": TOP_SWAPS}


def availability_dict(ctx) -> dict | None:
    """What a player in this Trophy Road arena can use (crdeck.availability); None = no restriction."""
    av = getattr(ctx, "availability", None)
    if av is None:
        return None
    from crdeck.availability import MIN_SEEN_DECKS, load_unlocks
    u = load_unlocks()
    return {"arena": av.arena, "number": av.number, "slots": sorted(av.slots), "slot_unlock": av.slot_unlock,
            "unlock": {str(k): v for k, v in av.unlock.items()}, "unlock_name": {str(k): v for k, v in av.unlock_name.items()},
            "seen_early": {str(k): v for k, v in av.seen_early.items()}, "min_seen_decks": MIN_SEEN_DECKS,
            "source": u.get("source"), "fetched_at": u.get("fetched_at")}


def fresh_evaluation(ctx) -> dict:
    """The saved evaluation for this mode if it matches the current data fingerprint and test
    window; otherwise run the evaluation now (Step 0: never export a stale report card)."""
    f = ctx.paths.processed / f"evaluation_{ctx.slug}.json"
    want_fp, want_win = _fingerprint(ctx.paths), list(ctx.split.window("test"))
    if f.exists():
        ev = json.loads(f.read_text(encoding="utf-8")).get("evaluation") or {}
        if ev.get("data_fingerprint") == want_fp and ev.get("test_window") == want_win:
            print(f"  evaluation for {ctx.slug}: up to date")
            return ev
        print(f"  evaluation for {ctx.slug}: STALE (saved for {ev.get('test_window')}, data now {want_win}); re-running")
    else:
        print(f"  evaluation for {ctx.slug}: missing; running")
    rep = full_report(ctx)
    save_model_outputs(ctx, rep)
    return runlog._jsonable(rep)


def forms_list(ctx, fstats) -> list[dict]:
    """Every playable card form (base, Evolution, Hero) as its own entry, from the API bitmask,
    with this mode's battle counts. Forms with no battles in this mode are kept (games 0)."""
    out = []
    for cid in ctx.cards.ids:
        c = ctx.cards[cid]
        for f in c.allowed_forms():
            k = f"{cid}:{f}"
            g, w = fstats["by_key"].get(k, [0, 0])
            out.append({"key": k, "card_id": cid, "form": f, "games": g, "wins": w})
    return out


def form_stats(ctx) -> dict:
    """Per card form, from train + validation battles: deck appearances, wins, share of appearances."""
    from crdeck.dataset import side_rows
    sides = side_rows(ctx.split.train_valid)
    n_total = len(sides)
    games, wins = {}, {}
    for k, won in zip(sides["deck_key"], sides["won"]):
        for e in k.split("|"):
            games[e] = games.get(e, 0) + 1
            wins[e] = wins.get(e, 0) + int(won)
    return {"appearances": n_total, "by_key": {k: [games[k], wins[k]] for k in sorted(games)}}


def csv_rows(ctx, fstats) -> list[dict]:
    """Every row of the user's source CSV (data/labels/source/cards_meta.csv) with what the
    project knows about it, so the website can show all of them, including the ones that
    are not deck cards. Status codes: in_search, seed_only, not_in_game, tower_troop, duplicate."""
    import csv
    from crdeck.cards import normalize_name
    src = ROOT / "data" / "labels" / "source" / "cards_meta.csv"
    by_name = {normalize_name(ctx.cards[c].name): ctx.cards[c] for c in ctx.cards.ids}
    support = set()
    for f in ctx.paths.raw.glob("*/cards/cards.json"):
        body = json.loads(f.read_text(encoding="utf-8")).get("body", {})
        support |= {normalize_name(s["name"]) for s in body.get("supportItems", [])}
    min_games = int(ctx.cfg["search"]["min_card_games"])
    out, seen = [], set()
    for i, r in enumerate(csv.DictReader(src.open(encoding="utf-8"))):
        name = r["card_name"].strip()
        if name.endswith(" Evolution"):
            base, form = name[: -len(" Evolution")], "evo"
        elif name.startswith("Hero "):
            base, form = name[len("Hero "):], "hero"
        else:
            base, form = name, "base"
        c = by_name.get(normalize_name(base))
        row = {"row": i + 2, "name": name, "base": base, "form": form, "card_id": c.card_id if c else None,
               "csv": {k: r[k] for k in ("elixir", "type", "rating", "usage", "win_rate", "cwr")}}
        key = f"{c.card_id}:{form}" if c else None
        g = fstats["by_key"].get(key, [0, 0]) if key else [0, 0]
        row["games"], row["wins"] = g
        if name in seen:
            row["status"], row["note"] = "duplicate", "Second row with this name in your CSV; it has different numbers. The first row is used."
        elif c is None and normalize_name(base) in support:
            row["status"], row["note"] = "tower_troop", "A tower troop chosen for the king tower, not one of the 8 deck cards."
        elif c is None:
            row["status"], row["note"] = "not_in_game", "No card with this name in the official card list."
        elif form not in c.allowed_forms():
            row["status"], row["note"] = "not_in_game", f"The official card list has no {'Hero' if form == 'hero' else 'Evolution'} form of {c.name}."
        elif ctx.strength.known(DeckCard(c.card_id, form)) and ctx.strength.games(DeckCard(c.card_id, form)) >= min_games:
            row["status"], row["note"] = "in_search", ""
        else:
            row["status"], row["note"] = "seed_only", (f"Only {g[0]} training appearances (search needs {min_games}); "
                                                      "you can still pick it as one of your cards.")
        seen.add(name)
        out.append(row)
    return out


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
            if ctx.embedding is not None:
                from crdeck.embedding import embedding_swaps
                rec["embedding_swaps"] = [{"new_deck_key": w["new_deck_key"], "distance": w["distance"],
                                           "delta_win_prob": w["delta_win_prob"]} for w in embedding_swaps(ctx, s, top.entries, entries)]
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


def candidate_modes(paths: Paths, ccfg: dict) -> list[tuple[str, str | None, dict]]:
    """Ranked, Trophy Road, All, then every league of Ranked and every arena of Trophy Road in game
    order (config), followed by any group seen in the data but missing from the config."""
    counts = json.loads((paths.interim / "counts.json").read_text(encoding="utf-8"))
    by_group = counts.get("ok_by_mode_group") or {}
    out = [("ranked", None, {}), ("trophy_road", None, {}), ("all", None, {})]
    for mode in ("ranked", "trophy_road"):
        word = ((ccfg["battles"]["modes"].get(mode) or {}).get("group_word") or "Group")
        known = mode_groups(ccfg, mode)
        names = {g["name"] for g in known}
        extra = sorted(k.split("|", 1)[1] for k in by_group if k.startswith(mode + "|") and k.split("|", 1)[1] not in names)
        for g in known + [{"name": n, "order": len(known) + i + 1, "not_in_config": True} for i, n in enumerate(extra)]:
            out.append((mode, g["name"], {"group_word": word, **{k: v for k, v in g.items() if k != "name"}}))
    return out


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), separators=(",", ":"), allow_nan=False), encoding="utf-8")


def main() -> None:
    from datetime import datetime, timezone
    source = sys.argv[1] if len(sys.argv) > 1 else "real"
    paths = Paths.for_source(source)
    ccfg, mcfg = collection_config(), model_config()
    counts = json.loads((paths.interim / "counts.json").read_text(encoding="utf-8"))
    modes, ranked_ctx = [], None
    by_group = counts.get("ok_by_mode_group") or {}
    for mode, group, gmeta in candidate_modes(paths, ccfg):
        slug, label = mode_slug(mode, group), mode_label(ccfg, mode, group)
        n_ok = (by_group.get(f"{mode}|{group}", 0) if group else
                sum(v.get("OK", 0) for k, v in counts["modes"].items() if k in (["ranked", "trophy_road"] if mode == "all" else [mode])))
        entry = {"slug": slug, "mode": mode, "group": group, "label": label, "ok_battles": n_ok, **gmeta}
        print(f"{label}: {n_ok} usable battles")
        if n_ok < MIN_BATTLES:
            # too few battles to train on: listed with its real count, never filled in
            reason = f"not enough data for {label}: only {n_ok} usable battles (minimum {MIN_BATTLES})"
            modes.append({**entry, "status": "not_enough_data", "reason": reason})
            continue
        try:
            ctx = load_context(source, mode=mode, group=group)
        except NoDataError as e:
            modes.append({**entry, "status": "not_enough_data", "reason": str(e)})
            print("  not enough data:", e)
            continue
        model = export_model(ctx)
        dump(OUT / "models" / f"{slug}.json", model)
        dump(OUT / "golden" / f"{slug}.json", golden(ctx))
        modes.append({**entry, "status": "exported", "file": f"models/{slug}.json",
                      "test_window": list(ctx.split.window("test")), "train_window": list(ctx.split.window("train"))})
        print(f"  wrote models/{slug}.json ({(OUT / 'models' / f'{slug}.json').stat().st_size / 1e6:.2f} MB)")
        if mode == "ranked" and group is None:
            ranked_ctx = ctx
    labels = json.loads(json.dumps(sorted(set(ranked_ctx.cards.df["label_version"])))) if ranked_ctx is not None else []
    runlog.write_section(paths, "export", {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code": runlog.git_version(), "label_versions": labels,
        "config": {"collection": ccfg, "model": mcfg},
        "modes": [{k: m.get(k) for k in ("slug", "label", "status", "ok_battles", "reason")} for m in modes]})
    index = {
        "default": "ranked", "modes": modes,
        "meta": meta_report(paths, ranked_ctx, mcfg) if ranked_ctx is not None else None,
        "seasons": season_report(paths, ranked_ctx, mcfg),
        "landscape": landscape_report(ranked_ctx) if ranked_ctx is not None else None,
        "log": runlog.read(paths),
        "caveats": runlog.model_notes_caveats(),
    }
    dump(OUT / "modes.json", index)
    print("wrote", OUT / "modes.json", f"{(OUT / 'modes.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
