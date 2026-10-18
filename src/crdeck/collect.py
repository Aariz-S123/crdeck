"""Collection orchestration: decides what to fetch; api.py does the fetching.

gate():    /cards, the Path of Legends leaderboard and one battle log, plus a
           field inventory to copy into docs/api-notes.md ("observed" section).
collect(): battle logs for the top N leaderboard players in the current window.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .api import ApiClient, ApiError
from .config import collection_config


def _leaderboard_items(body: Any) -> list[dict]:
    if isinstance(body, dict):
        return list(body.get("items", []))
    return []


def _field_inventory(objs: list[dict]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for o in objs:
        c.update(o.keys())
    return dict(sorted(c.items()))


def gate(client: ApiClient | None = None) -> dict[str, Any]:
    """Run the spec section 6 gate and return observations (no key, no headers)."""
    cfg = collection_config()
    client = client or ApiClient(cfg=cfg)
    obs: dict[str, Any] = {"window_id": client.window_id}

    cards = client.cards()
    items = cards.body.get("items", []) if isinstance(cards.body, dict) else []
    obs["cards"] = {
        "file": str(cards.path),
        "n_items": len(items),
        "top_level_keys": sorted(cards.body.keys()) if isinstance(cards.body, dict) else type(cards.body).__name__,
        "item_fields": _field_inventory(items),
        "rarities": dict(Counter(str(i.get("rarity")) for i in items)),
        "n_with_maxEvolutionLevel": sum(1 for i in items if "maxEvolutionLevel" in i),
        "example_items": items[:2],
    }

    lb_cfg = cfg["leaderboard"]
    lb = client.pol_leaderboard(lb_cfg["location_id"], lb_cfg.get("season_id"), limit=min(int(lb_cfg["limit"]), 50))
    players = _leaderboard_items(lb.body)
    obs["leaderboard"] = {
        "file": str(lb.path),
        "status": lb.status,
        "n_items": len(players),
        "item_fields": _field_inventory(players),
        "example_item": players[:1],
    }
    if not players:
        obs["battlelog"] = {"error": "leaderboard returned no players; check endpoint in docs/api-notes.md"}
        return obs

    tag = players[0]["tag"]
    bl = client.battlelog(tag)
    battles = bl.body if isinstance(bl.body, list) else []
    sides = [s for b in battles for s in (b.get("team", []) + b.get("opponent", []))]
    deck_cards = [c for s in sides for c in s.get("cards", [])]
    obs["battlelog"] = {
        "file": str(bl.path),
        "status": bl.status,
        "n_battles": len(battles),
        "battle_fields": _field_inventory(battles),
        "battle_types": dict(Counter(str(b.get("type")) for b in battles)),
        "battle_time_examples": [b.get("battleTime") for b in battles[:3]],
        "side_fields": _field_inventory(sides),
        "deck_card_fields": _field_inventory(deck_cards),
        "cards_per_side": dict(Counter(len(s.get("cards", [])) for s in sides)),
        "evolutionLevel_values": dict(Counter(str(c.get("evolutionLevel")) for c in deck_cards)),
        "example_side_cards": sides[0].get("cards", []) if sides else [],
    }
    obs["requests_sent"] = client.requests_sent
    return obs


def collect(n_players: int | None = None, client: ApiClient | None = None, progress: bool = True) -> dict[str, Any]:
    """Fetch battle logs for the top players. Cached files are skipped, so it is resumable."""
    cfg = collection_config()
    client = client or ApiClient(cfg=cfg)
    lb_cfg = cfg["leaderboard"]
    lb = client.pol_leaderboard(lb_cfg["location_id"], lb_cfg.get("season_id"), limit=int(lb_cfg["limit"]))
    players = _leaderboard_items(lb.body)
    if not players:
        raise ApiError("leaderboard returned no players")
    if n_players:
        players = players[:n_players]
    summary = {"players": len(players), "fetched": 0, "cached": 0, "not_found": 0, "errors": []}
    for i, p in enumerate(players):
        try:
            r = client.battlelog(p["tag"])
        except ApiError as e:
            summary["errors"].append(f"{p['tag']}: {e}")
            continue
        if r.status == 404:
            summary["not_found"] += 1
        summary["cached" if r.from_cache else "fetched"] += 1
        if progress and (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(players)} logs")
    summary["requests_sent"] = client.requests_sent
    return summary
