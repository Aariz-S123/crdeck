"""Upcoming seasons: what can be measured now, and what a season prediction will need.

Everything here is computed from collected data. Nothing predicts a future season yet:

- card_snapshots(): the official card list saved on each collection (GET /cards), and which
  cards, Evolutions and Heroes appeared between snapshots. A card released next season has
  no battles, so the builder lists it as "not played here" until it collects games.
- meta_decks(): the most-played ranked decks of leaderboard players in each collection
  period, with usage share, win rate and 90% intervals, and the change between the last
  two periods. Measured, not forecast.
- season_status(): how many seasons the data covers. A season-to-season prediction needs
  at least MIN_SEASONS seasons (fit the change on two, test it on a third) and must beat
  "no change" on a held-out season before it is shown. Until then it is locked.

Assumption (stated on the site): a battle's season is the calendar month of its battle time.
GET /locations/global/seasons lists season ids like "2026-09" but no start or end dates, so a
few days around each boundary can be assigned to the neighbouring season. Test: find the
Path of Legends rating reset in the battles and compare it with the month boundary.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .forecast import collection_periods

MIN_SEASONS = 3                 # fit on two season-to-season changes' worth of data, test on a third season
MIN_SEASON_BATTLES = 10_000     # leaderboard ranked battles for a month to count as a covered season
TOP_DECKS = 12
MIN_DECK_GAMES = 100            # appearances across all periods for a deck to be listed
Z90 = 1.6448536269514722


def _forms(item: dict) -> list[str]:
    bits = int(item.get("maxEvolutionLevel") or 0)
    return ["base"] + (["evo"] if bits & 1 else []) + (["hero"] if bits & 2 else [])


def card_snapshots(paths) -> dict:
    """Every saved card list, oldest first, and what was added between consecutive ones."""
    snaps = []
    for f in sorted(Path(paths.raw).glob("*/cards/cards.json")):
        w = json.loads(f.read_text(encoding="utf-8"))
        if w.get("status") != 200 or not isinstance(w.get("body"), dict):
            continue
        items = w["body"].get("items", [])
        forms = {f"{it['id']}:{fm}": it["name"] for it in items for fm in _forms(it)}
        snaps.append({"window_id": f.parent.parent.name, "fetched_at": w.get("fetched_at", ""), "cards": len(items),
                      "card_forms": len(forms), "_forms": forms})
    snaps.sort(key=lambda s: s["fetched_at"])
    changes = []
    for prev, cur in zip(snaps, snaps[1:]):
        added = sorted(set(cur["_forms"]) - set(prev["_forms"]))
        removed = sorted(set(prev["_forms"]) - set(cur["_forms"]))
        if added or removed:
            changes.append({"from": prev["fetched_at"], "to": cur["fetched_at"],
                            "added": [{"key": k, "name": cur["_forms"][k], "form": k.split(":")[1]} for k in added],
                            "removed": [{"key": k, "name": prev["_forms"][k], "form": k.split(":")[1]} for k in removed]})
    return {"snapshots": [{k: v for k, v in s.items() if k != "_forms"} for s in snaps], "changes": changes}


def _wilson(k: float, n: float) -> list[float]:
    if n <= 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + Z90 ** 2 / n
    c = (p + Z90 ** 2 / (2 * n)) / d
    h = Z90 * math.sqrt(p * (1 - p) / n + Z90 ** 2 / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def _leaderboard_ranked(battles: pd.DataFrame, dib: pd.DataFrame) -> pd.DataFrame:
    """One row per side of each OK ranked battle from the leaderboard sample: battle_time, deck_key, won."""
    keep = (battles["mode"] == "ranked") & (battles["status"] == "OK")
    if "sample" in battles:
        keep &= battles["sample"] == "leaderboard"
    b = battles.loc[keep, ["battle_key", "battle_time"]]
    s = dib.merge(b, on="battle_key")[["battle_key", "battle_time", "deck_key", "won"]]
    s["battle_time"] = pd.to_datetime(s["battle_time"], utc=True)
    return s


def meta_decks(paths, battles: pd.DataFrame, dib: pd.DataFrame, archetype=None, first_period_hours: float = 24.0) -> dict:
    """Most-played decks per collection period (leaderboard ranked battles), measured."""
    sides = _leaderboard_ranked(battles, dib)
    manifest = pd.read_csv(Path(paths.root) / "raw_manifest.csv")
    per = collection_periods(manifest, first_period_hours)
    rows = []
    for i, p in per.iterrows():
        sel = sides[(sides["battle_time"] > p["start"]) & (sides["battle_time"] <= p["end"])]
        g = sel.groupby("deck_key")["won"].agg(games="size", wins="sum")
        n = len(sel)
        for k, r in g.iterrows():
            rows.append({"period": int(i), "deck_key": k, "games": int(r["games"]), "wins": int(r["wins"]), "appearances": n})
    df = pd.DataFrame(rows, columns=["period", "deck_key", "games", "wins", "appearances"])
    totals = df.groupby("deck_key")["games"].sum()
    top = totals[totals >= MIN_DECK_GAMES].sort_values(ascending=False).head(TOP_DECKS).index.tolist()
    P = len(per)
    out = []
    from .rules import parse_deck_key
    for k in top:
        hist = []
        for p in range(P):
            r = df[(df["deck_key"] == k) & (df["period"] == p)]
            n = int(df.loc[df["period"] == p, "appearances"].iloc[0]) if (df["period"] == p).any() else 0
            games, wins = (int(r["games"].iloc[0]), int(r["wins"].iloc[0])) if len(r) else (0, 0)
            hist.append({"period": p, "games": games, "wins": wins, "appearances": n,
                         "share": games / n if n else None, "share_ci90": _wilson(games, n) if n else None,
                         "win_rate": wins / games if games else None, "win_ci90": _wilson(wins, games) if games else None})
        change = None
        if P >= 2 and hist[-1]["appearances"] and hist[-2]["appearances"]:
            a, b = hist[-2], hist[-1]
            p1, p2 = a["games"] / a["appearances"], b["games"] / b["appearances"]
            se = math.sqrt(p1 * (1 - p1) / a["appearances"] + p2 * (1 - p2) / b["appearances"])
            change = {"points": p2 - p1, "ci90": [p2 - p1 - Z90 * se, p2 - p1 + Z90 * se]}
        g, w = int(totals[k]), int(df.loc[df["deck_key"] == k, "wins"].sum())
        label = archetype.predict(parse_deck_key(k)).label if archetype is not None and archetype.fitted else None
        out.append({"deck_key": k, "games": g, "wins": w, "win_rate": w / g, "win_ci90": _wilson(w, g),
                    "archetype": label, "history": hist, "change": change})
    return {"periods": [{"window_id": r["window_id"], "start": str(r["start"]), "end": str(r["end"])} for _, r in per.iterrows()],
            "decks": out, "min_games": MIN_DECK_GAMES}


def season_status(battles: pd.DataFrame, dib: pd.DataFrame, season_ids: list[str] | None) -> dict:
    """Seasons the leaderboard ranked data covers (calendar-month assumption) and whether a prediction may be shown."""
    sides = _leaderboard_ranked(battles, dib)
    per_month = (sides.drop_duplicates("battle_key")["battle_time"].dt.strftime("%Y-%m").value_counts().sort_index())
    seasons = [{"season": m, "battles": int(n), "covered": int(n) >= MIN_SEASON_BATTLES} for m, n in per_month.items()]
    covered = sum(s["covered"] for s in seasons)
    latest_done = season_ids[-1] if season_ids else None
    reason = (f"The collected ranked battles cover {covered} season{'s' if covered != 1 else ''} with at least "
              f"{MIN_SEASON_BATTLES:,} battles. Predicting the next season needs {MIN_SEASONS}: two to measure how the meta "
              f"changes from one season to the next, and a third, held back, to test that against assuming no change. "
              f"Battle logs only hold each player's last 30 battles, so past seasons cannot be filled in later; "
              f"{max(0, MIN_SEASONS - covered)} more season{'s' if MIN_SEASONS - covered != 1 else ''} of daily collection "
              f"are needed.") if covered < MIN_SEASONS else (
              f"{covered} seasons are covered. A season-to-season model can now be fitted and backtested; it is shown only "
              "if it beats assuming no change on the held-out season.")
    return {"state": "blocked" if covered < MIN_SEASONS else "ready_to_backtest", "reason": reason,
            "covered": covered, "needed": MIN_SEASONS, "min_season_battles": MIN_SEASON_BATTLES, "seasons": seasons,
            "api_latest_completed_season": latest_done, "api_seasons_listed": len(season_ids or [])}


def season_ids(paths) -> list[str]:
    """Season ids from the newest saved GET /locations/global/seasons response."""
    files = sorted(Path(paths.raw).glob("*/seasons/seasons.json"), key=lambda f: json.loads(f.read_text(encoding="utf-8")).get("fetched_at", ""))
    for f in reversed(files):
        w = json.loads(f.read_text(encoding="utf-8"))
        if w.get("status") == 200 and isinstance(w.get("body"), dict):
            return [s["id"] for s in w["body"].get("items", []) if "id" in s]
    return []


def season_report(paths, ctx, cfg: dict) -> dict:
    from .pipeline import load_interim
    battles, dib, _, _ = load_interim(paths)
    fc = cfg.get("forecast", {})
    return {
        "status": season_status(battles, dib, season_ids(paths)),
        "meta_decks": meta_decks(paths, battles, dib, ctx.archetype if ctx is not None else None, float(fc.get("first_period_hours", 24))),
        "cards": card_snapshots(paths),
        "assumptions": [
            "A battle's season is the calendar month of its battle time. The API lists season ids (like 2026-09) but not "
            "their start and end dates, so a few days around each boundary may be counted in the neighbouring season.",
            "Meta decks are exact 8-card decks (base, Evolution and Hero forms distinct) of leaderboard players in Ranked; "
            "the arena sample is left out so every period describes the same kind of player.",
            "Usage share: the deck's appearances divided by all deck appearances in the period (both sides of each battle). "
            "Ranges are 90% Wilson intervals; the change between periods uses a normal approximation.",
            "A card, Evolution or Hero released in a new season has no battles yet. It is flagged as new on the next "
            "collection and has no weight or prediction until it has been played enough.",
        ],
    }
