// Run 4 checks (docs/claude-redesign/ACCEPTANCE.md R4.1–R4.4): the softmax table and sigmoid example against the
// engine, and the forecast's states, settings and coverage on the pages, using changed copies of modes.json served
// to the test page only (the export on disk is never edited).
//   cd tests/web && node run4_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "observed.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine, UNCERTAIN } = require(path.join(WEB, "engine.js"));
const CRObserved = require(path.join(WEB, "observed.js"));
const CRLearn = require(path.join(WEB, "learn.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));
const INDEX = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));

async function open(page, hash, transform) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, page), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}#${hash}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (rel === "modes.json" && transform) j = transform(j);
        return { ok: true, status: 200, json: async () => j };
      };
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");

(async () => {
  // R4.1 softmax table = Engine.predictArchetype, on several real decks in three modes
  out.softmax = [];
  for (const slug of ["ranked", "trophy_road", "ranked__master_iii"]) {
    const E = new Engine(load(slug));
    const decks = CRObserved.observedDecks(E, []).decks.map((d) => d.entries).concat(E.complete([]).map((d) => d.entries));
    for (const deck of decks) {
      const t = CRLearn.softmaxTable(E, deck), pr = E.predictArchetype(deck);
      expect(t.rows.every((r) => r.p === pr.probabilities[r.style]), `R4.1 ${slug}: softmax probabilities differ from predictArchetype`);
      expect(Math.abs(t.sum - 1) < 1e-9, `R4.1 ${slug}: probabilities sum to ${t.sum}`);
      expect(t.label === pr.label && t.top.p === pr.probability, `R4.1 ${slug}: label/threshold result differs`);
      expect(t.features.total === E.archetypeFeatures(deck).length && t.features.total === t.features.cards + t.features.roles + 3, `R4.1 ${slug}: feature count not from the export`);
      out.softmax.push([slug, t.label, +t.top.p.toFixed(3)]);
    }
  }
  expect(out.softmax.some((r) => r[1] === UNCERTAIN) && out.softmax.some((r) => r[1] !== UNCERTAIN), "R4.1 cases should cover both a threshold fallback and a confident label");
  // stability: adding 1000 to every intercept changes nothing (the max is subtracted before exp)
  const big = load("ranked"); big.archetype.intercept = big.archetype.intercept.map((b) => b + 1000);
  const Eb = new Engine(big), Er = new Engine(load("ranked")), dk = Er.complete([])[0].entries;
  const tb = CRLearn.softmaxTable(Eb, dk), tr = CRLearn.softmaxTable(Er, dk);
  expect(tb.rows.every((r, k) => Number.isFinite(r.p) && Math.abs(r.p - tr.rows[k].p) < 1e-9), "R4.1 max-subtraction does not keep softmax stable");
  expect(!/temperature\s*[:=(]/i.test(src["learn.js"] + src["engine.js"]), "R4.1 a temperature parameter appeared");

  // R4.2 sigmoid example = Engine.score's point estimate, and the formula holds
  const sg = CRLearn.sigmoidExample(Er, dk, 3);
  expect(sg.mean === Er.score(dk).win_prob && sg.p === 1 / (1 + Math.exp(-(sg.u - Er.oppU[3]))), "R4.2 sigmoid example differs from the engine");
  expect(sg.opponent.cards.length >= 7, "R4.2 opponent deck not decoded");

  // R4.2 / R4.3 How it works with the real export
  let p = await open("model.html", "ranked"), d = p.d;
  await until(() => d.querySelector("#three .three"));
  const three = text(d.querySelector("#three"));
  out.model = three.slice(0, 300);
  const x = Er.explain(CRObserved.observedDecks(Er, []).decks[0].entries);
  expect(three.includes(`That average is exactly the ${(100 * x.score.meta_win_prob).toFixed(1)}%`), "R4.2 worked sigmoid average doesn't match the deck's estimate");
  expect(/delta method/.test(three) && /not a bootstrap range/.test(three), "R4.2 deck interval method not named");
  expect(/not chances of winning/.test(three) && /never a win chance/.test(three) && /not a win rate/.test(three), "R4.2 styles, wins and usage not kept apart");
  expect(/“Hybrid” is a style the classifier was trained on; “Mixed style” is the site's fallback/.test(three), "R4.1 Hybrid vs fallback not explained");
  expect(d.querySelectorAll("#three table.nums tbody tr").length === Er.m.archetype.classes.length, "R4.1 softmax table lacks a row per class");
  expect(!p.errors.length, "model script errors: " + p.errors.join(" | ").slice(0, 300));

  // R4.3 / R4.4 forecast states from fixtures (status, forecast rows and settings changed in the served copy only)
  const F = (fn) => (j) => { j = JSON.parse(JSON.stringify(j)); fn(j.meta); return j; };
  const states = {
    blocked: F((m) => { m.status.state = "blocked"; m.status.reason = "Not enough periods (fixture)."; m.backtest = []; m.forecast = []; }),
    not_better: F((m) => { m.status.state = "not_better"; m.forecast = []; }),
    shown: F((m) => { m.status.state = "shown"; m.settings.monte_carlo_runs = 1234; m.forecast = [{ key: m.movers[0].key, median: 0.1, band50: [0.09, 0.11], band90: [0.08, 0.12] }]; }),
    shown_empty: F((m) => { m.status.state = "shown"; m.forecast = []; }),
    no_scored: F((m) => { m.backtest = m.backtest.map((b) => Object.assign({}, b, { card_forms_scored: 0 })); }),
  };
  out.meta = {};
  for (const [name, tf] of Object.entries(states)) {
    p = await open("meta.html", "ranked", tf); d = p.d;
    await until(() => d.querySelector("#fc-h"));
    const m = text(d.querySelector("#meta"));
    out.meta[name] = text(d.querySelector("#fc-h"));
    if (name === "blocked") expect(/not available yet/.test(out.meta[name]) && !/too narrow/.test(m), "R4.3 blocked state wrong");
    if (name === "not_better") expect(/hidden/.test(out.meta[name]), "R4.3 not_better state wrong");
    if (name === "shown") expect(/Experimental forecast shown/.test(out.meta[name]) && /1,234 runs/.test(m), "R4.3 shown state or exported run count not used");
    if (name === "shown_empty") expect(/nothing to forecast/.test(out.meta[name]) && /only \d+ battles/.test(m), "R4.3 shown-but-empty not explained");
    if (name === "no_scored") expect(!/held the real share \d/.test(m) && !/<td>\d+%<\/td><\/tr>/.test(d.querySelector("#meta").innerHTML), "R4.4 coverage invented with zero scored forms");
    if (name !== "blocked" && name !== "no_scored") {
      const s = CRLearn.forecastSummary(tf(INDEX).meta);
      expect(m.includes(`held the real share ${Math.round(100 * s.coverage)}% of the time`) && /not 90%/.test(m) && /not a significance test/.test(m), `R4.4 ${name}: coverage not shown against nominal`);
    }
    expect(/Season readiness/.test(m) && /It is not built/.test(m), `R4.3 ${name}: season readiness not kept separate`);
    expect(!p.errors.length, `meta ${name} script errors: ` + p.errors.join(" | ").slice(0, 300));
  }
  // weighted coverage on a hand-made fixture: (0.4·100 + 0.8·300) / 400 = 0.7; zero denominators give null
  const fx = { status: { state: "shown" }, backtest: [{ card_forms_scored: 100, coverage_90: 0.4, mae_points_monte_carlo: 1, mae_points_no_change: 1 }, { card_forms_scored: 300, coverage_90: 0.8, mae_points_monte_carlo: 1, mae_points_no_change: 1 }], periods: [], forecast: [] };
  expect(Math.abs(CRLearn.forecastSummary(fx).coverage - 0.7) < 1e-12, "R4.4 coverage is not weighted by card forms scored");
  expect(CRLearn.forecastSummary(Object.assign({}, fx, { backtest: [{ card_forms_scored: 0, coverage_90: 0.5, mae_points_monte_carlo: 1, mae_points_no_change: 1 }] })).coverage === null, "R4.4 zero denominator not handled");

  // R4.3 seasons page: readiness, not a prediction, independent of the forecast state
  p = await open("seasons.html", "ranked", states.shown); d = p.d;
  await until(() => d.querySelector("#pred-h"));
  const sz = text(d.querySelector("#body"));
  expect(/No next-season prediction is built/.test(sz) && /seasons collected/.test(sz) && !/Ready to backtest|When it unlocks/.test(sz), "R4.3 seasons page implies an automatic prediction");
  expect(!p.errors.length, "seasons script errors: " + p.errors.join(" | ").slice(0, 300));

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { out.fails = fails; console.log(JSON.stringify(out, null, 1)); console.error(e); process.exit(2); });
