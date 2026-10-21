"""Card embeddings: every card form as a vector, learned from which cards are played together.

Training data: deck appearances in the TRAINING window only (one side of one battle each).

  count(i)    = training decks holding card form i
  co(i, j)    = training decks holding both
  PMI(i, j)   = log( co(i, j) * N / (count(i) * count(j)) )     (the log-lift of the synergy data)
  M           = max(PMI, 0) for i != j, 0 on the diagonal         (positive PMI)
  M = U S Vᵀ  (SVD);  vector(i) = row i of U_d · sqrt(S_d), then scaled to length 1

Factorizing positive PMI is the matrix form of word2vec (Levy & Goldberg, 2014): cards that
appear in the same kinds of decks get similar vectors. It is deterministic (no random start).
The dimension d is chosen on the VALIDATION window from DIMS, and tested once on the test window.

Distances are cosine distances in the full d dimensions: distance = 1 - cos(a, b). The 3D view is
a PCA projection used only for the picture; swap distances never use it.

Swap suggestions (embedding_swaps): for each card in the deck that may be replaced, the center of
the OTHER 7 cards is the mean of their unit vectors. Every candidate that keeps the deck legal and
is unlocked is ranked by its distance to that center; among the NEAR nearest, those that raise the
deck's estimated win rate are suggested, each with its distance and win-rate change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .dataset import side_rows
from .rules import DeckCard, check_deck, parse_deck_key

DIMS = (8, 16, 32)
NEAR = 8           # nearest candidates per card considered for a swap
TOP_SWAPS = 6      # suggestions shown
EVAL_DECKS = 100
EVAL_MASK = 2
EVAL_K = 10


def _form_key(e: DeckCard) -> str:
    return f"{e.card_id}:{e.form}"


@dataclass
class CardEmbedding:
    dim: int
    keys: list[str]                          # card forms "id:form"
    vectors: np.ndarray                      # [len(keys), dim], unit length
    index: dict[str, int] = field(default_factory=dict)
    choice: list[dict] = field(default_factory=list)       # validation recall per dimension
    evaluation: dict = field(default_factory=dict)         # test recall vs popular cards
    pca3: np.ndarray | None = None                         # [len(keys), 3] for the picture only
    pca_explained: list[float] = field(default_factory=list)
    style: dict[str, str] = field(default_factory=dict)    # key -> most common deck style of decks holding it

    def __post_init__(self):
        self.index = {k: i for i, k in enumerate(self.keys)}

    def vec(self, e: DeckCard) -> np.ndarray | None:
        i = self.index.get(_form_key(e))
        return None if i is None else self.vectors[i]

    def center(self, entries: list[DeckCard]) -> np.ndarray | None:
        vs = [v for v in (self.vec(e) for e in entries) if v is not None]
        return np.mean(vs, axis=0) if vs else None

    def distance(self, v: np.ndarray, center: np.ndarray) -> float:
        n = float(np.linalg.norm(center))
        return 1.0 - float(v @ center) / n if n > 0 else 1.0


def ppmi(decks: pd.Series, keys: list[str]) -> np.ndarray:
    idx = {k: i for i, k in enumerate(keys)}
    rows, cols = [], []
    for r, d in enumerate(decks):
        for k in d.split("|"):
            if k in idx:
                rows.append(r)
                cols.append(idx[k])
    from scipy import sparse
    X = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(decks), len(keys)))
    co = (X.T @ X).toarray()
    cnt = np.diag(co).copy()
    n = float(len(decks))
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = np.log(co * n / np.outer(cnt, cnt))
    m = np.where(np.isfinite(pmi) & (pmi > 0), pmi, 0.0)
    np.fill_diagonal(m, 0.0)
    return m


def factorize(m: np.ndarray, dim: int) -> np.ndarray:
    u, s, _ = np.linalg.svd(m, hermitian=True)
    order = np.argsort(-s)[:dim]                   # hermitian SVD returns values by magnitude; keep the largest
    v = u[:, order] * np.sqrt(s[order])
    # fix each axis's sign (SVD signs are arbitrary): largest-magnitude entry positive
    v *= np.sign(v[np.abs(v).argmax(axis=0), np.arange(v.shape[1])])
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms > 0, norms, 1.0)


def _recall(emb_vectors: np.ndarray, keys: list[str], window_sides: pd.DataFrame, pop: pd.Series, seed: int) -> dict:
    """Hide EVAL_MASK cards of the most frequent decks; are they among the EVAL_K cards closest to the
    center of the rest? Card level (forms merged: a card's score is its best form). Baseline: most popular cards."""
    rng = np.random.default_rng(seed)
    idx = {k: i for i, k in enumerate(keys)}
    card_of = np.array([int(k.split(":")[0]) for k in keys])
    freq = window_sides["deck_key"].value_counts()
    decks = [d for d in freq.index if all(k in idx for k in d.split("|"))][:EVAL_DECKS]
    per = []
    for d in decks:
        ks = d.split("|")
        hide = rng.choice(len(ks), EVAL_MASK, replace=False)
        rest = [ks[i] for i in range(len(ks)) if i not in hide]
        truth = {int(ks[i].split(":")[0]) for i in hide}
        rest_ids = {int(k.split(":")[0]) for k in rest}
        c = emb_vectors[[idx[k] for k in rest]].mean(axis=0)
        sims = emb_vectors @ c
        best: dict[int, float] = {}
        for j in np.argsort(-sims):
            cid = int(card_of[j])
            if cid in rest_ids or cid in best:
                continue
            best[cid] = float(sims[j])
            if len(best) == EVAL_K:
                break
        top_b = [cid for cid in pop.index if cid not in rest_ids][:EVAL_K]
        per.append((len(truth & set(best)), len(truth & set(top_b)), len(truth)))
    if not per:
        return {"decks": 0, "recall": float("nan"), "recall_popular": float("nan")}
    arr = np.array(per, float)
    out = {"decks": len(per), "recall": float(arr[:, 0].sum() / arr[:, 2].sum()), "recall_popular": float(arr[:, 1].sum() / arr[:, 2].sum())}
    b = np.random.default_rng(seed + 1).integers(0, len(arr), size=(1000, len(arr)))
    sm, sb, st = arr[:, 0][b].sum(1), arr[:, 1][b].sum(1), arr[:, 2][b].sum(1)
    q = lambda x: [float(np.quantile(x, 0.05)), float(np.quantile(x, 0.95))]  # noqa: E731
    out.update({"recall_ci90": q(sm / st), "recall_popular_ci90": q(sb / st), "difference_ci90": q((sm - sb) / st)})
    return out


def train(ctx, seed: int | None = None) -> CardEmbedding | None:
    """None when there are too few card forms or validation decks to fit and choose a dimension."""
    seed = ctx.cfg["seed"] if seed is None else seed
    train_sides = side_rows(ctx.split.train)
    min_games = int(ctx.cfg["strength"]["min_feature_games"])
    counts = pd.Series([k for d in train_sides["deck_key"] for k in d.split("|")]).value_counts()
    keys = sorted(k for k, n in counts.items() if n >= min_games)
    m = ppmi(train_sides["deck_key"], keys)
    pop = pd.Series([int(k.split(":")[0]) for d in train_sides["deck_key"] for k in d.split("|")]).value_counts()
    valid_sides = side_rows(ctx.split.valid)
    choice, best = [], None
    for dim in DIMS:
        if dim >= len(keys):
            continue
        r = _recall(factorize(m, dim), keys, valid_sides, pop, seed)
        if not r["decks"]:
            continue
        choice.append({"dim": dim, "valid_recall": r["recall"], "valid_recall_popular": r["recall_popular"]})
        if best is None or r["recall"] > best[1] + 1e-12:
            best = (dim, r["recall"])
    if best is None:
        return None
    for c in choice:
        c["selected"] = c["dim"] == best[0]
    # rounded to 7 decimals: the exact numbers the website receives, so both compute identical distances
    vectors = np.round(factorize(m, best[0]), 7)
    # a card the kept dimensions don't describe gets an all-zero vector (no direction): leave it off the map
    has = np.linalg.norm(vectors, axis=1) > 0.5
    keys, vectors = [k for k, h in zip(keys, has) if h], vectors[has]
    emb = CardEmbedding(best[0], keys, vectors, choice=choice,
                        evaluation=_recall(vectors, keys, side_rows(ctx.split.test), pop, seed))
    centred = vectors - vectors.mean(axis=0)
    _, s, vt = np.linalg.svd(centred, full_matrices=False)
    emb.pca3 = centred @ vt[:3].T
    emb.pca_explained = [float(x) for x in (s[:3] ** 2) / (s ** 2).sum()]
    emb.style = card_styles(ctx, train_sides, keys)
    return emb


def card_styles(ctx, train_sides: pd.DataFrame, keys: list[str], top_decks: int = 3000) -> dict[str, str]:
    """For the picture only: the style (archetype) most often predicted for the most-played training
    decks that hold each card form."""
    if not ctx.archetype.fitted:
        return {}
    freq = train_sides["deck_key"].value_counts().head(top_decks)
    tally: dict[str, dict[str, int]] = {}
    for d, n in freq.items():
        label = ctx.archetype.predict(parse_deck_key(d)).label
        for k in d.split("|"):
            tally.setdefault(k, {})
            tally[k][label] = tally[k].get(label, 0) + int(n)
    return {k: max(t, key=t.get) for k, t in tally.items() if k in set(keys)}


def embedding_swaps(ctx, searcher, entries: list[DeckCard], locked: list[DeckCard] | None = None) -> list[dict]:
    """Swaps that stay close to the deck (full-dimensional distance) and raise the estimated win rate."""
    emb: CardEmbedding = ctx.embedding
    locked_ids = {e.card_id for e in (locked or [])}
    base = searcher.evaluate(entries)
    out = []
    for old in entries:
        if old.card_id in locked_ids:
            continue
        rest = [e for e in entries if e != old]
        c = emb.center(rest)
        if c is None:
            continue
        ids = {e.card_id for e in rest}
        near = []
        for cand in searcher.candidates:
            if cand.card_id in ids or cand.card_id == old.card_id:
                continue
            v = emb.vec(cand)
            if v is None:
                continue
            new = rest + [cand]
            if not check_deck(new, ctx.cards, ctx.rules).legal:
                continue
            near.append((emb.distance(v, c), _form_key(cand), cand, new))
        near.sort(key=lambda t: (t[0], t[1]))
        for dist, _, cand, new in near[:NEAR]:
            after = searcher.evaluate(new)
            dw = after.win_prob - base.win_prob
            if dw > 0:
                out.append({"replace_entry": old, "with_entry": cand, "distance": dist, "delta_win_prob": dw,
                            "new_deck_key": after.key})
    out.sort(key=lambda s: (-s["delta_win_prob"], s["distance"], s["new_deck_key"]))
    return out[:TOP_SWAPS]
