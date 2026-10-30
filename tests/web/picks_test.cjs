// Picks up to a full deck (the user raised the builder's limit from 3 to 8 on 2026-10-29): the picker, a full
// set of picks scored as the reader's own deck in either deck source, 4 to 7 picks completed by both sources,
// keyboard focus kept while picking, and the deck page's choice to let swaps replace picked cards.
// Expected values come from the exported models through the engine, not from the pages' own helpers.
//   cd tests/web && node picks_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "observed.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine, deckKey, keyOf, parseDeckKey } = require(path.join(WEB, "engine.js"));
const { observedDecks } = require(path.join(WEB, "observed.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const LETTER = { b: "base", e: "evo", h: "hero" }, FL = { base: "b", evo: "e", hero: "h" };
const ents = (s) => s.split("-").filter(Boolean).map((t) => ({ id: Number(t.slice(0, -1)), form: LETTER[t.slice(-1)] }));
const tok = (es) => es.map((e) => `${e.id}${FL[e.form]}`).join("-");
const pct = (x) => (100 * x).toFixed(1) + "%";

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
const settled = (d) => !/Building|Loading/.test(text(d.querySelector("#status")));
function clean(name, p) {
  const v = p.d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove());
  const t = v.textContent.replace(/\s+/g, " ");
  expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(t), `${name}: broken value in text`);
  expect(!t.includes("—"), `${name}: em dash in text`);
  expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
}
const names = (E, es) => es.map((e) => E.describe(e)).sort();
// the deck part of a builder link to the deck page, as a deck key
const linkDeck = (href) => deckKey(ents(decodeURIComponent(href).split("#")[1].split("~")[1]));

(async () => {
  const Er = new Engine(load("ranked"));
  const size = Er.m.rules.deck_size;
  expect(size === 8, `rules: deck size ${size}, expected 8`);
  // a full deck that is one of the mode's observed decks (the most played legal one), and one that is not
  const pool = Er.counterPool().filter((x) => Er.checkDeck(x.entries).legal && x.entries.every((e) => Er.isAvailable(e)));
  const top = pool.slice().sort((a, b) => b.played - a.played || (a.key < b.key ? -1 : 1))[0];
  const inPool = new Set(pool.map((x) => x.key));
  let fresh = Er.complete([]).map((x) => x.entries).find((es) => !inPool.has(deckKey(es)));
  if (!fresh) fresh = parseDeckKey(Er.swaps(top.entries, { locked: [] }).find((w) => !inPool.has(w.new_deck_key)).new_deck_key);
  const own = top.entries.slice(), ownTok = tok(own), freshTok = tok(fresh);
  out.decks = { observed: top.key, played: top.played, not_observed: deckKey(fresh) };

  // ------------------------------------------------------------ picker: no picks, then one
  let p = await open("index.html", "ranked~~"), d = p.d;
  await until(() => d.querySelectorAll(".deck h3").length === 3 && settled(d));
  out.empty = text(d.querySelector("#seeds"));
  expect(d.querySelectorAll("#seeds .seed.filled").length === 0 && d.querySelectorAll("#seeds .seed").length === 1 && /No cards picked\. You can pick up to 8\./.test(out.empty), `picker: empty state is not one line naming the limit: ${out.empty}`);
  const card = (key) => d.querySelector(`#cardlist [data-key="${key}"]`);
  card(keyOf(own[0])).click();
  out.oneFree = text(d.querySelector("#seeds .seed:not(.filled)"));
  expect(d.querySelectorAll("#seeds .seed.filled").length === 1 && out.oneFree === "7 of 8 slots free", `picker: one pick should leave "7 of 8 slots free", got "${out.oneFree}"`);
  expect(d.activeElement && d.activeElement.dataset.key === keyOf(own[0]), "focus: picking a card lost keyboard focus");
  for (const e of own.slice(1)) card(keyOf(e)).click();
  expect(d.querySelectorAll("#seeds .seed.filled").length === 8 && !d.querySelector("#seeds .seed:not(.filled)"), "picker: 8 picks not all shown, or a free line left");
  const extra = Er.candidates.find((e) => !own.some((o) => o.id === e.id));
  card(keyOf(extra)).click();
  out.ninth = text(d.querySelector("#seed-note"));
  expect(/You already picked 8 cards, a full deck\. Remove one to pick another\./.test(out.ninth) && d.querySelectorAll("#seeds .seed.filled").length === 8, `picker: ninth pick not refused: ${out.ninth}`);
  await until(() => settled(d) && d.querySelectorAll(".deck h3").length === 1);
  expect(p.w.location.hash === `#ranked~~${ownTok}`, `link: all 8 picks not saved (${p.w.location.hash})`);
  // remove one: the deck sources come back, focus moves to the next pick's remove button
  d.querySelector('#seeds [data-rm="0"]').click();
  expect(d.activeElement && d.activeElement.dataset.rm === "0", "focus: removing a pick lost keyboard focus");
  await until(() => settled(d) && d.querySelectorAll(".deck h3").length >= 1 && d.querySelectorAll("#srcbar [data-src]").length === 2);
  expect(d.querySelectorAll("#srcbar [data-src]").length === 2 && /Picking the top of many estimates/.test(text(d.querySelector("#resnote"))), "builder: after removing a pick the sources or the usual note didn't come back");
  d.querySelector("#pickact [data-clear]").click();
  expect(d.activeElement && "example" in d.activeElement.dataset, "focus: Clear picks lost keyboard focus");
  clean("builder picking", p);

  // ------------------------------------------------------------ a full deck of picks, both sources
  for (const [label, hash] of [["observed", `ranked~~${ownTok}`], ["generated", `ranked~~${ownTok}~g`]]) {
    p = await open("index.html", hash); d = p.d;
    await until(() => settled(d) && d.querySelectorAll(".deck h3").length === 1, 90000);
    const deckEl = d.querySelector(".deck"), x = Er.explain(own, Er.objectiveDict(Er.evaluate(own)));
    const r = out[`full_${label}`] = {
      status: text(d.querySelector("#status")), k: text(deckEl.querySelector(".k")), prov: text(deckEl.querySelector(".prov")),
      big: text(deckEl.querySelector(".win .big")), srcbar: text(d.querySelector("#srcbar")), hint: text(d.querySelector("#seed-hint")),
    };
    expect(d.querySelectorAll(".deck").length === 1 && r.k === "Your deck", `full ${label}: not one card labelled "Your deck"`);
    expect(r.status === "Your 8 picks, scored as one deck.", `full ${label}: status "${r.status}"`);
    expect(!d.querySelector("#srcbar [data-src]") && /All 8 cards are picked, so nothing is added/.test(r.srcbar), `full ${label}: deck-source buttons still shown`);
    expect(/All 8 slots used: that is a full deck/.test(r.hint), `full ${label}: hint "${r.hint}"`);
    const tiles = [...deckEl.querySelectorAll(".tile")].map((t) => t.getAttribute("title").replace(/, (evo|hero|wild) slot$/, "")).sort();
    expect(JSON.stringify(tiles) === JSON.stringify(names(Er, own)), `full ${label}: the card shows other cards than the picks (${tiles})`);
    expect(!deckEl.querySelector(".yours"), `full ${label}: "Your pick" marked on every card`);
    expect(r.big === pct(x.score.meta_win_prob), `full ${label}: estimate ${r.big}, engine ${pct(x.score.meta_win_prob)}`);
    const played = /observed decks: ([\d,]+) appearances/.exec(r.prov);
    expect(played && Number(played[1].replace(/,/g, "")) === top.played, `full ${label}: observed-deck appearances missing or wrong (${r.prov})`);
    expect(!d.querySelector("#compare") && !/Generated by the model|Observed deck/.test(r.prov), `full ${label}: compare panel or a source tag on the reader's own deck`);
    expect(/How its score is made/.test(text(deckEl.querySelector(".rankwhy summary"))) && /wasn't chosen as the top of many estimates/.test(text(d.querySelector("#resnote"))), `full ${label}: score or reading note not adapted`);
    const href = deckEl.querySelector("a.btn.primary").getAttribute("href");
    expect(linkDeck(href) === deckKey(own) && decodeURIComponent(href).split("~")[2] === ownTok, `full ${label}: the deck-page link doesn't carry the deck and all 8 picks (${href})`);
    clean(`full deck ${label}`, p);
  }
  // a full deck that is not an observed deck: no observed-deck sentence, but its records still shown
  p = await open("index.html", `ranked~~${freshTok}`); d = p.d;
  await until(() => settled(d) && d.querySelectorAll(".deck h3").length === 1, 90000);
  out.full_not_observed = text(d.querySelector(".deck .prov"));
  expect(/The 8 cards you picked/.test(out.full_not_observed) && !/observed decks:/.test(out.full_not_observed), `full deck not in the pool: provenance "${out.full_not_observed}"`);
  expect(/test battles/.test(text(d.querySelector(".deck .evidence"))), "full deck not in the pool: exact-deck record line missing");
  // a full set that breaks the rules (three Champions) is refused, picks kept
  const champs = Er.m.cards.filter((c) => c.champion).slice(0, 3).map((c) => ({ id: c.id, form: "base" }));
  const fillers = Er.candidates.filter((e) => e.form === "base" && !Er.card(e.id).champion).slice(0, 5);
  p = await open("index.html", `ranked~~${tok(champs.concat(fillers))}`); d = p.d;
  await until(() => settled(d) && /No legal deck/.test(text(d.querySelector("#decks"))), 90000);
  expect(/No legal deck can hold these cards together/.test(text(d.querySelector("#decks"))) && d.querySelectorAll("#seeds .seed.filled").length === 8, "full deck with three Champions: not refused, or picks dropped");
  clean("full deck refused", p);

  // ------------------------------------------------------------ 4 to 7 picks: both sources keep every pick
  out.partial = {};
  for (let n = 4; n <= 7; n++) {
    const seeds = own.slice(0, n);
    p = await open("index.html", `ranked~~${tok(seeds)}~g`); d = p.d;
    const want = Er.complete(seeds).map((x) => x.key);
    await until(() => settled(d) && d.querySelectorAll(".deck h3").length === want.length, 90000);
    const got = [...d.querySelectorAll(".deck a.btn.primary")].map((a) => linkDeck(a.getAttribute("href")));
    out.partial[`generated_${n}`] = got.length;
    expect(JSON.stringify(got) === JSON.stringify(want), `${n} picks, generated: decks differ from the engine (${got.length} vs ${want.length})`);
    // one free slot: completions differ by one card, fewer than the search's minimum difference, so one option
    const minDiff = Number(Er.cfg.search.min_diff_cards), note = text(d.querySelector("#decks .obsnote"));
    if (size - n < minDiff) expect(want.length === 1 && /^Only one generated option\./.test(note) && /^1 generated option with /.test(text(d.querySelector("#status"))), `${n} picks, generated: single option not explained (${note})`);
    else expect(!/Only one generated option/.test(note), `${n} picks, generated: single-option note shown with ${size - n} free slots`);
    clean(`${n} picks generated`, p);
    if (n === 5) {
      p = await open("index.html", `ranked~~${tok(seeds)}`); d = p.d;
      const ob = observedDecks(Er, seeds).decks.map((x) => x.key);
      await until(() => settled(d) && d.querySelectorAll(".deck h3").length === ob.length, 90000);
      const gotObs = [...d.querySelectorAll(".deck a.btn.primary")].map((a) => linkDeck(a.getAttribute("href")));
      out.partial.observed_5 = gotObs.length;
      expect(ob.length > 0 && JSON.stringify(gotObs) === JSON.stringify(ob), `5 picks, observed: decks differ from the observed-deck rule (${gotObs.length} vs ${ob.length})`);
      expect(gotObs.every((k) => seeds.every((s) => k.split("|").includes(keyOf(s)))), "5 picks, observed: a deck misses a pick");
    }
  }

  // ------------------------------------------------------------ deck page: every card a pick, then swaps allowed
  const locked = Er.swaps(own, { locked: own }), freeSw = Er.swaps(own, { locked: [] });
  expect(locked.length === 0 && freeSw.length > 0, `engine: full set of picks gives ${locked.length} locked and ${freeSw.length} free swaps`);
  p = await open("reason.html", `ranked~${ownTok}~${ownTok}`); d = p.d;
  await until(() => d.querySelector("#ov-h"));
  const ov = () => text(d.querySelector(".overview"));
  out.reason_locked = ov().slice(ov().indexOf("Best next step"));
  expect(/Every card here is one you picked, and swaps never replace a pick, so there is nothing to swap\./.test(ov()) && !d.querySelector(".overview [data-apply]"), "deck page: all-picks message missing or a swap offered");
  expect(!d.querySelector(".deckbox .yours"), "deck page: \"Your pick\" marked on every card of an all-picks deck");
  const lay = d.querySelector("#lay-swaps"); lay.open = true; lay.dispatchEvent(new p.w.Event("toggle"));
  await until(() => lay.querySelector(".body").dataset.done);
  expect(/Every card in this deck is one you picked/.test(text(lay)) && lay.querySelector('[data-free="1"]'), "deck page: swaps layer has no way to include the picks");
  d.querySelector('.overview [data-free="1"]').click();
  await until(() => d.querySelector('.overview [data-free="0"]'));
  out.reason_free = { hash: p.w.location.hash, summary: text(d.querySelector("#lay-swaps summary")) };
  expect(p.w.location.hash.endsWith("~free"), `deck page: the choice is not kept in the link (${p.w.location.hash})`);
  expect(new RegExp(`^All score swaps\\s*${freeSw.length.toLocaleString()} single-card changes`).test(out.reason_free.summary), `deck page: ${out.reason_free.summary} (engine ${freeSw.length})`);
  let bi = -1; freeSw.forEach((s, j) => { if (bi < 0 || s.delta_objective > freeSw[bi].delta_objective) bi = j; });
  const best = freeSw[bi];
  if (best.delta_objective > 0) expect(text(d.querySelector(".bestswap b")) === `Replace ${best.replace} with ${best.with}`, `deck page: best swap "${text(d.querySelector(".bestswap b"))}", engine ${best.replace} > ${best.with}`);
  else expect(/No single-card swap among the candidate cards raises/.test(ov()), "deck page: no improving swap, but the page offers one");
  expect(/Swaps may replace your picked cards too/.test(ov()) && d.activeElement === d.querySelector("#ov-h"), "deck page: allowed state not explained, or focus not moved to the summary");
  // the link brings the choice back; Keep my picks undoes it
  const q = await open("reason.html", p.w.location.hash.slice(1));
  await until(() => q.d.querySelector("#ov-h"));
  expect(!!q.d.querySelector('.overview [data-free="0"]'), "deck page: a link with the choice opened with picks locked");
  if (best.delta_objective > 0) {
    q.d.querySelector('.overview [data-apply]').click();
    await until(() => /Swapped/.test(text(q.d.querySelector("#sub"))));
    expect(q.d.querySelectorAll(".deckbox .yours").length === 7 && !!q.d.querySelector('.overview [data-free="0"]'), "deck page: after swapping a pick out, the other 7 picks aren't marked or the choice was lost");
  }
  d.querySelector('.overview [data-free="0"]').click();
  await until(() => d.querySelector('.overview [data-free="1"]'));
  expect(!p.w.location.hash.endsWith("~free") && /nothing to swap/.test(ov()), "deck page: Keep my picks didn't lock the picks again");
  clean("deck page all picks", p); clean("deck page from link", q);
  // with some picks, they are kept out of swaps and the reader can let swaps replace them
  const seeds3 = own.slice(0, 3);
  p = await open("reason.html", `ranked~${ownTok}~${tok(seeds3)}`); d = p.d;
  await until(() => d.querySelector("#ov-h"));
  expect(/Your 3 picked cards stay in the deck: swaps never replace them\./.test(ov()) && d.querySelector('.overview [data-free="1"]'), "deck page: 3 picks not explained with the choice to include them");
  expect(d.querySelectorAll(".deckbox .yours").length === 3, "deck page: the 3 picks are not marked");
  expect(new RegExp(`^All score swaps\\s*${Er.swaps(own, { locked: seeds3 }).length.toLocaleString()} single-card changes`).test(text(d.querySelector("#lay-swaps summary"))), "deck page: swaps with 3 picks differ from the engine");
  clean("deck page 3 picks", p);

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})();
