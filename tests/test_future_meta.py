"""The future-meta recommender on constructed battles: no look-ahead, the deck math, calibration, the gate, planted signals.
(Constructed numbers here only test the code; nothing from them is ever shown.)"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from crdeck.config import PROJECT_ROOT
from crdeck.futuremeta import data as dm
from crdeck.futuremeta import decks as dk
from crdeck.futuremeta import forecasting as fc
from crdeck.futuremeta import quality as q
from crdeck.futuremeta import report as rp
from crdeck.futuremeta import timesfm_runner as tr
from crdeck.pipeline import _fingerprint

START = pd.Timestamp("2026-10-01T00:00:00Z")
CFG = {"seed": 42, "forecast": {"min_games": 20, "min_hour_appearances": 2, "horizons": 3, "runs": 400, "independent_part": 0.25, "live_hours_per_step": 24},
       "timesfm": {"max_context": 512, "max_horizon": 256}, "matchup": {"C": 0.05},
       "decks": {"min_games_candidate": 10, "candidate_periods": 3, "min_games_tau": 10, "top": 3, "top_secondary": 5, "min_diff": 2, "min_games_judge": 20,
                 "min_games_range_check": 5, "bootstrap": 100}}


def deck_pool(n_decks=24, n_cards=20, seed=0) -> list[str]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_decks):
        ids = sorted(rng.choice(n_cards, 8, replace=False))
        out.append("|".join(f"{26000000 + i}:base" for i in ids))
    return sorted(set(out))


def tables(periods=6, per_period=300, seed=0, strong: str | None = None, edge=0.0, late_fetch=False):
    """Battles between random decks. `strong` wins with extra log-odds `edge`. Each period's battles are fetched at its end."""
    rng = np.random.default_rng(seed)
    decks = deck_pool(seed=seed)
    b, d = [], []
    for p in range(periods):
        begin = START + pd.Timedelta(days=p)
        for k in range(per_period):
            t = begin + pd.Timedelta(seconds=int(rng.integers(1, 86399)))
            x, y = rng.choice(len(decks), 2, replace=False)
            pa, pb = f"#P{rng.integers(0, 60)}", f"#Q{rng.integers(0, 60)}"
            z = edge * ((decks[x] == strong) - (decks[y] == strong))
            won = bool(rng.random() < 1 / (1 + np.exp(-z)))
            key = f"{pa}|{pb}|{p}|{k}"
            seen = begin + pd.Timedelta(days=1)
            if late_fetch and k % 2 == 0:
                seen = seen + pd.Timedelta(days=1)    # half of each period's battles are only fetched by the next collection
            b.append({"battle_key": key, "battle_time": t, "status": "OK", "mode": "ranked", "sample": "leaderboard", "fetched_at": seen.strftime("%Y-%m-%dT%H:%M:%SZ")})
            base = {"battle_key": key, "crowns": 1, "global_rank": np.nan, "level_deficit": 0.0, "form_unknown": False}
            d.append({**base, "side": "A", "player_tag": pa, "deck_key": decks[x], "won": won, "trophies_or_rank": 9000.0})
            d.append({**base, "side": "B", "player_tag": pb, "deck_key": decks[y], "won": not won, "trophies_or_rank": 9000.0})
    periods_df = pd.DataFrame([{"window_id": f"w{p}", "start": START + pd.Timedelta(days=p), "end": START + pd.Timedelta(days=p + 1), "battles": per_period, "merged": 1} for p in range(periods)])
    return pd.DataFrame(b), pd.DataFrame(d), periods_df


def built(**kw):
    b, d, p = tables(**kw)
    return dm.assemble(b, d, p, None, None, None, None)


def persistence(tasks):
    """A stand-in for TimesFM: the last known value, with a fixed spread. Records nothing, needs no model."""
    out = []
    for t in tasks:
        last = np.array([row[np.isfinite(row)][-1] if np.isfinite(row).any() else 0.1 for row in t.contexts])
        point = np.repeat(last[:, None], t.horizon, axis=1)
        quant = np.repeat(point[:, :, None], 10, axis=2)
        for i, delta in enumerate(np.linspace(-0.04, 0.04, 9), start=1):
            quant[:, :, i] = np.clip(point + delta, 0.0005, 0.9995)
        out.append((point, quant))
    return out


def family(data):
    return fc.Family("cards", list(data.keys), data.membership, 8.0, int(CFG["forecast"]["min_games"]))


# ---------------------------------------------------------------- periods and cutting by time

def test_small_periods_merge_into_the_next_and_a_small_last_one_is_in_progress():
    ends = [START + pd.Timedelta(days=i) for i in (1, 2, 3, 4)]
    periods = pd.DataFrame({"window_id": list("abcd"), "start": [START] + ends[:3], "end": ends})
    times = pd.Series(sorted(
        [START + pd.Timedelta(hours=5)] * 6 + [ends[0] + pd.Timedelta(hours=5)] * 2 + [ends[1] + pd.Timedelta(hours=5)] * 6 + [ends[2] + pd.Timedelta(hours=5)] * 3))
    out, progress = dm.merge_small_periods(periods, times, 5)
    assert out["battles"].tolist() == [6, 8]
    assert out["merged"].tolist() == [1, 2]
    assert out["start"].iloc[1] == ends[0] and out["end"].iloc[1] == ends[2]
    assert progress["battles"] == 3 and progress["window_id"] == "d"


def test_known_at_hides_battles_fetched_later():
    data = built(late_fetch=True, periods=4)
    end0 = data.end(0)
    assert data.known_at(end0).sum() == (data.period == 0).sum() / 2
    assert data.known_at(data.end(1)).sum() > (data.period == 0).sum()


def test_forecast_inputs_do_not_change_when_the_future_changes():
    """Everything an origin hands to the forecaster must ignore later battles and battles fetched later."""
    b, d, p = tables(late_fetch=True)
    data = dm.assemble(b, d, p, None, None, None, None)
    o = 3
    cut = p["end"].iloc[o - 1]
    before = fc.origin_inputs(data, family(data), o, CFG)
    # scramble every battle that was not yet fetched at the origin
    unseen = pd.to_datetime(b["fetched_at"], utc=True) > cut
    keys = set(b.loc[unseen, "battle_key"])
    d2 = d.copy()
    swap = d2["battle_key"].isin(keys)
    d2.loc[swap, "deck_key"] = d2.loc[swap, "deck_key"].iloc[::-1].to_numpy()
    d2.loc[swap, "won"] = ~d2.loc[swap, "won"].astype(bool)
    data2 = dm.assemble(b, d2, p, None, None, None, None)
    # compare by card form: the vocabulary is the same because every deck still appears
    assert data.keys == data2.keys
    after = fc.origin_inputs(data2, family(data2), o, CFG)
    np.testing.assert_array_equal(before.shares, after.shares)
    np.testing.assert_array_equal(before.hourly, after.hourly)
    np.testing.assert_array_equal(before.scored, after.scored)


def test_targets_cover_the_hours_of_their_period():
    data = built(periods=5)
    t = fc.targets_for(data, 2, 3, 24, 256)
    assert [x.period for x in t] == [2, 3, 4]
    assert (t[0].first, t[0].last) == (0, 24) and (t[1].first, t[1].last) == (24, 48)
    live = fc.targets_for(data, 5, 3, 24, 256)
    assert [(x.period, x.first, x.last) for x in live] == [(None, 0, 23), (None, 24, 47), (None, 48, 71)]


# ---------------------------------------------------------------- calibration and the Monte Carlo

def test_calibration_only_uses_targets_already_seen():
    misses = [{"horizon": 1, "period": 3, "z": np.array([1.0, np.nan])}, {"horizon": 1, "period": 4, "z": np.array([2.0, 2.0])}, {"horizon": 1, "period": 9, "z": np.array([100.0, 100.0])},
              {"horizon": 2, "period": 2, "z": np.array([50.0, 50.0])}]
    gamma, ok, used = fc.calibration(misses, 1, 4)
    assert ok and len(used) == 2
    assert gamma == pytest.approx(np.quantile([1.0, 2.0, 2.0], 0.9) / fc.Z90)
    gamma, ok, used = fc.calibration(misses, 1, 3)
    assert not ok and gamma == 1.0 and len(used) == 1


def test_draws_have_variance_one_and_keep_past_correlation():
    rng = np.random.default_rng(1)
    base = rng.normal(size=8)
    misses = [np.array([b, b + 0.01, -b]) for b in base]       # first two series move together, the third opposite
    Z = fc.correlated_normals(misses, 3, 40000, 0.25, rng)
    assert np.allclose(Z.var(axis=0), 1.0, atol=0.05)
    c = np.corrcoef(Z.T)
    assert c[0, 1] > 0.6 and c[0, 2] < -0.6
    assert abs(np.corrcoef(fc.correlated_normals(misses[:2], 3, 40000, 0.25, rng).T)[0, 1]) < 0.03   # too few forecasts: independent


def test_simulated_shares_add_up_and_unscored_series_stay():
    last = np.array([0.5, 0.3, 0.2, 0.05])
    scored = np.array([True, True, True, False])
    S = fc.simulate(np.array([0.6, 0.3, 0.2, np.nan]), np.array([0.2, 0.2, 0.2, 0.001]), 1.0, np.random.default_rng(0).standard_normal((50, 4)), scored, last, 1.05)
    assert np.allclose(S.sum(axis=1), 1.05)
    assert np.allclose(S[:, 3], 0.05)


def test_a_perfect_forecaster_passes_the_gate_and_copying_no_change_does_not():
    data = built(periods=7)
    res = fc.run_family(data, family(data), CFG, persistence)
    assert not fc.gate(res["rows"])["passed"]     # the stand-in equals no change or nearly so; it must not pass by tying
    every = np.ones(len(data.deck), dtype=bool)
    truth, _ = data.share_table(every, data.period, data.n_periods)
    calls = {"n": 0}
    origins = [fc.origin_inputs(data, family(data), o, CFG) for o in range(2, data.n_periods + 1)]

    def oracle(tasks):
        out = []
        for i, org in enumerate(origins):
            hourly_task, period_task = tasks[2 * i], tasks[2 * i + 1]
            point = np.zeros((hourly_task.contexts.shape[0], hourly_task.horizon))
            for t in org.targets:
                real = truth[t.period][org.scored] if t.period is not None else truth[-1][org.scored]
                point[:, t.first:t.last + 1] = real[:, None]
            quant = np.repeat(point[:, :, None], 10, axis=2)
            out.append((point, quant))
            out.append(persistence([period_task])[0])
            calls["n"] += 1
        return out
    passed = fc.gate(fc.run_family(data, family(data), CFG, oracle)["rows"])
    # the hour on a period boundary belongs to both targets, so even the oracle is not exactly right there
    assert passed["passed"] and passed["error"] < passed["error_no_change"] / 3 and calls["n"] == len(origins)


def test_calibrated_bands_hold_about_the_right_share_when_misses_are_steady():
    """Shares that bounce around a fixed level: the bands, widened from earlier misses, should hold most real shares."""
    data = built(periods=10, per_period=600, seed=3)
    res = fc.run_family(data, family(data), CFG, persistence)
    s = fc.summarize(res["rows"], 1)
    assert s["calibrated_periods"] >= 4
    assert 0.7 <= s["coverage_90"] <= 1.0
    assert s["coverage_50"] < s["coverage_90"]


# ---------------------------------------------------------------- deck math

def test_mean_log_odds_equals_averaging_over_real_opponents():
    data = built(periods=2)
    rng = np.random.default_rng(5)
    K = rng.normal(0, 0.05, (len(data.keys), len(data.keys)))
    K = K - K.T
    W = dk.Weights(rng.normal(0, 0.1, len(data.keys)), K, 0.2)
    mem = data.membership
    weights = rng.dirichlet(np.ones(mem.shape[0]))
    shares = np.asarray(mem.T @ weights).ravel()
    got = dk.mean_log_odds(mem, W, shares[None, :])[0]
    z = mem @ W.w
    brute = np.array([np.sum(weights * (z[a] - z + (mem[a] @ K @ mem.T.toarray()).ravel())) for a in range(mem.shape[0])])
    np.testing.assert_allclose(got, brute, atol=1e-9)


def test_own_record_shrinks_small_samples_and_finds_a_planted_edge():
    decks = deck_pool(seed=1)
    strong = decks[0]
    b, d, p = tables(strong=strong, edge=1.2, per_period=1500, seed=1)
    data = dm.assemble(b, d, p, None, None, None, None)

    class Flat:
        """A model that knows nothing about decks: every battle is 50:50."""
        @staticmethod
        def predict_df(df):
            return np.full(len(df), 0.5)
    rec = dk.own_record(data, Flat, 3, 10)
    i = rec.decks[strong]
    assert rec.tau2 > 0
    assert rec.mean[i] > 0.5
    assert rec.mean[i] == max(rec.mean)
    assert abs(rec.mean[i]) < abs(rec.raw[i] - rec.mu) + 1e-9
    # a deck with no games in the period keeps the prior
    m, v = dk.record_for(rec, ["no such deck"])
    assert m[0] == 0.0 and v[0] == rec.tau2


def test_no_real_edge_gives_little_spread():
    b, d, p = tables(per_period=1500, seed=2)
    data = dm.assemble(b, d, p, None, None, None, None)

    class Flat:
        @staticmethod
        def predict_df(df):
            return np.full(len(df), 0.5)
    rec = dk.own_record(data, Flat, 3, 10)
    assert rec.tau2 < 0.02


def test_lists_keep_their_order_and_differ_by_enough_cards():
    data = built(periods=2)
    n = len(data.decks)
    s = dk.Scored(2, list(data.decks), data.membership, np.tile(np.linspace(0.4, 0.6, n), (5, 1)), np.linspace(0.6, 0.4, n), np.linspace(0.6, 0.4, n), np.zeros(n), np.zeros(n),
                  np.ones(n, dtype=int), np.arange(n), pd.DataFrame({"adj": np.linspace(0.5, 0.6, n)}, index=data.decks), np.zeros(len(data.keys)),
                  dk.Weights(np.zeros(len(data.keys)), np.zeros((len(data.keys), len(data.keys))), 0.0), 0.0)
    listed = dk.lists_at(s, 3, 2)
    assert listed["future_field"][0] == data.decks[-1]
    assert listed["current_field"][0] == data.decks[0]
    assert listed["all_candidates"] == list(data.decks)
    ids = lambda x: {k.split(":")[0] for k in x.split("|")}  # noqa: E731
    top = listed["future_field"]
    assert all(len(ids(top[i]) - ids(top[j])) >= 2 for i in range(len(top)) for j in range(i))
    assert s.top_share(1)[-1] == 1.0


def test_the_deck_check_finds_a_planted_better_list_and_counts_too_few_games():
    rng = np.random.default_rng(0)
    n = 6000
    deck = rng.choice(["good", "bad", "other"], n)
    y = (rng.random(n) < np.where(deck == "good", 0.62, np.where(deck == "bad", 0.40, 0.5))).astype(float)
    frame = pd.DataFrame({"deck": deck, "player": [f"p{i}" for i in rng.integers(0, 500, n)], "y": y, "exp": 0.5, "new": rng.random(n) < 0.5})
    names = ["future_field", "most_played", "tiny", "all_candidates"]
    mem = {"future_field": {"good"}, "most_played": {"bad"}, "tiny": {"nothing"}, "all_candidates": {"good", "bad", "other"}}
    out = dk.pooled_check([frame], [mem], names, 200, 1, 20)
    primary = out["new_to_deck"]["lists"]
    assert primary["most_played"]["verdict"] == "better"
    assert primary["all_candidates"]["verdict"] == "better"
    assert primary["tiny"]["verdict"] == "too_few" and primary["tiny"]["adjusted_win_rate"] is None
    assert primary["future_field"]["verdict"] is None
    assert 0.55 < primary["future_field"]["adjusted_win_rate"] < 0.68
    flipped = dk.pooled_check([frame], [{**mem, "future_field": {"bad"}, "most_played": {"good"}}], names, 200, 1, 20)
    assert flipped["all_players"]["lists"]["most_played"]["verdict"] == "worse"


def test_the_whole_flow_prefers_a_deck_with_a_planted_edge():
    decks = deck_pool(seed=4)
    strong = decks[3]
    b, d, p = tables(strong=strong, edge=1.5, per_period=700, seed=4)
    data = dm.assemble(b, d, p, None, None, None, None)
    res = fc.run_family(data, family(data), CFG, persistence, keep_sims=True)
    model_cfg = {"matchup": {"min_pair_battles": 50, "max_iter": 500}, "strength": {"min_feature_games": 20}}
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        o = 5
        model = dk.fit_model(data, o, CFG, model_cfg, Path(tmp), verbose=False)
        assert list(Path(tmp).glob("matchup_*.pkl"))
        again = dk.fit_model(data, o, CFG, model_cfg, Path(tmp), verbose=False)
        assert again.w == model.w
    W = dk.weights_of(model, data.keys)
    rec = dk.own_record(data, model, o, 10)
    org = [x for x in res["origins"] if x.index == o][0]
    s = dk.score_origin(data, o, W, rec, org.forecast[1]["sims"], np.nan_to_num(org.shares[o - 1]), CFG, {x: True for x in data.decks})
    assert s.decks[int(np.argmax(s.mean))] == strong
    side = dk.target_rows(data, o)
    assert set(side.columns) == {"deck", "player", "y", "exp", "new"}
    assert side["new"].dtype == bool
    assert dk.adjusted(side).loc[strong, "adj"] > 0.6
    assert (s.runs >= 0).all() and (s.runs <= 1).all()
    assert s.top_share(3).sum() == pytest.approx(3.0)


# ---------------------------------------------------------------- what makes a deck good

def test_ridge_parts_add_up_to_the_prediction():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 4))
    y = X[:, 0] * 2 - X[:, 1] + rng.normal(0, 0.1, 200)
    m = q.fit_ridge(X, y, np.ones(200), 1.0, list("abcd"))
    np.testing.assert_allclose(m.intercept + m.parts(X).sum(axis=1), m.predict(X))
    assert m.coef[0] > 1.5 and m.coef[1] < -0.7


def panel(signal=1.0, seed=0, origins=6, per=60) -> pd.DataFrame:
    """Rows shaped like the real quality table, where only own_record predicts the next edge (if signal > 0)."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in range(2, 2 + origins):
        for i in range(per):
            row = {f: rng.normal() for f in q.NUMERIC}
            row.update({"deck": f"d{i}", "origin": o, "games": 50, "next_games": 50, "next_new_games": 10, STYLE_A: float(i % 2 == 0), STYLE_B: float(i % 2 == 1)})
            row["next_edge"] = signal * row["own_record"] + rng.normal(0, 1)
            row["next_new_edge"] = row["next_edge"] + rng.normal(0, 1)
            row["next_growth"] = rng.normal(0, 1)
            rows.append(row)
    return pd.DataFrame(rows)


STYLE_A, STYLE_B = q.STYLE_PREFIX + "Cycle", q.STYLE_PREFIX + "Bait"
QC = {"ridge_alpha": 10.0, "min_train_transitions": 2, "bootstrap": 400}


def test_a_planted_signal_holds_up_and_noise_does_not():
    res, _ = q.analyze_target(panel(), "next_edge", QC, 0)
    table = {s["signal"]: s for s in res["signals"]}
    assert res["predicts"] and res["r2"] > 0.2
    assert table["own_record"]["holds_up"] and table["own_record"]["coef"] > 0.5
    assert sum(s["holds_up"] for s in res["signals"]) <= 2      # 20 signals tested at once: noise must rarely pass
    assert res["new_to_deck"]["correlation"] > 0.2


def test_with_no_signal_the_model_does_not_claim_to_predict():
    res, _ = q.analyze_target(panel(signal=0.0, seed=2), "next_growth", QC, 0)
    assert res["r2"] < 0.02
    assert not any(s["holds_up"] and s["drop_r2"] > 0.02 for s in res["signals"])


def test_forward_predictions_never_train_on_their_own_or_later_transitions():
    rows = panel(origins=5)
    seen = []

    def spy(X_tr, y_tr, w_tr, X_te):
        seen.append(len(y_tr))
        return np.zeros(len(X_te))
    out = q.forward_predictions(rows, "next_edge", q.feature_list(rows), 10.0, 2, spy)
    assert sorted(out["origin"].unique()) == [4, 5, 6]
    assert seen == [120, 180, 240]


def test_explanation_adds_up_and_groups_the_style_parts():
    rows = panel()
    _, model = q.analyze_target(rows, "next_edge", QC, 0)
    one = q.explain(model, rows.iloc[[0]])
    assert one["intercept"] + sum(one["parts"].values()) == pytest.approx(one["prediction"])
    assert "style" in one["parts"] and not any(k.startswith(q.STYLE_PREFIX) for k in one["parts"])


def test_signals_do_not_change_when_the_future_changes():
    b, d, p = tables(late_fetch=True, per_period=400)
    data = dm.assemble(b, d, p, None, None, None, None)
    o = 3
    W = dk.Weights(np.zeros(len(data.keys)), np.zeros((len(data.keys), len(data.keys))), 0.0)
    rec = dk.Record({}, np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0), 0.0, 0.0)
    styles = {x: "Cycle" for x in data.decks}
    now = fc.origin_inputs(data, family(data), o, CFG).shares[o - 1]
    before = q.signals(data, o, rec, W, now, styles, {}, 5)
    cut = p["end"].iloc[o - 1]
    keys = set(b.loc[pd.to_datetime(b["fetched_at"], utc=True) > cut, "battle_key"])
    d2 = d.copy()
    swap = d2["battle_key"].isin(keys)
    d2.loc[swap, "player_tag"] = "#OTHER"
    d2.loc[swap, "trophies_or_rank"] = 1.0
    d2.loc[swap, "won"] = ~d2.loc[swap, "won"].astype(bool)
    after = q.signals(dm.assemble(b, d2, p, None, None, None, None), o, rec, W, now, styles, {}, 5)
    pd.testing.assert_frame_equal(before, after)


# ---------------------------------------------------------------- the runner, the report, and staying out of the model cache

def test_timesfm_results_come_from_the_cache_without_running_anything(tmp_path):
    cfg = {"timesfm": {"repo": "x/y", "max_context": 32, "max_horizon": 16, "batch_size": 2}}
    task = tr.Task(np.array([[0.1, np.nan, 0.3]]), 4)
    name = tmp_path / f"{tr._digest(task, 'x/y', 32, 16)}.npz"
    np.savez_compressed(name, point=np.ones((1, 4)), quantile=np.ones((1, 4, 10)))
    (point, quant), = tr.forecast([task], cfg, tmp_path, python=Path("does-not-exist"))
    assert point.shape == (1, 4) and quant.shape == (1, 4, 10)
    assert tr._digest(tr.Task(np.array([[0.1, np.nan, 0.31]]), 4), "x/y", 32, 16) != name.stem
    assert tr._digest(tr.Task(np.array([[0.1, np.nan, 0.3]]), 5), "x/y", 32, 16) != name.stem


def test_rounding_makes_clean_json():
    out = rp.r({"a": np.float64(0.1234567), "b": [np.nan, np.inf], "c": np.array([1, 2]), "d": np.bool_(True), "e": np.int64(3)})
    assert out == {"a": 0.12346, "b": [None, None], "c": [1, 2], "d": True, "e": 3}
    json.dumps(out, allow_nan=False)


def test_changing_this_package_cannot_retrain_the_models(tmp_path):
    """The fingerprint hashes only top-level files, so a subpackage and a config subfolder stay out of it."""
    from crdeck.config import Paths
    assert Path(dm.__file__).parent.name == "futuremeta" and Path(dm.__file__).parent.parent.name == "crdeck"
    assert (PROJECT_ROOT / "config" / "future_meta" / "settings.yaml").exists()
    code, conf = tmp_path / "code", tmp_path / "conf"
    (code / "sub").mkdir(parents=True); (conf / "sub").mkdir(parents=True)
    (code / "a.py").write_text("x = 1"); (conf / "a.yaml").write_text("x: 1")
    paths = Paths("synthetic", tmp_path / "data")
    first = _fingerprint(paths, code, conf)
    (code / "sub" / "b.py").write_text("y = 2"); (conf / "sub" / "b.yaml").write_text("y: 2")
    assert _fingerprint(paths, code, conf) == first
    (code / "a.py").write_text("x = 2")
    assert _fingerprint(paths, code, conf) != first


def test_the_exported_file_holds_no_player_tags():
    f = PROJECT_ROOT / "web" / "future_meta.json"
    if not f.exists():
        pytest.skip("web/future_meta.json is written by scripts/future_meta.py")
    text = f.read_text(encoding="utf-8")
    assert "#" not in text
    assert "player_tag" not in text
    json.loads(text)
