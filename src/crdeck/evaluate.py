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


def strength_report(ctx) -> pd.DataFrame:
    return ctx.model_comparison.copy()


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
    return {
        "decks_evaluated": len(decks) - skipped, "skipped": skipped, "masked_per_deck": mask, "k": k,
        "recall_model": hits_m / total if total else float("nan"),
        "recall_popular_fill": hits_b / total if total else float("nan"),
        "part": part, "cooccurrence_weight": searcher.co_weight,
        "note": f"{len(cand_ids)} candidate card forms; decks = most frequent {part}-window decks",
    }


def choose_cooccurrence(table: pd.DataFrame) -> float | None:
    """Smallest weight whose validation recall beats popular fill (keeps strength dominant)."""
    beat = table[table["valid_recall_model"] > table["valid_recall_popular_fill"]]
    return float(beat["cooccurrence_weight"].min()) if len(beat) else None


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
    for i, name in enumerate([f"mean_synergy ({syn.expected_from}, used)", f"mean_synergy ({other})", "mean_lift", "popularity"]):
        d = fa[:, i] - fb[:, i]
        rows.append({"score": name, "test_auc": float(roc_auc_score(y, d)) if np.ptp(d) > 0 else 0.5})
    return pd.DataFrame(rows)


def archetype_eval(ctx) -> dict:
    if ctx.archetype_labels is None or ctx.archetype_labels.empty:
        return {"status": "NO_LABELS", "detail": f"label decks in {ctx.paths.archetype_labels} first"}
    if not ctx.archetype.fitted:
        return {"status": "NOT_FITTED", "detail": "need train labels for at least 2 archetypes"}
    return ctx.archetype.evaluate_heldout(ctx.archetype_labels)


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
    s, e = ctx.split.window("test")
    return {
        "source": ctx.paths.banner(),
        "described_as": f"held-out top-player battles from {s} to {e}",
        "strength": strength_report(ctx),
        "completion": completion_recall(ctx, n_decks=completion_decks),
        "synergy": synergy_eval(ctx),
        "archetype": archetype_eval(ctx),
        "level_gap": level_gap_check(ctx),
    }
