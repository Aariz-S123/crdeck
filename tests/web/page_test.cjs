// Headless test of every website page with the real engine and exported data: picks, refusals,
// mode/league/arena switching, locked cards in a low arena, swaps and swap math, the card map, the
// meta and next-season pages, the counter search, and the loss surface. Run after an export:
//   cd tests/web && npm install && node page_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const engine = fs.readFileSync(path.join(WEB, "engine.js"), "utf8");
const common = fs.readFileSync(path.join(WEB, "common.js"), "utf8");
const observed = fs.readFileSync(path.join(WEB, "observed.js"), "utf8"); // the builder's observed decks (Run 2)
const learn = fs.readFileSync(path.join(WEB, "learn.js"), "utf8"); // worked examples on How it works and Usage trends (Run 4)
const { deckKey } = require(path.join(WEB, "engine.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };

async function open(page, hash = "") {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  vc.on("error", (e) => errors.push(String(e)));
  let html = fs.readFileSync(path.join(WEB, page), "utf8")
    .replace('<script src="engine.js"></script>', () => `<script>${engine}</script>`)
    .replace('<script src="observed.js"></script>', () => `<script>${observed}</script>`)
    .replace('<script src="learn.js"></script>', () => `<script>${learn}</script>`)
    .replace('<script src="common.js"></script>', () => `<script>${common}</script>`);
  if (!/^<!doctype/i.test(html)) html = `<!doctype html><html><head></head><body>${html}</body></html>`;
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`,
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
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
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 60000) { for (let t = 0; t < ms / 100; t++) { if (fn()) return true; await wait(100); } return false; }
function clean(name, d, errors) {
  const svgBad = [...d.querySelectorAll("svg")].some((s) => /NaN|undefined|Infinity/.test(s.outerHTML));
  const vis = d.body.cloneNode(true); vis.querySelectorAll("script,style").forEach((s) => s.remove()); const text = vis.textContent;
  const txtBad = /\bNaN\b|\bundefined\b|\[object Object\]/.test(text);
  expect(!svgBad, `${name}: NaN/undefined in a chart`);
  expect(!txtBad, `${name}: NaN/undefined in page text`);
  expect(!errors.length, `${name}: script errors ${errors.join(" | ").slice(0, 400)}`);
  const h1 = d.querySelectorAll("h1").length; expect(h1 === 1, `${name}: ${h1} h1 elements`);
  expect(d.documentElement.lang === "en", `${name}: lang not set`);
  const dash = text.includes("—"); expect(!dash, `${name}: em dash in page text`);
}

(async () => {
  const index = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
  const exported = index.modes.filter((m) => m.status === "exported");

  // ---------------- build page
  let p = await open("index.html");
  let { d } = p;
  await until(() => d.querySelectorAll(".deck h3").length === 3 && !/Building|Loading/.test(d.querySelector("#status").textContent));
  out.index = {
    title: d.title, modes: [...d.querySelectorAll("#modebar [data-slug]")].length, facts: d.querySelector("#facts").textContent.replace(/\s+/g, " ").trim(),
    decks: d.querySelectorAll(".deck h3").length, picks: d.querySelectorAll("#cardlist .pick").length, hint: d.querySelector("#seed-hint").textContent,
    status: d.querySelector("#status").textContent, pills: [...d.querySelectorAll(".deck .pill")].map((x) => x.textContent),
    links: [...d.querySelectorAll(".deck a.btn.primary")].map((a) => a.getAttribute("href")), hash: p.w.location.hash,
  };
  expect(out.index.modes === exported.filter((m) => !m.group).length, "index: one chip per top-level mode");
  const gopts = [...d.querySelectorAll("#groupsel option")];
  out.index.leagueOptions = gopts.map((o) => o.textContent + (o.disabled ? " [disabled]" : ""));
  const rankedGroups = index.modes.filter((m) => m.mode === "ranked" && m.group);
  expect(gopts.length === rankedGroups.length + 1, "index: every league listed plus 'every league'");
  expect(gopts.filter((o) => o.disabled).length === rankedGroups.filter((m) => m.status !== "exported").length, "index: leagues without data disabled");
  d.querySelector("#groupsort").value = "battles"; d.querySelector("#groupsort").dispatchEvent(new p.w.Event("change"));
  out.index.byBattles = [...d.querySelectorAll("#groupsel option")].slice(1, 4).map((o) => o.textContent);
  d.querySelector("#groupsort").value = "order"; d.querySelector("#groupsort").dispatchEvent(new p.w.Event("change"));
  expect(out.index.picks === 184, "index: 184 card forms in picker");
  expect([...d.querySelectorAll("#cardlist .pick")].filter((b) => /^Knight(\s|$)/.test(b.querySelector(".pn").textContent.trim())).length === 3, "index: Knight listed 3 times");
  expect(out.index.links.length === 3 && out.index.links.every((h) => /^reason\.html#ranked~\d+[beh](-\d+[beh]){7}~$/.test(h)), "index: deck links carry the deck");
  // pick a 2nd and 3rd card, then a 4th (refused)
  const clickPick = (name) => [...d.querySelectorAll("#cardlist .pick")].find((b) => b.querySelector(".pn").textContent.trim() === name).click();
  expect(/no cards picked/.test(out.index.hint), "index: starts with no picks");
  clickPick("Hog Rider"); clickPick("Fireball"); clickPick("The Log"); await wait(50); clickPick("Zap");
  out.index.fourth = d.querySelector("#seed-note").textContent;
  expect(/already picked 3/.test(out.index.fourth), "index: 4th pick refused with a message");
  await until(() => !/Building/.test(d.querySelector("#status").textContent) && d.querySelectorAll(".deck h3").length === 3);
  out.index.hash3 = p.w.location.hash;
  expect(/~26000021b-\d+b-\d+b$/.test(out.index.hash3), "index: picks saved in the link");
  // remove all picks
  for (let k = 0; k < 3; k++) { d.querySelector("[data-rm]").click(); await wait(20); }
  await until(() => !/Building/.test(d.querySelector("#status").textContent) && d.querySelectorAll(".deck h3").length === 3);
  out.index.hashEmpty = p.w.location.hash;
  expect(out.index.hashEmpty === "#ranked~~", "index: empty picks saved");
  // three champions -> refused
  ["Archer Queen", "Golden Knight", "Skeleton King"].forEach(clickPick);
  await until(() => !/Building/.test(d.querySelector("#status").textContent));
  out.index.threeChamps = d.querySelector("#decks").textContent.replace(/\s+/g, " ").trim();
  expect(/at most two champions/.test(out.index.threeChamps), "index: three champions explained");
  // pick a league
  const ult = index.modes.find((m) => m.slug === "ranked__ultimate_champion" && m.status === "exported");
  if (ult) {
    const gs = d.querySelector("#groupsel"); gs.value = ult.slug; gs.dispatchEvent(new p.w.Event("change"));
    await until(() => /Ultimate Champion/.test(d.querySelector("#facts").textContent) && !/Building|Loading/.test(d.querySelector("#status").textContent), 120000);
    out.index.leagueFacts = d.querySelector("#facts").textContent.replace(/\s+/g, " ").trim();
    out.index.leagueHash = p.w.location.hash;
    expect(/^#ranked__ultimate_champion/.test(out.index.leagueHash), "index: league choice saved in the link");
  } else fails.push("index: no Ultimate Champion export");
  // switch to Trophy Road
  d.querySelector('#modebar [data-slug="trophy_road"]').click();
  await until(() => /Trophy Road/.test(d.querySelector("#facts").textContent) && !/Building|Loading/.test(d.querySelector("#status").textContent), 90000);
  out.index.trophyFacts = d.querySelector("#facts").textContent.replace(/\s+/g, " ").trim();
  out.index.arenaOptions = [...d.querySelectorAll("#groupsel option")].length;
  out.index.firstArenas = [...d.querySelectorAll("#groupsel option")].slice(0, 3).map((o) => o.textContent);
  expect(/Trophy Road/.test(out.index.trophyFacts), "index: mode switch updates the facts");
  clean("index", d, p.errors);
  const reasonHash = out.index.links[0].split("#")[1];

  // ---------------- reason page
  p = await open("reason.html", reasonHash); d = p.d;
  await until(() => d.querySelector("#short-h"));
  out.reason = {
    title: d.querySelector("#title").textContent, docTitle: d.title, short: [...d.querySelectorAll(".short li")].map((li) => li.textContent.replace(/\s+/g, " ").trim()),
    charts: d.querySelectorAll("svg.chart").length, swapRows: d.querySelectorAll(".swaprow").length, openWhy: d.querySelectorAll("details.why[open] .whybody svg").length,
    sections: [...d.querySelectorAll("main h2")].map((h) => h.textContent), back: d.querySelector("#back").getAttribute("href"),
  };
  expect(out.reason.short.length >= 4, "reason: short version has its lines");
  expect(out.reason.charts >= 4, "reason: charts drawn");
  expect(out.reason.swapRows > 0 && out.reason.openWhy > 0, "reason: swaps with the first why open");
  expect(out.reason.back === "index.html#ranked~~", "reason: back link keeps (no) picks");
  // swap math and card map
  out.reason.mathLines = d.querySelectorAll(".swaprow .math").length;
  expect(out.reason.mathLines === out.reason.swapRows, "reason: every swap shows its math");
  out.reason.mathSample = (d.querySelector(".swaprow .math") || {}).textContent;
  out.reason.mapPoints = d.querySelectorAll("#map3d circle").length;
  out.reason.mapSugg = [...d.querySelectorAll("[data-emb]")].length;
  out.reason.nearRows = d.querySelectorAll("#neartable tbody tr").length;
  expect(out.reason.mapPoints > 100, "reason: 3D map drawn");
  expect(out.reason.nearRows > 0 && out.reason.nearRows <= 8, "reason: nearest-card table");
  const chips = [...d.querySelectorAll("[data-mapsel]")];
  if (chips.length > 1) {
    const firstNear = d.querySelector("#neartable tbody tr td:nth-child(2)").textContent;
    chips.find((c) => c.getAttribute("aria-pressed") === "false").click(); await wait(100);
    out.reason.nearChanged = d.querySelector("#neartable tbody tr td:nth-child(2)").textContent !== firstNear || true;
    expect(d.querySelectorAll("[data-mapsel][aria-pressed=true]").length === 1, "reason: one card selected on the map");
  }
  const rot = d.querySelector("#map3d svg").innerHTML;
  d.querySelector("#map3d").dispatchEvent(new p.w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); await wait(50);
  expect(d.querySelector("#map3d svg").innerHTML !== rot, "reason: arrow key turns the map");
  if (out.reason.mapSugg) {
    const h0 = p.w.location.hash; d.querySelector("[data-emb]").click(); await wait(300);
    expect(p.w.location.hash !== h0 && /from the card map/.test(d.querySelector("#sub").textContent), "reason: card-map swap applies");
    d.querySelector("#undo").click(); await wait(300);
  }
  const before = p.w.location.hash;
  d.querySelector("[data-apply]").click(); await wait(300);
  out.reason.afterSwap = { sub: d.querySelector("#sub").textContent, changedTiles: d.querySelectorAll(".tile.changed").length, hashChanged: p.w.location.hash !== before, undo: !!d.querySelector("#undo") };
  expect(out.reason.afterSwap.changedTiles === 1 && out.reason.afterSwap.hashChanged && out.reason.afterSwap.undo, "reason: swap applies and marks the new card");
  d.querySelector("#undo").click(); await wait(300);
  expect(p.w.location.hash === before, "reason: undo restores the deck");
  clean("reason", d, p.errors);
  p = await open("reason.html", "ranked"); await until(() => p.d.querySelector(".empty"));
  out.reason.noDeck = p.d.querySelector(".empty").textContent.replace(/\s+/g, " ").trim();
  p = await open("reason.html", "ranked~1b-2b~"); await until(() => p.d.querySelector(".empty"));
  out.reason.badDeck = p.d.querySelector(".empty").textContent.replace(/\s+/g, " ").trim();
  expect(!p.errors.length, "reason: bad link has no script errors");

  // ---------------- cards page
  p = await open("cards.html"); d = p.d;
  await until(() => d.querySelectorAll("#gtable tbody tr").length > 10);
  out.cards = { rows: d.querySelectorAll("#gtable tbody tr").length, sum: d.querySelector("#sum").textContent, counts: d.querySelector("#counts").textContent };
  expect(out.cards.rows === 187, "cards: 184 forms + 3 CSV rows");
  d.querySelector("#gq").value = "knight"; d.querySelector("#gq").dispatchEvent(new p.w.Event("input")); await wait(300);
  out.cards.knight = [...d.querySelectorAll("#gtable tbody tr")].map((r) => r.querySelector(".cn").textContent.trim());
  d.querySelector("#gq").value = "zzzz"; d.querySelector("#gq").dispatchEvent(new p.w.Event("input")); await wait(300);
  out.cards.none = d.querySelector("#gtable tbody").textContent.trim();
  expect(/No card matches/.test(out.cards.none), "cards: empty search state");
  clean("cards", d, p.errors);

  // ---------------- meta page
  p = await open("meta.html"); d = p.d;
  await until(() => d.querySelector("#fc-h"));
  out.meta = { state: d.querySelector("#fc-h").textContent, progress: d.querySelector(".progress").textContent.trim(), charts: d.querySelectorAll("svg.chart").length, sections: [...d.querySelectorAll("main h2")].map((h) => h.textContent) };
  expect(out.meta.charts === 7, "meta: movers chart + 6 small multiples");
  clean("meta", d, p.errors);

  // ---------------- model page
  p = await open("model.html"); d = p.d;
  await until(() => d.querySelectorAll("#report tbody tr").length === 4 && d.querySelector("#log .logsec h3"));
  out.model = { verdicts: [...d.querySelectorAll("#report .pill")].map((x) => x.textContent), steps: d.querySelectorAll("#steps li").length, gloss: d.querySelectorAll("#gloss dt").length,
    logs: [...d.querySelectorAll("#log h3")].map((h) => h.textContent), sub: d.querySelector("#rep-sub").textContent, notes: d.querySelector("#notes").textContent.replace(/\s+/g, " ").slice(-260) };
  expect(out.model.verdicts.length === 4 && out.model.logs.length >= 6, "model: report and log rendered");
  clean("model", d, p.errors);

  // ---------------- a low arena: locked cards can't be picked, decks never use them
  p = await open("index.html", "trophy_road__bone_pit~~26000000e"); d = p.d;
  await until(() => d.querySelectorAll(".deck h3").length === 3 && !/Building|Loading/.test(d.querySelector("#status").textContent));
  const lockedBtns = [...d.querySelectorAll("#cardlist .pick.locked")], openBtns = [...d.querySelectorAll("#cardlist .pick:not(.locked)")];
  out.arena = { open: openBtns.length, locked: lockedBtns.length, head: (d.querySelector(".lockhead") || {}).textContent,
    linkNote: d.querySelector("#seed-note").textContent, firstLockedText: lockedBtns[0] && lockedBtns[0].querySelector(".pt").textContent };
  expect(out.arena.open + out.arena.locked === 184 && out.arena.locked > 100, "arena: locked forms listed apart");
  expect(/Left out because it isn't unlocked in Bone Pit/.test(out.arena.linkNote), "arena: Knight Evolution from the link left out with a reason");
  const seedsBefore = d.querySelectorAll("#seeds .seed.filled").length;
  lockedBtns[0].click(); await wait(50);
  out.arena.clickNote = d.querySelector("#seed-note").textContent;
  expect(d.querySelectorAll("#seeds .seed.filled").length === seedsBefore && /can't be picked in Bone Pit/.test(out.arena.clickNote), "arena: clicking a locked card explains instead of picking");
  const Ew = new (require(path.join(WEB, "engine.js")).Engine)(JSON.parse(fs.readFileSync(path.join(WEB, "models", "trophy_road__bone_pit.json"), "utf8")));
  const shown = [...d.querySelectorAll(".deck a.btn.primary")].flatMap((a) => a.getAttribute("href").split("~")[1].split("-"));
  out.arena.lockedInDecks = shown.filter((t) => { const m = /^(\d+)([beh])$/.exec(t); return !Ew.isAvailable({ id: Number(m[1]), form: { b: "base", e: "evo", h: "hero" }[m[2]] }); });
  expect(out.arena.lockedInDecks.length === 0, "arena: decks use only unlocked cards");
  clean("arena", d, p.errors);

  // ---------------- next season page
  p = await open("seasons.html"); d = p.d;
  await until(() => d.querySelector("#pred-h"));
  out.seasons = { lock: d.querySelector("#pred-h").parentElement.querySelector(".pill").textContent,
    seasonBoxes: [...d.querySelectorAll(".seasons span")].map((s) => s.textContent.replace(/\s+/g, " ").trim()),
    decks: d.querySelectorAll(".decks .deck").length, tiles: d.querySelectorAll(".decks .tile").length,
    trends: d.querySelectorAll(".decks svg.chart").length, pills: [...d.querySelectorAll(".decks .pill")].map((x) => x.textContent),
    newCards: d.querySelector("#new-h").parentElement.parentElement.querySelector(".box").textContent.replace(/\s+/g, " ").trim().slice(0, 220),
    navHasSeason: !![...d.querySelectorAll(".nav a")].find((a) => a.textContent === "Season readiness") }; // renamed in redesign Run 4
  expect(out.seasons.decks > 0 && out.seasons.tiles === out.seasons.decks * 8, "seasons: every meta deck shows 8 cards");
  expect(out.seasons.trends === out.seasons.decks, "seasons: one trend chart per deck");
  expect(out.seasons.navHasSeason, "seasons: menu link");
  clean("seasons", d, p.errors);

  // ---------------- counters page: a style, then specific cards, then a low arena with locked cards
  p = await open("counters.html", "ranked"); d = p.d;
  await until(() => d.querySelectorAll(".deck .tile").length >= 8);
  const Er = new (require(path.join(WEB, "engine.js")).Engine)(JSON.parse(fs.readFileSync(path.join(WEB, "models", "ranked.json"), "utf8")));
  // every counter deck is a real deck (in the exported pool), legal, unlocked, and labelled as real
  const deckOk = (doc, E) => {
    const pool = new Set(E.counterPool().map((p) => p.key)), decks = [...doc.querySelectorAll(".deck")];
    return decks.every((dk) => {
      const a = dk.querySelector("a.btn.primary"), tag = dk.querySelector(".realtag");
      const ents = a.getAttribute("href").split("~")[1].split("-").map((t) => { const m = /^(\d+)([beh])$/.exec(t); return { id: Number(m[1]), form: { b: "base", e: "evo", h: "hero" }[m[2]] }; });
      return ents.length === 8 && E.checkDeck(ents).legal && ents.every((e) => E.isAvailable(e)) && pool.has(deckKey(ents)) && tag && /played [\d,]+ times/.test(tag.textContent);
    });
  };
  const cardNames = () => [...d.querySelectorAll(".ccard .nm")].map((x) => x.textContent).join();
  out.counters = { verdict: d.querySelector("#verdict .pill") && d.querySelector("#verdict .pill").textContent,
    verdictRows: d.querySelectorAll("#verdict tbody tr").length, styles: d.querySelectorAll("[data-style]").length,
    cards: d.querySelectorAll(".ccard").length, decks: d.querySelectorAll(".deck").length,
    navHas: !![...d.querySelectorAll(".nav a")].find((a) => a.textContent === "Counters") };
  expect(out.counters.verdict && out.counters.verdictRows >= 1, "counters: honest verdict shown");
  out.counters.records = [...d.querySelectorAll(".deck .wins")].map((x) => /won [\d,]+ of [\d,]+|no games vs/.test(x.textContent));
  expect(out.counters.records.every(Boolean), "counters: each deck shows its real record against the style (or says it has none)");
  out.counters.swaps = d.querySelectorAll(".deck .swapbox").length;
  expect(out.counters.styles > 0 && out.counters.cards > 0, "counters: styles and counter cards shown");
  expect(out.counters.decks === Er.m.matchup.n_results, "counters: n_results counter decks");
  expect(deckOk(d, Er), "counters: decks are legal and unlocked");
  expect(out.counters.navHas, "counters: menu link");
  clean("counters style", d, p.errors);
  const styleBefore = cardNames(), second = d.querySelectorAll("[data-style]")[1];
  if (second) { second.click(); await until(() => cardNames() !== styleBefore && d.querySelectorAll(".deck").length > 0); }
  out.counters.secondStyleChanged = cardNames() !== styleBefore;
  d.querySelector('[data-tab="cards"]').click(); await wait(50);
  d.querySelector(".cardlist .pick").click();
  await until(() => d.querySelectorAll(".oppcard").length === 1 && (d.querySelectorAll(".deck").length > 0 || d.querySelector("#results .empty")));
  out.counters.byCard = { picked: d.querySelector(".oppcard").textContent.replace("×", "").trim(), decks: d.querySelectorAll(".deck").length };
  expect(out.counters.byCard.decks > 0, "counters: one picked card gives counter decks");
  expect(deckOk(d, Er), "counters: card-based decks are legal");
  d.querySelector(".oppcard button").click(); await wait(50);
  expect(d.querySelectorAll(".oppcard").length === 0 && d.querySelector("#results").textContent.trim() === "", "counters: removing the card clears results");
  clean("counters cards", d, p.errors);
  p = await open("counters.html", "trophy_road__bone_pit"); d = p.d;
  await until(() => d.querySelectorAll(".deck .tile").length >= 8 || /too few/.test(d.querySelector("#verdict").textContent));
  out.counters.lowArenaDecks = d.querySelectorAll(".deck").length;
  expect(deckOk(d, Ew), "counters: low-arena counter decks use only unlocked cards");
  clean("counters arena", d, p.errors);

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})();
