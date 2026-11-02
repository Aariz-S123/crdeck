"""What goes with a deck winning more, or being used more, in the next period (docs/future-meta/DESIGN.md).

A row is one deck at one transition: signals at the end of period t, results in period t+1. Signals use battles played
and fetched by the end of period t. The model is a weighted ridge regression on standardized signals, so a deck's prediction
splits exactly into one part per signal, which is the explanation the page shows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ..rules import parse_deck_key
from .data import RankedData
from .decks import Record, Weights, adjusted, record_for
from .forecasting import logit

NUMERIC = ["own_record", "card_strength", "field_fit", "usage", "momentum", "breadth", "return_rate", "player_rating", "elixir",
           "spells", "buildings", "win_conditions", "air_defense", "splash", "evolutions", "heroes"]
STYLE_PREFIX = "style:"


def card_facts(data: RankedData) -> dict[int, dict]:
    df = data.cards.df
    facts = {}
    for r in df.itertuples():
        roles = set(str(r.roles).split(";")) if isinstance(r.roles, str) else set()
        facts[int(r.card_id)] = {"elixir": float(r.elixir) if pd.notna(r.elixir) else np.nan, "spell": r.card_type == "spell", "building": r.card_type == "building",
                                 "win": bool(r.is_win_condition), "air": "air_defense" in roles, "splash": "splash" in roles}
    return facts


def deck_traits(deck: str, facts: dict[int, dict]) -> dict[str, float]:
    ents = parse_deck_key(deck)
    got = [facts.get(int(e.card_id), {}) for e in ents]
    costs = [f.get("elixir", np.nan) for f in got]
    return {"elixir": float(np.nanmean(costs)) if np.isfinite(costs).any() else np.nan, "spells": sum(bool(f.get("spell")) for f in got),
            "buildings": sum(bool(f.get("building")) for f in got), "win_conditions": sum(bool(f.get("win")) for f in got),
            "air_defense": sum(bool(f.get("air")) for f in got), "splash": sum(bool(f.get("splash")) for f in got),
            "evolutions": sum(e.form == "evo" for e in ents), "heroes": sum(e.form == "hero" for e in ents)}


def signals(data: RankedData, o: int, rec: Record, W: Weights, field_now: np.ndarray, styles: dict[str, str], facts: dict[int, dict],
            min_games: int) -> pd.DataFrame:
    """Signals at the end of period t = o-1 for decks with enough OK games there, from what was known by then."""
    t, moment = o - 1, data.end(o - 1)
    known = data.known_at(moment)
    now, before = known & (data.period == t), known & (data.period == t - 1)
    deck, player = data.deck, data.player
    n_now = np.bincount(deck[now], minlength=len(data.decks))
    n_before = np.bincount(deck[before], minlength=len(data.decks))
    ok_now = np.bincount(deck[now & data.usable], minlength=len(data.decks))
    app_now, app_before = int(now.sum()), int(before.sum())
    picked = np.flatnonzero(ok_now >= min_games)
    names = [data.decks[i] for i in picked]
    members = data.membership[picked]
    frame = pd.DataFrame({"deck": deck[now], "player": player[now], "rating": data.rating[now]})
    per_deck = frame.groupby("deck").agg(players=("player", "nunique"), rating=("rating", "mean"))
    mean_rating = float(np.nanmean(frame["rating"]))
    pairs_now = pd.MultiIndex.from_arrays([deck[now], player[now]]).unique()
    pairs_before = pd.MultiIndex.from_arrays([deck[before], player[before]]).unique()
    users_before = pd.Series(pairs_before.get_level_values(0)).value_counts()
    returned = pd.Series(pairs_before.intersection(pairs_now).get_level_values(0)).value_counts()
    delta, _ = record_for(rec, names)
    rows = []
    fit = members @ (W.K @ field_now)
    own = members @ W.w - field_now @ W.w
    for j, (i, name) in enumerate(zip(picked, names)):
        share_now = (n_now[i] + 0.5) / (app_now + 1)
        share_before = (n_before[i] + 0.5) / (app_before + 1) if app_before else share_now
        had, back = int(users_before.get(i, 0)), int(returned.get(i, 0))
        row = {"deck": name, "origin": o, "own_record": delta[j], "card_strength": own[j], "field_fit": fit[j], "usage": float(np.log(share_now)),
               "momentum": float(logit(share_now) - logit(share_before)), "breadth": float(per_deck.at[i, "players"] / max(n_now[i], 1)),
               "return_rate": (back + 1) / (had + 2), "player_rating": (float(per_deck.at[i, "rating"]) - mean_rating) / 100 if np.isfinite(per_deck.at[i, "rating"]) else 0.0,
               "games": int(ok_now[i]), "appearances": int(n_now[i]), "share": share_now}
        row.update(deck_traits(name, facts))
        row[STYLE_PREFIX + styles.get(name, "unknown")] = 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def add_targets(rows: pd.DataFrame, data: RankedData, o: int, target_sides: pd.DataFrame, min_next: int) -> pd.DataFrame:
    """Next-period edge (points), its new-to-deck version, and usage growth (logit share change, smoothed)."""
    out = rows.copy()
    next_mask = data.period == o
    n_next = np.bincount(data.deck[next_mask], minlength=len(data.decks))
    app_next = int(next_mask.sum())
    idx = {d: i for i, d in enumerate(data.decks)}
    g1 = np.array([n_next[idx[d]] for d in out["deck"]])
    out["next_growth"] = logit((g1 + 0.5) / (app_next + 1)) - logit(out["share"].to_numpy())
    adj = adjusted(target_sides)
    new = adjusted(target_sides[target_sides["new"]]) if target_sides["new"].any() else adj.iloc[0:0]
    n = out["deck"].map(adj["n"]).fillna(0).to_numpy()
    out["next_games"] = n
    out["next_edge"] = np.where(n >= min_next, (out["deck"].map(adj["adj"]).to_numpy() - 0.5) * 100, np.nan)
    out["next_new_games"] = out["deck"].map(new["n"]).fillna(0).to_numpy()
    out["next_new_edge"] = (out["deck"].map(new["adj"]).to_numpy() - 0.5) * 100
    return out


def feature_list(rows: pd.DataFrame) -> list[str]:
    return NUMERIC + sorted(c for c in rows.columns if c.startswith(STYLE_PREFIX))


def blocks(features: list[str]) -> dict[str, list[str]]:
    """Signals for the drop-one test: each numeric signal alone, the style indicators as one."""
    out = {f: [f] for f in features if not f.startswith(STYLE_PREFIX)}
    style = [f for f in features if f.startswith(STYLE_PREFIX)]
    if style:
        out["style"] = style
    return out


@dataclass
class Ridge:
    features: list[str]
    center: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float

    def z(self, X: np.ndarray) -> np.ndarray:
        return (X - self.center) / self.scale

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.intercept + self.z(X) @ self.coef

    def parts(self, X: np.ndarray) -> np.ndarray:
        """Each signal's part of each prediction: coefficient x standardized value. Parts plus the intercept equal the prediction."""
        return self.z(X) * self.coef


def fit_ridge(X: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float, features: list[str]) -> Ridge:
    w = w / w.sum()
    center = w @ X
    scale = np.sqrt(w @ (X - center) ** 2)
    scale = np.where(scale > 1e-12, scale, 1.0)
    Z = (X - center) / scale
    intercept = float(w @ y)
    # alpha is per row, so its strength does not depend on how many decks there are
    A = (Z * w[:, None]).T @ Z + np.eye(Z.shape[1]) * alpha / len(y)
    coef = np.linalg.solve(A, (Z * w[:, None]).T @ (y - intercept))
    return Ridge(features, center, scale, coef, intercept)


def matrix(rows: pd.DataFrame, features: list[str]) -> np.ndarray:
    X = np.column_stack([rows[f].to_numpy(dtype=float) if f in rows else np.zeros(len(rows)) for f in features])
    return np.nan_to_num(X, nan=0.0)


TARGETS = {"next_edge": lambda r: r["next_games"].to_numpy(dtype=float), "next_growth": lambda r: np.sqrt(r["games"].to_numpy(dtype=float))}


def _usable(rows: pd.DataFrame, target: str) -> pd.DataFrame:
    return rows[rows[target].notna()]


def forward_predictions(rows: pd.DataFrame, target: str, features: list[str], alpha: float, min_train: int, predictor=None) -> pd.DataFrame:
    """Fit on every earlier transition, predict the next. Columns: origin, y, weight, prediction, baseline (the training mean)."""
    data = _usable(rows, target)
    origins = sorted(data["origin"].unique())
    weight = TARGETS[target]
    out = []
    for o in origins:
        train, test = data[data["origin"] < o], data[data["origin"] == o]
        if train["origin"].nunique() < min_train or test.empty:
            continue
        w_tr, y_tr = weight(train), train[target].to_numpy(dtype=float)
        X_tr, X_te = matrix(train, features), matrix(test, features)
        if predictor is None:
            pred = fit_ridge(X_tr, y_tr, w_tr, alpha, features).predict(X_te)
        else:
            pred = predictor(X_tr, y_tr, w_tr, X_te)
        out.append(pd.DataFrame({"origin": o, "deck": test["deck"].to_numpy(), "y": test[target].to_numpy(dtype=float), "weight": weight(test), "prediction": pred,
                                 "baseline": float(np.average(y_tr, weights=w_tr))}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["origin", "deck", "y", "weight", "prediction", "baseline"])


def r2(p: pd.DataFrame) -> float | None:
    if p.empty:
        return None
    sse = float(np.sum(p["weight"] * (p["y"] - p["prediction"]) ** 2))
    sst = float(np.sum(p["weight"] * (p["y"] - p["baseline"]) ** 2))
    return 1 - sse / sst if sst > 0 else None


def gbm_predictor(seed: int):
    def run(X_tr, y_tr, w_tr, X_te):
        return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=20, random_state=seed).fit(X_tr, y_tr, sample_weight=w_tr).predict(X_te)
    return run


def analyze_target(rows: pd.DataFrame, target: str, qc: dict, seed: int) -> tuple[dict, Ridge]:
    """Out-of-time R^2, the challenger, the coefficient ranges and the drop-one test for one target."""
    alpha, min_train = float(qc["ridge_alpha"]), int(qc["min_train_transitions"])
    features = feature_list(rows)
    data = _usable(rows, target).reset_index(drop=True)
    fwd = forward_predictions(rows, target, features, alpha, min_train)
    base_r2 = r2(fwd)
    challenger = r2(forward_predictions(rows, target, features, alpha, min_train, gbm_predictor(seed)))
    by_origin = [{"origin": int(o), "r2": r2(g), "decks": int(len(g))} for o, g in fwd.groupby("origin")]
    w, y, X = TARGETS[target](data), data[target].to_numpy(dtype=float), matrix(data, features)
    model = fit_ridge(X, y, w, alpha, features)
    # bootstrap of decks: all of a deck's rows stay together
    ids, inv = np.unique(data["deck"].to_numpy(), return_inverse=True)
    rng = np.random.default_rng(seed)
    boot = np.empty((int(qc["bootstrap"]), len(features)))
    for b in range(boot.shape[0]):
        counts = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids))).astype(float)
        wb = w * counts[inv]
        keep = wb > 0
        boot[b] = fit_ridge(X[keep], y[keep], wb[keep], alpha, features).coef
    lo, hi = np.quantile(boot, 0.05, axis=0), np.quantile(boot, 0.95, axis=0)
    lo99, hi99 = np.quantile(boot, 0.005, axis=0), np.quantile(boot, 0.995, axis=0)   # many signals are tested at once
    drop = {}
    for name, members in blocks(features).items():
        kept = [f for f in features if f not in members]
        v = r2(forward_predictions(rows, target, kept, alpha, min_train))
        drop[name] = None if (v is None or base_r2 is None) else base_r2 - v   # positive: removing it hurts
    block_of = {f: name for name, ms in blocks(features).items() for f in ms}
    table = []
    for i, f in enumerate(features):
        clear = bool(lo99[i] > 0 or hi99[i] < 0)
        loss = drop.get(block_of[f])
        table.append({"signal": f, "coef": float(model.coef[i]), "range": [float(lo[i]), float(hi[i])], "range99": [float(lo99[i]), float(hi99[i])], "sd": float(model.scale[i]),
                      "mean": float(model.center[i]), "clear": clear, "drop_r2": loss, "holds_up": bool(clear and loss is not None and loss > 0)})
    out = {"rows": int(len(data)), "decks": int(len(ids)), "transitions": int(data["origin"].nunique()), "forward_decks": int(len(fwd)), "r2": base_r2, "r2_by_origin": by_origin,
           "challenger_r2": challenger, "challenger_clearly_better": bool(challenger is not None and base_r2 is not None and challenger > max(base_r2, 0) + 0.01),
           "predicts": bool(base_r2 is not None and base_r2 > 0), "signals": table, "intercept": model.intercept}
    if target == "next_edge" and not fwd.empty:
        new = rows.set_index(["origin", "deck"])[["next_new_edge", "next_new_games"]]
        j = fwd.join(new, on=["origin", "deck"])
        j = j[(j["next_new_games"] > 0) & j["next_new_edge"].notna()]
        if len(j) >= 5:
            wt, a, b = j["next_new_games"].to_numpy(dtype=float), j["prediction"].to_numpy(dtype=float), j["next_new_edge"].to_numpy(dtype=float)
            ma, mb = np.average(a, weights=wt), np.average(b, weights=wt)
            cov = np.average((a - ma) * (b - mb), weights=wt)
            denom = np.sqrt(np.average((a - ma) ** 2, weights=wt) * np.average((b - mb) ** 2, weights=wt))
            out["new_to_deck"] = {"decks": int(len(j)), "games": int(wt.sum()), "correlation": float(cov / denom) if denom > 0 else None}
    return out, model


def explain(model: Ridge, row: pd.DataFrame) -> dict:
    """One deck's prediction as parts per signal, the style indicators summed into one part. Parts + intercept = prediction."""
    X = matrix(row, model.features)
    parts = model.parts(X)[0]
    out = {f: float(p) for f, p in zip(model.features, parts) if not f.startswith(STYLE_PREFIX)}
    out["style"] = float(sum(p for f, p in zip(model.features, parts) if f.startswith(STYLE_PREFIX)))
    return {"intercept": model.intercept, "prediction": float(model.predict(X)[0]), "parts": out}
