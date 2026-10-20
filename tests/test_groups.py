"""Leagues and arenas: battle groups read from the battle, the two collection samples, the full
group list for the site, the meta history's fixed population, and the arena collector."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from crdeck import parse as P
from crdeck.api import ApiClient, ApiError
from crdeck.config import Paths, collection_config
from crdeck.dataset import model_battles
from crdeck.parse import FormConfig, ModeRules, mode_groups, mode_slug, parse_battlelog, parse_files
from tests.test_api import CFG, KEY, FakeResp
from tests.test_parse import DECK1, DECK2, side


def battle(cards, btype, gm, arena="Legendary Arena", league=None, t="20261019T120000.000Z", a="#AAA", b="#BBB"):
    x = {"battleTime": t, "type": btype, "gameMode": {"name": gm}, "deckSelection": "collection", "arena": {"name": arena},
         "team": [side(cards, a, DECK1, 2)], "opponent": [side(cards, b, DECK2, 1)]}
    if league is not None:
        x["leagueNumber"] = league
    return x


@pytest.fixture(scope="module")
def rules():
    return ModeRules.from_collection(collection_config())


def test_group_is_league_for_ranked_and_arena_for_trophy_road(cards, rules):
    bs = [battle(cards, "pathOfLegend", "Ranked1v1_NewArena", league=7, t="20261019T120000.000Z"),
          battle(cards, "pathOfLegend", "Ranked1v1_NewArena", league=None, t="20261019T121000.000Z"),
          battle(cards, "trail", "Ladder", arena="Spell Valley", t="20261019T122000.000Z"),
          battle(cards, "pathOfLegend", "Ranked1v1_NewArena", league=9, t="20261019T123000.000Z")]
    b, _, _ = parse_battlelog(bs, "#AAA", "", cards, FormConfig(), modes=rules)
    assert [(x["mode"], x["group"], x["league"]) for x in b] == [
        ("ranked", "Ultimate Champion", 7), ("ranked", None, None), ("trophy_road", "Spell Valley", None), ("ranked", "League 9", 9)]
    assert mode_slug("ranked", "Ultimate Champion") == "ranked__ultimate_champion"


def test_configured_groups_in_game_order():
    cfg = collection_config()
    leagues, arenas = mode_groups(cfg, "ranked"), mode_groups(cfg, "trophy_road")
    assert [g["name"] for g in leagues][:2] == ["Master I", "Master II"] and leagues[-1]["name"] == "Ultimate Champion"
    assert len(leagues) == 7 and [g["league"] for g in leagues] == list(range(1, 8))
    assert arenas[0] == {"name": "Goblin Stadium", "order": 1, "min_trophies": 0}
    assert [a["name"] for a in arenas[-2:]] == ["Seasonal Arena I", "Seasonal Arena II"]
    floors = [a["min_trophies"] for a in arenas]
    assert floors == sorted(floors) and len(arenas) == 34
    assert mode_groups(cfg, "all") == []


def _wrap(body, fetched="2026-10-19T16:00:00Z"):
    return {"status": 200, "fetched_at": fetched, "body": body}


def test_samples_tagged_and_leaderboard_wins_duplicates(cards, rules, tmp_path):
    shared = battle(cards, "trail", "Ladder", arena="Spell Valley", t="20261019T120000.000Z")
    only_arena = battle(cards, "trail", "Ladder", arena="Bone Pit", t="20261019T130000.000Z")
    (tmp_path / "w" / "battlelog").mkdir(parents=True)
    (tmp_path / "w" / "battlelog_arena").mkdir(parents=True)
    # the arena-sample copy of the shared battle was fetched first: the leaderboard tag must still win
    (tmp_path / "w" / "battlelog" / "AAA.json").write_text(json.dumps(_wrap([shared], "2026-10-19T17:00:00Z")))
    (tmp_path / "w" / "battlelog_arena" / "BBB.json").write_text(json.dumps(_wrap([shared, only_arena], "2026-10-19T15:00:00Z")))
    files = sorted(tmp_path.glob("*/battlelog*/*.json"))
    parsed = parse_files(files, cards, FormConfig(), None, 8, (None, None), rules)
    got = dict(zip(parsed.battles["group"], parsed.battles["sample"]))
    assert got == {"Spell Valley": "leaderboard", "Bone Pit": "arena_sample"}
    assert parsed.counts["ok_by_sample"] == {"arena_sample": 1, "leaderboard": 1}
    assert parsed.counts["ok_by_mode_group"] == {"trophy_road|Bone Pit": 1, "trophy_road|Spell Valley": 1}
    mb = model_battles(parsed.battles, parsed.decks_in_battle, ["trophy_road"], "Bone Pit")
    assert len(mb) == 1


def test_meta_history_uses_the_leaderboard_sample_only(cards, rules):
    from crdeck.forecast import period_data
    bs = [battle(cards, "pathOfLegend", "Ranked1v1_NewArena", league=7, t="20261019T120000.000Z"),
          battle(cards, "pathOfLegend", "Ranked1v1_NewArena", league=4, t="20261019T121000.000Z", a="#CCC", b="#DDD")]
    b, d, s = parse_battlelog(bs, "#AAA", "", cards, FormConfig(), modes=rules)
    b[1]["sample"] = "arena_sample"
    parsed = P.dedupe(b, d, s)
    parsed.battles.loc[parsed.battles["battle_key"] == b[1]["battle_key"], "sample"] = "arena_sample"
    periods = pd.DataFrame([{"window_id": "w", "start": pd.Timestamp("2026-10-19T00:00:00Z"), "end": pd.Timestamp("2026-10-20T00:00:00Z")}])
    pdat = period_data(parsed.battles, parsed.decks_in_battle, periods)
    assert pdat.periods["battles"].tolist() == [1]


def test_every_league_and_arena_is_a_site_option(small_ctx):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("export_web", Path(__file__).resolve().parents[1] / "scripts" / "export_web.py")
    ew = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ew)
    cfg = collection_config()
    cands = ew.candidate_modes(small_ctx.paths, cfg)
    assert cands[:3] == [("ranked", None, {}), ("trophy_road", None, {}), ("all", None, {})]
    leagues = [g for m, g, _ in cands if m == "ranked" and g]
    arenas = [(g, meta["min_trophies"]) for m, g, meta in cands if m == "trophy_road" and g and "min_trophies" in meta]
    assert leagues[:7] == [g["name"] for g in mode_groups(cfg, "ranked")]
    assert [a for a, _ in arenas] == [g["name"] for g in mode_groups(cfg, "trophy_road")]


# ---------------------------------------------------------------- arena collector, no network

class RoutedSession:
    """Answers by URL path; unknown paths get an empty battle log."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.split("/v1", 1)[1]
        self.calls.append(path)
        r = self.routes.get(path)
        return r if r is not None else FakeResp(200, [])


def _ladder(arena, opp):
    return {"type": "trail", "gameMode": {"name": "Ladder"}, "deckSelection": "collection", "arena": {"name": arena},
            "team": [{"tag": "#M1"}], "opponent": [{"tag": opp}]}


def _arena_cfg(monkeypatch, sess, tmp_path, **sample):
    full = collection_config()
    full["battles"]["modes"]["trophy_road"]["arenas"] = [["Goblin Stadium", 0], ["Bone Pit", 300], ["Barbarian Bowl", 600]]
    full["arena_sample"] = {"players_per_arena": 2, "max_requests": 100, "snowball": True,
                            "clan_search": {"names": ["a"], "min_members": 1, "limit": 10, "max_pages": 2}, **sample}
    import crdeck.collect as C
    monkeypatch.setattr(C, "collection_config", lambda: full)
    monkeypatch.delenv("CR_API_BASE", raising=False)
    client = ApiClient(paths=Paths(source="real", root=tmp_path), cfg=CFG, session=sess, key=KEY, sleep=lambda s: None)
    return C, client


def test_arena_collector_places_players_by_their_own_arena(monkeypatch, tmp_path):
    sess = RoutedSession({
        "/clans": FakeResp(200, {"items": [{"tag": "#C1"}], "paging": {"cursors": {}}}),
        "/clans/%23C1/members": FakeResp(200, {"items": [
            {"tag": "#M1", "trophies": 50, "arena": {"name": "Goblin Stadium"}},
            {"tag": "#M2", "trophies": 120, "arena": {"name": "Goblin Stadium"}},
            {"tag": "#M3", "trophies": 200, "arena": {"name": "Goblin Stadium"}},   # Goblin Stadium already full
            {"tag": "#M4", "trophies": 350},                                        # no arena field: trophy floor
        ]}),
        "/players/%23M1/battlelog": FakeResp(200, [_ladder("Barbarian Bowl", "#O1")]),
    })
    C, client = _arena_cfg(monkeypatch, sess, tmp_path)
    s = C.collect_arenas(client=client, progress=False)
    got = {a["arena"]: a["players"] for a in s["arenas"]}
    assert got == {"Goblin Stadium": 2, "Bone Pit": 1, "Barbarian Bowl": 1}
    by = {a["arena"]: a for a in s["arenas"]}
    assert by["Barbarian Bowl"].get("ladder opponent") == 1 and by["Bone Pit"].get("clan member") == 1
    assert s["arena_assigned_by"]["trophy floor (config)"] == 1
    assert s["short_arenas"] == ["Bone Pit", "Barbarian Bowl"]
    logs = sorted(p.name for p in (tmp_path / "raw" / "test-window" / "battlelog_arena").glob("*.json"))
    assert logs == ["M1.json", "M2.json", "M4.json", "O1.json"]
    assert not (tmp_path / "raw" / "test-window" / "battlelog").exists()


def test_arena_collector_stops_on_ip_error(monkeypatch, tmp_path):
    sess = RoutedSession({"/clans": FakeResp(200, {"items": [{"tag": "#C1"}]}),
                          "/clans/%23C1/members": FakeResp(403, {"reason": "accessDenied.invalidIp"})})
    C, client = _arena_cfg(monkeypatch, sess, tmp_path)
    with pytest.raises(ApiError, match="403"):
        C.collect_arenas(client=client, progress=False)


def test_arena_collector_respects_request_budget(monkeypatch, tmp_path):
    members = [{"tag": f"#P{i}", "trophies": 10, "arena": {"name": "Goblin Stadium"}} for i in range(10)]
    sess = RoutedSession({"/clans": FakeResp(200, {"items": [{"tag": "#C1"}]}),
                          "/clans/%23C1/members": FakeResp(200, {"items": members})})
    C, client = _arena_cfg(monkeypatch, sess, tmp_path, players_per_arena=10, max_requests=4)
    s = C.collect_arenas(client=client, progress=False)
    assert s["requests_sent"] == 4 and s["stopped_by_request_budget"]


def test_arena_collector_stops_reading_clans_that_add_nobody(monkeypatch, tmp_path):
    # Bone Pit and Barbarian Bowl never appear, so they never fill; the stall guard ends the clan pass
    clans = [{"tag": f"#C{i}", "clanScore": 100 + i, "members": 10} for i in range(30)]
    routes = {"/clans": FakeResp(200, {"items": clans})}
    for i in range(30):
        routes[f"/clans/%23C{i}/members"] = FakeResp(200, {"items": [{"tag": f"#G{i}", "trophies": 10, "arena": {"name": "Goblin Stadium"}}]})
    sess = RoutedSession(routes)
    C, client = _arena_cfg(monkeypatch, sess, tmp_path, snowball=False, stall_clans=5, skip_arenas=["Barbarian Bowl"])
    s = C.collect_arenas(client=client, progress=False)
    assert s["clans_read"] == 7 and s["clan_pass_stopped_by"] == "no new players"   # 2 placed, then 5 in a row add nobody
    assert [a["arena"] for a in s["arenas"]] == ["Goblin Stadium", "Bone Pit"] and s["skipped_arenas"] == ["Barbarian Bowl"]
