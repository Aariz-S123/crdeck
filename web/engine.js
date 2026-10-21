/* crdeck web engine: a port of crdeck.rules, strength scoring, synergy, search, warnings,
 * archetype prediction and explanations. It runs on web/model.json, which
 * scripts/export_web.py writes from the trained Python models.
 *
 * Python stays the source of truth. scripts/check_web_engine.mjs compares this file's
 * legality verdicts, slot assignments, searches, scores and explanations against
 * web/golden.json (Python's own answers) and fails on any difference.
 *
 * Works in the browser (global `CRDeck`) and in Node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CRDeck = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FORMS = ["base", "evo", "hero"];
  const KIND_ORDER = { evo: 0, hero: 1, champion: 2 };
  const UNCERTAIN = "HYBRID / UNCERTAIN";
  const NO_LABELS = "NO_LABELS";
  const GROUP_TITLES = {
    win_condition: "No way to pressure towers",
    air: "Weak against air (Balloon, Lava Hound, air swarms)",
    spells: "Spell coverage",
    tank_defense: "Weak against big tanks",
    elixir: "Elixir cost",
  };

  class SeedError extends Error {}

  const sigmoid = (x) => 1 / (1 + Math.exp(-x));
  const keyOf = (e) => `${e.id}:${e.form}`;
  const parseKey = (k) => { const [id, form] = k.split(":"); return { id: Number(id), form }; };
  const deckKey = (entries) => entries.map(keyOf).sort().join("|");
  const parseDeckKey = (k) => k.split("|").filter(Boolean).map(parseKey);
  const cmpEntry = (a, b) => (a.id - b.id) || (a.form < b.form ? -1 : a.form > b.form ? 1 : 0);
  const sortedEntries = (entries) => entries.slice().sort(cmpEntry);

  // Python's round(x, n) for display parity (half-to-even on the binary value is close enough here)
  const fmtSigned = (x, d) => (x >= 0 ? "+" : "") + x.toFixed(d);

  function* permutations(n, k) {
    // itertools.permutations(range(n), k) order
    const used = new Array(n).fill(false), cur = [];
    function* rec() {
      if (cur.length === k) { yield cur.slice(); return; }
      for (let i = 0; i < n; i++) {
        if (used[i]) continue;
        used[i] = true; cur.push(i);
        yield* rec();
        cur.pop(); used[i] = false;
      }
    }
    yield* rec();
  }

  function invNormal(p) {
    // Acklam's rational approximation, refined by one Halley step (abs error < 1e-12)
    const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
    const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
    const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    let q, r, x;
    if (p < pl) { q = Math.sqrt(-2 * Math.log(p)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else if (p <= 1 - pl) { q = p - 0.5; r = q * q; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    else { q = Math.sqrt(-2 * Math.log(1 - p)); x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    const e = 0.5 * erfc(-x / Math.SQRT2) - p;
    const u = e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
    return x - u / (1 + x * u / 2);
  }
  function erfc(x) {
    // Numerical Recipes erfc (rel. error < 1.2e-7), adequate for the Halley refinement above
    const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }

  class Engine {
    constructor(model) {
      this.m = model;
      this.cards = new Map(model.cards.map((c) => [c.id, c]));
      this.ids = model.cards.map((c) => c.id).sort((a, b) => a - b);
      this.byName = new Map(model.cards.map((c) => [norm(c.name), c]));
      const st = model.strength;
      this.index = new Map(st.keys.map((k, i) => [k, i]));
      this.nCard = st.n_card_features;
      this.coef = st.coef;
      this.pairs = st.pairs;
      this.nDeck = this.coef.length;
      this.oppU = Float64Array.from(model.scorer.opp_u);
      this.oppRows = model.scorer.opp_rows;
      this.cov = model.strength.cov;
      this.z = model.scorer.interval === 0.9 ? 1.6448536269514722 : invNormal(1 - (1 - model.scorer.interval) / 2);
      const sy = model.synergy;
      this.synPos = new Map(sy.card_ids.map((c, i) => [c, i]));
      this.synPairs = new Map();
      for (const [i, j, games, lift, swr, syn, lo, hi, ok] of sy.pairs) this.synPairs.set(`${i},${j}`, { card_i: i, card_j: j, games, lift, shrunk_wr: swr, synergy: syn, lo, hi, ok });
      const ar = model.archetype;
      this.archIndex = new Map(ar.card_ids.map((c, i) => [c, i]));
      this.cfg = model.config;
      this.weight = Number(this.cfg.search.synergy_weight);
      this.coWeight = Number(this.cfg.search.cooccurrence_weight);
      this.candidates = this._candidates();
    }

    // ------------------------------------------------------------------ cards
    card(id) { return this.cards.get(Number(id)); }
    name(id) { const c = this.card(id); return c ? c.name : `<unknown ${id}>`; }
    describe(e) { const n = this.name(e.id); return e.form === "base" ? n : `${n} (${e.form === "evo" ? "Evolution" : "Hero"})`; }
    allowedForms(c) { const f = ["base"]; if (c.evo) f.push("evo"); if (c.hero) f.push("hero"); return f; }
    // crdeck.availability: what a player in this Trophy Road arena can use (null = no restriction)
    cardUnlocked(id) { const a = this.m.availability; return !a || (a.unlock[String(id)] || 0) <= a.number || String(id) in a.seen_early; }
    isAvailable(e) {
      const a = this.m.availability;
      if (!a) return true;
      if (!this.cardUnlocked(e.id)) return false;
      if (e.form === "evo") return a.slots.includes("evo");
      if (e.form === "hero") return a.slots.includes("hero");
      return true;
    }
    whyNot(e) {
      const a = this.m.availability, name = this.describe(e);
      if (!this.cardUnlocked(e.id)) return `${name} unlocks at ${a.unlock_name[String(e.id)] || "a later arena"} (Arena ${a.unlock[String(e.id)]})`;
      return `${name}: ${e.form === "evo" ? "Evolutions" : "Heroes"} unlock at Arena ${a.slot_unlock[e.form]}`;
    }
    byNameLookup(name) { const c = this.byName.get(norm(name)); if (!c) throw new SeedError(`no card named ${name}`); return c; }

    // ------------------------------------------------------------------ rules (crdeck.rules)
    slotKind(e) {
      if (e.form === "evo") return "evo";
      if (e.form === "hero") return "hero";
      const c = this.card(e.id);
      return c && c.champion ? "champion" : null;
    }
    _check(entries, complete) {
      const r = this.m.rules, reasons = [], details = [];
      const fail = (code, msg) => { if (!reasons.includes(code)) reasons.push(code); details.push(msg); };
      const n = entries.length;
      if (complete && n !== r.deck_size) fail("WRONG_SIZE", `deck has ${n} cards; rule is exactly ${r.deck_size}`);
      if (!complete && n > r.deck_size) fail("TOO_MANY_CARDS", `partial deck has ${n} cards; max ${r.deck_size}`);
      const seen = new Map();
      for (const e of entries) {
        if (seen.has(e.id)) fail("DUPLICATE_CARD", `card ${this.name(e.id)} appears twice (${seen.get(e.id).form} and ${e.form})`);
        seen.set(e.id, e);
        if (!FORMS.includes(e.form)) { fail("INVALID_FORM", `${this.name(e.id)}: form ${e.form} not allowed`); continue; }
        const c = this.card(e.id);
        if (!c) { fail("UNKNOWN_CARD", `card id ${e.id} not in card table`); continue; }
        if (!this.allowedForms(c).includes(e.form)) fail("FORM_NOT_AVAILABLE", `${c.name} has no ${e.form} form`);
      }
      const nChamp = entries.filter((e) => { const c = this.card(e.id); return c && c.champion; }).length;
      if (nChamp > r.max_champions) fail("TOO_MANY_CHAMPIONS", `${nChamp} champions; max_champions is ${r.max_champions}`);
      const kinds = [];
      for (const e of entries) { const k = this.slotKind(e); if (k) kinds.push([keyOf(e), k]); }
      kinds.sort((a, b) => (KIND_ORDER[a[1]] - KIND_ORDER[b[1]]) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
      let slots = null;
      const sl = r.special_slots;
      if (kinds.length <= sl.length) {
        if (!kinds.length) slots = {};
        else for (const perm of permutations(sl.length, kinds.length)) {
          if (kinds.every((kk, i) => sl[perm[i]].accepts.includes(kk[1]))) {
            slots = {}; kinds.forEach((kk, i) => { slots[kk[0]] = sl[perm[i]].name; }); break;
          }
        }
      }
      if (slots === null) {
        const counts = {}; kinds.forEach(([, k]) => { counts[k] = (counts[k] || 0) + 1; });
        fail("NO_SLOT_FOR_SPECIALS", `special cards ${JSON.stringify(counts)} cannot be placed in slots ` + sl.map((s) => `${s.name}(${s.accepts.join("/")})`).join(", "));
        slots = {};
      }
      return { legal: reasons.length === 0, reasons, details, slots };
    }
    checkDeck(entries) { return this._check(entries, true); }
    checkPartial(entries) { return this._check(entries, false); }

    // ------------------------------------------------------------------ strength
    featureKey(e) { return e.form === "hero" && !this.m.hero_observable ? `${e.id}:base` : keyOf(e); }
    known(e) { return this.index.has(this.featureKey(e)); }
    games(e) { return this.m.strength.feature_games[this.featureKey(e)] || 0; }
    utility(entries) {
      let u = 0;
      for (const e of entries) { const j = this.index.get(this.featureKey(e)); u += j === undefined ? 0 : this.coef[j]; }
      if (this.pairs.length) {
        const ids = new Set(entries.map((e) => e.id));
        let ps = 0;
        this.pairs.forEach(([a, b], p) => { if (ids.has(a) && ids.has(b)) ps += this.coef[this.nCard + p]; });
        u += ps;
      }
      return u;
    }
    winProbFromU(u) { const o = this.oppU; let s = 0; for (let i = 0; i < o.length; i++) s += 1 / (1 + Math.exp(-(u - o[i]))); return s / o.length; }
    score(entries) {
      const u = this.utility(entries), o = this.oppU, n = o.length;
      const p = new Float64Array(n);
      let mean = 0;
      for (let i = 0; i < n; i++) { p[i] = sigmoid(u - o[i]); mean += p[i]; }
      mean /= n;
      let v = 0; for (let i = 0; i < n; i++) v += (p[i] - mean) ** 2;
      const sdOpp = Math.sqrt(v / n) / Math.sqrt(n);
      const grad = new Float64Array(this.nDeck);
      let wMean = 0;
      for (let i = 0; i < n; i++) { const w = p[i] * (1 - p[i]); wMean += w; for (const j of this.oppRows[i]) grad[j] -= w / n; }
      wMean /= n;
      for (const j of this.vectorIdx(entries)) grad[j] += wMean;
      let q = 0;
      for (let a = 0; a < this.nDeck; a++) { if (!grad[a]) continue; const row = this.cov[a]; let s = 0; for (let b = 0; b < this.nDeck; b++) if (grad[b]) s += row[b] * grad[b]; q += grad[a] * s; }
      const sdModel = Math.sqrt(Math.max(q, 0)), sd = Math.hypot(sdModel, sdOpp);
      return { win_prob: mean, lo: Math.max(0, mean - this.z * sd), hi: Math.min(1, mean + this.z * sd), n_opponents: n,
               interval: this.m.scorer.interval, sd_model: sdModel, sd_opponents: sdOpp };
    }
    vectorIdx(entries) {
      const idx = new Set();
      for (const e of entries) { const j = this.index.get(this.featureKey(e)); if (j !== undefined) idx.add(j); }
      const ids = new Set(entries.map((e) => e.id));
      this.pairs.forEach(([a, b], p) => { if (ids.has(a) && ids.has(b)) idx.add(this.nCard + p); });
      return idx;
    }

    // ------------------------------------------------------------------ synergy
    pair(a, b) { const i = Math.min(a, b), j = Math.max(a, b); return this.synPairs.get(`${i},${j}`) || null; }
    meanSynergy(ids) {
      const pos = [...new Set(ids)].filter((c) => this.synPos.has(c)).map((c) => this.synPos.get(c));
      if (pos.length < 2) return [0, 0];
      let s = 0, n = 0; const M = this.m.synergy.matrix;
      for (let i = 0; i < pos.length; i++) for (let j = i + 1; j < pos.length; j++) { const v = M[pos[i]][pos[j]]; if (v !== null) { s += v; n++; } }
      return n ? [s / n, n] : [0, 0];
    }
    meanLogLift(ids) {
      const pos = [...new Set(ids)].filter((c) => this.synPos.has(c)).map((c) => this.synPos.get(c));
      if (pos.length < 2) return 0;
      let s = 0, n = 0; const L = this.m.synergy.log_lift;
      for (let i = 0; i < pos.length; i++) for (let j = i + 1; j < pos.length; j++) { s += L[pos[i]][pos[j]]; n++; }
      return s / n;
    }
    deckPairs(ids) {
      const u = [...new Set(ids)].sort((a, b) => a - b), out = [];
      for (let i = 0; i < u.length; i++) for (let j = i + 1; j < u.length; j++) {
        const p = this.pair(u[i], u[j]);
        out.push(p || { card_i: u[i], card_j: u[j], games: 0, lift: null, shrunk_wr: null, synergy: null, lo: null, hi: null, ok: false });
      }
      return out;
    }

    // ------------------------------------------------------------------ search (crdeck.search)
    _candidates() {
      const out = [], minGames = Number(this.cfg.search.min_card_games);
      for (const id of this.ids) for (const form of this.allowedForms(this.card(id))) {
        const e = { id, form };
        if (form === "hero" && !this.m.hero_observable) continue;
        if (!this.isAvailable(e)) continue; // not unlocked in this arena
        if (this.known(e) && this.games(e) >= minGames) out.push(e);
      }
      return out;
    }
    evaluate(entries) {
      const u = this.utility(entries), wp = this.winProbFromU(u), ids = entries.map((e) => e.id);
      const [syn, n] = this.meanSynergy(ids);
      const ll = this.coWeight ? this.meanLogLift(ids) : 0;
      const sorted = sortedEntries(entries);
      return { entries: sorted, key: deckKey(sorted), objective: wp + this.weight * syn + this.coWeight * ll, win_prob: wp, mean_synergy: syn, n_scored_pairs: n, mean_log_lift: ll };
    }
    objectiveDict(d) {
      return { objective: d.objective, formula: `meta_win_prob + ${this.weight} * mean_pair_synergy + ${this.coWeight} * mean_log_lift`,
               meta_win_prob: d.win_prob, mean_pair_synergy: d.mean_synergy, scored_pairs: d.n_scored_pairs, mean_log_lift: d.mean_log_lift };
    }
    complete(seeds, opts = {}) {
      const sc = this.cfg.search, nResults = opts.n_results || Number(sc.n_results), width = opts.beam_width || Number(sc.beam_width);
      const size = this.m.rules.deck_size;
      const uniq = []; const seenSeed = new Set();
      for (const s of seeds) { const k = keyOf(s); if (!seenSeed.has(k)) { seenSeed.add(k); uniq.push(s); } }
      seeds = uniq;
      if (seeds.length > size) throw new SeedError(`${seeds.length} seed cards; a deck has ${size}`);
      const locked = seeds.filter((s) => !this.isAvailable(s)).map((s) => this.whyNot(s));
      if (locked.length) throw new SeedError(`not unlocked in ${this.m.availability.arena}: ${locked.join("; ")}`);
      const res = this.checkPartial(seeds);
      if (!res.legal) throw new SeedError("seed cards cannot form a legal deck: " + res.details.join("; "));
      const perParent = Math.max(2, Math.floor(width / Number(sc.beam_parents_min || 10)));
      let beam = seeds.length ? [this.evaluate(seeds)] : [{ entries: [], key: "", objective: 0, win_prob: 0, mean_synergy: 0, n_scored_pairs: 0, mean_log_lift: 0 }];
      let nxt = seeds.length === size ? beam.slice() : [];
      for (let step = 0; step < size - seeds.length; step++) {
        const seen = new Set(), children = [];
        beam.forEach((d, pi) => {
          const ids = new Set(d.entries.map((e) => e.id));
          for (const c of this.candidates) {
            if (ids.has(c.id)) continue;
            const ne = d.entries.concat([c]);
            const k = deckKey(ne);
            if (seen.has(k)) continue;
            seen.add(k);
            if (!this.checkPartial(ne).legal) continue;
            children.push([pi, this.evaluate(ne)]);
          }
        });
        if (!children.length) throw new SeedError("no legal completion exists for these seeds with the current candidate cards");
        children.sort((a, b) => (b[1].objective - a[1].objective) || (a[1].key < b[1].key ? -1 : a[1].key > b[1].key ? 1 : 0));
        nxt = children.map((c) => c[1]);
        const taken = new Map(); beam = [];
        for (const [pi, d] of children) {
          if ((taken.get(pi) || 0) < perParent) { beam.push(d); taken.set(pi, (taken.get(pi) || 0) + 1); }
          if (beam.length === width) break;
        }
      }
      let final = nxt.filter((d) => this.checkDeck(d.entries).legal);
      if (sc.require_win_condition) final = final.filter((d) => this.hasWinCondition(d.entries));
      if (!final.length) throw new SeedError("search produced no legal deck satisfying the hard filters");
      const chosen = [], minDiff = Number(sc.min_diff_cards);
      for (const d of final) {
        const ids = new Set(d.entries.map((e) => e.id));
        if (chosen.every((c) => { const o = new Set(c.entries.map((e) => e.id)); let diff = 0; ids.forEach((x) => { if (!o.has(x)) diff++; }); return diff >= minDiff; })) chosen.push(d);
        if (chosen.length === nResults) break;
      }
      for (const d of chosen) if (!this.checkDeck(d.entries).legal) throw new Error("search produced an illegal deck");
      return chosen;
    }
    swaps(entries, opts = {}) {
      const top = opts.top || Number(this.cfg.search.top_swaps);
      const locked = new Set((opts.locked || []).map((e) => e.id));
      entries = sortedEntries(entries);
      const base = this.evaluate(entries), out = [];
      entries.forEach((old, i) => {
        if (locked.has(old.id)) return;
        const rest = entries.slice(0, i).concat(entries.slice(i + 1));
        const restIds = new Set(rest.map((e) => e.id)), options = [];
        for (const c of this.candidates) {
          if (restIds.has(c.id) || (c.id === old.id && c.form === old.form)) continue;
          const ne = rest.concat([c]);
          if (!this.checkDeck(ne).legal) continue;
          const s = this.evaluate(ne);
          options.push([s.objective - base.objective, c, s, ne]);
        }
        options.sort((a, b) => (b[0] - a[0]) || cmpEntry(a[1], b[1]));
        for (const [delta, c, s, ne] of options.slice(0, top)) {
          out.push({ replace: this.describe(old), with: this.describe(c), replace_entry: old, with_entry: c, new_deck_key: deckKey(ne),
                     delta_objective: delta, delta_win_prob: s.win_prob - base.win_prob, new_objective: s.objective, reason: this._pairReason(old, c, rest) });
        }
      });
      return out;
    }
    // Why a swap ranks where it does: its exact objective change, split into the
    // regression's card weights, its pair weights, and the two ranking terms.
    // The parts sum to evaluate(new).objective - evaluate(old).objective.
    coefInfo(e) {
      const j = this.index.get(this.featureKey(e));
      return { name: this.describe(e), key: keyOf(e), known: j !== undefined, weight: j === undefined ? 0 : this.coef[j],
               se: j === undefined ? null : Math.sqrt(Math.max(this.cov[j][j], 0)), games: this.games(e) };
    }
    explainSwap(entries, oldE, newE) {
      entries = sortedEntries(entries);
      const rest = entries.filter((e) => !(e.id === oldE.id && e.form === oldE.form));
      const after = sortedEntries(rest.concat([newE]));
      const before = this.evaluate(entries), aft = this.evaluate(after);
      const uOld = this.utility(entries), uNew = this.utility(after);
      const cOld = this.coefInfo(oldE), cNew = this.coefInfo(newE);
      const dCard = cNew.weight - cOld.weight, dPair = uNew - uOld - dCard;
      const wpOld = this.winProbFromU(uOld), wpMid = this.winProbFromU(uOld + dCard), wpNew = this.winProbFromU(uNew);
      const idsB = new Set(entries.map((e) => e.id)), idsA = new Set(after.map((e) => e.id));
      const pairChanges = [];
      this.pairs.forEach(([a, b], p) => {
        const inB = idsB.has(a) && idsB.has(b), inA = idsA.has(a) && idsA.has(b);
        if (inB !== inA) pairChanges.push({ pair: `${this.name(a)} + ${this.name(b)}`, weight: this.coef[this.nCard + p], gained: inA });
      });
      const parts = [
        { key: "card", label: "Card weight", value: wpMid - wpOld, detail: `coefficient ${fmtSigned(cNew.weight, 4)} vs ${fmtSigned(cOld.weight, 4)} log-odds` },
        { key: "pairs", label: "Pair weights", value: wpNew - wpMid, detail: pairChanges.length ? `${pairChanges.length} tracked pair(s) change` : "no tracked pair changes" },
        { key: "synergy", label: `Synergy ×${this.weight}`, value: this.weight * (aft.mean_synergy - before.mean_synergy), detail: `mean pair synergy ${fmtSigned(before.mean_synergy, 4)} → ${fmtSigned(aft.mean_synergy, 4)}` },
        { key: "coplay", label: `Co-play ×${this.coWeight}`, value: this.coWeight * (aft.mean_log_lift - before.mean_log_lift), detail: `mean log-lift ${before.mean_log_lift.toFixed(3)} → ${aft.mean_log_lift.toFixed(3)}` },
      ];
      return { old: cOld, new: cNew, parts, total: aft.objective - before.objective, d_logodds: uNew - uOld,
               d_card_logodds: dCard, d_pair_logodds: dPair, win_before: wpOld, win_after: wpNew, pair_changes: pairChanges };
    }
    // Held-out check of the regression: decks played in the test window, grouped into
    // bins of equal battle count by model strength (sum of weights), with their real win share.
    calibration(nBins = 8) {
      const rows = [];
      for (const [k, [n, w]] of Object.entries(this.m.test_deck_records)) rows.push({ u: this.utility(parseDeckKey(k)), n, w });
      rows.sort((a, b) => a.u - b.u);
      const total = rows.reduce((t, r) => t + r.n, 0), per = total / nBins, z = 1.6448536269514722;
      const bins = [];
      let cur = { n: 0, w: 0, su: 0, decks: 0, uLo: Infinity, uHi: -Infinity }, seen = 0;
      const close = () => {
        if (!cur.n) return;
        const p = cur.w / cur.n, n = cur.n, den = 1 + z * z / n, c = (p + z * z / (2 * n)) / den;
        const h = (z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den;
        bins.push({ u: cur.su / cur.n, uLo: cur.uLo, uHi: cur.uHi, battles: n, wins: cur.w, decks: cur.decks, win: p, lo: c - h, hi: c + h,
                    model: this.winProbFromU(cur.su / cur.n) });
        cur = { n: 0, w: 0, su: 0, decks: 0, uLo: Infinity, uHi: -Infinity };
      };
      for (const r of rows) {
        cur.n += r.n; cur.w += r.w; cur.su += r.u * r.n; cur.decks++; cur.uLo = Math.min(cur.uLo, r.u); cur.uHi = Math.max(cur.uHi, r.u);
        if (bins.length < nBins - 1 && seen + cur.n >= per * (bins.length + 1)) { seen += cur.n; close(); }
      }
      close();
      return { bins, total, decks: rows.length };
    }
    _pairReason(old, nw, rest) {
      const gained = [], lost = [];
      for (const e of rest) for (const [card, bucket] of [[nw, gained], [old, lost]]) {
        const p = this.pair(card.id, e.id);
        if (p && p.ok) bucket.push([p.synergy, `${this.name(card.id)}+${this.name(e.id)}`, p.games]);
      }
      const best = (arr) => arr.reduce((m, x) => (!m || x[0] > m[0] || (x[0] === m[0] && (x[1] > m[1] || (x[1] === m[1] && x[2] > m[2])))) ? x : m, null);
      const parts = [];
      if (gained.length) { const g = best(gained); parts.push(`gains ${g[1]} (${fmtSigned(g[0], 3)}, ${g[2]} games)`); }
      if (lost.length) { const w = best(lost); parts.push(`loses ${w[1]} (${fmtSigned(w[0], 3)}, ${w[2]} games)`); }
      return parts.length ? parts.join("; ") : "no pair with enough games; change comes from card strength";
    }

    // ------------------------------------------------------------------ warnings (crdeck.explain)
    avgElixir(entries) {
      const v = entries.map((e) => this.card(e.id)).filter((c) => c && c.elixir !== null && !c.elixir_variable).map((c) => c.elixir);
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    }
    hasWinCondition(entries) { return entries.some((e) => { const c = this.card(e.id); return c && c.wincon; }); }
    structuralWarnings(entries) {
      const cfg = this.cfg.warnings;
      const cs = entries.map((e) => this.card(e.id)).filter(Boolean);
      const roles = cs.flatMap((c) => c.roles);
      const count = (r) => roles.filter((x) => x === r).length;
      const w = [];
      const add = (code, group, message, rule, observed) => w.push({ code, group, message, rule, observed });
      if (cs.filter((c) => c.wincon).length === 0) add("NO_WIN_CONDITION", "win_condition", "no win condition", ">= 1 win condition", 0);
      const nAir = count("air_defense");
      if (nAir === 0) add("NO_AIR_DEFENSE", "air", "no air defense", ">= 1 air_defense card", 0);
      else if (nAir === 1) add("THIN_AIR_DEFENSE", "air", "only one air defense card", ">= 2 air_defense cards", 1);
      if (cs.filter((c) => c.type === "spell").length === 0) add("NO_SPELL", "spells", "no spell", ">= 1 spell", 0);
      if (count("small_spell") === 0) add("NO_SMALL_SPELL", "spells", "no small spell for swarms", ">= 1 small_spell", 0);
      if (count("building") === 0 && count("tank_killer") === 0) add("NO_TANK_ANSWER", "tank_defense", "no building or tank killer against tanks", ">= 1 building or tank_killer", 0);
      const ae = this.avgElixir(entries);
      if (ae !== null && ae > cfg.elixir_max) add("ELIXIR_HIGH", "elixir", `avg elixir ${ae.toFixed(1)}, rule <= ${cfg.elixir_max}`, `<= ${cfg.elixir_max}`, Math.round(ae * 100) / 100);
      if (ae !== null && ae < cfg.elixir_min) add("ELIXIR_LOW", "elixir", `avg elixir ${ae.toFixed(1)}, rule >= ${cfg.elixir_min}`, `>= ${cfg.elixir_min}`, Math.round(ae * 100) / 100);
      for (const role of cfg.narrow_roles) { const n = count(role); if (n >= 2) add(`DUPLICATE_ROLE_${role.toUpperCase()}`, `role:${role}`, `${n} cards with role ${role}`, `<= 1 ${role}`, n); }
      return w;
    }
    groupWarnings(ws) {
      const groups = new Map();
      for (const x of ws) { if (!groups.has(x.group)) groups.set(x.group, []); groups.get(x.group).push(x); }
      return [...groups.entries()].map(([g, items]) => ({
        group: g, root_cause: GROUP_TITLES[g] || (g.startsWith("role:") ? `Redundant role: ${g.split(":")[1]}` : g), warnings: items,
      }));
    }

    // ------------------------------------------------------------------ archetype (crdeck.archetype)
    archetypeFeatures(entries) {
      const ar = this.m.archetype, nc = ar.card_ids.length, nr = ar.roles.length;
      const v = new Float64Array(nc + nr + 3), el = [];
      for (const e of entries) {
        const j = this.archIndex.get(e.id); if (j !== undefined) v[j] = 1;
        const c = this.card(e.id); if (!c) continue;
        for (const r of c.roles) v[nc + ar.roles.indexOf(r)] += 1;
        if (c.elixir !== null && !c.elixir_variable) el.push(c.elixir);
        v[v.length - 2] += c.wincon ? 1 : 0;
        v[v.length - 1] += c.type === "spell" ? 1 : 0;
      }
      v[v.length - 3] = el.length ? el.reduce((a, b) => a + b, 0) / el.length : 0;
      return v;
    }
    predictArchetype(entries) {
      const ar = this.m.archetype;
      if (!ar.fitted) return { label: NO_LABELS, probability: null, probabilities: {}, status: NO_LABELS };
      const x = this.archetypeFeatures(entries);
      const z = ar.coef.map((row, k) => row.reduce((s, w, j) => s + w * x[j], ar.intercept[k]));
      const mx = Math.max(...z), ex = z.map((t) => Math.exp(t - mx)), tot = ex.reduce((a, b) => a + b, 0);
      const probs = {}; ar.classes.forEach((c, k) => { probs[c] = ex[k] / tot; });
      let top = ar.classes[0]; for (const c of ar.classes) if (probs[c] > probs[top]) top = c;
      return { label: probs[top] >= ar.threshold ? top : UNCERTAIN, probability: probs[top], probabilities: probs, status: "OK" };
    }

    // ------------------------------------------------------------------ explanation
    explain(entries, objective) {
      entries = sortedEntries(entries);
      const legal = this.checkDeck(entries);
      const specialSlots = {}; for (const [k, s] of Object.entries(legal.slots)) specialSlots[this.describe(parseKey(k))] = s;
      const pred = this.predictArchetype(entries);
      const ds = this.score(entries);
      const key = deckKey(entries);
      const obsKey = this.m.hero_observable ? key : deckKey(entries.map((e) => (e.form === "hero" ? { id: e.id, form: "base" } : e)));
      const exact = this.m.test_deck_records[obsKey] || [0, 0];
      const pairs = this.deckPairs(entries.map((e) => e.id));
      const scored = pairs.filter((p) => p.ok).sort((a, b) => b.synergy - a.synergy);
      const row = (p) => ({ pair: `${this.name(p.card_i)} + ${this.name(p.card_j)}`, synergy: p.synergy, interval: [p.lo, p.hi], lift: p.lift, games: p.games, shrunk_wr: p.shrunk_wr });
      const top = scored.slice(0, 3).map(row);
      const bottom = scored.slice(3).slice(-3).reverse().map(row);
      const nInsuff = pairs.filter((p) => !p.ok).length;
      const dq = [];
      if (nInsuff) dq.push({ state: "INSUFFICIENT_SAMPLE", detail: `${nInsuff} of ${pairs.length} pairs under ${this.m.synergy.min_games} games: no synergy score` });
      const unknown = entries.filter((e) => !this.card(e.id)).map((e) => e.id);
      if (unknown.length) dq.push({ state: "UNKNOWN_CARD", detail: `card ids ${unknown} not in card table` });
      if (!this.m.hero_observable) {
        const fu = entries.filter((e) => this.card(e.id) && (e.form === "hero" || (e.form === "base" && this.card(e.id).hero))).map((e) => this.describe(e));
        if (fu.length) dq.push({ state: "FORM_UNKNOWN", detail: "hero vs base form not distinguishable in battle data: " + fu.join(", ") });
      }
      if (!(this.m.deck_appearances[obsKey] > 0)) dq.push({ state: "UNSEEN_DECK", detail: "this exact deck never appears in the collected battles; the score is a model extrapolation from its cards" });
      const low = entries.filter((e) => !this.known(e)).map((e) => this.describe(e));
      if (low.length) dq.push({ state: "LOW_CARD_DATA", detail: `under ${this.m.strength.min_feature_games} train games, no learned weight: ` + low.join(", ") });
      return {
        deck: entries.map((e) => this.describe(e)), entries, deck_key: key,
        legality: { legal: legal.legal, reasons: legal.reasons, details: legal.details, special_slots: specialSlots, slots: legal.slots },
        archetype: { label: pred.label, probability: pred.probability, status: pred.status, probabilities: pred.probabilities },
        score: { meta_win_prob: ds.win_prob, interval: [ds.lo, ds.hi], sd_model: ds.sd_model, sd_opponents: ds.sd_opponents,
                 opponent_decks: ds.n_opponents, test_battles_exact_deck: exact[0], test_wins_exact_deck: exact[1] },
        synergy_top: top, synergy_bottom: bottom, synergy_insufficient_pairs: nInsuff,
        warnings: this.groupWarnings(this.structuralWarnings(entries)), data_quality: dq,
        objective: objective || null, avg_elixir: this.avgElixir(entries),
      };
    }
  }

  function norm(s) { return String(s).toLowerCase().replace(/[^a-z0-9]/g, ""); }

  return { Engine, SeedError, deckKey, parseDeckKey, keyOf, parseKey, sortedEntries, UNCERTAIN, NO_LABELS };
});
