/* The counter deck builder on Find counters: "Cards I keep facing" (docs/fable-brief/BLUEPRINT.md 8.4.1).
 * Up to 16 enemy card forms in, real decks out: the mode's pool decks that are legal and unlocked, pass the deck
 * norms, and have the chosen style, ranked against the picked cards. No generated fallback.
 * The core (shares, fieldFit, rank, elixirBounds, useExact) is the twin of crdeck.counters.builder_*; the shared
 * cases are tests/fixtures/counter_builder.json. Needs engine.js. Exposes the global CRCounterBuild. */
(function (root) {
  "use strict";
  const MAX_PICKS = 16, MIN_STYLE_DECKS = 5, EXACT_MIN_DECKS = 5, Z90 = 1.6448536269514722;
  const STYLES = ["Beatdown", "Cycle", "Bridge Spam", "Bait", "Siege", "Graveyard", "Control"];
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));
  const tie = (x) => Math.floor(x * 1e10 + 0.5);
  const idsOf = (key) => new Set(key.split("|").filter(Boolean).map((k) => Number(k.split(":")[0])));

  // ------------------------------------------------------------ the core, shared with Python
  const shares = (picks, deckSize = 8) => (picks.length ? Math.min(1, deckSize / picks.length) : 0);
  // z(A | s) = Σ_{i∈A} w_i − Σ_{j∈P} s·w_j + Σ_{i∈A} Σ_{j∈P} s·K(i, j), summed in key order like Python
  function fieldFit(deck, picks, w, k, deckSize = 8) {
    const s = shares(picks, deckSize), A = [...new Set(deck)].sort(), P = [...new Set(picks)].sort();
    let z = 0;
    for (const i of A) z += w(i);
    for (const j of P) z -= s * w(j);
    for (const i of A) for (const j of P) z += s * k(i, j);
    return { z, fit: sigmoid(z) };
  }
  const useExact = (picks, decksHoldingAll) => picks.length > 0 && picks.length <= 8 && decksHoldingAll >= EXACT_MIN_DECKS;
  function rank(rows, synergyWeight, coWeight, n, minDiff) {
    const scored = rows.map((r) => Object.assign({}, r, { score: r.fit + synergyWeight * r.mean_synergy + coWeight * r.mean_log_lift }));
    scored.sort((a, b) => tie(b.score) - tie(a.score) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
    const out = [];
    for (const r of scored) {
      const ids = idsOf(r.key);
      if (out.every((c) => [...ids].filter((x) => !c._ids.has(x)).length >= minDiff)) out.push(Object.assign(r, { _ids: ids }));
      if (out.length === n) break;
    }
    return out.map(({ _ids, ...r }) => r);
  }
  // weighted 5th and 95th percentiles: the smallest value whose cumulative weight share reaches each
  function elixirBounds(decks, lo = 0.05, hi = 0.95) {
    const pts = decks.filter(([, n]) => n > 0).map(([e, n]) => [Number(e), Number(n)]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const total = pts.reduce((t, [, n]) => t + n, 0);
    if (!pts.length || total <= 0) return null;
    const q = (share) => { let acc = 0; for (const [e, n] of pts) { acc += n; if (acc / total >= share - 1e-12) return e; } return pts[pts.length - 1][0]; };
    return [q(lo), q(hi)];
  }

  // ------------------------------------------------------------ the page's side, on a live Engine
  const avgElixir = (E, entries) => {
    const v = entries.map((e) => E.card(e.id)).filter((c) => c && c.elixir !== null && !c.elixir_variable).map((c) => c.elixir);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  // Pool decks that can be suggested here, with their predicted style; worked out once per mode.
  function candidates(E) {
    if (E._cbCands) return E._cbCands;
    const pool = E.counterPool(), rule = E.suggestionRule([]);
    const ok = pool.filter((p) => E.checkDeck(p.entries).legal && p.entries.every((e) => E.isAvailable(e)) && rule.full(p.entries));
    const bounds = elixirBounds(ok.map((p) => [avgElixir(E, p.entries), p.played]).filter(([e]) => e !== null));
    const rows = ok.map((p) => ({ p, elixir: avgElixir(E, p.entries), style: E.predictArchetype(p.entries).label }))
      .filter((r) => !bounds || (r.elixir !== null && r.elixir >= bounds[0] - 1e-9 && r.elixir <= bounds[1] + 1e-9));
    const counts = Object.fromEntries(STYLES.map((s) => [s, rows.filter((r) => r.style === s).length]));
    E._cbCands = { rows, bounds, counts, pool: pool.length, passing: ok.length };
    return E._cbCands;
  }
  // What each deck card does best against among the picks, and which picks the deck is weakest against.
  function explain(E, deckKeys, picks) {
    const mu = E.m.matchup, games = new Map(mu.pairs.map(([i, j, , , n]) => [`${i}|${j}`, n]));
    const pairGames = (i, j) => games.get(i < j ? `${i}|${j}` : `${j}|${i}`) || 0;
    const per = deckKeys.map((i) => {
      const best = picks.map((j) => ({ j, k: E.muK(i, j), se: E.muKse(i, j) })).filter((t) => t.k > 0).sort((a, b) => b.k - a.k || (a.j < b.j ? -1 : 1)).slice(0, 2)
        .map((t) => ({ card: t.j, weight: t.k, ci90: t.se === null ? null : [t.k - Z90 * t.se, t.k + Z90 * t.se], games: pairGames(i, t.j) }));
      return { card: i, best };
    });
    const weak = picks.map((j) => ({ card: j, total: deckKeys.reduce((t, i) => t + E.muK(i, j), 0) })).sort((a, b) => a.total - b.total || (a.card < b.card ? -1 : 1)).slice(0, 2);
    const noEvidence = picks.filter((j) => deckKeys.every((i) => E.muK(i, j) === 0));
    return { per, weak, noEvidence };
  }
  // The whole builder for one choice of picks (card-form keys) and style ("Any" or one of STYLES).
  function build(E, picks, style) {
    const mu = E.m.matchup;
    if (!mu) return { state: "no_model", decks: [] };
    const c = candidates(E);
    if (!picks.length) return { state: "no_picks", decks: [], counts: c.counts, bounds: c.bounds };
    const want = style && style !== "Any" ? style : null;
    if (want && c.counts[want] < MIN_STYLE_DECKS) return { state: "style_too_few", decks: [], counts: c.counts, bounds: c.bounds, style: want };
    const pool = c.rows.filter((r) => !want || r.style === want);
    const opps = picks.length <= 8 ? E.opponentsFor({ cards: picks }) : [];
    const exact = useExact(picks, opps.length);
    let fitOf;
    if (exact) { const sc = E._counterScorer(opps); fitOf = (r) => sc.win(sc.total(r.p.entries)); }
    else { const w = (x) => E.muW(x), k = (i, j) => E.muK(i, j); fitOf = (r) => fieldFit(r.p.entries.map(CRDeck.keyOf), picks, w, k).fit; }
    const rows = pool.map((r) => { const ev = E._poolEval(r.p); return { key: r.p.key, fit: fitOf(r), mean_synergy: ev.mean_synergy, mean_log_lift: ev.mean_log_lift, _r: r }; });
    const top = rank(rows, E.weight, E.coWeight, Number(mu.n_results), Number(E.cfg.search.min_diff_cards));
    const decks = top.map((t) => {
      const r = rows.find((x) => x.key === t.key)._r, keys = r.p.entries.map(CRDeck.keyOf);
      if (!E.checkDeck(r.p.entries).legal) throw new Error("counter builder deck is not legal");
      return { key: t.key, entries: r.p.entries, played: r.p.played, style: r.style, elixir: r.elixir, fit: t.fit, score: t.score, why: explain(E, keys, picks) };
    });
    return { state: decks.length ? "ok" : "none", decks, path: exact ? "exact" : "field", opponents: opps.length, share: shares(picks), counts: c.counts, bounds: c.bounds,
             candidates: pool.length, passing: c.passing, poolSize: c.pool, style: want };
  }

  const api = { MAX_PICKS, MIN_STYLE_DECKS, EXACT_MIN_DECKS, STYLES, shares, fieldFit, useExact, rank, elixirBounds, candidates, explain, build };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.CRCounterBuild = api;
})(typeof self !== "undefined" ? self : this);
