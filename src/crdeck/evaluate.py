"""Held-out evaluation against simple baselines (spec section 10).

All numbers describe held-out top-player battles in the test window, not
anyone's personal win rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .dataset import side_rows
from .rules import parse_deck_key
from .search import Searcher, SeedError
from .strength import evaluate
from .synergy import compute_synergy


def observed_deck_audit(paths, cards, rules) -> dict:
    """Check the slot rules against decks actually played in OK battles.

    Counts special-card combinations, where champions / evos / heroes sat (from deck
    positions), and how many observed decks the validator rejects. A rejection here
    means config/deck_rules.yaml disagrees with real play.
    """
    from collections import Counter
    from .pipeline import load_interim
    from .rules import check_deck
    battles, dib, _, _ = load_interim(paths)
    slots = pd.read_parquet(paths.interim / "slot_cards.parquet")
    keys = sorted(set(dib.loc[dib["battle_key"].isin(battles.loc[battles["status"] == "OK", "battle_key"]), "deck_key"]))
    combos, rejected = Counter(), Counter()
    for k in keys:
        entries = parse_deck_key(k)
        combos[(sum(e.form == "evo" for e in entries), sum(e.form == "hero" for e in entries),
                sum(cards[e.card_id].is_champion for e in entries if e.card_id in cards))] += 1
        r = check_deck(entries, cards, rules)
        if not r.legal:
            rejected["; ".join(r.reasons)] += 1
    sc = slots[slots["deck_key"].isin(keys)].copy()
    sc["champion"] = sc["card_id"].map(lambda c: c in cards and cards[c].is_champion)
    combo_df = pd.DataFrame([{"evos": a, "heroes": b, "champions": c, "decks": n} for (a, b, c), n in sorted(combos.items())])
    return {
        "distinct_decks": len(keys),
        "combinations": combo_df,
        "champion_slots": sc.loc[sc["champion"], "slot"].value_counts().to_dict(),
        "evo_slots": sc.loc[sc["form"] == "evo", "slot"].value_counts().to_dict(),
        "hero_slots": sc.loc[sc["form"] == "hero", "slot"].value_counts().to_dict(),
        "base_cards_in_special_slots": sc.loc[(sc["form"] == "base") & ~sc["champion"] & sc["slot"].isin(["evo", "hero", "wild"]), "slot"].value_counts().to_dict(),
        "rejected_by_validator": dict(rejected),
    }


def strength_report(ctx) -> pd.DataFrame:
    return ctx.model_comparison.copy()


def _ci(boots) -> list[float]:
    return [float(np.quantile(boots, 0.05)), float(np.quantile(boots, 0.95))]


def strength_intervals(ctx, n_boot: int = 500, seed: int | None = None) -> pd.DataFrame:
    """Test log loss and AUC of the selected model and every baseline, each with a 90%
    bootstrap interval over test battles (same resamples for every model)."""
    from .strength import ConstantBaseline, PopularityBaseline, RatingBaseline
    seed = ctx.cfg["seed"] if seed is None else seed
    t, tv = ctx.split.test, ctx.split.train_valid
    y = t["a_won"].astype(int).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(t), size=(n_boot, len(t)))
    rows = []
    for m in (ctx.strength, ConstantBaseline(), PopularityBaseline().fit(tv), RatingBaseline().fit(tv)):
        p = np.clip(m.predict_df(t), 1e-12, 1 - 1e-12)
        ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
        lls = ll[idx].mean(axis=1)
        aucs = [roc_auc_score(y[i], p[i]) if np.ptp(p[i]) > 0 and len(set(y[i])) > 1 else 0.5 for i in idx]
        auc = float(roc_auc_score(y, p)) if np.ptp(p) > 0 else 0.5
        rows.append({"model": m.name, "selected": m is ctx.strength, "test_log_loss": float(ll.mean()),
                     "log_loss_ci90": _ci(lls), "test_auc": auc, "auc_ci90": _ci(aucs), "test_battles": len(t)})
    return pd.DataFrame(rows)


def strength_significance(ctx, n_boot: int = 2000, seed: int | None = None) -> pd.DataFrame:
    """Paired bootstrap over test battles of log-loss(selected model) - log-loss(baseline).

    Negative = the model is better. The interval says whether a small difference is
    distinguishable from resampling noise on this test window.
    """
    from .strength import ConstantBaseline, PopularityBaseline, RatingBaseline
    seed = ctx.cfg["seed"] if seed is None else seed
    t, tv = ctx.split.test, ctx.split.train_valid
    y = t["a_won"].astype(int).to_numpy()

    def ll(p):
        p = np.clip(p, 1e-12, 1 - 1e-12)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    model_ll = ll(ctx.strength.predict_df(t))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(t), size=(n_boot, len(t)))
    rows = []
    for base in (ConstantBaseline(), PopularityBaseline().fit(tv), RatingBaseline().fit(tv)):
        d = model_ll - ll(base.predict_df(t))
        boots = d[idx].mean(axis=1)
        rows.append({"model": ctx.strength.name, "vs": base.name, "delta_log_loss": float(d.mean()),
                     "ci90_lo": float(np.quantile(boots, 0.05)), "ci90_hi": float(np.quantile(boots, 0.95)),
                     "share_boot_better": float((boots < 0).mean()), "test_battles": len(t)})
    return pd.DataFrame(rows)


def completion_recall(ctx, n_decks: int = 100, mask: int = 2, k: int = 10, beam_width: int = 10, seed: int | None = None,
                      part: str = "test", cooccurrence_weight: float | None = None) -> dict:
    """Mask `mask` cards from frequent held-out decks; recall@k of the masked cards.

    Model ranking: cards ordered by first appearance across the beam's ranked
    completions, then by single-card objective gain. Baseline: most popular
    train cards not already in the deck.
    """
    seed = ctx.cfg["seed"] if seed is None else seed
    rng = np.random.default_rng(seed)
    test_sides = side_rows(getattr(ctx.split, part))
    freq = test_sides["deck_key"].value_counts()
    searcher = Searcher(ctx, cooccurrence_weight)
    cand_ids = {c.card_id for c in searcher.candidates}
    decks = [d for d in freq.index if all(e.card_id in ctx.cards for e in parse_deck_key(d))][: n_decks]

    pop = pd.Series([e.card_id for d in side_rows(ctx.split.train_valid)["deck_key"] for e in parse_deck_key(d)]).value_counts()
    hits_m = hits_b = total = 0
    skipped = 0
    per_deck = []  # (model hits, baseline hits, masked cards) per evaluated deck
    for d in decks:
        entries = parse_deck_key(d)
        idx = rng.choice(len(entries), mask, replace=False)
        masked = [entries[i] for i in idx]
        seeds = [e for i, e in enumerate(entries) if i not in idx]
        try:
            res = searcher.complete(seeds, n_results=beam_width, beam_width=beam_width)
        except SeedError:
            skipped += 1
            continue
        ranked: list[int] = []
        seed_ids = {e.card_id for e in seeds}
        for r in res:
            for e in r.entries:
                if e.card_id not in seed_ids and e.card_id not in ranked:
                    ranked.append(e.card_id)
        if len(ranked) < k:
            gains = []
            for c in searcher.candidates:
                if c.card_id in seed_ids or c.card_id in ranked:
                    continue
                gains.append((searcher.evaluate(seeds + [c]).objective, c.card_id))
            for _, cid in sorted(gains, reverse=True):
                if cid not in ranked:
                    ranked.append(cid)
                if len(ranked) >= k:
                    break
        top_m = set(ranked[:k])
        top_b = [c for c in pop.index if c not in seed_ids][:k]
        truth = {e.card_id for e in masked}
        hits_m += len(truth & top_m)
        hits_b += len(truth & set(top_b))
        total += len(truth)
        per_deck.append((len(truth & top_m), len(truth & set(top_b)), len(truth)))
    ci = {}
    if per_deck:
        arr = np.array(per_deck, float)
        bidx = np.random.default_rng(seed + 1).integers(0, len(arr), size=(1000, len(arr)))
        sm, sb, st = arr[:, 0][bidx].sum(1), arr[:, 1][bidx].sum(1), arr[:, 2][bidx].sum(1)
        ci = {"recall_model_ci90": _ci(sm / st), "recall_popular_fill_ci90": _ci(sb / st), "difference_ci90": _ci((sm - sb) / st)}
    return {
        "decks_evaluated": len(decks) - skipped, "skipped": skipped, "masked_per_deck": mask, "k": k,
        "recall_model": hits_m / total if total else float("nan"),
        "recall_popular_fill": hits_b / total if total else float("nan"),
        **ci,
        "part": part, "cooccurrence_weight": searcher.co_weight,
        "note": f"{len(cand_ids)} candidate card forms; decks = most frequent {part}-window decks",
    }


def choose_cooccurrence(table: pd.DataFrame, plateau: float = 0.95) -> float | None:
    """Smallest weight whose validation recall reaches `plateau` x the best validation recall
    and beats popular fill. (Revised 2026-10-18 from "smallest weight that beats popular fill",
    after real data showed the strength model barely beats a coin flip; see docs/model-notes.md.)"""
    ok = table[table["valid_recall_model"] > table["valid_recall_popular_fill"]]
    if ok.empty:
        return None
    ok = ok[ok["valid_recall_model"] >= plateau * table["valid_recall_model"].max()]
    return float(ok["cooccurrence_weight"].min()) if len(ok) else None


def tune_cooccurrence(ctx, grid=(0.0, 0.01, 0.02, 0.05, 0.1, 0.2), n_decks: int = 60) -> pd.DataFrame:
    """Pick cooccurrence_weight by completion recall on the VALIDATION window (never test).

    The synergy table and strength model used here are fit on train+valid, so
    validation decks are partly in-sample; this tunes one scalar only, and the
    final number is still reported on the test window.
    """
    rows = []
    for w in grid:
        r = completion_recall(ctx, n_decks=n_decks, part="valid", cooccurrence_weight=w)
        rows.append({"cooccurrence_weight": w, "valid_recall_model": r["recall_model"],
                     "valid_recall_popular_fill": r["recall_popular_fill"]})
    return pd.DataFrame(rows)


def synergy_eval(ctx) -> pd.DataFrame:
    """Does deck mean synergy predict held-out winners better than mean lift or popularity?

    For each test battle, feature difference (A - B) is used as a score; AUC of a_won.
    """
    syn = ctx.synergy
    sy = ctx.cfg["synergy"]
    other = "marginal" if syn.expected_from == "without_partner" else "without_partner"
    syn_alt = compute_synergy(side_rows(ctx.split.train_valid), sy["k"], sy["min_games"], sy["interval"], other)
    rate = dict(zip(syn.cards["card_id"], syn.cards["rate"]))
    cache: dict[str, tuple[float, float, float, float]] = {}

    def feats(k: str):
        if k not in cache:
            ids = [e.card_id for e in parse_deck_key(k)]
            cache[k] = (syn.mean_synergy(ids)[0], syn_alt.mean_synergy(ids)[0], syn.mean_lift(ids),
                        float(np.mean([rate.get(c, 0.0) for c in ids])))
        return cache[k]

    t = ctx.split.test
    fa = np.array([feats(k) for k in t["deck_a"]])
    fb = np.array([feats(k) for k in t["deck_b"]])
    y = t["a_won"].astype(int).to_numpy()
    rows = []
    bidx = np.random.default_rng(ctx.cfg["seed"] + 2).integers(0, len(y), size=(300, len(y)))
    for i, name in enumerate([f"mean_synergy ({syn.expected_from}, used)", f"mean_synergy ({other})", "mean_lift", "popularity"]):
        d = fa[:, i] - fb[:, i]
        auc = float(roc_auc_score(y, d)) if np.ptp(d) > 0 else 0.5
        boots = [roc_auc_score(y[j], d[j]) if np.ptp(d[j]) > 0 and len(set(y[j])) > 1 else 0.5 for j in bidx]
        rows.append({"score": name, "test_auc": auc, "auc_ci90": _ci(boots)})
    return pd.DataFrame(rows)


def archetype_eval(ctx) -> dict:
    if ctx.archetype_labels is None or ctx.archetype_labels.empty:
        return {"status": "NO_LABELS", "detail": f"label decks in {ctx.paths.archetype_labels} first"}
    if not ctx.archetype.fitted:
        return {"status": "NOT_FITTED", "detail": "need train labels for at least 2 archetypes"}
    out = ctx.archetype.evaluate_heldout(ctx.archetype_labels)
    held = ctx.archetype_labels[ctx.archetype_labels["split"] == "heldout"]
    if len(held):
        am = ctx.archetype
        pred = np.array([max(zip(am.lr.predict_proba(am._X([k]))[0], am.classes))[1] for k in held["deck_key"]])
        truth = held["archetype"].to_numpy()
        correct, maj = (pred == truth).astype(float), (truth == out["majority_class"]).astype(float)
        bidx = np.random.default_rng(ctx.cfg["seed"] + 3).integers(0, len(truth), size=(2000, len(truth)))
        out["accuracy_ci90"] = _ci(correct[bidx].mean(1))
        out["majority_accuracy_ci90"] = _ci(maj[bidx].mean(1))
        out["labels_note"] = "labels drafted by the project's assistant; accuracy is agreement with that labeler"
    return out


def level_gap_check(ctx, threshold: float = 1.0) -> dict:
    """Spec 7.2: if level gaps exist, does filtering large gaps change test results?"""
    t = ctx.split.test
    if t["level_gap"].isna().all():
        return {"status": "NO_LEVEL_DATA"}
    small = t[t["level_gap"].abs() <= threshold]
    out = {
        "test_battles": len(t),
        "share_gap_over_threshold": float((t["level_gap"].abs() > threshold).mean()),
        "threshold_levels": threshold,
        "all": evaluate(ctx.strength, t),
    }
    if len(small) > 50 and small["a_won"].nunique() > 1:
        out["small_gap_only"] = evaluate(ctx.strength, small)
    return out


def full_report(ctx, completion_decks: int = 100) -> dict:
    from .pipeline import _fingerprint
    s, e = ctx.split.window("test")
    tuning = tune_cooccurrence(ctx)
    chosen = choose_cooccurrence(tuning)
    return {
        "source": ctx.paths.banner(),
        "mode": ctx.mode, "group": ctx.group, "mode_label": ctx.mode_label,
        "test_window": [s, e],
        "data_fingerprint": _fingerprint(ctx.paths),
        "described_as": f"held-out {ctx.mode_label} battles of top players from {s} to {e}",
        "splits": ctx.split.describe(),
        "strength": strength_report(ctx),
        "strength_candidates": ctx.candidates if ctx.candidates is not None else pd.DataFrame(),
        "strength_selection_rule": "lowest validation log loss among the card and card+pairs models, each at its best C",
        "strength_intervals": strength_intervals(ctx),
        "strength_significance": strength_significance(ctx),
        "cooccurrence_tuning": tuning,
        "cooccurrence_choice": {"chosen_on_validation": chosen, "config_value": float(ctx.cfg["search"]["cooccurrence_weight"]),
                                "rule": "smallest grid weight whose validation recall reaches 95% of the best validation recall and beats popular fill",
                                "note": "this rule was revised after test results had been seen (docs/model-notes.md, item 2)"},
        "completion": completion_recall(ctx, n_decks=completion_decks),
        "synergy_variant_choice (validation)": ctx.synergy_choice,
        "synergy": synergy_eval(ctx),
        "archetype": archetype_eval(ctx),
        "level_gap": level_gap_check(ctx),
    }
