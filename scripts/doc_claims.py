"""Sentences in the Word documentation whose truth depends on the exported results.

scripts/make_docs.py used to hardcode some of them, and they went stale (a "bootstrap" deck range that is really a
delta-method range, "cards only" when the export chose cards plus pairs, "edge not clear" next to an interval
entirely below zero, a "five-page website", a forecast "hidden" while the export said shown). Each function here
reads the relevant fields and picks its wording, so the document follows the data. Tested in tests/test_doc_claims.py.
"""

from __future__ import annotations

from pathlib import Path

# How Engine.score / strength.MetaScorer build a deck's 90% range (code, not data, so this is fixed wording).
DECK_INTERVAL = ("Its 90% range is not a bootstrap: it adds the uncertainty of the learned weights, carried through "
                 "with their covariance (the delta method), to the noise from which opponent decks were sampled.")


def model_choice(selected_model: str, c: float) -> str:
    """Which strength-model version validation picked, from its exported name (e.g. 'card_lr+pairs+skill')."""
    kind = "cards plus pairs" if "pairs" in selected_model else "cards only"
    return f"Ranked chose {kind} at C = {c}"


def edge_over(row: dict, name: str) -> str:
    """The model's log-loss edge over one baseline, worded by whether its 90% range clears zero (negative = better)."""
    lo, hi, d = row["ci90_lo"], row["ci90_hi"], row["delta_log_loss"]
    rng = f"log-loss change {d:.5f}, 90% range {lo:.5f} to {hi:.5f}"
    if hi < 0:
        return (f"its edge over {name} is small but its whole 90% range is below zero ({rng}): a real difference "
                "in the data, not necessarily one a player would notice")
    if lo > 0:
        return f"it does worse than {name} ({rng})"
    return f"its edge over {name} is not clear ({rng})"


def page_count(web_dir: Path) -> int:
    return len(list(Path(web_dir).glob("*.html")))


def forecast_status(meta: dict) -> str:
    """The next-period forecast's state, from modes.json's meta block, including the empty-but-shown case and the
    bands' historical coverage (weighted by card forms scored)."""
    st, bt, fc = meta.get("status", {}), meta.get("backtest", []), meta.get("forecast", [])
    periods, settings = meta.get("periods", []), meta.get("settings", {})
    state = st.get("state")
    if state == "blocked":
        return (f"The Monte Carlo forecast is not available yet: it needs {st.get('min_periods')} collection periods to "
                f"backtest and the project has {st.get('periods')}.")
    scored = sum(b.get("card_forms_scored", 0) for b in bt)
    cov = (sum(b["coverage_90"] * b.get("card_forms_scored", 0) for b in bt) / scored) if scored else None
    mc = sum(b["mae_points_monte_carlo"] for b in bt) / len(bt) if bt else None
    nc = sum(b["mae_points_no_change"] for b in bt) / len(bt) if bt else None
    better = sum(b["mae_points_monte_carlo"] < b["mae_points_no_change"] for b in bt)
    record = ""
    if bt:
        record = (f" Over {len(bt)} backtested periods it missed by {mc:.3f} percentage points of usage share on average, "
                  f"against {nc:.3f} for assuming no change, and was better in {better} of them.")
        if cov is not None:
            record += (f" Its 90% bands held the real share {cov:.0%} of the time, not 90%, so they are too narrow."
                       if cov < 0.9 else f" Its 90% bands held the real share {cov:.0%} of the time.")
        record += " The gate only asks that the average error be no worse than no change; it is not a significance test."
    if state == "not_better":
        return "The Monte Carlo forecast is hidden: on past periods it did worse than assuming no change." + record
    if state == "shown" and not fc:
        last = periods[-1] if periods else {}
        return ("The Monte Carlo forecast passed its backtest gate, but the latest collection period has only "
                f"{last.get('battles', 0):,} battles, so no card form reaches the {settings.get('min_games', 0)} games a "
                "forecast needs and nothing is forecast in this export. It is labelled experimental." + record)
    if state == "shown":
        return f"The Monte Carlo forecast is shown, labelled experimental, for {len(fc)} card forms." + record
    return f"The Monte Carlo forecast's state is “{state}”." + record


# the existing check's verdict words, as sentence endings ("the counter decks ...")
COUNTER_VERDICT = {"beats_strongest": "beat the highest-scoring general decks against their target style",
                   "beats_average": "beat an average eligible pool deck, but not clearly the highest-scoring general decks",
                   "not_shown": "were not shown to beat an average eligible pool deck",
                   "too_few": "had too few games to judge"}


def forward_check(ev: dict | None, slug: str = "ranked", label: str = "Ranked") -> str:
    """The forward counter check for one mode (web/counter_eval.json; design: docs/claude-redesign/EVAL-DESIGN.md):
    its verdict population, rates and paired-bootstrap ranges, and whether the retrospective version agrees."""
    if not ev or slug not in ev.get("modes", {}):
        return f"The forward check of the counter ranking has not been run for {label} in this copy."
    m = ev["modes"][slug]
    if "skipped" in m:
        return f"The forward check of the counter ranking was not run for {label}: {m['skipped']}."
    f, r = m["forward"], m["retrospective"]
    pop = f["populations"][f["headline"]]
    who = "players not in the training battles" if f["headline"] == "new_players" else "every player"
    rng = lambda d: f"{100 * d[0]:+.1f} points (90% range {100 * d[1]:+.1f} to {100 * d[2]:+.1f})" if d else "not available"  # noqa: E731
    games = pop["games"]["counter"]
    won = (f"counter decks won {100 * pop['rate']['counter']:.1f}% ({pop['wins']['counter']:,} of {games:,})" if games
           else "counter decks had no games")
    s = (f"A forward version of this check, designed before any of its numbers were computed, fixes every input before the "
         f"test window: each style's opponent decks and the general score's opponents come from the validation window. Its "
         f"ranges come from a paired bootstrap over players ({ev['settings']['replicates']:,} replicates), so shared decks, "
         f"battles and repeat players are allowed for. For {label}, counting {who}, {won}; counter minus highest-scoring "
         f"general decks {rng(pop['vs_field'])}, counter minus all eligible pool decks {rng(pop['vs_all'])}. In the forward "
         f"check the counter decks {COUNTER_VERDICT[f['verdict']]}")
    if r["verdict"] == f["verdict"]:
        return s + "; the retrospective check, with the same kind of ranges, reaches the same verdict."
    return s + f"; in the retrospective check, with the same kind of ranges, they {COUNTER_VERDICT[r['verdict']]}."
