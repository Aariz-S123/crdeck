// The counter deck builder (web/counterbuild.js): the shared fixture against Python's answers, then the builder on
// the real Ranked model and on the Find counters page ("Cards I keep facing").
//   cd tests/web && node counterbuild_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const FIX = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "counter_builder.json"), "utf8"));
global.CRDeck = require(path.join(WEB, "engine.js"));
const { Engine, keyOf, deckKey } = global.CRDeck;
const CB = require(path.join(WEB, "counterbuild.js"));
const { loadModel } = require("./model_file.cjs");
const src = Object.fromEntries(["engine.js", "common.js", "counterbuild.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const close = (a, b, tol = 1e-10) => Math.abs(a - b) <= tol;

async function open(hash) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, "counters.html"), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/counters.html#${hash}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
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
const pageText = (d) => { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent.replace(/\s+/g, " "); };

(async () => {
  // ---------------- 1. the shared fixture: the same numbers as Python
  const K = new Map(FIX.pairs.map(([a, b, k]) => [`${a}|${b}`, k]));
  const w = (x) => FIX.w[x] || 0, k = (i, j) => (i === j ? 0 : i < j ? K.get(`${i}|${j}`) || 0 : -(K.get(`${j}|${i}`) || 0));
  const syn = [0.010, 0.012, -0.004, 0.020, 0.000, 0.006], lift = [0.40, 0.35, 0.10, 0.80, 0.20, 0.55];
  for (const c of FIX.cases) {
    expect(CB.shares(c.picks) === c.share, `${c.name}: share`);
    const rows = c.fits.map(([key, z, fit], i) => {
      const g = CB.fieldFit(key.split("|"), c.picks, w, k);
      expect(close(g.z, z, 1e-12) && close(g.fit, fit, 1e-12), `${c.name}: fit of ${key} is ${g.z}, Python ${z}`);
      return { key, fit: g.fit, mean_synergy: syn[i], mean_log_lift: lift[i] };
    });
    const got = CB.rank(rows, FIX.synergy_weight, FIX.cooccurrence_weight, c.n_results, c.min_diff);
    expect(JSON.stringify(got.map((r) => r.key)) === JSON.stringify(c.expect), `${c.name}: order ${got.map((r) => r.key).join(" ; ")}`);
    got.forEach((r, i) => expect(close(r.score, c.scores[i], 1e-12), `${c.name}: score ${i}`));
  }
  const tied = CB.rank(FIX.ties.rows, FIX.synergy_weight, FIX.cooccurrence_weight, 3, 1).map((r) => r.key);
  expect(JSON.stringify(tied) === JSON.stringify(FIX.ties.expect), "float-noise ties go to the key");
  for (const e of FIX.elixir) expect(JSON.stringify(CB.elixirBounds(e.decks)) === JSON.stringify(e.expect), `elixir bounds ${JSON.stringify(e)}`);
  for (const e of FIX.exact) expect(CB.useExact(new Array(e.picks).fill("x"), e.decks) === e.expect, `exact rule ${JSON.stringify(e)}`);
  out.fixture = FIX.cases.length;

  // ---------------- 2. the real Ranked model: 16 picks from two real decks
  const E = new Engine(loadModel(path.join(WEB, "models", "ranked.json")));
  const pool = E.counterPool(), two = [pool[0], pool.find((p) => [...p.entries].filter((e) => pool[0].entries.some((x) => x.id === e.id)).length === 0)];
  const picks = [...new Set(two.flatMap((p) => p.entries.map(keyOf)))].slice(0, 16);
  const cand = CB.candidates(E), rule = E.suggestionRule([]);
  expect(cand.bounds && cand.bounds[0] < cand.bounds[1], `elixir bounds ${cand.bounds}`);
  for (const style of ["Any", ...CB.STYLES]) {
    const r = CB.build(E, picks, style);
    if (style !== "Any" && cand.counts[style] < CB.MIN_STYLE_DECKS) { expect(r.state === "style_too_few" && !r.decks.length, `${style}: a chip with ${cand.counts[style]} decks must be refused`); continue; }
    expect(r.state === "ok" && r.decks.length === Math.min(3, r.candidates) && r.path === "field" && r.share === 0.5, `${style}: ${r.state}, ${r.decks.length} decks, path ${r.path}`);
    for (const d of r.decks) {
      expect(E.checkDeck(d.entries).legal && d.entries.every((e) => E.isAvailable(e)) && rule.full(d.entries), `${style}: deck fails legality, unlocks or norms`);
      expect(d.elixir >= cand.bounds[0] - 1e-9 && d.elixir <= cand.bounds[1] + 1e-9, `${style}: deck elixir ${d.elixir} outside the group's bounds`);
      expect(style === "Any" || E.predictArchetype(d.entries).label === style, `${style}: wrong style`);
      expect(pool.some((p) => p.key === d.key), `${style}: not a pool deck`);
      // fit recomputed from the matchup weights, independently of the module
      const s = 0.5, A = [...new Set(d.entries.map(keyOf))].sort(), P = [...picks].sort();
      let z = 0; for (const i of A) z += E.muW(i); for (const j of P) z -= s * E.muW(j); for (const i of A) for (const j of P) z += s * E.muK(i, j);
      expect(close(d.fit, 1 / (1 + Math.exp(-z))), `${style}: fit differs from the formula`);
    }
    if (style === "Any") out.anyDecks = r.decks.map((d) => d.key);
  }
  // exact path: 2 picks held by at least 5 opponent decks
  const pp = pool[0].entries.slice(0, 2).map(keyOf), rx = CB.build(E, pp, "Any");
  const nOpp = E.opponentsFor({ cards: pp }).length;
  expect(rx.path === (nOpp >= 5 ? "exact" : "field") && rx.opponents === nOpp, `exact path: ${rx.path} with ${nOpp} opponent decks`);
  if (rx.path === "exact") { const sc = E._counterScorer(E.opponentsFor({ cards: pp })); for (const d of rx.decks) expect(close(d.fit, sc.win(sc.total(d.entries))), "exact path fit = W(A | O)"); }
  expect(CB.build(E, [], "Any").state === "no_picks", "no picks: the empty state");
  out.counts = cand.counts; out.passing = cand.passing; out.candidates = cand.rows.length;

  // ---------------- 3. the page
  const tok = (ks) => ks.map((x) => { const [id, f] = x.split(":"); return `${id}${{ base: "b", evo: "e", hero: "h" }[f]}`; }).join("-");
  let p = await open(`ranked~~${tok(picks)}~~c:Any`), d = p.d;
  await until(() => d.querySelectorAll("#results article.cbdeck").length > 0 || d.querySelector("#results .empty"));
  expect(d.querySelector('[data-tab="build"]').getAttribute("aria-pressed") === "true", "page: the builder tab is chosen from the link");
  expect(text(d.querySelector("#cbcount")) === `${picks.length} of 16`, `page: pick counter "${text(d.querySelector("#cbcount"))}"`);
  const shown = [...d.querySelectorAll("#results article.cbdeck")].map((a) => a.dataset.key);
  expect(JSON.stringify(shown) === JSON.stringify(out.anyDecks), `page decks differ from the module: ${shown.join(" ; ")}`);
  const chips = [...d.querySelectorAll("[data-cbstyle]")];
  for (const ch of chips) {
    const s = ch.dataset.cbstyle;
    if (s === "Any") continue;
    expect(ch.disabled === (cand.counts[s] < CB.MIN_STYLE_DECKS) && text(ch).includes(String(cand.counts[s])), `chip ${s}: disabled ${ch.disabled}, count ${cand.counts[s]}`);
  }
  const all = pageText(d);
  for (const bad of [/guaranteed/i, /\bbest\b/i, /—/]) expect(!bad.test(text(d.querySelector("#results"))), `page: forbidden wording ${bad}`);
  expect(/How these decks were chosen/.test(all) && all.includes(cand.bounds[0].toFixed(1)) && all.includes(cand.bounds[1].toFixed(1)), "page: norms disclosure with the elixir bounds");
  expect(/Still weak against/.test(text(d.querySelector("#results article.cbdeck"))), "page: weak-against line");
  // the forward check's verdict, worded from counter_eval.json
  const EV = JSON.parse(fs.readFileSync(path.join(WEB, "counter_eval.json"), "utf8")), fb = (EV.modes.ranked || {}).builder;
  const vt = text(d.querySelector("#cbcheck"));
  expect(!fb || fb.skipped ? /^Not checked yet/.test(vt) : fb.verdict === "better" ? /^Checked on later battles/.test(vt) : fb.verdict === "not_shown" ? /^Not shown to beat a random real deck here/.test(vt) : /^Too few later battles/.test(vt), `builder check wording: "${vt}"`);
  if (fb && !fb.skipped) expect(vt.includes(Number((fb.adjusted || fb).games.builder).toLocaleString()), "builder check: game count");
  out.builderCheck = vt;
  expect(!p.errors.length, `page errors: ${p.errors.join(" | ").slice(0, 300)}`);
  // choosing a style keeps the picks in the link
  const usable = chips.find((c) => c.dataset.cbstyle !== "Any" && !c.disabled);
  if (usable) {
    usable.click();
    await until(() => p.w.location.hash.endsWith(encodeURIComponent(`c:${usable.dataset.cbstyle}`)));
    expect(p.w.location.hash.includes(tok(picks)), `link keeps the picks: ${p.w.location.hash}`);
  }
  // old links still open the old tabs
  p = await open("ranked~~~~Siege"); d = p.d;
  await until(() => d.querySelector("[data-style]"));
  expect(d.querySelector('[data-tab="style"]').getAttribute("aria-pressed") === "true", "old style link opens the style tab");
  p = await open(`ranked~~${tok(picks.slice(0, 2))}`); d = p.d;
  await until(() => d.querySelector(".oppcards"));
  expect(d.querySelector('[data-tab="cards"]').getAttribute("aria-pressed") === "true", "old cards link opens the cards tab");

  console.log(JSON.stringify({ out, fails }, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
