// Invariant sweep: seed web/engine.js with every card form (and some pairs) and check
// every result: legal decks, seeds kept, distinct decks, legal swaps, finite numbers,
// and explanations that add up. Complements check_web_engine.mjs (parity with Python).
//   node scripts/sweep_web_engine.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { Engine, SeedError, parseDeckKey, keyOf } = require(join(root, "web", "engine.js"));
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
