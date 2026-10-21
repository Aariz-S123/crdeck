// Site-wide bug hunt: every exported mode on Build, Why this deck, All cards and How it works, plus
// bad and edge-case links: script errors, broken numbers, em dashes, duplicate ids, unnamed
// controls and links to missing files. Takes about 15 minutes.
//   cd tests/web && npm install && node site_check.cjs
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const engine = fs.readFileSync(path.join(WEB, "engine.js"), "utf8");
const common = fs.readFileSync(path.join(WEB, "common.js"), "utf8");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const problems = [];
const bad = (m) => { problems.push(m); console.log("PROBLEM", m); };
const PAGES = ["index.html", "reason.html", "cards.html", "meta.html", "seasons.html", "model.html"];

async function open(page, hash = "") {
  const errors = [], logs = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.message || e))));
  vc.on("error", (e) => errors.push(String(e)));
  vc.on("warn", (e) => logs.push("warn " + e));
  let html = fs.readFileSync(path.join(WEB, page), "utf8")
    .replace('<script src="engine.js"></script>', () => `<script>${engine}</script>`)
    .replace('<script src="common.js"></script>', () => `<script>${common}</script>`);
  if (!/^<!doctype/i.test(html)) html = `<!doctype html><html><head></head><body>${html}</body></html>`;
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const f = path.join(WEB, String(u).replace(/^http:\/\/localhost\//, ""));
        if (!fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        const txt = fs.readFileSync(f, "utf8");
        return { ok: true, status: 200, json: async () => JSON.parse(txt) };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.Element.prototype.scrollIntoView = function () {};
    },
  });
  return { w: dom.window, d: dom.window.document, errors, logs, close: () => dom.window.close() };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 100; t++) { if (fn()) return true; await wait(100); } return false; }
function visibleText(d) { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent; }
function sanity(label, p) {
  const d = p.d, text = visibleText(d);
  if (p.errors.length) bad(`${label}: script errors: ${p.errors.slice(0, 2).join(" | ").slice(0, 300)}`);
  if (/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(text)) bad(`${label}: broken value in text: ${(text.match(/.{0,40}(NaN|undefined|\[object Object\]|Infinity).{0,40}/) || [""])[0]}`);
  if ([...d.querySelectorAll("svg")].some((s) => /NaN|undefined|Infinity/.test(s.outerHTML))) bad(`${label}: broken value in a chart`);
  if (text.includes("—")) bad(`${label}: em dash in text`);
  if (d.querySelectorAll("h1").length !== 1) bad(`${label}: ${d.querySelectorAll("h1").length} h1`);
  const ids = [...d.querySelectorAll("[id]")].map((e) => e.id), dup = ids.filter((x, i) => ids.indexOf(x) !== i);
  if (dup.length) bad(`${label}: duplicate ids ${[...new Set(dup)].join(",")}`);
  // links to other pages must exist
  for (const a of d.querySelectorAll("a[href]")) {
    const h = a.getAttribute("href");
    if (/^(https?:|mailto:|#)/.test(h)) continue;
    const file = h.split("#")[0];
    if (file && !fs.existsSync(path.join(WEB, file))) bad(`${label}: link to missing file ${h}`);
  }
  // buttons and form controls need an accessible name
  for (const b of d.querySelectorAll("button, select, input")) {
    const name = b.getAttribute("aria-label") || b.textContent.trim() || (b.id && d.querySelector(`label[for="${b.id}"]`));
    if (!name) bad(`${label}: unnamed ${b.tagName.toLowerCase()} ${b.outerHTML.slice(0, 80)}`);
  }
}

(async () => {
  const index = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
  const exported = index.modes.filter((m) => m.status === "exported");
  const stats = [];
  for (const m of exported) {
    const t0 = Date.now();
    // build page
    let p = await open("index.html", m.slug);
    const ok = await until(() => p.d.querySelectorAll(".deck h3").length >= 1 && !/Building|Loading/.test(p.d.querySelector("#status").textContent));
    const decks = p.d.querySelectorAll(".deck h3").length, status = p.d.querySelector("#status").textContent;
    if (!ok || decks !== 3) bad(`${m.slug}: build page shows ${decks} decks (${status || p.d.querySelector("#decks").textContent.trim().slice(0, 120)})`);
    if (!p.d.querySelector("#facts").textContent.includes(m.label.split(": ").pop())) bad(`${m.slug}: facts do not name the mode`);
    const sel = p.d.querySelector("#groupsel");
    if (m.group && sel && sel.value !== m.slug) bad(`${m.slug}: picker does not show the current group (shows ${sel.value})`);
    sanity(`index#${m.slug}`, p);
    const link = (p.d.querySelector(".deck a.btn.primary") || { getAttribute: () => null }).getAttribute("href");
    p.close();
    // reason page from the first deck
    if (link) {
      p = await open("reason.html", link.split("#")[1]);
      await until(() => p.d.querySelector("#short-h") || p.d.querySelector(".empty"));
      if (!p.d.querySelector("#short-h")) bad(`${m.slug}: reason page empty: ${p.d.querySelector(".empty").textContent.trim().slice(0, 150)}`);
      else {
        if (p.d.querySelectorAll("svg.chart").length < 2) bad(`${m.slug}: reason charts missing`);
        const ap = p.d.querySelector("[data-apply]");
        if (ap) { ap.click(); await wait(200); if (!p.d.querySelector("#undo")) bad(`${m.slug}: swap did not apply`); }
      }
      sanity(`reason#${m.slug}`, p); p.close();
    }
    // cards and model pages
    p = await open("cards.html", m.slug);
    await until(() => p.d.querySelectorAll("#gtable tbody tr").length > 10);
    const rows = p.d.querySelectorAll("#gtable tbody tr").length;
    if (rows !== 187) bad(`${m.slug}: card guide has ${rows} rows`);
    sanity(`cards#${m.slug}`, p); p.close();
    p = await open("model.html", m.slug);
    await until(() => p.d.querySelectorAll("#report tbody tr").length === 4 && p.d.querySelector("#log h3"));
    if (p.d.querySelectorAll("#report tbody tr").length !== 4) bad(`${m.slug}: model report missing`);
    sanity(`model#${m.slug}`, p); p.close();
    stats.push(`${m.slug} ${((Date.now() - t0) / 1000).toFixed(1)}s`);
    console.log("checked", m.slug);
  }
  // pages without a mode switch
  for (const page of ["meta.html", "seasons.html"]) {
    const p = await open(page);
    await until(() => p.d.querySelector("#fc-h, #pred-h"));
    sanity(page, p); p.close();
  }
  // bad and edge-case links
  const edge = [
    ["index.html", "nonsense"], ["index.html", "trophy_road__goblin_stadium"], ["index.html", "ranked~~99999999b"], ["index.html", "ranked~~26000021e"],
    ["reason.html", ""], ["reason.html", "ranked~26000021b~"], ["reason.html", "ranked~26000021b-26000021b-26000021b-26000021b-26000021b-26000021b-26000021b-26000021b~"],
    ["reason.html", "trophy_road__goblin_stadium~26000021b~"], ["cards.html", "zzz"], ["model.html", "trophy_road__goblin_stadium"],
  ];
  for (const [page, hash] of edge) {
    const p = await open(page, hash);
    await until(() => p.d.querySelector(".deck h3, #short-h, .empty, #gtable tbody tr:nth-child(5), #report tbody tr"), 60000);
    await wait(300);
    const shown = (p.d.querySelector(".empty") || p.d.querySelector("#status") || p.d.querySelector("h1")).textContent.replace(/\s+/g, " ").trim().slice(0, 140);
    console.log(`edge ${page}#${hash} -> ${shown}`);
    sanity(`edge ${page}#${hash}`, p); p.close();
  }
  console.log(`\n${exported.length} modes x 4 pages + 2 pages + ${edge.length} edge links`);
  console.log(problems.length ? `${problems.length} problem(s)` : "no problems found");
  process.exit(problems.length ? 1 : 0);
})();
