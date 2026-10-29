"""Data-dependent sentences of the Word documentation (scripts/doc_claims.py), tested on every branch with small
hand-made inputs instead of the current export, so they stay right when the results change."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import doc_claims as dc  # noqa: E402

BT = [  # two backtest periods: the forecast loses one, wins the other; coverage 0.4 on 100 forms, 0.8 on 300
    {"target_period": 2, "card_forms_scored": 100, "mae_points_monte_carlo": 0.5, "mae_points_no_change": 0.4, "coverage_90": 0.4},
    {"target_period": 3, "card_forms_scored": 300, "mae_points_monte_carlo": 0.3, "mae_points_no_change": 0.6, "coverage_90": 0.8},
]


def meta(state, forecast=(), backtest=BT, last_battles=5000):
    return {"status": {"state": state, "periods": 4, "min_periods": 3}, "backtest": list(backtest), "forecast": list(forecast),
            "periods": [{"battles": 9000}, {"battles": last_battles}], "settings": {"min_games": 200}}


def test_blocked_forecast_says_not_available():
    t = dc.forecast_status(meta("blocked", backtest=[]))
    assert "not available yet" in t and "needs 3" in t and "has 4" in t


def test_hidden_forecast_says_hidden_with_its_record():
    t = dc.forecast_status(meta("not_better"))
    assert "hidden" in t and "better in 1 of them" in t


def test_shown_forecast_reports_weighted_coverage_and_no_significance_claim():
    t = dc.forecast_status(meta("shown", forecast=[{"key": "1:base"}]))
    # (0.4·100 + 0.8·300) / 400 = 70%
    assert "shown" in t and "70%" in t and "too narrow" in t and "not a significance test" in t
    assert "0.400" in t and "0.500" in t  # mean errors: (0.5 + 0.3) / 2 and (0.4 + 0.6) / 2


def test_shown_but_empty_forecast_says_nothing_is_forecast():
    t = dc.forecast_status(meta("shown", forecast=[], last_battles=23))
    assert "passed its backtest gate" in t and "only 23 battles" in t and "nothing is forecast" in t


def test_coverage_with_nothing_scored_is_not_invented():
    t = dc.forecast_status(meta("shown", forecast=[{"key": "1:base"}], backtest=[dict(BT[0], card_forms_scored=0)]))
    assert "held the real share" not in t


def test_edge_wording_follows_the_interval():
    clear = {"delta_log_loss": -0.001, "ci90_lo": -0.0014, "ci90_hi": -0.0007}
    unclear = {"delta_log_loss": -0.0002, "ci90_lo": -0.0006, "ci90_hi": 0.0002}
    worse = {"delta_log_loss": 0.0004, "ci90_lo": 0.0001, "ci90_hi": 0.0007}
    assert "below zero" in dc.edge_over(clear, "rating") and "not clear" not in dc.edge_over(clear, "rating")
    assert "not clear" in dc.edge_over(unclear, "rating")
    assert "does worse" in dc.edge_over(worse, "rating")


def test_model_choice_reads_the_exported_name():
    assert dc.model_choice("card_lr+pairs+skill", 0.01) == "Ranked chose cards plus pairs at C = 0.01"
    assert dc.model_choice("card_lr+skill", 0.1) == "Ranked chose cards only at C = 0.1"


def test_page_count_counts_html_files(tmp_path):
    for name in ("a.html", "b.html", "c.js"):
        (tmp_path / name).write_text("x")
    assert dc.page_count(tmp_path) == 2


def test_deck_interval_names_the_real_method():
    assert "delta method" in dc.DECK_INTERVAL and "not a bootstrap" in dc.DECK_INTERVAL


def test_generator_no_longer_hardcodes_the_stale_claims():
    src = (ROOT / "scripts" / "make_docs.py").read_text(encoding="utf8")
    for stale in ("a bootstrap gives its 90% range", "five-page website", "Ranked chose cards only at",
                  "rating alone is not clear", "So it stays hidden", "one more daily leaderboard collection unlocks"):
        assert stale not in src, stale
