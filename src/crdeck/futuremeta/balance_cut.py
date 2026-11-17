"""Regime cut for the usage forecast (docs/fable-brief/BLUEPRINT.md 9.1, item 5). Off unless settings say
`forecast.balance_cut: true`.

A card whose numbers changed in a balance update (a nerf, buff or rework in config/balance/events.yaml, for its own form
or for every form) plays differently afterwards, so the hours before the change say little about its use after it.
With the cut on, such a card's hourly history keeps only the hours from 24 hours after the update's day began (the
hour of an update is unknown, so its whole day is dropped). A card left with fewer than MIN_HOURS known hours is not
forecast at that origin: "changed on DATE, not enough new history".

Announced changes never alter a forecast number any other way, and the balance watch list is never read here.

Assumption: an update reaches every form of a card unless the notes name a form (as in crdeck.balance.events). Test:
the backtest with and without the cut, reported side by side, as the blueprint asks, before the setting is turned on.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from ..balance.events import BALANCE_LABELS

MIN_HOURS = 48


def cut_hours(keys: list[str], events, first_hour_time: np.datetime64, moment: np.datetime64, n_hours: int) -> dict[int, int]:
    """series index -> the first hour index (relative to the window's first hour) that may be used, for every series
    with a balance change whose day falls inside the window. Series without one are left out."""
    out: dict[int, int] = {}
    t0 = np.datetime64(first_hour_time, "h")
    for i, k in enumerate(keys):
        if ":" not in k:
            continue                      # deck styles have no card to match
        cid, form = k.split(":")
        for e in events:
            if not any(c.card_id == int(cid) and c.label in BALANCE_LABELS and c.form in ("all", form) for c in e.changes):
                continue
            start = np.datetime64(e.effective_date.isoformat(), "h") + np.timedelta64(24, "h")
            if np.datetime64(e.effective_date.isoformat(), "h") >= np.datetime64(moment, "h"):
                continue                  # not known at this origin
            h = int((start - t0) // np.timedelta64(1, "h"))
            if h > 0:
                out[i] = max(out.get(i, 0), min(h, n_hours))
    return out


def apply(hourly: np.ndarray, scored: np.ndarray, keys: list[str], events, first_hour_time, moment, min_hours: int = MIN_HOURS):
    """(hourly, scored, cut) with hours before each change set to NaN, and series with too little new history unscored.
    `cut`: {key: {"from_hour": h, "kept_hours": n, "forecast": bool}} for every series the cut touched."""
    hourly, scored = hourly.copy(), scored.copy()
    info = {}
    for i, h in cut_hours(keys, events, first_hour_time, moment, hourly.shape[0]).items():
        hourly[:h, i] = np.nan
        kept = int(np.isfinite(hourly[:, i]).sum())
        ok = kept >= min_hours
        if not ok:
            scored[i] = False
        info[keys[i]] = {"from_hour": int(h), "kept_hours": kept, "forecast": bool(ok)}
    return hourly, scored, info
