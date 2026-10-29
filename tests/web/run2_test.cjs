// Run 2 checks (docs/claude-redesign/ACCEPTANCE.md R2.1–R2.6): the observed-deck selector against the hand-worked
// fixture shared with Python (tests/fixtures/observed_selector.json), its invariants on the real Ranked and
// Trophy Road exports, and the builder's observed/generated choice, empty states and links.
//   cd tests/web && node run2_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const engineSrc = fs.readFileSync(path.join(WEB, "engine.js"), "utf8");
const observedSrc = fs.readFileSync(path.join(WEB, "observed.js"), "utf8");
const commonSrc = fs.readFileSync(path.join(WEB, "common.js"), "utf8");
const { Engine, deckKey, keyOf, parseDeckKey } = require(path.join(WEB, "engine.js"));
const CRObserved = require(path.join(WEB, "observed.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));

// opts.transform: {file: (json) => json} to serve a changed copy of an export (the files on disk stay untouched)
async function open(page, hash = "", opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  const html = fs.readFileSync(path.join(WEB, page), "utf8")
    .replace('<script src="engine.js"></script>', () => `<script>${engineSrc}</script>`)
    .replace('<script src="observed.js"></script>', () => `<script>${observedSrc}</script>`)
    .replace('<script src="common.js"></script>', () => `<script>${commonSrc}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        if (!fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (opts.transform && opts.transform[rel]) j = opts.transform[rel](j);
        return { ok: true, status: 200, json: async () => j };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const settled = (d) => !/Building|Loading/.test(text(d.querySelector("#status")));
const hrefKey = (a) => deckKey(a.getAttribute("href").split("#")[1].split("~")[1].split("-").map((x) => ({ id: Number(x.slice(0, -1)), form: { b: "base", e: "evo", h: "hero" }[x.slice(-1)] })));
const shownKeys = (d) => [...d.querySelectorAll(".deck a.btn.primary")].map(hrefKey);
const tok = (e) => `${e.id}${e.form[0]}`;

(async () => {
  // R2.2 hand-worked fixture (the same cases run in Python: tests/test_observed.py)
  const fx = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "observed_selector.json"), "utf8"));
  const rows = fx.pool.map(([key, , objective]) => ({ key, objective }));
  out.fixture = fx.cases.map((c) => {
    const got = CRObserved.select(rows, c.seeds, c.n_results, c.min_diff).chosen.map((r) => r.key);
    expect(JSON.stringify(got) === JSON.stringify(c.expect), `R2.2 fixture '${c.name}': got ${JSON.stringify(got)}`);
    return [c.name, got.length];
  });

  // R2.1 / R2.2 invariants on real exports
  out.real = {};
  for (const slug of ["ranked", "trophy_road", "trophy_road__goblin_stadium"]) {
    const E = new Engine(load(slug)), pool = new Map(E.counterPool().map((p) => [p.key, p.played]));
    const minDiff = Number(E.cfg.search.min_diff_cards), n = Number(E.cfg.search.n_results);
    const byGames = E.candidates.slice().sort((a, b) => E.games(b) - E.games(a) || keyOf(a).localeCompare(keyOf(b)));
    const three = []; for (const c of byGames) { if (!three.some((t) => t.id === c.id) && E.checkPartial(three.concat([c])).legal) three.push(c); if (three.length === 3) break; }
    const cases = { none: [], one: [byGames[0]], evo: byGames.filter((c) => c.form === "evo").slice(0, 1), three };
    out.real[slug] = {};
    for (const [name, seeds] of Object.entries(cases)) {
      const r = CRObserved.observedDecks(E, seeds);
      out.real[slug][name] = { state: r.state, n: r.decks.length, matching: r.matching, seeds: seeds.map(keyOf) };
      r.decks.forEach((dk, i) => {
        const where = `R2.1 ${slug}/${name} deck ${i + 1}`;
        expect(pool.has(dk.key), `${where}: not in the exported pool`);
        expect(dk.played === pool.get(dk.key), `${where}: count is not the pool's train+validation count`);
        expect(seeds.every((s) => dk.key.split("|").includes(keyOf(s))), `${where}: misses an exact picked form`);
        expect(E.checkDeck(dk.entries).legal && dk.entries.every((e) => E.isAvailable(e)), `${where}: illegal or locked`);
        expect(deckKey(dk.entries) === dk.key && dk.entries.length === E.m.rules.deck_size, `${where}: entries don't match key`);
        expect(dk.objective === E.evaluate(dk.entries).objective, `${where}: objective isn't the builder's objective`);
        for (let j = 0; j < i; j++) {
          const a = new Set(dk.entries.map((e) => e.id)), b = new Set(r.decks[j].entries.map((e) => e.id));
          expect([...a].filter((x) => !b.has(x)).length >= minDiff, `${where}: closer than ${minDiff} cards to deck ${j + 1}`);
          expect(CRObserved.tie(r.decks[j].objective) >= CRObserved.tie(dk.objective), `${where}: ranked above a higher objective`);
        }
      });
      expect(r.decks.length <= n, `R2.3 ${slug}/${name}: more than n_results`);
      expect((r.state === "ok") === (r.decks.length === n) && (r.state === "no_match") === (r.decks.length === 0), `R2.3 ${slug}/${name}: state '${r.state}' doesn't match ${r.decks.length} decks`);
    }
  }

  // ---------------- builder UI
  const ranked = new Engine(load("ranked"));
  const obs0 = CRObserved.observedDecks(ranked, []).decks.map((x) => x.key);
  let p = await open("index.html", "ranked~~"), d = p.d;
  await until(() => settled(d) && d.querySelectorAll(".deck .grid8").length === 3);
  out.defaultObserved = { keys: shownKeys(d), tags: [...d.querySelectorAll(".deck .tag")].map(text), pressed: text(d.querySelector('[data-src][aria-pressed="true"]')) };
  expect(JSON.stringify(out.defaultObserved.keys) === JSON.stringify(obs0), "R2.1 default builder doesn't show the observed selector's decks");
  expect(out.defaultObserved.tags.every((t) => t === "Observed deck") && out.defaultObserved.pressed === "Observed decks", "R2.4 default decks not labelled observed");
  expect([...d.querySelectorAll(".deck")].every((el) => /appearances in this mode's training battles/.test(text(el)) && /not players/.test(text(el))), "R2.1 observed count not scoped as train+validation uses");
  // toggle to generated and back (R2.4, R2.5)
  d.querySelector('[data-src="generated"]').click();
  await until(() => settled(d) && /generated/.test(text(d.querySelector("#status"))));
  out.toggled = { keys: shownKeys(d), hash: p.w.location.hash, tags: [...d.querySelectorAll(".deck .tag")].map(text) };
  expect(JSON.stringify(out.toggled.keys) === JSON.stringify(ranked.complete([]).map((x) => x.key)), "R2.4 generated decks differ from Engine.complete");
  expect(out.toggled.tags.every((t) => /Generated by the model/.test(t)), "R2.4 generated decks not labelled generated");
  expect(out.toggled.hash === "#ranked~~~g", "R2.5 generated source not kept in the link");
  // generated decks that happen to be in the pool are still labelled generated (R2.4)
  d.querySelector('[data-src="observed"]').click();
  await until(() => settled(d) && /observed/.test(text(d.querySelector("#status"))));
  expect(p.w.location.hash === "#ranked~~" && JSON.stringify(shownKeys(d)) === JSON.stringify(obs0), "R2.5 back to observed didn't restore the default link/decks");
  expect(!p.errors.length, "builder script errors: " + p.errors.join(" | ").slice(0, 300));

  // R2.3 / R2.6 no observed match: three rare forms that share no pool deck
  const pool = ranked.counterPool(), inPool = (ks) => pool.some((q) => ks.every((k) => q.key.split("|").includes(k)));
  const rare = ranked.candidates.filter((c) => c.form === "base").sort((a, b) => ranked.games(a) - ranked.games(b) || keyOf(a).localeCompare(keyOf(b)));
  let none = null;
  for (const c of rare) { if (!inPool([keyOf(c)]) && ranked.checkPartial([c]).legal) { none = [c]; break; } }
  if (!none) for (let i = 0; i < rare.length && !none; i++) for (let j = i + 1; j < rare.length && !none; j++) if (!inPool([keyOf(rare[i]), keyOf(rare[j])]) && ranked.checkPartial([rare[i], rare[j]]).legal) none = [rare[i], rare[j]];
  p = await open("index.html", `ranked~~${none.map(tok).join("-")}`); d = p.d;
  await until(() => settled(d) && !!d.querySelector(".obsnote"));
  out.noMatch = text(d.querySelector(".obsnote"));
  expect(/No observed deck holds all your picks/.test(out.noMatch) && /may still have been played/.test(out.noMatch), "R2.3 no-match state missing or implies the deck was never played");
  expect(!/fewer than/.test(out.noMatch), "R2.6 pool absence described as 'fewer than' appearances");
  expect(d.querySelectorAll(".deck .grid8").length === 0, "R2.3 no-match state padded with decks");
  d.querySelector("[data-gen]").click();
  await until(() => settled(d) && d.querySelectorAll(".deck .grid8").length > 0);
  out.noMatchGenerated = { hash: p.w.location.hash, tags: [...d.querySelectorAll(".deck .tag")].map(text) };
  expect(/~g$/.test(out.noMatchGenerated.hash) && out.noMatchGenerated.tags.every((t) => /Generated/.test(t)), "R2.3 explicit generated fallback didn't work");

  // R2.3 fewer diverse decks than asked: the first single pick, in a small-pool league, with 1 or 2 observed decks
  let fewSeed = null, fewSlug = null;
  for (const slug of ["ranked__master_iii", "ranked__champion", "trophy_road__goblin_stadium"]) {
    const eng = new Engine(load(slug));
    for (const c of eng.candidates) { if (CRObserved.observedDecks(eng, [c]).state === "few") { fewSeed = c; fewSlug = slug; break; } }
    if (fewSeed) break;
  }
  if (fewSeed) {
    p = await open("index.html", `${fewSlug}~~${tok(fewSeed)}`); d = p.d;
    await until(() => settled(d) && !!d.querySelector(".obsnote"));
    out.few = { slug: fewSlug, seed: keyOf(fewSeed), note: text(d.querySelector(".obsnote")), decks: d.querySelectorAll(".deck .grid8").length };
    expect(/Nothing was added/.test(out.few.note) && out.few.decks > 0 && out.few.decks < 3, "R2.3 'few' state not explained or padded");
  } else fails.push("R2.3 no single pick gives a 'few' state in the small-pool modes searched");

  // R2.3 / R2.5 a mode export without a pool: observed says so, generated still works
  const noPool = (j) => { delete j.matchup; return j; };
  p = await open("index.html", "ranked~~", { transform: { "models/ranked.json": noPool } }); d = p.d;
  await until(() => settled(d) && !!d.querySelector(".obsnote"));
  out.noPool = text(d.querySelector(".obsnote"));
  expect(/No observed decks in this mode/.test(out.noPool), "R2.3 missing pool not explained");
  d.querySelector("[data-gen]").click();
  await until(() => settled(d) && d.querySelectorAll(".deck .grid8").length === 3);
  expect(JSON.stringify(shownKeys(d)) === JSON.stringify(ranked.complete([]).map((x) => x.key)), "R2.5 generated path broke without a pool");
  expect(!p.errors.length, "no-pool script errors: " + p.errors.join(" | ").slice(0, 300));

  // R2.5 refresh/deep link and Explain/back keep mode, picks and source
  p = await open("index.html", "ranked~~28000015b~g"); d = p.d;
  await until(() => settled(d) && d.querySelectorAll(".deck .grid8").length === 3);
  const explain = d.querySelector(".deck a.btn.primary").getAttribute("href");
  out.explainLink = explain;
  expect(/~28000015b~g$/.test(explain), "R2.5 Explain link drops picks or source");
  p = await open("reason.html", explain.split("#")[1]); d = p.d;
  await until(() => d.querySelector("#short-h"));
  out.backLink = d.querySelector("#back").getAttribute("href");
  expect(out.backLink === "index.html#ranked~~28000015b~g", "R2.5 back link drops picks or source");
  p = await open("index.html", "ranked~~28000015b"); d = p.d;
  await until(() => settled(d) && d.querySelectorAll(".deck .grid8").length > 0);
  expect(/observed/.test(text(d.querySelector("#status"))) && [...d.querySelectorAll(".deck")].every((el) => /Hog|Barbarian Barrel|Arrows|Fireball|Log|Zap/.test(text(el))), "R2.5 old link (no source) doesn't open observed decks");
  const oKeys = shownKeys(d);
  expect(oKeys.every((k) => k.split("|").includes("28000015:base")), "R2.1 observed deck without the picked form");

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { out.fails = fails; console.log(JSON.stringify(out, null, 1)); console.error(e); process.exit(2); });
