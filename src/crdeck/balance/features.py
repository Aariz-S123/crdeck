"""Signals for the balance watch, computed for one cutoff (docs/balance/DESIGN.md, Sections 2 to 4).

Reads the future-meta side table (`crdeck.futuremeta.data.RankedData`); parses nothing itself. Everything is cut at
the cutoff T: a battle counts only if it was played before T and fetched by T, so a list never sees its future.

Assumptions (each with its test in DESIGN.md Section 4): top Path of Legends players stand in for what the developers
watch; the rating gap removes enough of player skill from the win edge; sides of one player depend on each other and
players don't.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse

from ..strength import RatingBaseline
from .events import BALANCE_LABELS, Event, last_event_before

DAY = np.timedelta64(1, "D")
WINDOW_DAYS = 14
MIN_WINDOW_DAYS = 7
MIN_TOP_SIDES = 50_000        # fewer top sides in the window: no list (status "insufficient")
MIN_CARD_SIDES = 300          # fewer top sides holding a card: "not enough data" for that card
MIN_EDGE_SIDES = 100          # fewer rating-known sides: the card has no win edge
MIN_RELEASE_AGE_DAYS = 14
RELEASE_RECENT_DAYS = 60
MOMENTUM_DAYS = 7
N_BOOT = 1000
SEED = 42
Z90 = 1.6448536269514722
DECK_SIZE = 8


def _np(t) -> np.datetime64:
    """Any moment as a timezone-free UTC datetime64[ns]."""
    ts = pd.Timestamp(t)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_datetime64().astype("datetime64[ns]")


def _day(t: np.datetime64) -> dt.date:
    return pd.Timestamp(t).date()


@dataclass(frozen=True)
class Window:
    """W = [start, end): the days since the last update, at most WINDOW_DAYS, ending at the cutoff."""
    cutoff: np.datetime64
    start: np.datetime64
    end: np.datetime64
    last_event: Event | None
    excluded: tuple[dt.date, ...]      # effective days of balance updates inside W: their battles are left out

    @property
    def days(self) -> float:
        return float((self.end - self.start) / DAY) - len(self.excluded)

    def holds(self, times: np.ndarray) -> np.ndarray:
        keep = (times >= self.start) & (times < self.end)
        for d in self.excluded:
            day0 = np.datetime64(d.isoformat(), "ns")
            keep &= ~((times >= day0) & (times < day0 + DAY))
        return keep


def window_for(cutoff, events) -> Window:
    """The window for cutoff T. E_last is the newest event before T with a nerf, buff or rework (any source)."""
    T = _np(cutoff)
    last = last_event_before(events, pd.Timestamp(T).to_pydatetime(), scoreable_only=False, balance_only=True)
    start = T - WINDOW_DAYS * DAY
    if last is not None:
        start = max(start, np.datetime64(last.effective_date.isoformat(), "ns") + DAY)
    excluded = tuple(e.effective_date for e in events
                     if e.is_balance and start <= np.datetime64(e.effective_date.isoformat(), "ns") < T)
    return Window(cutoff=T, start=start, end=T, last_event=last, excluded=excluded)


def card_matrix(decks: list[str], card_ids: list[int]) -> sparse.csr_matrix:
    """decks x cards, 1 where the deck holds any form of the card."""
    col = {c: j for j, c in enumerate(card_ids)}
    rows, cols = [], []
    for i, d in enumerate(decks):
        for cid in {int(k.split(":")[0]) for k in d.split("|") if k}:
            if cid in col:
                rows.append(i); cols.append(col[cid])
    return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(decks), len(card_ids)))


def release_days(events, snapshots: dict | None = None) -> dict[int, list[tuple[dt.date, str]]]:
    """card_id -> [(day, form)] of every known release of the card or one of its forms: calendar `addition` entries,
    and forms first seen in a saved card list (`crdeck.seasons.card_snapshots`). Cards with no entry were released
    before the calendar starts."""
    out: dict[int, list[tuple[dt.date, str]]] = {}
    for e in events:
        for c in e.changes:
            if c.label == "addition":
                out.setdefault(c.card_id, []).append((e.effective_date, "base" if c.form == "all" else c.form))
    for ch in (snapshots or {}).get("changes", []):
        day = pd.Timestamp(ch["to"]).date()
        for a in ch.get("added", []):
            cid, form = a["key"].split(":")
            known = out.setdefault(int(cid), [])
            # a release already in the calendar (entered from the notes) is not counted again from the later snapshot
            if not any(f == form and d <= day for d, f in known):
                known.append((day, form))
    return {c: sorted(v) for c, v in out.items()}


def robust_z(x: np.ndarray, among: np.ndarray, clip: float = 4.0) -> np.ndarray:
    """(x - median) / (1.4826 * MAD) across the cards in `among`, clipped; all zeros when the MAD is 0."""
    out = np.zeros(len(x))
    if not among.any():
        return out
    v = x[among]
    med = np.median(v)
    mad = np.median(np.abs(v - med))
    if not mad > 0:
        return out
    out[among] = np.clip((v - med) / (1.4826 * mad), -clip, clip)
    return out


def shrink(edge_raw: np.ndarray, se: np.ndarray, known: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Empirical-Bayes shrinkage toward 0: (E, posterior sd, tau2). tau2 = max(0, var(edge_raw) - mean(se^2)) over the
    cards with a known edge; cards without one get E = 0 and sd = 0."""
    E, sd = np.zeros(len(edge_raw)), np.zeros(len(edge_raw))
    if known.sum() < 2:
        return E, sd, 0.0
    tau2 = max(0.0, float(np.var(edge_raw[known])) - float(np.mean(se[known] ** 2)))
    if tau2 > 0:
        w = tau2 / (tau2 + se[known] ** 2)
        E[known] = w * edge_raw[known]
        sd[known] = np.sqrt(tau2 * se[known] ** 2 / (tau2 + se[known] ** 2))
    return E, sd, tau2


@dataclass
class Features:
    status: str                        # "ok" or "insufficient"
    reason: str | None
    window: Window
    card_ids: list[int]
    n_sides: int = 0                   # top sides in W
    n_players: int = 0
    n_battles: int = 0                 # rating-known OK top battles in W (the edge's battles)
    beta: float | None = None          # rating model coefficient per 100 rating points
    tau2: float = 0.0
    momentum_ok: bool = False          # W spans the full 14 days, so the week-on-week change exists
    arrays: dict[str, np.ndarray] = field(default_factory=dict)
    groups: list[dict] = field(default_factory=list)
    releases: dict[int, list[tuple[dt.date, str]]] = field(default_factory=dict)

    def __getitem__(self, name: str) -> np.ndarray:
        return self.arrays[name]


def _logit(p: np.ndarray) -> np.ndarray:
    return np.log(p / (1 - p))


def compute(data, events, cutoff, card_ids: list[int], *, releases: dict | None = None, ignore_fetch: bool = False,
            n_boot: int = N_BOOT, seed: int = SEED, min_top_sides: int = MIN_TOP_SIDES, min_card_sides: int = MIN_CARD_SIDES,
            min_edge_sides: int = MIN_EDGE_SIDES) -> Features:
    """Every signal of DESIGN.md Section 4 for one cutoff. `ignore_fetch` waives the "fetched by T" rule: only the
    retrospective 2026-10-19 pilot may use it (DESIGN.md Section 6, step 4)."""
    W = window_for(cutoff, events)
    T = W.cutoff
    releases = releases if releases is not None else release_days(events)
    feats = Features(status="ok", reason=None, window=W, card_ids=list(card_ids), releases=releases)
    K = len(card_ids)

    played = data.time < T
    known = played if ignore_fetch else played & (data.first_seen <= T)
    core = data.core if data.core is not None else np.ones(len(data.time), dtype=bool)
    in_w = known & W.holds(data.time)
    top = in_w & core
    feats.n_sides = int(top.sum())
    feats.n_players = int(len(np.unique(data.player[top])))
    if W.days < MIN_WINDOW_DAYS:
        feats.status, feats.reason = "insufficient", f"the window since the last update is {W.days:g} days, under {MIN_WINDOW_DAYS}"
        return feats
    if feats.n_sides < min_top_sides:
        feats.status, feats.reason = "insufficient", f"{feats.n_sides} top sides in the window, under {min_top_sides}"
        return feats

    C = card_matrix(data.decks, card_ids)                       # decks x cards
    P = len(data.players)
    rng = np.random.default_rng(seed)
    boot = rng.poisson(1.0, size=(n_boot, P)).astype(float)     # one weight per player per draw

    def per_player(mask: np.ndarray, values: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(players x cards sums of `values` over the sides in mask holding each card, players' side counts)."""
        v = np.ones(int(mask.sum())) if values is None else values
        side_deck = sparse.csr_matrix((v, (data.player[mask], data.deck[mask])), shape=(P, len(data.decks)))
        return np.asarray((side_deck @ C).todense()), np.bincount(data.player[mask], minlength=P).astype(float)

    # ---- usage among top players, with the player bootstrap
    held, sides_p = per_player(top)
    sides_card = held.sum(axis=0)
    usage = sides_card / feats.n_sides
    draws = (boot @ held) / (boot @ sides_p)[:, None]
    usage_lo, usage_hi = np.percentile(draws, [5, 95], axis=0)
    players_card = (held > 0).sum(axis=0)
    N = len(card_ids)
    avg = DECK_SIZE / N
    U = np.log((usage + 0.5 / feats.n_sides) / avg)

    # ---- usage across every league and arena, each counting the same (shown, never scored)
    w_all = data.weights(in_w)
    usage_all = np.asarray(C.T @ np.bincount(data.deck[in_w], weights=w_all, minlength=len(data.decks))).ravel() / max(w_all.sum(), 1e-12)
    if data.groups is not None and data.group is not None:
        for g, name in enumerate(data.groups):
            gm = in_w & (data.group == g)
            n_g = int(gm.sum())
            if n_g >= min_card_sides:
                share = np.asarray(C.T @ np.bincount(data.deck[gm], minlength=len(data.decks))).ravel() / n_g
                feats.groups.append({"group": name, "sides": n_g, "usage": share})

    # ---- raw win rate (for the 45-55% band baseline): OK top sides, no rating needed
    ok = top & data.usable
    games_ok = np.asarray(C.T @ np.bincount(data.deck[ok], minlength=len(data.decks))).ravel()
    wins_ok = np.asarray(C.T @ np.bincount(data.deck[ok], weights=data.won[ok], minlength=len(data.decks))).ravel()
    with np.errstate(invalid="ignore", divide="ignore"):
        wr_raw = np.where(games_ok > 0, wins_ok / games_ok, np.nan)

    # ---- win edge: result minus the rating-only expectation, on rating-known OK top battles in W
    edge_raw, se, edge_known, edge_sides = np.zeros(K), np.zeros(K), np.zeros(K, dtype=bool), np.zeros(K)
    b = data.battles
    bt = b["t"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    bseen = b["first_seen"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    keep = (bt < T) & W.holds(bt) & b["rating_diff"].notna().to_numpy()
    if not ignore_fetch:
        keep &= bseen <= T
    bw = b[keep]
    feats.n_battles = int(len(bw))
    if len(bw) >= 2 and bw["a_won"].nunique() == 2:
        rating = RatingBaseline().fit(bw)
        feats.beta = float(rating.lr.coef_[0][0])
        resid_a = bw["a_won"].astype(float).to_numpy() - rating.predict_df(bw)
        deck_idx = {d: i for i, d in enumerate(data.decks)}
        player_idx = {p: i for i, p in enumerate(data.players)}
        da, db = bw["deck_a"].map(deck_idx), bw["deck_b"].map(deck_idx)
        pa, pb = bw["player_a"].map(player_idx), bw["player_b"].map(player_idx)
        seen = (da.notna() & db.notna() & pa.notna() & pb.notna()).to_numpy()     # in the side table's vocabularies
        d2 = np.r_[da[seen].to_numpy(dtype=int), db[seen].to_numpy(dtype=int)]
        p2 = np.r_[pa[seen].to_numpy(dtype=int), pb[seen].to_numpy(dtype=int)]
        r2 = np.r_[resid_a[seen], -resid_a[seen]]
        Rs = np.asarray((sparse.csr_matrix((r2, (p2, d2)), shape=(P, len(data.decks))) @ C).todense())
        Ns = np.asarray((sparse.csr_matrix((np.ones(len(r2)), (p2, d2)), shape=(P, len(data.decks))) @ C).todense())
        edge_sides = Ns.sum(axis=0)
        edge_known = edge_sides >= min_edge_sides
        with np.errstate(invalid="ignore", divide="ignore"):
            edge_raw = np.where(edge_sides > 0, Rs.sum(axis=0) / edge_sides, 0.0)
            ed = (boot @ Rs) / (boot @ Ns)
        se = np.where(edge_known, np.nanstd(ed, axis=0), 0.0)
        edge_raw = np.where(edge_known, edge_raw, 0.0)
    E, E_sd, feats.tau2 = shrink(edge_raw, se, edge_known)

    # ---- momentum: this week's usage against the week before (only when W spans both weeks)
    M = np.zeros(K)
    feats.momentum_ok = W.days >= WINDOW_DAYS
    usage_last = usage_prev = np.full(K, np.nan)
    mid = T - MOMENTUM_DAYS * DAY
    last_m, prev_m = top & (data.time >= mid), top & (data.time < mid)
    n_last, n_prev = int(last_m.sum()), int(prev_m.sum())
    if feats.momentum_ok and n_last and n_prev:
        k_last = np.asarray(C.T @ np.bincount(data.deck[last_m], minlength=len(data.decks))).ravel()
        k_prev = np.asarray(C.T @ np.bincount(data.deck[prev_m], minlength=len(data.decks))).ravel()
        usage_last, usage_prev = k_last / n_last, k_prev / n_prev
        M = _logit(np.clip(usage_last + 0.5 / n_last, 1e-9, 1 - 1e-9)) - _logit(np.clip(usage_prev + 0.5 / n_prev, 1e-9, 1 - 1e-9))
    else:
        feats.momentum_ok = False

    # ---- releases and eligibility
    day_T = _day(T)
    recent = np.zeros(K, dtype=bool)
    new_card = np.zeros(K, dtype=bool)
    for j, cid in enumerate(card_ids):
        for day, form in releases.get(cid, []):
            if day <= day_T and (day_T - day).days <= RELEASE_RECENT_DAYS:
                recent[j] = True
            if form == "base" and day <= day_T and (day_T - day).days < MIN_RELEASE_AGE_DAYS:
                new_card[j] = True
    few = sides_card < min_card_sides
    eligible = ~few & ~new_card

    feats.arrays = {
        "usage_top": usage, "usage_lo": usage_lo, "usage_hi": usage_hi, "usage_all": usage_all, "U": U,
        "sides_top": sides_card, "players_top": players_card.astype(float),
        "wr_raw": wr_raw, "games_ok": games_ok,
        "edge_raw": edge_raw, "edge_se": se, "edge": E, "edge_sd": E_sd, "edge_known": edge_known, "edge_sides": edge_sides,
        "momentum": M, "usage_last": usage_last, "usage_prev": usage_prev,
        "release_recent": recent, "new_card": new_card, "too_few": few, "eligible": eligible,
    }
    return feats
