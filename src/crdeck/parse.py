"""Raw battle-log JSON -> Battle / DeckInBattle / Deck / SlotCard records (spec section 5).

Statuses (per battle):
  OK            usable by win models
  DRAW          equal crowns; stored, excluded from win models
  MIRROR        identical deck keys; stored, excluded from win models
  UNKNOWN_CARD  a card id not in the card table; excluded until labeled
  NOT_1V1       team/opponent not exactly one player each
  BAD_DECK      a side without exactly deck_size cards
  BAD_TIME      unparseable battleTime
  FILTERED_TYPE battle matches no mode in config battles.modes (or, legacy, not in battle_types)
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
class ModeRules:
    """Assigns each battle a mode from config `battles.modes` (type + gameMode + deckSelection).
    Battles matching no mode are "other" and are never modeled."""
    rules: tuple[tuple[str, frozenset, frozenset], ...]
    deck_selection: frozenset
    group_by: tuple[tuple[str, str], ...] = ()          # mode -> "league" | "arena"
    league_names: tuple[tuple[int, str], ...] = ()      # leagueNumber -> name

    @classmethod
    def from_collection(cls, cfg: dict) -> "ModeRules":
        b = cfg.get("battles", {})
        modes = b.get("modes") or {}
        rules = tuple((k, frozenset(v.get("types", [])), frozenset(v.get("game_modes", [])))
                      for k, v in modes.items())
        group_by = tuple((k, v["group_by"]) for k, v in modes.items() if v.get("group_by"))
        leagues = tuple((int(n), str(name)) for v in modes.values() for n, name in (v.get("leagues") or {}).items())
        return cls(rules, frozenset(b.get("deck_selection", ["collection"])), group_by, leagues)

    def group(self, battle: dict, mode: str) -> str | None:
        """The battle's group within its mode: its league name (from leagueNumber) or its arena
        name, both read from the battle. None when the mode has no grouping or the field is missing."""
        how = dict(self.group_by).get(mode)
        if how == "arena":
            return (battle.get("arena") or {}).get("name")
        if how == "league":
            n = battle.get("leagueNumber")
            return dict(self.league_names).get(n, f"League {n}") if n is not None else None
        return None

    def assign(self, battle: dict) -> str:
        if battle.get("deckSelection") not in self.deck_selection:
            return "other"
        t, gm = battle.get("type"), (battle.get("gameMode") or {}).get("name")
        for key, types, modes in self.rules:
            if t in types and gm in modes:
                return key
        return "other"


def mode_slug(mode: str, arena: str | None = None) -> str:
    """File-safe id: 'ranked', 'trophy_road__seasonal_arena_ii'."""
    import re
    return mode if not arena else f"{mode}__{re.sub(r'[^a-z0-9]+', '_', arena.lower()).strip('_')}"


def mode_label(cfg: dict, mode: str, arena: str | None = None) -> str:
    modes = cfg.get("battles", {}).get("modes") or {}
    base = modes.get(mode, {}).get("label") or ("All modes" if mode == "all" else mode)
    return f"{base}: {arena}" if arena else base


def mode_groups(cfg: dict, mode: str) -> list[dict]:
    """The configured groups of a mode in game order: [{"name", "order", "min_trophies" | "league"}].
    Names come from config (supplied by the project owner); data decides which battle is in which."""
    m = (cfg.get("battles", {}).get("modes") or {}).get(mode) or {}
    if m.get("group_by") == "league":
        return [{"name": str(name), "order": int(n), "league": int(n)} for n, name in sorted((m.get("leagues") or {}).items(), key=lambda x: int(x[0]))]
    if m.get("group_by") == "arena":
        return [{"name": str(a[0]), "order": i + 1, "min_trophies": a[1]} for i, a in enumerate(m.get("arenas") or [])]
    return []


def modes_for(cfg: dict, mode: str) -> list[str]:
    """'ranked' -> ['ranked']; a combined name like 'all' -> its member modes."""
    combined = (cfg.get("battles", {}).get("combined") or {})
    return list(combined[mode]) if mode in combined else [mode]


@dataclass(frozen=True)
class FormConfig:
    """How a battle-deck card's form and slot are read (config: form_resolution).

    form_values maps values of form_field to forms; a form missing from the map is
    not observable (e.g. without 2: hero, hero cards read as base -> FORM_UNKNOWN).
    slot_positions maps deck positions to special slots; empty = slots unknown.
    """
    form_field: str | None = "evolutionLevel"
    form_values: tuple[tuple[int, str], ...] = ((1, "evo"), (2, "hero"))
    slot_positions: tuple[tuple[int, str], ...] = ((0, "evo"), (1, "hero"), (2, "wild"))

    @classmethod
    def from_collection(cls, cfg: dict) -> "FormConfig":
        fr = cfg.get("form_resolution", {})
        return cls(
            form_field=fr.get("form_field"),
            form_values=tuple(sorted((int(k), str(v)) for k, v in (fr.get("form_values") or {}).items())),
            slot_positions=tuple(sorted((int(k), str(v)) for k, v in (fr.get("slot_positions") or {}).items())),
        )

    @property
    def hero_observable(self) -> bool:
        return "hero" in dict(self.form_values).values()

    def slot(self, position: int) -> str:
        if not self.slot_positions:
            return "unknown"
        return dict(self.slot_positions).get(position, "normal")


def card_form(card: dict, fc: FormConfig) -> str:
    """Observed: evolutionLevel 1 = evo, 2 = hero, absent = base. Unmapped values read as base."""
    if not fc.form_field:
        return "base"
    v = card.get(fc.form_field)
    try:
        return dict(fc.form_values).get(int(v), "base") if v is not None else "base"
    except (TypeError, ValueError):
        return "base"


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
        "global_rank": side.get("globalRank"),
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
    modes: ModeRules | None = None,
    sample: str = "leaderboard",
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (battles, decks_in_battle, slot_cards) rows for one log.

    With `modes`, each battle gets a mode and FILTERED_TYPE means "matches no mode".
    Without it (legacy), `battle_types` filters on `type` and accepted battles are "ranked"."""
    types = set(battle_types) if battle_types else None
    battles, dib, slots = [], [], []
    for b in body:
        t = parse_time(b.get("battleTime"))
        team, opp = b.get("team", []), b.get("opponent", [])
        if modes is not None:
            mode = modes.assign(b)
        else:
            mode = "ranked" if (types is None or b.get("type") in types) else "other"
        base = {
            "battle_type": b.get("type"),
            "game_mode": (b.get("gameMode") or {}).get("name"),
            "mode": mode,
            "arena": (b.get("arena") or {}).get("name"),
            "league": b.get("leagueNumber"),
            "group": modes.group(b, mode) if modes is not None else None,
            "sample": sample,
            "deck_selection": b.get("deckSelection"),
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
        if mode == "other":
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
                "won": won, "crowns": s["crowns"], "trophies_or_rank": s["trophies"], "global_rank": s["global_rank"],
                "level_deficit": s["level_deficit"], "form_unknown": s["form_unknown"],
            })
            for cid, form, pos in s["entries"]:
                slots.append({"deck_key": s["deck_key"], "card_id": cid, "form": form,
                              "slot": fc.slot(pos), "position": pos})
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
    modes: ModeRules | None = None,
) -> Parsed:
    # Rows are turned into DataFrames and de-duplicated every CHUNK_FILES files: holding every raw row of
    # ~50,000 logs as Python dicts no longer fits in memory. Keeping the first row per key inside each chunk
    # (in file order, battles after the same sort as dedupe) and then again over all chunks keeps exactly
    # the rows a single dedupe would keep.
    all_b, all_d, all_s = [], [], []
    frames_b, frames_d, frames_s = [], [], []
    in_leaderboard: set[str] = set()
    n_raw = 0

    def flush():
        nonlocal all_b, all_d, all_s, n_raw
        if all_b:
            f = pd.DataFrame(all_b, columns=BATTLE_COLS)
            n_raw += len(f)
            in_leaderboard.update(f.loc[f["sample"] == "leaderboard", "battle_key"])
            f = f.sort_values(["battle_key", "fetched_at", "source_player_tag"], kind="mergesort")
            frames_b.append(f.drop_duplicates("battle_key", keep="first"))
        if all_d:
            frames_d.append(pd.DataFrame(all_d, columns=DIB_COLS).drop_duplicates(["battle_key", "side"], keep="first"))
        if all_s:
            frames_s.append(pd.DataFrame(all_s, columns=SLOT_COLS).drop_duplicates(["deck_key", "card_id"], keep="first"))
        all_b, all_d, all_s = [], [], []

    n_files = n_404 = 0
    for p in sorted(files):
        if n_files and n_files % CHUNK_FILES == 0:
            flush()
        w = load_wrapped(p)
        n_files += 1
        if w.get("status") != 200 or not isinstance(w.get("body"), list):
            n_404 += 1
            continue
        tag = "#" + p.stem
        # which group of players the log was collected for: leaderboard players or the arena sample
        sample = "arena_sample" if p.parent.name == "battlelog_arena" else "leaderboard"
        b, d, s = parse_battlelog(w["body"], tag, w.get("fetched_at", ""), cards, fc, battle_types, deck_size, window, modes, sample)
        all_b += b
        all_d += d
        all_s += s
    flush()
    cat = lambda fr, cols: pd.concat(fr, ignore_index=True) if fr else pd.DataFrame(columns=cols)  # noqa: E731
    return dedupe(cat(frames_b, BATTLE_COLS), cat(frames_d, DIB_COLS), cat(frames_s, SLOT_COLS),
                  extra_counts={"files": n_files, "files_without_battles": n_404}, n_raw=n_raw, in_leaderboard=in_leaderboard)


BATTLE_COLS = ["battle_key", "battle_time", "battle_type", "game_mode", "mode", "arena", "league",
               "group", "sample", "deck_selection", "source_player_tag", "fetched_at", "status", "unknown_card_ids"]
DIB_COLS = ["battle_key", "side", "player_tag", "deck_key", "won", "crowns",
            "trophies_or_rank", "global_rank", "level_deficit", "form_unknown"]
SLOT_COLS = ["deck_key", "card_id", "form", "slot", "position"]
CHUNK_FILES = 2000


def dedupe(battles, dib, slots, extra_counts: dict | None = None, n_raw: int | None = None,
           in_leaderboard: set | None = None) -> Parsed:
    """battles, dib, slots: lists of row dicts or DataFrames. n_raw and in_leaderboard are passed when the rows
    were already de-duplicated in chunks (parse_files): the raw row count and every battle key seen in the
    leaderboard sample before that."""
    bdf = pd.DataFrame(battles, columns=BATTLE_COLS)
    if n_raw is None:
        n_raw = len(bdf)
    if bdf["sample"].isna().all():
        bdf["sample"] = "leaderboard"
    if in_leaderboard is None:
        in_leaderboard = set(bdf.loc[bdf["sample"] == "leaderboard", "battle_key"])
    bdf = bdf.sort_values(["battle_key", "fetched_at", "source_player_tag"], kind="mergesort")
    bdf = bdf.drop_duplicates("battle_key", keep="first").reset_index(drop=True)
    # a battle seen in both samples counts as a leaderboard battle, so the leaderboard sample stays whole
    bdf["sample"] = bdf["battle_key"].isin(in_leaderboard).map({True: "leaderboard", False: "arena_sample"})
    ddf = pd.DataFrame(dib, columns=DIB_COLS)
    ddf = ddf.drop_duplicates(["battle_key", "side"], keep="first").reset_index(drop=True)
    sdf = pd.DataFrame(slots, columns=SLOT_COLS)
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
        "modes": {m: {k: int(v) for k, v in g["status"].value_counts().sort_index().items()}
                  for m, g in bdf.groupby("mode", dropna=False)},
        "ok_by_mode_arena": {f"{m}|{a}": int(n) for (m, a), n in
                             bdf[bdf["status"] == OK].groupby(["mode", "arena"], dropna=False).size().items()},
        "ok_by_mode_group": {f"{m}|{g}": int(n) for (m, g), n in
                             bdf[bdf["status"] == OK].groupby(["mode", "group"]).size().items()},
        "ok_by_sample": {str(k): int(n) for k, n in bdf[bdf["status"] == OK].groupby("sample").size().items()},
        "unknown_card_ids": unknown_ids,
        "distinct_decks": int(len(decks)),
    }
    if len(bdf):
        ok_times = bdf.loc[bdf["battle_time"].notna(), "battle_time"]
        if len(ok_times):
            counts["first_battle"] = str(ok_times.min())
            counts["last_battle"] = str(ok_times.max())
    return Parsed(bdf, ddf, decks, sdf, counts)
