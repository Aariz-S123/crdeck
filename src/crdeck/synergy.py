"""Pair synergy with sample sizes and shrinkage (spec section 7.1).

Counting unit: one deck appearance = one side of one OK battle (mirrors and
draws are already excluded). Synergy is computed at card level (forms merged).

  rate(i)        = appearances with i / appearances
  co_rate(i,j)   = appearances with i and j / appearances
  lift(i,j)      = co_rate / (rate(i) rate(j))
  shrunk_wr(x)   = (wins + k g) / (games + k),   g = global win rate (0.5 after exclusions)
  expected_wr    = sigmoid(logit(swr_i) + logit(swr_j) - logit(g))
  synergy(i,j)   = shrunk_wr(i,j) - expected_wr(i,j)

expected_from chooses what "individual" win rate means:
  "marginal":        swr_i over all of i's games (the spec's literal reading).
                     When i and j nearly always co-occur, swr_i already contains
                     the pair's effect and the bonus is double-counted, which
                     pushes true synergies negative (seen on synthetic data with
                     planted pairs; see notebooks/05_models).
  "without_partner": swr_i over i's games without j (and vice versa), so the
                     comparison is literally "together vs separately". Default.

Interval: Beta(wins + k g, losses + k (1-g)) posterior quantiles of the pair win
rate, minus expected_wr (which is treated as fixed, so the interval is a little narrow).
Pairs with fewer than min_games get status INSUFFICIENT_SAMPLE and no score.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import beta as beta_dist

OK = "OK"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


def logit(p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def shrunk_rate(wins, games, k: float, g: float):
    return (np.asarray(wins, float) + k * g) / (np.asarray(games, float) + k)


def expected_pair_wr(swr_i, swr_j, g: float):
    return sigmoid(logit(swr_i) + logit(swr_j) - logit(g))


def deck_card_ids(deck_key: str) -> list[int]:
    return sorted({int(x.split(":")[0]) for x in deck_key.split("|") if x})


def card_matrix(deck_keys: pd.Series, card_index: dict[int, int]) -> sparse.csr_matrix:
    rows, cols = [], []
    for r, k in enumerate(deck_keys):
        for cid in deck_card_ids(k):
            j = card_index.get(cid)
            if j is not None:
                rows.append(r)
                cols.append(j)
    return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(deck_keys), len(card_index)))


@dataclass
class SynergyTable:
    cards: pd.DataFrame       # card_id, games, wins, rate, shrunk_wr
    pairs: pd.DataFrame       # card_i < card_j, games, wins, co_rate, lift, raw_wr, shrunk_wr, expected_wr, synergy, lo, hi, status
    k: float
    min_games: int
    global_wr: float
    n_appearances: int
    expected_from: str = "without_partner"
    log_lift: np.ndarray | None = None  # smoothed log((co + 1) / (expected_co + 1)) for every card pair

    def __post_init__(self):
        self._index = {(int(r.card_i), int(r.card_j)): i for i, r in enumerate(self.pairs.itertuples())}
        ids = self.cards["card_id"].astype(int).tolist()
        self.card_pos = {c: i for i, c in enumerate(ids)}
        n = len(ids)
        self.syn_matrix = np.full((n, n), np.nan)
        for r in self.pairs.itertuples():
            if r.status == OK:
                i, j = self.card_pos[int(r.card_i)], self.card_pos[int(r.card_j)]
                self.syn_matrix[i, j] = self.syn_matrix[j, i] = r.synergy

    def pair(self, a: int, b: int) -> dict | None:
        i, j = sorted((int(a), int(b)))
        idx = self._index.get((i, j))
        return None if idx is None else self.pairs.iloc[idx].to_dict()

    def deck_pairs(self, card_ids: list[int]) -> pd.DataFrame:
        """All pairs in a deck with their stats; unseen pairs appear with games=0 and INSUFFICIENT_SAMPLE."""
        rows = []
        for a, b in combinations(sorted(set(int(c) for c in card_ids)), 2):
            p = self.pair(a, b)
            if p is None:
                p = {"card_i": a, "card_j": b, "games": 0, "wins": 0, "co_rate": 0.0, "lift": np.nan,
                     "raw_wr": np.nan, "shrunk_wr": np.nan, "expected_wr": np.nan, "synergy": np.nan,
                     "lo": np.nan, "hi": np.nan, "status": INSUFFICIENT_SAMPLE}
            rows.append(p)
        return pd.DataFrame(rows)

    def mean_synergy(self, card_ids: list[int]) -> tuple[float, int]:
        """Mean synergy over scored pairs and the number of scored pairs (0.0, 0 if none)."""
        pos = [self.card_pos[c] for c in set(card_ids) if c in self.card_pos]
        if len(pos) < 2:
            return 0.0, 0
        sub = self.syn_matrix[np.ix_(pos, pos)]
        vals = sub[np.triu_indices(len(pos), 1)]
        vals = vals[~np.isnan(vals)]
        return (float(vals.mean()), int(len(vals))) if len(vals) else (0.0, 0)

    def mean_log_lift(self, card_ids: list[int]) -> float:
        """Mean smoothed log-lift over all deck pairs: how often players actually pair these cards."""
        pos = [self.card_pos[c] for c in set(card_ids) if c in self.card_pos]
        if len(pos) < 2 or self.log_lift is None:
            return 0.0
        sub = self.log_lift[np.ix_(pos, pos)]
        return float(sub[np.triu_indices(len(pos), 1)].mean())

    def mean_lift(self, card_ids: list[int]) -> float:
        lifts = [p["lift"] for a, b in combinations(sorted(set(card_ids)), 2) if (p := self.pair(a, b)) and p["games"] > 0]
        return float(np.mean(lifts)) if lifts else 1.0


def compute_synergy(sides: pd.DataFrame, k: float = 50, min_games: int = 200, interval: float = 0.90,
                    expected_from: str = "without_partner") -> SynergyTable:
    """sides: one row per deck appearance with columns deck_key, won (bool)."""
    if sides.empty:
        raise ValueError("no deck appearances")
    ids = sorted({c for k_ in sides["deck_key"] for c in deck_card_ids(k_)})
    index = {c: i for i, c in enumerate(ids)}
    X = card_matrix(sides["deck_key"], index)
    won = sides["won"].astype(float).to_numpy()
    n = X.shape[0]
    g = float(won.mean())

    games_c = np.asarray(X.sum(axis=0)).ravel()
    wins_c = np.asarray(X.T @ won).ravel()
    swr_c = shrunk_rate(wins_c, games_c, k, g)
    cards = pd.DataFrame({"card_id": ids, "games": games_c.astype(int), "wins": wins_c.astype(int),
                          "rate": games_c / n, "shrunk_wr": swr_c})

    co = (X.T @ X).toarray()
    W = (X.T @ sparse.diags(won) @ X).toarray()
    iu, ju = np.triu_indices(len(ids), 1)
    games = co[iu, ju]
    keep = games > 0
    iu, ju, games = iu[keep], ju[keep], games[keep]
    wins = W[iu, ju]
    co_rate = games / n
    lift = co_rate / (cards["rate"].to_numpy()[iu] * cards["rate"].to_numpy()[ju])
    swr = shrunk_rate(wins, games, k, g)
    if expected_from == "marginal":
        exp_wr = expected_pair_wr(swr_c[iu], swr_c[ju], g)
    elif expected_from == "without_partner":
        sw_i = shrunk_rate(wins_c[iu] - wins, games_c[iu] - games, k, g)
        sw_j = shrunk_rate(wins_c[ju] - wins, games_c[ju] - games, k, g)
        exp_wr = expected_pair_wr(sw_i, sw_j, g)
    else:
        raise ValueError(f"expected_from must be marginal or without_partner, got {expected_from!r}")
    a = wins + k * g
    b = (games - wins) + k * (1 - g)
    q = (1 - interval) / 2
    lo = beta_dist.ppf(q, a, b) - exp_wr
    hi = beta_dist.ppf(1 - q, a, b) - exp_wr
    ok = games >= min_games
    pairs = pd.DataFrame({
        "card_i": np.array(ids)[iu], "card_j": np.array(ids)[ju],
        "games": games.astype(int), "wins": wins.astype(int),
        "co_rate": co_rate, "lift": lift, "raw_wr": wins / games,
        "shrunk_wr": swr, "expected_wr": exp_wr,
        "synergy": np.where(ok, swr - exp_wr, np.nan),
        "lo": np.where(ok, lo, np.nan), "hi": np.where(ok, hi, np.nan),
        "status": np.where(ok, OK, INSUFFICIENT_SAMPLE),
    })
    rate = games_c / n
    log_lift = np.log((co + 1.0) / (n * np.outer(rate, rate) + 1.0))
    np.fill_diagonal(log_lift, 0.0)
    return SynergyTable(cards, pairs.reset_index(drop=True), k, min_games, g, n, expected_from, log_lift)
