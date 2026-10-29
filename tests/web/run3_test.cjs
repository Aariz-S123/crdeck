// Run 3 checks (docs/claude-redesign/ACCEPTANCE.md R3.1–R3.6): the deck explanation's decision-first overview,
// layers, swap/undo and score units; the counters page's order, labels, retrospective wording and empty states.
//   cd tests/web && node run3_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "observed.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine, deckKey, keyOf, parseDeckKey } = require(path.join(WEB, "engine.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));

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
        const t = fs.readFileSync(f, "utf8"); return { ok: true, status: 200, json: async () => JSON.parse(t) };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.Element.prototype.scrollIntoView = function () {};
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const tok = (es) => es.map((e) => `${e.id}${e.form[0]}`).join("-");
const SECTIONS = ["ov-h", "swap-h", "ev-h", "pairs-h", "warn-h", "map-h", "raw-h"];

(async () => {
  const ranked = new Engine(load("ranked"));

  // R3.1 empty and malformed links
  let p = await open("reason.html", "ranked"); await until(() => p.d.querySelector(".empty"));
  expect(/needs a deck/.test(text(p.d.querySelector(".empty"))), "R3.1 empty deck link not explained");
  p = await open("reason.html", "ranked~1b-2b~"); await until(() => p.d.querySelector(".empty"));
  expect(!!p.d.querySelector(".empty") && !p.errors.length, "R3.1 malformed deck link not handled");

  // R3.1 / R3.6 warned deck: the generated no-pick deck (it has warnings in the Ranked export)
  const warned = ranked.complete([])[0].entries, wx = ranked.explain(warned);
  p = await open("reason.html", `ranked~${tok(warned)}~`); let d = p.d;
  await until(() => d.querySelector("#ov-h"));
  const ov = d.querySelector(".overview");
  out.warned = { overview: text(ov).slice(0, 600), sections: SECTIONS.filter((id) => d.getElementById(id)) };
  expect(out.warned.sections.length === SECTIONS.length, `R3.1 sections missing: ${SECTIONS.filter((id) => !d.getElementById(id))}`);
  expect(wx.warnings.slice(0, 3).every((g) => text(ov).includes(g.root_cause)), "R3.6 overview does not show the major warnings");
  expect(/Win condition/.test(text(ov)) && /Air defense/.test(text(ov)), "R3.6 overview has no role summary");
  const order = [...d.querySelectorAll(".overview, details.layer")].map((el) => el.className.split(" ")[1] || el.id);
  expect(order[0] === "overview" && d.querySelectorAll("details.layer").length === 3, "R3.6 overview not first or layers missing");
  expect(d.querySelectorAll("svg.chart").length >= 4 && d.querySelectorAll("#map3d circle").length > 100, "R3.1 existing charts or 3D map lost");
  expect(d.querySelector("#map3d").getAttribute("tabindex") === "0", "R3.6 3D map not keyboard reachable");
  expect(!d.querySelector("#body[aria-live]"), "R3.6 whole analysis is still a live region");

  // R3.3 score decomposition: every swap's math line sums to its total, in score points; units labelled
  const rows = [...d.querySelectorAll(".swaprow")];
  let sumsOk = true;
  for (const r of rows) {
    const m = /= \(([+−\d.]+)\) \+ \(([+−\d.]+)\) \+ \(([+−\d.]+)\) = ([+−\d.]+) score points/.exec(r.querySelector(".math").textContent);
    if (!m) { sumsOk = false; continue; }
    const v = m.slice(1).map((x) => Number(x.replace("−", "-")));
    if (Math.abs(v[0] + v[1] + v[2] - v[3]) > 0.0021) sumsOk = false;
  }
  expect(rows.length && sumsOk, "R3.3 a swap's score parts don't add up to its total");
  expect(rows.every((r) => / pts · est\. wins [+−][\d.]+ pp/.test(text(r.querySelector(".d")))), "R3.3 swap rows don't label score points vs percentage points");
  // R3.2 eligibility unchanged: same score swaps and card-map swaps as the engine
  expect(rows.length === ranked.swaps(warned, { locked: [] }).length, "R3.2 score swap list differs from Engine.swaps");
  expect(d.querySelectorAll("[data-emb]").length === ranked.embeddingSwaps(warned, []).length, "R3.2 card-map swap list differs from Engine.embeddingSwaps");

  // R3.2 apply the overview's best swap with picks locked, then undo
  let deck = null, seeds = null;
  for (const q of ranked.counterPool().slice(0, 300)) {
    const lock = q.entries.slice(0, 2), sw = ranked.swaps(q.entries, { locked: lock });
    if (sw.some((x) => x.delta_objective > 0)) { deck = q.entries; seeds = lock; break; }
  }
  p = await open("reason.html", `ranked~${tok(deck)}~${tok(seeds)}`); d = p.d;
  await until(() => d.querySelector(".bestswap"));
  const h0 = p.w.location.hash, best = d.querySelector(".bestswap [data-apply]");
  out.best = text(d.querySelector(".bestswap")).slice(0, 400);
  expect(/score points/.test(out.best) && /percentage points/.test(out.best) && /Deck checks/.test(out.best) && /Evidence/.test(out.best), "R3.2 best swap lacks before/after units, checks or evidence");
  best.click(); await wait(300);
  const h1 = p.w.location.hash, newDeck = h1.split("~")[1].split("-").map((t) => ({ id: Number(t.slice(0, -1)), form: { b: "base", e: "evo", h: "hero" }[t.slice(-1)] }));
  out.applied = { hash: h1, focus: d.activeElement && d.activeElement.id, announce: text(d.querySelector("#announce")) };
  expect(h1 !== h0 && h1.split("~")[2] === h0.split("~")[2], "R3.2 apply changed the picks or not the deck");
  expect(seeds.every((s) => newDeck.some((e) => e.id === s.id && e.form === s.form)), "R3.2 a locked pick was swapped out");
  const nw = ranked.explain(newDeck).warnings.map((g) => g.root_cause);
  expect(nw.slice(0, 3).every((t) => text(d.querySelector(".overview")).includes(t)) && (nw.length || /No deck-check warnings/.test(text(d.querySelector(".overview")))), "R3.2 warnings not recomputed after a swap");
  expect(out.applied.focus === "ov-h" && /Swapped/.test(out.applied.announce), "R3.6 focus/announcement after apply");
  d.querySelector("[data-undo]").click(); await wait(300);
  expect(p.w.location.hash === h0, "R3.2 undo didn't restore the deck and link");
  expect(!p.errors.length, "reason script errors: " + p.errors.join(" | ").slice(0, 300));

  // ---------------- counters
  p = await open("counters.html", "ranked"); d = p.d;
  await until(() => d.querySelectorAll(".deck .tile").length >= 8);
  const main = [...d.querySelector("main").children].map((el) => el.id || el.className);
  out.countersOrder = main;
  expect(main.indexOf("results") < main.indexOf("verdict") && main.indexOf("verdict") > 1, "R3.4 trust check not below the results");
  const res = text(d.querySelector("#results"));
  expect(/Evidence so far:/.test(res) && /retrospective/.test(res), "R3.5 no one-line evidence status near results");
  expect(!!d.querySelector("#styledef") && /not model output/.test(text(d.querySelector("#styledef"))), "R3.4 style definition missing or not marked editorial");
  const decks = [...d.querySelectorAll(".deck")].map(text);
  expect(decks.every((t) => /estimate vs .* decks/.test(t) && /general estimate vs sampled field/.test(t)), "R3.4 target and field estimates not labelled apart");
  expect(decks.every((t) => /decks in the later battles/.test(t)) && !/after training/.test(res), "R3.4 style record not labelled as style-wide");
  expect(!/played fewer than/.test(res), "R3.4 pool absence still described as 'played fewer than'");
  const ver = text(d.querySelector("#verdict"));
  expect(/retrospective/.test(ver) && /Why "retrospective"/.test(ver), "R3.5 verdict not labelled retrospective");
  expect(/don't appear in the training battles/.test(ver) && /Models retrained without any player/.test(ver), "R3.5 unseen-player row and retrained row not distinguished");
  expect(!/only makes it wider|strongest decks/.test(ver), "R3.5 old interval or 'strongest' wording remains");
  // partial cards, exact deck, empty target set
  d.querySelector('[data-tab="cards"]').click(); await wait(50);
  expect(/up to \d+ most-played decks/.test(text(d.querySelector("#whobody"))), "R3.4 partial-card population not explained");
  // the most-played opponent deck whose 8 card forms all have matchup data (only those can be picked)
  const target = ranked.m.matchup.decks.map(([k]) => k.split("|")).find((ks) => ks.length === 8 && ks.every((k) => k in ranked.m.matchup.cards));
  for (const k of target) {
    const b = [...d.querySelectorAll(".cardlist .pick")].find((x) => x.dataset.key === k);
    if (b) b.click(); await wait(10);
  }
  // the results redraw after every pick; wait for the one made with all 8 cards
  await until(() => /this exact deck/.test(text(d.querySelector("#results"))), 30000);
  out.exact = text(d.querySelector("#cd-h") && d.querySelector("#cd-h").parentElement).slice(0, 200);
  expect(/this exact deck/.test(text(d.querySelector("#results"))), "R3.4 eight cards did not target the exact deck");
  expect(!/won \d+ of \d+ vs/.test(text(d.querySelector("#results"))), "R3.4 a style record shown as an exact-deck record");
  while (d.querySelector(".oppcard button")) { d.querySelector(".oppcard button").click(); await wait(10); }
  // two cards that share no collected deck
  const decksAll = ranked.m.matchup.decks.map(([k]) => new Set(k.split("|")));
  const keys = Object.keys(ranked.m.matchup.cards).sort();
  let pair = null;
  for (let i = 0; i < keys.length && !pair; i++) for (let j = i + 1; j < keys.length && !pair; j++) {
    if (keys[i].split(":")[0] !== keys[j].split(":")[0] && !decksAll.some((s) => s.has(keys[i]) && s.has(keys[j]))) pair = [keys[i], keys[j]];
  }
  for (const k of pair) { [...d.querySelectorAll(".cardlist .pick")].find((x) => x.dataset.key === k).click(); await wait(20); }
  await until(() => d.querySelector("#results .empty"));
  expect(/No collected deck holds all of these cards/.test(text(d.querySelector("#results"))), "R3.4 empty opponent set not explained");
  expect(!p.errors.length, "counters script errors: " + p.errors.join(" | ").slice(0, 300));

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { out.fails = fails; console.log(JSON.stringify(out, null, 1)); console.error(e); process.exit(2); });
