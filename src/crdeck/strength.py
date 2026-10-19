"""Deck strength: which deck wins a battle (spec section 7.2).

Models (all linear in deck features, so a deck has a scalar utility u and
P(A beats B) = sigmoid(u(A) - u(B))):
- ConstantBaseline:    always 0.5
- PopularityBaseline:  "more popular deck wins"; u = beta * mean train usage rate of the deck's cards
- CardModel:           logistic regression on one-hot card:form difference (no intercept, symmetric)
- CardModel(pairs=…):  the same plus pair-presence features for the top-N synergy pairs

Feature keys: card_id:form. When hero form is not observable in battle data,
hero entries map onto the base key (and explanations carry FORM_UNKNOWN).

Skill control (spec 7.2 names skill as a confounder): with skill_control=True the
regression also gets the players' rating difference (Path of Legends rating at
battle start, per 100 points) as a separate covariate. Card weights are then
estimated at equal rating, and deck utilities / deck scores exclude the rating
term, i.e. they describe a deck in the hands of an equally rated player.
RatingBaseline (rating difference only) shows how much of any predictive power
is skill rather than deck.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

from .rules import DeckCard, parse_deck_key
from .synergy import SynergyTable, sigmoid


def feature_key(e: DeckCard, hero_observable: bool) -> str:
    if e.form == "hero" and not hero_observable:
        return f"{e.card_id}:base"
    return e.key


def deck_feature_keys(entries: list[DeckCard], hero_observable: bool) -> list[str]:
    return [feature_key(e, hero_observable) for e in entries]


RATING_SCALE = 100.0


def rating_diff(df: pd.DataFrame) -> np.ndarray:
    """A-minus-B rating difference per 100 points; 0 where unknown."""
    if "rating_diff" not in df:
        return np.zeros(len(df))
    return (pd.to_numeric(df["rating_diff"], errors="coerce").fillna(0.0) / RATING_SCALE).to_numpy()


class ConstantBaseline:
    name = "constant_0.5"

    def predict_proba(self, deck_a: pd.Series, deck_b: pd.Series) -> np.ndarray:
        return np.full(len(deck_a), 0.5)

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        return np.full(len(df), 0.5)


class RatingBaseline:
    """Skill only: logistic regression on the rating difference (no deck information)."""
    name = "rating_only"

    def fit(self, df: pd.DataFrame) -> "RatingBaseline":
        self.lr = LogisticRegression(fit_intercept=False, C=1e6, max_iter=1000)
        self.lr.fit(rating_diff(df).reshape(-1, 1), df["a_won"].astype(int))
        return self

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        return self.lr.predict_proba(rating_diff(df).reshape(-1, 1))[:, 1]


class PopularityBaseline:
    name = "popularity"

    def fit(self, df: pd.DataFrame) -> "PopularityBaseline":
        sides = pd.concat([df["deck_a"], df["deck_b"]], ignore_index=True)
        counts: dict[int, int] = {}
        for k in sides:
            for e in parse_deck_key(k):
                counts[e.card_id] = counts.get(e.card_id, 0) + 1
        n = len(sides)
        self.rate = {c: v / n for c, v in counts.items()}
        x = (self._pop(df["deck_a"]) - self._pop(df["deck_b"])).reshape(-1, 1)
        self.lr = LogisticRegression(fit_intercept=False, C=1e6, max_iter=1000).fit(x, df["a_won"].astype(int))
        return self

    def _pop(self, decks: pd.Series) -> np.ndarray:
        return np.array([np.mean([self.rate.get(e.card_id, 0.0) for e in parse_deck_key(k)]) for k in decks])

    def predict_proba(self, deck_a: pd.Series, deck_b: pd.Series) -> np.ndarray:
        x = (self._pop(deck_a) - self._pop(deck_b)).reshape(-1, 1)
        return self.lr.predict_proba(x)[:, 1]

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        return self.predict_proba(df["deck_a"], df["deck_b"])


@dataclass
class CardModel:
    hero_observable: bool
    C: float = 1.0
    max_iter: int = 5000
    min_feature_games: int = 20
    pairs: list[tuple[int, int]] = field(default_factory=list)
    name: str = "card_lr"
    skill_control: bool = False

    def _vector_rows(self, decks: pd.Series) -> sparse.csr_matrix:
        rows, cols = [], []
        for r, k in enumerate(decks):
            entries = parse_deck_key(k)
            for fk in deck_feature_keys(entries, self.hero_observable):
                j = self.index.get(fk)
                if j is not None:
                    rows.append(r)
                    cols.append(j)
            if self.pairs:
                ids = {e.card_id for e in entries}
                for p, (a, b) in enumerate(self.pairs):
                    if a in ids and b in ids:
                        rows.append(r)
                        cols.append(self.n_card_features + p)
        shape = (len(decks), self.n_card_features + len(self.pairs))
        return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=shape)

    def fit(self, df: pd.DataFrame) -> "CardModel":
        counts: dict[str, int] = {}
        for k in pd.concat([df["deck_a"], df["deck_b"]]):
            for fk in deck_feature_keys(parse_deck_key(k), self.hero_observable):
                counts[fk] = counts.get(fk, 0) + 1
        self.feature_games = counts
        keys = sorted(k for k, v in counts.items() if v >= self.min_feature_games)
        self.index = {k: i for i, k in enumerate(keys)}
        self.n_card_features = len(keys)
        X = self._vector_rows(df["deck_a"]) - self._vector_rows(df["deck_b"])
        if self.skill_control:
            # Scale the rating column up so the L2 penalty on its coefficient is negligible:
            # coefficient g on (s * x) means effect g * s, penalised as g^2 = effect^2 / s^2.
            self._skill_scale = 100.0 / np.sqrt(self.C)
            X = sparse.hstack([X, sparse.csr_matrix(self._skill_scale * rating_diff(df).reshape(-1, 1))]).tocsr()
        y = df["a_won"].astype(int).to_numpy()
        self.lr = LogisticRegression(fit_intercept=False, C=self.C, max_iter=self.max_iter, solver="lbfgs")
        self.lr.fit(X, y)
        full = self.lr.coef_.ravel()
        n_deck = self.n_card_features + len(self.pairs)
        self.coef = full[:n_deck]  # deck-only weights: utilities and deck scores never include skill
        self.skill_coef = float(full[n_deck]) * self._skill_scale if self.skill_control else 0.0  # per 100 rating
        # Laplace approximation of coefficient uncertainty: (X' W X + I / C)^-1, marginal over the skill term
        p = sigmoid(X @ full)
        H = (X.T @ sparse.diags(p * (1 - p)) @ X).toarray() + np.eye(X.shape[1]) / self.C
        self.cov = np.linalg.pinv(H)[:n_deck, :n_deck]
        self.card_weights = dict(zip(keys, self.coef[: self.n_card_features]))
        self.pair_weights = dict(zip(self.pairs, self.coef[self.n_card_features:]))
        return self

    def utility(self, entries: list[DeckCard]) -> float:
        u = sum(self.card_weights.get(fk, 0.0) for fk in deck_feature_keys(entries, self.hero_observable))
        if self.pairs:
            ids = {e.card_id for e in entries}
            u += sum(w for (a, b), w in self.pair_weights.items() if a in ids and b in ids)
        return float(u)

    def utilities(self, decks: pd.Series) -> np.ndarray:
        return self._vector_rows(decks) @ self.coef

    def vector(self, entries: list[DeckCard]) -> np.ndarray:
        from .rules import deck_key
        return self._vector_rows(pd.Series([deck_key(entries)])).toarray().ravel()

    def predict_proba(self, deck_a: pd.Series, deck_b: pd.Series) -> np.ndarray:
        """Deck-only prediction (equal rating)."""
        return sigmoid(self.utilities(deck_a) - self.utilities(deck_b))

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        """Prediction for real battles: deck utilities plus the rating term when skill-controlled."""
        z = self.utilities(df["deck_a"]) - self.utilities(df["deck_b"])
        return sigmoid(z + self.skill_coef * rating_diff(df))

    def known(self, e: DeckCard) -> bool:
        return feature_key(e, self.hero_observable) in self.index

    def games(self, e: DeckCard) -> int:
        return self.feature_games.get(feature_key(e, self.hero_observable), 0)


def top_pairs(syn: SynergyTable, n: int) -> list[tuple[int, int]]:
    ok = syn.pairs[syn.pairs["status"] == "OK"].copy()
    ok["abs"] = ok["synergy"].abs()
    ok = ok.sort_values(["abs", "games"], ascending=[False, False]).head(n)
    return [(int(a), int(b)) for a, b in zip(ok["card_i"], ok["card_j"])]


def evaluate(model, df: pd.DataFrame) -> dict:
    p = model.predict_df(df)
    y = df["a_won"].astype(int).to_numpy()
    out = {"model": model.name, "battles": len(df), "log_loss": float(log_loss(y, p, labels=[0, 1]))}
    out["auc"] = float(roc_auc_score(y, p)) if len(set(y)) > 1 and np.ptp(p) > 0 else 0.5
    return out


@dataclass
class DeckScore:
    win_prob: float
    lo: float
    hi: float
    n_opponents: int
    interval: float
    sd_model: float = 0.0
    sd_opponents: float = 0.0


class MetaScorer:
    """Average win probability against the test-window opponent-deck distribution."""

    def __init__(self, model: CardModel, opponent_decks: pd.Series, n_opponents: int, n_bootstrap: int,
                 interval: float, seed: int):
        rng = np.random.default_rng(seed)
        decks = opponent_decks.reset_index(drop=True)
        if len(decks) > n_opponents:
            decks = decks.iloc[np.sort(rng.choice(len(decks), n_opponents, replace=False))]
        self.opp_X = model._vector_rows(decks)
        self.opp_u = self.opp_X @ model.coef
        self.model = model
        self.interval = interval

    def win_prob_from_u(self, u: float) -> float:
        return float(sigmoid(u - self.opp_u).mean())

    def score(self, entries: list[DeckCard]) -> DeckScore:
        """Win prob vs the opponent sample, with an approximate interval combining
        model uncertainty (Laplace, delta method) and opponent sampling (standard error
        of the mean over the opponent sample; the analytic form of the bootstrap SE, so the
        web port reproduces it exactly).
        It does not cover selection effects: the top result of a search is the
        maximum of noisy estimates and is likely optimistic."""
        from scipy.stats import norm
        u = self.model.utility(entries)
        p = sigmoid(u - self.opp_u)
        mean = float(p.mean())
        sd_opp = float(p.std() / np.sqrt(len(p)))
        w = p * (1 - p)
        grad = self.model.vector(entries) * w.mean() - np.asarray(self.opp_X.multiply(w[:, None]).mean(axis=0)).ravel()
        sd_model = float(np.sqrt(max(grad @ self.model.cov @ grad, 0.0)))
        z = norm.ppf(1 - (1 - self.interval) / 2)
        sd = np.hypot(sd_model, sd_opp)
        return DeckScore(mean, max(0.0, mean - z * sd), min(1.0, mean + z * sd), len(self.opp_u), self.interval,
                         sd_model, sd_opp)
