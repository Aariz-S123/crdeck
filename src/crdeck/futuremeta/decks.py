"""Deck estimates in a field, own records, and the recommendation lists with their forward check.

The matchup model at origin o is fitted on battles up to the end of period o-2, so period o-1 is out of sample for it.
Definitions: docs/future-meta/DESIGN.md. Everything here reads battles and fits its own models; it never touches the
exported models.

Win measures use only battles with a known rating gap. Without one, a skill gap can't be told from a deck's strength: right after a
season reset, logs carry no ratings while top players meet weaker opponents, which would inflate every deck they play.
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from ..counters import observed_decks
from ..matchup import MatchupModel
from ..rules import check_deck, parse_deck_key
from ..strength import RatingBaseline
from .data import RankedData
from .forecasting import sigmoid


# ---------------------------------------------------------------- models per origin

def fit_model(data: RankedData, o: int, cfg: dict, model_cfg: dict, cache: Path, verbose: bool = True) -> MatchupModel:
    """The matchup model for origin o (cached): battles played up to the end of period o-2 and fetched by the origin."""
    b = data.battles
    keep = (b["t"] <= data.periods["end"].iloc[o - 2]) & (b["first_seen"] <= data.periods["end"].iloc[o - 1]) & b["rating_diff"].notna()
    df = b[keep].reset_index(drop=True)
    tag = hashlib.sha1("|".join([str(len(df)), str(df["battle_key"].iloc[-1]), str(cfg["matchup"]["C"]),
                                 str(model_cfg["matchup"]["min_pair_battles"]), str(model_cfg["strength"]["min_feature_games"])]).encode()).hexdigest()[:16]
    f = cache / f"matchup_{tag}.pkl"
    if f.exists():
        with f.open("rb") as fh:
            return pickle.load(fh)
    m = MatchupModel(C=float(cfg["matchup"]["C"]), min_pair_battles=int(model_cfg["matchup"]["min_pair_battles"]),
                     min_card_games=int(model_cfg["strength"]["min_feature_games"]), max_iter=int(model_cfg["matchup"]["max_iter"])).fit(df)
    if verbose:
        print(f"matchup model for origin {o}: {len(df)} battles, {len(m.pairs)} pairs", flush=True)
    with f.open("wb") as fh:
        pickle.dump(m, fh)
    return m


@dataclass
class Weights:
    w: np.ndarray    # [keys]
    K: np.ndarray    # [keys, keys]: K[i, j] is card form i's weight against j
    rating: float    # log-odds per 100 rating points


def weights_of(model: MatchupModel, keys: list[str]) -> Weights:
    idx = {k: i for i, k in enumerate(keys)}
    w, K = np.zeros(len(keys)), np.zeros((len(keys), len(keys)))
    for k, v in model.w.items():
        if k in idx:
            w[idx[k]] = v
    for (i, j), v in model.K.items():
        if i in idx and j in idx:
            K[idx[i], idx[j]], K[idx[j], idx[i]] = v, -v
    return Weights(w, K, float(model.rating_coef))


def mean_log_odds(members: sparse.csr_matrix, W: Weights, S: np.ndarray) -> np.ndarray:
    """z(A | s) without the deck's own record: [runs, decks] for card shares S [runs, keys]. Exact for the mean log-odds
    against a field with these shares, because the mean over opponent decks of a sum over their cards needs only each card's share."""
    own = members @ W.w
    field_mean = S @ W.w
    fit = (members @ (W.K @ S.T)).T
    return own[None, :] - field_mean[:, None] + fit


def exact_field_gap(members: sparse.csr_matrix, opponents: sparse.csr_matrix, W: Weights) -> dict:
    """How far sigmoid(mean z) is from the mean of sigmoid(z) on a real field (real decks, each weighted once)."""
    own, opp = members @ W.w, opponents @ W.w
    z = own[:, None] - opp[None, :] + (members @ W.K @ opponents.T.toarray() if opponents.shape[0] else 0)
    exact, approx = sigmoid(z).mean(axis=1), sigmoid(z.mean(axis=1))
    return {"decks": int(members.shape[0]), "opponents": int(opponents.shape[0]), "mean_abs_points": float(np.mean(np.abs(exact - approx)) * 100),
            "max_abs_points": float(np.max(np.abs(exact - approx)) * 100)}


# ---------------------------------------------------------------- a deck's own record, out of sample

@dataclass
class Record:
    decks: dict[str, int]     # deck -> row
    n: np.ndarray
    raw: np.ndarray
    v: np.ndarray
    mean: np.ndarray          # posterior mean of delta
    var: np.ndarray           # posterior variance of delta
    tau2: float
    mu: float


def own_record(data: RankedData, model: MatchupModel, o: int, min_games_tau: int) -> Record:
    """Residuals of period o-1's battles (fetched by the origin) under the model that has not seen them, per deck, then
    empirical Bayes: few games means the record barely counts."""
    b = data.battles
    df = b[(b["t"] > data.periods["start"].iloc[o - 1]) & (b["t"] <= data.periods["end"].iloc[o - 1]) & (b["first_seen"] <= data.periods["end"].iloc[o - 1]) & b["rating_diff"].notna()]
    df = df.reset_index(drop=True)
    p = np.clip(model.predict_df(df), 1e-9, 1 - 1e-9)
    y = df["a_won"].astype(float).to_numpy()
    info = p * (1 - p)
    rows = pd.DataFrame({"deck": np.r_[df["deck_a"].to_numpy(), df["deck_b"].to_numpy()], "res": np.r_[y - p, p - y], "info": np.r_[info, info]})
    g = rows.groupby("deck", sort=True).agg(n=("res", "size"), res=("res", "sum"), info=("info", "sum"))
    raw, v = (g["res"] / g["info"]).to_numpy(), (1 / g["info"]).to_numpy()
    big = g["n"].to_numpy() >= min_games_tau
    if big.sum() >= 2:
        prec = 1 / v[big]
        mu = float(np.sum(prec * raw[big]) / prec.sum())
        tau2 = float(max(0.0, np.mean((raw[big] - mu) ** 2) - np.mean(v[big])))
    else:
        mu, tau2 = 0.0, 0.0
    shrink = tau2 / (tau2 + v)
    return Record({d: i for i, d in enumerate(g.index)}, g["n"].to_numpy(), raw, v, shrink * (raw - mu), shrink * v, tau2, mu)


def record_for(rec: Record, decks: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Posterior mean and variance for these decks. A deck with no games in the period keeps the prior: mean 0, variance tau^2."""
    idx = [rec.decks.get(d, -1) for d in decks]
    mean = np.array([rec.mean[i] if i >= 0 else 0.0 for i in idx])
    var = np.array([rec.var[i] if i >= 0 else rec.tau2 for i in idx])
    return mean, var


# ---------------------------------------------------------------- adjusted results

def side_rows(df: pd.DataFrame, expected_a: np.ndarray) -> pd.DataFrame:
    """One row per side: deck, player, won, expected win chance from the rating gap alone."""
    y = df["a_won"].astype(float).to_numpy()
    return pd.DataFrame({"deck": np.r_[df["deck_a"].to_numpy(), df["deck_b"].to_numpy()], "player": np.r_[df["player_a"].to_numpy(), df["player_b"].to_numpy()],
                         "y": np.r_[y, 1 - y], "exp": np.r_[expected_a, 1 - expected_a]})


def rating_model(data: RankedData, moment) -> RatingBaseline:
    b = data.battles
    return RatingBaseline().fit(b[(b["t"] <= moment) & (b["first_seen"] <= moment) & b["rating_diff"].notna()])


def period_battles(data: RankedData, periods: range | list[int], moment=None) -> pd.DataFrame:
    """OK battles with a known rating gap in these periods; with `moment`, only those fetched by then."""
    b = data.battles
    start, end = data.periods["start"].iloc[min(periods)], data.periods["end"].iloc[max(periods)]
    keep = (b["t"] > start) & (b["t"] <= end) & b["rating_diff"].notna()
    if moment is not None:
        keep &= b["first_seen"] <= moment
    return b[keep].reset_index(drop=True)


def adjusted(rows: pd.DataFrame) -> pd.DataFrame:
    """Per deck: games, wins, expected wins, adjusted win rate."""
    g = rows.groupby("deck", sort=False).agg(n=("y", "size"), wins=("y", "sum"), exp=("exp", "sum"))
    g["adj"] = 0.5 + (g["wins"] - g["exp"]) / g["n"]
    return g


# ---------------------------------------------------------------- candidates and lists

def legal_decks(data: RankedData, decks: list[str], memo: dict[str, bool]) -> list[str]:
    out = []
    for d in decks:
        if d not in memo:
            ents = parse_deck_key(d)
            memo[d] = len(ents) == data.rules.deck_size and check_deck(ents, data.cards, data.rules).legal
        if memo[d]:
            out.append(d)
    return out


@dataclass
class Scored:
    origin: int
    decks: list[str]
    members: sparse.csr_matrix
    runs: np.ndarray           # [runs, decks]: the Monte Carlo's estimates
    current: np.ndarray        # same estimate in last period's field, with the record
    cards_only: np.ndarray     # current field, no record
    delta: np.ndarray
    delta_var: np.ndarray
    games: np.ndarray          # OK games over the candidate periods
    played_last: np.ndarray    # appearances in the last period
    record: pd.DataFrame       # adjusted results over the candidate periods, per deck
    field_now: np.ndarray      # [keys] last period's shares
    weights: Weights
    tau2: float

    @property
    def mean(self) -> np.ndarray:
        return self.runs.mean(axis=0)

    def top_share(self, top: int) -> np.ndarray:
        """Chance of being among the top `top` candidates across the runs."""
        order = np.argsort(-self.runs, axis=1, kind="stable")[:, :top]
        counts = np.bincount(order.ravel(), minlength=self.runs.shape[1])
        return counts / self.runs.shape[0]


def score_origin(data: RankedData, o: int, W: Weights, rec: Record, sims: np.ndarray, field_now: np.ndarray, cfg: dict, memo: dict[str, bool]) -> Scored:
    """Every candidate deck at origin o across the simulated fields."""
    dc = cfg["decks"]
    moment = data.end(o - 1)
    first = max(0, o - int(dc["candidate_periods"]))
    known = data.known_at(moment)
    in_window = known & data.usable & (data.period >= first) & (data.period <= o - 1)
    games_all = np.bincount(data.deck[in_window], minlength=len(data.decks))
    played_all = np.bincount(data.deck[known & (data.period == o - 1)], minlength=len(data.decks))
    cand_idx = np.flatnonzero(games_all >= int(dc["min_games_candidate"]))
    decks = legal_decks(data, [data.decks[i] for i in cand_idx], memo)
    legal = set(decks)
    keep = [i for i in cand_idx if data.decks[i] in legal]
    members = data.membership[keep]
    delta, var = record_for(rec, decks)
    rng = np.random.default_rng(int(cfg["seed"]) + 1000 + o)
    z = mean_log_odds(members, W, sims)
    draws = delta[None, :] + np.sqrt(var)[None, :] * rng.standard_normal(z.shape)
    runs = sigmoid(z + draws)
    z_now = mean_log_odds(members, W, field_now[None, :])[0]
    rm = rating_model(data, data.periods["end"].iloc[o - 1])
    window = period_battles(data, range(first, o), data.periods["end"].iloc[o - 1])
    record = adjusted(side_rows(window, rm.predict_df(window)))
    return Scored(o, decks, members, runs, sigmoid(z_now + delta), sigmoid(z_now), delta, var, games_all[keep], played_all[keep], record, field_now, W, rec.tau2)


def ranked_list(s: Scored, values: np.ndarray, top: int, min_diff: int) -> list[str]:
    objectives = {d: float(v) for d, v in zip(s.decks, values)}
    return observed_decks([(d, 0) for d in s.decks], objectives, [], top, min_diff)


LISTS = ("future_field", "current_field", "cards_only", "last_record", "most_played")


def lists_at(s: Scored, top: int, min_diff: int) -> dict[str, list[str]]:
    rec = s.record["adj"].reindex(s.decks).fillna(0.5).to_numpy()
    return {"future_field": ranked_list(s, s.mean, top, min_diff), "current_field": ranked_list(s, s.current, top, min_diff),
            "cards_only": ranked_list(s, s.cards_only, top, min_diff), "last_record": ranked_list(s, rec, top, min_diff),
            "most_played": ranked_list(s, s.played_last.astype(float), top, min_diff), "all_candidates": list(s.decks)}


def target_rows(data: RankedData, o: int) -> pd.DataFrame:
    """Sides of period o's OK battles with the rating-only expectation, and whether the player is new to that deck
    (no earlier game with it, in any battle played before the origin)."""
    moment = data.periods["end"].iloc[o - 1]
    df = period_battles(data, [o])
    rows = side_rows(df, rating_model(data, moment).predict_df(df))
    b = data.battles
    old = b[b["t"] <= moment]
    seen = pd.Index(np.r_[(old["player_a"] + "|" + old["deck_a"]).to_numpy(), (old["player_b"] + "|" + old["deck_b"]).to_numpy()]).unique()
    rows["new"] = ~pd.Index(rows["player"] + "|" + rows["deck"]).isin(seen)
    return rows


def pooled_check(frames: list[pd.DataFrame], memberships: list[dict[str, set[str]]], names: list[str], n_boot: int, seed: int, min_games: int) -> dict:
    """Adjusted win rate per list, pooled over origins, and paired player-bootstrap differences against the recommender,
    for new-to-deck players (primary) and all players."""
    all_rows = []
    for f, mem in zip(frames, memberships):
        bits = {n: f["deck"].isin(mem[n]).to_numpy() for n in names}
        keep = np.any(np.stack(list(bits.values())), axis=0)
        part = f.loc[keep, ["player", "y", "exp", "new"]].copy()
        for n in names:
            part[n] = bits[n][keep]
        all_rows.append(part)
    rows = pd.concat(all_rows, ignore_index=True)
    out = {}
    for pop, sel in (("new_to_deck", rows["new"].to_numpy()), ("all_players", np.ones(len(rows), dtype=bool))):
        r = rows[sel]
        players, inv = np.unique(r["player"].to_numpy(), return_inverse=True)
        diff = (r["y"] - r["exp"]).to_numpy()
        mem = np.stack([r[n].to_numpy() for n in names]).astype(float)
        games = mem.sum(axis=1)
        rng = np.random.default_rng(seed)
        boot = np.empty((n_boot, len(names)))
        for b in range(n_boot):
            w = rng.multinomial(len(players), np.full(len(players), 1 / len(players))).astype(float)[inv]
            with np.errstate(invalid="ignore", divide="ignore"):
                boot[b] = (mem @ (w * diff)) / (mem @ w)
        point = {n: (float(0.5 + (mem[i] @ diff) / games[i]) if games[i] else None) for i, n in enumerate(names)}
        res = {"players": int(len(players)), "lists": {}}
        base = names.index("future_field")
        for i, n in enumerate(names):
            d = boot[:, base] - boot[:, i]
            enough = bool(games[i] >= min_games and games[base] >= min_games)
            lo, hi = (float(np.nanquantile(d, 0.05)), float(np.nanquantile(d, 0.95))) if i != base and games[i] and games[base] else (None, None)
            res["lists"][n] = {"games": int(games[i]), "adjusted_win_rate": point[n],
                               "range": ([float(np.nanquantile(boot[:, i], 0.05) + 0.5), float(np.nanquantile(boot[:, i], 0.95) + 0.5)] if games[i] else None),
                               "difference": (None if i == base or point[n] is None or point["future_field"] is None else point["future_field"] - point[n]),
                               "difference_range": None if i == base else [lo, hi], "enough_games": enough,
                               "verdict": (None if i == base else "too_few" if not enough else "better" if lo > 0 else "worse" if hi < 0 else "not_clear")}
        out[pop] = res
    return out


def range_check(s: Scored, adj: pd.DataFrame, min_games: int) -> list[tuple[float, float, float, int]]:
    """(estimate, spread, real adjusted win rate, games) for candidates with enough games in the target period."""
    mean, var = s.runs.mean(axis=0), s.runs.var(axis=0)
    out = []
    for i, d in enumerate(s.decks):
        if d in adj.index and adj.at[d, "n"] >= min_games:
            n = float(adj.at[d, "n"])
            out.append((float(mean[i]), float(np.sqrt(var[i] + mean[i] * (1 - mean[i]) / n)), float(adj.at[d, "adj"]), int(n)))
    return out


def pick_games(s: Scored, picked: list[str], side: pd.DataFrame) -> list[tuple[float, int, int]]:
    """(estimate when picked, games in the target period, of which by players new to the deck) for each listed deck."""
    pos = {d: i for i, d in enumerate(s.decks)}
    mean = s.mean
    rows = side[side["deck"].isin(picked)]
    games = rows["deck"].value_counts()
    new = rows.loc[rows["new"], "deck"].value_counts()
    return [(float(mean[pos[d]]), int(games.get(d, 0)), int(new.get(d, 0))) for d in picked]


def picks_estimate(picks: list[tuple[float, int, int]]) -> dict:
    """What past picks were estimated to win when picked, weighted by the games they then got. Compared on the page with what
    those games really won: the top of many noisy estimates tends to be too high, and this measures by how much."""
    a = np.array(picks, dtype=float).reshape(-1, 3)
    mean = lambda w: float(np.sum(a[:, 0] * w) / np.sum(w)) if np.sum(w) else None  # noqa: E731
    return {"listed": int(len(a)), "mean_at_listing": float(a[:, 0].mean()) if len(a) else None, "all_players": mean(a[:, 1]), "new_to_deck": mean(a[:, 2])}


def rank_correlation(values: dict[str, np.ndarray], s: Scored, adj: pd.DataFrame, min_games: int) -> dict[str, float | None]:
    """Spearman correlation between a ranking and the real adjusted win rate, among candidates with enough target games."""
    pick = [i for i, d in enumerate(s.decks) if d in adj.index and adj.at[d, "n"] >= min_games]
    if len(pick) < 5:
        return {k: None for k in values}
    truth = pd.Series([adj.at[s.decks[i], "adj"] for i in pick])
    return {k: float(pd.Series(v[pick]).corr(truth, method="spearman")) for k, v in values.items()}
