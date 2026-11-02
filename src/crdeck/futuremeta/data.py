"""Ranked leaderboard battles for the future-meta recommender, parsed apart from data/interim.

Reading the newest raw logs here leaves data/interim and the model caches alone, so no exported model goes stale.
Every table can be cut "as of" a moment: a battle counts only once it had been fetched, so a backtest origin sees
what a real forecast could have seen at that time. Battles keep their earliest fetch time (crdeck.parse.dedupe).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .. import archetype as arch
from ..cards import CardTable, attach_api, load_card_table, load_labels, save_card_table
from ..config import CARD_LABELS, CONFIG_DIR, Paths, collection_config
from ..dataset import model_battles
from ..forecast import collection_periods
from ..parse import OK, FormConfig, ModeRules, parse_files
from ..pipeline import _latest_cards_file, parse_time_iso
from ..rules import DeckRules

STATUSES = ("OK", "DRAW", "MIRROR")   # usage share counts these, as crdeck.forecast does
FETCHED = re.compile(r'"fetched_at"\s*:\s*"([^"]+)"')


def settings() -> dict:
    with (CONFIG_DIR / "future_meta" / "settings.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def cache_dir(paths: Paths) -> Path:
    d = paths.processed / "future_meta"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- periods

def merge_small_periods(periods: pd.DataFrame, battle_times: pd.Series, min_battles: int) -> tuple[pd.DataFrame, dict | None]:
    """Periods with fewer than `min_battles` battles merge into the next one; a small last period is returned
    apart as still in progress. Each row gets its `battles` count and how many raw periods it merged."""
    t = pd.to_datetime(battle_times, utc=True).sort_values()
    rows, carry = [], None
    for _, p in periods.iterrows():
        start = carry["start"] if carry else p["start"]
        merged = (carry["merged"] if carry else 0) + 1
        n = int(t.searchsorted(p["end"], "right") - t.searchsorted(start, "right"))
        row = {"window_id": p["window_id"], "start": start, "end": p["end"], "battles": n, "merged": merged}
        if n < min_battles:
            carry = row
        else:
            rows.append(row)
            carry = None
    out = pd.DataFrame(rows, columns=["window_id", "start", "end", "battles", "merged"])
    return out, (None if carry is None else {**carry, "start": str(carry["start"]), "end": str(carry["end"])})


# ---------------------------------------------------------------- the side table

@dataclass
class RankedData:
    """One row per side of each battle inside a period (arrays, oldest battle first)."""
    cards: CardTable
    rules: DeckRules
    archetype: arch.ArchetypeModel
    periods: pd.DataFrame
    in_progress: dict | None
    battles: pd.DataFrame          # model_battles rows (OK only) with player_a, player_b and first_seen
    decks: list[str]               # deck vocabulary
    keys: list[str]                # card-form vocabulary
    membership: sparse.csr_matrix  # decks x keys
    time: np.ndarray               # datetime64[ns]
    first_seen: np.ndarray         # datetime64[ns]
    hour: np.ndarray               # whole hours since hour0
    period: np.ndarray             # index into periods
    deck: np.ndarray               # index into decks
    player: np.ndarray             # index into players
    players: list[str]
    usable: np.ndarray             # status OK
    won: np.ndarray                # 1.0, 0.0, NaN when not usable
    rating: np.ndarray             # NaN when unknown
    hour0: pd.Timestamp

    @property
    def n_periods(self) -> int:
        return len(self.periods)

    def end(self, p: int) -> np.datetime64:
        return pd.Timestamp(self.periods["end"].iloc[p]).to_datetime64()

    def known_at(self, moment: np.datetime64) -> np.ndarray:
        """Sides of battles played and fetched by `moment`."""
        return (self.time <= moment) & (self.first_seen <= moment)

    def deck_counts(self, mask: np.ndarray, groups: np.ndarray, n_groups: int) -> sparse.csr_matrix:
        """groups x decks: how many sides in `mask` of each group held each deck."""
        return sparse.csr_matrix((np.ones(int(mask.sum())), (groups[mask], self.deck[mask])), shape=(n_groups, len(self.decks)))

    def share_table(self, mask: np.ndarray, groups: np.ndarray, n_groups: int) -> tuple[np.ndarray, np.ndarray]:
        """(share [groups, keys], appearances [groups]) over `mask`; a group with no appearances has NaN shares."""
        counts = self.deck_counts(mask, groups, n_groups)
        appearances = np.asarray(counts.sum(axis=1)).ravel()
        games = (counts @ self.membership).toarray()
        with np.errstate(invalid="ignore", divide="ignore"):
            share = games / appearances[:, None]
        return share, appearances

    def games_table(self, mask: np.ndarray) -> np.ndarray:
        """periods x keys: appearances of each card form over `mask`."""
        return (self.deck_counts(mask, self.period, self.n_periods) @ self.membership).toarray()

    def hourly_shares(self, moment: np.datetime64, min_appearances: int, max_hours: int) -> tuple[np.ndarray, int]:
        """Complete hours before `moment`, newest last, at most `max_hours`: (share [hours, keys], first hour).
        Hours with too few appearances are NaN, which TimesFM treats as gaps."""
        stop = int((moment - self.hour0.to_datetime64()) // np.timedelta64(1, "h"))
        first = max(0, stop - max_hours)
        mask = self.known_at(moment) & (self.hour >= first) & (self.hour < stop)
        share, app = self.share_table(mask, self.hour - first, stop - first) if stop > first else (np.empty((0, len(self.keys))), np.empty(0))
        share[app < min_appearances] = np.nan
        return share, first

    def hour_of(self, moment) -> int:
        return int((np.datetime64(moment) - self.hour0.to_datetime64()) // np.timedelta64(1, "h"))


def fetch_manifest(logs: list[Path]) -> pd.DataFrame:
    """window_id and fetch time of each battle log, read from the start of the file."""
    rows = []
    for f in logs:
        with f.open(encoding="utf-8") as fh:
            m = FETCHED.search(fh.read(1000))
        if m is None:
            with f.open(encoding="utf-8") as fh:
                got = json.load(fh).get("fetched_at")
        else:
            got = m.group(1)
        rows.append({"window_id": f.parts[-3], "kind": "battlelog", "fetched_at": got})
    return pd.DataFrame(rows)


def _private_card_table(paths: Paths) -> CardTable:
    """The newest card list attached to the labels, saved here so processed/cards.parquet stays as trained."""
    with _latest_cards_file(paths).open(encoding="utf-8") as f:
        body = json.load(f)["body"]
    table, _ = attach_api(load_labels(CARD_LABELS), body)
    target = cache_dir(paths) / "cards.parquet"
    save_card_table(table, target)
    return load_card_table(target)


def parse_ranked(paths: Paths, verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Ranked battles and sides from every leaderboard log; cached until a raw log is added."""
    logs = sorted(paths.raw.glob("*/battlelog/*.json"))
    d = cache_dir(paths)
    tag = hashlib.sha1("\n".join(str(p.relative_to(paths.raw)) for p in logs).encode()).hexdigest()
    bf, df, mf, cf = d / "battles.parquet", d / "sides.parquet", d / "fetches.parquet", d / "parse.json"
    cards = _private_card_table(paths)
    if cf.exists() and bf.exists() and df.exists() and mf.exists():
        saved = json.loads(cf.read_text(encoding="utf-8"))
        if saved.get("tag") == tag:
            return pd.read_parquet(bf), pd.read_parquet(df), pd.read_parquet(mf), saved
    ccfg = collection_config()
    win = ccfg.get("window", {})
    window = (parse_time_iso(win.get("start")), parse_time_iso(win.get("end")))
    parsed = parse_files(logs, cards, FormConfig.from_collection(ccfg), None, DeckRules.load().deck_size, window,
                         ModeRules.from_collection(ccfg))
    b = parsed.battles
    b = b[b["mode"] == "ranked"].reset_index(drop=True)
    dib = parsed.decks_in_battle
    dib = dib[dib["battle_key"].isin(b["battle_key"])].reset_index(drop=True)
    fetches = fetch_manifest(logs)
    info = {"tag": tag, "logs": len(logs), "unknown_card_ids": parsed.counts.get("unknown_card_ids", []),
            "last_battle": str(pd.to_datetime(b["battle_time"], utc=True).max()), "status": {k: int(v) for k, v in b["status"].value_counts().items()}}
    b.to_parquet(bf, index=False)
    dib.to_parquet(df, index=False)
    fetches.to_parquet(mf, index=False)
    cf.write_text(json.dumps(info), encoding="utf-8")
    if verbose:
        print(f"parsed {len(logs)} logs: {len(b)} ranked battles, newest {info['last_battle']}", flush=True)
    return b, dib, fetches, info


def assemble(battles: pd.DataFrame, dib: pd.DataFrame, periods: pd.DataFrame, in_progress: dict | None, cards: CardTable,
             rules: DeckRules, archetype: arch.ArchetypeModel) -> RankedData:
    """Build the side table for `periods` from parsed ranked battles and their sides."""
    b = battles[battles["status"].isin(STATUSES)][["battle_key", "battle_time", "status", "fetched_at"]].copy()
    b["t"] = pd.to_datetime(b["battle_time"], utc=True)
    b["first_seen"] = pd.to_datetime(b["fetched_at"], utc=True)
    b = b[(b["t"] > periods["start"].iloc[0]) & (b["t"] <= periods["end"].iloc[-1])]
    ends = pd.to_datetime(periods["end"], utc=True).to_numpy()
    b["period"] = np.searchsorted(ends, b["t"].to_numpy(), "left")
    s = dib.merge(b, on="battle_key").sort_values(["t", "battle_key", "side"], kind="mergesort").reset_index(drop=True)
    hour0 = pd.Timestamp(periods["start"].iloc[0]).floor("h")
    decks = sorted(s["deck_key"].unique())
    deck_idx = {d: i for i, d in enumerate(decks)}
    keys = sorted({k for d in decks for k in d.split("|") if k})
    key_idx = {k: i for i, k in enumerate(keys)}
    rows, cols = [], []
    for i, d in enumerate(decks):
        for k in set(x for x in d.split("|") if x):
            rows.append(i); cols.append(key_idx[k])
    membership = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(decks), len(keys)))
    players = sorted(s["player_tag"].unique())
    player_idx = {p: i for i, p in enumerate(players)}
    usable = (s["status"] == OK).to_numpy()
    won = np.where(usable, s["won"].map({True: 1.0, False: 0.0}).astype(float).to_numpy(), np.nan)
    times = s["t"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    seen = s["first_seen"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    # model tables: OK battles of all time (a fit may use the older ones too), with players and the fetch time
    mb = model_battles(battles, dib, ["ranked"])
    a, z = dib[dib["side"] == "A"].set_index("battle_key"), dib[dib["side"] == "B"].set_index("battle_key")
    mb["player_a"] = a["player_tag"].reindex(mb["battle_key"]).to_numpy()
    mb["player_b"] = z["player_tag"].reindex(mb["battle_key"]).to_numpy()
    seen_by_key = battles.set_index("battle_key")["fetched_at"]
    mb["first_seen"] = pd.to_datetime(seen_by_key.reindex(mb["battle_key"]).to_numpy(), utc=True)
    mb["t"] = pd.to_datetime(mb["battle_time"], utc=True)
    return RankedData(
        cards=cards, rules=rules, archetype=archetype, periods=periods.reset_index(drop=True), in_progress=in_progress,
        battles=mb, decks=decks, keys=keys, membership=membership, time=times, first_seen=seen,
        hour=((s["t"] - hour0) // pd.Timedelta(hours=1)).to_numpy().astype(int), period=s["period"].to_numpy().astype(int),
        deck=s["deck_key"].map(deck_idx).to_numpy().astype(int), player=s["player_tag"].map(player_idx).to_numpy().astype(int),
        players=players, usable=usable, won=won, rating=pd.to_numeric(s["trophies_or_rank"], errors="coerce").to_numpy(dtype=float),
        hour0=hour0.tz_localize(None))


def load(paths: Paths | None = None, verbose: bool = True) -> tuple[RankedData, dict]:
    """Everything the recommender reads: (RankedData, parse info)."""
    paths = paths or Paths.for_source("real")
    cfg = settings()
    battles, dib, fetches, info = parse_ranked(paths, verbose)
    cards = load_card_table(cache_dir(paths) / "cards.parquet")
    b = battles[battles["status"].isin(STATUSES)]
    periods, in_progress = merge_small_periods(
        collection_periods(fetches, float(cfg["periods"]["first_period_hours"])), b["battle_time"], int(cfg["periods"]["min_battles"]))
    model_cfg = yaml.safe_load((CONFIG_DIR / "model.yaml").read_text(encoding="utf-8"))["archetype"]
    am = arch.ArchetypeModel(cards, model_cfg["uncertain_threshold"], model_cfg["C"], int(cfg["seed"]))
    labels = arch.load_labels(paths.archetype_labels)
    am.fit(labels)
    return assemble(battles, dib, periods, in_progress, cards, DeckRules.load(), am), info
