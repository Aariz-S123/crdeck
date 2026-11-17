"""The balance calendar (crdeck.balance.events) and the staleness flags (crdeck.balance.flags).

The flag cases live in tests/fixtures/balance_flags.json and are also run by tests/web/balance_test.cjs against
UI.balanceFlags, so Python and the website must answer the same way."""

import copy
import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from crdeck.balance import events as ev
from crdeck.balance import stale_flags

ROOT = Path(__file__).resolve().parents[1]
FIX = json.loads((Path(__file__).parent / "fixtures" / "balance_flags.json").read_text(encoding="utf8"))


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(ev.EVENTS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def calendar(cards):
    return ev.load_events(cards=cards)


def by_id(calendar, eid):
    return next(e for e in calendar if e.id == eid)


# ---------------------------------------------------------------- the real calendar

def test_real_calendar_loads_and_every_name_resolves(calendar, cards):
    assert calendar.version >= 1 and len(calendar) >= 2
    for e in calendar:
        for c in e.changes:
            assert cards[c.card_id].name == c.card
    days = [e.effective_date for e in calendar]
    assert days == sorted(days) and len(set(days)) == len(days)


def test_only_official_events_are_scoreable_and_they_have_directional_labels(calendar):
    for e in calendar:
        if e.scoreable:
            assert e.source_kind == "official" and not e.date_conflict
            assert any(c.label in ev.DIRECTIONAL for c in e.changes)
    assert {e.id for e in calendar if e.scoreable} >= {"2026-10-06", "2026-10-19"}


def test_october_19_labels_match_the_official_sections(calendar, cards):
    labels = {cards[c].name: lab for c, lab in ev.card_labels(by_id(calendar, "2026-10-19")).items()}
    assert {n for n, lab in labels.items() if lab == "nerf"} == {"Cannon Cart", "Dart Goblin", "Minion Giant", "Rune Giant"}
    assert {n for n, lab in labels.items() if lab == "buff"} == {"Electro Wizard", "Electro Dragon", "Flying Machine", "Void"}
    assert {n for n, lab in labels.items() if lab == "rework"} == {"Skeleton Barrel", "Skeletons"}


def test_october_6_counts_and_a_fix_next_to_a_nerf_stays_a_nerf(calendar, cards):
    labels = {cards[c].name: lab for c, lab in ev.card_labels(by_id(calendar, "2026-10-06")).items()}
    count = lambda lab: sum(v == lab for v in labels.values())  # noqa: E731
    assert (count("nerf"), count("buff"), count("rework"), count("fix")) == (7, 8, 1, 1)
    assert labels["Royal Ghost"] == "nerf"          # its second entry is a bug fix
    assert labels["Elite Barbarians"] == "fix"
    assert labels["Golden Knight"] == "rework"


def test_last_event_before(calendar):
    assert ev.last_event_before(calendar, dt.date(2026, 10, 18)).id == "2026-10-06"
    assert ev.last_event_before(calendar, dt.date(2026, 10, 19)).id == "2026-10-06"    # the day itself is not "before"
    assert ev.last_event_before(calendar, dt.datetime(2026, 10, 20, 3)).id == "2026-10-19"
    assert ev.last_event_before(calendar, dt.date(2026, 11, 16)).id == "2026-10-19"    # the Oct 27 release is not scoreable
    assert ev.last_event_before(calendar, dt.date(2026, 11, 16), scoreable_only=False).id == "2026-10-27"
    assert ev.last_event_before(calendar, dt.date(2026, 11, 16), scoreable_only=False, balance_only=True).id == "2026-10-19"
    assert ev.last_event_before(calendar, dt.date(2026, 10, 1), scoreable_only=True) is None
    assert ev.last_event_before(calendar, dt.date(2026, 10, 1), scoreable_only=False, balance_only=True).id == "2026-09-23"


def test_web_copy_round_trips_and_is_current(calendar):
    body = ev.web_json(calendar)
    back = ev.from_web_json(json.loads(json.dumps(body)))
    assert [(e.id, e.effective_date, e.scoreable) for e in back] == [(e.id, e.effective_date, e.scoreable) for e in calendar]
    assert [[(c.form, c.label) for c in e.changes] for e in back] == [[(c.form, c.label) for c in e.changes] for e in calendar]
    # the committed website copy must be the calendar's (ids differ from this test's made-up card ids, so compare the rest)
    web = json.loads((ROOT / "web" / "balance_events.json").read_text(encoding="utf-8"))
    strip = lambda b: [(e["id"], e["effective_date"], e["source_kind"], e["scoreable"], [(c["name"], c["form"], c["label"]) for c in e["changes"]]) for e in b["events"]]  # noqa: E731
    assert web["version"] == body["version"] and strip(web) == strip(body), "run: python scripts/balance_watch.py --calendar-only"


# ---------------------------------------------------------------- schema errors

def broken(raw, fn):
    body = copy.deepcopy(raw)
    fn(body)
    return body


@pytest.mark.parametrize("name, change, message", [
    ("unknown card", lambda b: b["events"][-1]["changes"][0].update(card="Not A Card"), "no card named"),
    ("name not exact", lambda b: b["events"][-1]["changes"][0].update(card="giant"), "exactly as in the card table"),
    ("bad label", lambda b: b["events"][-1]["changes"][0].update(label="tweak"), "label must be"),
    ("bad form", lambda b: b["events"][-1]["changes"][0].update(form="super"), "form must be"),
    ("form the card lacks", lambda b: b["events"][-1]["changes"][2].update(card="Bandit", form="evo"), "no evo form"),
    ("bad date", lambda b: b["events"][0].update(effective_date="next week"), "not an ISO date"),
    ("not ascending", lambda b: b["events"].reverse(), "ascending"),
    ("duplicate id", lambda b: b["events"][1].update(id=b["events"][0]["id"]), "unique"),
    ("community scoreable", lambda b: b["events"][0].update(scoreable=True), "official source"),
    ("unknown key", lambda b: b["events"][0].update(efective_date="2026-01-01"), "unknown keys"),
    ("missing source", lambda b: b["events"][0].pop("source_url"), "missing source_url"),
    ("no version", lambda b: b.pop("version"), "integer version"),
    ("same entry twice", lambda b: b["events"][-1]["changes"].append(dict(b["events"][-1]["changes"][-1])), "entered twice"),
])
def test_schema_errors_are_raised(raw, cards, name, change, message):
    with pytest.raises(ev.EventsError, match=message):
        ev.parse_events(broken(raw, change), cards)


def test_a_scoreable_event_needs_a_directional_label(raw, cards):
    def only_fixes(b):
        e = next(x for x in b["events"] if str(x["id"]) == "2026-10-19")
        for c in e["changes"]:
            c["label"] = "fix"
    with pytest.raises(ev.EventsError, match="nerf or buff"):
        ev.parse_events(broken(raw, only_fixes), cards)


def test_mixed_directions_in_one_update_become_a_rework(cards):
    a, b = cards.by_name("Skeleton Barrel"), cards.by_name("Knight")
    body = {"version": 1, "events": [{
        "id": "2030-01-01", "effective_date": dt.date(2030, 1, 1), "source_kind": "official", "source_url": "https://example.invalid/", "scoreable": True,
        "changes": [{"card": a.name, "form": "base", "label": "buff"}, {"card": a.name, "form": "evo", "label": "nerf"},
                    {"card": b.name, "form": "all", "label": "buff"}, {"card": b.name, "form": "evo", "label": "addition"}]}]}
    labels = ev.card_labels(ev.parse_events(body, cards)[0])
    assert labels == {a.card_id: "rework", b.card_id: "buff"}


# ---------------------------------------------------------------- staleness flags (shared with the website)

@pytest.mark.parametrize("case", FIX["cases"], ids=[c["name"] for c in FIX["cases"]])
def test_stale_flags_match_the_shared_fixture(case):
    events = ev.from_web_json(FIX["calendar"])
    assert stale_flags([tuple(e) for e in case["entries"]], events, tuple(case["window"])) == case["expect"]


def test_stale_flags_accept_dates_and_times(calendar, cards):
    dart = cards.by_name("Dart Goblin").card_id
    got = stale_flags([(dart, "base")], calendar, (dt.date(2026, 9, 1), dt.datetime(2026, 10, 27, 1, 15)))
    assert [(f["event_id"], f["label"], f["kind"]) for f in got] == [("2026-10-19", "nerf", "mixed")]
    later = stale_flags([(dart, "evo")], calendar, ("2026-09-01", "2026-10-10"))
    assert [(f["event_id"], f["kind"]) for f in later] == [("2026-10-19", "after")]


def test_nothing_that_scores_decks_imports_the_watch_list():
    """Watch-list outputs never feed forecasts or deck scores (BLUEPRINT 9.1): no trained module, forecast module or
    the counters module may import crdeck.balance.watch."""
    src = ROOT / "src" / "crdeck"
    for f in list(src.glob("*.py")) + list((src / "futuremeta").glob("*.py")):
        text = f.read_text(encoding="utf-8")
        assert "balance.watch" not in text and "balance import watch" not in text, f.name
