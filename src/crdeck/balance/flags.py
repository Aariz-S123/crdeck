"""Which cards of a deck changed while, or after, a model's numbers were measured.

This is the state `crdeck.explain.STALE_AFTER_BALANCE` names. It is advisory, like a deck warning: it never changes a
score. The website's twin is `UI.balanceFlags` in web/common.js; tests/fixtures/balance_flags.json holds cases both
must answer the same way.

Rule, for each deck card and each calendar entry for that card (a nerf, buff or rework; fixes and releases are left
out) whose form is `all` or the deck card's own form:
- the update's day is before the window's first day: no flag (every battle was played after the change);
- it is inside the window, first and last day included: `mixed` (battles from before and after are pooled);
- it is after the window's last day: `after` (the numbers were measured before the change).

Assumption: the window's days are UTC days and an update's hour is unknown, so an update on a boundary day counts as
inside. Test: when notes give an hour, compare with the battle times on that day.
"""

from __future__ import annotations

import datetime as dt

from .events import BALANCE_LABELS


def _day(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def stale_flags(entries: list[tuple[int, str]], events, window: tuple) -> list[dict]:
    """entries: (card_id, form) of each deck card. events: the calendar. window: (first day, last day) of the battles
    the numbers come from. Returns one dict per flagged entry, in deck order, then oldest update first."""
    first, last = _day(window[0]), _day(window[1])
    out = []
    for card_id, form in entries:
        for ev in events:
            day = ev.effective_date
            if day < first:
                continue
            for ch in ev.changes:
                if ch.card_id != int(card_id) or ch.label not in BALANCE_LABELS or ch.form not in ("all", form):
                    continue
                out.append({"card_id": int(card_id), "form": form, "event_id": ev.id, "date": day.isoformat(),
                            "label": ch.label, "kind": "mixed" if day <= last else "after"})
    return out
