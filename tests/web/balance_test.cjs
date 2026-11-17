// Balance calendar on the website: the staleness flags (UI.balanceFlags, the twin of crdeck.balance.stale_flags)
// and where the builder, deck and counters pages show them. Then the Balance watch page (web/balance.html), with
// every drawn number recomputed here from balance_watch.json.
//   cd tests/web && node balance_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const FIX = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "balance_flags.json"), "utf8"));
const src = Object.fromEntries(["engine.js", "observed.js", "votes.js", "learn.js", "loss-surface.js", "futures-explorer.js", "common.js", "balance.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { UI } = require(path.join(WEB, "common.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const INDEX = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
const CAL = JSON.parse(fs.readFileSync(path.join(WEB, "balance_events.json"), "utf8"));

// opts.serve: {file: (json) => json} changes a copy of a data file for this page only; opts.missing: files answered 404
async function open(page, hash = "", opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, page), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const asked = [];
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        asked.push(rel);
        if ((opts.missing || []).includes(rel) || !fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (opts.serve && opts.serve[rel]) j = opts.serve[rel](j);
        return { ok: true, status: 200, json: async () => j };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.Element.prototype.scrollIntoView = function () {};
      w.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });
      w.localStorage.clear();
      if (opts.now) w.CRBalanceNow = opts.now;
    },
  });
  return { w: dom.window, d: dom.window.document, errors, asked };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const pageText = (d) => { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent.replace(/\s+/g, " "); };
function clean(name, p) {
  const t = pageText(p.d);
  expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(t), `${name}: broken value in text`);
  expect(!t.includes("—"), `${name}: em dash in text`);
  expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
}
const DART = 26000040; // Dart Goblin: nerfed in the official 2026-10-19 update

(async () => {
  // ---------------- 1. the shared fixture: the website's rule answers exactly as Python's
  for (const c of FIX.cases) {
    const got = UI.balanceFlags(c.entries.map(([id, form]) => ({ id, form })), FIX.calendar.events, { from: c.window[0], to: c.window[1] });
    expect(JSON.stringify(got) === JSON.stringify(c.expect), `fixture "${c.name}": got ${JSON.stringify(got)}`);
  }
  out.fixtureCases = FIX.cases.length;

  // ---------------- 2. one date format
  expect(UI.date("2026-10-19") === "Oct 19, 2026", `UI.date of a day: ${UI.date("2026-10-19")}`);
  expect(UI.date("2026-10-27 01:15 UTC") === "Oct 27, 2026", `UI.date of a time: ${UI.date("2026-10-27 01:15 UTC")}`);
  expect(UI.date("2026-10-27 01:15 UTC", true) === "Oct 27, 2026, 01:15 UTC", `UI.date with the hour: ${UI.date("2026-10-27 01:15 UTC", true)}`);
  expect(UI.date("2026-11-11T23:05:00+00:00", true) === "Nov 11, 2026, 23:05 UTC", "UI.date of an ISO time");
  expect(UI.date("not a date") === "not a date", "UI.date leaves unreadable text alone");

  // ---------------- 3. the calendar copy and the mode window
  const ranked = INDEX.modes.find((m) => m.slug === "ranked"), win = UI.modeWindow(ranked);
  expect(win && /^\d{4}-\d\d-\d\d$/.test(win.from) && win.from < win.to, `mode window ${JSON.stringify(win)}`);
  const oct19 = CAL.events.find((e) => e.id === "2026-10-19");
  expect(oct19 && oct19.source_kind === "official" && oct19.changes.some((c) => c.card_id === DART && c.label === "nerf"), "calendar copy holds the Oct 19 Dart Goblin nerf");
  const flags = UI.balanceFlags([{ id: DART, form: "base" }], CAL.events, win);
  expect(flags.some((f) => f.event_id === "2026-10-19" && f.kind === "mixed" && f.label === "nerf"), `Dart Goblin in Ranked is flagged mixed for Oct 19: ${JSON.stringify(flags)}`);
  out.rankedWindow = win;

  // ---------------- 4. builder: a deck with Dart Goblin in Ranked shows the flag
  let p = await open("index.html", `ranked~~${DART}b`);
  await until(() => p.d.querySelectorAll("#decks article.deck").length > 0);
  const decks = [...p.d.querySelectorAll("#decks article.deck")];
  expect(decks.length > 0, "builder: no decks with Dart Goblin");
  for (const [i, a] of decks.entries()) {
    const f = a.querySelector("details.balflags");
    expect(!!f, `builder deck ${i + 1}: no balance flag though it holds Dart Goblin`);
    if (!f) continue;
    const t = text(f);
    expect(/balance update/.test(text(f.querySelector("summary .baltag"))), `builder deck ${i + 1}: no "balance update" tag`);
    expect(/Dart Goblin\. Changed on Oct 19, 2026 \(nerf\)\. This card's numbers mix battles from before and after the change\./.test(t), `builder deck ${i + 1}: Dart Goblin flag text: ${t.slice(0, 200)}`);
    expect(!f.open, `builder deck ${i + 1}: the flag list starts closed`);
    // the count in the summary is the number of flagged cards, recomputed here from the deck's own tiles
    const names = [...a.querySelectorAll(".grid8 .tile .tn")].map((n) => text(n));
    const items = f.querySelectorAll("li").length, said = Number((/(\d+) changed cards?/.exec(text(f.querySelector("summary"))) || [])[1]);
    expect(items === said && items >= 1 && items <= names.length, `builder deck ${i + 1}: summary says ${said}, lists ${items}`);
    expect(a.querySelector(".health").contains(f), `builder deck ${i + 1}: flag sits under the warnings`);
  }
  expect(p.asked.includes("balance_events.json"), "builder asks for the calendar copy");
  clean("builder with flags", p);
  out.builderDecks = decks.length;
  out.builderFlagExample = decks.length ? text(decks[0].querySelector("details.balflags")).slice(0, 260) : null;
  const deckHref = decks.length ? decks[0].querySelector('a[href^="reason.html#"]').getAttribute("href") : null;

  // ---------------- 5. deck page: the same deck shows the flag in "At a glance"
  if (deckHref) {
    p = await open("reason.html", deckHref.split("#")[1]);
    await until(() => p.d.querySelector(".overview"));
    const f = p.d.querySelector(".overview .ovwarn details.balflags");
    expect(!!f && /Dart Goblin\. Changed on Oct 19, 2026 \(nerf\)/.test(text(f)), `deck page: flag missing or wrong: ${text(f).slice(0, 160)}`);
    clean("deck page with flags", p);
  }

  // ---------------- 6. counters: counter decks carry flags too (no card named: every Ranked deck list has some)
  p = await open("counters.html", "ranked");
  await until(() => p.d.querySelectorAll("#results article.deck").length > 0);
  const cdecks = [...p.d.querySelectorAll("#results article.deck")];
  const cal = CAL.events, w = UI.modeWindow(ranked);
  let cflagged = 0;
  for (const a of cdecks) {
    const link = a.querySelector('.actions a[href^="reason.html#"]').getAttribute("href").split("~")[1]; // the deck's own link, not the tech swap's
    const ents = link.split("-").map((t) => ({ id: Number(t.slice(0, -1)), form: { b: "base", e: "evo", h: "hero" }[t.slice(-1)] }));
    const want = new Set(UI.balanceFlags(ents, cal, w).map((f) => `${f.card_id}:${f.form}`)).size, f = a.querySelector("details.balflags");
    expect((f ? f.querySelectorAll("li").length : 0) === want, `counters: a deck lists ${f ? f.querySelectorAll("li").length : 0} flagged cards, expected ${want}`);
    if (f) cflagged++;
  }
  expect(cdecks.length > 0, "counters: no counter decks drawn");
  clean("counters with flags", p);
  out.counterDecks = cdecks.length; out.counterDecksFlagged = cflagged;

  // ---------------- 7. an update after the model's battles reads as "measured before the change"
  const later = (j) => { j.events.push({ id: "2026-12-01", effective_date: "2026-12-01", source_kind: "official", source_url: "https://example.invalid/", date_conflict: false, scoreable: true, partial: false,
    changes: [{ card_id: DART, name: "Dart Goblin", form: "all", label: "buff" }] }); return j; };
  p = await open("index.html", `ranked~~${DART}b`, { serve: { "balance_events.json": later } });
  await until(() => p.d.querySelectorAll("#decks article.deck details.balflags").length > 0);
  const t7 = text(p.d.querySelector("#decks article.deck details.balflags"));
  expect(/Changed on Dec 1, 2026 \(buff\)\. This card's numbers were measured before the change\./.test(t7), `"after" flag text: ${t7.slice(0, 300)}`);
  clean("builder with a later update", p);

  // ---------------- 8. a community entry says where it comes from
  const comm = CAL.events.find((e) => e.source_kind === "community" && e.changes.some((c) => ["nerf", "buff", "rework"].includes(c.label)) && e.effective_date >= win.from && e.effective_date <= win.to);
  if (comm) {
    const ch = comm.changes.find((c) => ["nerf", "buff", "rework"].includes(c.label) && c.form === "all");
    p = await open("index.html", `ranked~~${ch.card_id}b`);
    await until(() => p.d.querySelectorAll("#decks article.deck, #decks .obsnote").length > 0);
    const f = p.d.querySelector("#decks article.deck details.balflags");
    if (f) expect(/Reported changed on [A-Z][a-z]{2} \d+, 2026 \([a-z]+; from a community tracker/.test(text(f)), `community flag wording: ${text(f).slice(0, 300)}`);
    out.communityChecked = !!f;
    clean("builder with a community entry", p);
  }

  // ---------------- 9. a copy of the site without the calendar still works, with no flags
  p = await open("index.html", `ranked~~${DART}b`, { missing: ["balance_events.json"] });
  await until(() => p.d.querySelectorAll("#decks article.deck").length > 0);
  expect(p.d.querySelectorAll("#decks article.deck").length > 0 && !p.d.querySelector("details.balflags"), "without the calendar: decks draw and no flag is shown");
  clean("builder without the calendar", p);

  // ---------------- 10. a mode whose battles all come after the newest update shows no flag
  const future = (j) => { for (const m of j.modes) if (m.train_window) { m.train_window = ["2027-01-01 00:00 UTC", "2027-01-05 00:00 UTC"]; m.test_window = ["2027-01-05 00:00 UTC", "2027-01-07 00:00 UTC"]; } return j; };
  p = await open("index.html", `ranked~~${DART}b`, { serve: { "modes.json": future } });
  await until(() => p.d.querySelectorAll("#decks article.deck").length > 0);
  expect(!p.d.querySelector("details.balflags"), "battles after every update: no flag");

  // ================= the Balance watch page
  const CB = require(path.join(WEB, "balance.js"));
  const WATCH = JSON.parse(fs.readFileSync(path.join(WEB, "balance_watch.json"), "utf8"));
  const fresh = Date.parse(WATCH.cutoff) + 3600 * 1000;          // a reader one hour after the cutoff
  const openWatch = async (opts = {}) => { const q = await open("balance.html", "ranked", { now: fresh, ...opts }); await until(() => q.d.querySelector("#nerf-h, #insufficient, [data-retry]")); return q; };

  // ---------------- 11. the live list
  p = await openWatch();
  let d = p.d;
  expect(d.title === "Balance Watch · crdeck" && d.querySelectorAll("h1").length === 1, `balance page: title "${d.title}"`);
  expect(!p.asked.some((u) => /^models\/|modes\.json/.test(u)), `balance page fetched a model file: ${p.asked.join(", ")}`);
  expect(text(d.querySelector('.subnav a[aria-current="page"]')) === "Balance watch" && text(d.querySelector('nav.nav:not(.subnav) a[aria-current]')) === "Explore", "balance page: menu marks");
  const counts = CB.tierCounts(WATCH);
  for (const dir of ["nerf", "buff"]) {
    const want = CB.listOf(WATCH, dir), lis = [...d.querySelectorAll(`#${dir}-list li`)];
    expect(lis.length === want.length && want.length === (counts[`${dir}_watch`] || 0) + (counts[`${dir}_possible`] || 0), `${dir}: ${lis.length} rows, expected ${want.length}`);
    expect(lis.filter((li) => !li.hidden).length === Math.min(CB.SHOW_FIRST, want.length), `${dir}: first ${CB.SHOW_FIRST} rows shown`);
    lis.forEach((li, i) => {
      const c = want[i], b = li.querySelector("button.row"), e = CB.edgeOf(c, WATCH);
      expect(Number(b.dataset.card) === c.card_id && b.getAttribute("aria-label") === CB.rowName(c, WATCH, "top"), `${dir} row ${i + 1}: name or order`);
      const label = b.getAttribute("aria-label");
      expect(label.includes(CB.TIER_WORD[c.tier].toLowerCase()) && label.includes(CB.signed(e.pts)) && label.includes(CB.share(c.usage_top)), `${dir} row ${i + 1}: accessible name lacks its tier or numbers`);
      expect(text(b.querySelector(".pill")) === CB.TIER_WORD[c.tier], `${dir} row ${i + 1}: tier pill`);
      const range = b.querySelector("svg.strip .range");
      expect(!!range && range.classList.contains("dashed") === CB.crossesZero(e), `${dir} row ${i + 1}: range dashed iff it crosses 0`);
      const X = (v) => 8 + 144 * (Math.max(-4, Math.min(4, v)) + 4) / 8;
      expect(Math.abs(Number(b.querySelector("svg.strip .dot").getAttribute("cx")) - X(e.pts)) < 0.06, `${dir} row ${i + 1}: dot not at its edge`);
      expect(Math.abs(Number(b.querySelector("svg.ubar .ufill").getAttribute("width")) - 144 * Math.min(c.usage_top, 0.4) / 0.4) < 0.06, `${dir} row ${i + 1}: usage bar length`);
      for (const r of c.reasons) expect(text(b).includes(r), `${dir} row ${i + 1}: reason missing`);
    });
  }
  expect(!!d.querySelector("#edgenote") === !(WATCH.score.tau2 > 0), "edge note shown exactly when the shrunk edge is 0 for every card");
  const all = pageText(d);
  for (const bad of [/Grand Challenge/i, /will be (nerfed|buffed)/i, /guaranteed/i, /best deck/i, /\bprobabilit(y|ies) of\b/i, /\d+(\.\d+)?% (chance|likely)/i, /\bchance of (a )?(nerf|buff)/i])
    expect(!bad.test(all), `balance page: forbidden wording ${bad}`);
  expect(/Not affiliated with, endorsed by or sponsored by Supercell/.test(text(d.querySelector("footer"))), "balance page: non-affiliation line");
  expect(/Research preview/.test(text(d.querySelector("#banner"))) && !d.querySelector("#banner button"), "banner: research preview, can't be dismissed");
  expect(!d.querySelector("#stale"), "a fresh list shows no stale banner");
  // map: one dot per card; the table lists every card
  const dots = d.querySelectorAll("#map circle.mdot");
  expect(dots.length === WATCH.cards.length && /Map of \d+ cards/.test(d.querySelector("#map svg").getAttribute("aria-label")), `map: ${dots.length} dots for ${WATCH.cards.length} cards`);
  expect(d.querySelectorAll("#mapsec details.alt tbody tr").length === WATCH.cards.length, "map table: one row per card");
  const ob = CB.outsideBand(WATCH);
  expect(text(d.querySelector("#bandnote")).startsWith(ob.n ? `${ob.n} of ${ob.of} cards` : "Every card"), "band note: count of cards outside 45 to 55%");
  // track record: the pilot is labelled as one
  const trs = [...d.querySelectorAll("#track tbody tr")];
  expect(trs.length === WATCH.track_record.length, "track record rows");
  WATCH.track_record.forEach((r, i) => {
    expect(!r.pilot || /one retrospective pilot/.test(text(trs[i])), "pilot row not labelled");
    expect(text(trs[i]).includes(`${r.nerf.hits} of ${r.nerf.labels_eligible}`) && text(trs[i]).includes(`${r.buff.hits} of ${r.buff.labels_eligible}`), "track record hits");
  });
  expect(/No real update scored yet/.test(text(d.querySelector("#track"))) === !WATCH.track_record.some((r) => !r.pilot), "track record intro");
  clean("balance page", p);

  // ---------------- 12. show all, card type filter, usage toggle
  d.querySelector('[data-showall="nerf"]') && d.querySelector('[data-showall="nerf"]').click();
  expect(![...d.querySelectorAll("#nerf-list li")].some((li) => li.hidden) && !d.querySelector('[data-showall="nerf"]'), "Show all reveals every nerf row");
  d.querySelector('[data-role="spell"]').click();
  for (const dir of ["nerf", "buff"]) {
    const want = CB.listOf(WATCH, dir, "spell"), ids = [...d.querySelectorAll(`#${dir}-list button.row`)].map((b) => Number(b.dataset.card));
    expect(JSON.stringify(ids) === JSON.stringify(want.map((c) => c.card_id)), `${dir}: spell filter`);
  }
  d.querySelector('[data-role="all"]').click();
  d.querySelector('[data-usage="all"]').click();
  const c0 = CB.listOf(WATCH, "nerf")[0], b0 = d.querySelector(`#nerf-list button.row[data-card="${c0.card_id}"]`);
  expect(Math.abs(Number(b0.querySelector(".ufill").getAttribute("width")) - 144 * Math.min(c0.usage_all, 0.4) / 0.4) < 0.06 && b0.getAttribute("aria-label") === CB.rowName(c0, WATCH, "all"), "usage toggle draws every-league usage");
  expect(/always scored on top players/.test(text(d.querySelector("#usagenote"))), "usage toggle says the score stays on top players");
  // ---------------- 13. the detail panel
  b0.click();
  const det = d.querySelector("#detail");
  expect(!det.hidden && text(det.querySelector("h2")) === c0.name && d.activeElement === det.querySelector("h2"), "detail opens on the card and takes focus");
  const t13 = text(det);
  expect(t13.includes(CB.share(c0.usage_top)) && /research preview/i.test(t13) && /What would change this/.test(t13), "detail: usage, preview sentence, what would change it");
  if (c0.last_change) expect(t13.includes(UI.date(c0.last_change.date)), "detail: last change date");
  d.dispatchEvent(new p.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(det.hidden && d.activeElement === d.querySelector(`#nerf-list button.row[data-card="${c0.card_id}"]`), "Escape closes the detail and returns focus to the row");
  clean("balance page after interaction", p);
  out.watch = { nerf: CB.listOf(WATCH, "nerf").length, buff: CB.listOf(WATCH, "buff").length, edgeShown: CB.edgeOf(c0, WATCH).kind, track: WATCH.track_record.length };

  // ---------------- 14. states from fixtures
  p = await openWatch({ now: Date.parse(WATCH.cutoff) + 5 * 86400000 });
  expect(/These numbers are from/.test(text(p.d.querySelector("#stale"))), "stale: a list over 3 days old shows the banner");
  p = await openWatch({ serve: { "balance_watch.json": (j) => ({ ...j, status: "stale" }) } });
  expect(/hasn't been checked against the official notes/.test(text(p.d.querySelector("#stale"))), "stale status: calendar wording");
  const insuff = (j) => ({ ...j, status: "insufficient", status_reason: "the window since the last update is 3 days, under 7", cards: [], groups: [],
    calendar: { ...j.calendar, last_event: { ...j.calendar.last_event, effective_date: "2026-12-01" } }, window: { ...j.window, ready_on: "2026-12-09" } });
  p = await openWatch({ serve: { "balance_watch.json": insuff } });
  expect(/The last balance update was on Dec 1, 2026\. This list comes back after 7 days of new battles \(on Dec 9, 2026\)\./.test(text(p.d.querySelector("#insufficient"))) && !p.d.querySelector("#nerf-list"), "insufficient state");
  clean("balance page, insufficient", p);
  p = await openWatch({ missing: ["balance_watch.json"] });
  expect(/isn't in this copy of the site/.test(text(p.d.querySelector('[role="alert"]'))) && !!p.d.querySelector("[data-retry]"), "missing file: error with retry");
  clean("balance page, missing file", p);
  const shrunk = (j) => ({ ...j, score: { ...j.score, tau2: 0.0001 }, cards: j.cards.map((c) => (c.edge_known ? { ...c, edge_pts: c.edge_raw_pts / 2, edge_lo: c.edge_raw_pts / 2 - 0.3, edge_hi: c.edge_raw_pts / 2 + 0.3 } : c)) });
  p = await openWatch({ serve: { "balance_watch.json": shrunk } });
  const cs = CB.listOf(shrunk(WATCH), "nerf")[0], bs = p.d.querySelector(`#nerf-list button.row[data-card="${cs.card_id}"]`);
  expect(!p.d.querySelector("#edgenote") && bs.getAttribute("aria-label").includes(`Win edge ${CB.signed(cs.edge_pts)} points`) && !/before shrinking/.test(bs.getAttribute("aria-label")), "with a spread above 0 the shrunk edge is drawn");
  clean("balance page, shrunk edges", p);

  // ---------------- 15. one data date in every footer (WP4)
  const ST = JSON.parse(fs.readFileSync(path.join(WEB, "data_status.json"), "utf8"));
  const line = UI.dataLine(ST);
  expect(/^Data as of: deck models, battles to [A-Z][a-z]{2} \d+, \d{4}; usage forecast, battles to .+; balance watch, battles to .+\.$/.test(line), `data line: "${line}"`);
  expect(line.includes(UI.date(ST.models.last_battle)) && line.includes(UI.date(ST.future_meta.last_period_end)), "data line: dates from data_status.json");
  for (const [page, ready] of [["balance.html", "#nerf-h, #insufficient"], ["meta.html", "#fc-h"], ["index.html", "#decks article.deck"], ["counters.html", "#results article.deck"]]) {
    const q = await open(page, "ranked", { now: fresh });
    await until(() => q.d.querySelector(ready) && q.d.querySelector("footer .datadate"));
    const f = q.d.querySelector("footer .datadate");
    expect(!!f && text(f) === line && !/\d{4}-\d\d-\d\dT/.test(text(q.d.querySelector("footer"))), `${page}: footer data line "${f ? text(f) : "missing"}"`);
  }
  const q2 = await open("balance.html", "ranked", { now: fresh, missing: ["data_status.json"] });
  await until(() => q2.d.querySelector("#nerf-h"));
  await wait(200);
  expect(!q2.d.querySelector("footer .datadate"), "without data_status.json the footer has no data line");
  clean("balance page without data status", q2);
  out.dataLine = line;

  // ---------------- 16. model files in two parts (WP7): only pages that explain decks load the per-deck part
  const transfer = {};
  for (const [page, ready, wantDecks] of [["meta.html", "#fc-h", false], ["future.html", "#decklist article", false], ["seasons.html", "#pred-h", false],
    ["cards.html", "#gtable tbody tr", false], ["index.html", "#decks article.deck", true], ["counters.html", "#results article.deck", true], ["model.html", "#report tbody tr", true]]) {
    const q = await open(page, "ranked", { now: fresh });
    await until(() => q.d.querySelector(ready) && q.asked.includes("models/ranked.json"));
    await wait(100);
    const asked = q.asked.filter((u) => u.startsWith("models/"));
    expect(asked.includes("models/ranked.json") && asked.includes("models/ranked.decks.json") === wantDecks, `${page}: model parts asked ${asked.join(", ")}`);
    transfer[page] = q.asked.reduce((t, u) => t + (fs.existsSync(path.join(WEB, u)) ? fs.statSync(path.join(WEB, u)).size : 0), 0);
    clean(`${page} with split model files`, q);
  }
  const Q = await open("index.html", "ranked~~", { now: fresh });
  await until(() => Q.d.querySelector("#decks article.deck"));
  const full = require("./model_file.cjs").loadModel(path.join(WEB, "models", "ranked.json"));
  expect(text(Q.d.querySelector("#facts")).includes(`${Object.keys(full.deck_appearances).length.toLocaleString()} different decks`), "builder facts: different decks counted from the merged model");
  if (fs.existsSync(path.join(WEB, "models", "ranked.decks.json"))) {
    const meta = transfer["meta.html"], fut = transfer["future.html"];
    expect(meta < transfer["index.html"] - 4e6 && fut < transfer["index.html"] - 4e6, `split saves the per-deck part: ${JSON.stringify(transfer)}`);
  }
  out.transferBytes = transfer;

  // ---------------- 17. the made-up futures example lives on How it works, not on Future meta (WP11)
  const fq = await open("future.html", "ranked", { now: fresh });
  await until(() => fq.d.querySelector("#decklist article"));
  expect(!fq.d.querySelector(".futures-explorer") && !fq.asked.includes("futures-example.json"), "future meta: the illustrative explorer is gone");
  const toc = [...fq.d.querySelectorAll('nav.toc[aria-label="On this page"] a')];
  expect(toc.length >= 4 && toc.every((a) => fq.d.getElementById(a.getAttribute("href").slice(1))), `future meta: contents list links ${toc.length}`);
  expect(fq.d.querySelector("nav.toc").previousElementSibling === fq.d.querySelector("#body > section"), "future meta: contents list right after the verdict");
  clean("future meta after the move", fq);
  const mq = await open("model.html", "ranked", { now: fresh });
  await until(() => mq.d.querySelector("#mcexample"));
  expect(!mq.asked.includes("futures-example.json"), "how it works: the example loads only when opened");
  const mx = mq.d.querySelector("#mcexample"); mx.open = true; mx.dispatchEvent(new mq.w.Event("toggle"));
  await until(() => mq.d.querySelector("#mcexample .futures-explorer h3") && mq.asked.includes("futures-example.json"));
  const F = JSON.parse(fs.readFileSync(path.join(WEB, "future_meta.json"), "utf8"));
  expect(text(mq.d.querySelector("#mcexample .futures-explorer h3")) === `An example with 10,000 runs (the real forecast uses ${F.settings.runs.toLocaleString("en-US")})`, `how it works: example heading "${text(mq.d.querySelector("#mcexample h3"))}"`);
  expect(/illustrative/.test(text(mq.d.querySelector("#mcexample"))) && !/’/.test(fs.readFileSync(path.join(WEB, "futures-explorer.js"), "utf8")), "example keeps its disclaimer; no curly apostrophes");
  clean("how it works with the example", mq);

  console.log(JSON.stringify({ out, fails }, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
