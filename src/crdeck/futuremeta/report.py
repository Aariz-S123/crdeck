"""Turns the recommender's results into web/future_meta.json, the only file the Future meta page reads.

No player tag reaches this file. Deck keys and card keys are public game data. Sentences are written by the page from these
numbers, so a new run can never leave a stale claim behind.
"""

from __future__ import annotations

from typing import Any

import numpy as np

import pandas as pd

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
        known = int((data.known_at(data.end(int(i))) & (data.period == int(i))).sum() // 2)
        out.append({"index": int(i), "window_id": p["window_id"], "start": str(p["start"]), "end": str(p["end"]), "battles": int(p["battles"]), "merged": int(p["merged"]),
                    "hours": round((p["end"] - p["start"]).total_seconds() / 3600, 1), "known_at_end": known})
    return out


def _utc(t) -> np.datetime64:
    return pd.Timestamp(t).tz_convert(None).to_datetime64()


def mean_shift(data, moment: np.datetime64, hours: float, min_sides: int) -> float | None:
    """Mean absolute change in share points across `moment`, comparing `hours` before with `hours` after, over forms above 2%."""
    span = np.timedelta64(int(hours * 3600), "s")
    a, b = (data.time >= moment - span) & (data.time < moment), (data.time >= moment) & (data.time < moment + span)
    if a.sum() < min_sides or b.sum() < min_sides:
        return None
    zero = np.zeros(len(data.deck), dtype=int)
    sa, sb = data.share_table(a, zero, 1)[0][0], data.share_table(b, zero, 1)[0][0]
    return float(np.mean(np.abs(sb - sa)[sa > 0.02]) * 100)


def event_shift(data, event: dict, top: int = 8, min_sides: int = 5000) -> dict | None:
    """What moved across an observed game event inside the newest period: equal spans of hours on each side, with the same
    measure at the same hour on earlier days for scale. All of it is measured; nothing here is a forecast."""
    moment, end = _utc(event["time"]), data.end(data.n_periods - 1)
    start = pd.Timestamp(data.periods["start"].iloc[-1]).tz_convert(None).to_datetime64()
    if not (start <= moment <= end):
        return None
    hours = float((end - moment) / np.timedelta64(1, "h"))
    span = np.timedelta64(int(hours * 3600), "s")
    before, after = (data.time >= moment - span) & (data.time < moment), data.time >= moment
    if not before.any() or not after.any():
        return None
    zero = np.zeros(len(data.deck), dtype=int)
    sb, sa = data.share_table(before, zero, 1)[0][0], data.share_table(after, zero, 1)[0][0]
    diff = sa - sb
    order = [i for i in np.argsort(-np.abs(diff), kind="stable") if sb[i] >= 0.01 or sa[i] >= 0.01][:top]
    earlier = [mean_shift(data, moment - np.timedelta64(d, "D"), hours, min_sides) for d in range(1, 16)]
    earlier = [x for x in earlier if x is not None]
    return {"time": str(pd.Timestamp(event["time"])), "text": event["text"], "hours_after": round(hours, 1), "sides_before": int(before.sum()), "sides_after": int(after.sum()),
            "mean_abs_points": float(np.mean(np.abs(diff)[sb > 0.02]) * 100), "typical_points": float(np.median(earlier)) if earlier else None, "typical_days": len(earlier),
            "movers": [{"key": data.keys[i], "before": float(sb[i]), "after": float(sa[i])} for i in order],
            "new_forms": [{"key": data.keys[i], "after": float(sa[i])} for i in np.flatnonzero((sb < 0.001) & (sa >= 0.01))]}


def sampled_player_results(battles: pd.DataFrame, dib: pd.DataFrame, event: dict, hours: float) -> dict:
    """Win rate of the sampled leaderboard players themselves, in equal spans either side of an event, with its 90% Wilson range. Matchmaking
    pairs similar ratings, so this normally stays near a steady level; a jump says their opponents changed, not their decks."""
    moment = pd.Timestamp(event["time"])
    t = pd.to_datetime(battles["battle_time"], utc=True)
    span = pd.Timedelta(hours=hours)
    out = {}
    for name, keep in (("before", (t >= moment - span) & (t < moment)), ("after", (t >= moment) & (t < moment + span))):
        b = battles.loc[keep & (battles["status"] == "OK"), ["battle_key", "source_player_tag"]]
        sides = dib.merge(b, left_on=["battle_key", "player_tag"], right_on=["battle_key", "source_player_tag"])
        n, wins = len(sides), int(sides["won"].astype(bool).sum())
        if n:
            z, p = 1.6448536269514722, wins / n
            d = 1 + z * z / n
            mid, half = (p + z * z / (2 * n)) / d, z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
            out[name] = {"games": n, "win_rate": p, "range": [mid - half, mid + half]}
    return out


def after_event_mask(data, events: list[dict]) -> np.ndarray | None:
    return data.time >= _utc(events[0]["time"]) if events else None


def since_event_shares(data, membership, mask: np.ndarray | None) -> np.ndarray | None:
    if mask is None or not mask.any():
        return None
    counts = np.bincount(data.deck[mask], minlength=len(data.decks)).astype(float)
    return np.asarray(membership.T @ counts).ravel() / mask.sum()


def since_event_records(data, mask: np.ndarray | None) -> dict[str, tuple[int, int]]:
    """Raw OK games and wins per deck since the event. Ratings are missing then, so no rating adjustment is possible."""
    if mask is None:
        return {}
    ok = mask & data.usable
    games = np.bincount(data.deck[ok], minlength=len(data.decks))
    wins = np.bincount(data.deck[ok], weights=data.won[ok], minlength=len(data.decks))
    return {data.decks[i]: (int(games[i]), int(wins[i])) for i in np.flatnonzero(games)}


def family_json(res: dict, since_event: np.ndarray | None = None, history_range: np.ndarray | None = None) -> dict:
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
        if since_event is not None:
            item["since_event"] = float(since_event[k])
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
    ("Backtests only use battles already fetched at each origin, and score against every battle later seen. A collection that fetched few logs leaves its period thinly known at that origin, which hurts every method in that period.",
     "Collect full lists on every run and compare."),
    ("The matchup model's strength setting (C) comes from one selection on 2026-10-24, which looked at later battles than the earliest origins. Each origin's weights are still fitted only on earlier battles.",
     "Re-choose C at each origin."),
    ("Each model still has the same regular players in training and later battles, so the matchup weights can partly remember players rather than cards. That is why the deck check leads with players new to a deck.",
     "Refit without the players being scored."),
    ("Win estimates are at equal player rating. Rating does not capture everything about skill: a deck used by unusually good players can still look stronger than it is.",
     "Compare results of the same players on different decks."),
    ("Estimates average log-odds over the field before turning them into a win chance, which is close but not identical to averaging win chances. The gap is measured and shown.",
     "Average over real sampled opponents instead."),
    ("Battle logs stopped giving player ratings when the new season started. A battle with no rating gap counts toward usage, but toward no win estimate, record or model, because a skill gap could not be told from a deck's strength. If ratings do not return, the win estimates stop updating.",
     "Recheck once ratings return to the logs."),
    ("A forecast can only continue what its history shows. A season start, a balance change or a new card has no history here, and no model on this data can see it coming.",
     "Collect across several seasons, then test a season-level forecast."),
    ("The deck check is fragile. Run on 2026-11-02 while still counting battles with no rating gap as evenly rated, the picks' lead over most played among players new to a deck was +3.65 points (90% range -1.08 to +7.58, not clear). Leaving those battles out, as now, made it clear. A verdict that moves with a data rule should be read as tentative.",
     "Repeat the same check over more periods, with its rules unchanged."),
    ("Every signal about what makes a deck good is an association. It does not prove that changing that signal would make a deck win more.",
     "An experiment would be needed, which this data cannot provide."),
]
