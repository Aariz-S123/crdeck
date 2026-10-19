"""Meta history and a Monte Carlo forecast of next-period usage (ranked decks).

Everything is computed from collected battles; the forecast is shown only when the data can
support it and a backtest says it does at least as well as assuming no change.

Definitions (also stated on the website and in docs/model-notes.md):
- Meta: usage share of each card form = share of ranked deck appearances (one side of one
  battle) whose deck contains that form; also the share of each predicted archetype.
- Period: the ranked battles played between two collection runs, (previous fetch, this fetch].
  The first period has no previous fetch and covers the `first_period_hours` before it.
  Periods never overlap. Per-day counts inside one collection are NOT used for the forecast:
  a battle log holds only a player's last 30 battles, so older days over-represent less
  active players and would look like meta change.
- Uncertainty: bootstrap over battles within each period (fixed seed).

Forecast model (an assumption, tested by the backtest):
  replicator-style drift in log-odds space,
    logit(share[t+1]) = logit(share[t]) + alpha + beta * (win_rate[t] - 0.5)
  card forms that win more than half their games gain share, at a rate beta fitted on the
  observed period-to-period changes; alpha absorbs a common shift. Each Monte Carlo run draws
  shares and win rates from the bootstrap, alpha/beta from a bootstrap of the fit, and binomial
  sampling noise for the next period's size, so the bands are prediction intervals for the
  next period's observed share.
Baselines: "no change" (last period's share) and "linear trend" (last change repeated).
Minimum data: 3 periods (one transition to fit, one held-out transition to test).
Recommended: 5 periods (at least 3 held-out transitions).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import sparse

MIN_PERIODS = 3
RECOMMENDED_PERIODS = 5


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


# ---------------------------------------------------------------- periods from collected data

def collection_periods(manifest: pd.DataFrame, first_period_hours: float = 24.0) -> pd.DataFrame:
    """One row per collection window: (start, end] with end = the window's last battle-log fetch."""
    m = manifest[manifest["kind"] == "battlelog"].copy()
    m["fetched_at"] = pd.to_datetime(m["fetched_at"], utc=True)
    ends = m.groupby("window_id")["fetched_at"].max().sort_values()
    rows, prev = [], None
    for w, end in ends.items():
        start = prev if prev is not None else end - timedelta(hours=first_period_hours)
        rows.append({"window_id": w, "start": start, "end": end})
        prev = end
    return pd.DataFrame(rows)


@dataclass
class PeriodData:
    periods: pd.DataFrame          # window_id, start, end, battles, appearances
    keys: list[str]                # card-form keys "id:form"
    X: list[sparse.csr_matrix]     # per period: battles x keys, count of sides (0, 1, 2) holding the key
    W: list[sparse.csr_matrix]     # per period: battles x keys, count of winning sides holding the key
    sides: list[np.ndarray]        # per period: sides per battle (2)
    deck_keys: list[pd.DataFrame]  # per period: battle_key, deck_a, deck_b, a_won (for archetype shares)


def period_data(battles: pd.DataFrame, dib: pd.DataFrame, periods: pd.DataFrame, mode: str = "ranked",
                statuses=("OK", "DRAW", "MIRROR")) -> PeriodData:
    b = battles[(battles["mode"] == mode) & battles["status"].isin(statuses)][["battle_key", "battle_time", "status"]]
    b = b.assign(battle_time=pd.to_datetime(b["battle_time"], utc=True))
    a = dib[dib["side"] == "A"].set_index("battle_key")
    bb = dib[dib["side"] == "B"].set_index("battle_key")
    keys = sorted({e for k in dib.loc[dib["battle_key"].isin(b["battle_key"]), "deck_key"] for e in k.split("|") if e})
    kidx = {k: i for i, k in enumerate(keys)}
    Xs, Ws, Ss, Ds, rows = [], [], [], [], []
    for _, p in periods.iterrows():
        sel = b[(b["battle_time"] > p["start"]) & (b["battle_time"] <= p["end"])]
        bk = sel["battle_key"].to_numpy()
        da, db = a.loc[bk, "deck_key"].to_numpy(), bb.loc[bk, "deck_key"].to_numpy()
        wa = a.loc[bk, "won"].to_numpy()
        ra, ca, va, wr_, wc, wv = [], [], [], [], [], []
        for i, (x, y, won) in enumerate(zip(da, db, wa)):
            for deck, side_won in ((x, won is True), (y, won is False)):
                for e in deck.split("|"):
                    j = kidx[e]
                    ra.append(i); ca.append(j); va.append(1.0)
                    if side_won:
                        wr_.append(i); wc.append(j); wv.append(1.0)
        n = len(bk)
        Xs.append(sparse.csr_matrix((va, (ra, ca)), shape=(n, len(keys))))
        Ws.append(sparse.csr_matrix((wv, (wr_, wc)), shape=(n, len(keys))))
        Ss.append(np.full(n, 2.0))
        Ds.append(pd.DataFrame({"battle_key": bk, "deck_a": da, "deck_b": db}))
        rows.append({**p.to_dict(), "battles": n, "appearances": 2 * n})
    return PeriodData(pd.DataFrame(rows), keys, Xs, Ws, Ss, Ds)


def period_stats(pd_: PeriodData, n_boot: int, seed: int):
    """Point estimates and bootstrap draws of share and win rate, per period x key.
    Returns dict with arrays: share [P,K], wr [P,K], games [P,K], share_boot [P,B,K], wr_boot [P,B,K]."""
    rng = np.random.default_rng(seed)
    P, K = len(pd_.X), len(pd_.keys)
    share = np.full((P, K), np.nan); wr = np.full((P, K), np.nan); games = np.zeros((P, K))
    share_b = np.full((P, n_boot, K), np.nan); wr_b = np.full((P, n_boot, K), np.nan)
    for p in range(P):
        X, W, s = pd_.X[p], pd_.W[p], pd_.sides[p]
        n = X.shape[0]
        if n == 0:
            continue
        g = np.asarray(X.sum(0)).ravel(); w = np.asarray(W.sum(0)).ravel()
        games[p] = g; share[p] = g / s.sum(); wr[p] = np.where(g > 0, w / np.maximum(g, 1), np.nan)
        cnt = rng.multinomial(n, np.full(n, 1 / n), size=n_boot).astype(float)  # B x n resample weights
        gb = cnt @ X.toarray() if n * K < 4e6 else np.vstack([X.T @ c for c in cnt])
        wb = cnt @ W.toarray() if n * K < 4e6 else np.vstack([W.T @ c for c in cnt])
        share_b[p] = gb / (cnt @ s)[:, None]
        wr_b[p] = np.where(gb > 0, wb / np.maximum(gb, 1), np.nan)
    return {"share": share, "wr": wr, "games": games, "share_boot": share_b, "wr_boot": wr_b}


# ---------------------------------------------------------------- dynamics fit, Monte Carlo, baselines

def fit_drift(share: np.ndarray, wr: np.ndarray, games: np.ndarray, transitions: list[int], min_games: int):
    """Least squares for logit(s[t+1]) - logit(s[t]) = alpha + beta * (wr[t] - 0.5) over the given t."""
    xs, ys, ws = [], [], []
    for t in transitions:
        ok = (games[t] >= min_games) & (games[t + 1] >= 1) & np.isfinite(wr[t])
        xs.append(wr[t][ok] - 0.5); ys.append(_logit(share[t + 1][ok]) - _logit(share[t][ok])); ws.append(np.sqrt(games[t][ok]))
    x, y, w = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    if len(x) < 3:
        return None
    A = np.vstack([np.ones_like(x), x]).T * w[:, None]
    coef, *_ = np.linalg.lstsq(A, y * w, rcond=None)
    return float(coef[0]), float(coef[1])


def monte_carlo(stats: dict, t: int, transitions: list[int], next_n: int, runs: int, seed: int, min_games: int):
    """Distribution of next-period shares given period t, with alpha/beta refitted per run on
    bootstrap draws of the fit periods. Returns [runs, K] simulated observed shares."""
    rng = np.random.default_rng(seed)
    B = stats["share_boot"].shape[1]
    K = stats["share"].shape[1]
    out = np.empty((runs, K))
    for r in range(runs):
        bt = rng.integers(B)
        # refit on a bootstrap draw of every fit period (parameter uncertainty)
        sb = stats["share"].copy(); wb = stats["wr"].copy()
        for tt in set(transitions) | {tt + 1 for tt in transitions}:
            k = rng.integers(B)
            sb[tt] = stats["share_boot"][tt, k]; wb[tt] = stats["wr_boot"][tt, k]
        ab = fit_drift(sb, wb, stats["games"], transitions, min_games) or (0.0, 0.0)
        s0 = np.nan_to_num(stats["share_boot"][t, bt], nan=0.0)
        w0 = np.nan_to_num(stats["wr_boot"][t, bt], nan=0.5)
        mean = _sigmoid(_logit(s0) + ab[0] + ab[1] * (w0 - 0.5))
        mean = np.where(s0 > 0, mean, 0.0)
        out[r] = rng.binomial(next_n, np.clip(mean, 0, 1)) / next_n  # next period's observed share
    return out


def backtest(stats: dict, appearances: list[int], runs: int, seed: int, min_games: int) -> pd.DataFrame:
    """Forecast each period T >= 2 from period T-1, fitting only on transitions before T-1."""
    P = stats["share"].shape[0]
    rows = []
    for T in range(2, P):
        fit_tr = list(range(0, T - 1))
        sims = monte_carlo(stats, T - 1, fit_tr, appearances[T], runs, seed + T, min_games)
        actual = stats["share"][T]
        keep = (stats["games"][T - 1] >= min_games) | (stats["games"][T] >= min_games)
        med = np.median(sims, 0)
        lo, hi = np.quantile(sims, 0.05, 0), np.quantile(sims, 0.95, 0)
        nochange = stats["share"][T - 1]
        trend = np.clip(stats["share"][T - 1] + (stats["share"][T - 1] - stats["share"][T - 2]), 0, 1)
        err = lambda f: float(np.nanmean(np.abs(f[keep] - actual[keep])) * 100)
        rows.append({"target_period": T, "card_forms_scored": int(keep.sum()),
                     "mae_points_monte_carlo": err(med), "mae_points_no_change": err(nochange),
                     "mae_points_linear_trend": err(trend),
                     "coverage_90": float(np.mean((actual[keep] >= lo[keep]) & (actual[keep] <= hi[keep])))})
    return pd.DataFrame(rows)


def meta_report(paths, ctx, cfg: dict) -> dict:
    """Everything the website's meta section shows, computed from collected data only."""
    from .pipeline import load_interim
    fc = cfg.get("forecast", {})
    seed, n_boot, runs = int(cfg["seed"]), int(fc.get("n_boot", 300)), int(fc.get("runs", 2000))
    min_games = int(fc.get("min_games", 200))
    battles, dib, _, _ = load_interim(paths)
    manifest = pd.read_csv(paths.root / "raw_manifest.csv")
    per = collection_periods(manifest, float(fc.get("first_period_hours", 24)))
    pdat = period_data(battles, dib, per, mode="ranked")
    stats = period_stats(pdat, n_boot, seed)
    P = len(pdat.periods)
    q = lambda arr, a: np.nanquantile(arr, a, axis=1)
    lo, hi = q(stats["share_boot"], 0.05), q(stats["share_boot"], 0.95)
    keys = pdat.keys
    # archetype shares per period (classifier from the ranked context)
    arche = []
    if ctx.archetype.fitted:
        from .rules import parse_deck_key
        cache = {}
        def lab(k):
            if k not in cache:
                cache[k] = ctx.archetype.predict(parse_deck_key(k)).label
            return cache[k]
        for p, d in enumerate(pdat.deck_keys):
            labs = pd.Series([lab(k) for k in pd.concat([d["deck_a"], d["deck_b"]])])
            n = len(labs)
            for a_, c in labs.value_counts().items():
                arche.append({"period": p, "archetype": a_, "share": c / n, "appearances": int(c)})
    history = []
    for p in range(P):
        for i, k in enumerate(keys):
            if stats["games"][p, i] == 0 and (P < 2 or stats["games"][:, i].sum() == 0):
                continue
            history.append({"period": p, "key": k, "share": float(stats["share"][p, i]), "share_ci90": [float(lo[p, i]), float(hi[p, i])],
                            "games": int(stats["games"][p, i]), "win_rate": None if not np.isfinite(stats["wr"][p, i]) else float(stats["wr"][p, i])})
    movers = []
    if P >= 2:
        d_boot = stats["share_boot"][P - 1] - stats["share_boot"][P - 2]
        for i, k in enumerate(keys):
            if max(stats["games"][P - 1, i], stats["games"][P - 2, i]) < min_games:
                continue
            movers.append({"key": k, "share_before": float(stats["share"][P - 2, i]), "share_after": float(stats["share"][P - 1, i]),
                           "change": float(stats["share"][P - 1, i] - stats["share"][P - 2, i]),
                           "change_ci90": [float(np.nanquantile(d_boot[:, i], 0.05)), float(np.nanquantile(d_boot[:, i], 0.95))]})
        movers.sort(key=lambda m: -abs(m["change"]))
    status = {"periods": P, "min_periods": MIN_PERIODS, "recommended_periods": RECOMMENDED_PERIODS}
    bt = pd.DataFrame()
    forecast = None
    if P < MIN_PERIODS:
        status.update(state="blocked", reason=(
            f"{P} collection period(s) so far. Fitting the share-change rate needs one period-to-period change and testing it "
            f"needs another, so at least {MIN_PERIODS} periods are required; {MIN_PERIODS - P} more daily collection(s) give the first "
            f"backtest and {RECOMMENDED_PERIODS - P} more give the recommended {RECOMMENDED_PERIODS} periods."))
    else:
        bt = backtest(stats, list(pdat.periods["appearances"]), runs, seed, min_games)
        mc, nc = bt["mae_points_monte_carlo"].mean(), bt["mae_points_no_change"].mean()
        if mc <= nc:
            sims = monte_carlo(stats, P - 1, list(range(P - 1)), int(pdat.periods["appearances"].iloc[-1]), runs, seed, min_games)
            forecast = [{"key": k, "median": float(np.median(sims[:, i])),
                         "band50": [float(np.quantile(sims[:, i], 0.25)), float(np.quantile(sims[:, i], 0.75))],
                         "band90": [float(np.quantile(sims[:, i], 0.05)), float(np.quantile(sims[:, i], 0.95))]}
                        for i, k in enumerate(keys) if stats["games"][P - 1, i] >= min_games]
            status.update(state="shown", reason=f"backtest error {mc:.3f} points vs {nc:.3f} for no change, over {len(bt)} held-out period(s)")
        else:
            status.update(state="not_better", reason=(f"in the backtest the forecast missed by {mc:.3f} share points on average, "
                                                      f"assuming no change missed by {nc:.3f}; the forecast is not yet better than no change"))
    return {
        "periods": pdat.periods.assign(start=lambda d: d["start"].astype(str), end=lambda d: d["end"].astype(str)).to_dict("records"),
        "history": history, "archetypes": arche, "movers": movers, "status": status,
        "backtest": bt.to_dict("records"), "forecast": forecast,
        "settings": {"bootstrap_resamples": n_boot, "monte_carlo_runs": runs, "seed": seed, "min_games": min_games,
                     "first_period_hours": float(fc.get("first_period_hours", 24))},
        "assumptions": [
            "Meta = share of ranked deck appearances that include a card form (one side of one battle = one appearance).",
            "A period is the battles played between two collection runs; the first period covers the 24 hours before the first run.",
            "Each battle log holds a player's last 30 battles, so very active players can be cut off within a period; "
            "this applies the same way to every daily period. Per-day counts inside one collection are not used.",
            "Forecast dynamics (only used once backtested): card forms that win more than half their games gain share, "
            "logit(share next) = logit(share now) + alpha + beta x (win rate - 0.5), with alpha and beta fitted on observed period changes.",
            "Uncertainty: bootstrap over battles within each period; prediction bands add binomial noise for the next period's size.",
            "Periods of different length or hours of the day mix in different player regions (time zones). Part of a change between "
            "two periods can be who was playing at those hours rather than a meta shift. Equal daily collections reduce this.",
        ],
        "period_hours": [round((pd.Timestamp(r["end"]) - pd.Timestamp(r["start"])).total_seconds() / 3600, 1)
                         for _, r in pdat.periods.iterrows()],
    }
