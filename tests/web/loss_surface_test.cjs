// Approximate loss surfaces on How it works (web/loss-surface.js and the loss-surface chart in web/model.html).
// Part 1 checks the quadratic, the packed curvature, the slice and the helpers against independent arithmetic on
// fixtures (no browser needed). Part 2 opens model.html in jsdom with the real export (modes.json, models/) and
// controlled approximation files: selectors, duplicate prevention, compare mode, shared view, ticks, category
// weights, exact-preset source, keyboard stops, one fetch, and missing / malformed / incompatible files.
//   cd tests/web && npm install && node loss_surface_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const WEB = path.join(__dirname, "..", "..", "web");
const CRLoss = require(path.join(WEB, "loss-surface.js"));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const close = (a, b, tol = 1e-9) => Math.abs(a - b) <= tol;

// ------------------------------------------------------------ fixtures
// a symmetric positive-definite H = M Mᵀ + 0.05 I with non-zero cross terms, packed independently of the module
function fixture(forms, seed = 1) {
  let s = seed; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647) - 0.5;
  const m = forms.length, M = forms.map(() => forms.map(() => rnd()));
  const H = forms.map((_, i) => forms.map((_, j) => M[i].reduce((t, v, k) => t + v * M[j][k], 0) * 0.2 + (i === j ? 0.05 : 0)));
  const packed = [];
  for (let i = 0; i < m; i++) for (let j = i; j < m; j++) packed.push(H[i][j]);   // row-major upper triangle
  const body = { schema_version: 1, source_mode: "ranked", n_train: 12345, C: 0.5, half_width: 0.05, J0: 0.6812345678,
    forms, weights: forms.map(() => 0.3 * rnd()), g: forms.map(() => 1e-3 * rnd()), h_packed: packed, snapshot_id: "fixture-" + seed };
  return { body, H };
}
const F5 = [["1:base", "Knight", "base", "troop", 900], ["1:evo", "Knight", "evo", "troop", 300], ["2:base", "Fireball", "base", "spell", 800],
  ["3:base", "Cannon", "base", "building", 500], ["4:base", "Archers", "base", "troop", 700]];

async function main() {
  // ============================================================ part 1: arithmetic
  const { body, H } = fixture(F5, 7), m = F5.length;
  const V = CRLoss.validate(body, { snapshot_id: body.snapshot_id });
  expect(V.ok, `validate rejected a good fixture: ${V.reason}`);
  const S = V.S;
  // packed index: every (i, j) once, symmetric, the same order the fixture used
  const seen = new Set();
  let k = 0;
  for (let i = 0; i < m; i++) for (let j = i; j < m; j++) { expect(CRLoss.packedIndex(i, j, m) === k && CRLoss.packedIndex(j, i, m) === k, `packed index (${i}, ${j})`); seen.add(CRLoss.packedIndex(i, j, m)); k++; }
  expect(seen.size === (m * (m + 1)) / 2, "packed index does not cover the triangle");
  // the quadratic against an independent full-vector dᵀ H d, for every ordered pair (swapped axes included)
  let worst = 0, cases = 0;
  for (let ia = 0; ia < m; ia++) for (let ib = 0; ib < m; ib++) {
    if (ia === ib) continue;
    const B = CRLoss.pairBlock(S, F5[ia][0], F5[ib][0]);
    expect(CRLoss.quadLoss(B, 0, 0) === body.J0, "zero displacement is not J0");
    for (const [da, db] of [[0.03, -0.02], [-0.05, 0.05], [0.011, 0.047]]) {
      const d = new Array(m).fill(0); d[ia] = da; d[ib] = db;
      let quad = 0, lin = 0;
      for (let i = 0; i < m; i++) { lin += body.g[i] * d[i]; for (let j = 0; j < m; j++) quad += d[i] * H[i][j] * d[j]; }
      const want = body.J0 + lin + 0.5 * quad, got = CRLoss.quadLoss(B, da, db);
      const gw = [body.g[ia] + H[ia].reduce((t, h, j) => t + h * d[j], 0), body.g[ib] + H[ib].reduce((t, h, j) => t + h * d[j], 0)];
      const gg = CRLoss.quadGrad(B, da, db);
      worst = Math.max(worst, Math.abs(got - want), Math.abs(gg[0] - gw[0]), Math.abs(gg[1] - gw[1])); cases++;
      // and the gradient is the derivative of the loss (central differences)
      const h = 1e-6, fd = [(CRLoss.quadLoss(B, da + h, db) - CRLoss.quadLoss(B, da - h, db)) / (2 * h), (CRLoss.quadLoss(B, da, db + h) - CRLoss.quadLoss(B, da, db - h)) / (2 * h)];
      expect(close(fd[0], gg[0], 1e-7) && close(fd[1], gg[1], 1e-7), "gradient differs from finite differences");
    }
  }
  out.quadratic = { cases, worst_abs_error: worst };
  expect(worst <= 1e-9, `quadratic or gradient off by ${worst}`);
  expect(H[0][2] !== 0 && body.g.every((x) => x !== 0), "fixture lacks a cross term or gradient");
  // identical or unknown axes are refused
  let threw = 0;
  for (const [a, b] of [["1:base", "1:base"], ["1:base", "9:base"]]) { try { CRLoss.pairBlock(S, a, b); } catch { threw++; } }
  expect(threw === 2, "identical or unknown axis keys accepted");
  // the slice: renderer shape, centred on the fitted point, arrows from the quadratic, a downhill path inside the range
  const sl = CRLoss.customSlice(S, "1:evo", "3:base");
  const r = body.half_width, wa = body.weights[1], wb = body.weights[3];
  expect(sl.approximate === true && sl.fitted_loss === body.J0 && sl.keys.join() === "1:evo,3:base", "slice not flagged approximate or not at J0");
  expect(sl.a.length === CRLoss.GRID && sl.b.length === CRLoss.GRID && sl.loss.length === CRLoss.GRID && sl.loss.every((row) => row.length === CRLoss.GRID), "slice grid shape");
  expect(sl.a[20] === wa && sl.b[20] === wb && close(sl.a[0], wa - r, 1e-12) && close(sl.b[40], wb + r, 1e-12), "slice not centred on the fitted weights");
  expect(sl.grad_a.length === CRLoss.ARROWS && sl.grad_a[0].length === CRLoss.ARROWS && sl.arrow_step === 5, "arrow grid shape");
  const Bs = CRLoss.pairBlock(S, "1:evo", "3:base");
  expect(close(sl.loss[7][33], CRLoss.quadLoss(Bs, sl.a[7] - wa, sl.b[33] - wb), 0) && close(sl.grad_b[2][6], CRLoss.quadGrad(Bs, sl.a[10] - wa, sl.b[30] - wb)[1], 0), "grid values not from the quadratic");
  const pl = sl.path.map((q) => q[2]);
  expect(sl.path.length === CRLoss.PATH_STEPS + 1 && pl.every((v, i) => i === 0 || v <= pl[i - 1] + 1e-15), "path goes uphill");
  expect(sl.path.every((q) => Math.abs(q[0] - wa) <= r + 1e-12 && Math.abs(q[1] - wb) <= r + 1e-12), "path leaves the drawn range");
  expect(sl.path.every((q) => close(q[2], CRLoss.quadLoss(Bs, q[0] - wa, q[1] - wb), 1e-15)), "path loss not from the quadratic");
  expect(pl[pl.length - 1] - body.J0 < 0.05 * (pl[0] - body.J0) + 1e-12, "path doesn't reach the bottom");
  // a strong gradient pushes the quadratic's minimum outside the range: the path is clamped and still only goes down
  const steep = JSON.parse(JSON.stringify(body)); steep.g = steep.g.map(() => 0.05); steep.snapshot_id = "steep";
  const ss = CRLoss.customSlice(CRLoss.validate(steep).S, "1:base", "2:base"), sp = ss.path.map((q) => q[2]);
  expect(sp.every((v, i) => i === 0 || v <= sp[i - 1] + 1e-15) && ss.path.every((q) => Math.abs(q[0] - ss.fitted[0]) <= r + 1e-12 && Math.abs(q[1] - ss.fitted[1]) <= r + 1e-12), "clamped path wrong");
  // validation rejects missing, malformed, incompatible and non-number files
  const bad = (f) => { const j = JSON.parse(JSON.stringify(body)); f(j); return CRLoss.validate(j, { snapshot_id: j.snapshot_id }); };
  const rejected = {
    missing: CRLoss.validate(null), schema: bad((j) => { j.schema_version = 2; }), mode: bad((j) => { j.source_mode = "trophy_road"; }),
    dims: bad((j) => { j.h_packed.pop(); }), nan: bad((j) => { j.weights[2] = null; }), dup: bad((j) => { j.forms[1] = j.forms[0]; }),
    type: bad((j) => { j.forms[0][3] = "tower"; }), diag: bad((j) => { j.h_packed[0] = -1; }), range: bad((j) => { j.half_width = 0; }),
    id: CRLoss.validate(body, { snapshot_id: "other" }),
  };
  out.rejected = Object.fromEntries(Object.entries(rejected).map(([k2, v]) => [k2, v.ok ? "ACCEPTED" : v.reason]));
  expect(Object.values(rejected).every((v) => !v.ok && typeof v.reason === "string"), "a bad file was accepted");
  // ticks: at least three, distinct labels, inside the range, including a tiny loss span
  for (const [lo, hi] of [[0.68112, 0.68151], [-0.0512, 0.0488], [0.6931471, 0.6931479], [0.2, 0.3]]) {
    const t = CRLoss.ticks(lo, hi, 3);
    expect(t.length >= 3 && new Set(t.map((x) => x.label)).size === t.length && t.every((x) => x.v >= lo - 1e-12 && x.v <= hi + 1e-12), `ticks for [${lo}, ${hi}]: ${t.map((x) => x.label)}`);
  }
  out.ticks = CRLoss.ticks(0.68112, 0.68151, 3).map((x) => x.label);
  // selector options and category groups: every form once, readable form names, types from the file
  const op = CRLoss.formOptions(S);
  expect(op.length === m && new Set(op.map((o) => o.key)).size === m && op.some((o) => o.label === "Knight (Evolution)") && op.some((o) => o.label === "Knight"), "selector options");
  const cg = CRLoss.categoryGroups(S);
  expect(cg.map((g) => g.title).join() === "Troops,Spells,Buildings" && cg.reduce((t, g) => t + g.items.length, 0) === m, "category groups");
  expect(cg[0].items.every((it, i, a) => i === 0 || a[i - 1].weight >= it.weight) && cg[2].items[0].key === "3:base" && cg[2].items[0].weight === body.weights[3], "category order or weights");
  const noB = JSON.parse(JSON.stringify(body)); noB.forms[3][3] = "troop";
  expect(/No buildings/.test(CRLoss.categoryGroups(CRLoss.validate(noB).S)[2].empty || ""), "empty category not explained");

  // ============================================================ part 2: the chart in jsdom
  let JSDOM, VirtualConsole;
  try { ({ JSDOM, VirtualConsole } = require("jsdom")); } catch { /* reported below */ }
  if (!JSDOM) { out.chart = out.page = "NOT RUN: jsdom is not installed (cd tests/web && npm install)"; fails.push(out.chart); }
  else {
    // 2a: model.html's own loss-surface code with the real common.js, on fixture presets (runs without an export)
    out.chart = "run"; await pageChecks(chartEnv(JSDOM, VirtualConsole), "chart");
    // 2b: the whole page with the real export, when there is one
    const need = ["modes.json", "models/ranked.json"].filter((f) => !fs.existsSync(path.join(WEB, f)));
    if (need.length) out.page = `NOT RUN: web/${need.join(", web/")} missing (run scripts/export_web.py first)`;
    else { out.page = "run"; await pageChecks(pageEnv(JSDOM, VirtualConsole), "page"); }
  }

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn, ms = 60000) => { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const read = (f) => fs.readFileSync(path.join(WEB, f), "utf8");
const ref = (snap, opts) => (opts.ref === undefined ? { file: "loss_surface.json", snapshot_id: snap && snap.snapshot_id } : opts.ref);
// fetch stub: loss_surface.json is the given file (404 when null), modes.json gets the matching reference, the rest from web/
function stub(w, snap, opts, fetched, INDEX) {
  w.fetch = async (u) => {
    const rel = String(u).replace(/^http:\/\/localhost\//, ""); fetched.push(rel);
    if (rel === "modes.json" && INDEX) { const j = JSON.parse(JSON.stringify(INDEX)); j.loss_surface = ref(snap, opts); return { ok: true, status: 200, json: async () => j }; }
    if (rel === "loss_surface.json") return snap ? { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(snap)) } : { ok: false, status: 404, json: async () => ({}) };
    const f = path.join(WEB, rel);
    if (!fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
    const txt = fs.readFileSync(f, "utf8"); return { ok: true, status: 200, json: async () => JSON.parse(txt) };
  };
  w.navigator.clipboard = { writeText: async () => {} };
  w.Element.prototype.scrollIntoView = function () {};
}
const ready = (d) => d.querySelector("#learn .formula") && d.querySelector("#catw") && !/Getting/.test(text(d.querySelector("#learn")));

// model.html's loss-surface section (from its "how the model learns" marker to the next section), run with the
// real engine.js, loss-surface.js and common.js; the three presets are fixture exact slices with their own J0
function chartEnv(JSDOM, VirtualConsole) {
  const html = read("model.html"), a = html.indexOf("// ------------------------------------------------------------------ how the model learns"), b = html.indexOf("// One story, in order");
  if (a < 0 || b < a) throw new Error("model.html: loss-surface section markers not found");
  const chunk = html.slice(a, b);
  const forms = [["26000000:base", "Knight", "base", "troop", 900], ["26000000:evo", "Knight", "evo", "troop", 400], ["28000000:base", "Fireball", "base", "spell", 800],
    ["27000000:base", "Cannon", "base", "building", 500], ["26000001:base", "Archers", "base", "troop", 700], ["28000001:base", "Arrows", "base", "spell", 650],
    ["27000006:base", "Tesla", "base", "building", 420], ["26000021:base", "Hog Rider", "base", "troop", 990], ["28000009:base", "Poison", "base", "spell", 610],
    ["26000010:base", "Skeletons", "base", "troop", 560], ["26000010:evo", "Skeletons", "evo", "troop", 210], ["27000003:base", "Inferno Tower", "base", "building", 330]];
  const pre = fixture(forms, 11).body; pre.J0 = 0.7012345678; pre.snapshot_id = "presets";
  const PS = CRLoss.validate(pre).S, labels = ["The two most-played card forms", "The two strongest common cards", "The two weakest common cards"];
  const slices = [[7, 8], [2, 6], [4, 5]].map(([i, j], k) => {
    const s = CRLoss.customSlice(PS, forms[i][0], forms[j][0]);
    for (const f of ["approximate", "fitted_grad", "half_width", "curvature"]) delete s[f];
    return Object.assign(s, { label: labels[k], se: [0.01, 0.012] });
  });
  const L = { slices }, name = new Map(forms.map((f) => [f[0], CRLoss.formLabel(f)]));
  const libs = ["engine.js", "loss-surface.js", "common.js"].map((f) => `<script>${read(f)}</script>`).join("");
  async function open(snap, opts = {}) {
    const errors = [], fetched = [];
    const vc = new VirtualConsole(); vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
    const page = `<!doctype html><html lang="en"><head><title>t</title></head><body><main><div id="learn"></div></main>${libs}
      <script>(() => { "use strict"; const { $, esc, pct, num, signed } = UI; const tx = (t, plain = t) => UI.tex(t, plain); const tn = UI.texNum;
      ${chunk}
      learn({ INDEX: window.__INDEX, E: window.__E }); })();</script></body></html>`;
    const dom = new JSDOM(page, { url: "http://localhost/model.html#ranked", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) {
        stub(w, snap, opts, fetched, null);
        w.__INDEX = { landscape: JSON.parse(JSON.stringify(L)), loss_surface: ref(snap, opts) };
        w.__E = { describe: (e) => name.get(`${e.id}:${e.form}`), m: { strength: { coef: new Array(190).fill(0) } } };
      } });
    const p = { w: dom.window, d: dom.window.document, errors, fetched };
    await until(() => ready(p.d), 10000);
    return p;
  }
  return { open, L, forms, fx: fixture(forms, 3).body, real: null };
}

// the whole model.html with the real export; the controlled file uses the Ranked model's own card forms and weights
function pageEnv(JSDOM, VirtualConsole) {
  const src = Object.fromEntries(["engine.js", "observed.js", "learn.js", "loss-surface.js", "common.js"].map((f) => [f, read(f)]));
  const INDEX = JSON.parse(read("modes.json")), ranked = JSON.parse(read("models/ranked.json"));
  const st = ranked.strength, card = new Map(ranked.cards.map((c) => [c.id, c]));
  const forms = st.keys.slice(0, st.n_card_features).map((k) => { const [id, f] = k.split(":"); const c = card.get(Number(id)); return [k, c.name, f, c.type, st.feature_games[k] || 0]; });
  const fx = fixture(forms, 3).body; fx.weights = st.coef.slice(0, st.n_card_features);
  async function open(snap, opts = {}) {
    const errors = [], fetched = [];
    const vc = new VirtualConsole(); vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
    let html = read("model.html");
    for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
    const dom = new JSDOM(html, { url: "http://localhost/model.html#ranked", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) { stub(w, snap, opts, fetched, INDEX); } });
    const p = { w: dom.window, d: dom.window.document, errors, fetched };
    await until(() => ready(p.d));
    return p;
  }
  return { open, L: INDEX.landscape, forms, fx, real: { ref: INDEX.loss_surface, nCard: st.n_card_features, keys: st.keys } };
}

async function pageChecks(env, tag) {
  const { open, L, forms, fx } = env;
  const expect = (c, m) => { if (!c) fails.push(`${tag}: ${m}`); };
  const pill = (d, k = 0) => text(d.querySelector(`.lspanel[data-panel="${k}"] .pill`));
  const sel = (d, k, ax) => d.querySelector(`select[data-panel="${k}"][data-axis="${ax}"]`);
  const pick = async (p, k, ax, key) => { const s = sel(p.d, k, ax); s.value = key; s.dispatchEvent(new p.w.Event("change", { bubbles: true })); await wait(30); };
  const fittedTip = (d, k) => [...d.querySelectorAll(`#surf${k} circle[data-tip]`)].map((c) => c.outerHTML).find((h) => /fitted weights/.test(h)) || "";
  const clean = (name, p) => {
    const v = p.d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove());
    expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(v.textContent) && !v.textContent.includes("—"), `${name}: broken value or em dash in text`);
    expect(![...p.d.querySelectorAll("#learn svg")].some((s) => /NaN|undefined|Infinity/.test(s.outerHTML)), `${name}: broken value in the chart`);
    expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
  };

  let p = await open(fx), d = p.d;
  const keys = forms.map((f) => f[0]);
  // selectors: exactly the fitted Ranked forms, readable, the other axis's form disabled
  const optKeys = (s) => [...s.options].map((o) => o.value).sort().join();
  expect(sel(d, 0, "a") && optKeys(sel(d, 0, "a")) === keys.slice().sort().join() && optKeys(sel(d, 0, "b")) === keys.slice().sort().join(), "page: selectors don't list exactly the fitted forms");
  expect([...sel(d, 0, "a").options].every((o) => o.textContent.trim().length > 0 && !/^\d+:/.test(o.textContent.trim())), "page: selector labels are raw keys");
  // default: preset 1, exact, its exported numbers
  expect(pill(d) === "Exact slice" && sel(d, 0, "a").value === L.slices[0].keys[0] && sel(d, 0, "b").value === L.slices[0].keys[1], "page: default isn't the first exact slice");
  expect(fittedTip(d, 0).includes(`J ${L.slices[0].fitted_loss.toFixed(6)}`), "page: exact slice not drawn from its exported data");
  const dis = [...sel(d, 0, "a").options].filter((o) => o.disabled).map((o) => o.value);
  expect(dis.length === 1 && dis[0] === sel(d, 0, "b").value, "page: the b form isn't disabled on the a axis");
  // three numeric ticks per axis, plain names, lower is better
  const ticksOf = (k, ax) => [...d.querySelectorAll(`#surf${k} [data-axis-tick="${ax}"]`)].map(text);
  // the default is the flat map: a and b on real axes with numbers, words for the dot and the path's start
  expect(/^Flat map/.test(d.querySelector("#surf0").getAttribute("aria-label")) && d.querySelector("#surfview").getAttribute("aria-pressed") === "false" && !d.querySelector("#surfreset"), "page: the flat map isn't the default view");
  for (const ax of ["a", "b"]) { const t = ticksOf(0, ax); expect(t.length >= 3 && new Set(t).size === t.length && t.every((x) => /^−?\d/.test(x)), `page: ${ax} ticks ${t}`); }
  const svg0 = d.querySelector("#surf0 svg");
  expect(/a\s*[:=] weight of/.test(text(svg0)) && /b\s*[:=] weight of/.test(text(svg0)) && /training loss/.test(text(svg0)) && /lower is better/.test(text(svg0)), "page: axis names not in plain words");
  expect(/end of training \(lowest point\)/.test(text(svg0)) && /start \(example\)/.test(text(svg0)) && !/f\(a, b\)/.test(text(d.querySelector("#learn"))), "page: the dot and the path's start aren't named in words");
  const bar = [...d.querySelectorAll("#learn .scale-bar span")].map(text);
  expect(bar[0] === "+0.00000" && /^\+0\.000\d\d$/.test(bar[1]), `page: colour bar not on the 'above the lowest point' scale: ${bar}`);
  out[`${tag}Ticks`] = { a: ticksOf(0, "a"), b: ticksOf(0, "b") };
  // 3D: only the loss axis has numbers, on the colour bar's scale; a and b ranges sit in the corner key
  d.querySelector("#surfview").click(); await wait(20);
  const tJ = ticksOf(0, "J");
  expect(/^3D/.test(d.querySelector("#surf0").getAttribute("aria-label")) && tJ.length >= 3 && new Set(tJ).size === tJ.length && tJ.every((x) => /^\+\d/.test(x)) && !ticksOf(0, "a").length && !ticksOf(0, "b").length, `page: 3D ticks J ${tJ}, a ${ticksOf(0, "a")}`);
  expect(/a = weight of .+, [+−]\d.* to [+−]\d/.test(text(d.querySelector("#surf0 svg"))) && /end of training \(lowest point\)/.test(text(d.querySelector("#surf0 svg"))), "page: 3D corner key has no ranges, or the dot isn't named");
  expect(!!d.querySelector("#surfreset") && !!d.querySelector("#surfrotate"), "page: 3D has no Reset view or Rotate");
  d.querySelector("#surfview").click(); await wait(20);
  out[`${tag}Ticks`].J = tJ;
  // a pair no preset uses: approximate, from the quadratic, labelled
  const presetKeys = new Set(L.slices.flatMap((s) => s.keys));
  const free = keys.filter((x) => !presetKeys.has(x));
  await pick(p, 0, "a", free[0]); await pick(p, 0, "b", free[1]);
  const lt = text(d.querySelector("#learn"));
  expect(pill(d) === "Approximate" && /local quadratic/.test(lt) && /every other weight fixed/.test(lt) && /illustration/.test(lt), "page: custom pair not labelled approximate");
  const S = CRLoss.validate(fx).S, B = CRLoss.pairBlock(S, free[0], free[1]);
  expect(fittedTip(d, 0).includes(`J ${fx.J0.toFixed(6)}`) && /approximate surface/.test(fittedTip(d, 0)), "page: custom fitted point not J0 from the file");
  const cells = [...d.querySelectorAll("#surf0 path[data-tip]")], marks = [...d.querySelectorAll("#surf0 circle[data-tip]")];
  expect(cells.length > 100 && cells.every((c) => !c.hasAttribute("tabindex")) && marks.length > 0 && marks.every((c) => c.getAttribute("tabindex") === "0"), "page: custom surface cells are Tab stops, or its marks aren't");
  expect(B.haa > 0, "page: pair block");
  // choosing a preset's own pair from the selectors gives back the exact surface
  await pick(p, 0, "a", L.slices[2].keys[0]); await pick(p, 0, "b", L.slices[2].keys[1]);
  expect(pill(d) === "Exact slice" && fittedTip(d, 0).includes(`J ${L.slices[2].fitted_loss.toFixed(6)}`), "page: a preset pair chosen by hand isn't its exact surface");
  // the same form on both axes is refused
  const before = [sel(d, 0, "a").value, sel(d, 0, "b").value];
  await pick(p, 0, "a", before[1]);
  expect(sel(d, 0, "a").value === before[0] && /can't be on both axes/.test(text(d.querySelector("#surfmsg"))), "page: identical forms accepted");
  // two forms of one card
  const byId = {}; keys.forEach((x) => { (byId[x.split(":")[0]] = byId[x.split(":")[0]] || []).push(x); });
  const two = Object.values(byId).find((v) => v.length > 1);
  if (two) { await pick(p, 0, "a", two[0]); await pick(p, 0, "b", two[1]); expect(sel(d, 0, "a").value === two[0] && sel(d, 0, "b").value === two[1] && d.querySelector("#surf0 svg"), "page: two forms of one card can't be compared"); }
  out[`${tag}TwoForms`] = two || null;
  // category weights: below the chart, inside its frame, every form once with its weight and type
  const frame = d.querySelector("#surf0").closest(".panel"), lis = [...d.querySelectorAll("#catw .catlist li")];
  expect(frame && frame.contains(d.querySelector("#catw")), "page: category weights not inside the chart frame");
  expect(lis.length === keys.length && new Set(lis.map((li) => li.dataset.key)).size === keys.length, "page: category list doesn't list each form once");
  const fi = new Map(forms.map((f, i) => [f[0], [f[3], fx.weights[i]]]));
  expect(lis.every((li) => li.closest(".catlist").dataset.cat === fi.get(li.dataset.key)[0] && text(li.querySelector(".w")) === p.w.UI.signed(fi.get(li.dataset.key)[1], 4)), "page: category or weight wrong");
  expect(["Troops", "Spells", "Buildings"].every((t) => text(d.querySelector("#catw")).includes(t)), "page: category headings");
  // compare: two independent pairs, one shared view, scale disclosure
  await pick(p, 0, "a", free[0]); await pick(p, 0, "b", free[1]);
  d.querySelector("#surfcmp").click(); await wait(30);
  expect(d.querySelectorAll(".cmpgrid .lspanel").length === 2 && d.querySelector("#surf1 svg") && d.querySelector("#surfcmp").getAttribute("aria-pressed") === "true", "page: compare doesn't show two panels");
  expect(/share one viewing angle/.test(text(d.querySelector("#learn"))) && /own loss range/.test(text(d.querySelector("#learn"))), "page: compare doesn't disclose the shared view and separate scales");
  const p1 = [sel(d, 0, "a").value, sel(d, 0, "b").value];
  expect(p1.join() === `${free[0]},${free[1]}` && sel(d, 1, "a").value + sel(d, 1, "b").value !== p1.join(""), "page: pair 2 starts as pair 1");
  await pick(p, 1, "b", free[2] === sel(d, 1, "a").value ? free[3] : free[2]);
  expect([sel(d, 0, "a").value, sel(d, 0, "b").value].join() === p1.join() && pill(d, 1) === "Approximate" && pill(d, 0) === "Approximate", "page: changing pair 2 changed pair 1");
  d.querySelector("#surfview").click(); await wait(20);   // rotation is a 3D thing
  const svgs = () => [0, 1].map((k2) => d.querySelector(`#surf${k2} svg`).innerHTML);
  const s0 = svgs();
  d.querySelector("#surf1").dispatchEvent(new p.w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); await wait(20);
  const s1 = svgs();
  expect(s1[0] !== s0[0] && s1[1] !== s0[1], "page: rotating one panel doesn't turn both");
  d.querySelector("#surfreset").click(); await wait(20);
  expect(svgs().join() === s0.join(), "page: Reset view doesn't reset both panels");
  d.querySelector('[data-panel="1"][data-slice="1"]').click(); await wait(30);
  expect(pill(d, 1) === "Exact slice" && pill(d, 0) === "Approximate" && fittedTip(d, 1).includes(`J ${L.slices[1].fitted_loss.toFixed(6)}`), "page: preset in pair 2 not exact, or pair 1 lost");
  expect([...d.querySelectorAll(`#surf1 [data-axis-tick="J"]`)].length >= 3, "page: pair 2 has no J ticks in 3D");
  d.querySelector("#surfview").click(); await wait(20);
  for (const ax of ["a", "b"]) expect([...d.querySelectorAll(`#surf1 [data-axis-tick="${ax}"]`)].length >= 3, `page: pair 2 has no ${ax} ticks on the flat map`);
  expect(p.fetched.filter((f) => f === "loss_surface.json").length === 1, `page: approximation file fetched ${p.fetched.filter((f) => f === "loss_surface.json").length} times`);
  clean("page", p);

  // the real exported file, when there is one (whole-page run only)
  const realF = path.join(WEB, "loss_surface.json");
  if (env.real && env.real.ref && fs.existsSync(realF)) {
    const st = env.real, real = JSON.parse(fs.readFileSync(realF, "utf8")), v = CRLoss.validate(real, st.ref);
    out.realFile = { bytes: fs.statSync(realF).size, forms: real.forms.length, ok: v.ok, reason: v.reason };
    expect(v.ok && fs.statSync(realF).size < 500000 && real.forms.length === st.nCard, `real file: ${v.reason || "too big or wrong size"}`);
    expect(real.forms.every((f, i) => f[0] === st.keys[i]), "real file: forms not the Ranked model's card forms in order");
    const q = await open(real, { ref: st.ref });
    expect(sel(q.d, 0, "a") && q.d.querySelectorAll("#catw .catlist li").length === real.forms.length, "real file: page didn't use it");
    clean("real file", q);
  } else if (env.real) out.realFile = "not exported yet";

  // missing, malformed, non-number and incompatible files: custom pairs unavailable, presets still work
  const variants = {
    missing: [null, {}], none: [fx, { ref: null }],
    malformed: [Object.assign(JSON.parse(JSON.stringify(fx)), { h_packed: fx.h_packed.slice(1) }), {}],
    nonnumber: [Object.assign(JSON.parse(JSON.stringify(fx)), { g: fx.g.map((x, i) => (i === 3 ? null : x)) }), {}],
    incompatible: [fx, { ref: { file: "loss_surface.json", snapshot_id: "another-export" } }],
  };
  const un = out[`${tag}Unavailable`] = {};
  for (const [name, [snap, opts]] of Object.entries(variants)) {
    const q = await open(snap, opts), qd = q.d;
    un[name] = text(qd.querySelector(".lspanel p.muted"));
    expect(!sel(qd, 0, "a") && /unavailable/.test(text(qd.querySelector("#learn"))) && /Not available/.test(text(qd.querySelector("#catw"))), `${name}: no unavailable state`);
    qd.querySelector('[data-panel="0"][data-slice="2"]').click(); await wait(30);
    expect(pill(qd) === "Exact slice" && qd.querySelector('[data-slice="2"]').getAttribute("aria-pressed") === "true" && fittedTip(qd, 0).includes(`J ${L.slices[2].fitted_loss.toFixed(6)}`), `${name}: exact presets broken`);
    qd.querySelector("#surfcmp").click(); await wait(30);
    expect(qd.querySelectorAll(".cmpgrid .lspanel").length === 2, `${name}: compare broken without the file`);
    clean(name, q);
  }
}

main().catch((e) => { out.fails = fails; console.log(JSON.stringify(out, null, 1)); console.error(e); process.exit(2); });
