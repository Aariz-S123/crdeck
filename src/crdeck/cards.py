"""Card table loading and validation (spec section 5).

Hand labels live in data/labels/cards.csv. card_id and rarity come from the API
/cards response via attach_api(); the join between the two is by normalized
name exactly once, here, and everything downstream joins on card_id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

ROLES = {
    "small_spell", "big_spell", "air_defense", "tank", "mini_tank",
    "splash", "building", "cycle", "tank_killer",
}
TARGETS = {"ground", "air_ground", "buildings", "none", "unknown"}
CARD_TYPES = {"troop", "spell", "building"}
FORMS = ("base", "evo", "hero")
BOOL_COLS = ["elixir_variable", "has_evolution", "has_hero", "is_champion", "is_win_condition"]
REQUIRED = [
    "card_id", "name", "elixir", "elixir_variable", "rarity", "card_type",
    "has_evolution", "has_hero", "is_champion", "is_win_condition",
    "roles", "targets", "label_version",
]


class CardTableError(ValueError):
    pass


def normalize_name(name: str) -> str:
    """'P.E.K.K.A' -> 'pekka', 'X-Bow' -> 'xbow'. Only used for the one-time label/API join."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "yes", "y"}:
        return True
    if s in {"false", "0", "no", "n", "", "nan", "none"}:
        return False
    raise CardTableError(f"not a boolean: {v!r}")


def load_labels(path: str | Path) -> pd.DataFrame:
    """Load and validate the hand-label table. Raises CardTableError listing every problem."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise CardTableError(f"missing columns: {missing}")
    if "notes" not in df.columns:
        df["notes"] = ""
    problems: list[str] = []
    for c in BOOL_COLS:
        try:
            df[c] = df[c].map(_to_bool)
        except CardTableError as e:
            problems.append(f"column {c}: {e}")
    df["elixir"] = pd.to_numeric(df["elixir"], errors="coerce")
    for _, r in df.iterrows():
        n = r["name"]
        if not n:
            problems.append("row with empty name")
        if r["card_type"] not in CARD_TYPES:
            problems.append(f"{n}: card_type {r['card_type']!r} not in {sorted(CARD_TYPES)}")
        if r["targets"] not in TARGETS:
            problems.append(f"{n}: targets {r['targets']!r} not in {sorted(TARGETS)}")
        for role in filter(None, r["roles"].split(";")):
            if role not in ROLES:
                problems.append(f"{n}: unknown role {role!r}")
        if pd.isna(r["elixir"]) and not r["elixir_variable"]:
            problems.append(f"{n}: elixir missing")
    dup = df["name"].map(normalize_name)
    for name in df.loc[dup.duplicated(), "name"]:
        problems.append(f"duplicate name {name!r}")
    if problems:
        raise CardTableError("card label table invalid:\n  " + "\n  ".join(problems))
    df["roles_list"] = df["roles"].map(lambda s: [x for x in s.split(";") if x])
    return df


@dataclass
class AttachReport:
    labels_without_api: list[str] = field(default_factory=list)
    api_without_labels: list[str] = field(default_factory=list)
    elixir_overrides: list[str] = field(default_factory=list)
    champion_overrides: list[str] = field(default_factory=list)
    evolution_overrides: list[str] = field(default_factory=list)
    hero_overrides: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = []
        for title, items in [
            ("Labeled cards with no API match (dropped until matched)", self.labels_without_api),
            ("API cards with no label row (UNKNOWN_CARD in battles)", self.api_without_labels),
            ("Elixir taken from API instead of label", self.elixir_overrides),
            ("is_champion taken from API rarity", self.champion_overrides),
            ("has_evolution taken from API maxEvolutionLevel", self.evolution_overrides),
            ("has_hero taken from API maxEvolutionLevel", self.hero_overrides),
        ]:
            out.append(f"{title}: {len(items)}")
            out.extend(f"  - {x}" for x in items)
        return out


def attach_api(labels: pd.DataFrame, cards_body: dict[str, Any]) -> tuple[pd.DataFrame, AttachReport]:
    """Join hand labels to the API /cards body ({"items": [...]}) by normalized name.

    API fields win for card_id, name, elixir, rarity, champion status, and form
    availability. Observed 2026-10-18: /cards `maxEvolutionLevel` is a bitmask
    (1 = Evolution form, 2 = Hero form, 3 = both; absent = neither), and every deck
    card is listed, so its absence means the card has no special form.
    """
    items = cards_body.get("items", [])
    api = {normalize_name(c["name"]): c for c in items}
    rep = AttachReport()
    rows = []
    for _, r in labels.iterrows():
        key = normalize_name(r["name"])
        c = api.get(key)
        if c is None:
            rep.labels_without_api.append(r["name"])
            continue
        row = r.to_dict()
        row["card_id"] = int(c["id"])
        row["name"] = c["name"]
        if "elixirCost" in c and not r["elixir_variable"]:
            if pd.isna(r["elixir"]) or int(r["elixir"]) != int(c["elixirCost"]):
                rep.elixir_overrides.append(f"{c['name']}: label {r['elixir']} -> API {c['elixirCost']}")
            row["elixir"] = int(c["elixirCost"])
        if "rarity" in c:
            row["rarity"] = str(c["rarity"]).lower()
            api_champ = row["rarity"] == "champion"
            if api_champ != r["is_champion"]:
                rep.champion_overrides.append(f"{c['name']}: label {r['is_champion']} -> API {api_champ}")
            row["is_champion"] = api_champ
        forms = int(c.get("maxEvolutionLevel") or 0)
        api_evo, api_hero = bool(forms & 1), bool(forms & 2)
        if api_evo != r["has_evolution"]:
            rep.evolution_overrides.append(f"{c['name']}: label {r['has_evolution']} -> API {api_evo}")
        if api_hero != r["has_hero"]:
            rep.hero_overrides.append(f"{c['name']}: label {r['has_hero']} -> API {api_hero}")
        row["has_evolution"], row["has_hero"] = api_evo, api_hero
        rows.append(row)
    labeled = {normalize_name(n) for n in labels["name"]}
    rep.api_without_labels = sorted(c["name"] for k, c in api.items() if k not in labeled)
    out = pd.DataFrame(rows)
    if out.empty:
        raise CardTableError("no label rows matched the API /cards response")
    out["card_id"] = out["card_id"].astype(int)
    return out.reset_index(drop=True), rep


@dataclass(frozen=True)
class Card:
    card_id: int
    name: str
    elixir: float | None
    elixir_variable: bool
    rarity: str
    card_type: str
    has_evolution: bool
    has_hero: bool
    is_champion: bool
    is_win_condition: bool
    roles: tuple[str, ...]
    targets: str

    def allowed_forms(self) -> tuple[str, ...]:
        forms = ["base"]
        if self.has_evolution:
            forms.append("evo")
        if self.has_hero:
            forms.append("hero")
        return tuple(forms)


class CardTable:
    """Card lookups by card_id (the canonical key) with name resolution for user input."""

    def __init__(self, df: pd.DataFrame):
        if df["card_id"].isna().any() or (df["card_id"].astype(str) == "").any():
            raise CardTableError("card table has rows without card_id; run attach_api first")
        self.df = df.reset_index(drop=True)
        self._by_id: dict[int, Card] = {}
        for _, r in self.df.iterrows():
            roles = r["roles_list"] if "roles_list" in r and isinstance(r["roles_list"], list) else [
                x for x in str(r["roles"]).split(";") if x
            ]
            elixir = None if pd.isna(r["elixir"]) else float(r["elixir"])
            card = Card(
                card_id=int(r["card_id"]), name=str(r["name"]), elixir=elixir,
                elixir_variable=bool(r["elixir_variable"]), rarity=str(r["rarity"]),
                card_type=str(r["card_type"]), has_evolution=bool(r["has_evolution"]),
                has_hero=bool(r["has_hero"]), is_champion=bool(r["is_champion"]),
                is_win_condition=bool(r["is_win_condition"]), roles=tuple(roles),
                targets=str(r["targets"]),
            )
            self._by_id[card.card_id] = card
        self._by_name = {normalize_name(c.name): c for c in self._by_id.values()}

    def __contains__(self, card_id: int) -> bool:
        return int(card_id) in self._by_id

    def __getitem__(self, card_id: int) -> Card:
        return self._by_id[int(card_id)]

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, card_id: int) -> Card | None:
        return self._by_id.get(int(card_id))

    @property
    def ids(self) -> list[int]:
        return sorted(self._by_id)

    def by_name(self, name: str) -> Card:
        c = self._by_name.get(normalize_name(name))
        if c is None:
            raise KeyError(f"no card named {name!r}")
        return c

    def name(self, card_id: int) -> str:
        c = self.get(card_id)
        return c.name if c else f"<unknown {card_id}>"


def save_card_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["roles_list"], errors="ignore").to_parquet(path, index=False)


def load_card_table(path: str | Path) -> CardTable:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it with `python -m crdeck build` after the API gate "
            "has saved a /cards response (or `--source synthetic` for synthetic data)."
        )
    df = pd.read_parquet(path)
    df["roles_list"] = df["roles"].map(lambda s: [x for x in str(s).split(";") if x])
    return CardTable(df)
