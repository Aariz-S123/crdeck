"""Scoring a frozen watch list against one balance update (docs/balance/DESIGN.md, Section 6).

A snapshot is scored exactly as it was written: this module reads the snapshot file's own numbers and the calendar's
labels, and recomputes nothing from battles. The unit of evaluation is the update, never the card row.
"""

from __future__ import annotations

import datetime as dt

from .events import BALANCE_LABELS, DIRECTIONAL, Event, card_labels
from .watch import K_EVAL

BASELINES = ("random", "usage_only", "edge_only", "band_rule", "recency", "trend")
CUTOFF_GAP_HOURS = 24


class ScoreError(ValueError):
    pass


def cutoff_ok(snapshot: dict, event: Event) -> bool:
    """A snapshot may be scored for an update only if its cutoff is at least 24 hours before the update's first
    public day (00:00 UTC of the announcement day when one is recorded, else of the effective day)."""
    cutoff = dt.datetime.strptime(snapshot["cutoff"], "%Y-%m-%dT%H:%M:%SZ")
    public = dt.datetime.combine(event.first_public, dt.time())
    return cutoff <= public - dt.timedelta(hours=CUTOFF_GAP_HOURS)


def pick_snapshot(snapshots: list[dict], event: Event) -> dict | None:
    """The newest usable snapshot whose cutoff is early enough; None when there is none."""
    ok = [s for s in snapshots if s.get("status") != "insufficient" and s.get("cards") and cutoff_ok(s, event)]
    return max(ok, key=lambda s: s["cutoff"]) if ok else None


def _lists(snapshot: dict) -> dict[str, dict[str, list[int]]]:
    """For each method, the full ordering of eligible card ids per direction (best candidate first)."""
    cards = [c for c in snapshot["cards"] if c["eligible"]]
    by = lambda key, reverse: [c["card_id"] for c in sorted(cards, key=lambda c: ((-key(c) if reverse else key(c)), c["card_id"]))]  # noqa: E731
    num = lambda v: 0.0 if v is None else float(v)  # noqa: E731
    out: dict[str, dict[str, list[int]]] = {}
    # the watch score: the direction's own cards by score first, then every other eligible card by that score
    out["score"] = {d: [c["card_id"] for c in sorted(cards, key=lambda c: (c["direction"] != d, -num(c[f"{d}_score"]), c["card_id"]))] for d in DIRECTIONAL}
    out["usage_only"] = {"nerf": by(lambda c: num(c["log_usage_ratio"]), True), "buff": by(lambda c: num(c["log_usage_ratio"]), False)}
    out["edge_only"] = {"nerf": by(lambda c: num(c["edge_pts"]), True), "buff": by(lambda c: num(c["edge_pts"]), False)}
    out["trend"] = {"nerf": by(lambda c: num(c["momentum"]), True), "buff": by(lambda c: num(c["momentum"]), False)}
    return out


def _short_lists(snapshot: dict) -> dict[str, dict[str, list[int]]]:
    """Methods that list only some cards: the watch score's own direction lists, the band rule and the recency rule."""
    cards = [c for c in snapshot["cards"] if c["eligible"]]
    last = (snapshot.get("calendar") or {}).get("last_event") or {}
    out: dict[str, dict[str, list[int]]] = {"score": {}, "band_rule": {}, "recency": {}}
    for d in DIRECTIONAL:
        own = [c for c in cards if c["direction"] == d]
        out["score"][d] = [c["card_id"] for c in sorted(own, key=lambda c: (-float(c[f"{d}_score"]), c["card_id"]))]
        # recency: changed at the last update in this direction, most recently released first
        moved = [c for c in cards if c.get("last_change") and c["last_change"]["event_id"] == last.get("id") and c["last_change"]["label"] == d]
        out["recency"][d] = [c["card_id"] for c in sorted(moved, key=lambda c: (c.get("released") or "", ), reverse=True)]
    wr = [c for c in cards if c.get("wr_raw") is not None]
    out["band_rule"]["nerf"] = [c["card_id"] for c in sorted((c for c in wr if c["wr_raw"] > 0.55), key=lambda c: (-c["wr_raw"], c["card_id"]))]
    out["band_rule"]["buff"] = [c["card_id"] for c in sorted((c for c in wr if c["wr_raw"] < 0.45), key=lambda c: (c["wr_raw"], c["card_id"]))]
    return out


def average_precision(order: list[int], positives: set[int]) -> float | None:
    if not positives:
        return None
    hits, total = 0, 0.0
    for r, cid in enumerate(order, start=1):
        if cid in positives:
            hits += 1
            total += hits / r
    return total / len(positives)


def score_event(snapshot: dict, event: Event, *, k: int = K_EVAL, pilot: bool = False) -> dict:
    """One track-record row: the snapshot's lists against the update's labels, with every baseline at the same K."""
    if not cutoff_ok(snapshot, event):
        raise ScoreError(f"snapshot cutoff {snapshot['cutoff']} is not at least {CUTOFF_GAP_HOURS} hours before {event.id} became public")
    if snapshot.get("status") == "insufficient" or not snapshot.get("cards"):
        raise ScoreError("the snapshot holds no list (status insufficient)")
    labels = card_labels(event)
    eligible = {c["card_id"] for c in snapshot["cards"] if c["eligible"]}
    full, short = _lists(snapshot), _short_lists(snapshot)
    row = {"event_id": event.id, "effective_date": event.effective_date.isoformat(), "snapshot_cutoff": snapshot["cutoff"], "pilot": bool(pilot or snapshot.get("pilot")),
           "k": k, "eligible": len(eligible), "baselines": {b: {} for b in BASELINES}}
    for d in DIRECTIONAL:
        pos_all = {c for c, lab in labels.items() if lab == d}
        pos = pos_all & eligible
        own = short["score"][d]
        row[d] = {"labels": len(pos_all), "labels_eligible": len(pos), "listed": min(k, len(own)),
                  "hits": len(set(own[:k]) & pos), "hits5": len(set(own[:5]) & pos),
                  "recall": (len(set(own[:k]) & pos) / len(pos)) if pos else None,
                  "ap": average_precision(full["score"][d], pos),
                  "hit_cards": sorted(set(own[:k]) & pos)}
        k_eff = min(k, len(eligible))
        row["baselines"]["random"][d] = (k_eff * len(pos) / len(eligible)) if eligible else 0.0
        for b in ("usage_only", "edge_only", "trend"):
            row["baselines"][b][d] = len(set(full[b][d][:k]) & pos)
        for b in ("band_rule", "recency"):
            row["baselines"][b][d] = len(set(short[b][d][:k]) & pos)
            row["baselines"][b][f"{d}_listed"] = min(k, len(short[b][d]))
    # secondary: changed at all (nerf, buff or rework), against the two lists together
    changed = {c for c, lab in labels.items() if lab in BALANCE_LABELS}
    listed = set(short["score"]["nerf"][:k]) | set(short["score"]["buff"][:k])
    row["changed"] = {"labels": len(changed), "labels_eligible": len(changed & eligible), "hits": len(listed & changed)}
    return row


def summary(rows: list[dict]) -> dict:
    """Sums across scored updates, and in how many the watch score beat each baseline (nerf + buff hits@K)."""
    real = [r for r in rows if not r.get("pilot")]
    total = lambda r: r["nerf"]["hits"] + r["buff"]["hits"]  # noqa: E731
    base = lambda r, b: r["baselines"][b]["nerf"] + r["baselines"][b]["buff"]  # noqa: E731
    return {"events": len(real), "pilots": len(rows) - len(real), "hits": sum(total(r) for r in real),
            "labels": sum(r["nerf"]["labels_eligible"] + r["buff"]["labels_eligible"] for r in real),
            "beats": {b: sum(total(r) > base(r, b) for r in real) for b in BASELINES}}
