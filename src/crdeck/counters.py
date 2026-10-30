"""Counter cards and counter decks, computed after training from a trained Context.

Nothing here changes a Context, and nothing used while building one imports this module, so this file
and config/counters.yaml are left out of the model cache fingerprint (pipeline.POST_TRAINING): editing
them never forces a retrain. Settings are read fresh from config/counters.yaml on every call.

Opponents. A deck style stands for its `opponents_per_set` most-played test-window decks, a set of
chosen cards for the most-played test-window decks holding all of them; each opponent deck o weighs n_o
(its appearances). With the matchup model (crdeck.matchup), at equal rating:

    W(A | O) = Σ_o n_o σ(z(A, o)) / Σ_o n_o

Counter cards rank each card form i by its average effect against O in log-odds,
effect(i) = w_i + Σ_o n_o Σ_{j∈o} K(i, j) / Σ_o n_o, listing the matchups behind it, each with its own
exact 90% range.

Counter decks are real decks. The first version searched every legal card combination for the highest
W(A | O) and returned decks nobody plays (four tanks and no spell, "85-93%" estimates): the matchup
model adds up card effects and was only ever checked on decks people actually play. Now the candidates
are the decks played at least `pool.min_battles` times in the training battles (legal and unlocked
here; the `pool.max_decks` most played), ranked by the deck builder's own objective with its win term
replaced by the win rate against the opponents:

    score(A) = W(A | O) + synergy_weight · mean pair synergy(A) + cooccurrence_weight · mean log-lift(A)

Tech swap: for each counter deck, the one like-for-like change (same card type, same win-condition
flag) that raises both W(A | O) and the score without adding a deck warning.

Held-out check (`backtest`): in the test window, which the exported models never saw, the records of the
`backtest.top` best-ranked counter decks against each style, compared with as many decks the deck
builder ranks strongest overall and with all pool decks; once with every game and once counting only
games by players who never appear in the training battles. It is retrospective: the opponent decks
standing for each style, and the general score's opponent sample, come from the test window itself.

Forward check (`check_version`, docs/claude-redesign/EVAL-DESIGN.md, design fixed before any result):
the same check with those two inputs taken from the validation window instead, so every input is known
before the test window, and with ranges from a paired bootstrap over players (all groups from the same
draw, so shared decks, battles and players stay shared), plus a style-standardized rate.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .archetype import NO_LABELS, UNCERTAIN
from .config import load_yaml
from .dataset import side_rows
from .explain import structural_warnings
from .matchup import Z90, MatchupModel, _keys
from .rules import DeckCard, check_deck, deck_key, parse_deck_key
from .strength import sigmoid


def counters_config() -> dict:
    """config/counters.yaml, read on every call (it is not part of a cached Context)."""
    return load_yaml("counters.yaml")


def tie(x: float) -> int:
    """Sort key at fixed precision, identical in the website (values equal up to float noise tie)."""
    return math.floor(x * 1e10 + 0.5)


# ---------------------------------------------------------------- opponent sets
def opponent_sets(ctx, per_set: int) -> dict:
    """The most-played test-window decks of each predicted style, with appearances (shared with the website)."""
    freq = side_rows(ctx.split.test)["deck_key"].value_counts()
    styles: dict[str, list] = {}
    if ctx.archetype.fitted:
        for d, n in freq.head(3000).items():
            lab = ctx.archetype.predict(parse_deck_key(d)).label
            styles.setdefault(lab, [])
            if len(styles[lab]) < per_set:
                styles[lab].append([d, int(n)])
    return {"styles": styles, "decks": [[d, int(n)] for d, n in freq.head(3000).items()]}


def decks_with(all_decks: list, cards: list[str], per_set: int) -> list:
    """Most-played decks holding every chosen card form (cards as 'id:form')."""
    need = set(cards)
    return [[d, n] for d, n in all_decks if need <= set(_keys(d))][:per_set]


# ---------------------------------------------------------------- counter cards
def counter_cards(model: MatchupModel, candidates: list[str], opponents: list, top: int) -> list[dict]:
    """Card forms ranked by their average log-odds effect against the opponent set:
    effect(i) = w_i + Σ_o n_o Σ_{j∈o} K(i, j) / Σ_o n_o.

    No combined range is given for the effect: its parts are strongly correlated and the full covariance
    is too large to ship to the website, so each card instead lists the matchups behind it, each with its
    own exact 90% range (Laplace standard error of that one weight)."""
    tot = sum(n for _, n in opponents)
    out = []
    for c in candidates:
        if c not in model.w:
            continue
        terms: dict[str, float] = {}
        for o, n in opponents:
            for j in set(_keys(o)):
                kk = model.k(c, j)
                if kk:
                    terms[j] = terms.get(j, 0.0) + n * kk / tot
        eff = model.w[c] + sum(terms.values())

        def term(j):
            kk = model.k(c, j)
            se = model.K_se.get((c, j) if c < j else (j, c), float("nan"))
            return {"card": j, "weight": kk, "ci90": [kk - Z90 * se, kk + Z90 * se], "share": terms[j] / kk}
        best = [term(j) for j, v in sorted(terms.items(), key=lambda t: (-t[1], t[0]))[:3] if v > 0]
        worst = [term(j) for j, v in sorted(terms.items(), key=lambda t: (t[1], t[0]))[:2] if v < 0]
        out.append({"card": c, "effect": float(eff), "own_weight": model.w[c], "best_against": best, "worst_against": worst})
    out.sort(key=lambda r: (-tie(r["effect"]), r["card"]))
    return out[:top]


# ---------------------------------------------------------------- the real-deck pool
def counter_pool(ctx, min_battles: int, max_decks: int) -> list[tuple[str, int]]:
    """Real decks: played at least `min_battles` times in the training battles (training and validation
    windows), legal and unlocked here; the `max_decks` most played (ties by deck key), with that count."""
    freq = side_rows(ctx.split.train_valid)["deck_key"].value_counts()
    av = getattr(ctx, "availability", None)
    out: list[tuple[str, int]] = []
    for d, n in sorted(freq.items(), key=lambda t: (-t[1], t[0])):
        if n < min_battles or len(out) == max_decks:
            break
        ents = parse_deck_key(d)
        if len(ents) != ctx.rules.deck_size or not check_deck(ents, ctx.cards, ctx.rules).legal:
            continue
        if av is not None and not all(av.form_ok(e) for e in ents):
            continue
        out.append((d, int(n)))
    return out


def pool_evaluations(searcher, pool: list) -> dict:
    """The deck builder's evaluation (field win rate, synergy, log-lift) of every pool deck, by key."""
    return {d: searcher.evaluate(parse_deck_key(d)) for d, _ in pool}


class _Scorer:
    """W(A | O) and the counter score for one opponent set. Each card form's log-odds effect against every
    opponent deck is computed once: e_c[o] = w_c + Σ_{j∈o} K(c, j); with u_o = Σ_{j∈o} w_j,
    W(A | O) = Σ_o n_o σ(Σ_{c∈A} e_c[o] − u_o) / Σ_o n_o. Opponent cards are taken in deck-key order and
    deck cards in key order, the same order as the website, so both add up the same numbers."""

    def __init__(self, ctx, model: MatchupModel, searcher, opponents: list):
        self.ctx, self.m, self.s = ctx, model, searcher
        self.opp = [list(dict.fromkeys(_keys(o))) for o, _ in opponents]
        self.n = np.array([n for _, n in opponents], float)
        self.u = np.array([sum(model.w.get(j, 0.0) for j in o) for o in self.opp])
        self._e: dict[str, np.ndarray] = {}

    def e(self, c: str) -> np.ndarray:
        if c not in self._e:
            w = self.m.w.get(c, 0.0)
            self._e[c] = np.array([w + sum(self.m.k(c, j) for j in o) for o in self.opp])
        return self._e[c]

    def win(self, total: np.ndarray) -> float:
        s = 0.0
        for n, p in zip(self.n.tolist(), sigmoid(total - self.u).tolist()):    # left to right, like the website
            s += n * p
        return s / float(self.n.sum())

    def total(self, entries: list[DeckCard]) -> np.ndarray:
        t = np.zeros(len(self.opp))
        for x in entries:
            t = t + self.e(x.key)
        return t

    def score(self, wv: float, ev) -> float:
        return wv + self.s.weight * ev.mean_synergy + self.s.co_weight * ev.mean_log_lift

    def rank(self, pool: list, evals: dict) -> list[dict]:
        rows = []
        for d, n in pool:
            ents = parse_deck_key(d)
            t = self.total(ents)
            wv, ev = self.win(t), evals[d]
            rows.append({"key": d, "entries": ents, "played": n, "win_vs": wv, "score": self.score(wv, ev),
                         "field_win": ev.win_prob, "mean_synergy": ev.mean_synergy, "mean_log_lift": ev.mean_log_lift,
                         "_total": t})
        rows.sort(key=lambda r: (-tie(r["score"]), r["key"]))
        return rows

    def tech_swap(self, row: dict, played: dict) -> dict | None:
        """The like-for-like single change that raises W(A | O) and the score, without a new deck warning."""
        cards, ents = self.ctx.cards, row["entries"]
        warn = lambda d: {w.code for w in structural_warnings(d, cards, self.ctx.cfg["warnings"])}  # noqa: E731
        base_warn, ids = warn(ents), {e.card_id for e in ents}
        found = []
        for old in ents:
            oc, rest = cards[old.card_id], [e for e in ents if e != old]
            for c in self.s.candidates:
                if c.card_id in ids or c.key not in self.m.w:
                    continue
                cc = cards[c.card_id]
                if cc.card_type != oc.card_type or cc.is_win_condition != oc.is_win_condition:
                    continue
                new = rest + [c]
                if not check_deck(new, cards, self.ctx.rules).legal:
                    continue
                wv = self.win(row["_total"] - self.e(old.key) + self.e(c.key))
                sc = self.score(wv, self.s.evaluate(new))
                if tie(wv) > tie(row["win_vs"]) and tie(sc) > tie(row["score"]):
                    found.append((sc, old.key, c.key, old, c, wv, new))
        found.sort(key=lambda t: (-tie(t[0]), t[1], t[2]))
        for sc, _, _, old, c, wv, new in found:
            if warn(new) <= base_warn:
                k = deck_key(new)
                return {"replace": old, "with": c, "key": k, "entries": sorted(new), "win_vs": wv, "score": sc,
                        "played": played.get(k, 0)}
        return None


def counter_decks(ctx, model: MatchupModel, searcher, opponents: list, pool: list, n_results: int, min_diff: int,
                  tech_swap: bool = True, evals: dict | None = None) -> list[dict]:
    """The best-scoring pool decks against the opponents (each differing from the ones before by at least
    `min_diff` cards), each with its tech swap. Every deck returned is a real, legal, unlocked deck."""
    if not opponents or not pool:
        return []
    evals = evals if evals is not None else pool_evaluations(searcher, pool)
    sc = _Scorer(ctx, model, searcher, opponents)
    played = dict(pool)
    chosen: list[dict] = []
    for r in sc.rank(pool, evals):
        ids = {e.card_id for e in r["entries"]}
        if all(len(ids - {e.card_id for e in c["entries"]}) >= min_diff for c in chosen):
            chosen.append(r)
        if len(chosen) == n_results:
            break
    for r in chosen:
        assert check_deck(r["entries"], ctx.cards, ctx.rules).legal    # pool decks are legal by construction
        r["swap"] = sc.tech_swap(r, played) if tech_swap else None
        del r["_total"]
    return chosen


# ---------------------------------------------------------------- held-out evidence
def new_player_sides(ctx) -> set | None:
    """(battle_key, side) of the test-window decks played by players who never appear in the training
    battles; None when the battle table with player tags is not available."""
    f = ctx.paths.interim / "decks_in_battle.parquet"
    if not f.exists():
        return None
    dib = pd.read_parquet(f, columns=["battle_key", "side", "player_tag"])
    seen = set(dib.loc[dib["battle_key"].isin(set(ctx.split.train_valid["battle_key"])), "player_tag"])
    t = dib[dib["battle_key"].isin(set(ctx.split.test["battle_key"]))]
    return {(b, s) for b, s, p in zip(t["battle_key"], t["side"], t["player_tag"]) if p not in seen}


def deck_records(ctx, pool: list, new_sides: set | None = None) -> tuple[dict, dict | None]:
    """Test-window records of pool decks against each opponent style, {deck: {style: [games, wins]}},
    and the same counting only games by never-seen players (None without player data). The opponent's
    style comes from the archetype model; these battles were never used to fit the exported models."""
    rec: dict[str, dict] = {}
    rec_new: dict[str, dict] | None = {} if new_sides is not None else None
    if not ctx.archetype.fitted or not pool:
        return rec, rec_new
    keys, styles = {d for d, _ in pool}, {}
    te = ctx.split.test
    for bk, a, b, aw in zip(te["battle_key"], te["deck_a"], te["deck_b"], te["a_won"].astype(bool)):
        for side, me, op, won in (("A", a, b, aw), ("B", b, a, not aw)):
            if me not in keys:
                continue
            if op not in styles:
                styles[op] = ctx.archetype.predict(parse_deck_key(op)).label
            for target, ok in ((rec, True), (rec_new, new_sides is not None and (bk, side) in new_sides)):
                if target is not None and ok:
                    r = target.setdefault(me, {}).setdefault(styles[op], [0, 0])
                    r[0] += 1
                    r[1] += int(won)
    return rec, rec_new


def _wilson(w: int, n: int, z: float = Z90) -> list[float]:
    p = w / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, min(c - h, p)), min(1.0, max(c + h, p))]


def _summary(groups: dict) -> dict:
    """Rates with 90% Wilson ranges, and the counter group's difference from the others with a 90% range
    (normal approximation that treats the groups as independent). The groups share decks, battles and
    players, so this difference range is not dependence-aware; `check_version` gives paired bootstrap ranges."""
    out = {}
    for g, (n, w) in groups.items():
        out[g] = {"games": n, "wins": w, "rate": w / n if n else None, "ci90": _wilson(w, n) if n else None}
    nc, wc = groups["counter"]
    for other in ("field", "all"):
        no, wo = groups[other]
        if nc and no:
            pc, po = wc / nc, wo / no
            se = math.sqrt(pc * (1 - pc) / nc + po * (1 - po) / no)
            out[f"vs_{other}"] = [pc - po, pc - po - Z90 * se, pc - po + Z90 * se]
        else:
            out[f"vs_{other}"] = None
    return out


def backtest(ctx, model: MatchupModel, searcher, pool: list, styles: dict, rec: dict, rec_new: dict | None,
             top: int, min_games: int, evals: dict | None = None) -> dict | None:
    """Did the best-ranked counter decks beat each style more often in the held-out test window than the
    decks the deck builder ranks strongest overall, and than all real decks? None without styles or pool."""
    usable = {st: o for st, o in styles.items() if st not in (UNCERTAIN, NO_LABELS) and o}
    if not pool or not usable:
        return None
    evals = evals if evals is not None else pool_evaluations(searcher, pool)
    field = [d for d, _ in sorted(pool, key=lambda t: (-tie(evals[t[0]].objective), t[0]))[:top]]
    every = [d for d, _ in pool]

    def record(decks, st, r):
        n = w = 0
        for d in decks:
            x = r.get(d, {}).get(st)
            if x:
                n, w = n + x[0], w + x[1]
        return [n, w]

    per_style, tot, tot_new = {}, {g: [0, 0] for g in ("counter", "field", "all")}, {g: [0, 0] for g in ("counter", "field", "all")}
    for st, opps in sorted(usable.items()):
        counter = [r["key"] for r in _Scorer(ctx, model, searcher, opps).rank(pool, evals)[:top]]
        row = {}
        for label, r, acc in (("all_players", rec, tot), ("new_players", rec_new, tot_new)):
            if r is None:
                row[label] = None
                continue
            row[label] = {g: record(ds, st, r) for g, ds in (("counter", counter), ("field", field), ("all", every))}
            for g, (n, w) in row[label].items():
                acc[g][0] += n
                acc[g][1] += w
        per_style[st] = row
    pooled = _summary(tot)
    pooled_new = _summary(tot_new) if rec_new is not None else None
    head_new = pooled_new is not None and pooled_new["counter"]["games"] >= min_games
    head = pooled_new if head_new else pooled
    if head["counter"]["games"] < min_games:
        verdict = "too_few"
    elif head["vs_field"] and head["vs_field"][1] > 0:
        verdict = "beats_strongest"
    elif head["vs_all"] and head["vs_all"][1] > 0:
        verdict = "beats_average"
    else:
        verdict = "not_shown"
    return {"top": top, "min_games": min_games, "styles": per_style, "pooled": pooled, "pooled_new": pooled_new,
            "headline": "new_players" if head_new else "all_players", "verdict": verdict}


def observed_decks(pool: list, objectives: dict, seeds: list[str], n_results: int, min_diff: int) -> list[str]:
    """Observed decks for the deck builder (website twin: web/observed.js `select`). From the real-deck pool
    [(deck_key, played)], keep the decks holding every seed card form (keys such as "26000000:evo"), rank them
    by the deck builder's objective `objectives[deck_key]` (fixed precision, then deck key), and keep each one
    that differs from every earlier pick by at least `min_diff` cards (card ids), up to `n_results`. Fewer
    matches give fewer results; nothing is padded."""
    need = set(seeds)
    rows = [d for d, _ in pool if need <= set(d.split("|"))]
    rows.sort(key=lambda d: (-tie(objectives[d]), d))
    chosen: list[str] = []
    ids = lambda d: {int(k.split(":")[0]) for k in d.split("|") if k}  # noqa: E731
    for d in rows:
        mine = ids(d)
        if all(len(mine - ids(c)) >= min_diff for c in chosen):
            chosen.append(d)
        if len(chosen) == n_results:
            break
    return chosen


# ---------------------------------------------------------------- forward check (docs/claude-redesign/EVAL-DESIGN.md)
GROUPS = ("counter", "field", "all")
FEW = 30    # fewest games of every group against a style for it to enter the style-standardized rate


def style_sets(ctx, battles: pd.DataFrame, per_set: int) -> dict:
    """The most-played decks of each predicted style in any window's battles ({style: [[deck, appearances]]}),
    built like opponent_sets()["styles"], which always uses the test window."""
    freq = side_rows(battles)["deck_key"].value_counts()
    styles: dict[str, list] = {}
    if ctx.archetype.fitted:
        for d, n in freq.head(3000).items():
            lab = ctx.archetype.predict(parse_deck_key(d)).label
            styles.setdefault(lab, [])
            if len(styles[lab]) < per_set:
                styles[lab].append([d, int(n)])
    return styles


def window_scorer(ctx, battles: pd.DataFrame):
    """A shallow copy of ctx whose general score samples its opponent decks from `battles` instead of the test
    window, with the exported scorer's size, seed and procedure. The models are shared, not refitted."""
    import copy
    from .strength import MetaScorer
    ds = ctx.cfg["deck_score"]
    opp = pd.concat([battles["deck_a"], battles["deck_b"]], ignore_index=True)
    out = copy.copy(ctx)
    out.scorer = MetaScorer(ctx.strength, opp, ds["n_opponent_decks"], ds["n_bootstrap"], ds["interval"], ctx.cfg["seed"])
    return out


def check_lists(ctx, model: MatchupModel, searcher, pool: list, styles: dict, top: int, evals: dict) -> tuple[dict, list]:
    """The decks of the compared groups, chosen exactly as in backtest(): {style: the `top` counter decks against
    that style's opponent decks} for every usable style, and the `top` decks with the highest general score."""
    usable = {st: o for st, o in styles.items() if st not in (UNCERTAIN, NO_LABELS) and o}
    field = [d for d, _ in sorted(pool, key=lambda t: (-tie(evals[t[0]].objective), t[0]))[:top]]
    counter = {st: [r["key"] for r in _Scorer(ctx, model, searcher, opps).rank(pool, evals)[:top]] for st, opps in sorted(usable.items())}
    return counter, field


def test_games(ctx, pool: list) -> pd.DataFrame:
    """Every test-window game of a pool deck (one side of one battle, counted as in deck_records): battle_key,
    side, deck, the opponent's predicted style, won (0/1), and the player's and the opponent's tags (None
    without the player table)."""
    keys, styles, rows = {d for d, _ in pool}, {}, []
    te = ctx.split.test
    for bk, a, b, aw in zip(te["battle_key"], te["deck_a"], te["deck_b"], te["a_won"].astype(bool)):
        for side, me, op, won in (("A", a, b, aw), ("B", b, a, not aw)):
            if me not in keys:
                continue
            if op not in styles:
                styles[op] = ctx.archetype.predict(parse_deck_key(op)).label
            rows.append((bk, side, me, styles[op], int(won)))
    g = pd.DataFrame(rows, columns=["battle_key", "side", "deck", "style", "won"])
    f = ctx.paths.interim / "decks_in_battle.parquet"
    if not f.exists():
        return g.assign(player=None, opponent=None)
    dib = pd.read_parquet(f, columns=["battle_key", "side", "player_tag"]).drop_duplicates(["battle_key", "side"])
    me = dib.rename(columns={"player_tag": "player"})
    op = dib.assign(side=dib["side"].map({"A": "B", "B": "A"})).rename(columns={"player_tag": "opponent"})
    return g.merge(me, on=["battle_key", "side"], how="left").merge(op, on=["battle_key", "side"], how="left")


def memberships(games: pd.DataFrame, counter: dict, field: list) -> np.ndarray:
    """(games, 3) 0/1: whether each game counts for the counter, field and all group. Only games against a style
    with a counter list count at all; a game can count for several groups (shared decks are kept)."""
    cs, fs = {st: set(v) for st, v in counter.items()}, set(field)
    m = np.zeros((len(games), 3), dtype=np.int8)
    for i, (d, st) in enumerate(zip(games["deck"], games["style"])):
        if st in cs:
            m[i] = (d in cs[st], d in fs, 1)
    return m


def _rates(N: np.ndarray, W: np.ndarray, inc: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Pooled rate per group (wins / games over all styles) and the equal-weight mean of per-style rates over
    the styles `inc` (NaN where a group has no game). N, W: (groups, styles)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        pooled = W.sum(1) / N.sum(1)
        std = (W[:, inc] / N[:, inc]).mean(1) if inc else np.full(len(N), np.nan)
    return pooled, std


def paired_bootstrap(games: pd.DataFrame, member: np.ndarray, cluster, n_boot: int = 2000, seed: int = 42,
                     styles_inc: list[str] | None = None) -> dict:
    """Pooled win rate of each group, the differences counter − field and counter − all, and the same for the
    style-standardized rate, with 90% ranges (5th and 95th percentiles) from resampling whole clusters with
    replacement. Every group is recomputed from the same draw, so shared decks, battles and players stay
    shared. A game without a cluster id is its own cluster. styles_inc: the styles of the standardized rate
    (None: every style where each group has at least FEW games, decided once on the full sample)."""
    keep = member.any(1)
    g, m = games[keep].reset_index(drop=True), member[keep].astype(float)
    cl = pd.Series(list(cluster), dtype=object)[keep].reset_index(drop=True)
    cl = cl.where(cl.notna(), pd.Series([f"row{i}" for i in range(len(cl))], dtype=object))
    ci, _ = pd.factorize(cl, sort=True)
    snames = sorted(set(g["style"]))
    si = g["style"].map({s: k for k, s in enumerate(snames)}).to_numpy(dtype=np.int64)
    C, S = int(ci.max()) + 1 if len(ci) else 0, len(snames)
    n, w = np.zeros((C, 3, S)), np.zeros((C, 3, S))
    won = g["won"].to_numpy(float)
    for k in range(3):
        np.add.at(n, (ci, k, si), m[:, k])
        np.add.at(w, (ci, k, si), m[:, k] * won)
    N, W = n.sum(0), w.sum(0)
    if styles_inc is None:
        styles_inc = [s for k, s in enumerate(snames) if all(N[j, k] >= FEW for j in range(3))]
    inc = [snames.index(s) for s in styles_inc if s in snames]
    pooled, std = _rates(N, W, inc)
    rng, n2, w2 = np.random.default_rng(seed), n.reshape(C, 3 * S), w.reshape(C, 3 * S)
    rep_p, rep_s = np.full((n_boot, 3), np.nan), np.full((n_boot, 3), np.nan)
    for b in range(n_boot if C else 0):
        k = np.bincount(rng.integers(0, C, C), minlength=C).astype(float)
        rep_p[b], rep_s[b] = _rates((k @ n2).reshape(3, S), (k @ w2).reshape(3, S), inc)

    def rng90(x):
        x = x[~np.isnan(x)]
        return [float(np.percentile(x, 5)), float(np.percentile(x, 95))] if len(x) else None

    def diff(point, reps, j):
        d = point[0] - point[j]
        r = rng90(reps[:, 0] - reps[:, j])
        return None if np.isnan(d) or r is None else [float(d)] + r

    num = lambda x: None if np.isnan(x) else float(x)  # noqa: E731
    return {
        "games": {gr: int(N[j].sum()) for j, gr in enumerate(GROUPS)}, "wins": {gr: int(W[j].sum()) for j, gr in enumerate(GROUPS)},
        "rate": {gr: num(pooled[j]) for j, gr in enumerate(GROUPS)}, "rate_ci90": {gr: rng90(rep_p[:, j]) for j, gr in enumerate(GROUPS)},
        "vs_field": diff(pooled, rep_p, 1), "vs_all": diff(pooled, rep_p, 2),
        "standardized": {"styles": [snames[k] for k in inc], "rate": {gr: num(std[j]) for j, gr in enumerate(GROUPS)},
                         "vs_field": diff(std, rep_s, 1), "vs_all": diff(std, rep_s, 2),
                         "undefined_replicates": int(np.isnan(rep_s[:, 0] - rep_s[:, 1]).sum())},
        "clusters": C, "replicates": n_boot, "seed": seed,
    }


def check_verdict(res: dict, min_games: int) -> str:
    """The existing check's verdict words, from paired-bootstrap ranges."""
    if res["games"]["counter"] < min_games:
        return "too_few"
    if res["vs_field"] and res["vs_field"][1] > 0:
        return "beats_strongest"
    if res["vs_all"] and res["vs_all"][1] > 0:
        return "beats_average"
    return "not_shown"


def check_version(ctx, model: MatchupModel, searcher, pool: list, styles: dict, games: pd.DataFrame,
                  new_sides: set | None, top: int, min_games: int, n_boot: int = 2000, seed: int = 42,
                  evals: dict | None = None) -> dict:
    """One version of the check: the groups chosen from these inputs (searcher: whose general score ranks the
    field; styles: the opponent decks per style), then for every player and for players never seen in the
    training battles, the pooled and style-standardized results with player-clustered ranges (primary) and
    opponent-clustered ranges (sensitivity). Headline and verdict follow backtest()."""
    evals = evals if evals is not None else pool_evaluations(searcher, pool)
    counter, field = check_lists(ctx, model, searcher, pool, styles, top, evals)
    member = memberships(games, counter, field)
    out = {"styles": sorted(counter), "field": field, "counter": counter, "populations": {}}
    unseen = None if new_sides is None else np.array([(b, s) in new_sides for b, s in zip(games["battle_key"], games["side"])], dtype=bool)
    for pop, mask in (("all_players", np.ones(len(games), dtype=bool)), ("new_players", unseen)):
        if mask is None:
            out["populations"][pop] = None
            continue
        g, mb = games[mask].reset_index(drop=True), member[mask]
        res = paired_bootstrap(g, mb, g["player"], n_boot, seed)
        opp = paired_bootstrap(g, mb, g["opponent"], n_boot, seed, res["standardized"]["styles"])
        res["opponent_clusters"] = {"vs_field": opp["vs_field"], "vs_all": opp["vs_all"],
                                    "standardized": {k: opp["standardized"][k] for k in ("vs_field", "vs_all")}, "clusters": opp["clusters"]}
        out["populations"][pop] = res
    new = out["populations"]["new_players"]
    out["headline"] = "new_players" if new is not None and new["games"]["counter"] >= min_games else "all_players"
    out["verdict"] = check_verdict(out["populations"][out["headline"]], min_games)
    return out
