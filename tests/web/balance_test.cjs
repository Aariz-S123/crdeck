// Balance calendar on the website: the staleness flags (UI.balanceFlags, the twin of crdeck.balance.stale_flags)
// and where the builder, deck and counters pages show them.
//   cd tests/web && node balance_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const FIX = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "balance_flags.json"), "utf8"));
const src = Object.fromEntries(["engine.js", "observed.js", "votes.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
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
    const items = f.querySelectorAll("li").length, said = Number((/(\d+) cards? here/.exec(text(f.querySelector("summary"))) || [])[1]);
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

  console.log(JSON.stringify({ out, fails }, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
