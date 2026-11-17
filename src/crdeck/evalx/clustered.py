"""Player-clustered check of the win model against its baselines (docs/fable-brief/BLUEPRINT.md 9.3).

`crdeck.evaluate.strength_significance` resamples single test battles. A player's battles are not independent (the
same player, often the same deck, many times), so that range is too narrow. Here every player's battles move
together: players are drawn with replacement, and the paired log-loss difference (model minus baseline) is recomputed
on each draw from the same players for every baseline.

Unit: the player of side A of each test battle (the logged player). The opponent (side B) as the unit is reported as a
sensitivity check. The test window is one to two days, so no time blocks are needed.

Assumption: players are independent of each other. Test: compare with the opponent as the unit; if the two disagree a
lot, two-way clustering is needed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

N_BOOT, SEED = 2000, 42


def log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def clustered_range(d: np.ndarray, cluster: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Mean of `d` with a 90% range from resampling whole clusters with replacement (seed fixed).
    Returns delta, lo, hi, share_better (share of draws below 0), clusters, n."""
    codes, inv = np.unique(cluster, return_inverse=True)
    P = len(codes)
    S = np.bincount(inv, weights=d, minlength=P)
    N = np.bincount(inv, minlength=P).astype(float)
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    step = max(1, int(2e7 // max(P, 1)))          # draws per chunk, to keep memory small
    for s in range(0, n_boot, step):
        k = rng.multinomial(P, np.full(P, 1.0 / P), size=min(step, n_boot - s)).astype(float)
        draws[s:s + len(k)] = (k @ S) / (k @ N)
    return {"delta": float(d.mean()), "lo": float(np.quantile(draws, 0.05)), "hi": float(np.quantile(draws, 0.95)),
            "share_better": float((draws < 0).mean()), "clusters": int(P), "n": int(len(d))}


def battle_players(ctx) -> pd.DataFrame | None:
    """battle_key -> player_a, player_b for the test battles; None without the player table."""
    f = ctx.paths.interim / "decks_in_battle.parquet"
    if not f.exists():
        return None
    dib = pd.read_parquet(f, columns=["battle_key", "side", "player_tag"]).drop_duplicates(["battle_key", "side"])
    dib = dib[dib["battle_key"].isin(set(ctx.split.test["battle_key"]))]
    wide = dib.pivot(index="battle_key", columns="side", values="player_tag")
    return wide.rename(columns={"A": "player_a", "B": "player_b"})


def clustered_significance(ctx, n_boot: int = N_BOOT, seed: int = SEED, players: pd.DataFrame | None = None) -> list[dict]:
    """One row per baseline: the battle-level numbers recomputed here, and the player-clustered ranges with side A's
    player as the unit (primary) and side B's (sensitivity). Same baselines as strength_significance."""
    from ..strength import ConstantBaseline, PopularityBaseline, RatingBaseline
    t, tv = ctx.split.test, ctx.split.train_valid
    players = battle_players(ctx) if players is None else players
    if players is None:
        return []
    pl = players.reindex(t["battle_key"])
    known = pl["player_a"].notna().to_numpy() & pl["player_b"].notna().to_numpy()
    y = t["a_won"].astype(int).to_numpy()
    model_ll = log_loss(y, ctx.strength.predict_df(t))
    rows = []
    for base in (ConstantBaseline(), PopularityBaseline().fit(tv), RatingBaseline().fit(tv)):
        d = (model_ll - log_loss(y, base.predict_df(t)))[known]
        a = clustered_range(d, pl["player_a"].to_numpy()[known], n_boot, seed)
        b = clustered_range(d, pl["player_b"].to_numpy()[known], n_boot, seed)
        rows.append({"model": ctx.strength.name, "vs": base.name, "delta": a["delta"], "lo": a["lo"], "hi": a["hi"],
                     "share_better": a["share_better"], "players": a["clusters"], "battles": a["n"],
                     "opponent": {"lo": b["lo"], "hi": b["hi"], "share_better": b["share_better"], "players": b["clusters"]},
                     "battles_without_players": int((~known).sum())})
    return rows
