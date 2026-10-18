"""Archetype classification (spec section 7.3).

Labels: data/labels/archetype_labels.csv (real) with columns
  deck_key, archetype, split (train | heldout), labeled_at, notes
Label the 20 heldout decks before fitting or tuning anything.

Clustering is used only to choose decks worth labeling (suggest_decks_to_label).
Prediction returns the top label and its probability; below the threshold the
label is HYBRID / UNCERTAIN.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression

from .cards import ROLES, CardTable
from .rules import DeckCard, parse_deck_key

ARCHETYPES = ["Beatdown", "Cycle", "Control", "Siege", "Bait", "Bridge Spam", "Graveyard", "Hybrid"]
UNCERTAIN = "HYBRID / UNCERTAIN"
NO_LABELS = "NO_LABELS"
LABEL_COLUMNS = ["deck_key", "archetype", "split", "labeled_at", "notes"]
ROLE_LIST = sorted(ROLES)


class ArchetypeLabelError(ValueError):
    pass


def deck_features(entries: list[DeckCard], cards: CardTable, card_index: dict[int, int]) -> np.ndarray:
    v = np.zeros(len(card_index) + len(ROLE_LIST) + 3)
    elixirs = []
    for e in entries:
        j = card_index.get(e.card_id)
        if j is not None:
            v[j] = 1.0
        c = cards.get(e.card_id)
        if c is None:
            continue
        for r in c.roles:
            v[len(card_index) + ROLE_LIST.index(r)] += 1
        if c.elixir is not None and not c.elixir_variable:
            elixirs.append(c.elixir)
        v[-2] += c.is_win_condition
        v[-1] += c.card_type == "spell"
    v[-3] = np.mean(elixirs) if elixirs else 0.0
    return v


def load_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LABEL_COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in LABEL_COLUMNS[:3] if c not in df.columns]
    if missing:
        raise ArchetypeLabelError(f"{path}: missing columns {missing}")
    df = df[df["archetype"].str.strip() != ""].copy()
    bad = sorted(set(df["archetype"]) - set(ARCHETYPES))
    if bad:
        raise ArchetypeLabelError(f"{path}: unknown archetypes {bad}; allowed {ARCHETYPES}")
    bad_split = sorted(set(df["split"]) - {"train", "heldout"})
    if bad_split:
        raise ArchetypeLabelError(f"{path}: split must be train or heldout, got {bad_split}")
    dup = df["deck_key"][df["deck_key"].duplicated()]
    if len(dup):
        raise ArchetypeLabelError(f"{path}: duplicate deck_key rows: {list(dup)[:3]}")
    return df.reset_index(drop=True)


@dataclass
class ArchetypePrediction:
    label: str
    probability: float | None
    probabilities: dict[str, float]
    status: str = "OK"


class ArchetypeModel:
    def __init__(self, cards: CardTable, threshold: float = 0.5, C: float = 1.0, seed: int = 42):
        self.cards = cards
        self.threshold = threshold
        self.C = C
        self.seed = seed
        self.card_index = {c: i for i, c in enumerate(cards.ids)}
        self.fitted = False

    def _X(self, deck_keys) -> np.ndarray:
        return np.vstack([deck_features(parse_deck_key(k), self.cards, self.card_index) for k in deck_keys])

    def fit(self, labels: pd.DataFrame) -> "ArchetypeModel":
        train = labels[labels["split"] == "train"]
        if train["archetype"].nunique() < 2:
            raise ArchetypeLabelError("need train labels for at least 2 archetypes")
        self.lr = LogisticRegression(C=self.C, max_iter=5000, random_state=self.seed)
        self.lr.fit(self._X(train["deck_key"]), train["archetype"])
        self.classes = list(self.lr.classes_)
        self.n_train = len(train)
        self.fitted = True
        return self

    def predict(self, entries: list[DeckCard]) -> ArchetypePrediction:
        if not self.fitted:
            return ArchetypePrediction(NO_LABELS, None, {}, status=NO_LABELS)
        x = deck_features(entries, self.cards, self.card_index).reshape(1, -1)
        p = self.lr.predict_proba(x)[0]
        probs = dict(zip(self.classes, map(float, p)))
        top = max(probs, key=probs.get)
        label = top if probs[top] >= self.threshold else UNCERTAIN
        return ArchetypePrediction(label, probs[top], probs)

    def evaluate_heldout(self, labels: pd.DataFrame) -> dict:
        held = labels[labels["split"] == "heldout"]
        train = labels[labels["split"] == "train"]
        if held.empty:
            return {"status": "NO_HELDOUT_LABELS"}
        pred = [max(zip(self.lr.predict_proba(self._X([k]))[0], self.classes))[1] for k in held["deck_key"]]
        majority = train["archetype"].value_counts().idxmax()
        return {
            "heldout_decks": len(held),
            "accuracy": float(np.mean(np.array(pred) == held["archetype"].to_numpy())),
            "majority_class": majority,
            "majority_accuracy": float(np.mean(held["archetype"].to_numpy() == majority)),
        }


def suggest_decks_to_label(decks: pd.DataFrame, cards: CardTable, n_clusters: int, per_cluster: int,
                           seed: int, exclude: set[str] | None = None) -> pd.DataFrame:
    """Pick frequent decks spread across k-means clusters of deck vectors, as a labeling worklist."""
    exclude = exclude or set()
    d = decks[~decks["deck_key"].isin(exclude)].sort_values("appearances", ascending=False).head(3000)
    if d.empty:
        return pd.DataFrame(columns=["cluster", "appearances", "deck_key", "cards", *LABEL_COLUMNS[1:]])
    idx = {c: i for i, c in enumerate(cards.ids)}
    X = np.vstack([deck_features(parse_deck_key(k), cards, idx)[: len(idx)] for k in d["deck_key"]])
    k = min(n_clusters, len(d))
    km = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(X)
    d = d.assign(cluster=km.labels_)
    picks = d.groupby("cluster", group_keys=False).head(per_cluster)
    out = picks[["cluster", "appearances", "deck_key"]].copy()
    out["cards"] = out["deck_key"].map(lambda k: ", ".join(
        cards.name(e.card_id) + ("" if e.form == "base" else f" ({e.form})") for e in parse_deck_key(k)))
    for c in LABEL_COLUMNS[1:]:
        out[c] = ""
    return out.sort_values(["cluster", "appearances"], ascending=[True, False]).reset_index(drop=True)
