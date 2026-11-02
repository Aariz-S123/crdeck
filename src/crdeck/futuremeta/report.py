"""Turns the recommender's results into web/future_meta.json, the only file the Future meta page reads.

No player tag reaches this file. Deck keys and card keys are public game data. Sentences are written by the page from these
numbers, so a new run can never leave a stale claim behind.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .decks import Scored, mean_log_odds
from .forecasting import sigmoid, summarize


def r(x: Any, digits: int = 5) -> Any:
    """Round floats, also inside lists and dicts; NaN and infinity become null."""
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return None if not np.isfinite(v) else round(v, digits)
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, np.ndarray):
        return r(x.tolist(), digits)
    if isinstance(x, (list, tuple)):
        return [r(v, digits) for v in x]
    if isinstance(x, dict):
        return {str(k): r(v, digits) for k, v in x.items()}
    return x


def periods_json(data) -> list[dict]:
    out = []
    for i, p in data.periods.iterrows():
        out.append({"index": int(i), "window_id": p["window_id"], "start": str(p["start"]), "end": str(p["end"]), "battles": int(p["battles"]), "merged": int(p["merged"]),
                    "hours": round((p["end"] - p["start"]).total_seconds() / 3600, 1)})
    return out


def family_json(res: dict, label_rows=None, history_range: np.ndarray | None = None) -> dict:
    """One family's backtest and live forecast. Each live series carries its real history and the three future steps."""
    fam, live = res["family"], res["origins"][-1]
    rows = res["rows"]
    steps = []
    for h in sorted(live.forecast):
        f = live.forecast[h]
        steps.append({"horizon": h, "from_hour": f["target"].first, "to_hour": f["target"].last, "gamma": f["gamma"], "calibrated": f["calibrated"]})
    series = []
    for k in np.flatnonzero(live.scored):
        item = {"key": fam.labels[k], "history": [None if not np.isfinite(v) else float(v) for v in res["actual"][:, k]], "games_last": int(live.games[k]),
                "median": [], "band50": [], "band90": [], "timesfm_median": [], "no_change": float(live.shares[-1, k])}
        if history_range is not None:
            item["history_range"] = history_range[:, k, :].tolist()
        for h in sorted(live.forecast):
            b = live.forecast[h]["band"][:, k]
            item["median"].append(float(b[2]))
            item["band50"].append([float(b[1]), float(b[3])])
            item["band90"].append([float(b[0]), float(b[4])])
            item["timesfm_median"].append(float(live.forecast[h]["median"][k]))
        series.append(item)
    return {"rows": rows, "summary": [summarize(rows, h) for h in (1, 2, 3)], "steps": steps, "series": series}


def deck_row(s: Scored, i: int, top_share: np.ndarray, styles: dict[str, str], sims: np.ndarray, models: dict, signal_row, keys: list[str], top_cards: int = 3) -> dict:
    """Everything the page shows for one deck: its estimate, why, and its record. All numbers come from this origin's data."""
    from .quality import explain
    d, W = s.decks[i], s.weights
    member = s.members[i]
    own_idx = member.indices
    mean_share = sims.mean(axis=0)
    versus = W.K[own_idx].sum(axis=0)                       # sum_{i in deck} K(i, j), for each opposing card j
    own = float(W.w[own_idx].sum())
    field_mean = float(s.field_now @ W.w)
    fit = float(versus @ s.field_now)
    delta = float(s.delta[i])
    z_now = own - field_mean + fit + delta
    matchups = versus * s.field_now
    order = np.argsort(matchups, kind="stable")
    change = (versus - W.w) * (mean_share - s.field_now)    # what each card's forecast change does to this deck's log-odds
    worder = np.argsort(change, kind="stable")
    z_future = float(mean_log_odds(member, W, mean_share[None, :])[0, 0]) + delta
    col = s.runs[:, i]
    rec = s.record.loc[d] if d in s.record.index else None
    out = {"deck": d, "style": styles.get(d, "unknown"), "estimate": float(col.mean()), "range": [float(np.quantile(col, 0.05)), float(np.quantile(col, 0.95))],
           "chance_above_50": float((col > 0.5).mean()), "chance_top": float(top_share[i]), "current_field": float(s.current[i]), "cards_only": float(s.cards_only[i]),
           "games": int(s.games[i]), "played_last": int(s.played_last[i]), "record": None if rec is None else {"games": int(rec["n"]), "wins": int(rec["wins"]), "adjusted": float(rec["adj"])},
           "math": {"own": own, "field_mean": field_mean, "fit": fit, "delta": delta, "delta_var": float(s.delta_var[i]), "z_now": z_now, "estimate_now": float(sigmoid(z_now)),
                    "z_future": z_future, "estimate_future": float(sigmoid(z_future))},
           "good_against": [{"key": keys[j], "share": float(s.field_now[j]), "log_odds": float(matchups[j])} for j in order[::-1][:top_cards] if matchups[j] > 0],
           "bad_against": [{"key": keys[j], "share": float(s.field_now[j]), "log_odds": float(matchups[j])} for j in order[:top_cards] if matchups[j] < 0],
           "helped_by": [{"key": keys[j], "share_now": float(s.field_now[j]), "share_next": float(mean_share[j]), "log_odds": float(change[j])} for j in worder[::-1][:top_cards] if change[j] > 0],
           "hurt_by": [{"key": keys[j], "share_now": float(s.field_now[j]), "share_next": float(mean_share[j]), "log_odds": float(change[j])} for j in worder[:top_cards] if change[j] < 0]}
    if signal_row is not None:
        out["signals"] = {f: float(signal_row[f].iloc[0]) for f in ("own_record", "card_strength", "field_fit", "usage", "momentum", "breadth", "return_rate", "player_rating", "elixir",
                                                                     "spells", "buildings", "win_conditions", "air_defense", "splash", "evolutions", "heroes")}
        out["explain"] = {t: explain(m, signal_row) for t, m in models.items()}
    return out


ASSUMPTIONS = [
    ("A period is the battles played between two data collections. Small ones merge into the next, so periods run from about half a day to several days. The forecast treats hours as hours, so uneven gaps do not stretch its time axis.",
     "Collect daily at the same hour and compare."),
    ("Only Ranked battles from sampled leaderboard players' logs count, on both sides. This describes top players and their opponents, not everyone.",
     "Compare with the arena sample."),
    ("A battle log holds a player's last 30 battles. After a long gap between collections, the older hours mostly show less active players, which can look like the meta moving.",
     "Compare hours collected soon after they happened with the same hours collected later."),
    ("Backtests only use battles already fetched at each origin, and score against every battle later seen. The older replicator forecast is the exception: its inputs use all fetched battles, which slightly favors it.",
     "Rerun it with the same cut."),
    ("The matchup model's strength setting (C) comes from one selection on 2026-10-24, which looked at later battles than the earliest origins. Each origin's weights are still fitted only on earlier battles.",
     "Re-choose C at each origin."),
    ("Each model still has the same regular players in training and later battles, so the matchup weights can partly remember players rather than cards. That is why the deck check leads with players new to a deck.",
     "Refit without the players being scored."),
    ("Win estimates are at equal player rating. Rating does not capture everything about skill: a deck used by unusually good players can still look stronger than it is.",
     "Compare results of the same players on different decks."),
    ("Estimates average log-odds over the field before turning them into a win chance, which is close but not identical to averaging win chances. The gap is measured and shown.",
     "Average over real sampled opponents instead."),
    ("A forecast can only continue what its history shows. A season start, a balance change or a new card has no history here, and no model on this data can see it coming.",
     "Collect across several seasons, then test a season-level forecast."),
    ("Every signal about what makes a deck good is an association. It does not prove that changing that signal would make a deck win more.",
     "An experiment would be needed, which this data cannot provide."),
]
