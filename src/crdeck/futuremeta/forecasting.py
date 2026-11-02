"""Usage forecasts at every origin: baselines, TimesFM, calibration and the Monte Carlo over TimesFM.

An origin o is the end of period o-1. A forecast at o uses battles played and fetched by then (RankedData.known_at).
The real share it is scored against comes from every battle, whenever fetched. Definitions: docs/future-meta/DESIGN.md.

The same code forecasts any family of series over decks: card forms, deck styles, or single decks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from .data import RankedData
from .timesfm_runner import Task

Z90 = 1.6448536269514722
QUANTILE_WIDTH = 2.5631031310892   # z(90%) - z(10%): turns TimesFM's 10% to 90% distance into a standard deviation
Q10, Q90 = 1, 9                    # columns of TimesFM's quantile output: the mean, then the 10% to 90% deciles


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


@dataclass
class Family:
    name: str
    labels: list[str]               # the series
    membership: sparse.csr_matrix   # decks x series
    total: float | None             # the shares of one appearance add up to this (8 cards, 1 style); None: no rescaling
    min_games: int                  # a series is scored with this many appearances in the period ending at the origin
    top_n: int | None = None        # keep only the most-used scored series at each origin
    force_live: np.ndarray | None = None  # bool [series]: also forecast these at the live origin, whatever their games


@dataclass
class Target:
    horizon: int          # 1, 2 or 3
    period: int | None    # the real period it is scored on; None for a live forecast
    first: int            # first predicted hour, counted from the origin's hour
    last: int             # last predicted hour, included


@dataclass
class Origin:
    index: int                    # o: the first future period (n_periods for the live forecast)
    live: bool
    scored: np.ndarray            # bool [series]
    shares: np.ndarray            # [o, series]: what was known at the origin
    games: np.ndarray             # [series]: appearances in the period ending at the origin
    hourly: np.ndarray            # [hours, series]
    targets: list[Target]
    hours: int = 0                # TimesFM horizon in hours
    forecast: dict = field(default_factory=dict)  # horizon -> {median, q10, q90, sims, gamma, calibrated, period_median}


def targets_for(data: RankedData, o: int, horizons: int, live_step: int, max_horizon: int) -> list[Target]:
    if o >= data.n_periods:
        return [Target(h, None, (h - 1) * live_step, h * live_step - 1) for h in range(1, horizons + 1) if h * live_step <= max_horizon]
    stop = data.hour_of(data.end(o - 1))
    out = []
    for h in range(1, horizons + 1):
        p = o + h - 1
        if p >= data.n_periods:
            break
        first = data.hour_of(np.datetime64(data.periods["start"].iloc[p].tz_localize(None))) - stop
        last = data.hour_of(np.datetime64(data.periods["end"].iloc[p].tz_localize(None))) - stop
        if last >= max_horizon:
            break
        out.append(Target(h, p, max(first, 0), last))
    return out


def origin_inputs(data: RankedData, fam: Family, o: int, cfg: dict) -> Origin:
    fc, tf = cfg["forecast"], cfg["timesfm"]
    moment = data.end(o - 1)
    mask = data.known_at(moment)
    counts = data.deck_counts(mask, data.period, data.n_periods)
    appearances = np.asarray(counts.sum(axis=1)).ravel()
    games = (counts @ fam.membership).toarray()
    with np.errstate(invalid="ignore", divide="ignore"):
        shares = games[:o] / appearances[:o, None]
    last_games = games[o - 1]
    scored = last_games >= fam.min_games
    if fam.top_n is not None and scored.sum() > fam.top_n:
        keep = np.argsort(-last_games, kind="stable")[: fam.top_n]
        scored = np.zeros_like(scored); scored[keep] = True
    if o >= data.n_periods and fam.force_live is not None:
        scored = scored | fam.force_live
    stop = data.hour_of(moment)
    first = max(0, stop - int(tf["max_context"]))
    hm = mask & (data.hour >= first) & (data.hour < stop)
    hc = data.deck_counts(hm, data.hour - first, stop - first)
    happ = np.asarray(hc.sum(axis=1)).ravel()
    with np.errstate(invalid="ignore", divide="ignore"):
        hourly = (hc @ fam.membership).toarray() / happ[:, None]
    hourly[happ < int(fc["min_hour_appearances"])] = np.nan
    targets = targets_for(data, o, int(fc["horizons"]), int(fc["live_hours_per_step"]), int(tf["max_horizon"]))
    hours = max((t.last + 1 for t in targets), default=1)
    return Origin(o, o >= data.n_periods, scored, shares, last_games, hourly, targets, hours)


def tasks_for(org: Origin, horizons: int) -> tuple[Task, Task]:
    """The hourly task and the period-series task of one origin."""
    idx = org.scored
    return (Task(org.hourly[:, idx].T.copy(), org.hours), Task(org.shares[:, idx].T.copy(), horizons))


def calibration(history: list[dict], horizon: int, seen_through: int) -> tuple[float, bool, list[np.ndarray]]:
    """gamma and the earlier standardized misses for this horizon: only forecasts whose target period is at or before
    `seen_through`, which has been seen by then. gamma is 1 and not calibrated with fewer than 2 such forecasts."""
    usable = [r for r in history if r["horizon"] == horizon and r["period"] <= seen_through]
    misses = [r["z"] for r in usable]
    if len(misses) < 2:
        return 1.0, False, misses
    z = np.abs(np.concatenate([m[np.isfinite(m)] for m in misses]))
    return float(np.quantile(z, 0.9) / Z90), True, misses


def correlated_normals(misses: list[np.ndarray], n_series: int, runs: int, independent_part: float, rng: np.random.Generator) -> np.ndarray:
    """[runs, series] standard normal draws. With at least 3 earlier forecasts, part of each draw mixes their standardized
    misses with random normal weights, so series that missed together tend to move together; each series stays at variance 1."""
    e = rng.standard_normal((runs, n_series))
    if len(misses) < 3:
        return e
    R = np.nan_to_num(np.stack(misses), nan=0.0)              # forecasts x series
    W = rng.standard_normal((runs, R.shape[0])) @ R
    scale = np.sqrt((R ** 2).sum(axis=0))
    W = np.where(scale > 0, W / np.where(scale > 0, scale, 1.0), rng.standard_normal((runs, n_series)))
    return np.sqrt(1 - independent_part) * W + np.sqrt(independent_part) * e


def simulate(median: np.ndarray, sigma: np.ndarray, gamma: float, Z: np.ndarray, scored: np.ndarray, last: np.ndarray,
             total: float | None) -> np.ndarray:
    """[runs, series] simulated shares: scored series from the forecast, others at their last share, rescaled to `total`."""
    S = np.tile(np.nan_to_num(last, nan=0.0), (Z.shape[0], 1))
    S[:, scored] = sigmoid(logit(median[scored]) + gamma * sigma[scored] * Z[:, scored])
    if total is not None:
        rest = np.nan_to_num(last, nan=0.0)[~scored].sum()
        S[:, scored] *= (np.maximum(total - rest, 0.0) / S[:, scored].sum(axis=1))[:, None]
    return np.clip(S, 0.0, 1.0)


def aggregate(point: np.ndarray, quantile: np.ndarray, t: Target) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Median, 10% and 90% over the target's hours: the mean of the hourly values."""
    span = slice(t.first, t.last + 1)
    return point[:, span].mean(axis=1), quantile[:, span, Q10].mean(axis=1), quantile[:, span, Q90].mean(axis=1)


def spread(q10: np.ndarray, q90: np.ndarray) -> np.ndarray:
    return np.maximum((logit(q90) - logit(q10)) / QUANTILE_WIDTH, 1e-3)


def run_family(data: RankedData, fam: Family, cfg: dict, forecaster: Callable[[list[Task]], list[tuple[np.ndarray, np.ndarray]]],
               replicator: Callable[[int], np.ndarray] | None = None, keep_sims: bool = False) -> dict:
    """Backtest every origin in time order, then the live forecast. `forecaster` takes Tasks and returns (point, quantile);
    `replicator(o)` returns the existing Monte Carlo's [runs, series] simulated shares for period o."""
    fc = cfg["forecast"]
    P, K, horizons = data.n_periods, len(fam.labels), int(fc["horizons"])
    all_mask = np.ones(len(data.deck), dtype=bool)
    counts = data.deck_counts(all_mask, data.period, P)
    app_final = np.asarray(counts.sum(axis=1)).ravel()
    actual = (counts @ fam.membership).toarray() / app_final[:, None]
    origins = [origin_inputs(data, fam, o, cfg) for o in range(2, P + 1)]
    tasks: list[Task] = []
    for org in origins:
        tasks += list(tasks_for(org, horizons))
    outputs = forecaster(tasks)
    history: list[dict] = []
    rows: list[dict] = []
    for i, org in enumerate(origins):
        o, idx, last = org.index, org.scored, org.shares[org.index - 1]
        (hp, hq), (pp, _) = outputs[2 * i], outputs[2 * i + 1]
        rng = np.random.default_rng(int(cfg["seed"]) + o)
        for t in org.targets:
            med_s, q10_s, q90_s = aggregate(hp, hq, t)
            median, q10, q90 = (np.full(K, np.nan) for _ in range(3))
            median[idx], q10[idx], q90[idx] = med_s, q10_s, q90_s
            period_median = np.full(K, np.nan)
            period_median[idx] = pp[:, t.horizon - 1]
            sigma = spread(np.nan_to_num(q10, nan=0.5), np.nan_to_num(q90, nan=0.5))
            # at a live origin, every period has been seen; at a backtest origin, only those before o
            gamma, calibrated, misses = calibration(history, t.horizon, o - 1)
            Z = correlated_normals(misses, K, int(fc["runs"]), float(fc["independent_part"]), rng)
            S = simulate(median, sigma, gamma, Z, idx, last, fam.total)
            org.forecast[t.horizon] = {"median": median, "q10": q10, "q90": q90, "gamma": gamma, "calibrated": calibrated, "sigma": sigma,
                                       "band": np.quantile(S, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0),
                                       "sims": S if keep_sims and t.horizon == 1 else None, "target": t}
            if t.period is None:
                continue
            truth = actual[t.period]
            band = org.forecast[t.horizon]["band"]
            mean3 = np.nanmean(org.shares[max(0, o - 3):o], axis=0)
            mae = lambda f: float(np.mean(np.abs(f[idx] - truth[idx])) * 100)  # noqa: E731
            row = {"origin": o, "horizon": t.horizon, "period": t.period, "scored": int(idx.sum()), "gamma": gamma, "calibrated": calibrated,
                   "no_change": mae(last), "last3_mean": mae(mean3), "timesfm_hourly": mae(median), "timesfm_periods": mae(period_median),
                   "coverage_50": float(np.mean((truth[idx] >= band[1, idx]) & (truth[idx] <= band[3, idx]))),
                   "coverage_90": float(np.mean((truth[idx] >= band[0, idx]) & (truth[idx] <= band[4, idx]))),
                   "coverage_raw_80": float(np.mean((truth[idx] >= q10[idx]) & (truth[idx] <= q90[idx])))}
            if t.horizon == 1 and replicator is not None:
                sims = replicator(o)
                row["replicator_mc"] = mae(np.median(sims, axis=0))
                row["replicator_coverage_90"] = float(np.mean((truth[idx] >= np.quantile(sims, 0.05, axis=0)[idx]) & (truth[idx] <= np.quantile(sims, 0.95, axis=0)[idx])))
            rows.append(row)
            z = np.full(K, np.nan)
            z[idx] = (logit(truth[idx]) - logit(median[idx])) / sigma[idx]
            history.append({"horizon": t.horizon, "period": t.period, "z": z})
    return {"family": fam, "origins": origins, "rows": rows, "actual": actual, "appearances": app_final, "history": history}


def summarize(rows: list[dict], horizon: int = 1) -> dict:
    """Mean error per method over the target periods of one horizon, periods beating no change, band coverage."""
    r = [x for x in rows if x["horizon"] == horizon]
    if not r:
        return {"horizon": horizon, "periods": 0}
    methods = [m for m in ("no_change", "last3_mean", "replicator_mc", "timesfm_periods", "timesfm_hourly") if m in r[0]]
    out = {"horizon": horizon, "periods": len(r), "mae": {m: float(np.mean([x[m] for x in r])) for m in methods},
           "beats_no_change": {m: int(sum(x[m] < x["no_change"] for x in r)) for m in methods if m != "no_change"}}
    cal = [x for x in r if x["calibrated"]]
    weights = [x["scored"] for x in cal]
    out["calibrated_periods"] = len(cal)
    if cal:
        out["coverage_50"] = float(np.average([x["coverage_50"] for x in cal], weights=weights))
        out["coverage_90"] = float(np.average([x["coverage_90"] for x in cal], weights=weights))
    w_all = [x["scored"] for x in r]
    out["coverage_raw_80"] = float(np.average([x["coverage_raw_80"] for x in r], weights=w_all))
    if "replicator_coverage_90" in r[0]:
        out["replicator_coverage_90"] = float(np.average([x["replicator_coverage_90"] for x in r], weights=w_all))
    return out


def gate(rows: list[dict], primary: str = "timesfm_hourly") -> dict:
    """The design's gate, one period ahead: mean error below no change AND better in more than half of the target periods."""
    s = summarize(rows, 1)
    if not s["periods"]:
        return {"passed": False, "periods": 0, "reason": "no target periods"}
    below, wins, n = s["mae"][primary] < s["mae"]["no_change"], s["beats_no_change"][primary], s["periods"]
    return {"passed": bool(below and wins > n / 2), "mean_error_below": bool(below), "wins": wins, "periods": n,
            "error": s["mae"][primary], "error_no_change": s["mae"]["no_change"]}
