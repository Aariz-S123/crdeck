// Run 5 checks: the items of the redesign specs that Runs 1–4 deferred (docs/claude-redesign/START-HERE.md,
// BACKLOG.md and the original redesign prompt), PROMPT-PROGRESS.md "Run 5". Expected values are computed
// from the exported models and modes.json here, not taken from the pages' own helpers.
//   cd tests/web && node run5_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "observed.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine, deckKey, keyOf, parseKey, UNCERTAIN } = require(path.join(WEB, "engine.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const load = (slug) => JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8"));
const INDEX = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8"));
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const LETTER = { b: "base", e: "evo", h: "hero" }, FL = { base: "b", evo: "e", hero: "h" };
const ents = (s) => s.split("-").filter(Boolean).map((t) => ({ id: Number(t.slice(0, -1)), form: LETTER[t.slice(-1)] }));
const tok = (es) => es.map((e) => `${e.id}${FL[e.form]}`).join("-");

// opts.transform: changes a copy of modes.json served to this page only; opts.reduce: prefers-reduced-motion
async function open(page, hash = "", opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, page), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const scrolled = [];
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        if ((opts.missing || []).includes(rel) || !fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (rel === "modes.json" && opts.transform) j = opts.transform(j);
        return { ok: true, status: 200, json: async () => j };
      };
      w.navigator.clipboard = { writeText: async () => {} };
      w.Element.prototype.scrollIntoView = function (o) { scrolled.push(o); };
      w.matchMedia = (q) => ({ matches: !!opts.reduce && /reduced-motion: reduce/.test(q), media: q, addEventListener() {}, removeEventListener() {} });
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors, scrolled };
}
async function until(fn, ms = 90000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const settled = (d) => !/Building|Loading/.test(text(d.querySelector("#status")));
const pageText = (d) => { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent.replace(/\s+/g, " "); };
function clean(name, p) {
  const t = pageText(p.d);
  expect(!/\bNaN\b|\bundefined\b|\[object Object\]|Infinity/.test(t), `${name}: broken value in text`);
  expect(!t.includes("—"), `${name}: em dash in text`);
  expect(![...p.d.querySelectorAll("svg")].some((s) => /NaN|undefined|Infinity/.test(s.outerHTML)), `${name}: broken value in a chart`);
  expect(!p.errors.length, `${name}: script errors ${p.errors.join(" | ").slice(0, 300)}`);
  // causal wording for card weights was replaced by association wording
  expect(!/raised the chance of winning/.test(t), `${name}: causal card-weight wording`);
}

(async () => {
  const Er = new Engine(load("ranked"));

  // ------------------------------------------------------------ navigation: four destinations, Explore trends sub-menu
  let p = await open("index.html", "ranked~~"), d = p.d;
  await until(() => d.querySelectorAll(".deck h3").length === 3 && settled(d));
  const main = [...d.querySelectorAll("nav.nav:not(.subnav) a")].map(text);
  out.nav = main;
  expect(JSON.stringify(main) === JSON.stringify(["Build a deck", "Find counters", "Explore trends", "How it works"]), `nav: not the four destinations: ${main}`);
  expect(!d.querySelector(".subnav"), "nav: Explore sub-menu shown outside Explore trends");
  for (const [page, cur] of [["meta.html", "Card usage trends"], ["seasons.html", "Season readiness"], ["cards.html", "All cards"]]) {
    const q = await open(page, "ranked");
    await until(() => q.d.querySelector(".subnav"));
    const sub = [...q.d.querySelectorAll(".subnav a")];
    expect(sub.map(text).join("|") === "Card usage trends|Season readiness|All cards", `${page}: Explore sub-menu wrong`);
    expect(text(q.d.querySelector('.subnav a[aria-current="page"]')) === cur, `${page}: sub-menu doesn't mark the page`);
    expect(text(q.d.querySelector('nav.nav:not(.subnav) a[aria-current]')) === "Explore trends", `${page}: Explore trends not marked as the section`);
  }

  // ------------------------------------------------------------ mode bar: evidence disclosure
  const info = d.querySelector("#modeinfo");
  const entry = INDEX.modes.find((m) => m.slug === "ranked"), split = INDEX.log.export.config.collection.split;
  out.modeinfo = text(info);
  expect(info && info.tagName === "DETAILS" && info.querySelector("#groupsort"), "modebar: sort control not inside the About these battles disclosure");
  expect(new RegExp(`${Math.round(100 * split.train_frac)}%`).test(text(info)) && /test battles/.test(text(info)), "modebar: split or windows not described from the export");
  expect(text(info).includes(entry.ok_battles.toLocaleString()), "modebar: usable battle count not from modes.json");
  expect(d.querySelector("#groupsel") && !d.querySelector("#groupsel").closest("details"), "modebar: league list hidden in the disclosure");

  // ------------------------------------------------------------ builder picker: definitions, example, clear
  expect(/Troops|troops/.test(text(d.querySelector("#typedef"))), "picker: no type definition");
  d.querySelector('[data-type="spell"]').click(); await wait(20);
  expect(/^Spells /.test(text(d.querySelector("#typedef"))), "picker: type definition doesn't follow the filter");
  d.querySelector('[data-type="all"]').click(); await wait(20);
  expect(/Evolution slot takes an Evolution/.test(text(d.querySelector("#formdef"))) && /Wild slot takes/.test(text(d.querySelector("#formdef"))), "picker: form definition not from the rules");
  // the example: the most-played usable card form, computed from the export
  const mcg = Number(load("ranked").config.search.min_card_games), fg = load("ranked").strength.feature_games;
  let want = null;
  for (const [k, g] of Object.entries(fg)) {
    const e = parseKey(k), c = Er.card(e.id);
    if (!c || !Er.allowedForms(c).includes(e.form) || g < mcg || !Er.index.has(k)) continue;
    if (!want || g > want.g || (g === want.g && k < want.k)) want = { k, g };
  }
  expect(!!d.querySelector("[data-example]"), "picker: no Try an example button with no picks");
  d.querySelector("[data-example]").click();
  await until(() => settled(d) && d.querySelectorAll(".seed.filled").length === 1);
  out.example = text(d.querySelector("#seed-note"));
  expect(/^Example pick:/.test(out.example) && out.example.includes(Er.describe(parseKey(want.k))), `picker: example is not the most-played card form (${want.k})`);
  expect(p.w.location.hash === `#ranked~~${tok([parseKey(want.k)])}`, "picker: example pick not in the link");
  expect(!d.querySelector("[data-example]") && !!d.querySelector("[data-clear]"), "picker: Clear picks not offered after a pick");
  d.querySelector("[data-clear]").click(); await until(() => settled(d));
  expect(d.querySelectorAll(".seed.filled").length === 0 && /Picks cleared/.test(text(d.querySelector("#seed-note"))) && p.w.location.hash === "#ranked~~", "picker: Clear picks didn't clear, announce and update the link");
  // empty search offers a clear button
  const q = d.querySelector("#q"); q.value = "zzzz"; q.dispatchEvent(new p.w.Event("input")); await wait(20);
  expect(!!d.querySelector("[data-clearq]"), "picker: empty search has no Clear the search button");
  d.querySelector("[data-clearq]").click(); await wait(20);
  expect(q.value === "" && d.querySelectorAll("#cardlist .pick").length === 184, "picker: Clear the search didn't restore the list");

  // ------------------------------------------------------------ deck cards: style description, why it ranks here, compare
  await until(() => d.querySelectorAll(".deck h3").length === 3 && settled(d));
  const decks = [...d.querySelectorAll(".deck")];
  const keys = decks.map((dk) => ents(dk.querySelector("a.btn.primary").getAttribute("href").split("#")[1].split("~")[1]));
  decks.forEach((dk, i) => {
    const x = Er.explain(keys[i], Er.objectiveDict(Er.evaluate(keys[i]))), lab = x.archetype.label;
    const sd = text(dk.querySelector(".style-def"));
    expect(lab === UNCERTAIN ? /Mixed style/.test(sd) : sd.startsWith(`A ${lab} deck`), `deck ${i + 1}: style description doesn't match '${lab}'`);
    expect(/not model output/.test(sd), `deck ${i + 1}: style description not marked editorial`);
    const why = text(dk.querySelector(".rankwhy"));
    const m = /estimated wins (\d+\.\d+), pair synergy ([+−]\d+\.\d+), cards played together ([+−]\d+\.\d+), total (\d+\.\d+)/.exec(why);
    const num = (s) => Number(s.replace("−", "-"));
    expect(!!m, `deck ${i + 1}: Why it ranks here has no score parts`);
    if (m) {
      expect(Math.abs(num(m[1]) + num(m[2]) + num(m[3]) - num(m[4])) <= 0.02, `deck ${i + 1}: score parts don't add up`);
      expect(Math.abs(num(m[4]) - 100 * Er.evaluate(keys[i]).objective) <= 0.006 && Math.abs(num(m[1]) - 100 * x.score.meta_win_prob) <= 0.006, `deck ${i + 1}: score parts differ from the engine`);
    }
    expect(x.synergy_top[0] ? why.includes(x.synergy_top[0].pair) && /not proof/.test(why) : /often enough/.test(why), `deck ${i + 1}: strongest pair not named with its caveat`);
    expect(text(dk.querySelector(".pill")).length > 0 && /Model estimate|no clear modeled edge/.test(text(dk.querySelector(".pill"))), `deck ${i + 1}: first pill is no longer the estimate verdict`);
  });
  const cmp = d.querySelector("#compare");
  expect(cmp && cmp.tagName === "DETAILS" && !cmp.closest(".deck"), "compare: no comparison view");
  if (cmp) {
    const sets = keys.map((k) => new Set(k.map(keyOf))), shared = [...sets[0]].filter((k) => sets.every((s) => s.has(k)));
    const row = [...cmp.querySelectorAll("tbody tr")].find((r) => /In every option/.test(text(r.querySelector("th"))));
    const want = shared.length ? shared.map((k) => Er.describe(parseKey(k))).join(", ") : "no card is in all of them";
    expect(row && text(row.querySelector("td")) === want, `compare: shared cards wrong (${row && text(row.querySelector("td"))} vs ${want})`);
    const est = [...cmp.querySelectorAll("tbody tr")].find((r) => /Estimated wins/.test(text(r.querySelector("th"))));
    keys.forEach((k, i) => expect(est && text(est.querySelectorAll("td")[i]).startsWith((100 * Er.score(k).win_prob).toFixed(1) + "%"), `compare: option ${i + 1} estimate differs`));
    expect(/No option is called the best/.test(text(cmp)) && !/\bwinner\b|\bbest option\b/i.test(text(cmp).replace("No option is called the best", "")), "compare: declares a winner");
  }
  expect(/top of many estimates/.test(text(d.querySelector("#resnote"))), "results: no selection-optimism note for both sources");
  clean("builder", p);

  // early-unlock marker explained in visible text (Bone Pit has cards decks use before their wiki unlock)
  p = await open("index.html", "trophy_road__bone_pit~~"); d = p.d;
  await until(() => settled(d) && d.querySelectorAll(".deck h3").length >= 1, 90000);
  const bone = load("trophy_road__bone_pit");
  if (Object.keys(bone.availability.seen_early).length) expect(/“early” marks cards/.test(text(d.querySelector("#cardlist"))), "picker: 'early' not explained in visible text");
  expect(/Only base forms here/.test(text(d.querySelector("#formdef"))), "picker: Bone Pit form definition not from its unlocks");
  clean("builder bone pit", p);

  // ------------------------------------------------------------ deck explanation: lazy layers, chart alternatives
  const deck = keys[0];
  p = await open("reason.html", `ranked~${tok(deck)}~`); d = p.d;
  await until(() => d.querySelector("#ov-h"));
  expect(d.querySelectorAll("details.layer").length === 3 && [...d.querySelectorAll("details.layer > .body")].every((b) => !b.children.length), "reason: closed layers were rendered up front");
  expect(!d.querySelector("#map3d"), "reason: the 3D map was drawn before its layer was opened");
  const x0 = Er.explain(deck);
  if (x0.archetype.label !== UNCERTAIN) expect(text(d.querySelector(".overview .style-def")).includes(`A ${x0.archetype.label} deck`), "reason: overview has no style description");
  const ev = d.querySelector("#lay-ev"); ev.open = true;
  await until(() => ev.querySelectorAll("svg.chart").length >= 2);
  const wt = [...ev.querySelectorAll("details.alt table")][0], cal = [...ev.querySelectorAll("details.alt table")][1];
  expect(wt && wt.querySelectorAll("tbody tr").length === 8, "reason: card-weight table alternative missing");
  expect(wt && [...wt.querySelectorAll("tbody a")].every((a) => /^cards\.html#ranked~~\d+[beh]$/.test(a.getAttribute("href"))), "reason: card names don't link to All cards");
  expect(cal && cal.querySelectorAll("tbody tr").length === Er.calibration(8).bins.length, "reason: calibration table alternative missing");
  const ws = deck.map((e) => Er.coefInfo(e)).filter((c) => c.known).sort((a, b) => b.weight - a.weight);
  expect(text(ev).includes(`Takeaway: ${ws[0].name} has the highest weight`), "reason: weight chart takeaway doesn't name the top card");
  expect(/Which cards carry this deck\?/.test(text(ev)) && /not the card's own win rate/.test(text(ev)), "reason: chart title not a question or weight wording causal");
  expect(!x0.synergy_top.length || /90% Beta range/.test(text(ev)), "reason: synergy range method not named");
  expect(!d.querySelector("#map3d"), "reason: opening Evidence drew the map");
  const mt = d.querySelector("#lay-math"); mt.open = true;
  await until(() => d.querySelector("#map3d circle"));
  expect(!/\d pts</.test(d.querySelector("#neartable").innerHTML) && /pp</.test(d.querySelector("#neartable").innerHTML), "reason: nearest-card win change not in percentage points");
  expect(/doesn't mean they work well together/.test(text(d.querySelector("#mapsec"))), "reason: card map closeness not qualified");
  // reduced motion: Apply scrolls without smooth animation
  const pr = await open("reason.html", `ranked~${tok(deck)}~`, { reduce: true });
  await until(() => pr.d.querySelector("#ov-h"));
  const ap = pr.d.querySelector(".bestswap [data-apply]");
  if (ap) { ap.click(); await wait(100); expect(pr.scrolled.length && pr.scrolled.every((o) => o && o.behavior === "auto"), "reason: smooth scroll despite reduced motion"); }
  clean("reason", p);

  // ------------------------------------------------------------ shared: Escape hides tooltips, scroll boxes get a name
  const tipEl = d.querySelector("[data-tip]");
  tipEl.dispatchEvent(new p.w.FocusEvent("focusin", { bubbles: true }));
  const tip = d.getElementById("tip");
  expect(tip && !tip.hidden, "tooltip: not shown on focus");
  d.dispatchEvent(new p.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  expect(tip.hidden, "tooltip: Escape doesn't hide it");
  const box = d.querySelector(".tblwrap");
  Object.defineProperty(box, "scrollWidth", { value: 900 }); Object.defineProperty(box, "clientWidth", { value: 300 });
  p.w.UI.labelScrollers();
  expect(box.getAttribute("tabindex") === "0" && box.getAttribute("role") === "region" && /scrolls sideways/.test(box.getAttribute("aria-label")), "tables: a scrolling box isn't named and focusable");
  const css = fs.readFileSync(path.join(WEB, "app.css"), "utf8");
  expect(/\.btn\.small \{[^}]*min-height: 44px/.test(css), "css: small buttons under 44px");

  // ------------------------------------------------------------ counters: choice in the link, labels, equal-weight row
  p = await open("counters.html", "ranked~~~~Siege"); d = p.d;
  await until(() => d.querySelectorAll(".deck .tile").length >= 8);
  expect(d.querySelector('[data-style="Siege"]').getAttribute("aria-pressed") === "true", "counters: style from the link not selected");
  const other = [...d.querySelectorAll("[data-style]")].find((b) => b.dataset.style === "Bridge Spam");
  other.click(); await wait(50);
  expect(p.w.location.hash === "#ranked~~~~Bridge%20Spam", `counters: style not saved in the link (${p.w.location.hash})`);
  d.querySelector('[data-tab="cards"]').click(); await wait(20);
  [...d.querySelectorAll(".cardlist .pick")].find((b) => text(b.querySelector(".pn")) === "Hog Rider").click(); await wait(50);
  expect(p.w.location.hash === "#ranked~~26000021b", `counters: picked card not saved in the link (${p.w.location.hash})`);
  const vtext = text(d.querySelector("#verdict"));
  expect(!/Strongest decks|All real decks/.test(vtext), "counters: old 'strongest' / 'all real decks' labels remain");
  // equal-weight row, recomputed from the export: styles where every group has at least 30 games
  const bt = Er.m.matchup.backtest, st = Object.entries(bt.styles).filter(([, r]) => r.all_players && r.all_players.counter[0]);
  const inc = st.filter(([, r]) => ["counter", "field", "all"].every((g) => r.all_players[g][0] >= 30));
  const avg = (g) => inc.reduce((t, [, r]) => t + r.all_players[g][1] / r.all_players[g][0], 0) / inc.length;
  const eqRow = [...d.querySelectorAll("#verdict tr")].find((r) => /Every style counted equally/.test(text(r)));
  out.equalWeight = eqRow ? text(eqRow) : null;
  expect(eqRow && ["counter", "field", "all"].every((g, k) => text(eqRow.querySelectorAll("td")[k + 1]) === (100 * avg(g)).toFixed(1) + "%"), "counters: equal-weight row differs from the export");
  expect(/would be wrong/.test(vtext), "counters: equal-weight row claims a range");
  const q2 = await open("counters.html", "ranked~~26000021b");
  await until(() => q2.d.querySelectorAll(".oppcard").length === 1 && q2.d.querySelectorAll(".deck").length > 0);
  expect(q2.d.querySelector('[data-tab="cards"]').getAttribute("aria-pressed") === "true" && /Hog Rider/.test(text(q2.d.querySelector(".oppcard"))), "counters: card choice from the link not restored");
  const q3 = await open("counters.html", "ranked");
  await until(() => q3.d.querySelectorAll(".deck .tile").length >= 8);
  expect(q3.d.querySelectorAll('[data-style][aria-pressed="true"]').length === 1, "counters: old mode-only link broken");
  expect([...d.querySelectorAll(".ccard .nm a")].every((a) => /^cards\.html#ranked~~\d+[beh]$/.test(a.getAttribute("href"))), "counters: counter cards don't link to All cards");
  clean("counters", p);

  // forward check (web/counter_eval.json, docs/claude-redesign/EVAL-DESIGN.md)
  const EV = JSON.parse(fs.readFileSync(path.join(WEB, "counter_eval.json"), "utf8")), fe = EV.modes.ranked;
  out.forward = { retro: fe.retrospective.verdict, forward: fe.forward.verdict, matches: fe.matches_export };
  expect(fe.matches_export === true, "forward check: the retrospective counts don't reproduce the exported check");
  const fwd = d.querySelector(".fwd");
  expect(!!fwd && /Forward check/.test(text(fwd)) && /written down before/.test(text(fwd)), "forward check: block missing");
  const pills = [...d.querySelectorAll("#verdict .pill")].map(text);
  if (fe.forward.verdict === bt.verdict) expect(pills[0] === pills[1], "forward check: same verdict key shown with different words");
  const frows = [...fwd.querySelectorAll("tbody tr")];
  expect(frows.length === 4 && frows.filter((r) => /\(verdict\)/.test(text(r))).length === 2, "forward check: table lacks both versions and populations");
  const hp = fe.forward.populations[fe.forward.headline], sgn = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(100 * v).toFixed(1)}`;
  const vrow = frows.find((r) => /^Forward \(verdict\)/.test(text(r)));
  expect(vrow && text(vrow).includes(`${sgn(hp.vs_field[0])} pp (90%: ${sgn(hp.vs_field[1])} to ${sgn(hp.vs_field[2])})`), "forward check: verdict row differs from the file");
  expect(/Evidence so far: forward check: .*; retrospective check: /.test(text(d.querySelector("#results"))), "forward check: evidence line doesn't name both checks");
  const q4 = await open("counters.html", "ranked", { missing: ["counter_eval.json"] });
  await until(() => q4.d.querySelectorAll(".deck .tile").length >= 8);
  expect(!q4.d.querySelector(".fwd") && /Why "retrospective"/.test(text(q4.d.querySelector("#verdict"))) && /\(retrospective check\)/.test(text(q4.d.querySelector("#results"))), "forward check: a copy without the file breaks the page");
  clean("counters without forward file", q4);

  // ------------------------------------------------------------ All cards: observed first, model and CSV in their own views
  p = await open("cards.html", "ranked"); d = p.d;
  await until(() => d.querySelectorAll("#gtable tbody tr").length > 10);
  const heads = () => [...d.querySelectorAll("#gtable thead th")].map(text);
  out.cardsHeads = heads();
  expect(JSON.stringify(heads().slice(0, 6)) === JSON.stringify(["Card", "Role", "Elixir", "Status", "Games", "Real win rate"]), `cards: default columns ${heads()}`);
  expect(d.querySelectorAll("#gtable tbody tr").length === 187 && !heads().some((h) => /Rating|Weight/.test(h)), "cards: default view mixes model or CSV columns");
  const hog = [...d.querySelectorAll("#gtable tbody tr")].find((r) => text(r.querySelector(".cn > span:not(.drop)")) === "Hog Rider");
  expect(hog && /Troop · win condition/.test(text(hog.querySelector(".role"))), "cards: role column not from the card labels");
  const tw = Er.m.meta.train_window;
  expect(/training battles/.test(text(d.querySelector("#prov"))) && /measured/.test(text(d.querySelector("#prov"))), "cards: observed view has no provenance");
  d.querySelector('[data-view="model"]').click(); await wait(50);
  expect(heads().includes("Weight (log-odds)") && heads().includes("90% model range") && /log-odds/.test(text(d.querySelector("#prov"))) && !/raised/.test(text(d.querySelector("#prov"))), "cards: model view wrong");
  d.querySelector('[data-view="csv"]').click(); await wait(50);
  expect(heads().includes("Rating") && /no dates or sources/.test(text(d.querySelector("#prov"))), "cards: CSV view wrong");
  expect(d.querySelectorAll("#gtable tbody tr").length === 187, "cards: a view changed the rows");
  clean("cards", p);
  p = await open("cards.html", "ranked~~26000021b"); d = p.d;
  await until(() => d.querySelectorAll("#gtable tbody tr").length >= 1 && d.querySelector("#gq").value);
  expect(d.querySelector("#gq").value === "Hog Rider" && [...d.querySelectorAll("#gtable tbody .cn")].every((c) => /Hog Rider/.test(text(c))), "cards: card link doesn't open the page on that card");

  // ------------------------------------------------------------ usage trends: forecast picture, alternatives, quiet search
  const shown = (j) => { j = JSON.parse(JSON.stringify(j)); const M = j.meta, lastP = M.periods.length - 1;
    const ks = [...new Set(M.history.filter((h) => h.period === lastP && h.share > 0).map((h) => h.key))].slice(0, 8);
    M.status.state = "shown"; M.forecast = ks.map((k) => { const s = M.history.find((h) => h.key === k && h.period === lastP).share; return { key: k, median: s * 1.05, band50: [s * 0.95, s * 1.15], band90: [s * 0.8, s * 1.3] }; });
    return j; };
  p = await open("meta.html", "ranked", { transform: shown }); d = p.d;
  await until(() => d.querySelector("#fc-h"));
  const pic = d.querySelector(".fcpic");
  expect(pic && pic.querySelectorAll("svg.chart").length === 6, "meta: forecast picture missing (6 cells expected)");
  expect(pic && pic.querySelectorAll("line.nochange").length === 6 && /observed/.test(pic.innerHTML) && /forecast/.test(pic.innerHTML), "meta: forecast picture lacks the no-change line or region labels");
  expect(pic && /Next: forecast median/.test(text(pic.querySelector("details.alt"))), "meta: forecast picture has no table alternative");
  clean("meta shown", p);
  p = await open("meta.html", "ranked"); d = p.d;
  await until(() => d.querySelector("#fc-h"));
  expect(!d.querySelector(".fcpic") && /No forecast picture/.test(text(d.querySelector("#meta"))), "meta: a forecast picture drawn without forecast rows");
  expect(d.querySelectorAll("svg.chart").length === 7, "meta: chart count changed on the live export");
  expect(!d.querySelector("#tres").hasAttribute("aria-live"), "meta: lookup results are still a live region");
  const tq = d.querySelector("#tq"); tq.value = "hog"; tq.dispatchEvent(new p.w.Event("input", { bubbles: true })); await wait(50);
  expect(/card forms? match/.test(text(d.querySelector("#tstatus"))), "meta: lookup has no short status line");
  const mv = [...d.querySelectorAll("details.alt")].find((x) => /Usage changes/.test(text(x.querySelector("caption"))));
  expect(mv && mv.querySelectorAll("tbody tr").length === Math.min(14, INDEX.meta.movers.length), "meta: movers chart has no table alternative");
  clean("meta", p);

  // ------------------------------------------------------------ season readiness: dated, no "unlocks"
  p = await open("seasons.html", "ranked"); d = p.d;
  await until(() => d.querySelector("#pred-h"));
  const stx = pageText(d);
  expect(!/right now/i.test(stx) && /Most-played decks, as of /.test(stx), "seasons: snapshot called current without a date");
  expect(!/unlocks?\b/i.test(text(d.querySelector("footer"))), "seasons: footer implies the prediction unlocks by itself");
  const md = INDEX.seasons.meta_decks;
  expect(d.querySelectorAll(".decks details.alt").length === md.decks.length && d.querySelector(".decks details.alt tbody").querySelectorAll("tr").length === md.decks[0].history.length, "seasons: trend charts have no table alternative");
  clean("seasons", p);

  // ------------------------------------------------------------ How it works: one story, glossary with real examples, symbols
  p = await open("model.html", "ranked"); d = p.d;
  await until(() => d.querySelectorAll("#gloss dt").length > 10 && d.querySelector("#learn .formula"));
  const stepsB = [...d.querySelectorAll("#steps li b")].map(text);
  expect(JSON.stringify(stepsB) === JSON.stringify(["Recorded battles.", "Learned relationships.", "Candidate decks.", "Scores and recommendations.", "Tests on later battles."]), `model: steps not the five-part story (${stepsB})`);
  const dts = [...d.querySelectorAll("#gloss dt")].map(text);
  for (const t of ["Synergy and lift", "Regularization", "Training, validation and test battles", "Beam search", "Bootstrap", "Delta method", "Wilson range", "Logit and sigmoid", "Selection optimism", "Association", "Calibration", "AUC", "Log loss", "Percentage points"])
    expect(dts.includes(t), `model: glossary lacks '${t}'`);
  const gl = (t) => text([...d.querySelectorAll("#gloss div")].find((x) => text(x.querySelector("dt")) === t));
  const chosen = INDEX.log["evaluate:ranked"].strength_candidates.find((c) => c.selected);
  expect(gl("Regularization").includes(`C = ${chosen.C}`), "model: regularization example not the selected C");
  const spl = Er.m.evaluation.splits;
  expect(spl.every((s) => gl("Training, validation and test battles").includes(s.battles.toLocaleString())), "model: split example counts not from the export");
  const sl = INDEX.landscape.slices[0], lt = text(d.querySelector("#learn"));
  expect(/two-parameter slice/.test(lt) && /illustration/.test(lt) && lt.includes(`N = ${sl.n_train.toLocaleString()}`) && lt.includes(`C = ${sl.C}`), "model: loss surface symbols or slice/illustration labels missing");
  clean("model", p);

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { out.fails = fails; console.log(JSON.stringify(out, null, 1)); console.error(e); process.exit(2); });
