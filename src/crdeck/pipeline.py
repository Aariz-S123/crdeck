"""One-command rebuild (spec 9.2) and the trained-model context used by notebooks.

build(source):        raw (+ data/labels) -> processed/cards.parquet, interim/*.parquet, interim/counts.json
load_context(source): time split, synergy, strength (with model selection on the
                      validation window), meta scorer, archetype model -> Context
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import archetype as arch
from .cards import CardTable, attach_api, load_card_table, load_labels, save_card_table
from .config import CARD_LABELS, Paths, collection_config, model_config
from .dataset import Split, model_battles, side_rows, time_split
from .parse import FormConfig, parse_files, parse_time
from .rules import DeckRules
from .strength import CardModel, ConstantBaseline, MetaScorer, PopularityBaseline, evaluate, top_pairs
from .synergy import SynergyTable, compute_synergy


class NoDataError(RuntimeError):
    """Required collected data is missing. Raised instead of substituting anything."""


def _latest_cards_file(paths: Paths) -> Path:
    files = sorted(paths.raw.glob("*/cards/cards.json"))
    if not files:
        raise NoDataError(
            f"No /cards response under {paths.raw}. "
            + ("Run `python -m crdeck synthetic` first." if paths.is_synthetic
               else "Run the API gate first: `python -m crdeck gate` (needs CR_API_KEY in .env).")
        )
    def fetched(p: Path) -> str:
        with p.open(encoding="utf-8") as f:
            return json.load(f).get("fetched_at", "")
    return max(files, key=fetched)


def build(source: str | None = None, verbose: bool = True, paths: Paths | None = None) -> dict[str, Any]:
    paths = paths or Paths.for_source(source)
    ccfg = collection_config()
    rules = DeckRules.load()

    labels = load_labels(CARD_LABELS)
    cards_file = _latest_cards_file(paths)
    with cards_file.open(encoding="utf-8") as f:
        cards_body = json.load(f)["body"]
    table, report = attach_api(labels, cards_body)
    save_card_table(table, paths.processed / "cards.parquet")
    cards = load_card_table(paths.processed / "cards.parquet")

    logs = sorted(paths.raw.glob("*/battlelog/*.json"))
    if not logs:
        raise NoDataError(f"No battle logs under {paths.raw}. Run `python -m crdeck collect`.")
    win = ccfg.get("window", {})
    window = (parse_time_iso(win.get("start")), parse_time_iso(win.get("end")))
    parsed = parse_files(logs, cards, FormConfig.from_collection(ccfg), ccfg["battles"]["battle_types"],
                         rules.deck_size, window)
    ranks = leaderboard_ranks(paths)
    if ranks:
        dib = parsed.decks_in_battle
        missing = dib["trophies_or_rank"].isna()
        dib.loc[missing, "trophies_or_rank"] = dib.loc[missing, "player_tag"].map(ranks)
        dib["rank_source"] = None
        dib.loc[~missing, "rank_source"] = "battle"
        dib.loc[missing & dib["trophies_or_rank"].notna(), "rank_source"] = "leaderboard"
    paths.interim.mkdir(parents=True, exist_ok=True)
    parsed.battles.to_parquet(paths.interim / "battles.parquet", index=False)
    parsed.decks_in_battle.to_parquet(paths.interim / "decks_in_battle.parquet", index=False)
    parsed.decks.to_parquet(paths.interim / "decks.parquet", index=False)
    parsed.slot_cards.to_parquet(paths.interim / "slot_cards.parquet", index=False)
    counts = {
        "source": paths.source,
        "cards_file": str(cards_file.relative_to(paths.root)),
        "card_table_rows": len(table),
        "card_attach_report": report.lines(),
        **parsed.counts,
    }
    with (paths.interim / "counts.json").open("w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2, default=str)
    if verbose:
        print(paths.banner())
        print(json.dumps({k: v for k, v in counts.items() if k != "card_attach_report"}, indent=2, default=str))
    return counts


def leaderboard_ranks(paths: Paths) -> dict[str, float]:
    """tag -> best (lowest) leaderboard rank seen in any cached leaderboard file."""
    ranks: dict[str, float] = {}
    for f in paths.raw.glob("*/leaderboard/*.json"):
        with f.open(encoding="utf-8") as fh:
            body = json.load(fh).get("body")
        items = body.get("items", []) if isinstance(body, dict) else []
        for it in items:
            r = it.get("rank")
            if it.get("tag") and r is not None:
                ranks[it["tag"]] = min(float(r), ranks.get(it["tag"], float("inf")))
    return ranks


def save_model_outputs(ctx: "Context", report: dict | None = None) -> list[Path]:
    """Model outputs to data/processed (spec 4: 'feature tables, model outputs')."""
    out = ctx.paths.processed
    out.mkdir(parents=True, exist_ok=True)
    name = ctx.cards.name
    pairs = ctx.synergy.pairs.copy()
    pairs.insert(2, "name_i", pairs["card_i"].map(name))
    pairs.insert(3, "name_j", pairs["card_j"].map(name))
    pairs.to_csv(out / "synergy_pairs.csv", index=False)
    cards = ctx.synergy.cards.copy()
    cards.insert(1, "name", cards["card_id"].map(name))
    cards.to_csv(out / "card_stats.csv", index=False)
    w = pd.DataFrame([{"feature": k, "card_id": int(k.split(":")[0]), "form": k.split(":")[1],
                       "name": name(int(k.split(":")[0])), "weight": v,
                       "train_games": ctx.strength.feature_games.get(k, 0)} for k, v in ctx.strength.card_weights.items()])
    w.sort_values("weight", ascending=False).to_csv(out / "card_weights.csv", index=False)
    ctx.model_comparison.to_csv(out / "model_comparison.csv", index=False)
    meta = {"source": ctx.paths.source, "banner": ctx.paths.banner(), "split": ctx.split.describe().to_dict("records"),
            "strength_model": ctx.strength.name, "C": ctx.strength.C, "synergy_expected_from": ctx.synergy.expected_from}
    if report is not None:
        meta["evaluation"] = {k: (v.to_dict("records") if isinstance(v, pd.DataFrame) else v) for k, v in report.items()}
    with (out / "evaluation.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    return [out / n for n in ("synergy_pairs.csv", "card_stats.csv", "card_weights.csv", "model_comparison.csv", "evaluation.json")]


def parse_time_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    t = parse_time(s)
    if t is None:
        raise ValueError(f"bad window time {s!r}; use e.g. 2026-10-01T00:00:00Z")
    return t


@dataclass
class Context:
    paths: Paths
    cfg: dict
    rules: DeckRules
    cards: CardTable
    split: Split
    synergy: SynergyTable
    strength: CardModel
    scorer: MetaScorer
    archetype: arch.ArchetypeModel
    hero_observable: bool
    model_comparison: pd.DataFrame
    decks: pd.DataFrame
    counts: dict
    test_deck_records: dict[str, tuple[int, int]] = field(default_factory=dict)
    deck_appearances: dict[str, int] = field(default_factory=dict)
    archetype_labels: pd.DataFrame | None = None


def load_interim(paths: Paths) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    f = paths.interim / "battles.parquet"
    if not f.exists():
        raise NoDataError(f"{f} not found. Run `python -m crdeck build" + (" --source synthetic`." if paths.is_synthetic else "`."))
    battles = pd.read_parquet(f)
    dib = pd.read_parquet(paths.interim / "decks_in_battle.parquet")
    decks = pd.read_parquet(paths.interim / "decks.parquet")
    with (paths.interim / "counts.json").open(encoding="utf-8") as fh:
        counts = json.load(fh)
    return battles, dib, decks, counts


def train_strength(split: Split, syn_train: SynergyTable, cfg: dict, hero_observable: bool) -> tuple[CardModel, pd.DataFrame, SynergyTable]:
    """Fit baselines and both card models on train, select on valid, refit the winner on train+valid.

    Returns (final model, comparison table, synergy table on train+valid).
    The comparison's test columns use models refit on train+valid.
    """
    s = cfg["strength"]
    sy = cfg["synergy"]
    pair_list = top_pairs(syn_train, s["top_n_pairs"])
    best: dict[str, tuple[float, float, CardModel]] = {}
    for C in s["C_grid"]:
        for name, pl in (("card_lr", []), ("card_lr+pairs", pair_list)):
            m = CardModel(hero_observable, C, s["max_iter"], s["min_feature_games"], pairs=pl, name=name).fit(split.train)
            ll_ = evaluate(m, split.valid)["log_loss"]
            if name not in best or ll_ < best[name][0]:
                best[name] = (ll_, C, m)
    pop = PopularityBaseline().fit(split.train)
    const = ConstantBaseline()
    rows = [{**evaluate(m, split.valid), "part": "valid", "C": None} for m in (const, pop)]
    rows += [{**evaluate(best[n][2], split.valid), "part": "valid", "C": best[n][1]} for n in ("card_lr", "card_lr+pairs")]
    valid = pd.DataFrame(rows)
    chosen = "card_lr+pairs" if best["card_lr+pairs"][0] < best["card_lr"][0] else "card_lr"
    C_base, C_pairs = best["card_lr"][1], best["card_lr+pairs"][1]

    tv = split.train_valid
    syn_tv = compute_synergy(side_rows(tv), sy["k"], sy["min_games"], sy["interval"], sy["expected_from"])
    final_base = CardModel(hero_observable, C_base, s["max_iter"], s["min_feature_games"], name="card_lr").fit(tv)
    final_pairs = CardModel(hero_observable, C_pairs, s["max_iter"], s["min_feature_games"],
                            pairs=top_pairs(syn_tv, s["top_n_pairs"]), name="card_lr+pairs").fit(tv)
    final_pop = PopularityBaseline().fit(tv)
    test_rows = [{**evaluate(m, split.test), "part": "test", "C": c}
                 for m, c in ((const, None), (final_pop, None), (final_base, C_base), (final_pairs, C_pairs))]
    comp = pd.concat([valid, pd.DataFrame(test_rows)], ignore_index=True)
    comp["selected"] = comp["model"] == chosen
    final = final_pairs if chosen == "card_lr+pairs" else final_base
    return final, comp, syn_tv


def _fingerprint(paths: Paths) -> str:
    """Hash of everything a Context depends on: interim data, card table, labels, configs, code."""
    import hashlib
    from .config import CONFIG_DIR
    h = hashlib.sha256()
    files = sorted(paths.interim.glob("*")) + [paths.processed / "cards.parquet", paths.archetype_labels]
    files += sorted(CONFIG_DIR.glob("*.yaml")) + sorted(Path(__file__).parent.glob("*.py"))
    for f in files:
        h.update(str(f.name).encode())
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()


def load_context(source: str | None = None, verbose: bool = False, paths: Paths | None = None,
                 cache: bool = True) -> Context:
    """Train (or load cached) models. The cache in processed/context_cache.pkl is reused only
    when the fingerprint of data, labels, configs and code is unchanged."""
    import pickle
    paths = paths or Paths.for_source(source)
    cache_file = paths.processed / "context_cache.pkl"
    fp = _fingerprint(paths) if cache else ""
    if cache and cache_file.exists():
        try:
            with cache_file.open("rb") as f:
                saved_fp, ctx = pickle.load(f)
            if saved_fp == fp:
                if verbose:
                    print(paths.banner())
                    print("(models loaded from cache)")
                    print(ctx.split.describe().to_string(index=False))
                return ctx
        except Exception:  # stale or unreadable cache: retrain
            pass
    ctx = _train_context(paths, verbose)
    if cache:
        paths.processed.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as f:
            pickle.dump((fp, ctx), f)
    return ctx


def _train_context(paths: Paths, verbose: bool) -> Context:
    cfg = model_config()
    ccfg = collection_config()
    rules = DeckRules.load()
    cards = load_card_table(paths.processed / "cards.parquet")
    battles, dib, decks, counts = load_interim(paths)
    mb = model_battles(battles, dib)
    if len(mb) < 100:
        raise NoDataError(f"only {len(mb)} usable battles; collect more before modeling")
    split = time_split(mb, ccfg["split"]["train_frac"], ccfg["split"]["valid_frac"])
    hero_obs = FormConfig.from_collection(ccfg).hero_observable

    sy = cfg["synergy"]
    syn_train = compute_synergy(side_rows(split.train), sy["k"], sy["min_games"], sy["interval"], sy["expected_from"])
    strength, comp, syn_tv = train_strength(split, syn_train, cfg, hero_obs)

    ds = cfg["deck_score"]
    opp = pd.concat([split.test["deck_a"], split.test["deck_b"]], ignore_index=True)
    scorer = MetaScorer(strength, opp, ds["n_opponent_decks"], ds["n_bootstrap"], ds["interval"], cfg["seed"])

    test_sides = side_rows(split.test)
    rec = test_sides.groupby("deck_key")["won"].agg(["size", "sum"])
    test_records = {k: (int(r["size"]), int(r["sum"])) for k, r in rec.iterrows()}

    ac = cfg["archetype"]
    am = arch.ArchetypeModel(cards, ac["uncertain_threshold"], ac["C"], cfg["seed"])
    labels = arch.load_labels(paths.archetype_labels)
    if (labels["split"] == "train").sum() > 0 and labels.loc[labels["split"] == "train", "archetype"].nunique() >= 2:
        am.fit(labels)

    all_sides = side_rows(mb)
    appearances = all_sides["deck_key"].value_counts().to_dict()
    ctx = Context(paths, cfg, rules, cards, split, syn_tv, strength, scorer, am, hero_obs, comp, decks, counts,
                  test_records, appearances, labels)
    if verbose:
        print(paths.banner())
        print(split.describe().to_string(index=False))
    return ctx
