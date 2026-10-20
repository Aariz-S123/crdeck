"""Next-season page: card-list snapshots and new forms, measured meta decks, and the season lock."""

from __future__ import annotations

import json

import pandas as pd

from crdeck.config import Paths
from crdeck.seasons import MIN_SEASON_BATTLES, MIN_SEASONS, _wilson, card_snapshots, meta_decks, season_status


def _cards(tmp, window, fetched, items):
    f = tmp / "raw" / window / "cards" / "cards.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"status": 200, "fetched_at": fetched, "body": {"items": items}}))


def test_snapshots_flag_new_cards_evolutions_and_heroes(tmp_path):
    _cards(tmp_path, "w1", "2026-10-01T00:00:00Z", [{"id": 1, "name": "Knight", "maxEvolutionLevel": 1},
                                                   {"id": 2, "name": "Archers"}])
    # next season: Knight gains a Hero (bit 2), Archers an Evolution, and a new card arrives
    _cards(tmp_path, "w2", "2026-11-03T00:00:00Z", [{"id": 1, "name": "Knight", "maxEvolutionLevel": 3},
                                                   {"id": 2, "name": "Archers", "maxEvolutionLevel": 1},
                                                   {"id": 3, "name": "New Card"}])
    s = card_snapshots(Paths(source="real", root=tmp_path))
    assert [x["card_forms"] for x in s["snapshots"]] == [3, 6]
    (ch,) = s["changes"]
    assert sorted((a["name"], a["form"]) for a in ch["added"]) == [("Archers", "evo"), ("Knight", "hero"), ("New Card", "base")]
    assert ch["removed"] == []


def test_wilson_interval_contains_the_rate_and_narrows():
    lo, hi = _wilson(55, 100)
    assert lo < 0.55 < hi
    lo2, hi2 = _wilson(5500, 10000)
    assert hi2 - lo2 < hi - lo


def _ranked(n_by_month):
    rows, dib = [], []
    for month, n in n_by_month.items():
        for i in range(n):
            k = f"{month}-{i}"
            rows.append({"battle_key": k, "battle_time": pd.Timestamp(f"{month}-15T12:00:00Z"), "mode": "ranked",
                         "status": "OK", "sample": "leaderboard"})
            dib += [{"battle_key": k, "side": "A", "deck_key": "1:base|2:base", "won": True},
                    {"battle_key": k, "side": "B", "deck_key": "3:base|4:base", "won": False}]
    return pd.DataFrame(rows), pd.DataFrame(dib)


def test_season_lock_until_enough_seasons():
    b, d = _ranked({"2026-09": 50, "2026-10": MIN_SEASON_BATTLES})
    st = season_status(b, d, ["2026-08", "2026-09"])
    assert st["state"] == "blocked" and st["covered"] == 1 and st["needed"] == MIN_SEASONS
    assert [s["covered"] for s in st["seasons"]] == [False, True]
    assert "2 more seasons" in st["reason"]
    b, d = _ranked({m: MIN_SEASON_BATTLES for m in ("2026-10", "2026-11", "2026-12")})
    assert season_status(b, d, None)["state"] == "ready_to_backtest"


def test_meta_decks_measured_per_period(tmp_path):
    b, d = _ranked({"2026-10": 150})
    arena = b.iloc[:10].assign(battle_key=lambda x: "arena-" + x["battle_key"], sample="arena_sample")
    b = pd.concat([b, arena])
    d = pd.concat([d, d.iloc[:20].assign(battle_key=lambda x: "arena-" + x["battle_key"])])
    pd.DataFrame([{"window_id": "w1", "kind": "battlelog", "file": "x", "status": 200, "fetched_at": "2026-10-16T00:00:00Z"}]) \
        .to_csv(tmp_path / "raw_manifest.csv", index=False)
    md = meta_decks(Paths(source="real", root=tmp_path), b, d)
    assert len(md["periods"]) == 1
    top = {x["deck_key"]: x for x in md["decks"]}
    assert set(top) == {"1:base|2:base", "3:base|4:base"}
    w = top["1:base|2:base"]
    assert w["games"] == 150 and w["win_rate"] == 1.0          # arena-sample battles are not counted
    assert w["history"][0]["share"] == 0.5 and w["change"] is None
