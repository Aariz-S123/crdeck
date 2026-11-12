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
  // it starts on the card whose drawn runs agree most about the direction at the last step; ties go to the more used card
  const runsOf = (fam, key) => P[fam].runs[P[fam].keys.indexOf(key)].map((s) => s.map((v) => v * P.unit));
  const ends = (fam, s) => { const e = runsOf(fam, s.key).pop(); return [e.filter((v) => v > s.no_change).length, e.filter((v) => v < s.no_change).length]; };
  let top = null, lean = -1;
  F.forecast.cards.series.slice().sort((a, b) => b.no_change - a.no_change).forEach((s) => { const [u, l] = ends("cards", s); if (Math.abs(u - l) > lean) { lean = Math.abs(u - l); top = s; } });
  const sel = d.querySelector("#runs-series");
  expect(sel.value === `cards:${top.key}`, `starts on ${sel.value}, not on the card with the most one-sided runs (${top.key})`);
  expect(sel.querySelectorAll("optgroup").length === 2 && sel.querySelectorAll("option").length === F.forecast.cards.series.length + F.forecast.styles.series.length, "the picker doesn't list every forecast card and style");
  const drawn = () => [...d.querySelectorAll("#runs-lines .run")];
  const check = (fam, s, label) => {
    const runs = runsOf(fam, s.key);
    expect(drawn().length === P.shown, `${label}: ${drawn().length} lines for ${P.shown} runs`);
    expect(drawn().every((l) => l.style.display !== "none" && !/NaN|undefined/.test(l.getAttribute("d"))), `${label}: a run line is hidden or broken`);
    // the answer leads: the counts of drawn runs ending above and below the share now, in words, colors and on the chart
    const [up, down] = ends(fam, s), share = up / (up + down), take = text(d.querySelector("#runs-take")), last = s.band90[s.band90.length - 1];
    const words = share >= 0.9 ? "very likely to be played more" : share >= 0.7 ? "more likely to be played more than less" : share <= 0.1 ? "very likely to be played less" : share <= 0.3 ? "more likely to be played less than more" : "could go either way";
    expect(text(d.querySelector(".runs-verdict")).endsWith(`: ${words}`), `${label}: verdict "${text(d.querySelector(".runs-verdict"))}" for ${up} up and ${down} down`);
    expect(take.includes(`${up} end higher and ${down} end lower`) && take.includes(`in ${pct(s.no_change)} of Ranked decks now`) && take.includes(`between ${pct(last[0])} and ${pct(last[1])}`), `${label}: the takeaway doesn't match the files: ${take}`);
    expect(d.querySelectorAll("#runs-lines .run.up").length === up && d.querySelectorAll("#runs-lines .run.down").length === down, `${label}: line colors don't match ${up} up and ${down} down`);
    expect(text(d.querySelector(".runs-count.up")) === `${up} end above ${pct(s.no_change)}` && text(d.querySelector(".runs-count.down")) === `${down} end below`, `${label}: the counts on the chart`);
    out[label] = text(d.querySelector(".runs-verdict"));
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
  const runs = check("cards", top, "first card");
  out.card = text(d.querySelector(".runs-verdict"));
  expect(text(d.querySelector("#runs h3")).startsWith("Will it be played more or less?"), "the chart doesn't open with its question");
  expect(text(d.querySelector("#runs-intro")).startsWith("Why this chart is here:") && text(d.querySelector("#runs-take")).includes(`Of the ${P.shown} possible futures drawn here`), "the chart doesn't say why it is there or how many runs are drawn");
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
  out.style = text(d.querySelector(".runs-verdict"));
  expect(out.style && out.style !== out.card, "the picker didn't switch to the style");
  d.querySelector("#runs-play").click();
  expect(drawn().some((l) => l.style.display === "none"), "replay doesn't start from an empty chart");
  expect(await until(() => drawn().every((l) => l.style.display !== "none"), 8000), "replay never finished drawing the runs");

  // ---- comparing cards: the same runs read across cards. Correlations are recomputed here from the file.
  const pearson = (a, b) => { const m = (v) => v.reduce((t, x) => t + x, 0) / v.length, ma = m(a), mb = m(b); let ab = 0, aa = 0, bb = 0; a.forEach((x, i) => { ab += (x - ma) * (b[i] - mb); aa += (x - ma) ** 2; bb += (b[i] - mb) ** 2; }); return ab / Math.sqrt(aa * bb); };
  const med = (v) => { const t = v.slice().sort((x, y) => x - y), h = t.length >> 1; return t.length % 2 ? t[h] : (t[h - 1] + t[h]) / 2; };
  const sameSide = (a, b) => { const ma = med(a), mb = med(b); return [a.filter((x, i) => (x - ma) * (b[i] - mb) > 0).length, a.filter((x, i) => (x - ma) * (b[i] - mb) < 0).length]; };
  const sgn = (r) => `${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}`;
  const limit = 1.96 / Math.sqrt(P.shown - 3);
  const wordsFor = (r) => (Math.abs(r) < limit ? "no clear link" : r > 0 ? (Math.abs(r) >= 0.5 ? "move together" : "lean together") : (Math.abs(r) >= 0.5 ? "move opposite ways" : "lean opposite ways"));
  d.querySelector('[data-runs-mode="compare"]').click();
  expect(text(d.querySelector("#runs-h")) === "Do these cards rise and fall together?" && d.querySelector("#runs-c-one").hidden && !d.querySelector("#runs-c-cmp").hidden && !d.querySelector("#runs-pairs").hidden && d.querySelector("#runs-stats").hidden, "compare mode doesn't swap the controls and the question");
  const chosen = () => [...d.querySelectorAll("[data-runs-remove]")].map((b) => b.dataset.runsRemove);
  // it opens on the most strongly linked pair among the 40 most used cards, one step ahead, plus the card most against the first
  const pool = F.forecast.cards.series.slice().sort((a, b) => b.no_change - a.no_change).slice(0, 40).map((s) => ({ key: s.key, v: runsOf("cards", s.key)[0] }));
  let bi = 0, bj = 1, strongest = -1;
  for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) { const r = Math.abs(pearson(pool[i].v, pool[j].v)); if (r > strongest) { strongest = r; bi = i; bj = j; } }
  let against = -1, lowest = Infinity;
  pool.forEach((q, k) => { if (k === bi || k === bj) return; const r = pearson(pool[bi].v, q.v); if (r < lowest) { lowest = r; against = k; } });
  expect(JSON.stringify(chosen()) === JSON.stringify([pool[bi].key, pool[bj].key, pool[against].key]), `compare opens on ${chosen()}`);
  const pickNames = () => [...d.querySelectorAll("[data-runs-remove]")].map((b) => text(b).replace(/ ×$/, ""));
  out.compare_opens_on = pickNames();
  out.compare_strongest = +strongest.toFixed(3); out.compare_against = +lowest.toFixed(3);
  const checkCompare = (label, step) => {
    const keys = chosen(), at = keys.map((k) => runsOf("cards", k)[step]), k = keys.length;
    expect(drawn().length === k * Math.min(60, P.shown) && drawn().every((l) => !/NaN|undefined/.test(l.getAttribute("d"))), `${label}: ${drawn().length} lines for ${k} cards`);
    expect(d.querySelectorAll("#runs-pairs .runs-dots").length === k * (k - 1) / 2 && [...d.querySelectorAll("#runs-pairs .runs-dots")].every((g) => g.children.length === P.shown), `${label}: the grid doesn't hold one dot per run for every pair`);
    const rows = [...d.querySelectorAll("#runs-table tbody tr")].map((r) => [...r.children].map(text));
    const want = [];
    for (let i = 0; i < k; i++) for (let j = i + 1; j < k; j++) { const r = pearson(at[i], at[j]), [same, opp] = sameSide(at[i], at[j]); want.push([sgn(r), `${same} of ${P.shown}`, `${opp} of ${P.shown}`, wordsFor(r), r, same, opp]); }
    expect(rows.length === want.length && rows.every((r, n) => r[1] === want[n][0] && r[2] === want[n][1] && r[3] === want[n][2] && r[4] === want[n][3]), `${label}: the pair table doesn't match the file: ${JSON.stringify(rows)} against ${JSON.stringify(want.map((w) => w.slice(0, 4)))}`);
    expect(JSON.stringify([...d.querySelectorAll("#runs-pairs .runs-r")].map(text)) === JSON.stringify(want.map((w) => w[0])), `${label}: the grid's correlations don't match the table`);
    const lead = want.slice().sort((a, b) => Math.abs(b[4]) - Math.abs(a[4]))[0], take = text(d.querySelector("#runs-take"));
    expect(take.includes(`correlation ${lead[0]}`) && take.includes(`In ${lead[4] >= 0 ? lead[5] : lead[6]} of the ${P.shown} futures drawn here`) && take.includes(`${F.settings.hours_per_step * (step + 1)} hours ahead`), `${label}: the takeaway doesn't lead with the strongest pair: ${take}`);
    expect(Math.abs(lead[4]) < limit ? take.startsWith("No clear link") : lead[4] > 0 ? /rise and fall together/.test(take) : /played less/.test(take), `${label}: the takeaway's direction is wrong: ${take}`);
    return { keys, at };
  };
  const cmp = checkCompare("compare, opening", 0);
  out.compare_take = text(d.querySelector(".runs-verdict"));
  expect(text(d.querySelector("#runs-note")).includes(limit.toFixed(2)) && text(d.querySelector("#runs-intro")).includes("doesn't show that one card causes"), "compare mode doesn't state its limits");
  // following one run reads the same future across every card and rings it in each scatter
  trace.value = "12"; fire(p.w, trace, "input");
  const names = pickNames();
  const wantRun = `Run 12 of ${P.runs.toLocaleString()}, ${F.settings.hours_per_step} hours ahead: ${cmp.at.map((v, n) => `${names[n]} ${pct(v[11], 2)}`).join(", ")}. The ringed dots in the grid are this same future.`;
  expect(text(d.querySelector("#runs-read")) === wantRun, `compare, followed run reads "${text(d.querySelector("#runs-read"))}", expected "${wantRun}"`);
  expect(d.querySelectorAll("#runs-pairs .runs-dot-one circle").length === 3 && d.querySelectorAll("#runs-one path").length === 2 * cmp.keys.length, "compare: the followed run isn't marked on the lines and in every scatter");
  trace.value = "0"; fire(p.w, trace, "input");
  // another step, a fourth card, then removing cards down to two
  d.querySelector('[data-runs-step="2"]').click();
  checkCompare("compare, last step", 2);
  expect(!d.querySelector("#runs-add").disabled && d.querySelectorAll("#runs-add option").length === F.forecast.cards.series.length - 3 + 1, "the add list should hold every card not yet compared");
  const extra = F.forecast.cards.series.slice().sort((a, b) => b.no_change - a.no_change).find((s) => !chosen().includes(s.key));
  d.querySelector("#runs-add").value = extra.key; fire(p.w, d.querySelector("#runs-add"), "change");
  expect(chosen().length === 4 && chosen()[3] === extra.key && d.querySelector("#runs-add").disabled, "adding a fourth card, the most allowed");
  checkCompare("compare, four cards", 2);
  d.querySelector(`[data-runs-remove="${chosen()[0]}"]`).click();
  d.querySelector(`[data-runs-remove="${chosen()[0]}"]`).click();
  expect(chosen().length === 2 && [...d.querySelectorAll("[data-runs-remove]")].every((b) => b.disabled), "removing down to two cards, which then can't be removed");
  checkCompare("compare, two cards", 2);
  d.querySelector('[data-runs-mode="one"]').click();
  expect(text(d.querySelector("#runs-h")).startsWith("Will it be played more or less?") && d.querySelector("#runs-pairs").hidden && drawn().length === P.shown && d.querySelector(".runs-count.up"), "going back to one card doesn't restore it");
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
