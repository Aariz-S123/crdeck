// The runs chart on the Future meta page (web/runs-chart.js). Expected values are read from web/future_paths.json and
// web/future_meta.json here, not from the page's own helpers.
//   cd tests/web && node runs_chart_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "learn.js", "common.js", "futures-explorer.js", "runs-chart.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const F = JSON.parse(fs.readFileSync(path.join(WEB, "future_meta.json"), "utf8"));
const P = JSON.parse(fs.readFileSync(path.join(WEB, "future_paths.json"), "utf8"));
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

async function open(opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, "future.html"), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const dom = new JSDOM(html, {
    url: "http://localhost/future.html", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        if ((opts.missing || []).includes(rel) || !fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (rel === "future_paths.json" && opts.paths) j = opts.paths(j);
        return { ok: true, status: 200, json: async () => j };
      };
      w.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
      w.Element.prototype.scrollIntoView = function () {};
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 60000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const fire = (w, el, type) => el.dispatchEvent(new w.Event(type, { bubbles: true }));

(async () => {
  // ---- the two files describe the same forecast
  expect(P.written_at === F.written_at, `future_paths.json (${P.written_at}) and future_meta.json (${F.written_at}) are from different runs`);
  expect(P.runs === F.settings.runs && P.shown > 0 && P.shown <= P.runs, "run counts don't match the settings");
  for (const fam of ["cards", "styles"]) {
    const keys = F.forecast[fam].series.map((s) => s.key);
    expect(JSON.stringify(P[fam].keys) === JSON.stringify(keys), `${fam}: the saved runs are not the forecast series, in order`);
    const steps = F.forecast[fam].steps.length;
    expect(P[fam].runs.every((r) => r.length === steps && r.every((s) => s.length === P.shown && s.every(Number.isInteger))), `${fam}: wrong shape`);
    // a fixed sample of the runs: about nine in ten of its values should sit inside the 90% ranges that count every run
    let inside = 0, total = 0;
    F.forecast[fam].series.forEach((s, k) => s.band90.forEach((b, j) => P[fam].runs[k][j].forEach((v) => { total++; if (v * P.unit >= b[0] - P.unit && v * P.unit <= b[1] + P.unit) inside++; })));
    out[`${fam}_inside_90`] = +(inside / total).toFixed(4);
    expect(inside / total > 0.86 && inside / total < 0.94, `${fam}: ${pct(inside / total)} of the saved runs sit inside the 90% ranges`);
  }

  // ---- the chart
  let p = await open(), d = p.d;
  expect(await until(() => d.querySelector("#runs-lines .run")), "the runs were never drawn");
  const heads = [...d.querySelectorAll("#body section h2")].map(text);
  const section = [...d.querySelectorAll("#body section")][heads.indexOf("What may be played next")];
  expect(section && section.querySelector("#runs"), "the runs chart is not in the forecast section");
  const top = F.forecast.cards.series.slice().sort((a, b) => b.no_change - a.no_change)[0];
  const sel = d.querySelector("#runs-series");
  expect(sel.value === `cards:${top.key}`, "doesn't start on the most used card");
  expect(sel.querySelectorAll("optgroup").length === 2 && sel.querySelectorAll("option").length === F.forecast.cards.series.length + F.forecast.styles.series.length, "the picker doesn't list every forecast card and style");
  const runsOf = (fam, key) => P[fam].runs[P[fam].keys.indexOf(key)].map((s) => s.map((v) => v * P.unit));
  const drawn = () => [...d.querySelectorAll("#runs-lines .run")];
  const check = (fam, s, label) => {
    const runs = runsOf(fam, s.key);
    expect(drawn().length === P.shown, `${label}: ${drawn().length} lines for ${P.shown} runs`);
    expect(drawn().every((l) => l.style.display !== "none" && !/NaN|undefined/.test(l.getAttribute("d"))), `${label}: a run line is hidden or broken`);
    const stats = [...d.querySelectorAll("#runs-stats .nums3 > div")].map(text);
    expect(stats.length === s.median.length, `${label}: one summary per step`);
    s.median.forEach((m, j) => {
      const up = runs[j].filter((v) => v > s.no_change).length;
      expect(stats[j].startsWith(pct(m)) && stats[j].includes(`${pct(s.band90[j][0])} to ${pct(s.band90[j][1])}`), `${label} step ${j + 1}: summary doesn't match the export: ${stats[j]}`);
      expect(stats[j].includes(`${up} of the ${P.shown} drawn end above the latest share (${pct(s.no_change)})`), `${label} step ${j + 1}: count above the latest share is not ${up}: ${stats[j]}`);
    });
    const rows = [...d.querySelectorAll("#runs-table tbody tr")].map((r) => [...r.children].map(text));
    expect(rows.length === s.median.length, `${label}: table rows`);
    rows.forEach((r, j) => {
      expect(r[1] === pct(s.timesfm_median[j], 2) && r[2] === pct(s.median[j], 2) && r[3] === `${pct(s.band50[j][0], 2)} to ${pct(s.band50[j][1], 2)}`, `${label}: table row ${j + 1} is ${r}`);
      expect(r[5] === `${pct(Math.min(...runs[j]), 2)} to ${pct(Math.max(...runs[j]), 2)}`, `${label}: lowest and highest drawn run in row ${j + 1}: ${r[5]}`);
    });
    return runs;
  };
  const runs = check("cards", top, "top card");
  out.card = text(d.querySelector("#runs-intro b"));
  expect(text(d.querySelector("#runs-intro")).includes(`${P.shown} of the ${P.runs.toLocaleString()} runs`), "the intro doesn't say how many runs are drawn");
  expect(text(d.querySelector("#runs-note")).includes("unrelated draws"), "the note doesn't say each step is drawn separately");

  // ---- following one run reads that run's own numbers
  const trace = d.querySelector("#runs-trace");
  expect(Number(trace.max) === P.shown && text(d.querySelector("#runs-trace-out")) === "none" && !d.querySelector("#runs-one").children.length, "the slider doesn't start on no run");
  trace.value = "37"; fire(p.w, trace, "input");
  const want = `Run 37 of ${P.runs.toLocaleString()}: ${runs.map((s, j) => `${pct(s[36], 2)} after ${F.settings.hours_per_step * (j + 1)} hours`).join(", ")}.`;
  out.followed = text(d.querySelector("#runs-read"));
  expect(out.followed === want, `followed run reads "${out.followed}", expected "${want}"`);
  expect(d.querySelectorAll("#runs-one path").length === 2 && d.querySelectorAll("#runs-one circle").length === runs.length && text(d.querySelector("#runs-trace-out")) === "run 37", "the followed run isn't drawn on top");
  trace.value = "0"; fire(p.w, trace, "input");
  expect(!d.querySelector("#runs-one").children.length && text(d.querySelector("#runs-read")).startsWith("Point at a line"), "letting go doesn't clear the followed run");

  // ---- the two switches redraw without the ranges or TimesFM's line, and the runs stay
  const paths = () => d.querySelectorAll("#runs-stage svg > path").length;
  const before = paths();
  const bands = d.querySelector('[data-runs-toggle="bands"]'), tfm = d.querySelector('[data-runs-toggle="tfm"]');
  bands.click();
  expect(bands.getAttribute("aria-pressed") === "false" && paths() === before - 2, "the ranges switch doesn't remove the two ranges");
  tfm.click();
  expect(tfm.getAttribute("aria-pressed") === "false" && paths() === before - 3 - top.median.length, "the TimesFM switch doesn't remove its line and markers");
  expect(drawn().length === P.shown, "the switches lost the runs");
  bands.click(); tfm.click();
  expect(paths() === before, "switching both back doesn't restore the chart");

  // ---- a deck style, then replaying
  const style = F.forecast.styles.series.slice().sort((a, b) => b.no_change - a.no_change)[0];
  sel.value = `styles:${style.key}`; fire(p.w, sel, "change");
  await until(() => drawn().every((l) => l.style.display !== "none"), 8000);
  check("styles", style, "top style");
  out.style = text(d.querySelector("#runs-intro b"));
  expect(out.style && out.style !== out.card, "the picker didn't switch to the style");
  d.querySelector("#runs-play").click();
  expect(drawn().some((l) => l.style.display === "none"), "replay doesn't start from an empty chart");
  expect(await until(() => drawn().every((l) => l.style.display !== "none"), 8000), "replay never finished drawing the runs");
  expect(!p.errors.length, `script errors: ${p.errors.join(" | ").slice(0, 400)}`);

  // ---- without the file, or with a file from another run, the page says so and the rest still works
  p = await open({ missing: ["future_paths.json"] }); d = p.d;
  expect(await until(() => d.querySelector("#runs .notice")), "no notice when future_paths.json is missing");
  expect(text(d.querySelector("#runs .notice")).includes("future_paths.json") && d.querySelector("#runs .controls").hidden && d.querySelector("#fans .mcell") && !p.errors.length, "missing file: notice, hidden controls and the rest of the page");
  p = await open({ paths: (j) => ({ ...j, written_at: "2000-01-01 00:00 UTC" }) }); d = p.d;
  expect(await until(() => d.querySelector("#runs .notice")), "no notice when the runs are from another forecast");
  expect(text(d.querySelector("#runs .notice")).includes("different forecast") && !d.querySelector("#runs-lines") && !p.errors.length, "stale file: the runs must not be drawn");

  console.log(JSON.stringify({ ok: !fails.length, fails, out }, null, 1));
  process.exit(fails.length ? 1 : 0);
})();
