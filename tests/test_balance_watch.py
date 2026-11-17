"""The balance watch on constructed battles: no look-ahead, the window rule, the signals, the fixed score and tiers,
and scoring a frozen list. (Constructed numbers here only test the code; nothing from them is ever shown.)"""

from __future__ import annotations

import copy
import datetime as dt
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from crdeck.balance import events as ev
from crdeck.balance import features as ft
from crdeck.balance import score as sc
from crdeck.balance import watch
from crdeck.config import PROJECT_ROOT, Paths
from crdeck.explore import data_status
from crdeck.futuremeta import data as dm
from crdeck.pipeline import _fingerprint

START = pd.Timestamp("2026-03-01T00:00:00Z")
N_CARDS = 20
IDS = [26000000 + i for i in range(N_CARDS)]
STRONG, WEAK = IDS[0], IDS[1]


def calendar(*events) -> ev.Calendar:
    """A calendar from (day, [(card_id, form, label)], scoreable) tuples."""
    return ev.Calendar(version=1, checked_on=dt.date(2026, 3, 20), events=tuple(
        ev.Event(id=day, effective_date=dt.date.fromisoformat(day), source_kind="official", source_url="https://example.invalid/", scoreable=scoreable,
                 changes=tuple(ev.Change(card_id=c, card=str(c), form=f, label=lab) for c, f, lab in changes))
        for day, changes, scoreable in events))


def tables(days=20, per_day=400, seed=0, edge=0.0, players=80):
    """Battles between random decks. A deck with STRONG gains `edge` log-odds, one with WEAK loses it. Each day's
    battles are fetched at the end of that day. Ratings differ, and the better-rated side wins more often."""
    rng = np.random.default_rng(seed)
    pool = sorted({"|".join(f"{c}:base" for c in sorted(rng.choice(IDS, 8, replace=False))) for _ in range(60)})
    has = lambda d, c: f"{c}:base" in d.split("|")  # noqa: E731
    b, d = [], []
    for day in range(days):
        begin = START + pd.Timedelta(days=day)
        for k in range(per_day):
            t = begin + pd.Timedelta(seconds=int(rng.integers(1, 86399)))
            x, y = rng.choice(len(pool), 2, replace=False)
            pa, pb = f"#P{rng.integers(0, players)}", f"#Q{rng.integers(0, players)}"
            ra, rb = 9000 + float(rng.normal(0, 150)), 9000 + float(rng.normal(0, 150))
            z = edge * ((has(pool[x], STRONG) - has(pool[y], STRONG)) - (has(pool[x], WEAK) - has(pool[y], WEAK))) + 0.3 * (ra - rb) / 100
            won = bool(rng.random() < 1 / (1 + np.exp(-z)))
            key = f"{pa}|{pb}|{day}|{k}"
            b.append({"battle_key": key, "battle_time": t, "status": "OK", "mode": "ranked", "sample": "leaderboard",
                      "fetched_at": (begin + pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")})
            base = {"battle_key": key, "crowns": 1, "global_rank": np.nan, "level_deficit": 0.0, "form_unknown": False}
            d.append({**base, "side": "A", "player_tag": pa, "deck_key": pool[x], "won": won, "trophies_or_rank": ra})
            d.append({**base, "side": "B", "player_tag": pb, "deck_key": pool[y], "won": not won, "trophies_or_rank": rb})
    periods = pd.DataFrame([{"window_id": "w", "start": START - pd.Timedelta(days=1), "end": START + pd.Timedelta(days=days), "battles": days * per_day, "merged": 1}])
    return pd.DataFrame(b), pd.DataFrame(d), periods


def built(**kw):
    b, d, p = tables(**kw)
    return dm.assemble(b, d, p, None, None, None, None)


def cut(day: int) -> pd.Timestamp:
    return START + pd.Timedelta(days=day)


def run(data, cal, day=18, **kw):
    kw.setdefault("min_top_sides", 1000)
    kw.setdefault("min_card_sides", 50)
    kw.setdefault("min_edge_sides", 50)
    kw.setdefault("n_boot", 200)
    return ft.compute(data, cal, cut(day), IDS, **kw)


CARDS = {c: SimpleNamespace(name=f"Card {c - 26000000}", is_win_condition=(c % 5 == 0), card_type="spell" if c % 3 == 0 else "troop") for c in IDS}
NO_EVENTS = calendar()


# ---------------------------------------------------------------- the window

def test_window_starts_the_day_after_the_last_balance_update_and_is_at_most_14_days():
    cal = calendar(("2026-03-02", [(IDS[3], "all", "nerf")], True), ("2026-03-10", [(IDS[4], "evo", "addition")], False))
    w = ft.window_for(cut(18), cal)                                   # T = 2026-03-19
    assert pd.Timestamp(w.start) == pd.Timestamp("2026-03-05") and w.days == 14 and w.last_event.id == "2026-03-02"
    w = ft.window_for(cut(8), cal)                                    # T = 2026-03-09, six days after the update
    assert pd.Timestamp(w.start) == pd.Timestamp("2026-03-03") and w.days == 6
    w = ft.window_for(cut(18), NO_EVENTS)
    assert w.last_event is None and w.days == 14
    # a release or a bug-fix event does not move the window; a community balance update does
    late = calendar(("2026-03-12", [(IDS[4], "all", "fix")], False), ("2026-03-14", [(IDS[5], "all", "buff")], False))
    w = ft.window_for(cut(18), late)
    assert w.last_event.id == "2026-03-14" and pd.Timestamp(w.start) == pd.Timestamp("2026-03-15")


def test_battles_on_an_effective_day_are_left_out_of_the_window():
    cal = calendar(("2026-03-02", [(IDS[3], "all", "nerf")], True))
    w = ft.window_for(cut(18), cal)
    t = np.array(["2026-03-04T23:59:59", "2026-03-05T00:00:00", "2026-03-18T23:59:59", "2026-03-19T00:00:00"], dtype="datetime64[ns]")
    assert w.holds(t).tolist() == [False, True, True, False]
    # an update inside the 14 days: the window starts after it, so its day is never inside
    inside = ft.window_for(cut(18), calendar(("2026-03-10", [(IDS[3], "all", "nerf")], True)))
    assert pd.Timestamp(inside.start) == pd.Timestamp("2026-03-11") and inside.excluded == ()


def test_a_short_window_or_too_few_sides_gives_no_list():
    data = built()
    short = run(data, calendar(("2026-03-14", [(IDS[3], "all", "nerf")], True)))      # 4 days since the update
    assert short.status == "insufficient" and "days" in short.reason and short.arrays == {}
    few = run(data, NO_EVENTS, min_top_sides=10**9)
    assert few.status == "insufficient" and "top sides" in few.reason
    body = watch.build(short, calendar(("2026-03-14", [(IDS[3], "all", "nerf")], True)), CARDS)
    assert body["status"] == "insufficient" and body["cards"] == [] and body["window"]["ready_on"] == "2026-03-22"


# ---------------------------------------------------------------- no look-ahead

def test_signals_do_not_change_when_battles_after_the_cutoff_change():
    b, d, p = tables(edge=0.6)
    T = cut(12)
    before = ft.compute(dm.assemble(b, d, p, None, None, None, None), NO_EVENTS, T, IDS, min_top_sides=1000, min_card_sides=50, min_edge_sides=50, n_boot=100)
    # flip every result and reshuffle every deck of the battles played after the cutoff
    late = set(b.loc[pd.to_datetime(b["battle_time"], utc=True) >= T, "battle_key"])
    d2 = d.copy()
    m = d2["battle_key"].isin(late)
    d2.loc[m, "won"] = ~d2.loc[m, "won"].astype(bool)
    d2.loc[m, "deck_key"] = d2.loc[m, "deck_key"].to_numpy()[::-1]
    after = ft.compute(dm.assemble(b, d2, p, None, None, None, None), NO_EVENTS, T, IDS, min_top_sides=1000, min_card_sides=50, min_edge_sides=50, n_boot=100)
    for name in before.arrays:
        np.testing.assert_array_equal(before[name], after[name], err_msg=name)
    assert (before.n_sides, before.n_battles, before.beta) == (after.n_sides, after.n_battles, after.beta)


def test_a_battle_fetched_after_the_cutoff_is_not_counted_unless_the_pilot_waives_it():
    b, d, p = tables(days=20)
    data = dm.assemble(b, d, p, None, None, None, None)
    # each day's battles are fetched at the end of that day, so at 12:00 that day's battles are played but unknown
    noon = cut(12) + pd.Timedelta(hours=12)
    strict = ft.compute(data, NO_EVENTS, noon, IDS, min_top_sides=1000, min_card_sides=50, n_boot=20)
    waived = ft.compute(data, NO_EVENTS, noon, IDS, min_top_sides=1000, min_card_sides=50, n_boot=20, ignore_fetch=True)
    assert waived.n_sides > strict.n_sides and waived.n_battles > strict.n_battles
    played_today = int(((data.time >= ft._np(cut(12))) & (data.time < ft._np(noon))).sum())
    assert waived.n_sides - strict.n_sides == played_today


def test_changing_battles_on_the_effective_day_moves_nothing():
    cal = calendar(("2026-03-08", [(IDS[3], "all", "nerf")], True))
    b, d, p = tables()
    day = (pd.to_datetime(b["battle_time"], utc=True).dt.date == dt.date(2026, 3, 8))
    d2 = d.copy()
    m = d2["battle_key"].isin(set(b.loc[day, "battle_key"]))
    d2.loc[m, "won"] = ~d2.loc[m, "won"].astype(bool)
    one = run(dm.assemble(b, d, p, None, None, None, None), cal)
    two = run(dm.assemble(b, d2, p, None, None, None, None), cal)
    assert one.status == "ok" and m.any()
    for name in one.arrays:
        np.testing.assert_array_equal(one[name], two[name], err_msg=name)


# ---------------------------------------------------------------- the signals

def test_usage_matches_a_hand_count_and_adds_up_to_eight():
    data = built()
    f = run(data, NO_EVENTS)
    w = f.window
    mask = (data.time < w.cutoff) & (data.first_seen <= w.cutoff) & w.holds(data.time)
    assert f.n_sides == int(mask.sum()) and f.n_players == len(set(data.player[mask]))
    held = np.array([sum(f"{c}:base" in data.decks[i].split("|") for i in data.deck[mask]) for c in IDS])
    np.testing.assert_allclose(f["usage_top"], held / mask.sum())
    assert f["usage_top"].sum() == pytest.approx(8.0) and f["usage_all"].sum() == pytest.approx(8.0)
    np.testing.assert_array_equal(f["sides_top"], held)
    assert (f["usage_lo"] <= f["usage_top"]).all() and (f["usage_top"] <= f["usage_hi"]).all()
    np.testing.assert_allclose(f["U"], np.log((f["usage_top"] + 0.5 / f.n_sides) / (8 / N_CARDS)))


def test_a_planted_strong_card_has_a_positive_edge_and_a_weak_one_a_negative_edge():
    f = run(built(edge=0.8, per_day=600), NO_EVENTS, n_boot=300)
    i, j = IDS.index(STRONG), IDS.index(WEAK)
    assert f["edge_known"].all() and f.tau2 > 0 and f.beta > 0
    assert f["edge"][i] == f["edge"].max() and f["edge"][j] == f["edge"].min()
    assert f["edge"][i] - ft.Z90 * f["edge_sd"][i] > 0 > f["edge"][j] + ft.Z90 * f["edge_sd"][j]
    # shrinkage pulls toward 0 and never flips a sign
    assert (np.abs(f["edge"]) <= np.abs(f["edge_raw"]) + 1e-12).all() and (np.sign(f["edge"]) == np.sign(f["edge_raw"])).all()


def test_the_edge_is_the_mean_result_minus_the_rating_expectation():
    data = built(edge=0.5, days=16)
    f = run(data, NO_EVENTS, day=15)
    w, b = f.window, data.battles
    bt = b["t"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    bw = b[(bt < w.cutoff) & w.holds(bt) & b["rating_diff"].notna().to_numpy() & (b["first_seen"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]") <= w.cutoff)]
    exp = 1 / (1 + np.exp(-f.beta * bw["rating_diff"].to_numpy() / 100))
    res = bw["a_won"].astype(float).to_numpy() - exp
    key = f"{STRONG}:base"
    vals = np.r_[res[[key in k.split("|") for k in bw["deck_a"]]], -res[[key in k.split("|") for k in bw["deck_b"]]]]
    assert f["edge_raw"][IDS.index(STRONG)] == pytest.approx(vals.mean(), abs=1e-9)
    assert f["edge_sides"][IDS.index(STRONG)] == len(vals) and f.n_battles == len(bw)


def test_shrinkage_hand_example():
    raw, se = np.array([0.04, -0.04, 0.0]), np.array([0.01, 0.01, 0.01])
    E, sd, tau2 = ft.shrink(raw, se, np.array([True, True, True]))
    assert tau2 == pytest.approx(0.0032 / 3 - 0.0001)
    w = tau2 / (tau2 + 0.0001)
    np.testing.assert_allclose(E, [0.04 * w, -0.04 * w, 0.0])
    np.testing.assert_allclose(sd, np.sqrt(tau2 * 0.0001 / (tau2 + 0.0001)))
    # noise as large as the spread: nothing is left, every edge is 0
    E0, sd0, t0 = ft.shrink(np.array([0.01, -0.01]), np.array([0.05, 0.05]), np.array([True, True]))
    assert t0 == 0.0 and not E0.any() and not sd0.any()
    # a card without an edge stays at 0 and does not enter the spread
    E1, _, t1 = ft.shrink(np.array([0.04, -0.04, 9.0]), np.array([0.01, 0.01, 0.0]), np.array([True, True, False]))
    assert E1[2] == 0.0 and t1 == pytest.approx(0.0016 - 0.0001)


def test_a_card_with_too_few_rating_known_sides_has_no_edge():
    f = run(built(), NO_EVENTS, min_edge_sides=10**9)
    assert not f["edge_known"].any() and not f["edge"].any() and f.tau2 == 0.0
    body = watch.build(f, NO_EVENTS, CARDS)
    assert all(c["edge_pts"] is None and c["z"]["edge"] == 0 for c in body["cards"])


def test_robust_z_hand_example_and_a_zero_mad():
    x = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    z = ft.robust_z(x, np.ones(5, dtype=bool))
    np.testing.assert_allclose(z[:4], (x[:4] - 3) / 1.4826)
    assert z[4] == 4.0                                           # clipped
    assert not ft.robust_z(np.array([5.0, 5.0, 5.0, 9.0]), np.ones(4, dtype=bool)).any()      # MAD 0: all zeros, no crash
    part = ft.robust_z(x, np.array([True, True, True, False, False]))
    assert part[3] == 0 and part[4] == 0 and part[0] == pytest.approx(-1 / 1.4826)
    assert not ft.robust_z(x, np.zeros(5, dtype=bool)).any()


def test_momentum_needs_both_weeks_and_follows_the_usage_change():
    data = built()
    f = run(data, NO_EVENTS)
    assert f.momentum_ok
    np.testing.assert_allclose(f["momentum"], np.log((f["usage_last"] + 0.5 / (f.n_sides / 2)) / (1 - f["usage_last"] - 0.5 / (f.n_sides / 2)))
                               - np.log((f["usage_prev"] + 0.5 / (f.n_sides / 2)) / (1 - f["usage_prev"] - 0.5 / (f.n_sides / 2))), atol=1e-9)
    short = run(data, calendar(("2026-03-09", [(IDS[3], "all", "nerf")], True)))           # 9 days since the update
    assert short.status == "ok" and not short.momentum_ok and not short["momentum"].any()
    assert all(c["momentum"] is None for c in watch.build(short, calendar(("2026-03-09", [(IDS[3], "all", "nerf")], True)), CARDS)["cards"])


def test_releases_come_from_the_calendar_and_from_saved_card_lists():
    cal = calendar(("2026-01-05", [(IDS[2], "base", "addition")], False), ("2026-03-10", [(IDS[3], "evo", "addition"), (IDS[4], "base", "addition")], False))
    snaps = {"changes": [{"from": "2026-03-01T00:00:00Z", "to": "2026-03-12T08:00:00Z", "added": [{"key": f"{IDS[5]}:hero"}, {"key": f"{IDS[3]}:evo"}]}]}
    rel = ft.release_days(cal, snaps)
    assert rel[IDS[3]] == [(dt.date(2026, 3, 10), "evo")]                       # already in the calendar: not added again from the snapshot
    assert rel[IDS[5]] == [(dt.date(2026, 3, 12), "hero")]
    f = run(built(), cal, releases=rel)
    recent, new = f["release_recent"], f["new_card"]
    assert [bool(recent[IDS.index(c)]) for c in (IDS[2], IDS[3], IDS[4], IDS[5], IDS[6])] == [False, True, True, True, False]   # Jan 5 is 73 days before
    assert [bool(new[IDS.index(c)]) for c in (IDS[3], IDS[4])] == [False, True]      # a new form is not a new card; a card released 9 days ago is
    assert not f["eligible"][IDS.index(IDS[4])]
    body = watch.build(f, cal, CARDS)
    row = next(c for c in body["cards"] if c["card_id"] == IDS[4])
    assert row["tier"] == "not_enough_data" and row["ineligible_reason"] == "new_card" and row["nerf_score"] == 0


def test_the_same_seed_gives_the_same_file():
    data = built(edge=0.4)
    one = watch.build(run(data, NO_EVENTS), NO_EVENTS, CARDS, generated_at="A")
    two = watch.build(run(data, NO_EVENTS), NO_EVENTS, CARDS, generated_at="B")
    assert watch.same_apart_from_time(one, two)
    assert json.dumps({**one, "generated_at": ""}, sort_keys=True) == json.dumps({**two, "generated_at": ""}, sort_keys=True)
    other = watch.build(run(data, NO_EVENTS, seed=7), NO_EVENTS, CARDS, generated_at="A")
    assert not watch.same_apart_from_time(one, other)


# ---------------------------------------------------------------- the fixed score and the tiers

def test_scores_follow_the_fixed_formula():
    E = np.array([0.03, -0.02, 0.0, 0.01, -0.01, 0.0])
    U = np.array([1.0, -1.5, 0.2, 0.0, -0.3, 0.1])
    M = np.array([0.2, -0.2, 0.0, 0.1, 0.0, -0.1])
    R = np.array([True, False, False, False, False, True])
    elig = np.array([True, True, True, True, True, False])
    s = watch.scores(E, U, M, R, elig)
    zE, zU, zM = ft.robust_z(E, elig), ft.robust_z(U, elig), ft.robust_z(M, elig)
    np.testing.assert_allclose(s["nerf"][:5], (np.maximum(0, zE) + np.maximum(0, zU) + 0.5 * np.maximum(0, zM) + 0.5 * R)[:5])
    np.testing.assert_allclose(s["buff"][:5], (np.maximum(0, -zE) + np.maximum(0, -zU) + 0.5 * np.maximum(0, -zM))[:5])
    assert s["nerf"][5] == 0 and s["buff"][5] == 0                 # not eligible: no score, even with a recent release
    assert watch.WEIGHTS == {"edge": 1.0, "usage": 1.0, "momentum": 0.5, "release": 0.5}
    assert watch.TIERS == {"watch": {"max_rank": 5, "min_score": 1.0}, "possible": {"max_rank": 15, "min_score": 0.5}} and watch.K_EVAL == 15


def test_direction_is_the_higher_score_and_ties_have_none():
    elig = np.array([True, True, True, False])
    d = watch.directions(np.array([2.0, 0.5, 1.0, 3.0]), np.array([0.0, 1.5, 1.0, 0.0]), elig)
    assert d.tolist() == ["nerf", "buff", "", ""]


def test_tier_rules():
    n = 20
    ids = list(range(100, 100 + n))
    nerf = np.array([3.0, 2.5, 0.8, 2.0, 1.5, 1.2, 1.1, 0.9, 0.7, 0.6, 0.55, 0.52, 0.51, 0.505, 0.502, 0.501, 0.4, 0.0, 0.0, 0.0])
    buff = np.zeros(n)
    buff[17], buff[18] = 1.4, 0.3
    elig = np.ones(n, dtype=bool)
    elig[19] = False
    dirs = watch.directions(nerf, buff, elig)
    tier, rank = watch.tiers(dirs, nerf, buff, elig, ids)
    order = sorted(range(17), key=lambda j: -nerf[j])
    assert [rank[j] for j in order] == list(range(1, 18))
    assert [tier[j] for j in order[:5]] == ["nerf_watch"] * 5                    # ranks 1 to 5, all above 1.0
    assert tier[order[5]] == "nerf_possible" and nerf[order[5]] == 1.1           # rank 6 with 1.1: past rank 5, so "possible"
    assert all(tier[j] == "nerf_possible" for j in order[5:15])
    assert tier[order[15]] == "none" and nerf[order[15]] > 0.5                   # rank 16: past the list, whatever its score
    assert tier[16] == "none"                                                    # 0.4: under every threshold
    assert tier[17] == "buff_watch" and rank[17] == 1 and tier[18] == "none" and rank[18] == 2
    assert tier[19] == "not_enough_data" and rank[19] is None
    # rank 1 to 5 but a score between 0.5 and 1.0 is "possible", not "watch closely" and not "no signal"
    low = np.array([0.8, 0.6, 0.3])
    t2, _ = watch.tiers(watch.directions(low, np.zeros(3), np.ones(3, dtype=bool)), low, np.zeros(3), np.ones(3, dtype=bool), [1, 2, 3])
    assert t2 == ["nerf_possible", "nerf_possible", "none"]
    # equal scores are ranked by card id
    eq = np.array([2.0, 2.0])
    _, r3 = watch.tiers(watch.directions(eq, np.zeros(2), np.ones(2, dtype=bool)), eq, np.zeros(2), np.ones(2, dtype=bool), [9, 4])
    assert r3 == [2, 1]


def test_the_website_file_follows_its_contract():
    cal = calendar(("2026-02-20", [(STRONG, "all", "nerf"), (IDS[7], "evo", "buff"), (IDS[8], "all", "fix")], True))
    f = run(built(edge=0.8, per_day=600), cal, n_boot=300)
    body = watch.build(f, cal, CARDS, generated_at="2026-03-19T01:00:00Z")
    assert body["version"] == 1 and body["status"] == "preview" and body["cutoff"] == "2026-03-19T00:00:00Z" and body["pilot"] is False
    assert body["window"]["start"] == "2026-03-05T00:00:00Z" and body["window"]["days"] == 14 and body["window"]["sides_top"] == f.n_sides
    assert body["calendar"]["last_event"] == {"id": "2026-02-20", "effective_date": "2026-02-20", "source_url": "https://example.invalid/", "source_kind": "official", "n_changes": 2}
    assert body["reference"]["wr_band"] == [0.45, 0.55] and body["reference"]["usage_band"] == [0.07, 0.09] and body["reference"]["avg_usage"] == pytest.approx(8 / N_CARDS)
    assert body["score"]["weights"] == {"edge": 1, "usage": 1, "momentum": 0.5, "release": 0.5} and body["score"]["design"] == "docs/balance/DESIGN.md"
    assert len(body["cards"]) == N_CARDS and sum(c["usage_top"] for c in body["cards"]) == pytest.approx(8.0, abs=1e-3)
    tiers = {"nerf_watch", "nerf_possible", "buff_watch", "buff_possible", "none", "not_enough_data"}
    for c in body["cards"]:
        assert c["tier"] in tiers and c["ineligible_reason"] in (None, "too_few_games", "new_card") and c["role"] in ("spell", "win_condition", "building", "troop")
        assert c["eligible"] == (c["tier"] != "not_enough_data")
        if c["edge_known"]:
            assert c["edge_lo"] <= c["edge_pts"] <= c["edge_hi"]
        assert (c["direction"] is None) == (c["rank"] is None)
        if c["tier"].endswith("_watch"):
            assert c["rank"] <= 5 and max(c["nerf_score"], c["buff_score"]) > 1.0
        for r in c["reasons"]:
            assert "—" not in r and "will" not in r.split() and "guaranteed" not in r
    strong, weak = (next(c for c in body["cards"] if c["card_id"] == i) for i in (STRONG, WEAK))
    assert strong["direction"] == "nerf" and weak["direction"] == "buff" and strong["edge_pts"] > 0 > weak["edge_pts"]
    assert any("more often than their players' ratings predict" in r for r in strong["reasons"])
    assert any("less often than their players' ratings predict" in r for r in weak["reasons"])
    assert strong["last_change"] == {"event_id": "2026-02-20", "label": "nerf", "date": "2026-02-20", "source_kind": "official"} and strong["days_since_change"] == 27
    assert next(c for c in body["cards"] if c["card_id"] == IDS[8])["last_change"] is None            # a bug fix is not a balance change
    # stale: neither a calendar event nor a check of the notes in the last 45 days
    old = ev.Calendar(version=1, checked_on=dt.date(2026, 1, 1), events=cal.events[:0])
    assert watch.build(run(built(), old), old, CARDS)["status"] == "stale"
    fresh = ev.Calendar(version=1, checked_on=dt.date(2026, 3, 1), events=cal.events[:0])
    assert watch.build(run(built(), fresh), fresh, CARDS)["status"] == "preview"


# ---------------------------------------------------------------- scoring a frozen list

def snapshot(cutoff="2026-03-19T00:00:00Z"):
    """A hand-made list of 8 eligible cards and one that is not, with every number a baseline reads."""
    def card(cid, direction, nerf, buff, u, e, m, wr, last=None, released=None, eligible=True):
        return {"card_id": cid, "eligible": eligible, "direction": direction, "nerf_score": nerf, "buff_score": buff, "log_usage_ratio": u, "edge_pts": e,
                "momentum": m, "wr_raw": wr, "last_change": last, "released": released}
    last = lambda lab: {"event_id": "2026-03-01", "label": lab, "date": "2026-03-01", "source_kind": "official"}  # noqa: E731
    return {"cutoff": cutoff, "status": "preview", "pilot": False, "calendar": {"last_event": {"id": "2026-03-01"}}, "cards": [
        card(1, "nerf", 3.0, 0.0, 1.6, 1.0, 0.3, 0.56),
        card(2, "nerf", 2.0, 0.0, 0.2, 2.0, 0.0, 0.58, last("nerf"), "2026-02-01"),
        card(3, "nerf", 1.0, 0.2, 1.0, -0.5, 0.1, 0.50, last("nerf"), "2026-02-20"),
        card(4, None, 0.5, 0.5, 0.0, 0.0, 0.0, 0.50),
        card(5, "buff", 0.0, 2.5, -2.0, -1.0, -0.4, 0.44, last("buff")),
        card(6, "buff", 0.1, 1.5, -1.0, -2.0, 0.0, 0.47),
        card(7, "buff", 0.0, 0.6, -0.5, 0.1, -0.2, 0.43),
        card(8, "nerf", 0.4, 0.0, 0.5, 0.2, 0.5, 0.51),
        card(9, None, 0.0, 0.0, 3.0, 5.0, 2.0, 0.70, eligible=False),
    ]}


def update(day="2026-03-21", announced=None):
    e = calendar((day, [(2, "all", "nerf"), (8, "all", "nerf"), (9, "all", "nerf"), (5, "all", "buff"), (4, "all", "buff"), (3, "base", "buff"), (3, "evo", "nerf"), (6, "all", "fix")], True))[0]
    return e if announced is None else ev.Event(**{**e.__dict__, "announced": dt.date.fromisoformat(announced)})


def test_a_snapshot_is_scored_only_if_its_cutoff_is_a_day_before_the_update_became_public():
    assert sc.cutoff_ok(snapshot("2026-03-20T00:00:00Z"), update())            # exactly 24 hours before
    assert not sc.cutoff_ok(snapshot("2026-03-20T00:00:01Z"), update())
    assert not sc.cutoff_ok(snapshot("2026-03-19T00:00:00Z"), update(announced="2026-03-19"))   # the announcement is what counts
    with pytest.raises(sc.ScoreError, match="24 hours"):
        sc.score_event(snapshot("2026-03-21T00:00:00Z"), update())
    with pytest.raises(sc.ScoreError, match="no list"):
        sc.score_event({**snapshot(), "status": "insufficient", "cards": []}, update())
    snaps = [snapshot("2026-03-17T00:00:00Z"), snapshot("2026-03-19T00:00:00Z"), snapshot("2026-03-21T00:00:00Z"), {**snapshot("2026-03-20T00:00:00Z"), "status": "insufficient", "cards": []}]
    assert sc.pick_snapshot(snaps, update())["cutoff"] == "2026-03-19T00:00:00Z"            # newest that is early enough and holds a list
    assert sc.pick_snapshot(snaps[2:], update()) is None


def test_scoring_hand_example_with_every_baseline():
    row = sc.score_event(snapshot(), update(), k=2)
    # labels: nerf = {2, 8, 9}, buff = {5, 4}; card 3 moved both ways (rework); 6 is a fix; 9 is not eligible
    assert row["eligible"] == 8 and row["k"] == 2 and row["pilot"] is False
    assert row["nerf"]["labels"] == 3 and row["nerf"]["labels_eligible"] == 2 and row["buff"]["labels"] == 2 and row["buff"]["labels_eligible"] == 2
    # nerf list (cards with the nerf direction, by score): 1, 2, 3, 8 -> top 2 = {1, 2}: one hit (2)
    assert row["nerf"]["hits"] == 1 and row["nerf"]["hit_cards"] == [2] and row["nerf"]["recall"] == 0.5 and row["nerf"]["listed"] == 2
    # buff list: 5, 6, 7 -> top 2 = {5, 6}: one hit (5); card 4 has no direction, so the list cannot hold it
    assert row["buff"]["hits"] == 1 and row["buff"]["hit_cards"] == [5] and row["buff"]["recall"] == 0.5
    # average precision over all eligible cards. nerf order: 1, 2, 3, 8, then 4, 6, 5, 7 -> positives at 2 and 4
    assert row["nerf"]["ap"] == pytest.approx((1 / 2 + 2 / 4) / 2)
    # buff order: 5, 6, 7, then 4 (0.5), 3 (0.2), 1, 2, 8 -> positives at 1 and 4
    assert row["buff"]["ap"] == pytest.approx((1 / 1 + 2 / 4) / 2)
    base = row["baselines"]
    assert base["random"] == {"nerf": pytest.approx(2 * 2 / 8), "buff": pytest.approx(2 * 2 / 8)}
    assert base["usage_only"]["nerf"] == 0 and base["usage_only"]["buff"] == 1          # most used: 1, 3; least used: 5, 6
    assert base["edge_only"]["nerf"] == 1 and base["edge_only"]["buff"] == 1            # highest edge: 2, 1; lowest: 6, 5
    assert base["trend"]["nerf"] == 1 and base["trend"]["buff"] == 1                    # rising: 8, 1; falling: 5, 7
    assert base["band_rule"]["nerf"] == 1 and base["band_rule"]["nerf_listed"] == 2     # above 55%: 2 (58%), 1 (56%); 9 is not eligible
    assert base["band_rule"]["buff"] == 1 and base["band_rule"]["buff_listed"] == 2     # below 45%: 7 (43%), 5 (44%)
    assert base["recency"]["nerf"] == 1 and base["recency"]["nerf_listed"] == 2         # nerfed last time: 3 (newer), 2
    assert base["recency"]["buff"] == 1 and base["recency"]["buff_listed"] == 1         # buffed last time: 5
    # changed at all: nerf, buff or rework = {2, 8, 9, 5, 4, 3}; the two lists together hold {1, 2, 5, 6}
    assert row["changed"] == {"labels": 6, "labels_eligible": 5, "hits": 2}
    s = sc.summary([row, {**row, "pilot": True}])
    assert s["events"] == 1 and s["pilots"] == 1 and s["hits"] == 2 and s["labels"] == 4
    assert s["beats"]["usage_only"] == 1 and s["beats"]["edge_only"] == 0 and s["beats"]["random"] == 1


# ---------------------------------------------------------------- housekeeping

def test_data_status_updates_one_key_and_keeps_the_others(tmp_path):
    data_status.update(tmp_path, "models", {"last_battle": "2026-10-27T01:22:09Z"}, written="2026-10-27T05:00:00Z")
    body = data_status.update(tmp_path, "balance_watch", {"cutoff": "2026-11-16T00:00:00Z"}, written="2026-11-16T01:00:00Z")
    assert body == {"models": {"last_battle": "2026-10-27T01:22:09Z", "written": "2026-10-27T05:00:00Z"},
                    "balance_watch": {"cutoff": "2026-11-16T00:00:00Z", "written": "2026-11-16T01:00:00Z"}}
    assert data_status.read(tmp_path) == body
    with pytest.raises(ValueError):
        data_status.update(tmp_path, "nonsense", {})
    (tmp_path / data_status.FILE_NAME).write_text("not json", encoding="utf-8")
    assert data_status.read(tmp_path) == {}


def test_the_balance_code_is_outside_the_training_cache_fingerprint(tmp_path):
    """Adding or editing files in the subpackages and config subfolders must never force a retrain."""
    code, cfg = tmp_path / "code", tmp_path / "cfg"
    (code / "balance").mkdir(parents=True)
    (cfg / "balance").mkdir(parents=True)
    (code / "strength.py").write_text("x = 1\n")
    (cfg / "model.yaml").write_text("a: 1\n")
    paths = Paths(source="synthetic", root=tmp_path / "data")
    before = _fingerprint(paths, code, cfg)
    (code / "balance" / "watch.py").write_text("y = 2\n")
    (cfg / "balance" / "events.yaml").write_text("version: 1\n")
    assert _fingerprint(paths, code, cfg) == before
    (code / "strength.py").write_text("x = 2\n")
    assert _fingerprint(paths, code, cfg) != before
    # and the real tree keeps the calendar and the balance code where the fingerprint does not look
    assert (PROJECT_ROOT / "config" / "balance" / "events.yaml").exists() and not (PROJECT_ROOT / "config" / "events.yaml").exists()
    assert not list((PROJECT_ROOT / "src" / "crdeck").glob("balance*.py"))
