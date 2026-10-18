"""SYNTHETIC data for pipeline testing. Never a fallback for real data.

Writes raw-format files under data/synthetic/raw/ only, in the battle-log
shape assumed in docs/api-notes.md, so parse -> models -> search can be run
end to end before an API key exists, and so tests can check that the models
recover a known, planted signal. Every file carries "synthetic": true.

The hidden truth (card strengths, planted pair synergies) is saved to
data/synthetic/truth.json so recovery can be checked. Nothing generated here
describes the real game: real card names are used only so decks are readable.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .cards import CardTable, attach_api, load_labels
from .config import CARD_LABELS, Paths
from .rules import DeckCard, DeckRules, check_deck

WINDOW_ID = "synthetic-w1"
UNKNOWN_SYNTHETIC_CARD_ID = 99_999_999
TAG_ALPHABET = "0289PYLQGRJCUV"

TEMPLATES: dict[str, list[str]] = {
    "Cycle": ["Hog Rider", "Ice Spirit", "Skeletons", "Cannon", "Musketeer", "The Log", "Fireball", "Ice Golem"],
    "Cycle-EQ": ["Hog Rider", "Earthquake", "Valkyrie", "Musketeer", "Cannon", "Skeletons", "Ice Spirit", "The Log"],
    "Beatdown": ["Golem", "Night Witch", "Baby Dragon", "Lightning", "Mega Minion", "Tornado", "Lumberjack", "Barbarian Barrel"],
    "Siege": ["X-Bow", "Tesla", "Archers", "Knight", "Skeletons", "Ice Spirit", "Fireball", "The Log"],
    "Bait": ["Goblin Barrel", "Princess", "Goblin Gang", "Inferno Tower", "Rocket", "The Log", "Knight", "Ice Spirit"],
    "Bridge Spam": ["P.E.K.K.A", "Battle Ram", "Bandit", "Royal Ghost", "Electro Wizard", "Magic Archer", "Poison", "Zap"],
    "Graveyard": ["Graveyard", "Poison", "Baby Dragon", "Ice Wizard", "Tornado", "Valkyrie", "Tombstone", "Barbarian Barrel"],
    "Control": ["Miner", "Poison", "Valkyrie", "Bomb Tower", "Spear Goblins", "Electro Spirit", "The Log", "Archer Queen"],
}
PLANTED_SYNERGY = [
    ("Hog Rider", "Ice Spirit", 0.15), ("Golem", "Night Witch", 0.15), ("X-Bow", "Tesla", 0.12),
    ("Goblin Barrel", "Princess", 0.12), ("Graveyard", "Poison", 0.15), ("P.E.K.K.A", "Battle Ram", 0.12),
    ("Hog Rider", "Earthquake", 0.12), ("Miner", "Poison", 0.10),
]


def synthetic_cards_body(labels) -> dict:
    items = []
    for i, r in enumerate(labels.sort_values("name").itertuples()):
        item = {"name": r.name, "id": 90_000_000 + i, "elixirCost": int(r.elixir) if r.elixir == r.elixir else 0,
                "rarity": "champion" if r.is_champion else "synthetic", "maxLevel": 16}
        if r.has_evolution:
            item["maxEvolutionLevel"] = 1
        items.append(item)
    return {"items": items, "synthetic": True}


def synthetic_card_table() -> CardTable:
    labels = load_labels(CARD_LABELS)
    table, _ = attach_api(labels, synthetic_cards_body(labels))
    return CardTable(table)


@dataclass
class SynthConfig:
    n_players: int = 300
    n_battles: int = 20_000
    days: int = 21
    seed: int = 7
    start: datetime = datetime(2026, 9, 27, tzinfo=timezone.utc)


def _tag(rng) -> str:
    return "#SYN" + "".join(rng.choice(list(TAG_ALPHABET), 6))


def generate(cfg: SynthConfig | None = None, paths: Paths | None = None, overwrite: bool = True) -> dict:
    cfg = cfg or SynthConfig()
    paths = paths or Paths.for_source("synthetic")
    assert paths.is_synthetic, "synthetic data is only ever written to the synthetic root"
    rng = np.random.default_rng(cfg.seed)
    rules = DeckRules.load()
    labels = load_labels(CARD_LABELS)
    body = synthetic_cards_body(labels)
    table, _ = attach_api(labels, body)
    cards = CardTable(table)
    name_id = {c.name: c.card_id for c in (cards[i] for i in cards.ids)}

    if overwrite and paths.root.exists():
        shutil.rmtree(paths.root)
    raw = paths.raw / WINDOW_ID
    (raw / "cards").mkdir(parents=True, exist_ok=True)
    (raw / "battlelog").mkdir(parents=True, exist_ok=True)
    (raw / "leaderboard").mkdir(parents=True, exist_ok=True)
    fetched = "2026-10-18T12:00:00Z"

    def wrap(endpoint, body_):
        return {"request": {"endpoint": endpoint, "params": {}, "window_id": WINDOW_ID},
                "status": 200, "fetched_at": fetched, "synthetic": True, "body": body_}

    with (raw / "cards" / "cards.json").open("w", encoding="utf-8") as f:
        json.dump(wrap("/cards", body), f)

    # Hidden truth
    strength = {}
    for cid in cards.ids:
        for form in cards[cid].allowed_forms():
            strength[f"{cid}:{form}"] = float(rng.normal(0, 0.12)) + (0.04 if form == "evo" else 0.0)
    synergy = {(min(name_id[a], name_id[b]), max(name_id[a], name_id[b])): v for a, b, v in PLANTED_SYNERGY}

    def utility(entries: list[DeckCard]) -> float:
        hero_ok = lambda e: f"{e.card_id}:{e.form}" if f"{e.card_id}:{e.form}" in strength else f"{e.card_id}:base"
        u = sum(strength[hero_ok(e)] for e in entries)
        ids = sorted(e.card_id for e in entries)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                u += synergy.get((ids[i], ids[j]), 0.0)
        return u

    pool = cards.ids
    pool_w = rng.dirichlet(np.ones(len(pool)) * 0.6)

    def make_deck(template: list[str]) -> list[DeckCard]:
        for _ in range(200):
            ids = [name_id[n] for n in template]
            for _ in range(int(rng.choice([0, 1, 1, 2]))):
                i = int(rng.integers(len(ids)))
                new = int(rng.choice(pool, p=pool_w))
                if new not in ids:
                    ids[i] = new
            entries = [DeckCard(c, "base") for c in ids]
            evo_capable = [i for i, e in enumerate(entries) if cards[e.card_id].has_evolution]
            rng.shuffle(evo_capable)
            n_evo = 0
            if evo_capable and rng.random() < 0.85:
                n_evo = 1
                has_champ = any(cards[e.card_id].is_champion for e in entries)
                if len(evo_capable) > 1 and not has_champ and rng.random() < 0.5:
                    n_evo = 2
            for i in evo_capable[:n_evo]:
                entries[i] = DeckCard(entries[i].card_id, "evo")
            if check_deck(entries, cards, rules).legal:
                return entries
        raise RuntimeError("could not build a legal synthetic deck")

    archetypes = list(TEMPLATES)
    players = []
    tags = set()
    while len(players) < cfg.n_players:
        t = _tag(rng)
        if t in tags:
            continue
        tags.add(t)
        a = archetypes[int(rng.integers(len(archetypes)))]
        players.append({"tag": t, "name": f"synthetic-{len(players)}", "archetype": a,
                        "deck": make_deck(TEMPLATES[a]), "alt_deck": make_deck(TEMPLATES[a]), "skill": float(rng.normal(0, 0.15)),
                        "trophies": int(rng.integers(2000, 3000))})

    logs: dict[str, list] = {p["tag"]: [] for p in players}
    span = cfg.days * 86400
    n_mirror = n_unknown = n_draw = n_other_type = 0
    for _ in range(cfg.n_battles):
        i, j = rng.choice(len(players), 2, replace=False)
        pa, pb = players[i], players[j]
        da = pa["alt_deck"] if rng.random() < 0.3 else pa["deck"]
        db = pb["alt_deck"] if rng.random() < 0.3 else pb["deck"]
        if rng.random() < 0.005:
            db = da
            n_mirror += 1
        t = cfg.start + timedelta(seconds=int(rng.integers(span)))
        p = 1 / (1 + np.exp(-(utility(da) - utility(db) + pa["skill"] - pb["skill"])))
        if rng.random() < 0.02:
            ca = cb = int(rng.integers(0, 3))
            n_draw += 1
        elif rng.random() < p:
            ca = int(rng.integers(1, 4)); cb = int(rng.integers(0, ca))
        else:
            cb = int(rng.integers(1, 4)); ca = int(rng.integers(0, cb))
        btype = "pathOfLegend"
        if rng.random() < 0.02:
            btype = "friendly"
            n_other_type += 1
        unknown = rng.random() < 0.003
        n_unknown += unknown

        def side(pl, deck, crowns, inject_unknown=False):
            ordered = sorted(deck, key=lambda e: (e.form == "base", e.card_id))
            cs = []
            for e in ordered:
                c = {"name": cards[e.card_id].name, "id": e.card_id, "level": int(rng.integers(14, 17)), "maxLevel": 16}
                if e.form == "evo":
                    c["evolutionLevel"] = 1
                    c["maxEvolutionLevel"] = 1
                cs.append(c)
            if inject_unknown:
                cs[-1] = {"name": "Synthetic Unknown", "id": UNKNOWN_SYNTHETIC_CARD_ID, "level": 15, "maxLevel": 16}
            return {"tag": pl["tag"], "name": pl["name"], "crowns": crowns, "startingTrophies": pl["trophies"], "cards": cs}

        sa, sb = side(pa, da, ca), side(pb, db, cb, unknown)
        game = {"battleTime": t.strftime("%Y%m%dT%H%M%S.000Z"), "type": btype,
                "gameMode": {"id": 0, "name": "Synthetic_Ranked1v1"}}
        logs[pa["tag"]].append({**game, "team": [sa], "opponent": [sb]})
        logs[pb["tag"]].append({**game, "team": [sb], "opponent": [sa]})

    for tag, battles in logs.items():
        battles.sort(key=lambda b: b["battleTime"], reverse=True)
        with (raw / "battlelog" / f"{tag.lstrip('#')}.json").open("w", encoding="utf-8") as f:
            json.dump(wrap(f"/players/%23{tag.lstrip('#')}/battlelog", battles), f, separators=(",", ":"))

    with (raw / "leaderboard" / "global.json").open("w", encoding="utf-8") as f:
        json.dump(wrap("/locations/global/pathoflegend/players",
                       {"items": [{"tag": p["tag"], "name": p["name"], "rank": r + 1} for r, p in enumerate(players)]}), f)

    # Synthetic archetype labels: template of origin, 80 train + 20 heldout distinct decks.
    from .rules import deck_key
    seen, rows = set(), []
    for p in players:
        for d in (p["deck"], p["alt_deck"]):
            k = deck_key(d)
            if k in seen:
                continue
            seen.add(k)
            rows.append((k, p["archetype"].replace("Cycle-EQ", "Cycle")))
    order = rng.permutation(len(rows))[:100]
    lab_dir = paths.archetype_labels.parent
    lab_dir.mkdir(parents=True, exist_ok=True)
    with paths.archetype_labels.open("w", encoding="utf-8", newline="") as f:
        f.write("deck_key,archetype,split,labeled_at,notes\n")
        for n, idx in enumerate(order):
            k, a = rows[idx]
            f.write(f"{k},{a},{'heldout' if n < 20 else 'train'},2026-10-18,SYNTHETIC template of origin (not a hand label)\n")

    truth = {
        "synthetic": True,
        "card_strength": strength,
        "planted_synergy": [{"a": a, "b": b, "a_id": name_id[a], "b_id": name_id[b], "bonus": v} for a, b, v in PLANTED_SYNERGY],
        "injected": {"mirrors": n_mirror, "draws": n_draw, "unknown_card_battles": int(n_unknown), "non_ranked_type": n_other_type},
        "config": {"n_players": cfg.n_players, "n_battles": cfg.n_battles, "days": cfg.days, "seed": cfg.seed},
    }
    with (paths.root / "truth.json").open("w", encoding="utf-8") as f:
        json.dump(truth, f, indent=1)
    return truth["injected"] | truth["config"]
