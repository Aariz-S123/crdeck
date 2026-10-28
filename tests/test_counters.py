"""Counter page: counter cards, real-deck counter decks, tech swaps, held-out records, and the cache rule
that keeps this post-training code from forcing a retrain."""

from __future__ import annotations

from pathlib import Path

import pytest

import crdeck
from crdeck import counters as cm
from crdeck.config import Paths
from crdeck.dataset import side_rows
from crdeck.explain import structural_warnings
from crdeck.matchup import MatchupModel
from crdeck.pipeline import _fingerprint
from crdeck.rules import check_deck, deck_key, parse_deck_key
from crdeck.search import Searcher
from tests.test_matchup import FILLER, planted_battles


def test_counter_cards_rank_the_planted_counter_first():
    m = MatchupModel(C=1.0, min_pair_battles=500, min_card_games=20).fit(planted_battles())
    opp = [["2:base|" + "|".join(FILLER[:7]), 10]]
    top = cm.counter_cards(m, ["1:base"] + FILLER, opp, 3)
    assert top[0]["card"] == "1:base" and top[0]["effect"] > 0
    t = top[0]["best_against"][0]
    assert t["card"] == "2:base" and t["ci90"][0] > 0 and t["share"] == 1.0


def test_decks_with_keeps_only_decks_holding_every_card():
    all_decks = [["1:base|2:base", 5], ["1:base|3:base", 4], ["2:base", 3]]
    assert cm.decks_with(all_decks, ["1:base"], 10) == [["1:base|2:base", 5], ["1:base|3:base", 4]]


@pytest.fixture(scope="module")
def setup(small_ctx):
    ctx = small_ctx
    s = Searcher(ctx)
    pool = cm.counter_pool(ctx, 5, 400)
    opp = [[d, int(n)] for d, n in side_rows(ctx.split.test)["deck_key"].value_counts().head(8).items()]
    return ctx, s, pool, opp


def test_pool_holds_only_legal_decks_played_often_enough(setup):
    ctx, _, pool, _ = setup
    freq = side_rows(ctx.split.train_valid)["deck_key"].value_counts()
    assert pool, "the synthetic data repeats decks, so the pool is not empty"
    assert [n for _, n in pool] == sorted((n for _, n in pool), reverse=True)
    for d, n in pool:
        assert n == freq[d] >= 5
        assert check_deck(parse_deck_key(d), ctx.cards, ctx.rules).legal


def test_counter_decks_are_real_decks_ranked_by_the_counter_score(setup):
    ctx, s, pool, opp = setup
    res = cm.counter_decks(ctx, ctx.matchup, s, opp, pool, n_results=3, min_diff=2)
    assert res
    keys = dict(pool)
    for r in res:
        assert r["key"] in keys and r["played"] == keys[r["key"]]                 # a real deck, never invented
        assert abs(r["win_vs"] - ctx.matchup.win_vs(r["key"].split("|"), opp)) < 1e-9
        ev = s.evaluate(r["entries"])
        assert abs(r["score"] - (r["win_vs"] + s.weight * ev.mean_synergy + s.co_weight * ev.mean_log_lift)) < 1e-12
    assert [r["score"] for r in res] == sorted((r["score"] for r in res), reverse=True)
    for i, a in enumerate(res):
        for b in res[:i]:
            assert len({e.card_id for e in a["entries"]} - {e.card_id for e in b["entries"]}) >= 2


def test_tech_swaps_are_like_for_like_improvements_without_new_warnings(setup):
    ctx, s, pool, opp = setup
    swaps = []
    for o in opp:
        for r in cm.counter_decks(ctx, ctx.matchup, s, [o], pool, n_results=3, min_diff=2):
            if r["swap"]:
                swaps.append((r, r["swap"]))
    assert swaps, "some counter deck can be improved by one change"
    for r, w in swaps:
        old, new = ctx.cards[w["replace"].card_id], ctx.cards[w["with"].card_id]
        assert (old.card_type, old.is_win_condition) == (new.card_type, new.is_win_condition)
        assert w["replace"] in r["entries"] and w["with"] not in r["entries"]
        assert w["key"] == deck_key(w["entries"]) and check_deck(w["entries"], ctx.cards, ctx.rules).legal
        assert w["win_vs"] > r["win_vs"] and w["score"] > r["score"]
        codes = lambda d: {x.code for x in structural_warnings(d, ctx.cards, ctx.cfg["warnings"])}  # noqa: E731
        assert codes(w["entries"]) <= codes(r["entries"])


def test_deck_records_count_each_test_game_once(setup):
    ctx, _, pool, _ = setup
    rec, rec_new = cm.deck_records(ctx, pool, cm.new_player_sides(ctx))
    if not ctx.archetype.fitted:
        assert rec == {}
        return
    sides = side_rows(ctx.split.test)
    for d, _ in pool[:20]:
        games = sides[sides["deck_key"] == d]
        assert sum(g for g, _ in rec.get(d, {}).values()) == len(games)
        assert sum(w for _, w in rec.get(d, {}).values()) == int(games["won"].sum())
        assert sum(g for g, _ in rec_new.get(d, {}).values()) <= len(games)


def test_summary_and_verdict_inputs():
    out = cm._summary({"counter": [400, 280], "field": [400, 220], "all": [4000, 2000]})
    assert out["counter"]["rate"] == 0.7 and out["counter"]["ci90"][0] < 0.7 < out["counter"]["ci90"][1]
    assert out["vs_field"][1] > 0 and out["vs_all"][1] > 0
    same = cm._summary({"counter": [50, 26], "field": [50, 25], "all": [500, 250]})
    assert same["vs_field"][1] < 0 < same["vs_field"][2]


def test_post_training_files_do_not_change_the_cache_fingerprint(tmp_path):
    code, conf = tmp_path / "code", tmp_path / "conf"
    code.mkdir()
    conf.mkdir()
    for f, text in ((code / "model.py", "a = 1"), (code / "counters.py", "b = 1"),
                    (conf / "model.yaml", "x: 1"), (conf / "counters.yaml", "y: 1")):
        f.write_text(text)
    paths = Paths(source="synthetic", root=tmp_path)
    fp = lambda: _fingerprint(paths, code_dir=code, config_dir=conf)  # noqa: E731
    before = fp()
    (code / "counters.py").write_text("b = 2")
    (conf / "counters.yaml").write_text("y: 2")
    assert fp() == before
    (code / "model.py").write_text("a = 2")
    assert fp() != before


def test_training_code_never_imports_the_counter_module():
    import ast
    for f in Path(crdeck.__file__).parent.glob("*.py"):
        if f.name == "counters.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                continue
            assert not any(n == "counters" or n.endswith(".counters") for n in names), f.name
