// Check my deck (web/check.html): a player's own 8 cards, scored against the decks people play in one mode.
// Pure functions over the engine (web/engine.js), no page code, so node tests can call them directly.
//
// Two models are used, and the page says which number comes from which:
//  - the win model (Engine.score, via Engine.explain): the deck's estimated win rate against the sampled field
//    of the chosen mode, with its 90% range. Pages hide it where the model didn't beat a coin flip (UI.estimateGate).
//  - the matchup model (Engine.winVs / muW / muK, crdeck.matchup): win rate against one opponent deck or a set of them,
//    from card strengths w and card-against-card weights K, at equal player rating.
// Most single leagues and arenas have few card pairs with enough battles for a K (Goblin Stadium 0, Hog Mountain 0,
// Champion 0), so there the matchups would only reflect card strength. When the chosen mode has fewer than
// MIN_OWN_PAIRS pairs, the matchups use the mode's pooled model (every league or every arena together), still
// against the opponent decks of the chosen league or arena. The user chose this fallback, labelled, on 2026-11-21.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CRDeckCheck = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const MIN_OWN_PAIRS = 1000;   // card-pair weights a mode needs before its own matchup model is used
  const TOP_OPPONENTS = 200;    // the most-played opponent decks the "beats / loses to" lists choose from
  const SHOW = 5;               // decks in each of those lists
  const MIN_CARD_SHARE = 0.03;  // an opponent card must be in at least 3% of the field to be listed
  const SHOW_CARDS = 6;         // cards in each of the "your deck handles / has trouble with" lists
  const Z90 = 1.6448536269514722;
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));

  // ---------------------------------------------------------------- reading a pasted deck
  // Accepts a card list ("Hog Rider, Evo Musketeer, Ice Spirit ...", one per line or comma-separated) or a game
  // deck link (its 8 card ids). "Evo"/"Evolution" and "Hero" before or after a name pick that form. Card ids from a
  // game link come in as base forms: the link's slot details aren't read, and the page says so.
  function parseDeckText(E, text) {
    const s = String(text || "").trim();
    if (!s) return { entries: [], unknown: [], fromIds: false };
    const ids = s.match(/\b2[678]\d{6}\b/g);
    if (ids && ids.length >= 2) {
      const entries = [], unknown = [], seen = new Set();
      for (const t of ids) { const id = Number(t); if (seen.has(id)) continue; seen.add(id); if (E.card(id)) entries.push({ id, form: "base" }); else unknown.push(t); }
      return { entries, unknown, fromIds: true };
    }
    const entries = [], unknown = [], seen = new Set();
    for (const raw of s.split(/[,;\n\r\t]+/)) {
      let name = raw.trim(); if (!name) continue;
      let form = "base";
      const evo = /^(evo(lution|lved)?)\b\s*|\s*\(?\b(evo(lution)?)\)?$/i, hero = /^hero\b\s*|\s*\(?\bhero\)?$/i;
      if (evo.test(name)) { form = "evo"; name = name.replace(evo, "").trim(); }
      else if (hero.test(name)) { form = "hero"; name = name.replace(hero, "").trim(); }
      let c = null;
      try { c = E.byNameLookup(name); } catch { c = null; }
      if (!c) { unknown.push(raw.trim()); continue; }
      const id = c.id !== undefined ? c.id : c.card_id;
      if (seen.has(id)) continue; seen.add(id);
      const ok = E.allowedForms(E.card(id)).includes(form);
      entries.push({ id, form: ok ? form : "base" });
    }
    return { entries, unknown, fromIds: false };
  }

  // ---------------------------------------------------------------- which matchup model
  const pairCount = (m) => (m && m.matchup ? m.matchup.pairs.length : 0);
  function needsPooled(entry, m) { return Boolean(entry && entry.group) && pairCount(m) < MIN_OWN_PAIRS; }
  // the pooled mode for a league or arena: the top-level mode of the same game mode ("ranked", "trophy_road")
  function pooledSlug(INDEX, entry) {
    const top = INDEX.modes.find((x) => !x.group && x.mode === entry.mode && x.status === "exported");
    return top ? top.slug : null;
  }

  // A card form as the matchup model knows it: a Hero the battle data can't tell from its base form is read as base.
  // Forms with no matchup weight add 0 and are listed so the page can say so.
  function matchupKeys(ME, entries) {
    const cards = ME.m.matchup.cards, keys = [], missing = [];
    for (const e of entries) {
      const k = `${e.id}:${e.form}`, b = `${e.id}:base`;
      if (k in cards) keys.push(k);
      else if (e.form === "hero" && b in cards) keys.push(b);
      else missing.push(e);
    }
    return { keys, missing };
  }

  // ---------------------------------------------------------------- matchups
  // E: the chosen mode's engine (opponent decks and styles come from it); ME: the engine whose matchup weights are
  // used (E itself, or the pooled mode's). All win rates are at equal player rating.
  function analyze(E, ME, entries) {
    const mu = E.m.matchup, mm = ME.m.matchup;
    if (!mu || !mm) return { state: "no_matchup" };
    const { keys, missing } = matchupKeys(ME, entries);
    const mine = keys.slice().sort().join("|");
    const winVs = (opps) => ME.winVs(keys, opps);

    // each opponent deck's style, from the chosen mode's style lists (only the most-played decks of each style are listed)
    const styleOf = new Map();
    for (const [st, list] of Object.entries(mu.styles || {})) for (const [d] of list) if (!styleOf.has(d)) styleOf.set(d, st);

    // styles: the chosen mode's opponent decks of each style, weighted by how often each was played
    const styles = Object.entries(mu.styles || {})
      .filter(([st, list]) => list.length && st !== "HYBRID / UNCERTAIN" && st !== "NO_LABELS")
      .map(([st, list]) => ({ style: st, decks: list.length, appearances: list.reduce((t, [, n]) => t + n, 0), win: winVs(list) }))
      .sort((a, b) => b.win - a.win || (a.style < b.style ? -1 : 1));

    // the field: the most-played opponent decks of the chosen mode, without the reader's own deck (a mirror is 50%)
    const field = mu.decks.slice(0, TOP_OPPONENTS).filter(([d]) => d !== mine);
    const total = field.reduce((t, [, n]) => t + n, 0);
    const rows = field.map(([d, n]) => ({ key: d, n, share: n / total, win: winVs([[d, 1]]), style: styleOf.get(d) || null }));
    const fieldWin = rows.reduce((t, r) => t + r.share * r.win, 0);
    const favoured = rows.reduce((t, r) => t + (r.win > 0.5 ? r.share : 0), 0);
    const byWin = rows.slice().sort((a, b) => b.win - a.win || b.n - a.n || (a.key < b.key ? -1 : 1));
    const beats = byWin.slice(0, SHOW).filter((r) => r.win > 0.5);
    const losesTo = byWin.slice().reverse().slice(0, SHOW).filter((r) => r.win < 0.5);

    // opponent cards: Σ over the reader's cards of K(mine, theirs), the card-against-card part only (each card's own
    // strength is left out, so a strong card isn't called a counter just for being strong). Cards in at least
    // MIN_CARD_SHARE of the field, weighted by appearances.
    const cardShare = new Map();
    for (const r of rows) for (const j of new Set(r.key.split("|"))) cardShare.set(j, (cardShare.get(j) || 0) + r.share);
    const mineSet = new Set(keys);
    const cards = [];
    for (const [j, share] of cardShare) {
      if (share < MIN_CARD_SHARE || mineSet.has(j) || !(j in mm.cards)) continue;
      let k = 0; const parts = [];
      for (const i of keys) {
        const w = ME.muK(i, j); if (!w) continue;
        k += w; const se = ME.muKse(i, j);
        parts.push({ mine: i, weight: w, ci90: se === null ? null : [w - Z90 * se, w + Z90 * se] });
      }
      if (!parts.length) continue;
      parts.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight) || (a.mine < b.mine ? -1 : 1));
      cards.push({ card: j, share, k, points: 100 * (sigmoid(k) - 0.5), parts });
    }
    const handles = cards.filter((c) => c.k > 0).sort((a, b) => b.k - a.k || (a.card < b.card ? -1 : 1)).slice(0, SHOW_CARDS);
    const trouble = cards.filter((c) => c.k < 0).sort((a, b) => a.k - b.k || (a.card < b.card ? -1 : 1)).slice(0, SHOW_CARDS);

    // the deck's held-out record against each style, when it is one of the mode's real pool decks
    E.counterPool();
    const pool = E._poolIndex ? E._poolIndex.get(entries.map((e) => `${e.id}:${e.form}`).sort().join("|")) : null;

    return { state: "ok", keys, missing, styles, field: { decks: rows.length, appearances: total, win: fieldWin, favoured },
             beats, losesTo, handles, trouble, poolRecord: pool ? pool.rec : null, poolPlayed: pool ? pool.played : 0 };
  }

  // the matchup model's held-out check, in the terms the page uses: the row for players the model never saw
  function evidence(ME) {
    const ev = ME.m.matchup && ME.m.matchup.evaluation;
    if (!ev) return null;
    const pd = ev.player_disjoint || null, r = pd || ev;
    return { disjoint: Boolean(pd), battles: r.battles, auc: r.auc_matchup, aucStrength: r.auc_strength,
             diff: r.difference, ci90: r.difference_ci90, better: Array.isArray(r.difference_ci90) && r.difference_ci90[1] < 0 };
  }

  return { MIN_OWN_PAIRS, TOP_OPPONENTS, SHOW, MIN_CARD_SHARE, SHOW_CARDS, parseDeckText, pairCount, needsPooled, pooledSlug, matchupKeys, analyze, evidence };
});
