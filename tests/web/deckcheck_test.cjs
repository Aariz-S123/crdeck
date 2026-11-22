// Check my deck (web/check.html, web/deckcheck.js): reading a pasted deck, the choice between a mode's own and its
// pooled matchup model, the matchup numbers recomputed from the model file by hand, and the page in three modes
// (Ranked with its own matchup model, an arena that borrows Trophy Road's, a league whose win model is gated).
//   cd tests/web && node deckcheck_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "common.js", "deckcheck.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine } = require(path.join(WEB, "engine.js"));
const DC = require(path.join(WEB, "deckcheck.js"));
const INDEX = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => require("./model_file.cjs").loadModel(path.join(WEB, "models", slug + ".json"));
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const FL = { base: "b", evo: "e", hero: "h" };
const tok = (es) => es.map((e) => `${e.id}${FL[e.form]}`).join("-");
const entry = (slug) => INDEX.modes.find((m) => m.slug === slug);
const close = (a, b, eps = 1e-12) => Math.abs(a - b) <= eps;

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
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
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
function clean(name, p) {
  const v = p.d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove());
  const t = v.textContent.replace(/\s+/g, " ");
  expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(t), `${name}: broken value in text`);
  expect(!t.includes("—"), `${name}: em dash in text`);
  expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
}

// the matchup model written out from the model file, without the engine: z = Σw_A − Σw_B + ΣK(i, j)
function handWin(mm, A, B) {
  const K = new Map(mm.pairs.map(([i, j, k]) => [`${i}|${j}`, k]));
  const k = (i, j) => (i === j ? 0 : i < j ? K.get(`${i}|${j}`) || 0 : -(K.get(`${j}|${i}`) || 0));
  const w = (c) => (mm.cards[c] ? mm.cards[c][0] : 0);
  const sA = [...new Set(A)], sB = [...new Set(B)];
  let z = 0; for (const i of sA) z += w(i); for (const j of sB) z -= w(j);
  for (const i of sA) for (const j of sB) z += k(i, j);
  return 1 / (1 + Math.exp(-z));
}

(async () => {
  const LIST = "Hog Rider, Evo Musketeer, Ice Spirit, Ice Golem, Skeletons, Cannon, Fireball, The Log";
  const Er = new Engine(load("ranked"));

  // ---------------------------------------------------------------- 1. reading a pasted deck
  const p1 = DC.parseDeckText(Er, LIST);
  expect(p1.entries.length === 8 && !p1.unknown.length && !p1.fromIds, "paste: 8 names not all read");
  expect(p1.entries.find((e) => e.id === Er.byNameLookup("Musketeer").id).form === "evo", "paste: Evo Musketeer not read as an Evolution");
  expect(Er.checkDeck(p1.entries).legal, "paste: the example deck isn't legal");
  const p2 = DC.parseDeckText(Er, "Hog Rider\nMusketeer (Evolution)\nNot A Card");
  expect(p2.entries.length === 2 && p2.unknown.length === 1 && p2.entries[1].form === "evo", "paste: lines, a suffix form and an unknown name");
  const ids = p1.entries.map((e) => e.id);
  const p3 = DC.parseDeckText(Er, `https://link.clashroyale.com/en/?clashroyale://copyDeck?deck=${ids.join(";")}&l=Royals`);
  expect(p3.fromIds && p3.entries.length === 8 && p3.entries.every((e) => e.form === "base"), "paste: a game link's card ids");
  expect(!DC.parseDeckText(Er, "   ").entries.length, "paste: empty text");

  // ---------------------------------------------------------------- 2. which matchup model
  expect(!DC.needsPooled(entry("ranked"), Er.m), "pooled: Ranked should use its own matchup model");
  const uc = load("ranked__ultimate_champion"), hm = load("trophy_road__hog_mountain");
  expect(!DC.needsPooled(entry("ranked__ultimate_champion"), uc), `pooled: Ultimate Champion has ${uc.matchup.pairs.length} pairs and should use its own`);
  expect(DC.needsPooled(entry("trophy_road__hog_mountain"), hm) && DC.pooledSlug(INDEX, entry("trophy_road__hog_mountain")) === "trophy_road", "pooled: Hog Mountain should borrow Trophy Road");
  out.pooled_modes = INDEX.modes.filter((m) => m.status === "exported" && m.group).filter((m) => DC.needsPooled(m, load(m.slug))).length;

  // ---------------------------------------------------------------- 3. matchup numbers, recomputed by hand
  const r = DC.analyze(Er, Er, p1.entries), mm = Er.m.matchup;
  expect(r.state === "ok" && !r.missing.length, "analyze: Ranked state or missing cards");
  for (const s of r.styles) {
    const list = mm.styles[s.style], tot = list.reduce((t, [, n]) => t + n, 0);
    const want = list.reduce((t, [d, n]) => t + n * handWin(mm, r.keys, d.split("|")), 0) / tot;
    expect(close(s.win, want), `analyze: ${s.style} win ${s.win} vs hand ${want}`);
  }
  for (const d of r.beats.concat(r.losesTo)) expect(close(d.win, handWin(mm, r.keys, d.key.split("|"))), `analyze: deck ${d.key} win differs from hand`);
  expect(r.beats.every((d) => d.win > 0.5) && r.losesTo.every((d) => d.win < 0.5), "analyze: beats above 50%, loses-to below");
  expect(r.beats.length <= DC.SHOW && r.losesTo.length <= DC.SHOW, "analyze: list lengths");
  const share = r.field.decks ? r.beats.concat(r.losesTo).every((d) => d.share > 0 && d.share < 1) : false;
  expect(share && close(mm.decks.slice(0, DC.TOP_OPPONENTS).filter(([k]) => k !== r.keys.slice().sort().join("|")).length, r.field.decks, 0), "analyze: field size or shares");
  for (const c of r.trouble.concat(r.handles)) {
    const k = r.keys.reduce((t, i) => t + Er.muK(i, c.card), 0);
    expect(close(c.k, k) && c.share >= DC.MIN_CARD_SHARE && !r.keys.includes(c.card), `analyze: card ${c.card} score or share`);
  }
  expect(r.trouble.every((c) => c.k < 0) && r.handles.every((c) => c.k > 0), "analyze: card list signs");
  out.ranked = { field_win: r.field.win, favoured: r.field.favoured, styles: r.styles.map((s) => [s.style, +s.win.toFixed(4)]),
    best: r.beats[0] && +r.beats[0].win.toFixed(4), worst: r.losesTo[0] && +r.losesTo[0].win.toFixed(4) };
  // a mode's real pool deck brings its measured records against the styles
  const top = Er.counterPool().filter((x) => Er.checkDeck(x.entries).legal).sort((a, b) => b.played - a.played)[0];
  const rp = DC.analyze(Er, Er, top.entries);
  expect(rp.poolRecord && rp.poolPlayed === top.played, "analyze: a pool deck's records not found");

  // ---------------------------------------------------------------- 4. the page
  // Ranked: its own matchup model, with a win estimate
  let p = await open("check.html", `ranked~${tok(p1.entries)}~`), d = p.d;
  await until(() => d.querySelector("#mu-h") || d.querySelector('#results [role="alert"]'));
  expect(d.querySelector("#mu-h"), "page ranked: no matchups");
  expect(/^\d+\.\d%\s*estimated win rate/.test(text(d.querySelector("#win-h + .big"))), "page ranked: no win estimate");
  expect(!/Borrowed model/.test(text(d.querySelector("#results"))), "page ranked: says borrowed");
  expect(d.querySelectorAll(".bar").length === r.styles.length, "page ranked: style rows");
  expect(text(d.querySelector(".bar b")) === `${(100 * r.styles[0].win).toFixed(1)}%`, "page ranked: first style number differs from analyze");
  expect(d.querySelectorAll("#beat-h ~ .opp").length === r.beats.length && d.querySelectorAll("#lose-h ~ .opp").length === r.losesTo.length, "page ranked: deck lists");
  expect([...d.querySelectorAll(".nav a")].some((a) => a.textContent === "Check my deck" && a.getAttribute("aria-current") === "page"), "page: menu link");
  clean("page ranked", p);

  // pasting into the page
  d.querySelector("#paste").value = "Hog Rider, Musketeer";
  d.querySelector("#readpaste").click();
  await until(() => /6 more cards/.test(text(d.querySelector("#results"))));
  expect(/Read 2 cards/.test(text(d.querySelector("#paste-note"))) && /2 of 8/.test(text(d.querySelector("#count"))), "page: paste of 2 cards");
  expect(p.w.location.hash.includes(`${Er.byNameLookup("Hog Rider").id}b`), "page: link doesn't hold the pasted cards");

  // an arena that borrows Trophy Road's matchup model
  p = await open("check.html", `trophy_road__hog_mountain~${tok(p1.entries)}~`); d = p.d;
  await until(() => d.querySelector("#mu-h") || d.querySelector('#results [role="alert"]'));
  expect(/Borrowed model/.test(text(d.querySelector("#results"))) && /Trophy Road ladder matchup model/.test(text(d.querySelector("#results"))), "page hog mountain: borrowed model not said");
  clean("page hog mountain", p);

  // a league whose win model is gated: no headline estimate, matchups still shown
  p = await open("check.html", `ranked__champion~${tok(p1.entries)}~`); d = p.d;
  await until(() => d.querySelector("#mu-h") || d.querySelector('#results [role="alert"]'));
  expect(/No win estimate here/.test(text(d.querySelector("#results"))) && !d.querySelector("#win-h + .big"), "page champion: gated estimate shown");
  expect(d.querySelector("#mu-h"), "page champion: no matchups");
  clean("page champion", p);

  // an illegal deck (two champions are allowed? use 9 cards' worth: a duplicate form can't happen, so 7 cards)
  p = await open("check.html", `ranked~${tok(p1.entries.slice(0, 7))}~`); d = p.d;
  await until(() => /1 more card/.test(text(d.querySelector("#results"))));
  expect(!d.querySelector("#mu-h"), "page: 7 cards shouldn't be checked");
  clean("page 7 cards", p);

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})();
