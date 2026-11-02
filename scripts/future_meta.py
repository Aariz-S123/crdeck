"""Builds web/future_meta.json: what makes a deck good, the usage forecast (TimesFM and Monte Carlo) and the decks to consider,
each with its forward check. Design, fixed before any result: docs/future-meta/DESIGN.md.

It never touches data/interim, the exported models or their caches. Its own work is cached in data/processed/future_meta/, so a
rerun after a new collection only computes what changed.

    python scripts/future_meta.py

Needs .venv-timesfm once: py -3.12 -m venv .venv-timesfm && .venv-timesfm/Scripts/python -m pip install -r requirements-timesfm.txt
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.config import Paths, model_config  # noqa: E402
from crdeck.forecast import monte_carlo, period_data, period_stats  # noqa: E402
from crdeck.futuremeta import data as dm  # noqa: E402
from crdeck.futuremeta import decks as dk  # noqa: E402
from crdeck.futuremeta import forecasting as fc  # noqa: E402
from crdeck.futuremeta import quality as q  # noqa: E402
from crdeck.futuremeta import report as rp  # noqa: E402
from crdeck.futuremeta import timesfm_runner as tf  # noqa: E402
from crdeck.rules import parse_deck_key  # noqa: E402

WEB = ROOT / "web"
LOG_T0 = time.time()


def log(*a) -> None:
    print(f"[{time.time() - LOG_T0:6.0f}s]", *a, flush=True)


def deck_styles(data) -> dict[str, str]:
    return {d: data.archetype.predict(parse_deck_key(d)).label for d in data.decks}


def card_family(data, cfg) -> fc.Family:
    return fc.Family("cards", list(data.keys), data.membership, 8.0, int(cfg["forecast"]["min_games"]))


def style_family(data, styles, cfg) -> fc.Family:
    names = sorted(set(styles.values()))
    idx = {n: i for i, n in enumerate(names)}
    rows = np.arange(len(data.decks))
    cols = np.array([idx[styles[d]] for d in data.decks])
    return fc.Family("styles", names, sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(data.decks), len(names))), 1.0, int(cfg["forecast"]["min_games"]))


def deck_family(data, cfg, force: set[str]) -> fc.Family:
    """Single decks: the 60 most used at each origin (added after the design; see its last section), plus the listed decks live."""
    every = np.ones(len(data.deck), dtype=bool)
    games = data.deck_counts(every, data.period, data.n_periods).toarray()
    picked = np.flatnonzero((games.max(axis=0) >= int(cfg["decks"]["min_games_candidate"])) | np.isin(np.array(data.decks), list(force)))
    labels = [data.decks[i] for i in picked]
    mem = sparse.csr_matrix((np.ones(len(picked)), (picked, np.arange(len(picked)))), shape=(len(data.decks), len(picked)))
    live = np.array([d in force for d in labels])
    return fc.Family("decks", labels, mem, None, int(cfg["decks"]["min_games_candidate"]), top_n=60, force_live=live)


def replicator_runner(data, battles, dib, cfg, model_cfg):
    """The existing replicator Monte Carlo for a period, in this run's card order, fed only battles fetched by the origin,
    like every other method here. Also returns the measured history's 90% bootstrap ranges, from all battles."""
    settings = model_cfg["forecast"]
    n_boot, seed, min_games = int(settings["n_boot"]), int(cfg["seed"]), int(settings["min_games"])
    fetched = pd.to_datetime(battles["fetched_at"], utc=True)
    final = period_data(battles, dib, data.periods.copy())
    stats = period_stats(final, n_boot, seed)
    appearances = final.periods["appearances"].astype(int).tolist()

    def run(o: int) -> np.ndarray:
        known = battles[fetched <= data.periods["end"].iloc[o - 1]]
        pdat = period_data(known, dib, data.periods.iloc[:o].copy())
        st = period_stats(pdat, n_boot, seed + o)
        sims = monte_carlo(st, o - 1, list(range(o - 1)), appearances[o], int(cfg["forecast"]["runs"]), seed + o, min_games)
        where = {k: i for i, k in enumerate(pdat.keys)}
        return np.column_stack([sims[:, where[k]] if k in where else np.zeros(sims.shape[0]) for k in data.keys])
    order = [final.keys.index(k) for k in data.keys]
    lo, hi = np.nanquantile(stats["share_boot"], 0.05, axis=1), np.nanquantile(stats["share_boot"], 0.95, axis=1)
    return run, np.stack([lo[:, order], hi[:, order]], axis=2)


def recommender(data, res_cards, models, styles, cfg, facts):
    """Quality rows, scores and lists at every origin, then the forward check of the lists."""
    dc = cfg["decks"]
    P = data.n_periods
    memo: dict[str, bool] = {}
    by_origin = {org.index: org for org in res_cards["origins"]}
    quality_rows, frames, members_10, members_30, checks, correlations, picks = [], [], [], [], [], [], []
    live_rows, live_scored, gap = None, None, None
    origins_used = []
    for o in range(2, P + 1):
        if not by_origin[o].forecast:   # too few battles known at this origin: not a forecast time
            continue
        W = dk.weights_of(models[o], data.keys)
        rec = dk.own_record(data, models[o], o, int(dc["min_games_tau"]))
        now = np.nan_to_num(by_origin[o].shares[o - 1], nan=0.0)
        rows = q.signals(data, o, rec, W, now, styles, facts, int(cfg["quality"]["min_games"]))
        side = dk.target_rows(data, o) if o < P else None
        if o < P:
            quality_rows.append(q.add_targets(rows, data, o, side, int(cfg["quality"]["min_games_next"])))
        else:
            live_rows = rows
        if o < 3:
            continue
        s = dk.score_origin(data, o, W, rec, by_origin[o].forecast[1]["sims"], now, cfg, memo)
        if o == P:
            live_scored = s
            top = np.argsort(-s.played_last, kind="stable")[:200]
            opp = data.membership[np.argsort(-np.bincount(data.deck[data.period == o - 1], minlength=len(data.decks)), kind="stable")[:2000]]
            gap = dk.exact_field_gap(s.members[top], opp, W)
            continue
        origins_used.append(o)
        adj = dk.adjusted(side)
        lists10, lists30 = dk.lists_at(s, int(dc["top"]), int(dc["min_diff"])), dk.lists_at(s, int(dc["top_secondary"]), int(dc["min_diff"]))
        frames.append(side)
        members_10.append({k: set(v) for k, v in lists10.items()})
        members_30.append({k: set(v) for k, v in lists30.items()})
        checks += dk.range_check(s, adj, int(dc["min_games_range_check"]))
        picks += dk.pick_games(s, lists10["future_field"], side)
        rec_adj = s.record["adj"].reindex(s.decks).fillna(0.5).to_numpy()
        correlations.append({"origin": o, **dk.rank_correlation({"future_field": s.mean, "current_field": s.current, "cards_only": s.cards_only, "last_record": rec_adj,
                                                                 "most_played": s.played_last.astype(float)}, s, adj, int(dc["min_games_range_check"]))})
        log(f"origin {o}: {len(s.decks)} candidates, tau {np.sqrt(s.tau2):.3f}, largest forecast effect {np.abs(s.mean - s.current).max() * 100:.3f} points")
    return {"quality_rows": pd.concat(quality_rows, ignore_index=True), "live_rows": live_rows, "live": live_scored, "frames": frames, "members_10": members_10,
            "members_30": members_30, "checks": checks, "correlations": correlations, "gap": gap, "picks": picks, "origins": origins_used}


def range_summary(checks: list[tuple]) -> dict:
    if not checks:
        return {"decks": 0}
    a = np.array(checks)
    hit = np.abs(a[:, 2] - a[:, 0]) <= fc.Z90 * a[:, 1]
    hit50 = np.abs(a[:, 2] - a[:, 0]) <= 0.6744897501960817 * a[:, 1]
    return {"decks": int(len(a)), "games": int(a[:, 3].sum()), "coverage_90": float(hit.mean()), "coverage_50": float(hit50.mean())}


def main() -> None:
    paths = Paths.for_source("real")
    cfg, model_cfg = dm.settings(), model_config()
    cache = dm.cache_dir(paths)
    data, info = dm.load(paths)
    log(f"{data.n_periods} periods, {len(data.deck) // 2} battles in them, newest {info['last_battle']}")
    styles = deck_styles(data)
    log("styles labelled")
    forecaster = lambda tasks: tf.forecast(tasks, cfg, cache / "timesfm")  # noqa: E731
    battles, dib = pd.read_parquet(cache / "battles.parquet"), pd.read_parquet(cache / "sides.parquet")
    replicator, history_range = replicator_runner(data, battles, dib, cfg, model_cfg)
    log("replicator statistics done")
    events = [e for e in cfg.get("events", []) if rp.event_shift(data, e) is not None]
    after = rp.after_event_mask(data, events)
    res_cards = fc.run_family(data, card_family(data, cfg), cfg, forecaster, replicator, keep_sims=True)
    log("card forecast done:", json.dumps(fc.gate(res_cards["rows"])))
    res_styles = fc.run_family(data, style_family(data, styles, cfg), cfg, forecaster)
    log("style forecast done")
    models = {}
    for o in range(2, data.n_periods + 1):
        t0 = time.time()
        models[o] = dk.fit_model(data, o, cfg, model_cfg, cache)
        log(f"matchup model {o}/{data.n_periods}: {len(models[o].pairs)} pairs, {time.time() - t0:.0f}s")
    facts = q.card_facts(data)
    rec = recommender(data, res_cards, models, styles, cfg, facts)
    log("decks scored")
    qc = cfg["quality"]
    analyses, fitted = {}, {}
    for target in ("next_edge", "next_growth"):
        analyses[target], fitted[target] = q.analyze_target(rec["quality_rows"], target, qc, int(cfg["seed"]))
        log(f"{target}: out-of-time R2 {analyses[target]['r2']}, challenger {analyses[target]['challenger_r2']}")
    dc = cfg["decks"]
    names = list(dk.LISTS) + ["all_candidates"]
    check_10 = dk.pooled_check(rec["frames"], rec["members_10"], names, int(dc["bootstrap"]), int(cfg["seed"]), int(dc["min_games_judge"]))
    check_30 = dk.pooled_check(rec["frames"], rec["members_30"], names, int(dc["bootstrap"]), int(cfg["seed"]), int(dc["min_games_judge"]))
    log("deck check done")
    s, live_rows = rec["live"], rec["live_rows"]
    sims = res_cards["origins"][-1].forecast[1]["sims"]
    top_share = s.top_share(int(dc["top"]))
    listed = dk.lists_at(s, int(dc["top"]), int(dc["min_diff"]))
    pos = {d: i for i, d in enumerate(s.decks)}
    row_of = lambda d: live_rows[live_rows["deck"] == d] if (live_rows["deck"] == d).any() else None  # noqa: E731
    since = rp.since_event_records(data, after)

    def make(d: str) -> dict:
        row = rp.deck_row(s, pos[d], top_share, styles, sims, fitted, row_of(d), data.keys)
        if after is not None:
            row["since_event"] = {"games": since.get(d, (0, 0))[0], "wins": since.get(d, (0, 0))[1]}
        return row
    consider, popular = [make(d) for d in listed["future_field"]], [make(d) for d in listed["most_played"]]
    res_decks = fc.run_family(data, deck_family(data, cfg, {x["deck"] for x in consider + popular}), cfg, forecaster)
    log("deck usage forecast done")
    out = {
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "design": "docs/future-meta/DESIGN.md",
        "model": {"name": "TimesFM 2.5", "repo": cfg["timesfm"]["repo"], "revision": tf.model_revision(cfg["timesfm"]["repo"]), "weights_license": "Apache-2.0"},
        "settings": {"runs": cfg["forecast"]["runs"], "seed": cfg["seed"], "min_games": cfg["forecast"]["min_games"], "top": dc["top"], "top_secondary": dc["top_secondary"], "min_diff": dc["min_diff"],
                     "min_games_judge": dc["min_games_judge"], "min_games_candidate": dc["min_games_candidate"], "candidate_periods": dc["candidate_periods"], "hours_per_step": cfg["forecast"]["live_hours_per_step"], "ridge_alpha": qc["ridge_alpha"]},
        "data": {"periods": rp.periods_json(data), "in_progress": data.in_progress, "newest_battle": info["last_battle"], "battles": int(len(data.deck) // 2), "logs": info["logs"],
                 "live_from": str(data.periods["end"].iloc[-1]), "unknown_card_ids": info["unknown_card_ids"], "skipped_origins": res_cards["skipped"],
                 "events": [{**rp.event_shift(data, e), "sampled_players": rp.sampled_player_results(battles, dib, e, rp.event_shift(data, e)["hours_after"])} for e in events]},
        "gate": fc.gate(res_cards["rows"]),
        "forecast": {"cards": rp.family_json(res_cards, rp.since_event_shares(data, res_cards["family"].membership, after), history_range),
                     "styles": rp.family_json(res_styles, rp.since_event_shares(data, res_styles["family"].membership, after)), "decks": rp.family_json(res_decks)},
        "quality": {"targets": analyses, "transitions": int(rec["quality_rows"]["origin"].nunique())},
        "recommend": {"check_top": check_10, "check_secondary": check_30, "origins": rec["origins"], "range_check": range_summary(rec["checks"]),
                      "rank_correlation": rec["correlations"], "field_gap": rec["gap"], "picks_estimate": dk.picks_estimate(rec["picks"]), "tau": float(np.sqrt(s.tau2)), "candidates": len(s.decks), "consider": consider, "popular": popular},
        "assumptions": [{"text": a, "test": b} for a, b in rp.ASSUMPTIONS],
    }
    target = WEB / "future_meta.json"
    target.write_text(json.dumps(rp.r(out), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    log("wrote", target, f"{target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
