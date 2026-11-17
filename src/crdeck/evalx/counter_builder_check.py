"""Forward check of the counter deck builder (docs/fable-brief/BLUEPRINT.md 8.4.1, "Honest evaluation"). Experimental.

Question: when someone keeps losing to a set of cards, do the builder's three decks win more often against decks
holding those cards, in battles the models never saw, than simple alternatives?

- Query sets: QUERIES per mode (seed 42), each the union of the card forms of two real decks drawn from the sides of
  the validation window (so a set is the kind of thing a player could meet, and every input is known before the test
  window).
- Lists, from the same qualifying pool decks the page uses (legal and unlocked by construction of the pool, the deck
  norms of Engine.suggestionRule, the group's 5th to 95th percentile of average elixir), any style:
    builder      the builder's top 3 (card-field fit, crdeck.counters.builder_*; the exact-opponent path is not used here
                 because two decks' worth of cards is almost always more than 8)
    most_played  the most-played qualifying deck in the mode
    random       one qualifying deck drawn at random per query (seed 42)
- Outcome: test-window games of each listed deck against opponent decks holding at least MIN_OVERLAP of the set's
  forms. A game counts at most once per list, however many query sets put it there (the same popular decks meet the
  same opponents in many sets; counting them each time multiplied a few games into hundreds).
- Ranges: paired bootstrap over the listed deck's player, REPLICATES draws, seed 42: every list is recomputed from the
  same draw. Verdict: "better" when the whole 90% range of builder − random is above 0; "too_few" under MIN_GAMES
  games for the builder or for the random list; else "not_shown".
- Raw wins, not adjusted for player skill: decks the model likes may be the decks of stronger players. Read a
  "better" verdict with that in mind.

Assumption: a query set's later opponents are the test-window decks holding at least MIN_OVERLAP of its forms. Test:
vary MIN_OVERLAP (3 and 5) and see whether the verdict moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse

from .. import counters as cm
from ..dataset import side_rows
from ..explain import structural_warnings
from ..rules import parse_deck_key

QUERIES, REPLICATES, SEED = 500, 2000, 42
MIN_OVERLAP, MIN_GAMES = 4, 30
STRICT = {"NO_WIN_CONDITION", "NO_AIR_DEFENSE", "NO_SPELL", "NO_TANK_ANSWER", "ELIXIR_HIGH", "ELIXIR_LOW"}
LISTS = ("builder", "most_played", "random")


def passes_norms(entries, cards, cfg) -> bool:
    """Engine.suggestionRule([]).full: at most one tank and none of the strict deck warnings."""
    tanks = sum(1 for e in entries if e.card_id in cards and "tank" in cards[e.card_id].roles)
    return tanks <= 1 and not any(w.code in STRICT for w in structural_warnings(entries, cards, cfg["warnings"]))


def avg_elixir(entries, cards) -> float | None:
    v = [cards[e.card_id].elixir for e in entries if e.card_id in cards and cards[e.card_id].elixir is not None and not cards[e.card_id].elixir_variable]
    return sum(v) / len(v) if v else None


def qualifying(ctx, pool: list) -> list[tuple[str, int]]:
    rows = []
    for d, n in pool:
        ents = parse_deck_key(d)
        if passes_norms(ents, ctx.cards, ctx.cfg):
            rows.append((d, n, avg_elixir(ents, ctx.cards)))
    bounds = cm.builder_elixir_bounds([(e, n) for _, n, e in rows if e is not None])
    if bounds:
        rows = [r for r in rows if r[2] is not None and bounds[0] - 1e-9 <= r[2] <= bounds[1] + 1e-9]
    return [(d, n) for d, n, _ in rows]


def query_sets(ctx, n: int = QUERIES, seed: int = SEED) -> list[list[str]]:
    sides = side_rows(ctx.split.valid)["deck_key"].to_numpy()
    if len(sides) < 2:
        return []
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        a, b = rng.choice(len(sides), 2, replace=False)
        out.append(sorted(set(sides[a].split("|")) | set(sides[b].split("|"))))
    return out


def run(ctx, model, searcher, pool: list, queries: int = QUERIES, replicates: int = REPLICATES, seed: int = SEED,
        min_overlap: int = MIN_OVERLAP, players: pd.DataFrame | None = None) -> dict:
    cand = qualifying(ctx, pool)
    if len(cand) < 3:
        return {"skipped": f"only {len(cand)} qualifying pool decks"}
    sets = query_sets(ctx, queries, seed)
    if not sets:
        return {"skipped": "no validation battles"}
    evals = cm.pool_evaluations(searcher, cand)
    keys = sorted(model.w)
    kidx = {k: i for i, k in enumerate(keys)}
    F = len(keys)
    w = np.array([model.w[k] for k in keys])
    Kd = np.zeros((F, F))
    for (i, j), v in model.K.items():
        if i in kidx and j in kidx:
            Kd[kidx[i], kidx[j]], Kd[kidx[j], kidx[i]] = v, -v
    deck_keys = [d for d, _ in cand]
    rows, cols = [], []
    for r, d in enumerate(deck_keys):
        for k in set(d.split("|")):
            if k in kidx:
                rows.append(r); cols.append(kidx[k])
    D = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(deck_keys), F))
    own = D @ w
    most_played = max(cand, key=lambda t: (t[1], t[0]))[0]
    rng = np.random.default_rng(seed + 1)
    nres, min_diff = int(cm.counters_config()["n_results"]), int(ctx.cfg["search"]["min_diff_cards"])

    # test-window sides: my deck, the opponent's card forms, won, my player
    te = ctx.split.test
    me = np.r_[te["deck_a"].to_numpy(), te["deck_b"].to_numpy()]
    op = np.r_[te["deck_b"].to_numpy(), te["deck_a"].to_numpy()]
    won = np.r_[te["a_won"].astype(float).to_numpy(), 1 - te["a_won"].astype(float).to_numpy()]
    bk = np.r_[te["battle_key"].to_numpy(), te["battle_key"].to_numpy()]
    side = np.r_[np.full(len(te), "A"), np.full(len(te), "B")]
    if players is None:
        f = ctx.paths.interim / "decks_in_battle.parquet"
        players = pd.read_parquet(f, columns=["battle_key", "side", "player_tag"]).drop_duplicates(["battle_key", "side"]) if f.exists() else None
    if players is not None:
        pl = pd.DataFrame({"battle_key": bk, "side": side}).merge(players, on=["battle_key", "side"], how="left")["player_tag"].to_numpy()
    else:
        pl = np.array([f"row{i}" for i in range(len(me))], dtype=object)
    orows, ocols = [], []
    for r, d in enumerate(op):
        for k in set(d.split("|")):
            if k in kidx:
                orows.append(r); ocols.append(kidx[k])
    O = sparse.csr_matrix((np.ones(len(orows)), (orows, ocols)), shape=(len(op), F))
    me_index: dict[str, np.ndarray] = {}
    for d in set(me):
        me_index[d] = np.flatnonzero(me == d)

    games = []          # (query, list, side row)
    listed_any = 0
    for q, P in enumerate(sets):
        pi = [kidx[k] for k in P if k in kidx]
        if not pi:
            continue
        s = cm.builder_shares(P)
        z = own - s * w[pi].sum() + s * np.asarray(D @ Kd[:, pi].sum(axis=1)).ravel()
        fit = 1 / (1 + np.exp(-z))
        top = cm.builder_rank([{"key": d, "fit": float(fit[i]), "mean_synergy": evals[d].mean_synergy, "mean_log_lift": evals[d].mean_log_lift}
                               for i, d in enumerate(deck_keys)], searcher.weight, searcher.co_weight, nres, min_diff)
        lists = {"builder": [t["key"] for t in top], "most_played": [most_played], "random": [deck_keys[int(rng.integers(len(deck_keys)))]]}
        facing = np.flatnonzero(np.asarray(O[:, pi].sum(axis=1)).ravel() >= min_overlap)
        if not len(facing):
            continue
        fset = set(facing.tolist())
        for name, decks in lists.items():
            for d in decks:
                for r in me_index.get(d, ()):
                    if r in fset:
                        games.append((q, name, r))
                        listed_any += 1
    if not games:
        return {"queries": len(sets), "candidates": len(cand), "games": {n: 0 for n in LISTS}, "verdict": "too_few"}
    g = pd.DataFrame(games, columns=["query", "list", "row"]).drop_duplicates(["list", "row"])
    g["won"], g["player"] = won[g["row"]], pl[g["row"]]
    g["player"] = g["player"].where(pd.notna(g["player"]), "row" + g["row"].astype(str))
    ci, _ = pd.factorize(g["player"], sort=True)
    li = g["list"].map({n: i for i, n in enumerate(LISTS)}).to_numpy()
    C = int(ci.max()) + 1
    N, Wn = np.zeros((C, 3)), np.zeros((C, 3))
    np.add.at(N, (ci, li), 1.0)
    np.add.at(Wn, (ci, li), g["won"].to_numpy())
    tot_n, tot_w = N.sum(0), Wn.sum(0)
    rate = np.where(tot_n > 0, tot_w / np.maximum(tot_n, 1), np.nan)
    brng = np.random.default_rng(seed)
    reps = np.full((replicates, 3), np.nan)
    for b in range(replicates):
        kk = np.bincount(brng.integers(0, C, C), minlength=C).astype(float)
        n_, w_ = kk @ N, kk @ Wn
        with np.errstate(invalid="ignore", divide="ignore"):
            reps[b] = w_ / n_
    def diff(j):
        d = rate[0] - rate[j]
        x = reps[:, 0] - reps[:, j]
        x = x[~np.isnan(x)]
        return None if np.isnan(d) or not len(x) else [float(d), float(np.percentile(x, 5)), float(np.percentile(x, 95))]
    vs_random, vs_most = diff(2), diff(1)
    verdict = "too_few" if tot_n[0] < MIN_GAMES or tot_n[2] < MIN_GAMES or vs_random is None else ("better" if vs_random[1] > 0 else "not_shown")
    return {"queries": len(sets), "candidates": len(cand), "min_overlap": min_overlap, "clusters": C, "replicates": replicates, "seed": seed,
            "games": {n: int(tot_n[i]) for i, n in enumerate(LISTS)}, "wins": {n: int(tot_w[i]) for i, n in enumerate(LISTS)},
            "rate": {n: (None if np.isnan(rate[i]) else float(rate[i])) for i, n in enumerate(LISTS)},
            "vs_random": vs_random, "vs_most_played": vs_most, "verdict": verdict}
