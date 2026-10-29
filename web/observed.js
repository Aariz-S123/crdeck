/* Observed decks: real decks from the mode's exported candidate pool (decks played at least
 * pool_min_battles times in the training and validation battles, legal and unlocked here; large modes keep
 * only the most played), that contain every picked card form. They are ranked by the deck builder's own
 * objective and thinned with its diversity rule, so the only difference from the generated decks is where
 * the candidates come from. Python twin: crdeck.counters.observed_decks.
 *
 * Works in the browser (global `CRObserved`, after engine.js) and in Node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./engine.js"));
  else root.CRObserved = factory(root.CRDeck);
})(typeof self !== "undefined" ? self : this, function (CRDeck) {
  "use strict";
  const tie = (x) => Math.floor(x * 1e10 + 0.5); // crdeck.embedding.tie
  const idsOf = (key) => key.split("|").filter(Boolean).map((k) => Number(k.split(":")[0]));

  // rows: [{key, objective}] with key a sorted deck key ("id:form|..."). seedKeys: card-form keys that every
  // result must contain. Highest objective first (fixed precision, then deck key); each result differs from
  // every earlier one by at least minDiff cards (card ids), as in Engine.complete.
  function select(rows, seedKeys, nResults, minDiff) {
    const matching = rows.filter((r) => { const ks = new Set(r.key.split("|")); return seedKeys.every((k) => ks.has(k)); });
    const ranked = matching.slice().sort((a, b) => tie(b.objective) - tie(a.objective) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
    const chosen = [];
    for (const r of ranked) {
      const ids = new Set(idsOf(r.key));
      if (chosen.every((c) => { const o = new Set(idsOf(c.key)); let diff = 0; ids.forEach((x) => { if (!o.has(x)) diff++; }); return diff >= minDiff; })) chosen.push(r);
      if (chosen.length === nResults) break;
    }
    return { matching: matching.length, chosen };
  }

  // The observed options for these picks in this mode, with an explicit state:
  //   no_pool            the export has no real-deck pool for this mode
  //   hero_unobservable  a Hero pick, but Hero and base can't be told apart in this mode's battle data
  //   no_match           no pool deck contains every pick
  //   few                fewer diverse decks than asked for (never padded)
  //   ok
  function observedDecks(E, seeds) {
    const sc = E.cfg.search, n = Number(sc.n_results), minDiff = Number(sc.min_diff_cards);
    const pool = E.counterPool();
    const out = { state: "ok", decks: [], poolSize: pool.length, matching: 0, minBattles: E.m.matchup ? E.m.matchup.pool_min_battles : null, wanted: n };
    if (!pool.length) { out.state = "no_pool"; return out; }
    if (!E.m.hero_observable && seeds.some((s) => s.form === "hero")) { out.state = "hero_unobservable"; return out; }
    const seedKeys = seeds.map(CRDeck.keyOf);
    if (!E._obsRows) {
      // every pool deck is re-checked here: legal under this mode's rules and every card form unlocked
      E._obsRows = pool.filter((p) => E.checkDeck(p.entries).legal && p.entries.every((e) => E.isAvailable(e)))
        .map((p) => ({ key: p.key, played: p.played, entries: p.entries, objective: null }));
    }
    const cand = E._obsRows.filter((r) => { const ks = new Set(r.key.split("|")); return seedKeys.every((k) => ks.has(k)); });
    for (const r of cand) if (r.objective === null) { r.ev = E.evaluate(r.entries); r.objective = r.ev.objective; }
    const res = select(cand, seedKeys, n, minDiff);
    out.matching = res.matching;
    out.decks = res.chosen.map((r) => ({ key: r.key, entries: CRDeck.sortedEntries(r.entries), played: r.played, objective: r.objective, win_prob: r.ev.win_prob }));
    out.state = !out.decks.length ? "no_match" : out.decks.length < n ? "few" : "ok";
    return out;
  }

  return { select, observedDecks, tie };
});
