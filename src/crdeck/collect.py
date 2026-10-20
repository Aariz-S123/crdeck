"""Collection orchestration: decides what to fetch; api.py does the fetching.

gate():    /cards, the Path of Legends leaderboard and one battle log, plus a
           field inventory to copy into docs/api-notes.md ("observed" section).
collect(): battle logs for the top N leaderboard players in the current window.
collect_arenas(): battle logs for players in every Trophy Road arena (clan search, then
           ladder opponents), stored apart from the leaderboard logs.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api import ApiClient, ApiError
from .config import PROJECT_ROOT, collection_config
from .parse import ModeRules, mode_groups

# Battle-deck card fields known before 2026. Anything else seen in a real log is
# listed in the observed notes as a candidate marker (e.g. for Hero form).
KNOWN_DECK_CARD_FIELDS = {
    "name", "id", "level", "starLevel", "evolutionLevel", "maxLevel", "maxEvolutionLevel",
    "rarity", "elixirCost", "iconUrls", "count", "used",
}
OBSERVED_NOTES = PROJECT_ROOT / "docs" / "api-notes-observed.md"


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
    obs["throttled_429"] = client.throttled
    obs["server_errors_5xx"] = client.server_errors
    obs["unknown_deck_card_fields"] = sorted(set(obs["battlelog"]["deck_card_fields"]) - KNOWN_DECK_CARD_FIELDS)
    obs["config_suggestions"] = suggest_config(obs)
    return obs


def suggest_config(obs: dict[str, Any]) -> list[str]:
    """Config changes implied by an observed gate run (printed, never applied automatically)."""
    out = []
    bl = obs.get("battlelog", {})
    types = bl.get("battle_types", {})
    ranked = [t for t in types if "legend" in t.lower() or "ranked" in t.lower()]
    if types and "pathOfLegend" not in types:
        out.append(f"battles.battle_types: 'pathOfLegend' not seen; observed types {types}; candidates {ranked}")
    fields = bl.get("deck_card_fields", {})
    if fields and "evolutionLevel" not in fields:
        out.append("form_resolution.evo_field: 'evolutionLevel' not seen on battle cards; find the evolution marker")
    unknown = obs.get("unknown_deck_card_fields", [])
    if unknown:
        out.append(f"form_resolution.hero_field: new battle-card fields {unknown}; check whether one marks Hero form")
    cps = bl.get("cards_per_side", {})
    if cps and set(cps) != {8}:
        out.append(f"cards per side not always 8: {cps}")
    if obs.get("leaderboard", {}).get("n_items", 0) == 0:
        out.append("leaderboard empty: check leaderboard endpoint / season_id")
    return out


def write_observed_notes(obs: dict[str, Any], path: Path = OBSERVED_NOTES) -> Path:
    """Write the gate observations as markdown: the 'observed in my calls' half of api-notes."""
    import json

    def block(x) -> str:
        return "```json\n" + json.dumps(x, indent=1, default=str)[:6000] + "\n```"

    c, lb, bl = obs.get("cards", {}), obs.get("leaderboard", {}), obs.get("battlelog", {})
    lines = [
        "# API notes: observed in my calls",
        "",
        f"Generated by `python -m crdeck gate` at {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}, window `{obs.get('window_id')}`.",
        "No key or headers are recorded. Compare with the documented column in `api-notes.md`.",
        "",
        "## Summary",
        "",
        f"- `/cards`: {c.get('n_items')} items; top-level keys {c.get('top_level_keys')}; rarities {c.get('rarities')}; "
        f"{c.get('n_with_maxEvolutionLevel')} items carry `maxEvolutionLevel`.",
        f"- Leaderboard: HTTP {lb.get('status')}, {lb.get('n_items')} players.",
        f"- Battle log: HTTP {bl.get('status')}, {bl.get('n_battles')} battles; types {bl.get('battle_types')}; "
        f"cards per side {bl.get('cards_per_side')}.",
        f"- Time format examples: {bl.get('battle_time_examples')}",
        f"- `evolutionLevel` values on battle cards: {bl.get('evolutionLevel_values')}",
        f"- Battle-card fields not known before 2026 (Hero-form candidates): {obs.get('unknown_deck_card_fields') or 'none'}",
        f"- Requests sent {obs.get('requests_sent')}; HTTP 429 seen {obs.get('throttled_429')}; 5xx seen {obs.get('server_errors_5xx')}.",
        "",
        "## Suggested config changes",
        "",
        *([f"- {s}" for s in obs.get("config_suggestions", [])] or ["- none"]),
        "",
        "## Field inventories (field: count of objects carrying it)",
        "",
        "/cards items:", block(c.get("item_fields")),
        "Leaderboard items:", block(lb.get("item_fields")),
        "Battles:", block(bl.get("battle_fields")),
        "Battle sides:", block(bl.get("side_fields")),
        "Battle deck cards:", block(bl.get("deck_card_fields")),
        "",
        "## Examples",
        "",
        "/cards items:", block(c.get("example_items")),
        "One side's deck cards:", block(bl.get("example_side_cards")),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def auto_window_id(now: datetime | None = None) -> str:
    """A window id per UTC day, e.g. '2026-10-18'. Battle logs only hold recent battles,
    so collecting once per day under a new window id accumulates history."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def collect(n_players: int | None = None, client: ApiClient | None = None, progress: bool = True,
            window_id: str | None = None) -> dict[str, Any]:
    """Fetch battle logs for the top players. Cached files are skipped, so it is resumable."""
    cfg = collection_config()
    if window_id == "auto":
        window_id = auto_window_id()
    client = client or ApiClient(cfg=cfg, window_id=window_id)
    # the card list and season list on every collection, so new cards / Evolutions / Heroes are
    # spotted the day they appear (crdeck.seasons.card_snapshots)
    snapshot_errors = []
    for fetch in (client.cards, client.seasons):
        try:
            fetch()
        except ApiError as e:
            if "403" in str(e):
                raise
            snapshot_errors.append(str(e))
    lb_cfg = cfg["leaderboard"]
    boards = [(str(lb_cfg["location_id"]), int(lb_cfg["limit"]))]
    boards += [(str(k), int(v)) for k, v in (lb_cfg.get("extra_locations") or {}).items()]
    players, seen, per_board = [], set(), {}
    for loc, limit in boards:
        try:
            lb = client.pol_leaderboard(loc, lb_cfg.get("season_id") if loc == str(lb_cfg["location_id"]) else None, limit=limit)
        except ApiError as e:
            per_board[loc] = f"error: {e}"
            continue
        items = _leaderboard_items(lb.body)
        new = [p for p in items if p.get("tag") and p["tag"] not in seen]
        seen.update(p["tag"] for p in new)
        players += new
        per_board[loc] = f"{len(items)} listed, {len(new)} new"
    if not players:
        raise ApiError("leaderboards returned no players")
    if n_players:
        players = players[:n_players]
    summary = {"window_id": client.window_id, "leaderboards": per_board, "players": len(players),
               "fetched": 0, "cached": 0, "not_found": 0, "errors": list(snapshot_errors)}
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
    summary["throttled_429"] = client.throttled
    return summary


def _body_items(r) -> list[dict]:
    return list(r.body.get("items", [])) if r.status == 200 and isinstance(r.body, dict) else []


def collect_arenas(client: ApiClient | None = None, progress: bool = True, window_id: str | None = None) -> dict[str, Any]:
    """Battle logs for up to `players_per_arena` players in each Trophy Road arena.

    1. Clan pass: GET /clans by name word (config arena_sample.clan_search), then member lists,
       lowest clan score per member first. A member goes to the arena named in its own `arena` field; when that field is
       missing or unknown, to the arena whose trophy floor (config) its trophies reach.
    2. Opponent pass: for arenas still short, the ladder opponents in the logs fetched so far,
       placed in the arena the battle was played in.
    Logs are cached under <window>/battlelog_arena/. Stops at `max_requests` network requests,
    and at once on an API error that affects every call (wrong IP, bad key)."""
    cfg = collection_config()
    acfg = cfg["arena_sample"]
    if window_id == "auto":
        window_id = auto_window_id()
    client = client or ApiClient(cfg=cfg, window_id=window_id)
    skip = set(acfg.get("skip_arenas") or [])
    floors = sorted((a["min_trophies"], a["name"]) for a in mode_groups(cfg, "trophy_road"))
    arenas = [a for a in mode_groups(cfg, "trophy_road") if a["name"] not in skip]
    target, budget = int(acfg["players_per_arena"]), int(acfg["max_requests"])
    picked: dict[str, list[str]] = {a["name"]: [] for a in arenas}
    source: dict[str, Counter] = {a["name"]: Counter() for a in arenas}
    seen: set[str] = set()
    how = Counter()
    rules = ModeRules.from_collection(cfg)
    summary: dict[str, Any] = {"window_id": client.window_id, "players_per_arena": target, "errors": []}

    def arena_of(member: dict) -> str | None:
        name = (member.get("arena") or {}).get("name")
        if name in picked:
            how["member arena field"] += 1
            return name
        t = member.get("trophies")
        if not isinstance(t, (int, float)):
            how["no arena, no trophies"] += 1
            return None
        how["trophy floor (config)"] += 1
        return [n for f, n in floors if f <= t][-1] if t >= floors[0][0] else None
    # (an arena in skip_arenas is not a key of `picked`, so add() ignores it)

    def add(tag: str | None, arena: str | None, via: str) -> None:
        if tag and arena in picked and tag not in seen and len(picked[arena]) < target:
            picked[arena].append(tag)
            seen.add(tag)
            source[arena][via] += 1

    full = lambda: all(len(v) >= target for v in picked.values())  # noqa: E731
    spent = lambda: client.requests_sent >= budget  # noqa: E731
    fetched: dict[str, Any] = {}

    def fetch_logs() -> None:
        for arena, tags in picked.items():
            for tag in tags:
                if tag in fetched or spent():
                    continue
                try:
                    fetched[tag] = client.battlelog(tag, folder="battlelog_arena")
                except ApiError as e:
                    if "403" in str(e):
                        raise
                    summary["errors"].append(f"{tag}: {e}")
                    fetched[tag] = None

    # 1. clan pass: gather clans by name word, then read member lists, low score per member first
    cs = acfg["clan_search"]
    clans: dict[str, dict] = {}
    for word in cs["names"]:
        after = None
        for _ in range(int(cs["max_pages"])):
            if spent():
                break
            r = client.clan_search({"name": word, "minMembers": int(cs["min_members"]), "limit": int(cs["limit"])}, after)
            for c in _body_items(r):
                if c.get("tag"):
                    clans.setdefault(c["tag"], c)
            after = ((r.body.get("paging") or {}).get("cursors") or {}).get("after") if isinstance(r.body, dict) else None
            if not after:
                break
    summary["clans_found"] = len(clans)
    if progress:
        print(f"  {len(clans)} clans found by name search")
    order = sorted(clans.values(), key=lambda c: (c.get("clanScore") or 0) / max(1, c.get("members") or 1))
    visited = stall = 0
    max_reads, max_stall = int(acfg.get("max_clan_reads", 10**9)), int(acfg.get("stall_clans", 10**9))
    for clan in order:
        if full() or spent() or visited >= max_reads or stall >= max_stall:
            break
        placed_before = len(seen)
        try:
            members = client.clan_members(clan["tag"])
        except ApiError as e:
            if "403" in str(e):
                raise
            summary["errors"].append(f"clan {clan.get('tag')}: {e}")
            continue
        visited += 1
        for m in _body_items(members):
            add(m.get("tag"), arena_of(m), "clan member")
        stall = 0 if len(seen) > placed_before else stall + 1
        if progress and visited % 100 == 0:
            print(f"  {visited} clans read: {sum(len(v) for v in picked.values())} players placed")
    summary["clans_read"] = visited
    summary["clan_pass_stopped_by"] = ("all arenas full" if full() else "request budget" if spent() else
                                       "max_clan_reads" if visited >= max_reads else "no new players" if stall >= max_stall else "clans exhausted")
    summary["skipped_arenas"] = sorted(skip)
    fetch_logs()

    # 2. opponent pass: ladder opponents from logs already fetched, until no arena gains a player
    rounds = 0
    while acfg.get("snowball", True) and not full() and not spent():
        before = sum(len(v) for v in picked.values())
        for tag, r in list(fetched.items()):
            if r is None or r.status != 200 or not isinstance(r.body, list):
                continue
            for b in r.body:
                if rules.assign(b) != "trophy_road":
                    continue
                arena = (b.get("arena") or {}).get("name")
                if arena in picked and len(picked[arena]) < target:
                    for side in b.get("opponent", []) + b.get("team", []):
                        add(side.get("tag"), arena, "ladder opponent")
        rounds += 1
        if sum(len(v) for v in picked.values()) == before:
            break
        fetch_logs()
        if progress:
            print(f"  opponent round {rounds}: {sum(len(v) for v in picked.values())} players placed")

    summary["arenas"] = [{"arena": a["name"], "players": len(picked[a["name"]]), **dict(source[a["name"]]),
                          "logs": sum(1 for t in picked[a["name"]] if fetched.get(t) is not None and fetched[t].status == 200)}
                         for a in arenas]
    summary["short_arenas"] = [a["name"] for a in arenas if len(picked[a["name"]]) < target]
    summary["arena_assigned_by"] = dict(how)
    summary["opponent_rounds"] = rounds
    summary["requests_sent"] = client.requests_sent
    summary["stopped_by_request_budget"] = spent()
    summary["throttled_429"] = client.throttled
    return summary
