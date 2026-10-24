"""Card-vs-card matchups and the counter search.

The strength model adds up each deck's card weights, so it ranks decks the same way against every
opponent and cannot say what counters what. The matchup model adds one weight per common pairing of a
card on one side with a card on the other:

    z(A, B) = Σ_{i∈A} w_i − Σ_{j∈B} w_j + Σ_{i∈A, j∈B} K(i, j) + β · rating difference
    P(A beats B) = σ(z)

K is antisymmetric (K(i, j) = −K(j, i)): K(i, j) > 0 means a deck holding i did better than expected
against decks holding j, beyond both cards' overall strength. Only pairings with at least
`min_pair_battles` training battles get a weight. It is still a logistic regression (no intercept,
L2, the rating column scaled so it is barely penalized, L-BFGS finished with Newton steps), C chosen
on validation log loss from `C_grid`, refitted on train + validation, then tested once on the test
window against the strength model (paired bootstrap).

Counter search, against an opponent set O (one deck, the most-played decks holding some chosen cards,
or the most-played decks of a style; each with a weight n_o = test-window appearances):

    W(A | O) = Σ_o n_o σ(z(A, o)) / Σ_o n_o           (equal player rating)

Counter cards rank each card form i by its average effect against O in log-odds,
effect(i) = w_i + Σ_o n_o Σ_{j∈o} K(i, j) / Σ_o n_o, listing the matchups behind it, each with its own
exact 90% range. Counter decks come from a beam search
over legal, unlocked decks maximizing W(A | O).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from .dataset import side_rows
from .rules import DeckCard, check_deck, check_partial, deck_key, parse_deck_key
from .strength import rating_diff, sigmoid

Z90 = 1.6448536269514722


def _keys(deck: str) -> list[str]:
    return [k for k in deck.split("|") if k]


def pair_counts(df: pd.DataFrame) -> dict[tuple[str, str], int]:
    """Battles in which card form i is on one side and j on the other (i < j as strings)."""
    cnt: dict[tuple[str, str], int] = {}
    for a, b in zip(df["deck_a"], df["deck_b"]):
        A, B = set(_keys(a)), set(_keys(b))
        for i in A:
            for j in B:
                if i != j:
                    key = (i, j) if i < j else (j, i)
                    cnt[key] = cnt.get(key, 0) + 1
    return cnt


@dataclass
class MatchupModel:
    C: float = 0.01
    min_pair_battles: int = 500
    min_card_games: int = 20
    max_iter: int = 3000
    card_index: dict[str, int] = field(default_factory=dict)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    w: dict[str, float] = field(default_factory=dict)
    w_se: dict[str, float] = field(default_factory=dict)
    K: dict[tuple[str, str], float] = field(default_factory=dict)   # (i, j), i < j: i's side vs j's side
    K_se: dict[tuple[str, str], float] = field(default_factory=dict)
    pair_battles: dict[tuple[str, str], int] = field(default_factory=dict)
    rating_coef: float = 0.0
    newton_steps: int = 0
    max_gradient: float = float("nan")

    # ---------------------------------------------------------------- features
    def _rows(self, df: pd.DataFrame) -> sparse.csr_matrix:
        pidx = {p: t for t, p in enumerate(self.pairs)}
        nc = len(self.card_index)
        rows, cols, vals = [], [], []
        for r, (a, b) in enumerate(zip(df["deck_a"], df["deck_b"])):
            A, B = set(_keys(a)), set(_keys(b))
            for k in A:
                if k in self.card_index:
                    rows.append(r); cols.append(self.card_index[k]); vals.append(1.0)
            for k in B:
                if k in self.card_index:
                    rows.append(r); cols.append(self.card_index[k]); vals.append(-1.0)
            for i in A:
                for j in B:
                    if i == j:
                        continue
                    key, s = ((i, j), 1.0) if i < j else ((j, i), -1.0)
                    t = pidx.get(key)
                    if t is not None:
                        rows.append(r); cols.append(nc + t); vals.append(s)
        X = sparse.csr_matrix((vals, (rows, cols)), shape=(len(df), nc + len(self.pairs)))
        X.sum_duplicates()
        return X

    def _design(self, df: pd.DataFrame) -> sparse.csr_matrix:
        scale = 100.0 / np.sqrt(self.C)     # rating column scaled so its L2 penalty is negligible
        self._scale = scale
        return sparse.hstack([self._rows(df), sparse.csr_matrix(scale * rating_diff(df).reshape(-1, 1))]).tocsr()

    # ---------------------------------------------------------------- fit
    def fit(self, df: pd.DataFrame) -> "MatchupModel":
        counts = pd.Series([k for d in pd.concat([df["deck_a"], df["deck_b"]]) for k in _keys(d)]).value_counts()
        self.card_index = {k: i for i, k in enumerate(sorted(k for k, n in counts.items() if n >= self.min_card_games))}
        pc = pair_counts(df)
        self.pairs = sorted(p for p, n in pc.items() if n >= self.min_pair_battles
                            and p[0] in self.card_index and p[1] in self.card_index)
        self.pair_battles = {p: int(pc[p]) for p in self.pairs}
        X = self._design(df)
        y = df["a_won"].astype(float).to_numpy()
        lr = LogisticRegression(fit_intercept=False, C=self.C, max_iter=self.max_iter, solver="lbfgs").fit(X, y)
        full = lr.coef_.ravel().astype(float)
        n, d = X.shape
        # finish with exact Newton steps on mean log loss + ||w||^2 / (2 C N), as the strength model does
        for _ in range(10):
            p = sigmoid(X @ full)
            g = X.T @ (p - y) / n + full / (self.C * n)
            self.max_gradient = float(np.abs(g).max())
            if self.max_gradient < 1e-10 or d > 8000:
                break
            H = (X.T @ sparse.diags(p * (1 - p)) @ X).toarray() / n + np.eye(d) / (self.C * n)
            full = full - np.linalg.solve(H, g)
            self.newton_steps += 1
        p = sigmoid(X @ full)
        cov_diag = np.full(d, np.nan)
        if d <= 8000:   # Laplace approximation of each weight's standard error
            H = (X.T @ sparse.diags(p * (1 - p)) @ X).toarray() + np.eye(d) / self.C
            cov_diag = np.clip(np.diag(np.linalg.inv(H)), 0, None)
        nc = len(self.card_index)
        keys = sorted(self.card_index, key=self.card_index.get)
        # the counter search reads these, rounded to 7 decimals so the website (which gets the same
        # rounded numbers) computes identical win rates; predictions use the unrounded coefficients
        self.w = {k: round(float(full[i]), 7) for k, i in self.card_index.items()}
        self.w_se = {k: round(float(np.sqrt(cov_diag[i])), 7) for k, i in self.card_index.items()}
        self.K = {pp: round(float(full[nc + t]), 7) for t, pp in enumerate(self.pairs)}
        self.K_se = {pp: round(float(np.sqrt(cov_diag[nc + t])), 7) for t, pp in enumerate(self.pairs)}
        self.rating_coef = float(full[-1]) * self._scale
        self._coef, self._keys = full, keys
        return self

    # ---------------------------------------------------------------- scoring
    def k(self, i: str, j: str) -> float:
        """Matchup weight of card form i (my side) against j (their side)."""
        if i == j:
            return 0.0
        if i < j:
            return self.K.get((i, j), 0.0)
        return -self.K.get((j, i), 0.0)

    def z(self, A: list[str], B: list[str]) -> float:
        """Log-odds that deck A beats deck B at equal rating."""
        sA, sB = set(A), set(B)
        u = sum(self.w.get(i, 0.0) for i in sA) - sum(self.w.get(j, 0.0) for j in sB)
        return u + sum(self.k(i, j) for i in sA for j in sB)

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        return sigmoid(self._design(df) @ self._coef)

    def win_vs(self, A: list[str], opponents: list[tuple[str, int]]) -> float:
        tot = sum(n for _, n in opponents)
        return float(sum(n * sigmoid(self.z(A, _keys(o))) for o, n in opponents) / tot) if tot else float("nan")


def players_by_battle(dib: pd.DataFrame) -> dict[str, frozenset]:
    return {k: frozenset(g) for k, g in dib.groupby("battle_key")["player_tag"]}


def new_player_rows(df: pd.DataFrame, players: dict, seen: set) -> np.ndarray:
    """True for battles in which neither player appears in `seen`."""
    return df["battle_key"].map(lambda k: not (players.get(k, frozenset()) & seen)).to_numpy()


def choose_and_fit(split, mcfg: dict, min_card_games: int, players: dict | None = None) -> tuple[MatchupModel, list[dict]]:
    """C on validation log loss (fitted on train), then the winner refitted on train + validation.

    With `players`, C is chosen on the validation battles whose players never appear in training (when
    there are at least 1,000): the site's users are new players, and the same players recurring across
    windows otherwise rewards weights that memorize regulars (measured on Ranked, 2026-10-24)."""
    from sklearn.metrics import log_loss
    cfg = mcfg["matchup"]
    valid = split.valid
    if players is not None:
        seen = set().union(*[players.get(k, frozenset()) for k in split.train["battle_key"]])
        mask = new_player_rows(split.valid, players, seen)
        if mask.sum() >= 1000:
            valid = split.valid[mask]
    tried, best = [], None
    for C in cfg["C_grid"]:
        m = MatchupModel(C=C, min_pair_battles=int(cfg["min_pair_battles"]), min_card_games=min_card_games,
                         max_iter=int(cfg["max_iter"])).fit(split.train)
        ll = float(log_loss(valid["a_won"].astype(int), m.predict_df(valid), labels=[0, 1]))
        tried.append({"C": C, "pairs": len(m.pairs), "valid_log_loss": ll, "valid_battles": int(len(valid)),
                      "valid_new_players_only": bool(len(valid) < len(split.valid))})
        if best is None or ll < best[0]:
            best = (ll, C)
    for t in tried:
        t["selected"] = t["C"] == best[1]
    final = MatchupModel(C=best[1], min_pair_battles=int(cfg["min_pair_battles"]), min_card_games=min_card_games,
                         max_iter=int(cfg["max_iter"])).fit(split.train_valid)
    return final, tried


def _compare(y, p_add, p_mu, seed, n_boot):
    from sklearn.metrics import roc_auc_score
    p_add, p_mu = np.clip(p_add, 1e-12, 1 - 1e-12), np.clip(p_mu, 1e-12, 1 - 1e-12)
    ll = lambda p: -(y * np.log(p) + (1 - y) * np.log(1 - p))  # noqa: E731
    d = ll(p_mu) - ll(p_add)
    idx = np.random.default_rng(seed).integers(0, len(d), size=(n_boot, len(d)))
    bd = d[idx].mean(axis=1)
    return {"battles": int(len(y)), "log_loss_strength": float(ll(p_add).mean()), "log_loss_matchup": float(ll(p_mu).mean()),
            "difference": float(d.mean()), "difference_ci90": [float(np.quantile(bd, 0.05)), float(np.quantile(bd, 0.95))],
            "auc_strength": float(roc_auc_score(y, p_add)), "auc_matchup": float(roc_auc_score(y, p_mu))}


def player_disjoint_check(ctx, model: MatchupModel, players: dict, seed: int = 0, n_boot: int = 1000) -> dict | None:
    """Refit both models on train + validation battles WITHOUT any player who appears in the test window,
    then compare on the test window: what a new player can expect. None when fewer than 2,000 battles remain."""
    from .strength import CardModel
    te, tv = ctx.split.test, ctx.split.train_valid
    test_players = set().union(*[players.get(k, frozenset()) for k in te["battle_key"]])
    tv2 = tv[new_player_rows(tv, players, test_players)].reset_index(drop=True)
    if len(tv2) < 2000:
        return None
    s = ctx.strength
    add = CardModel(s.hero_observable, s.C, s.max_iter, s.min_feature_games, name=s.name, skill_control=s.skill_control).fit(tv2)
    mu = MatchupModel(C=model.C, min_pair_battles=model.min_pair_battles, min_card_games=model.min_card_games,
                      max_iter=model.max_iter).fit(tv2)
    out = _compare(te["a_won"].astype(float).to_numpy(), add.predict_df(te), mu.predict_df(te), seed, n_boot)
    out.update({"training_battles": int(len(tv2)), "pairs": len(mu.pairs)})
    return out


def evaluate(ctx, model: MatchupModel, seed: int = 0, n_boot: int = 1000, players: dict | None = None) -> dict:
    """Held-out comparison with the strength model on the test window (paired bootstrap), plus the
    player-disjoint check when player tags are given."""
    te = ctx.split.test
    out = _compare(te["a_won"].astype(float).to_numpy(), ctx.strength.predict_df(te), model.predict_df(te), seed, n_boot)
    out.update({"pairs": len(model.pairs), "C": model.C, "test_battles": out["battles"]})
    out["player_disjoint"] = player_disjoint_check(ctx, model, players, seed, n_boot) if players is not None else None
    return out


# ---------------------------------------------------------------- opponent sets
def opponent_sets(ctx, per_set: int) -> dict:
    """The most-played test-window decks of each predicted style, with appearances (shared with the website)."""
    sides = side_rows(ctx.split.test)
    freq = sides["deck_key"].value_counts()
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


# ---------------------------------------------------------------- counters
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


def tie(x: float) -> int:
    """Sort key at fixed precision, identical in the website (values equal up to float noise tie)."""
    import math
    return math.floor(x * 1e10 + 0.5)


def counter_search(ctx, model: MatchupModel, searcher, opponents: list, seeds: list[DeckCard],
                   n_results: int, beam_width: int, min_diff: int) -> list[dict]:
    """Legal, unlocked decks (holding the seeds) with the highest estimated win rate against the opponents.

    For speed, each card form's log-odds effect against every opponent deck is computed once:
    e_c[o] = w_c + Σ_{j∈o} K(c, j), and u_o = Σ_{j∈o} w_j. A deck's score is then
    Σ_o n_o σ(Σ_{c∈A} e_c[o] − u_o) / Σ_o n_o, exactly W(A | O)."""
    from .rules import describe
    from .search import SeedError
    size = ctx.rules.deck_size
    seeds = list(dict.fromkeys(seeds))
    av = getattr(ctx, "availability", None)
    if av is not None:
        locked = [av.why_not(e, describe(e, ctx.cards)) for e in seeds if not av.form_ok(e)]
        if locked:
            raise SeedError(f"not unlocked in {av.arena}: " + "; ".join(locked))
    if not check_partial(seeds, ctx.cards, ctx.rules).legal:
        raise SeedError("seed cards cannot form a legal deck")
    opp = [(_keys(o), n) for o, n in opponents]
    nvec = np.array([n for _, n in opp], float)
    u = np.array([sum(model.w.get(j, 0.0) for j in set(o)) for o, _ in opp])
    key = lambda e: f"{e.card_id}:{e.form}"  # noqa: E731
    def evec(e):
        c = key(e)
        return np.array([model.w.get(c, 0.0) + sum(model.k(c, j) for j in set(o)) for o, _ in opp])
    cands = [c for c in searcher.candidates if key(c) in model.w]
    E = {key(c): evec(c) for c in cands}
    for e in seeds:
        E.setdefault(key(e), evec(e))
    def score(total):
        return float((nvec * sigmoid(total - u)).sum() / nvec.sum())
    start = sum((E[key(e)] for e in seeds), np.zeros(len(opp)))
    beam = [(seeds, start)]
    last: list = []
    for _ in range(size - len(seeds)):
        seen, children = set(), []
        for d, tot in beam:
            ids = {e.card_id for e in d}
            for c in cands:
                if c.card_id in ids:
                    continue
                new = d + [c]
                k = deck_key(new)
                if k in seen or not check_partial(new, ctx.cards, ctx.rules).legal:
                    continue
                seen.add(k)
                t2 = tot + E[key(c)]
                children.append((score(t2), k, new, t2))
        if not children:
            return []
        children.sort(key=lambda t: (-tie(t[0]), t[1]))
        last = children
        beam = [(d, t) for _, _, d, t in children[:beam_width]]
    if len(seeds) == size:
        last = [(score(start), deck_key(seeds), seeds, start)]
    chosen = []
    for s_, k, d, _ in last:
        if not check_deck(d, ctx.cards, ctx.rules).legal:
            continue
        ids = {e.card_id for e in d}
        if all(len(ids - {e.card_id for e in c["entries"]}) >= min_diff for c in chosen):
            chosen.append({"entries": d, "key": k, "win_vs": s_})
        if len(chosen) == n_results:
            break
    for c in chosen:     # never return an illegal deck
        assert check_deck(c["entries"], ctx.cards, ctx.rules).legal
    return chosen
