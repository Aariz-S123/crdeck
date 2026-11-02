"""Season-start fallback for `python -m crdeck collect`.

When a season starts, the Path of Legends leaderboards answer with no players (observed 2026-11-02: HTTP 200 and an
empty list on all 13 boards), so `collect` stops with "leaderboards returned no players". Battle logs still answer.
This fetches the logs of the players on the newest lists that held enough players into today's window, the same layout
`collect` writes. It sends only the same read-only requests through the same client, and skips what is cached.

It is a separate script because editing crdeck/collect.py would change the model cache fingerprint and force a retrain.
The scheduled collection (scripts/daily_collect.py) calls it by itself when it is needed.

    python scripts/collect_known_players.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crdeck.api import ApiClient, ApiError  # noqa: E402
from crdeck.collect import auto_window_id  # noqa: E402
from crdeck.config import Paths, collection_config  # noqa: E402

MIN_PLAYERS = 1000   # a list shorter than this is still refilling after a season start


def known_players(raw: Path, min_players: int = MIN_PLAYERS) -> tuple[list[str], str]:
    """Tags from the newest collection whose leaderboards listed at least `min_players`, in file order, without repeats."""
    for window in sorted((p for p in raw.iterdir() if (p / "leaderboard").is_dir()), key=lambda p: p.name, reverse=True):
        tags: list[str] = []
        for f in sorted((window / "leaderboard").glob("*.json")):
            body = json.loads(f.read_text(encoding="utf-8")).get("body")
            tags += [it["tag"] for it in (body.get("items", []) if isinstance(body, dict) else []) if it.get("tag")]
        tags = list(dict.fromkeys(tags))
        if len(tags) >= min_players:
            return tags, window.name
    raise ApiError(f"no leaderboard list with at least {min_players} players was found under data/raw")


def fetch() -> dict:
    tags, source = known_players(Paths.for_source("real").raw)
    window = auto_window_id()
    client = ApiClient(cfg=collection_config(), window_id=window)
    done = {"window_id": window, "players_from_window": source, "players": len(tags), "fetched": 0, "cached": 0, "not_found": 0, "errors": []}
    for i, tag in enumerate(tags):
        try:
            r = client.battlelog(tag)
        except ApiError as e:
            done["errors"].append(f"{tag}: {e}")
            continue
        if r.status == 404:
            done["not_found"] += 1
        done["cached" if r.from_cache else "fetched"] += 1
        if (i + 1) % 250 == 0:
            print(f"  {i + 1}/{len(tags)} logs", flush=True)
    done["requests_sent"], done["throttled_429"] = client.requests_sent, client.throttled
    return done


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2))
