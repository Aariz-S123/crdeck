"""The balance calendar (config/balance/events.yaml), loaded and checked.

Labels come from balance notes, never from battle data: the official card list (GET /cards) has no card stats, so a
buff or nerf can't be read from the API. Each event is one update; each change is one entry of its notes.

Assumption: an entry that names no form (`form: all`) reaches every form of the card. The official notes say base
changes carry over "most of the time". Test: compare the base and special forms' numbers before and after an update
once two updates have battles on both sides.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..cards import CardTable
from ..config import CONFIG_DIR

EVENTS_FILE = CONFIG_DIR / "balance" / "events.yaml"
LABELS = ("nerf", "buff", "rework", "fix", "addition")
DIRECTIONAL = ("nerf", "buff")              # what a watch list can hit
BALANCE_LABELS = ("nerf", "buff", "rework")  # changes to how a card plays, as opposed to a fix or a release
FORMS = ("all", "base", "evo", "hero")
SOURCE_KINDS = ("official", "community")
EVENT_KEYS = {"id", "announced", "effective_date", "effective_time_utc", "source_kind", "source_url", "date_conflict",
              "alt_dates", "scoreable", "scoreable_override", "partial", "note", "changes"}
CHANGE_KEYS = {"card", "card_id", "form", "label", "stats", "reason"}


class EventsError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    card_id: int
    card: str
    form: str
    label: str
    stats: tuple[dict, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class Event:
    id: str
    effective_date: dt.date
    source_kind: str
    source_url: str
    scoreable: bool
    changes: tuple[Change, ...]
    announced: dt.date | None = None
    effective_time_utc: str | None = None
    date_conflict: bool = False
    alt_dates: tuple[dt.date, ...] = ()
    partial: bool = False
    note: str | None = None

    @property
    def first_public(self) -> dt.date:
        """The earliest day the changes were public: the announcement when one is recorded, else the effective day."""
        return min(self.announced, self.effective_date) if self.announced else self.effective_date

    @property
    def is_balance(self) -> bool:
        """Whether any entry changed how a card plays (a nerf, buff or rework), not only fixes and releases."""
        return any(c.label in BALANCE_LABELS for c in self.changes)


@dataclass(frozen=True)
class Calendar:
    version: int
    events: tuple[Event, ...]
    checked_on: dt.date | None = None
    checked_note: str | None = None

    def __iter__(self):
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, i):
        return self.events[i]


def _date(v: Any, where: str) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError as e:
        raise EventsError(f"{where}: not an ISO date: {v!r}") from e


def _change(raw: Any, cards: CardTable, where: str) -> Change:
    if not isinstance(raw, dict):
        raise EventsError(f"{where}: a change must be a mapping, got {raw!r}")
    extra = set(raw) - CHANGE_KEYS
    if extra:
        raise EventsError(f"{where}: unknown keys {sorted(extra)}")
    name = raw.get("card")
    if not name:
        raise EventsError(f"{where}: a change needs a card name")
    try:
        card = cards.by_name(name)
    except KeyError as e:
        raise EventsError(f"{where}: no card named {name!r} in the card table") from e
    if card.name != name:
        raise EventsError(f"{where}: card name {name!r} must be written exactly as in the card table: {card.name!r}")
    form, label = raw.get("form"), raw.get("label")
    if form not in FORMS:
        raise EventsError(f"{where} ({name}): form must be one of {FORMS}, got {form!r}")
    if label not in LABELS:
        raise EventsError(f"{where} ({name}): label must be one of {LABELS}, got {label!r}")
    # a release may name a form the label file doesn't list yet; every other entry must name a form the card has
    if label != "addition" and form != "all" and form not in card.allowed_forms():
        raise EventsError(f"{where} ({name}): the card table has no {form} form of this card")
    stats = raw.get("stats") or []
    if not isinstance(stats, list) or any(not isinstance(s, dict) or "stat" not in s for s in stats):
        raise EventsError(f"{where} ({name}): stats must be a list of {{stat, before, after}}")
    return Change(card_id=card.card_id, card=card.name, form=form, label=label, stats=tuple(stats), reason=raw.get("reason"))


def _event(raw: Any, cards: CardTable, i: int) -> Event:
    if not isinstance(raw, dict):
        raise EventsError(f"event {i}: must be a mapping")
    extra = set(raw) - EVENT_KEYS
    if extra:
        raise EventsError(f"event {i}: unknown keys {sorted(extra)}")
    for k in ("id", "effective_date", "source_kind", "source_url", "scoreable", "changes"):
        if k not in raw or raw[k] in (None, ""):
            raise EventsError(f"event {i}: missing {k}")
    eid = str(raw["id"])
    where = f"event {eid}"
    kind = raw["source_kind"]
    if kind not in SOURCE_KINDS:
        raise EventsError(f"{where}: source_kind must be one of {SOURCE_KINDS}, got {kind!r}")
    scoreable, conflict = raw["scoreable"], raw.get("date_conflict", False)
    if not isinstance(scoreable, bool) or not isinstance(conflict, bool):
        raise EventsError(f"{where}: scoreable and date_conflict must be true or false")
    if scoreable and kind != "official" and not raw.get("scoreable_override"):
        raise EventsError(f"{where}: only an official source can be scoreable (or give scoreable_override with the reason)")
    if scoreable and conflict:
        raise EventsError(f"{where}: an event with conflicting dates can't be scored")
    if not isinstance(raw["changes"], list):
        raise EventsError(f"{where}: changes must be a list")
    changes = tuple(_change(c, cards, f"{where}, change {j}") for j, c in enumerate(raw["changes"]))
    seen = set()
    for c in changes:
        key = (c.card_id, c.form, c.label)
        if key in seen:
            raise EventsError(f"{where}: {c.card} ({c.form}, {c.label}) is entered twice")
        seen.add(key)
    if scoreable and not any(c.label in DIRECTIONAL for c in changes):
        raise EventsError(f"{where}: a scoreable event needs at least one nerf or buff")
    return Event(
        id=eid, effective_date=_date(raw["effective_date"], where), source_kind=kind, source_url=str(raw["source_url"]),
        scoreable=scoreable, changes=changes, announced=None if raw.get("announced") is None else _date(raw["announced"], where),
        effective_time_utc=None if raw.get("effective_time_utc") is None else str(raw["effective_time_utc"]),
        date_conflict=conflict, alt_dates=tuple(_date(d, where) for d in raw.get("alt_dates") or []),
        partial=bool(raw.get("partial", False)), note=raw.get("note"))


def parse_events(body: Any, cards: CardTable) -> Calendar:
    """Check a loaded calendar and return it. Raises EventsError on the first problem."""
    if not isinstance(body, dict) or not isinstance(body.get("version"), int):
        raise EventsError("the calendar needs an integer version")
    extra = set(body) - {"version", "checked_on", "checked_note", "events"}
    if extra:
        raise EventsError(f"unknown top-level keys {sorted(extra)}")
    if not isinstance(body.get("events"), list):
        raise EventsError("the calendar needs an events list")
    events = tuple(_event(e, cards, i) for i, e in enumerate(body["events"]))
    ids = [e.id for e in events]
    if len(set(ids)) != len(ids):
        raise EventsError(f"event ids must be unique: {sorted(i for i in set(ids) if ids.count(i) > 1)}")
    for a, b in zip(events, events[1:]):
        if not a.effective_date < b.effective_date:
            raise EventsError(f"events must be in ascending date order, one per day: {a.id} then {b.id}")
    checked = body.get("checked_on")
    return Calendar(version=body["version"], events=events, checked_on=None if checked is None else _date(checked, "checked_on"),
                    checked_note=body.get("checked_note"))


def load_events(path: str | Path = EVENTS_FILE, cards: CardTable | None = None) -> Calendar:
    """The calendar, checked, oldest event first. `cards` resolves names to card ids; by default the card table the
    project already built (the newest one saved for the future-meta page, else the trained one)."""
    if cards is None:
        cards = default_card_table()
    with Path(path).open(encoding="utf-8") as f:
        body = yaml.safe_load(f)
    return parse_events(body, cards)


def default_card_table() -> CardTable:
    from ..cards import load_card_table
    from ..config import Paths
    processed = Paths.for_source("real").processed
    newest = processed / "future_meta" / "cards.parquet"
    return load_card_table(newest if newest.exists() else processed / "cards.parquet")


def card_labels(event: Event) -> dict[int, str]:
    """card_id -> one label for this event. A card with entries in both directions, or any rework entry, is a
    `rework`. A fix or a release next to a nerf or buff doesn't change the direction (Royal Ghost on 2026-10-06 is a
    nerf with a separate bug fix). A card with only fixes is `fix`; with a release and no balance change, `addition`."""
    by_card: dict[int, set[str]] = {}
    for c in event.changes:
        by_card.setdefault(c.card_id, set()).add(c.label)
    out = {}
    for cid, labels in by_card.items():
        if "rework" in labels or {"nerf", "buff"} <= labels:
            out[cid] = "rework"
        elif "nerf" in labels:
            out[cid] = "nerf"
        elif "buff" in labels:
            out[cid] = "buff"
        elif "addition" in labels:
            out[cid] = "addition"
        else:
            out[cid] = "fix"
    return out


def last_event_before(events, t: dt.date | dt.datetime, scoreable_only: bool = True, balance_only: bool = False) -> Event | None:
    """The newest event whose effective date is before the day of `t`. `scoreable_only` keeps official, scoreable
    updates; `balance_only` keeps any event with a nerf, buff or rework, whatever its source (what a data window has
    to start after)."""
    day = t.date() if isinstance(t, dt.datetime) else t
    best = None
    for e in events:
        if e.effective_date >= day:
            continue
        if scoreable_only and not e.scoreable:
            continue
        if balance_only and not e.is_balance:
            continue
        best = e
    return best


def from_web_json(body: dict) -> Calendar:
    """The calendar back from its website copy (card ids are already resolved there, so no card table is needed).
    Stats, reasons and notes are not in that copy."""
    events = tuple(Event(
        id=str(e["id"]), effective_date=_date(e["effective_date"], f"event {e['id']}"), source_kind=e.get("source_kind", "community"),
        source_url=e.get("source_url", ""), scoreable=bool(e.get("scoreable", False)), date_conflict=bool(e.get("date_conflict", False)),
        partial=bool(e.get("partial", False)),
        changes=tuple(Change(card_id=int(c["card_id"]), card=str(c.get("name", c["card_id"])), form=c["form"], label=c["label"]) for c in e["changes"]),
    ) for e in body["events"])
    checked = body.get("checked_on")
    return Calendar(version=int(body["version"]), events=events, checked_on=None if checked is None else _date(checked, "checked_on"))


def web_json(calendar: Calendar) -> dict:
    """The copy of the calendar the website reads (web/balance_events.json)."""
    return {
        "version": calendar.version,
        "checked_on": None if calendar.checked_on is None else calendar.checked_on.isoformat(),
        "events": [{
            "id": e.id, "effective_date": e.effective_date.isoformat(), "source_url": e.source_url, "source_kind": e.source_kind,
            "date_conflict": e.date_conflict, "scoreable": e.scoreable, "partial": e.partial,
            "changes": [{"card_id": c.card_id, "name": c.card, "form": c.form, "label": c.label} for c in e.changes],
        } for e in calendar.events],
    }
