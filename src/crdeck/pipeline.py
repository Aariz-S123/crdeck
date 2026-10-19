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

import numpy as np
import pandas as pd

from . import archetype as arch
from .cards import CardTable, attach_api, load_card_table, load_labels, save_card_table
from .config import CARD_LABELS, Paths, collection_config, model_config
from .dataset import Split, model_battles, side_rows, time_split
from .parse import FormConfig, ModeRules, mode_label, mode_slug, modes_for, parse_files, parse_time
from .rules import DeckRules
from .strength import CardModel, ConstantBaseline, MetaScorer, PopularityBaseline, RatingBaseline, evaluate, top_pairs
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
    parsed = parse_files(logs, cards, FormConfig.from_collection(ccfg), None, rules.deck_size, window,
                         ModeRules.from_collection(ccfg))
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
    write_raw_manifest(paths)
    from . import runlog
    runlog.write_section(paths, "build", runlog.build_section(paths, counts))
    if verbose:
        print(paths.banner())
        print(json.dumps({k: v for k, v in counts.items() if k != "card_attach_report"}, indent=2, default=str))
    return counts


def write_raw_manifest(paths: Paths) -> Path:
    """data/raw stays out of git (spec 9.7), so record what was fetched and when in a
    small tracked CSV: one row per raw file (window, kind, file, HTTP status, fetched_at)."""
    rows = []
    for f in sorted(paths.raw.glob("*/*/*.json")):
        with f.open(encoding="utf-8") as fh:
            w = json.load(fh)
        rows.append({"window_id": f.parts[-3], "kind": f.parts[-2], "file": f.name,
                     "status": w.get("status"), "fetched_at": w.get("fetched_at")})
    out = paths.root / "raw_manifest.csv"
    pd.DataFrame(rows, columns=["window_id", "kind", "file", "status", "fetched_at"]).to_csv(out, index=False)
    return out


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
    """Model outputs to data/processed (spec 4: 'feature tables, model outputs'), one set per
    mode (file suffix = mode slug), plus the evaluate:<slug> section of the run log."""
    from . import runlog
    out = ctx.paths.processed
    out.mkdir(parents=True, exist_ok=True)
    sfx = ctx.slug
    name = ctx.cards.name
    pairs = ctx.synergy.pairs.copy()
    pairs.insert(2, "name_i", pairs["card_i"].map(name))
    pairs.insert(3, "name_j", pairs["card_j"].map(name))
    pairs.to_csv(out / f"synergy_pairs_{sfx}.csv", index=False)
    cards = ctx.synergy.cards.copy()
    cards.insert(1, "name", cards["card_id"].map(name))
    cards.to_csv(out / f"card_stats_{sfx}.csv", index=False)
    w = pd.DataFrame([{"feature": k, "card_id": int(k.split(":")[0]), "form": k.split(":")[1],
                       "name": name(int(k.split(":")[0])), "weight": v,
                       "train_games": ctx.strength.feature_games.get(k, 0)} for k, v in ctx.strength.card_weights.items()])
    w.sort_values("weight", ascending=False).to_csv(out / f"card_weights_{sfx}.csv", index=False)
    ctx.model_comparison.to_csv(out / f"model_comparison_{sfx}.csv", index=False)
    meta = {"source": ctx.paths.source, "banner": ctx.paths.banner(), "mode": ctx.mode, "arena": ctx.arena,
            "mode_label": ctx.mode_label, "split": ctx.split.describe().to_dict("records"),
            "strength_model": ctx.strength.name, "C": ctx.strength.C, "synergy_expected_from": ctx.synergy.expected_from}
    if report is not None:
        meta["evaluation"] = runlog._jsonable(report)
        runlog.write_section(ctx.paths, f"evaluate:{sfx}", meta["evaluation"])
    with (out / f"evaluation_{sfx}.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    return [out / f"{n}_{sfx}.{e}" for n, e in (("synergy_pairs", "csv"), ("card_stats", "csv"), ("card_weights", "csv"),
                                                ("model_comparison", "csv"), ("evaluation", "json"))]


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
    synergy_choice: pd.DataFrame | None = None
    mode: str = "ranked"
    arena: str | None = None
    mode_label: str = "Ranked (Path of Legends)"
    candidates: pd.DataFrame | None = None  # every strength model and C tried, with validation scores

    @property
    def slug(self) -> str:
        return mode_slug(self.mode, self.arena)
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


def choose_synergy(split: Split, sy: dict) -> tuple[SynergyTable, pd.DataFrame]:
    """Synergy table on train. expected_from "auto" picks the variant whose deck mean
    synergy better separates winners on the VALIDATION window (AUC); test is never used."""
    from sklearn.metrics import roc_auc_score
    variants = ["without_partner", "marginal"] if sy["expected_from"] == "auto" else [sy["expected_from"]]
    tables = {v: compute_synergy(side_rows(split.train), sy["k"], sy["min_games"], sy["interval"], v) for v in variants}
    rows = []
    y = split.valid["a_won"].astype(int).to_numpy()
    for v, t in tables.items():
        def ms(k: str) -> float:
            return t.mean_synergy([int(x.split(":")[0]) for x in k.split("|") if x])[0]
        d = split.valid["deck_a"].map(ms).to_numpy() - split.valid["deck_b"].map(ms).to_numpy()
        auc = float(roc_auc_score(y, d)) if len(set(y)) > 1 and np.ptp(d) > 0 else 0.5
        rows.append({"expected_from": v, "valid_auc": auc})
    table = pd.DataFrame(rows)
    best = table.sort_values("valid_auc", ascending=False).iloc[0]["expected_from"]
    table["selected"] = table["expected_from"] == best
    return tables[best], table


def train_strength(split: Split, syn_train: SynergyTable, cfg: dict, hero_observable: bool) -> tuple[CardModel, pd.DataFrame, SynergyTable]:
    """Fit baselines and both card models on train, select on valid, refit the winner on train+valid.

    Returns (final model, comparison table, synergy table on train+valid).
    The comparison's test columns use models refit on train+valid.
    """
    s = cfg["strength"]
    sy = cfg["synergy"]
    pair_list = top_pairs(syn_train, s["top_n_pairs"])
    skill = bool(s.get("skill_control", False))
    suffix = "+skill" if skill else ""
    names = (f"card_lr{suffix}", f"card_lr+pairs{suffix}")
    best: dict[str, tuple[float, float, CardModel]] = {}
    tried = []
    for C in s["C_grid"]:
        for name, pl in ((names[0], []), (names[1], pair_list)):
            m = CardModel(hero_observable, C, s["max_iter"], s["min_feature_games"], pairs=pl, name=name,
                          skill_control=skill).fit(split.train)
            ev_ = evaluate(m, split.valid)
            ll_ = ev_["log_loss"]
            tried.append({"model": name, "C": C, "valid_log_loss": ll_, "valid_auc": ev_["auc"]})
            if name not in best or ll_ < best[name][0]:
                best[name] = (ll_, C, m)
    pop = PopularityBaseline().fit(split.train)
    rating = RatingBaseline().fit(split.train)
    const = ConstantBaseline()
    rows = [{**evaluate(m, split.valid), "part": "valid", "C": None} for m in (const, pop, rating)]
    rows += [{**evaluate(best[n][2], split.valid), "part": "valid", "C": best[n][1]} for n in names]
    valid = pd.DataFrame(rows)
    chosen = names[1] if best[names[1]][0] < best[names[0]][0] else names[0]
    C_base, C_pairs = best[names[0]][1], best[names[1]][1]

    tv = split.train_valid
    syn_tv = compute_synergy(side_rows(tv), sy["k"], sy["min_games"], sy["interval"], sy["expected_from"])
    final_base = CardModel(hero_observable, C_base, s["max_iter"], s["min_feature_games"], name=names[0],
                           skill_control=skill).fit(tv)
    final_pairs = CardModel(hero_observable, C_pairs, s["max_iter"], s["min_feature_games"],
                            pairs=top_pairs(syn_tv, s["top_n_pairs"]), name=names[1], skill_control=skill).fit(tv)
    final_pop = PopularityBaseline().fit(tv)
    final_rating = RatingBaseline().fit(tv)
    test_rows = [{**evaluate(m, split.test), "part": "test", "C": c}
                 for m, c in ((const, None), (final_pop, None), (final_rating, None), (final_base, C_base), (final_pairs, C_pairs))]
    comp = pd.concat([valid, pd.DataFrame(test_rows)], ignore_index=True)
    comp["selected"] = comp["model"] == chosen
    final = final_pairs if chosen == names[1] else final_base
    cand = pd.DataFrame(tried)
    cand["best_C_for_model"] = [best[r["model"]][1] == r["C"] for _, r in cand.iterrows()]
    cand["selected"] = cand["best_C_for_model"] & (cand["model"] == chosen)
    comp.attrs["candidates"] = cand
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
                 cache: bool | None = None, mode: str = "ranked", arena: str | None = None) -> Context:
    """Train (or load cached) models for one mode (and optionally one arena).
    mode: a key of config battles.modes (e.g. 'ranked', 'trophy_road') or of battles.combined ('all').
    The cache in processed/context_cache_<slug>.pkl is reused only when the fingerprint of data,
    labels, configs and code is unchanged. cache=None reads CRDECK_NO_CACHE=1 to disable it."""
    import os
    import pickle
    if cache is None:
        cache = os.environ.get("CRDECK_NO_CACHE") != "1"
    paths = paths or Paths.for_source(source)
    cache_file = paths.processed / f"context_cache_{mode_slug(mode, arena)}.pkl"
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
    ctx = _train_context(paths, verbose, mode, arena)
    if cache:
        paths.processed.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as f:
            pickle.dump((fp, ctx), f)
    return ctx


def _train_context(paths: Paths, verbose: bool, mode: str = "ranked", arena: str | None = None) -> Context:
    cfg = model_config()
    ccfg = collection_config()
    rules = DeckRules.load()
    cards = load_card_table(paths.processed / "cards.parquet")
    battles, dib, decks, counts = load_interim(paths)
    if "mode" not in battles:
        raise NoDataError("interim tables predate modes; run `python -m crdeck build` again")
    mb = model_battles(battles, dib, modes_for(ccfg, mode), arena)
    label = mode_label(ccfg, mode, arena)
    if len(mb) < 100:
        raise NoDataError(f"not enough data for {label}: only {len(mb)} usable battles (minimum 100)")
    split = time_split(mb, ccfg["split"]["train_frac"], ccfg["split"]["valid_frac"])
    for part in ("train", "valid", "test"):
        if len(getattr(split, part)) < 30:
            raise NoDataError(f"not enough data for {label}: the time split leaves only {len(getattr(split, part))} battles in {part}; "
                              "collect battles over a longer period before modeling")
    hero_obs = FormConfig.from_collection(ccfg).hero_observable

    sy = cfg["synergy"]
    syn_train, syn_choice = choose_synergy(split, sy)
    cfg = {**cfg, "synergy": {**sy, "expected_from": syn_train.expected_from}}
    strength, comp, syn_tv = train_strength(split, syn_train, cfg, hero_obs)
    candidates = comp.attrs.pop("candidates", None)

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
                  test_deck_records=test_records, deck_appearances=appearances, archetype_labels=labels,
                  synergy_choice=syn_choice, mode=mode, arena=arena, mode_label=label, candidates=candidates)
    if verbose:
        print(paths.banner())
        print(split.describe().to_string(index=False))
    return ctx
