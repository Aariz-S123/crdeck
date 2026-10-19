"""Model-ready battles and the time split (spec section 9.4: never random)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .parse import OK


def model_battles(battles: pd.DataFrame, dib: pd.DataFrame) -> pd.DataFrame:
    """One row per OK battle: battle_key, battle_time, deck_a, deck_b, a_won, level gap, form_unknown."""
    ok = battles.loc[battles["status"] == OK, ["battle_key", "battle_time"]]
    a = dib[dib["side"] == "A"].set_index("battle_key")
    b = dib[dib["side"] == "B"].set_index("battle_key")
    df = ok.set_index("battle_key")
    # Explicit reindex: assigning a Series to an empty frame would adopt the Series' index.
    a, b = a.reindex(df.index), b.reindex(df.index)
    df["deck_a"] = a["deck_key"]
    df["deck_b"] = b["deck_key"]
    df["a_won"] = a["won"].astype(bool)
    df["level_gap"] = a["level_deficit"].astype(float) - b["level_deficit"].astype(float)
    # Skill proxy: Path of Legends rating at battle start (startingTrophies), A minus B.
    df["rating_diff"] = pd.to_numeric(a["trophies_or_rank"], errors="coerce") - pd.to_numeric(b["trophies_or_rank"], errors="coerce")
    df["form_unknown"] = a["form_unknown"].astype(bool) | b["form_unknown"].astype(bool)
    df = df.reset_index().sort_values(["battle_time", "battle_key"], kind="mergesort").reset_index(drop=True)
    return df


@dataclass
class Split:
    train: pd.DataFrame
    valid: pd.DataFrame
    test: pd.DataFrame

    @property
    def train_valid(self) -> pd.DataFrame:
        return pd.concat([self.train, self.valid], ignore_index=True)

    def window(self, part: str) -> tuple[str, str]:
        df = getattr(self, part)
        if df.empty:
            return ("n/a", "n/a")
        return (df["battle_time"].min().strftime("%Y-%m-%d %H:%M UTC"), df["battle_time"].max().strftime("%Y-%m-%d %H:%M UTC"))

    def describe(self) -> pd.DataFrame:
        rows = []
        for p in ("train", "valid", "test"):
            s, e = self.window(p)
            rows.append({"part": p, "battles": len(getattr(self, p)), "from": s, "to": e})
        return pd.DataFrame(rows)


def time_split(df: pd.DataFrame, train_frac: float, valid_frac: float) -> Split:
    """Earliest train_frac -> train, next valid_frac -> valid, rest -> test.

    Battles sharing the boundary timestamp all go to the earlier part, so no
    timestamp is split across parts.
    """
    if df.empty:
        raise ValueError("no OK battles to split")
    df = df.sort_values(["battle_time", "battle_key"], kind="mergesort").reset_index(drop=True)
    n = len(df)
    t1 = df["battle_time"].iloc[min(n - 1, max(0, int(n * train_frac) - 1))]
    t2 = df["battle_time"].iloc[min(n - 1, max(0, int(n * (train_frac + valid_frac)) - 1))]
    train = df[df["battle_time"] <= t1]
    valid = df[(df["battle_time"] > t1) & (df["battle_time"] <= t2)]
    test = df[df["battle_time"] > t2]
    return Split(train.reset_index(drop=True), valid.reset_index(drop=True), test.reset_index(drop=True))


def side_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Two rows per battle (deck_key, won) for deck-level statistics."""
    a = pd.DataFrame({"deck_key": df["deck_a"], "won": df["a_won"].astype(bool)})
    b = pd.DataFrame({"deck_key": df["deck_b"], "won": ~df["a_won"].astype(bool)})
    return pd.concat([a, b], ignore_index=True)
