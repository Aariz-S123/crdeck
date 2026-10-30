// Invariant sweep: seed web/engine.js with every card form (and some pairs, and 4 to 9 cards of real decks) and check
// every result: legal decks, seeds kept, distinct decks, legal swaps, finite numbers,
// and explanations that add up. Complements check_web_engine.mjs (parity with Python).
//   node scripts/sweep_web_engine.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { Engine, SeedError, parseDeckKey, keyOf, deckKey, sortedEntries } = require(join(root, "web", "engine.js"));
const index = JSON.parse(readFileSync(join(root, "web", "modes.json"), "utf8"));
const onlySlug = process.argv[2]; // optional: sweep one mode only
let model, E;

const problems = [];
const bad = (m) => { problems.push(m); if (problems.length <= 30) console.log("PROBLEM", m); };
const finite = (x) => typeof x === "number" && Number.isFinite(x);
// no search result or swap may use a card form that is not unlocked in the model's arena
function lockedUse(label, entries) { for (const e of entries) if (!E.isAvailable(e)) bad(`${label}: uses locked ${keyOf(e)}`); }
let searches = 0, refused = 0, swapsChecked = 0;

function checkResult(seeds, res, label) {
  if (!res.length) bad(`${label}: no decks returned`);
  const keys = new Set();
  for (const d of res) {
    lockedUse(`${label} deck`, d.entries);
    const r = E.checkDeck(d.entries);
    if (!r.legal) bad(`${label}: illegal deck ${d.key} ${r.reasons}`);
    for (const s of seeds) if (!d.entries.some((e) => e.id === s.id && e.form === s.form)) bad(`${label}: seed ${keyOf(s)} missing from ${d.key}`);
    if (keys.has(d.key)) bad(`${label}: duplicate deck ${d.key}`);
    keys.add(d.key);
    if (![d.objective, d.win_prob, d.mean_synergy, d.mean_log_lift].every(finite)) bad(`${label}: non-finite score ${d.key}`);
    const x = E.explain(d.entries, E.objectiveDict(d));
    if (!x.legality.legal) bad(`${label}: explanation says illegal ${d.key}`);
    if (![x.score.meta_win_prob, x.score.interval[0], x.score.interval[1]].every(finite)) bad(`${label}: non-finite explanation ${d.key}`);
    if (!(x.score.interval[0] <= x.score.meta_win_prob + 1e-12 && x.score.meta_win_prob <= x.score.interval[1] + 1e-12)) bad(`${label}: win prob outside interval ${d.key}`);
    if (Object.keys(x.legality.slots).length !== d.entries.filter((e) => E.slotKind(e)).length) bad(`${label}: special card without a slot ${d.key}`);
  }
  for (let i = 0; i < res.length; i++) for (let j = i + 1; j < res.length; j++) {
    const a = new Set(res[i].entries.map((e) => e.id));
    const diff = res[j].entries.filter((e) => !a.has(e.id)).length;
    if (diff < Number(model.config.search.min_diff_cards)) bad(`${label}: decks ${i} and ${j} differ by only ${diff} cards`);
  }
  // card-map swaps on the first deck: legal, unlocked, keep the picks, distance in [0, 2], win rate up
  for (const w of E.embeddingSwaps(res[0].entries, seeds)) {
    const nd = parseDeckKey(w.new_deck_key);
    if (!E.checkDeck(nd).legal) bad(`${label}: illegal card-map swap ${w.new_deck_key}`);
    lockedUse(`${label} card-map swap`, nd);
    for (const sd of seeds) if (!nd.some((e) => e.id === sd.id && e.form === sd.form)) bad(`${label}: card-map swap removed seed ${keyOf(sd)}`);
    if (!(w.distance >= -1e-9 && w.distance <= 2 + 1e-9) || !(w.delta_win_prob > 0)) bad(`${label}: card-map swap numbers ${w.distance} ${w.delta_win_prob}`);
  }
  // swaps on the first deck
  const sw = E.swaps(res[0].entries, { locked: seeds });
  for (const s of sw) {
    swapsChecked++;
    const nd = parseDeckKey(s.new_deck_key);
    lockedUse(`${label} swap`, nd);
    if (!E.checkDeck(nd).legal) bad(`${label}: illegal swap result ${s.new_deck_key}`);
    for (const sd of seeds) if (!nd.some((e) => e.id === sd.id && e.form === sd.form)) bad(`${label}: swap removed seed ${keyOf(sd)}`);
    const x = E.explainSwap(res[0].entries, s.replace_entry, s.with_entry);
    const sum = x.parts.reduce((t, p) => t + p.value, 0);
    if (Math.abs(sum - s.delta_objective) > 1e-9) bad(`${label}: swap breakdown does not add up for ${s.new_deck_key}`);
  }
}

function run(seeds, label, expectRefusal) {
  searches++;
  let res;
  try { res = E.complete(seeds); } catch (e) {
    if (!(e instanceof SeedError)) { bad(`${label}: crashed: ${e.stack}`); return; }
    refused++;
    if (!expectRefusal) bad(`${label}: refused unexpectedly: ${e.message}`);
    return;
  }
  if (expectRefusal) bad(`${label}: should have been refused`);
  checkResult(seeds, res, label);
}

const t0 = Date.now();
for (const entry of index.modes.filter((m) => m.status === "exported" && (!onlySlug || m.slug === onlySlug))) {
model = JSON.parse(readFileSync(join(root, "web", entry.file), "utf8"));
E = new Engine(model);
const before = { searches, refused, swapsChecked, problems: problems.length };
// in a single Trophy Road arena, forms not unlocked there (and combinations needing slots not
// unlocked yet) must be refused; elsewhere the fixed expectations below apply
const refusedHere = (seeds, base) => (model.availability ? seeds.some((s) => !E.isAvailable(s)) || !E.checkPartial(seeds).legal : base);
// 1. every card form alone
for (const c of model.cards) for (const f of E.allowedForms(c)) run([{ id: c.id, form: f }], `${c.name}@${f}`, refusedHere([{ id: c.id, form: f }], false));
// 2. forms that do not exist must be refused
for (const c of model.cards) {
  if (!c.evo) run([{ id: c.id, form: "evo" }], `${c.name}@evo (no such form)`, true);
  if (!c.hero) run([{ id: c.id, form: "hero" }], `${c.name}@hero (no such form)`, true);
}
// 3. hard combinations
const champs = model.cards.filter((c) => c.champion);
const combo = (seeds, label, base) => run(seeds, label, refusedHere(seeds, base));
combo(champs.slice(0, 2).map((c) => ({ id: c.id, form: "base" })), "two champions", false);
combo(champs.slice(0, 3).map((c) => ({ id: c.id, form: "base" })), "three champions", true);
const evos = model.cards.filter((c) => c.evo), heroes = model.cards.filter((c) => c.hero && !c.evo);
combo([evos[0], evos[1]].map((c) => ({ id: c.id, form: "evo" })).concat([{ id: heroes[0].id, form: "hero" }]), "2 evo + 1 hero", false);
combo(evos.slice(0, 3).map((c) => ({ id: c.id, form: "evo" })), "three evolutions", true);
combo([{ id: heroes[0].id, form: "hero" }, { id: heroes[1].id, form: "hero" }, { id: champs[0].id, form: "base" }], "2 heroes + champion", true);
combo([{ id: champs[0].id, form: "base" }, { id: heroes[0].id, form: "hero" }, { id: evos[0].id, form: "evo" }], "champion + hero + evo", false);
run([], "no seeds", false);
// 3a. more picks (the builder takes up to a full deck since 2026-10-29): 4 to 8 card forms of legal, unlocked decks
// (the top generated decks and up to 12 decks spread over the pool), so a legal completion exists. A full set of
// picks must come back as that very deck, alone, and a ninth card must be refused.
{
  const size = model.rules.deck_size;
  const pool = E.counterPool().filter((p) => E.checkDeck(p.entries).legal && p.entries.every((e) => E.isAvailable(e)));
  const step = Math.max(1, Math.ceil(pool.length / 12));
  const sources = E.complete([]).map((d) => d.entries).concat(pool.filter((_, i) => i % step === 0).slice(0, 12).map((p) => p.entries));
  sources.forEach((src, j) => {
    const es = sortedEntries(src), order = es.slice(j % size).concat(es.slice(0, j % size)); // other cards first for each deck
    for (let n = 4; n <= size; n++) run(order.slice(0, n), `${entry.slug} deck ${j}: ${n} picks`, false);
    let full = null;
    try { full = E.complete(order); } catch (e) { bad(`${entry.slug} deck ${j}: a full set of picks was refused: ${e.message}`); }
    if (full && (full.length !== 1 || full[0].key !== deckKey(order))) bad(`${entry.slug} deck ${j}: a full set of picks did not come back as itself alone`);
    const extra = E.candidates.find((c) => !order.some((o) => o.id === c.id));
    if (extra) run(order.concat([extra]), `${entry.slug} deck ${j}: ${size + 1} picks`, true);
  });
}
// 3b. counters against every deck style: only real decks (in the pool), legal and unlocked, win rates are
// probabilities; every tech swap is like-for-like, legal, unlocked, an improvement, and adds no deck warning
if (model.matchup) for (const st of Object.keys(model.matchup.styles)) {
  const opps = E.opponentsFor({ style: st });
  if (!opps.length) continue;
  searches++;
  const res = E.counterDecks(opps), pool = new Set(E.counterPool().map((p) => p.key));
  if (!res.length && pool.size) bad(`${entry.slug}: no counter deck for ${st}`);
  for (const d of res) {
    if (!pool.has(d.key)) bad(`${entry.slug}: counter deck vs ${st} is not a real deck ${d.key}`);
    if (!E.checkDeck(d.entries).legal) bad(`${entry.slug}: illegal counter deck vs ${st} ${d.key}`);
    lockedUse(`${entry.slug} counter vs ${st}`, d.entries);
    if (!(d.win_vs > 0 && d.win_vs < 1)) bad(`${entry.slug}: counter win rate ${d.win_vs} vs ${st}`);
    const w = d.swap; if (!w) continue;
    swapsChecked++;
    const a = E.card(w.replace.id), b = E.card(w.with.id), codes = (x) => new Set(E.structuralWarnings(x).map((y) => y.code)), before = codes(d.entries);
    if (a.type !== b.type || Boolean(a.wincon) !== Boolean(b.wincon)) bad(`${entry.slug}: tech swap vs ${st} is not like-for-like ${keyOf(w.replace)} > ${keyOf(w.with)}`);
    if (!E.checkDeck(w.entries).legal) bad(`${entry.slug}: illegal tech swap vs ${st} ${w.key}`);
    lockedUse(`${entry.slug} tech swap vs ${st}`, w.entries);
    if (!(w.win_vs > d.win_vs && w.score > d.score)) bad(`${entry.slug}: tech swap vs ${st} does not improve ${w.key}`);
    if (![...codes(w.entries)].every((x) => before.has(x))) bad(`${entry.slug}: tech swap vs ${st} adds a deck warning ${w.key}`);
  }
  for (const c of E.counterCards(opps, model.matchup.top_cards)) if (!finite(c.effect) || !E.isAvailable(c.entry)) bad(`${entry.slug}: counter card ${c.card} vs ${st}`);
}
// 4. the regression-line bins
const cal = E.calibration(8);
if (cal.total !== model.meta.test_battles_total * 2) bad(`calibration total ${cal.total}`);
if (!cal.bins.every((b) => [b.u, b.win, b.lo, b.hi, b.model].every(finite) && b.lo <= b.win && b.win <= b.hi)) bad("calibration bin values");
// 5. every playable form has its own entry in the forms list (API bitmask)
const nForms = model.cards.reduce((t, c) => t + E.allowedForms(c).length, 0);
if (model.forms.length !== nForms) bad(`${entry.slug}: forms list has ${model.forms.length} entries, card table has ${nForms} forms`);
console.log(`${entry.label}: ${searches - before.searches} searches (${refused - before.refused} refused), ${swapsChecked - before.swapsChecked} swaps, ${problems.length - before.problems} problems`);
}

console.log(`\n${searches} searches (${refused} correctly refused), ${swapsChecked} swaps checked, ${((Date.now() - t0) / 1000).toFixed(1)} s`);
console.log(problems.length ? `${problems.length} problem(s)` : "no problems found");
process.exit(problems.length ? 1 : 0);
