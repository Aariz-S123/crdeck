"""Raw battle-log JSON -> Battle / DeckInBattle / Deck / SlotCard records (spec section 5).

Statuses (per battle):
  OK            usable by win models
  DRAW          equal crowns; stored, excluded from win models
  MIRROR        identical deck keys; stored, excluded from win models
  UNKNOWN_CARD  a card id not in the card table; excluded until labeled
  NOT_1V1       team/opponent not exactly one player each
  BAD_DECK      a side without exactly deck_size cards
  BAD_TIME      unparseable battleTime
  FILTERED_TYPE battle type not in config battles.battle_types
  OUT_OF_WINDOW battle_time outside config window start/end
The battle key is (sorted tags, battle_time), so a battle seen in both players'
logs is the same record; dedupe() keeps one row per key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .cards import CardTable

OK = "OK"
DRAW = "DRAW"
MIRROR = "MIRROR"
UNKNOWN_CARD = "UNKNOWN_CARD"
NOT_1V1 = "NOT_1V1"
BAD_DECK = "BAD_DECK"
BAD_TIME = "BAD_TIME"
FILTERED_TYPE = "FILTERED_TYPE"
OUT_OF_WINDOW = "OUT_OF_WINDOW"

TIME_FORMATS = ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class FormConfig:
    evo_field: str | None = "evolutionLevel"
    hero_field: str | None = None  # None: hero vs base not observable -> FORM_UNKNOWN

    @classmethod
    def from_collection(cls, cfg: dict) -> "FormConfig":
        fr = cfg.get("form_resolution", {})
        return cls(evo_field=fr.get("evo_field"), hero_field=fr.get("hero_field"))

    @property
    def hero_observable(self) -> bool:
        return bool(self.hero_field)


def card_form(card: dict, fc: FormConfig) -> str:
    if fc.hero_field and _positive(card.get(fc.hero_field)):
        return "hero"
    if fc.evo_field and _positive(card.get(fc.evo_field)):
        return "evo"
    return "base"


def _positive(v: Any) -> bool:
    try:
        return v is not None and float(v) > 0
    except (TypeError, ValueError):
        return bool(v)


def battle_key(tag_a: str, tag_b: str, t: datetime) -> str:
    a, b = sorted([tag_a, tag_b])
    return f"{a}|{b}|{t.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _side(side: dict, cards: CardTable, fc: FormConfig) -> dict:
    entries = []
    unknown = []
    form_unknown = False
    deficits = []
    for pos, c in enumerate(side.get("cards", [])):
        cid = int(c["id"])
        form = card_form(c, fc)
        if cid not in cards:
            unknown.append(cid)
        elif form == "base" and not fc.hero_observable and cards[cid].has_hero:
            form_unknown = True
        entries.append((cid, form, pos))
        if c.get("maxLevel") is not None and c.get("level") is not None:
            deficits.append(float(c["maxLevel"]) - float(c["level"]))
    key = "|".join(sorted(f"{cid}:{form}" for cid, form, _ in entries))
    return {
        "tag": side.get("tag", ""),
        "crowns": side.get("crowns"),
        "trophies": side.get("startingTrophies"),
        "entries": entries,
        "deck_key": key,
        "unknown": unknown,
        "form_unknown": form_unknown,
        "level_deficit": (sum(deficits) / len(deficits)) if deficits else None,
    }


def parse_battlelog(
    body: list[dict],
    source_tag: str,
    fetched_at: str,
    cards: CardTable,
    fc: FormConfig,
    battle_types: Iterable[str] | None = None,
    deck_size: int = 8,
    window: tuple[datetime | None, datetime | None] = (None, None),
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (battles, decks_in_battle, slot_cards) rows for one log."""
    types = set(battle_types) if battle_types else None
    battles, dib, slots = [], [], []
    for b in body:
        t = parse_time(b.get("battleTime"))
        team, opp = b.get("team", []), b.get("opponent", [])
        base = {
            "battle_type": b.get("type"),
            "game_mode": (b.get("gameMode") or {}).get("name"),
            "source_player_tag": source_tag,
            "fetched_at": fetched_at,
        }
        if t is None:
            battles.append({**base, "battle_key": f"BAD_TIME|{source_tag}|{b.get('battleTime')}", "battle_time": None, "status": BAD_TIME, "unknown_card_ids": ""})
            continue
        if len(team) != 1 or len(opp) != 1:
            tags = [p.get("tag", "") for p in team + opp]
            battles.append({**base, "battle_key": f"{'|'.join(sorted(tags))}|{t.strftime('%Y-%m-%dT%H:%M:%SZ')}", "battle_time": t, "status": NOT_1V1, "unknown_card_ids": ""})
            continue
        s1, s2 = _side(team[0], cards, fc), _side(opp[0], cards, fc)
        a, bb = sorted([s1, s2], key=lambda s: s["tag"])
        key = battle_key(a["tag"], bb["tag"], t)
        unknown = sorted(set(a["unknown"] + bb["unknown"]))
        if types is not None and b.get("type") not in types:
            status = FILTERED_TYPE
        elif (window[0] and t < window[0]) or (window[1] and t >= window[1]):
            status = OUT_OF_WINDOW
        elif len(a["entries"]) != deck_size or len(bb["entries"]) != deck_size:
            status = BAD_DECK
        elif unknown:
            status = UNKNOWN_CARD
        elif a["crowns"] == bb["crowns"]:
            status = DRAW
        elif a["deck_key"] == bb["deck_key"]:
            status = MIRROR
        else:
            status = OK
        battles.append({**base, "battle_key": key, "battle_time": t, "status": status,
                        "unknown_card_ids": ";".join(map(str, unknown))})
        for side_name, s, other in (("A", a, bb), ("B", bb, a)):
            won = None if a["crowns"] == bb["crowns"] or s["crowns"] is None else bool(s["crowns"] > other["crowns"])
            dib.append({
                "battle_key": key, "side": side_name, "player_tag": s["tag"], "deck_key": s["deck_key"],
                "won": won, "crowns": s["crowns"], "trophies_or_rank": s["trophies"],
                "level_deficit": s["level_deficit"], "form_unknown": s["form_unknown"],
            })
            for cid, form, pos in s["entries"]:
                slots.append({"deck_key": s["deck_key"], "card_id": cid, "form": form,
                              "slot": "unknown", "position": pos})
    return battles, dib, slots


def load_wrapped(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Parsed:
    battles: pd.DataFrame
    decks_in_battle: pd.DataFrame
    decks: pd.DataFrame
    slot_cards: pd.DataFrame
    counts: dict[str, Any]


def parse_files(
    files: Iterable[Path],
    cards: CardTable,
    fc: FormConfig,
    battle_types: Iterable[str] | None = None,
    deck_size: int = 8,
    window: tuple[datetime | None, datetime | None] = (None, None),
) -> Parsed:
    all_b, all_d, all_s = [], [], []
    n_files = n_404 = 0
    for p in sorted(files):
        w = load_wrapped(p)
        n_files += 1
        if w.get("status") != 200 or not isinstance(w.get("body"), list):
            n_404 += 1
            continue
        tag = "#" + p.stem
        b, d, s = parse_battlelog(w["body"], tag, w.get("fetched_at", ""), cards, fc, battle_types, deck_size, window)
        all_b += b
        all_d += d
        all_s += s
    return dedupe(all_b, all_d, all_s, extra_counts={"files": n_files, "files_without_battles": n_404})


def dedupe(battles: list[dict], dib: list[dict], slots: list[dict], extra_counts: dict | None = None) -> Parsed:
    bdf = pd.DataFrame(battles, columns=["battle_key", "battle_time", "battle_type", "game_mode",
                                         "source_player_tag", "fetched_at", "status", "unknown_card_ids"])
    n_raw = len(bdf)
    bdf = bdf.sort_values(["battle_key", "fetched_at", "source_player_tag"], kind="mergesort")
    bdf = bdf.drop_duplicates("battle_key", keep="first").reset_index(drop=True)
    ddf = pd.DataFrame(dib, columns=["battle_key", "side", "player_tag", "deck_key", "won", "crowns",
                                     "trophies_or_rank", "level_deficit", "form_unknown"])
    ddf = ddf.drop_duplicates(["battle_key", "side"], keep="first").reset_index(drop=True)
    sdf = pd.DataFrame(slots, columns=["deck_key", "card_id", "form", "slot", "position"])
    sdf = sdf.drop_duplicates(["deck_key", "card_id"], keep="first").reset_index(drop=True)
    decks = (
        ddf.groupby("deck_key", as_index=False)
        .agg(appearances=("battle_key", "size"), form_unknown=("form_unknown", "max"))
    )
    decks["cards"] = decks["deck_key"].map(lambda k: [int(x.split(":")[0]) for x in k.split("|") if x])
    decks["forms"] = decks["deck_key"].map(lambda k: [x.split(":")[1] for x in k.split("|") if x])
    unknown_ids = sorted({int(x) for s in bdf["unknown_card_ids"].fillna("") for x in str(s).split(";") if x})
    counts = {
        **(extra_counts or {}),
        "battle_rows_before_dedupe": n_raw,
        "battles_after_dedupe": len(bdf),
        "duplicates_removed": n_raw - len(bdf),
        "status": {k: int(v) for k, v in bdf["status"].value_counts().sort_index().items()},
        "unknown_card_ids": unknown_ids,
        "distinct_decks": int(len(decks)),
    }
    if len(bdf):
        ok_times = bdf.loc[bdf["battle_time"].notna(), "battle_time"]
        if len(ok_times):
            counts["first_battle"] = str(ok_times.min())
            counts["last_battle"] = str(ok_times.max())
    return Parsed(bdf, ddf, decks, sdf, counts)
