"""Balance calendar and balance watch for the website (design, fixed before any result: docs/balance/DESIGN.md).

    python scripts/balance_watch.py                      today's list: web/balance_watch.json and a dated snapshot
    python scripts/balance_watch.py --cutoff 2026-11-16  the list for that cutoff (00:00 UTC of the day)
    python scripts/balance_watch.py --calendar-only      check config/balance/events.yaml, write web/balance_events.json
    python scripts/balance_watch.py --score 2026-12-01   score the frozen snapshot for that update (calendar event id)
    python scripts/balance_watch.py --pilot              the one retrospective pilot: 2026-10-19 from T = 2026-10-18

Every run checks the calendar and rewrites its website copy. A snapshot in docs/balance/snapshots/ is written once
and never overwritten: its git commit time is the proof of when the list existed. Scores go to
docs/balance/track_record.json and are shown on the page from the next run on.

Nothing here trains or changes a model, and no forecast or deck score reads the watch list.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.balance import events as ev  # noqa: E402
from crdeck.balance import features as ft  # noqa: E402
from crdeck.balance import score as sc  # noqa: E402
from crdeck.balance import watch  # noqa: E402
from crdeck.config import Paths  # noqa: E402
from crdeck.explore import data_status  # noqa: E402

WEB = ROOT / "web"
DOCS = ROOT / "docs" / "balance"
SNAPSHOTS = DOCS / "snapshots"
TRACK = DOCS / "track_record.json"
PILOT_EVENT, PILOT_CUTOFF = "2026-10-19", "2026-10-18"


def write_json(path: Path, body, indent=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_calendar(calendar: ev.Calendar, web: Path = WEB) -> Path:
    target = web / "balance_events.json"
    write_json(target, ev.web_json(calendar))
    return target


def load_data(verbose: bool):
    """The future-meta side table (crdeck.futuremeta.data.load): every parsed battle, cut by time inside features."""
    from crdeck.futuremeta import data as fm
    return fm.load(verbose=verbose)


def load_pilot_data(cutoff: pd.Timestamp, verbose: bool):
    """The same parsed battles, with one period that reaches back before the project's first collection. The usual
    side table starts a day before the first fetch, so it holds no battle from the pilot's window."""
    from crdeck.cards import load_card_table
    from crdeck.futuremeta import data as fm
    from crdeck.rules import DeckRules
    paths = Paths.for_source("real")
    cfg = fm.settings()
    bal = cfg.get("balance") or {}
    battles, dib, _, info = fm.parse_ranked(paths, verbose, tuple(bal.get("modes") or ["ranked"]))
    cards = load_card_table(fm.cache_dir(paths) / "cards.parquet")
    start = cutoff - pd.Timedelta(days=ft.WINDOW_DAYS + 1)
    periods = pd.DataFrame([{"window_id": "pilot", "start": start, "end": cutoff, "battles": 0, "merged": 1}])
    return fm.assemble(battles, dib, periods, None, cards, DeckRules.load(), None, int(bal.get("min_group_sides") or 0)), info


def snapshot_path(body: dict) -> Path:
    return SNAPSHOTS / f"{'pilot-' if body.get('pilot') else ''}{body['cutoff'][:10]}.json"


def save_snapshot(body: dict) -> tuple[Path, str]:
    """Write the dated snapshot once. An existing one is kept, whatever the new run says."""
    target = snapshot_path(body)
    frozen = {k: v for k, v in body.items() if k != "track_record"}
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        return target, "kept (identical)" if watch.same_apart_from_time(old, frozen) else "kept (an earlier, different snapshot exists and is never overwritten)"
    write_json(target, frozen)
    return target, "written"


def all_snapshots() -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(SNAPSHOTS.glob("*.json"))] if SNAPSHOTS.exists() else []


def add_track_row(row: dict) -> list[dict]:
    rows = read_json(TRACK, [])
    if any(r["event_id"] == row["event_id"] for r in rows):
        raise SystemExit(f"{row['event_id']} is already scored in {TRACK.relative_to(ROOT)}; a score is never redone")
    rows.append(row)
    rows.sort(key=lambda r: r["event_id"])
    write_json(TRACK, rows, indent=1)
    return rows


def build(cutoff: pd.Timestamp, calendar: ev.Calendar, *, pilot: bool, verbose: bool) -> dict:
    from crdeck.seasons import card_snapshots
    paths = Paths.for_source("real")
    data, _ = load_pilot_data(cutoff, verbose) if pilot else load_data(verbose)
    releases = ft.release_days(calendar, card_snapshots(paths))
    feats = ft.compute(data, calendar, cutoff, data.cards.ids, releases=releases, ignore_fetch=pilot)
    return watch.build(feats, calendar, data.cards, pilot=pilot, track_record=read_json(TRACK, []))


def describe(body: dict) -> str:
    w = body["window"]
    head = f"cutoff {body['cutoff']}, window {w['start'][:10]} to {w['end'][:10]} ({w['days']:g} days), {w['sides_top']:,} top sides from {w['players_top']:,} players: {body['status']}"
    if body["status"] == "insufficient":
        return f"{head} ({body['status_reason']})"
    tiers = {}
    for c in body["cards"]:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    return f"{head}; {w['battles_top']:,} rating-known battles; tiers {dict(sorted(tiers.items()))}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calendar-only", action="store_true", help="check the calendar and write web/balance_events.json, nothing else")
    ap.add_argument("--cutoff", help="cutoff day (YYYY-MM-DD, 00:00 UTC); default: today")
    ap.add_argument("--score", metavar="EVENT_ID", help="score the frozen snapshot for this calendar event")
    ap.add_argument("--pilot", action="store_true", help=f"rebuild the list for T = {PILOT_CUTOFF} and score {PILOT_EVENT} as a retrospective pilot")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()
    calendar = ev.load_events()
    target = write_calendar(calendar)
    print(f"calendar version {calendar.version}: {len(calendar)} events ({sum(e.is_balance for e in calendar)} with balance changes, "
          f"{sum(e.scoreable for e in calendar)} scoreable), newest {calendar[-1].id}; wrote {target.relative_to(ROOT)}")
    if args.calendar_only:
        return 0

    if args.score:
        event = next((e for e in calendar if e.id == args.score), None)
        if event is None or not event.scoreable:
            raise SystemExit(f"{args.score} is not a scoreable event in the calendar")
        snap = sc.pick_snapshot([s for s in all_snapshots() if not s.get("pilot")], event)
        if snap is None:
            print(f"{event.id}: not scored (no snapshot with a cutoff at least {sc.CUTOFF_GAP_HOURS} hours before it became public)")
            return 1
        row = sc.score_event(snap, event)
        add_track_row(row)
        print(f"{event.id} scored from the {snap['cutoff']} snapshot: nerf {row['nerf']['hits']} of {row['nerf']['labels_eligible']}, "
              f"buff {row['buff']['hits']} of {row['buff']['labels_eligible']} at K = {row['k']}; baselines {row['baselines']}")
        return 0

    if args.pilot:
        event = next(e for e in calendar if e.id == PILOT_EVENT)
        body = build(pd.Timestamp(PILOT_CUTOFF, tz="UTC"), calendar, pilot=True, verbose=not args.quiet)
        path, how = save_snapshot(body)
        print(f"pilot: {describe(body)}; snapshot {path.relative_to(ROOT)} {how}")
        if body["status"] == "insufficient":
            print("pilot: not scored (the status rule of DESIGN.md Section 3 is not met)")
            return 1
        row = sc.score_event(json.loads(path.read_text(encoding="utf-8")), event, pilot=True)
        add_track_row(row)
        print(f"pilot scored: nerf {row['nerf']['hits']} of {row['nerf']['labels_eligible']}, buff {row['buff']['hits']} of {row['buff']['labels_eligible']} "
              f"at K = {row['k']}; baselines {row['baselines']}")
        return 0

    cutoff = pd.Timestamp(args.cutoff, tz="UTC") if args.cutoff else pd.Timestamp(dt.datetime.now(dt.timezone.utc).date(), tz="UTC")
    body = build(cutoff, calendar, pilot=False, verbose=not args.quiet)
    write_json(WEB / "balance_watch.json", body)
    path, how = save_snapshot(body)
    data_status.update(WEB, "balance_watch", {"cutoff": body["cutoff"], "window_start": body["window"]["start"], "status": body["status"],
                                              "last_update": (body["calendar"]["last_event"] or {}).get("effective_date")})
    print(f"{describe(body)}\nwrote web/balance_watch.json; snapshot {path.relative_to(ROOT)} {how}; {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
