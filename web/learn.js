/* Worked examples for the "How it works" and "Card usage trends" pages, computed from the same exports
 * and the same engine code the rest of the site uses, so the teaching numbers can't drift from the real ones.
 *   softmaxTable     the deck-style classifier for one deck: every class's raw score, exponential weight
 *                    and probability (identical arithmetic to Engine.predictArchetype)
 *   sigmoidExample   one deck against one sampled opponent deck, then the average over all of them
 *                    (identical to Engine.score's point estimate)
 *   forecastSummary  the next-period usage forecast's state, backtest errors and interval coverage
 * Works in the browser (global `CRLearn`, after engine.js) and in Node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./engine.js"));
  else root.CRLearn = factory(root.CRDeck);
})(typeof self !== "undefined" ? self : this, function (CRDeck) {
  "use strict";
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));

  // z_s = w_s · x + b_s ; p_s = exp(z_s − max z) / Σ_t exp(z_t − max z), with x from Engine.archetypeFeatures
  function softmaxTable(E, entries) {
    const ar = E.m.archetype;
    if (!ar.fitted) return null;
    const x = E.archetypeFeatures(entries);
    const z = ar.coef.map((row, k) => row.reduce((s, w, j) => s + w * x[j], ar.intercept[k]));
    const mx = Math.max(...z), ex = z.map((t) => Math.exp(t - mx)), tot = ex.reduce((a, b) => a + b, 0);
    const rows = ar.classes.map((c, k) => ({ style: c, z: z[k], weight: ex[k], p: ex[k] / tot }));
    let top = rows[0]; for (const r of rows) if (r.p > top.p) top = r;
    const nc = ar.card_ids.length, nr = ar.roles.length;
    const names = ar.card_ids.map((id) => E.name(id)).concat(ar.roles.map((r) => `count of role ${r}`), ["average elixir", "number of win conditions", "number of spells"]);
    const active = [];
    for (let j = 0; j < x.length; j++) if (x[j]) active.push({ feature: names[j], value: x[j] });
    return { rows, top, threshold: ar.threshold, label: top.p >= ar.threshold ? top.style : CRDeck.UNCERTAIN,
      sum: rows.reduce((a, r) => a + r.p, 0), features: { total: x.length, cards: nc, roles: nr, summary: 3 }, active };
  }

  // one opponent deck from the scorer's sample (its card forms decoded from the opponent's feature rows)
  function opponentCards(E, i) {
    const keys = E.m.strength.keys, out = [];
    for (const j of E.oppRows[i]) if (j < E.nCard) out.push(CRDeck.parseKey(keys[j]));
    return out;
  }
  // P(A beats o) = σ(u_A − u_o) at equal rating; the reported estimate is the mean over every sampled o
  function sigmoidExample(E, entries, i = 0) {
    const u = E.utility(entries), uo = E.oppU[i], z = u - uo;
    const all = Array.from(E.oppU, (o) => sigmoid(u - o));
    return { u, opponent: { index: i, cards: opponentCards(E, i), u: uo }, z, p: sigmoid(z),
      n: all.length, mean: E.winProbFromU(u), min: Math.min(...all), max: Math.max(...all) };
  }

  // Coverage over all backtests: Σ coverage_90 × card_forms_scored / Σ card_forms_scored (null if nothing was scored)
  function forecastSummary(M) {
    if (!M) return null;
    const bt = M.backtest || [], st = M.status || {};
    const scored = bt.reduce((a, b) => a + (b.card_forms_scored || 0), 0);
    const coverage = scored ? bt.reduce((a, b) => a + (b.coverage_90 || 0) * (b.card_forms_scored || 0), 0) / scored : null;
    const mean = (k) => (bt.length ? bt.reduce((a, b) => a + b[k], 0) / bt.length : null);
    const periods = M.periods || [], last = periods.length ? periods[periods.length - 1] : null;
    const fc = M.forecast || [];
    return {
      state: st.state, reason: st.reason, settings: M.settings || {}, periods, last,
      backtests: bt.length, mae_mc: mean("mae_points_monte_carlo"), mae_nc: mean("mae_points_no_change"),
      better_periods: bt.filter((b) => b.mae_points_monte_carlo < b.mae_points_no_change).length,
      coverage, coverage_range: bt.length ? [Math.min(...bt.map((b) => b.coverage_90)), Math.max(...bt.map((b) => b.coverage_90))] : null,
      nominal: 0.9, forecast_count: fc.length,
      // the gate passed but no card form had enough games in the latest period to forecast
      shown_but_empty: st.state === "shown" && !fc.length,
    };
  }

  return { softmaxTable, sigmoidExample, opponentCards, forecastSummary, sigmoid };
});
