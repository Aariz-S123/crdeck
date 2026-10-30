// Golden check: web/engine.js must agree with the Python package on web/golden.json.
//   node scripts/check_web_engine.mjs              (the exported golden files, web/golden/)
//   node scripts/check_web_engine.mjs <dir>        (other golden files, e.g. from scripts/more_picks_golden.py;
//                                                   sections a file lacks, and modes without a file, are skipped)
// Exits 1 on any disagreement in legality, slots, searches, scores, explanations or swaps.
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { Engine, parseKey, keyOf, SeedError } = require(join(root, "web", "engine.js"));
const index = JSON.parse(readFileSync(join(root, "web", "modes.json"), "utf8"));
const goldenDir = process.argv[2] ? resolve(process.argv[2]) : null;

let failures = 0, checks = 0;
const fail = (msg) => { failures++; if (failures <= 25) console.log("FAIL", msg); };
const close = (a, b, tol) => Math.abs(a - b) <= tol;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// every exported mode has its own model and golden file
for (const entry of index.modes.filter((m) => m.status === "exported")) {
console.log(`\n=== ${entry.label} (${entry.slug}) ===`);
const goldenFile = join(goldenDir || join(root, "web", "golden"), `${entry.slug}.json`);
if (goldenDir && !existsSync(goldenFile)) { console.log("no golden file here, skipped"); continue; }
const model = JSON.parse(readFileSync(join(root, "web", entry.file), "utf8"));
const golden = JSON.parse(readFileSync(goldenFile, "utf8"));
const eng = new Engine(model);

// 1. legality on random decks
for (const g of golden.legality || []) {
  const deck = g.deck.map(parseKey);
  const r = eng.checkDeck(deck);
  checks++;
  if (r.legal !== g.legal || !same(r.reasons, g.reasons)) fail(`legality ${g.deck.join("|")}: js ${r.legal} ${r.reasons} vs py ${g.legal} ${g.reasons}`);
  if (!same(Object.entries(r.slots).sort(), Object.entries(g.slots).sort())) fail(`slots ${g.deck.join("|")}: ${JSON.stringify(r.slots)} vs ${JSON.stringify(g.slots)}`);
  const n = g.deck.length, rp = eng.checkPartial(deck.slice(0, Math.max(1, n - 3)));
  if (rp.legal !== g.partial_legal) fail(`partial ${g.deck.join("|")}: js ${rp.legal} vs py ${g.partial_legal}`);
}
console.log(`legality: ${(golden.legality || []).length} random decks checked`);

// 2. searches, swaps
for (const s of golden.searches) {
  const seeds = s.seeds.map(parseKey);
  checks++;
  let res;
  try { res = eng.complete(seeds); } catch (e) {
    if (!(e instanceof SeedError)) throw e;
    if (!s.error) fail(`search ${s.seeds}: js error ${e.message}, py succeeded`);
    else console.log(`search ${s.seeds.join(",") || "(none)"}: both refuse (${e.message.slice(0, 60)}…)`);
    continue;
  }
  if (s.error) { fail(`search ${s.seeds}: js succeeded, py error ${s.error}`); continue; }
  const keysJs = res.map((d) => d.key), keysPy = s.decks.map((d) => d.key);
  if (!same(keysJs, keysPy)) fail(`search ${s.seeds}: decks differ\n  js ${keysJs.join("\n     ")}\n  py ${keysPy.join("\n     ")}`);
  res.forEach((d, i) => {
    const p = s.decks[i]; if (!p) return;
    if (!close(d.objective, p.objective, 1e-9) || !close(d.win_prob, p.win_prob, 1e-9)) fail(`score ${d.key}: obj ${d.objective} vs ${p.objective}, wp ${d.win_prob} vs ${p.win_prob}`);
  });
  const sw = eng.swaps(res[0].entries, { locked: seeds });
  const a = sw.map((w) => [w.replace, w.with, w.new_deck_key]), b = s.swaps.map((w) => [w.replace, w.with, w.new_deck_key]);
  if (!same(a, b)) fail(`swaps ${s.seeds}: differ (js ${a.length}, py ${b.length}); first js ${JSON.stringify(a[0])} py ${JSON.stringify(b[0])}`);
  sw.forEach((w, i) => { if (s.swaps[i] && !close(w.delta_objective, s.swaps[i].delta_objective, 1e-5)) fail(`swap delta ${w.new_deck_key}: ${w.delta_objective} vs ${s.swaps[i].delta_objective}`); });
  // the "why this swap" breakdown must add up to the same objective change the ranking used
  sw.forEach((w) => {
    const x = eng.explainSwap(res[0].entries, w.replace_entry, w.with_entry);
    const sum = x.parts.reduce((a, p) => a + p.value, 0);
    checks++;
    if (!close(sum, w.delta_objective, 1e-9) || !close(x.total, w.delta_objective, 1e-9)) fail(`swap breakdown ${w.new_deck_key}: parts ${sum} total ${x.total} vs ${w.delta_objective}`);
  });
  // card-map swaps: same suggestions, distances and win-rate changes as Python
  if (s.embedding_swaps) {
    const ej = eng.embeddingSwaps(res[0].entries, seeds);
    checks++;
    if (!same(ej.map((w) => w.new_deck_key), s.embedding_swaps.map((w) => w.new_deck_key))) fail(`embedding swaps ${s.seeds}: js ${ej.map((w) => w.new_deck_key).length} py ${s.embedding_swaps.length} differ`);
    ej.forEach((w, i) => { const p = s.embedding_swaps[i]; if (p && (!close(w.distance, p.distance, 1e-9) || !close(w.delta_win_prob, p.delta_win_prob, 1e-9))) fail(`embedding swap ${w.new_deck_key}: distance ${w.distance} vs ${p.distance}, dwin ${w.delta_win_prob} vs ${p.delta_win_prob}`); });
  }
  console.log(`search ${s.seeds.join(",") || "(none)"}: ${res.length} decks and ${sw.length} swaps match`);
}

// 2b. counters: same real counter decks, scores, win rates against the opponents, tech swaps, and counter cards as Python
for (const c of golden.counters || []) {
  checks++;
  const dj = eng.counterDecks(c.opponents), cj = eng.counterCards(c.opponents, model.matchup.top_cards);
  if (!same(dj.map((d) => d.key), c.decks.map((d) => d.key))) fail(`counter decks ${c.kind} ${c.what}: js ${dj.map((d) => d.key).join(" / ")} vs py ${c.decks.map((d) => d.key).join(" / ")}`);
  dj.forEach((d, i) => {
    const p = c.decks[i]; if (!p) return;
    if (!close(d.win_vs, p.win_vs, 1e-9) || !close(d.score, p.score, 1e-9) || d.played !== p.played) fail(`counter deck ${d.key}: win ${d.win_vs} vs ${p.win_vs}, score ${d.score} vs ${p.score}, played ${d.played} vs ${p.played}`);
    const js = d.swap ? `${keyOf(d.swap.replace)}>${keyOf(d.swap.with)}` : "none", py = p.swap ? `${p.swap.replace}>${p.swap.with}` : "none";
    if (js !== py) fail(`tech swap for ${d.key}: js ${js} vs py ${py}`);
    else if (d.swap && (!close(d.swap.win_vs, p.swap.win_vs, 1e-9) || !close(d.swap.score, p.swap.score, 1e-9) || d.swap.key !== p.swap.key || d.swap.played !== p.swap.played)) fail(`tech swap numbers for ${d.key}`);
  });
  if (!same(cj.map((x) => x.card), c.cards.map((x) => x.card))) fail(`counter cards ${c.kind} ${c.what}: js ${cj.map((x) => x.card)} vs py ${c.cards.map((x) => x.card)}`);
  cj.forEach((x, i) => { if (c.cards[i] && !close(x.effect, c.cards[i].effect, 1e-9)) fail(`counter card effect ${x.card}: ${x.effect} vs ${c.cards[i].effect}`); });
  console.log(`counters ${c.kind} ${String(c.what).slice(0, 30)}: ${dj.length} decks (${dj.filter((d) => d.swap).length} tech swaps) and ${cj.length} cards match`);
}

// 3. explanations of each search's top deck
for (const x of golden.explanations) {
  const e = eng.explain(x.key.split("|").map(parseKey));
  checks++;
  if (!close(e.score.meta_win_prob, x.win_prob, 5e-5)) fail(`explain ${x.key}: win ${e.score.meta_win_prob} vs ${x.win_prob}`);
  if (!close(e.score.interval[0], x.interval[0], 5e-5) || !close(e.score.interval[1], x.interval[1], 5e-5)) fail(`explain ${x.key}: interval ${e.score.interval} vs ${x.interval}`);
  if (e.archetype.label !== x.archetype || (x.probability !== null && !close(e.archetype.probability, x.probability, 1e-6))) fail(`explain ${x.key}: archetype ${e.archetype.label} ${e.archetype.probability} vs ${x.archetype} ${x.probability}`);
  const codes = e.warnings.flatMap((g) => g.warnings.map((w) => w.code));
  if (!same(codes, x.warnings)) fail(`explain ${x.key}: warnings ${codes} vs ${x.warnings}`);
  if (!same(e.data_quality.map((d) => d.state), x.data_quality)) fail(`explain ${x.key}: data quality ${e.data_quality.map((d) => d.state)} vs ${x.data_quality}`);
  if (!same(e.synergy_top.map((p) => p.pair), x.synergy_top) || !same(e.synergy_bottom.map((p) => p.pair), x.synergy_bottom)) fail(`explain ${x.key}: synergy pairs differ`);
}
console.log(`explanations: ${golden.explanations.length} checked`);

// 4. the regression-line chart's held-out bins cover every test-window deck appearance exactly once
{
  const cal = eng.calibration(8);
  const want = model.meta.test_battles_total * 2;
  checks++;
  if (cal.total !== want) fail(`calibration covers ${cal.total} deck appearances, test window has ${want}`);
  if (cal.bins.reduce((t, b) => t + b.battles, 0) !== cal.total) fail("calibration bins do not add up");
  for (let i = 1; i < cal.bins.length; i++) if (cal.bins[i].u < cal.bins[i - 1].u) fail("calibration bins not ordered by strength");
  console.log(`calibration: ${cal.bins.length} bins over ${cal.total} test deck appearances (${cal.decks} decks)`);
  console.log(cal.bins.map((b) => `  u ${b.u.toFixed(3)}  real ${(100 * b.win).toFixed(1)}%  model ${(100 * b.model).toFixed(1)}%  n ${b.battles}`).join("\n"));
}

}

console.log(failures ? `\n${failures} disagreement(s) in ${checks} checks` : `\nall ${checks} checks agree with Python`);
process.exit(failures ? 1 : 0);
