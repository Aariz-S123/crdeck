"""What the crdeck-collect scheduled task runs once a day: the same collection as `python -m crdeck collect --window auto`, made to survive
the ways it failed in October and November 2026.

- A season start empties the leaderboards, so it falls back to the last good player list (scripts/collect_known_players.py). It does the same
  while they are still refilling, so one short list can't shrink a day's sample.
- A dropped connection doesn't end the day's collection: it waits and tries again, and finished logs are cached, so each try resumes.
- It writes its own log and, run with pythonw.exe, opens no console window that could be closed by accident.

It is a separate script because editing crdeck/collect.py would change the model cache fingerprint and force a retrain.

    .venv/Scripts/python scripts/daily_collect.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

ATTEMPTS, WAIT_SECONDS = 3, 20 * 60
MAX_ERRORS = 50          # more failed logs than this in a run: try again, the finished ones are cached
MIN_PLAYERS = 1000       # same floor as collect_known_players: a shorter list is still refilling
NO_PLAYERS = "leaderboards returned no players"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def one_attempt(collect_fn: Callable[[], dict], known_fn: Callable[[], dict]) -> dict:
    """The normal collection, then the last good list if the leaderboards are empty or still refilling."""
    from crdeck.api import ApiError
    try:
        summary = collect_fn()
    except ApiError as e:
        if NO_PLAYERS not in str(e):
            raise
        print(f"{NO_PLAYERS}: using the last good player list", flush=True)
        return known_fn()
    print(json.dumps(summary, indent=2), flush=True)
    if summary["players"] < MIN_PLAYERS:
        print(f"only {summary['players']} players listed: also fetching the last good player list", flush=True)
        return known_fn()
    return summary


def run(collect_fn: Callable[[], dict], known_fn: Callable[[], dict], sleep_fn: Callable[[float], None] = time.sleep,
        attempts: int = ATTEMPTS, wait_seconds: float = WAIT_SECONDS) -> int:
    """0 when a collection finished with few failed logs, 1 when every attempt fell short."""
    for attempt in range(1, attempts + 1):
        try:
            summary = one_attempt(collect_fn, known_fn)
            failed = len(summary.get("errors", []))
            if failed <= MAX_ERRORS:
                print(f"{now()} finished: {json.dumps({k: v for k, v in summary.items() if k != 'errors' and k != 'leaderboards'})}, {failed} failed", flush=True)
                return 0
            print(f"{now()} attempt {attempt}: {failed} logs failed", flush=True)
        except Exception as e:  # a dropped connection, a full disk, an API answer it can't read: all are worth one more try
            print(f"{now()} attempt {attempt} stopped: {type(e).__name__}: {e}", flush=True)
        if attempt < attempts:
            sleep_fn(wait_seconds)
    print(f"{now()} gave up after {attempts} attempts", flush=True)
    return 1


def main() -> int:
    os.chdir(ROOT)
    # pythonw.exe has no console, so stdout and stderr don't exist until they are pointed at the log
    log = open(ROOT / "data" / "collect_daily.log", "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = log
    print(f"\n{now()} daily collection started", flush=True)
    try:
        import collect_known_players
        from crdeck.collect import collect
        return run(lambda: collect(window_id="auto"), collect_known_players.fetch)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
