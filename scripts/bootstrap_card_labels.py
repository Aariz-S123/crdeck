"""One-shot bootstrap of data/labels/cards.csv from data/labels/source/cards_meta.csv.

After this runs once, data/labels/cards.csv is the hand-edited source of truth.
The script refuses to overwrite it unless --force is given.

What it does:
- collapses "X Evolution" and "Hero X" rows onto the base card X
  (has_evolution / has_hero flags);
- keeps the base row's elixir and type, and reports evolution/hero rows that disagree;
- reports duplicate rows and forms with no base row;
- adds DRAFT role labels (label_version v0-draft). These are a starting point
  written by an assistant, not ground truth: review every row, then bump
  label_version.

card_id and rarity stay empty here: they come from the API /cards response
(crdeck.cards.attach_api), never from names typed by hand.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "labels" / "source" / "cards_meta.csv"
OUT = ROOT / "data" / "labels" / "cards.csv"
REPORT = ROOT / "data" / "labels" / "cards_label_report.md"

# name: (is_win_condition, roles, targets, note)
# targets: ground / air_ground / buildings / none / unknown
DRAFT = {
    "Archer Queen": (False, "air_defense", "air_ground", ""),
    "Archers": (False, "air_defense", "air_ground", ""),
    "Arrows": (False, "small_spell", "air_ground", ""),
    "Baby Dragon": (False, "air_defense;splash", "air_ground", ""),
    "Balloon": (True, "", "buildings", ""),
    "Bandit": (False, "mini_tank", "ground", ""),
    "Barbarian Barrel": (False, "small_spell", "ground", ""),
    "Barbarian Hut": (False, "building", "ground", ""),
    "Barbarians": (False, "tank_killer", "ground", ""),
    "Bats": (False, "air_defense;cycle", "air_ground", ""),
    "Battle Healer": (False, "mini_tank", "ground", ""),
    "Battle Ram": (True, "", "buildings", ""),
    "Berserker": (False, "mini_tank", "ground", "drafter unsure of role"),
    "Bomb Tower": (False, "building;splash", "ground", ""),
    "Bomber": (False, "splash", "ground", ""),
    "Boss Bandit": (False, "mini_tank", "ground", "drafter unsure; verify"),
    "Bowler": (False, "splash;mini_tank", "ground", ""),
    "Cannon": (False, "building", "ground", ""),
    "Cannon Cart": (False, "mini_tank", "ground", ""),
    "Cannoneer": (False, "", "unknown", "unknown to drafter; label yourself"),
    "Clone": (False, "", "none", ""),
    "Dark Prince": (False, "mini_tank;splash", "ground", ""),
    "Dart Goblin": (False, "air_defense;cycle", "air_ground", ""),
    "Earthquake": (False, "", "ground", "building-damage spell; no role fits"),
    "Electro Dragon": (False, "air_defense;splash", "air_ground", ""),
    "Electro Giant": (True, "tank", "buildings", ""),
    "Electro Spirit": (False, "cycle", "air_ground", ""),
    "Electro Wizard": (False, "air_defense", "air_ground", ""),
    "Elite Barbarians": (False, "tank_killer", "ground", ""),
    "Elixir Collector": (False, "", "none", ""),
    "Elixir Golem": (True, "tank", "buildings", ""),
    "Executioner": (False, "splash;air_defense", "air_ground", ""),
    "Fire Spirit": (False, "splash;cycle", "air_ground", ""),
    "Fireball": (False, "big_spell", "air_ground", ""),
    "Firecracker": (False, "splash;air_defense", "air_ground", ""),
    "Fisherman": (False, "mini_tank", "ground", ""),
    "Flying Machine": (False, "air_defense", "air_ground", ""),
    "Freeze": (False, "", "air_ground", "utility spell; no role fits"),
    "Furnace": (False, "building", "air_ground", "spawner building"),
    "Giant": (True, "tank", "buildings", ""),
    "Giant Skeleton": (False, "tank;splash", "ground", ""),
    "Giant Snowball": (False, "small_spell", "air_ground", ""),
    "Goblin Barrel": (True, "", "ground", ""),
    "Goblin Cage": (False, "building", "ground", ""),
    "Goblin Curse": (False, "small_spell", "air_ground", "drafter unsure; verify"),
    "Goblin Demolisher": (False, "splash", "ground", "drafter unsure; verify"),
    "Goblin Drill": (True, "", "ground", "CSV type spell; in-game it is placed like a building; verify"),
    "Goblin Gang": (False, "tank_killer", "air_ground", ""),
    "Goblin Giant": (True, "tank", "buildings", ""),
    "Goblin Hut": (False, "building", "air_ground", ""),
    "Goblin Machine": (False, "mini_tank", "ground", "unknown to drafter; verify"),
    "Goblins": (False, "cycle", "ground", ""),
    "Goblinstein": (True, "tank", "buildings", "unknown to drafter; verify"),
    "Golden Knight": (False, "mini_tank", "ground", ""),
    "Golem": (True, "tank", "buildings", ""),
    "Graveyard": (True, "", "ground", ""),
    "Guards": (False, "tank_killer", "ground", ""),
    "Heal Spirit": (False, "cycle", "air_ground", ""),
    "Hog Rider": (True, "", "buildings", ""),
    "Hunter": (False, "air_defense;tank_killer;splash", "air_ground", ""),
    "Ice Golem": (False, "mini_tank;cycle", "buildings", ""),
    "Ice Spirit": (False, "cycle", "air_ground", ""),
    "Ice Wizard": (False, "splash;air_defense", "air_ground", ""),
    "Inferno Dragon": (False, "air_defense;tank_killer", "air_ground", ""),
    "Inferno Tower": (False, "building;tank_killer;air_defense", "air_ground", ""),
    "Knight": (False, "mini_tank", "ground", ""),
    "Lava Hound": (True, "tank", "buildings", ""),
    "Lightning": (False, "big_spell", "air_ground", ""),
    "Little Prince": (False, "air_defense", "air_ground", ""),
    "Lumberjack": (False, "mini_tank", "ground", ""),
    "Magic Archer": (False, "air_defense;splash", "air_ground", ""),
    "Mega Knight": (False, "tank;splash", "ground", ""),
    "Mega Minion": (False, "air_defense", "air_ground", ""),
    "Mighty Miner": (False, "mini_tank;tank_killer", "ground", ""),
    "Miner": (True, "", "ground", ""),
    "Mini P.E.K.K.A": (False, "mini_tank;tank_killer", "ground", ""),
    "Minion Giant": (False, "", "unknown", "unknown to drafter; label yourself"),
    "Minion Horde": (False, "air_defense;tank_killer", "air_ground", ""),
    "Minions": (False, "air_defense", "air_ground", ""),
    "Mirror": (False, "", "none", ""),
    "Monk": (False, "mini_tank", "ground", ""),
    "Mortar": (True, "building", "ground", ""),
    "Mother Witch": (False, "air_defense", "air_ground", ""),
    "Musketeer": (False, "air_defense", "air_ground", ""),
    "Night Witch": (False, "mini_tank", "ground", ""),
    "P.E.K.K.A": (False, "tank;tank_killer", "ground", ""),
    "Phoenix": (False, "air_defense", "air_ground", ""),
    "Poison": (False, "big_spell", "air_ground", ""),
    "Prince": (False, "mini_tank", "ground", ""),
    "Princess": (False, "splash;air_defense", "air_ground", ""),
    "Rage": (False, "", "none", ""),
    "Ram Rider": (True, "", "buildings", ""),
    "Rascals": (False, "mini_tank;air_defense", "air_ground", ""),
    "Rocket": (False, "big_spell", "air_ground", ""),
    "Ronin": (False, "", "unknown", "unknown to drafter; label yourself"),
    "Royal Delivery": (False, "small_spell", "ground", ""),
    "Royal Ghost": (False, "mini_tank;splash", "ground", ""),
    "Royal Giant": (True, "tank", "buildings", ""),
    "Royal Hogs": (True, "", "buildings", ""),
    "Royal Recruits": (False, "", "ground", ""),
    "Rune Giant": (False, "tank", "ground", "drafter unsure; verify"),
    "Skeleton Army": (False, "tank_killer", "ground", ""),
    "Skeleton Barrel": (True, "", "buildings", ""),
    "Skeleton Dragons": (False, "air_defense;splash", "air_ground", ""),
    "Skeleton King": (False, "mini_tank;splash", "ground", ""),
    "Skeletons": (False, "cycle", "ground", ""),
    "Sparky": (False, "splash;tank_killer", "ground", ""),
    "Spear Goblins": (False, "air_defense;cycle", "air_ground", ""),
    "Spirit Empress": (False, "", "unknown", "unknown to drafter; label yourself"),
    "Suspicious Bush": (True, "cycle", "buildings", "CSV type spell; drafter believes troop; verify"),
    "Tesla": (False, "building;air_defense", "air_ground", ""),
    "The Log": (False, "small_spell", "ground", ""),
    "Three Musketeers": (True, "air_defense", "air_ground", ""),
    "Tombstone": (False, "building", "ground", ""),
    "Tornado": (False, "small_spell", "air_ground", ""),
    "Valkyrie": (False, "splash;mini_tank", "ground", ""),
    "Vines": (False, "small_spell", "air_ground", "drafter unsure; verify"),
    "Void": (False, "small_spell", "air_ground", "drafter unsure; verify"),
    "Wall Breakers": (True, "", "buildings", ""),
    "Witch": (False, "splash;air_defense", "air_ground", ""),
    "Wizard": (False, "splash;air_defense", "air_ground", ""),
    "X-Bow": (True, "building", "ground", ""),
    "Zap": (False, "small_spell", "air_ground", ""),
    "Zappies": (False, "air_defense", "air_ground", ""),
}

# Champions by drafter knowledge. The API rarity "champion" overrides this when attached.
CHAMPIONS = {
    "Archer Queen", "Golden Knight", "Mighty Miner", "Skeleton King",
    "Little Prince", "Monk", "Goblinstein", "Boss Bandit",
}
VARIABLE_ELIXIR = {"Mirror"}

FIELDS = [
    "card_id", "name", "elixir", "elixir_variable", "rarity", "card_type",
    "has_evolution", "has_hero", "is_champion", "is_win_condition",
    "roles", "targets", "label_version", "notes",
]


def split_form(name: str) -> tuple[str, str]:
    if name.endswith(" Evolution"):
        return name[: -len(" Evolution")], "evo"
    if name.startswith("Hero "):
        return name[len("Hero "):], "hero"
    return name, "base"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if OUT.exists() and not args.force:
        print(f"{OUT} exists; it is the hand-edited source of truth. Use --force to overwrite.")
        return 1

    with SOURCE.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    issues: list[str] = []
    base: dict[str, dict] = {}
    forms: dict[str, list[dict]] = {}
    seen: dict[str, dict] = {}
    for r in rows:
        name = r["card_name"].strip()
        if name in seen:
            issues.append(
                f"Duplicate row `{name}`: kept first ({seen[name]['rating']}/{seen[name]['usage']}/"
                f"{seen[name]['win_rate']}), dropped ({r['rating']}/{r['usage']}/{r['win_rate']})"
                " [rating/usage/win_rate]."
            )
            continue
        seen[name] = r
        b, form = split_form(name)
        if form == "base":
            base[b] = r
        else:
            forms.setdefault(b, []).append({**r, "_form": form})

    out = []
    for b in sorted(base):
        r = base[b]
        fl = forms.get(b, [])
        for fr in fl:
            if fr["elixir"] != r["elixir"]:
                issues.append(f"Elixir mismatch: `{fr['card_name']}` = {fr['elixir']} vs `{b}` = {r['elixir']}; kept base value (API /cards overrides).")
            ftype = fr["type"]
            btype = "troop" if r["type"] == "hero" else r["type"]
            if ftype != btype:
                issues.append(f"Type mismatch: `{fr['card_name']}` = {ftype} vs `{b}` = {r['type']}; kept base value.")
        if b not in DRAFT:
            issues.append(f"No draft role labels for `{b}`; left blank.")
        wc, roles, targets, note = DRAFT.get(b, (False, "", "unknown", "not labeled"))
        ctype = r["type"]
        if ctype == "hero":  # the source marks champions as type "hero"
            ctype = "troop"
        out.append({
            "card_id": "",
            "name": b,
            "elixir": r["elixir"],
            "elixir_variable": str(b in VARIABLE_ELIXIR).lower(),
            "rarity": "",
            "card_type": ctype,
            "has_evolution": str(any(x["_form"] == "evo" for x in fl)).lower(),
            "has_hero": str(any(x["_form"] == "hero" for x in fl)).lower(),
            "is_champion": str(b in CHAMPIONS).lower(),
            "is_win_condition": str(wc).lower(),
            "roles": roles,
            "targets": targets,
            "label_version": "v0-draft",
            "notes": note,
        })

    for b in sorted(set(forms) - set(base)):
        issues.append(f"Form rows with no base row: {[x['card_name'] for x in forms[b]]}.")
    for b in sorted(set(DRAFT) - set(base)):
        issues.append(f"Draft label for `{b}` has no row in the source CSV.")

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)

    n_evo = sum(r["has_evolution"] == "true" for r in out)
    n_hero = sum(r["has_hero"] == "true" for r in out)
    lines = [
        "# Card label bootstrap report",
        "",
        f"Source: `data/labels/source/cards_meta.csv` ({len(rows)} rows).",
        f"Output: `data/labels/cards.csv` ({len(out)} base cards, {n_evo} with Evolution, {n_hero} with Hero form, "
        f"{sum(r['is_champion'] == 'true' for r in out)} champions).",
        "",
        "Roles, targets, win conditions and the champion list are **drafts** (label_version `v0-draft`).",
        "Review them, fix anything you disagree with, and bump `label_version`.",
        "Rows with a note need your attention first.",
        "",
        "The meta columns in the source (rating, usage, win_rate, cwr) are not used by any model:",
        "the models learn only from battles collected through the official API.",
        "",
        "## Issues found in the source CSV",
        "",
        *[f"- {i}" for i in issues],
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} cards) and {REPORT} ({len(issues)} issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
