"""The balance watch list: the fixed score, the tiers and the file the website reads.

Everything here is fixed by docs/balance/DESIGN.md (Section 5) before any result. Nothing is fitted to labels.
The output is a ranking in tiers, never a probability. No forecast, deck score or counter ranking may read it.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import features as ft
from .events import BALANCE_LABELS, Calendar

VERSION = 1
WEIGHTS = {"edge": 1.0, "usage": 1.0, "momentum": 0.5, "release": 0.5}
TIERS = {"watch": {"max_rank": 5, "min_score": 1.0}, "possible": {"max_rank": 15, "min_score": 0.5}}
K_EVAL = 15
STALE_DAYS = 45
REFERENCE = {"wr_band": [0.45, 0.55], "wr_band_note": "community-reported, not official",
             "usage_band": [0.07, 0.09], "usage_band_note": "reported designer interview, not official"}
REASON_Z = 1.0               # a reason sentence is written only when its signal's z reaches this
MOMENTUM_GLYPH = 0.10        # logit change beyond which the page draws an up or down mark


def scores(E: np.ndarray, U: np.ndarray, M: np.ndarray, R: np.ndarray, eligible: np.ndarray) -> dict[str, np.ndarray]:
    """nerf and buff scores with their z-scores (DESIGN.md Section 5). Cards outside `eligible` score 0."""
    zE, zU, zM = ft.robust_z(E, eligible), ft.robust_z(U, eligible), ft.robust_z(M, eligible)
    pos = lambda v: np.maximum(0.0, v)  # noqa: E731
    nerf = WEIGHTS["edge"] * pos(zE) + WEIGHTS["usage"] * pos(zU) + WEIGHTS["momentum"] * pos(zM) + WEIGHTS["release"] * R.astype(float)
    buff = WEIGHTS["edge"] * pos(-zE) + WEIGHTS["usage"] * pos(-zU) + WEIGHTS["momentum"] * pos(-zM)
    nerf, buff = np.where(eligible, nerf, 0.0), np.where(eligible, buff, 0.0)
    return {"z_edge": zE, "z_usage": zU, "z_momentum": zM, "nerf": nerf, "buff": buff}


def directions(nerf: np.ndarray, buff: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """Per card: "nerf", "buff" or "" (not eligible, or equal scores)."""
    out = np.full(len(nerf), "", dtype=object)
    out[eligible & (nerf > buff)] = "nerf"
    out[eligible & (buff > nerf)] = "buff"
    return out


def ranked(direction: str, dirs: np.ndarray, score: np.ndarray, card_ids: list[int]) -> list[int]:
    """Indices of the cards of one direction, highest score first, ties by card id."""
    idx = [j for j in range(len(card_ids)) if dirs[j] == direction]
    return sorted(idx, key=lambda j: (-score[j], card_ids[j]))


def tiers(dirs: np.ndarray, nerf: np.ndarray, buff: np.ndarray, eligible: np.ndarray, card_ids: list[int]) -> tuple[list[str], list[int | None]]:
    """(tier, rank) per card. Rank is the place within the card's direction, None without one."""
    tier = ["none" if eligible[j] else "not_enough_data" for j in range(len(card_ids))]
    rank: list[int | None] = [None] * len(card_ids)
    for d, score in (("nerf", nerf), ("buff", buff)):
        for r, j in enumerate(ranked(d, dirs, score, card_ids), start=1):
            rank[j] = r
            if r <= TIERS["watch"]["max_rank"] and score[j] > TIERS["watch"]["min_score"]:
                tier[j] = f"{d}_watch"
            elif r <= TIERS["possible"]["max_rank"] and score[j] > TIERS["possible"]["min_score"]:
                tier[j] = f"{d}_possible"
    return tier, rank


def role_of(card) -> str:
    if card.is_win_condition:
        return "win_condition"
    return {"spell": "spell", "building": "building"}.get(card.card_type, "troop")


def _pct(x: float, digits: int = 1) -> str:
    """A share as a percentage; shares under 1% get one more decimal so that small differences stay visible."""
    return f"{100 * x:.{digits + 1 if abs(x) < 0.01 else digits}f}%"


def reasons(direction: str, z: dict[str, float], row: dict, avg_usage: float, momentum_ok: bool) -> list[str]:
    """Fixed sentences, one per signal that points the card's way with z of at least REASON_Z."""
    out = []
    sign = 1 if direction == "nerf" else -1
    if sign * z["usage"] >= REASON_Z:
        ratio = row["usage_top"] / avg_usage
        if direction == "nerf":
            out.append(f"Used in {_pct(row['usage_top'])} of decks, about {ratio:.1f} times the average card.")
        else:
            out.append(f"Used in {_pct(row['usage_top'])} of decks. The average card is in {_pct(avg_usage)}.")
    if sign * z["edge"] >= REASON_Z and row["edge_known"]:
        pts, lo, hi = abs(row["edge_pts"]), row["edge_lo"], row["edge_hi"]
        luck = " The range crosses zero, so this could be luck." if lo < 0 < hi else ""
        word = "more" if direction == "nerf" else "less"
        out.append(f"Decks with it win {pts:.1f} points {word} often than their players' ratings predict (range {lo:+.1f} to {hi:+.1f}).{luck}".replace("-", "−"))
    if momentum_ok and sign * z["momentum"] >= REASON_Z and row["usage_prev"] is not None:
        word = "rising" if direction == "nerf" else "falling"
        out.append(f"Its use is {word}: from {_pct(row['usage_prev'])} of decks to {_pct(row['usage_last'])} in a week.")
    if direction == "nerf" and row["release_recent"]:
        out.append(f"It, or one of its forms, was released in the last {ft.RELEASE_RECENT_DAYS} days.")
    return out


def _iso(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x, digits: int = 5):
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else round(x, digits)


def last_change(card_id: int, events: Calendar, before: dt.date) -> dict | None:
    """The card's newest nerf, buff or rework before `before` (its entries of one update merged as card_labels does)."""
    from .events import card_labels
    best = None
    for e in events:
        if e.effective_date >= before:
            continue
        lab = card_labels(e).get(card_id)
        if lab in BALANCE_LABELS:
            best = {"event_id": e.id, "label": lab, "date": e.effective_date.isoformat(), "source_kind": e.source_kind}
    return best


def build(feats: ft.Features, events: Calendar, cards, *, generated_at: str | None = None, pilot: bool = False,
          track_record: list[dict] | None = None) -> dict:
    """The website file (web/balance_watch.json; contract in docs/fable-brief/BLUEPRINT.md 7.6)."""
    W = feats.window
    T_day = ft._day(W.cutoff)
    N = len(feats.card_ids)
    avg = ft.DECK_SIZE / N if N else None
    newest = events[-1] if len(events) else None
    last = W.last_event
    fresh_from = max([d for d in (newest.effective_date if newest else None, events.checked_on) if d is not None], default=None)
    status = "insufficient" if feats.status != "ok" else "stale" if fresh_from is None or (T_day - fresh_from).days > STALE_DAYS else "preview"
    out = {
        "version": VERSION,
        "generated_at": generated_at or _iso(pd.Timestamp.now(tz="UTC")),
        "status": status,
        "status_reason": feats.reason,
        "pilot": pilot,
        "cutoff": _iso(W.cutoff),
        "window": {"start": _iso(W.start), "end": _iso(W.end), "days": W.days, "excluded_days": [d.isoformat() for d in W.excluded],
                   "ready_on": None, "battles_top": feats.n_battles, "sides_top": feats.n_sides, "players_top": feats.n_players},
        "calendar": {"version": events.version, "checked_on": None if events.checked_on is None else events.checked_on.isoformat(),
                     "last_event": None if last is None else {"id": last.id, "effective_date": last.effective_date.isoformat(), "source_url": last.source_url,
                                                              "source_kind": last.source_kind, "n_changes": len({c.card_id for c in last.changes if c.label in BALANCE_LABELS})},
                     "next_event": None},
        "reference": {**REFERENCE, "avg_usage": _r(avg)},
        "score": {"weights": {k: (int(v) if float(v).is_integer() else v) for k, v in WEIGHTS.items()}, "tiers": TIERS, "k": K_EVAL, "design": "docs/balance/DESIGN.md",
                  "momentum_ok": feats.momentum_ok, "tau2": _r(feats.tau2, 8), "rating_beta": _r(feats.beta, 6),
                  "min_card_sides": ft.MIN_CARD_SIDES, "min_edge_sides": ft.MIN_EDGE_SIDES, "bootstrap": ft.N_BOOT, "seed": ft.SEED},
        "cards": [], "track_record": track_record or [], "groups": [],
    }
    if last is not None:
        # the first cutoff with a full minimum window after the last update: the day the list can come back
        out["window"]["ready_on"] = (last.effective_date + dt.timedelta(days=1 + ft.MIN_WINDOW_DAYS)).isoformat()
    if feats.status != "ok":
        return out

    a = feats.arrays
    eligible = a["eligible"]
    sc = scores(a["edge"], a["U"], a["momentum"], a["release_recent"], eligible)
    dirs = directions(sc["nerf"], sc["buff"], eligible)
    tier, rank = tiers(dirs, sc["nerf"], sc["buff"], eligible, feats.card_ids)
    for j, cid in enumerate(feats.card_ids):
        card = cards[cid]
        known = bool(a["edge_known"][j])
        e_pts, e_sd = 100 * a["edge"][j], 100 * a["edge_sd"][j]
        row = {
            "card_id": int(cid), "name": card.name, "role": role_of(card),
            "eligible": bool(eligible[j]),
            "ineligible_reason": None if eligible[j] else "new_card" if a["new_card"][j] else "too_few_games",
            "usage_top": _r(a["usage_top"][j]), "usage_lo": _r(a["usage_lo"][j]), "usage_hi": _r(a["usage_hi"][j]), "usage_all": _r(a["usage_all"][j]),
            "log_usage_ratio": _r(a["U"][j]),
            "edge_known": known,
            "edge_pts": _r(e_pts, 3) if known else None, "edge_lo": _r(e_pts - ft.Z90 * e_sd, 3) if known else None,
            "edge_hi": _r(e_pts + ft.Z90 * e_sd, 3) if known else None, "edge_raw_pts": _r(100 * a["edge_raw"][j], 3) if known else None,
            "edge_raw_se_pts": _r(100 * a["edge_se"][j], 3) if known else None,
            "edge_sides": int(a["edge_sides"][j]),
            "wr_raw": _r(a["wr_raw"][j]), "games_ok": int(a["games_ok"][j]),
            "momentum": _r(a["momentum"][j]) if feats.momentum_ok else None,
            "usage_last": _r(a["usage_last"][j]) if feats.momentum_ok else None, "usage_prev": _r(a["usage_prev"][j]) if feats.momentum_ok else None,
            "release_recent": bool(a["release_recent"][j]),
            "released": max((d.isoformat() for d, f in feats.releases.get(cid, []) if d <= T_day), default=None),
            "sides_top": int(a["sides_top"][j]), "players_top": int(a["players_top"][j]),
            "last_change": None, "days_since_change": None,
            "z": {"edge": _r(sc["z_edge"][j], 4), "usage": _r(sc["z_usage"][j], 4), "momentum": _r(sc["z_momentum"][j], 4)},
            "nerf_score": _r(sc["nerf"][j], 4), "buff_score": _r(sc["buff"][j], 4),
            "direction": dirs[j] or None, "rank": rank[j], "tier": tier[j], "reasons": [],
        }
        lc = last_change(cid, events, T_day)
        if lc:
            row["last_change"] = lc
            row["days_since_change"] = (T_day - dt.date.fromisoformat(lc["date"])).days
        if dirs[j]:
            row["reasons"] = reasons(dirs[j], row["z"], row, avg, feats.momentum_ok)
        out["cards"].append(row)
    out["groups"] = [{"group": g["group"], "sides": g["sides"], "usage": {str(cid): _r(g["usage"][j], 4) for j, cid in enumerate(feats.card_ids)}}
                     for g in feats.groups]
    return out


def same_apart_from_time(a: dict, b: dict) -> bool:
    """Whether two lists are the same apart from when they were written and the track record carried along."""
    strip = lambda d: {k: v for k, v in d.items() if k not in ("generated_at", "track_record")}  # noqa: E731
    return strip(a) == strip(b)
