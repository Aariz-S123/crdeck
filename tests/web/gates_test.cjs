// Honesty gates on win estimates (docs/fable-brief/BLUEPRINT.md 9.2, R0.3):
//  - a mode whose win model didn't beat a coin flip on later battles shows no estimate, range or pill;
//  - the green pill needs evidence outside the model: not a generated deck, seen in the battles, and at least
//    200 exact-deck games in the later test battles.
// Expected values are recomputed here from the exported models, not taken from the pages' helpers.
//   cd tests/web && node gates_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "observed.js", "votes.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine, deckKey } = require(path.join(WEB, "engine.js"));
const { UI } = require(path.join(WEB, "common.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const INDEX = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));
const LETTER = { b: "base", e: "evo", h: "hero" };
const ents = (s) => s.split("-").filter(Boolean).map((t) => ({ id: Number(t.slice(0, -1)), form: LETTER[t.slice(-1)] }));

async function open(page, hash = "") {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, page), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const f = path.join(WEB, String(u).replace(/^http:\/\/localhost\//, ""));
        if (!fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        const j = JSON.parse(fs.readFileSync(f, "utf8"));
        return { ok: true, status: 200, json: async () => j };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.Element.prototype.scrollIntoView = function () {};
      w.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const settled = (d) => d.querySelectorAll("#decks article.deck").length > 0 && !/Building|Loading/.test(text(d.querySelector("#status")));
const pageText = (d) => { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent.replace(/\s+/g, " "); };
function clean(name, p) {
  const t = pageText(p.d);
  expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(t), `${name}: broken value in text`);
  expect(!t.includes("—"), `${name}: em dash in text`);
  expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
}
// the gate's rule, straight from the exported check
const rowOf = (m) => (m.evaluation.strength_significance || []).find((r) => r.vs === "constant_0.5");
const shown = (m) => { const r = rowOf(m); return !r || r.ci90_hi < 0; };

(async () => {
  // ---------------- 1. the gate equals the rule in every exported mode
  const exported = INDEX.modes.filter((m) => m.status === "exported"), gated = [];
  for (const e of exported) {
    const m = load(e.slug), g = UI.estimateGate(m, e);
    expect(g.show === shown(m), `${e.slug}: gate says ${g.show}, the exported check says ${shown(m)}`);
    if (!g.show) {
      gated.push(e.slug);
      const r = rowOf(m), where = e.group || { ranked: "Ranked", trophy_road: "Trophy Road", all: "All modes" }[e.mode];
      expect(g.text.startsWith(`In ${where} the win model `) && g.text.endsWith("so no win estimate is shown."), `${e.slug}: gate sentence "${g.text}"`);
      expect(r.delta_log_loss >= 0 ? g.text.includes("does no better than a coin flip") : g.text.includes("isn't shown to beat a coin flip") && g.text.includes(Number(r.test_battles).toLocaleString()),
        `${e.slug}: gate wording doesn't follow the result: "${g.text}"`);
    } else expect(g.text === "", `${e.slug}: an open gate has no sentence`);
  }
  expect(gated.includes("all") && !gated.includes("ranked") && !gated.includes("trophy_road"), `gated modes: ${gated.join(", ")}`);
  const noCheck = UI.estimateGate({ evaluation: {} }, null);
  expect(noCheck.show === true && noCheck.row === null, "an export without the check keeps its estimates");
  out.modes = exported.length; out.gated = gated;

  // ---------------- 2. All modes: the builder shows no estimate, range or pill, and says why
  let p = await open("index.html", "all~~"), d = p.d;
  await until(() => settled(d));
  const allDecks = [...d.querySelectorAll("#decks article.deck")];
  expect(allDecks.length > 0, "All modes: no decks drawn");
  expect(text(d.querySelector("#gatenote")).includes("In All modes the win model does no better than a coin flip on later battles, so no win estimate is shown."), `All modes: gate sentence missing: ${text(d.querySelector("#gatenote"))}`);
  for (const [i, a] of allDecks.entries()) {
    expect(!a.querySelector(".pill") && !a.querySelector(".win .big") && !a.querySelector(".meter") && !a.querySelector(".win .range"), `All modes deck ${i + 1}: an estimate, range or pill is shown`);
    expect(!/\d%/.test(text(a.querySelector(".win"))), `All modes deck ${i + 1}: a percentage in the estimate block: ${text(a.querySelector(".win"))}`);
    expect(!/Estimated wins against|90% model range/.test(text(a)), `All modes deck ${i + 1}: estimate wording still there`);
    expect(/Average elixir/.test(text(a.querySelector(".win"))), `All modes deck ${i + 1}: average elixir is kept`);
    expect(/didn't beat a coin flip here/.test(text(a.querySelector(".rankwhy"))), `All modes deck ${i + 1}: the ranking note doesn't say its win part is weak`);
  }
  const cmpAll = d.querySelector("#compare");
  if (cmpAll) expect(!/Estimated wins/.test(text(cmpAll.querySelector("thead"))) && !cmpAll.querySelector("td.est"), "All modes: the comparison still has an estimate column");
  expect(/no win estimate is shown in this mode/.test(text(d.querySelector("#resnote"))) && !/Edges are small/.test(text(d.querySelector("#resnote"))), "All modes: reading note");
  clean("All modes builder", p);
  // its deck page
  const allHref = allDecks[0].querySelector('a[href^="reason.html#"]').getAttribute("href").split("#")[1];
  p = await open("reason.html", allHref); d = p.d;
  await until(() => d.querySelector("#ov-h"));
  expect(text(d.querySelector("#gatenote")).includes("In All modes the win model does no better than a coin flip"), "All modes deck page: gate sentence missing");
  expect(!d.querySelector(".short .big") && !d.querySelector(".short .pill"), "All modes deck page: estimate or pill in the short version");
  expect(!/Estimated wins/.test(text(d.querySelector(".overview"))), "All modes deck page: the best swap still shows estimated wins");
  clean("All modes deck page", p);
  // counters: the general estimate (the win model's) is left out; the matchup estimate has its own check and stays
  p = await open("counters.html", "all"); d = p.d;
  await until(() => d.querySelectorAll("#results article.deck").length > 0 || /too few battles/.test(text(d.querySelector("#verdict"))));
  if (d.querySelectorAll("#results article.deck").length) expect(!/general estimate vs sampled field/.test(text(d.querySelector("#results"))), "All modes counters: general estimate shown");
  clean("All modes counters", p);

  // ---------------- 3. a small league whose check is inconclusive says so with its battle count
  const small = INDEX.modes.find((e) => gated.includes(e.slug) && e.group && rowOf(load(e.slug)).delta_log_loss < 0);
  if (small) {
    p = await open("index.html", `${small.slug}~~`); d = p.d;
    await until(() => settled(d) || d.querySelector("#decks .empty"));
    const r = rowOf(load(small.slug));
    if (d.querySelector("#gatenote")) expect(text(d.querySelector("#gatenote")).includes(`In ${small.group} the win model isn't shown to beat a coin flip on later battles (only ${Number(r.test_battles).toLocaleString()} to check it on)`), `${small.slug}: ${text(d.querySelector("#gatenote"))}`);
    expect(!d.querySelector("#decks article.deck .pill"), `${small.slug}: a pill is shown`);
    clean(`${small.slug} builder`, p);
    out.smallGated = small.slug;
  }

  // ---------------- 4. Ranked: estimates stay; the green pill follows the evidence rule
  const m = load("ranked"), E = new Engine(m);
  const expectPill = (entries, source) => {
    const x = E.explain(entries, E.objectiveDict(E.evaluate(entries))), [lo, hi] = x.score.interval;
    const obsKey = deckKey(m.hero_observable ? entries : entries.map((e) => (e.form === "hero" ? { id: e.id, form: "base" } : e)));
    const games = (m.test_deck_records[obsKey] || [0, 0])[0], seen = (m.deck_appearances[obsKey] || 0) > 0;
    if (lo > 0.5) return source !== "generated" && seen && games >= 200 ? "Model estimate above 50%" : "Model estimate (no measured check)";
    return hi < 0.5 ? "Model estimate below 50%" : "Range includes 50%: no clear modeled edge";
  };
  const tally = {};
  for (const [hash, source] of [["ranked~~", "observed"], ["ranked~~~g", "generated"], ["ranked~~26000021b", "observed"], ["ranked~~26000021b~g", "generated"]]) {
    p = await open("index.html", hash); d = p.d;
    await until(() => settled(d));
    const cards = [...d.querySelectorAll("#decks article.deck")];
    expect(cards.length > 0 && !d.querySelector("#gatenote"), `${hash}: decks drawn and no gate note`);
    for (const [i, a] of cards.entries()) {
      const entries = ents(a.querySelector('a[href^="reason.html#"]').getAttribute("href").split("~")[1]);
      const want = expectPill(entries, source), got = text(a.querySelector(".pill"));
      expect(got === want, `${hash} deck ${i + 1}: pill "${got}", expected "${want}"`);
      expect(a.querySelector(".pill").classList.contains("good") === (want === "Model estimate above 50%"), `${hash} deck ${i + 1}: pill colour doesn't match its text`);
      expect(!!a.querySelector(".win .big") && /90% model range/.test(text(a)), `${hash} deck ${i + 1}: estimate missing`);
      tally[`${source}: ${want}`] = (tally[`${source}: ${want}`] || 0) + 1;
    }
    if (source === "generated") expect(!d.querySelector("#decks .pill.good"), `${hash}: a generated deck wears a green pill`);
    if (hash === "ranked~~") {
      // "Edges are small": the middle six of eight equal strength groups of the test battles, recomputed here
      await until(() => /Edges are small/.test(text(d.querySelector("#resnote"))), 60000);
      const c = E.calibration(8), a = E.winProbFromU(c.bins[1].uLo), b = E.winProbFromU(c.bins[6].uHi);
      const want = `three quarters of the games were played with decks this model scores between ${(100 * a).toFixed(1)}% and ${(100 * b).toFixed(1)}% here.`;
      expect(text(d.querySelector("#resnote")).endsWith(want), `edge note: "${text(d.querySelector("#resnote")).slice(-170)}", expected to end "${want}"`);
      const mid = c.bins.slice(1, 7).reduce((t, x) => t + x.battles, 0) / c.total;
      expect(Math.abs(mid - 0.75) < 0.02, `the middle six groups hold ${(100 * mid).toFixed(1)}% of the games, not about 75%`);
      out.edgeSpan = [a, b];
    }
    clean(`Ranked builder ${hash}`, p);
  }
  out.pills = tally;

  // ---------------- 5. Ranked deck page: estimate shown; a generated deck's pill is never green there either
  p = await open("index.html", "ranked~~~g"); d = p.d;
  await until(() => settled(d));
  const genHref = d.querySelector('#decks article.deck a[href^="reason.html#"]').getAttribute("href").split("#")[1];
  p = await open("reason.html", genHref); d = p.d;
  await until(() => d.querySelector("#ov-h"));
  expect(!!d.querySelector(".short .big") && !d.querySelector("#gatenote"), "Ranked deck page: estimate shown");
  expect(!d.querySelector(".short .pill.good"), "Ranked deck page of a generated deck: green pill");
  clean("Ranked generated deck page", p);

  console.log(JSON.stringify({ out, fails }, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
