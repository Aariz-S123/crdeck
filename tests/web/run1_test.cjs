// Run 1 checks of the builder and shared page code (docs/claude-redesign/ACCEPTANCE.md R1.1–R1.6):
// document shell, picks and refusals, stale mode loads, bad links, a missing model file, wording of
// estimates and support, and the clipboard fallback. Uses the real engine and exported models.
//   cd tests/web && node run1_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const engine = fs.readFileSync(path.join(WEB, "engine.js"), "utf8");
const common = fs.readFileSync(path.join(WEB, "common.js"), "utf8");
const { Engine, deckKey } = require(path.join(WEB, "engine.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };

// opts.missing: model files that answer 404; opts.slow: {file: ms} delays; opts.clipboard: false makes writeText reject
async function open(page, hash = "", opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  const html = fs.readFileSync(path.join(WEB, page), "utf8")
    .replace('<script src="engine.js"></script>', () => `<script>${engine}</script>`)
    .replace('<script src="common.js"></script>', () => `<script>${common}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/${page}${hash ? "#" + hash : ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        if ((opts.missing || []).includes(rel) || !fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        if (opts.slow && opts.slow[rel]) await wait(opts.slow[rel]);
        const txt = fs.readFileSync(f, "utf8");
        return { ok: true, status: 200, json: async () => JSON.parse(txt) };
      };
      w.navigator.clipboard = { writeText: async () => { if (opts.clipboard === false) throw new Error("denied"); } };
      w.localStorage.clear();
    },
  });
  return { w: dom.window, d: dom.window.document, errors };
}
async function until(fn, ms = 60000) { for (let t = 0; t < ms / 50; t++) { if (fn()) return true; await wait(50); } return false; }
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const settled = (d) => !/Building|Loading/.test(text(d.querySelector("#status")));
const decksShown = (d) => d.querySelectorAll(".deck h3").length;

(async () => {
  const ranked = new Engine(JSON.parse(fs.readFileSync(path.join(WEB, "models", "ranked.json"), "utf8")));
  const trophy = new Engine(JSON.parse(fs.readFileSync(path.join(WEB, "models", "trophy_road.json"), "utf8")));

  // R1.1 document shell (layout widths are measured in a real browser by docs/claude-redesign/evidence/shots.mjs)
  for (const page of fs.readdirSync(WEB).filter((f) => f.endsWith(".html"))) {
    const h = fs.readFileSync(path.join(WEB, page), "utf8");
    expect(/^<!doctype html>/i.test(h), `${page}: no doctype`);
    expect(/<html lang="en">/.test(h), `${page}: no <html lang="en">`);
    expect(/<meta name="viewport" content="width=device-width, initial-scale=1/.test(h), `${page}: no responsive viewport meta`);
  }

  // R1.5 / R1.6 no picks: same decks as the engine, honest labels
  let p = await open("index.html", "ranked~~"), d = p.d;
  await until(() => decksShown(d) === 3 && settled(d));
  const want = ranked.complete([]);
  const shownKeys = [...d.querySelectorAll(".deck a.btn.primary")].map((a) => {
    const t = a.getAttribute("href").split("#")[1].split("~")[1];
    return deckKey(t.split("-").map((x) => ({ id: Number(x.slice(0, -1)), form: { b: "base", e: "evo", h: "hero" }[x.slice(-1)] })));
  });
  out.noPick = { keys: shownKeys, cards: [...d.querySelectorAll(".deck")].map((a) => text(a).slice(0, 400)) };
  expect(JSON.stringify(shownKeys) === JSON.stringify(want.map((x) => x.key)), "R1.6 no-pick decks differ from Engine.complete([])");
  const page = text(d.body);
  expect(!/% sure|style guess/.test(page), "R1.5 style probability still shown as 'sure'");
  expect(!/Wins more than it loses|Loses more than it wins|About even/.test(page), "R1.5 unconditional verdict wording remains");
  expect(!/strongest decks it can find/.test(page), "R1.5 'strongest decks' wording remains");
  expect(/highest-scoring options under this model/.test(page), "R1.5 neutral no-pick wording missing");
  const decks = [...d.querySelectorAll(".deck")];
  decks.forEach((el, i) => {
    const x = ranked.explain(want[i].entries);
    const t = text(el);
    if (x.score.test_battles_exact_deck === 0) {
      expect(/No exact-deck test records/.test(t), `R1.5 deck ${i + 1}: zero support not stated as 'no exact-deck test records'`);
      expect(!/won 0\b|0\.0% wins/.test(t), `R1.5 deck ${i + 1}: zero support shown as zero wins`);
    }
    expect(/Predicted style: |Suggested deck/.test(t), `R1.5 deck ${i + 1}: no 'Predicted style' heading`);
    expect(/Estimated wins against sampled opponents/.test(t) && /90% model range/.test(t), `R1.5 deck ${i + 1}: estimate label or range label missing`);
    const lo = x.score.interval[0], hi = x.score.interval[1];
    const pill = text(el.querySelector(".pill"));
    expect(lo > 0.5 ? pill === "Model estimate above 50%" : hi < 0.5 ? pill === "Model estimate below 50%" : /no clear modeled edge/.test(pill), `R1.5 deck ${i + 1}: verdict '${pill}' doesn't match its range`);
    for (const g of x.warnings) expect(t.includes(g.root_cause), `R1.6 deck ${i + 1}: warning '${g.root_cause}' not visible`);
  });
  expect(d.querySelector("#newbie") && /Exactly 8 different cards/.test(text(d.querySelector("#newbie-body"))), "R1.6 newcomer help missing or not from rules");
  expect(/Game mode/.test(text(d.querySelector("#modebar"))) && !/Learn from/.test(text(d.querySelector("#modebar"))), "R1.5 mode selector still labelled 'Learn from'");

  // R1.2 one, three, fourth pick, form change, conflicting forms, clear, locked card
  const pickBtn = (name, form = "base") => [...d.querySelectorAll("#cardlist .pick")].find((b) => {
    const n = b.querySelector(".pn").textContent.trim();
    return form === "base" ? n === name : n.startsWith(name) && n.includes(form === "evo" ? "EVO" : "HERO");
  });
  pickBtn("Hog Rider").click();
  await until(() => settled(d) && decksShown(d) === 3);
  out.onePick = text(d.querySelector("#status"));
  expect(/Hog Rider/.test(out.onePick), "R1.2 one pick not reflected");
  pickBtn("Fireball").click(); pickBtn("The Log").click(); await wait(20);
  pickBtn("Zap").click();
  out.fourth = text(d.querySelector("#seed-note"));
  expect(/already picked 3/.test(out.fourth) && d.querySelectorAll(".seed.filled").length === 3, "R1.2 fourth pick not refused with an explanation");
  d.querySelector("[data-rm]").click(); await wait(20);
  pickBtn("Knight").click(); await wait(20);
  pickBtn("Knight", "evo").click();
  out.formChange = text(d.querySelector("#seed-note"));
  expect(/one form only/.test(out.formChange), "R1.2 changing a picked card's form not explained");
  for (let k = 0; k < 3; k++) { d.querySelector("[data-rm]").click(); await wait(10); }
  expect(d.querySelectorAll(".seed.filled").length === 0, "R1.2 clear did not empty the picks");
  // three Evolutions: two slots take Evolutions (Evolution, Wild), so a third can't be placed
  ["Knight", "Archers", "Bats"].forEach((n) => pickBtn(n, "evo").click());
  await until(() => settled(d));
  out.conflict = text(d.querySelector("#decks"));
  expect(/No legal deck can hold these cards together/.test(out.conflict) && /picks are kept/.test(out.conflict), "R1.2 conflicting forms not explained");
  expect(d.querySelectorAll(".seed.filled").length === 3, "R1.2 conflicting picks were not kept");
  expect(!p.errors.length, "index script errors: " + p.errors.join(" | ").slice(0, 300));

  // R1.2 card not unlocked in a low arena
  const low = JSON.parse(fs.readFileSync(path.join(WEB, "modes.json"), "utf8")).modes.find((m) => m.slug === "trophy_road__bone_pit");
  if (low && low.status === "exported") {
    p = await open("index.html", "trophy_road__bone_pit~~"); d = p.d;
    await until(() => settled(d) && decksShown(d) === 3, 90000);
    const lockedBtn = d.querySelector("#cardlist .pick.locked");
    lockedBtn.click();
    out.locked = text(d.querySelector("#seed-note"));
    expect(/can't be picked/.test(out.locked) && d.querySelectorAll(".seed.filled").length === 0, "R1.2 locked card not refused with a reason");
  } else fails.push("R1.2 no Bone Pit export to test locked cards");

  // R1.3 rapid mode switches: a slow Trophy Road load must not draw over a later Ranked choice
  p = await open("index.html", "ranked~~28000015b", { slow: { "models/trophy_road.json": 1500 } }); d = p.d;
  await until(() => settled(d) && decksShown(d) === 3);
  d.querySelector('#modebar [data-slug="trophy_road"]').click();
  await wait(30);
  d.querySelector('#modebar [data-slug="ranked"]').click();
  await wait(2500);
  await until(() => settled(d) && decksShown(d) === 3);
  out.rapid = { facts: text(d.querySelector("#facts")), hash: p.w.location.hash };
  expect(/Ranked/.test(out.rapid.facts) && !/Trophy Road/.test(out.rapid.facts), "R1.3 slow earlier mode load drew over the newer choice");
  expect(/^#ranked~~28000015b$/.test(out.rapid.hash), "R1.3 valid pick lost across mode switches");
  const keyOfHref = (a) => deckKey(a.getAttribute("href").split("#")[1].split("~")[1].split("-").map((x) => ({ id: Number(x.slice(0, -1)), form: { b: "base", e: "evo", h: "hero" }[x.slice(-1)] })));
  const wantR = ranked.complete([{ id: 28000015, form: "base" }]).map((x) => x.key);
  expect(JSON.stringify([...d.querySelectorAll(".deck a.btn.primary")].map(keyOfHref)) === JSON.stringify(wantR), "R1.3 shown decks are not Ranked's decks for the kept pick");

  // R1.3 removal announced when a pick isn't available in the new mode
  p = await open("index.html", "trophy_road__bone_pit~~26000000e"); d = p.d;
  await until(() => settled(d) && decksShown(d) === 3, 90000);
  out.removed = text(d.querySelector("#seed-note"));
  expect(/Left out because/.test(out.removed), "R1.3 removed pick not announced");

  // R1.4 malformed percent-encoding and junk card codes
  p = await open("index.html", "ranked~~26000021b-zz-%E0%A4%A"); d = p.d;
  await until(() => settled(d) && decksShown(d) === 3);
  out.malformed = { note: text(d.querySelector("#link-note")), picks: d.querySelectorAll(".seed.filled").length };
  expect(/couldn't be read/.test(out.malformed.note) && out.malformed.picks === 1, "R1.4 malformed link crashed, lost the readable pick, or was not reported");
  expect(!p.errors.length, "R1.4 script errors on malformed link: " + p.errors.join(" | ").slice(0, 300));

  // R1.4 unknown mode vs missing model file
  p = await open("index.html", "no_such_mode~~"); d = p.d;
  await until(() => settled(d) && decksShown(d) === 3);
  out.unknown = text(d.querySelector("#fallback-note"));
  expect(/wasn't recognized/.test(out.unknown), "R1.4 unknown mode not reported");
  p = await open("index.html", "trophy_road~~", { missing: ["models/trophy_road.json"] }); d = p.d;
  await until(() => /isn't in this copy/.test(text(d.querySelector("#decks"))));
  out.missing = { msg: text(d.querySelector("#decks")), retry: !!d.querySelector("[data-retry]"), chips: d.querySelectorAll("#modebar [data-slug]").length };
  expect(/model file for Trophy Road ladder isn't in this copy/.test(out.missing.msg) && out.missing.retry, "R1.4 missing model not explained with a retry");
  expect(out.missing.chips === 3, "R1.4 configured modes hidden after a missing file");
  expect(/Technical details/.test(out.missing.msg), "R1.4 raw error not kept under technical details");
  d.querySelector('#modebar [data-slug="ranked"]').click();
  await until(() => settled(d) && decksShown(d) === 3);
  expect(decksShown(d) === 3, "R1.4 could not recover by picking another mode");

  // R1.6 clipboard blocked: the list is shown selected
  p = await open("index.html", "ranked~~", { clipboard: false }); d = p.d;
  await until(() => settled(d) && decksShown(d) === 3);
  d.querySelector("[data-copy]").click(); await wait(50);
  const fall = d.querySelector('[data-fall="0"] input');
  out.clipboard = fall ? fall.value : null;
  expect(fall && fall.value.split(", ").length === 8 && !d.querySelector('[data-fall="0"]').hidden, "R1.6 blocked clipboard gives no readable copy text");

  // explanation page: support wording and the local-search statement
  const k = want[0].entries.map((e) => `${e.id}${e.form[0]}`).join("-");
  p = await open("reason.html", `ranked~${k}~`); d = p.d;
  await until(() => d.querySelector("#short-h"));
  const rt = text(d.body);
  expect(/No exact-deck test records/.test(rt) && /Zero records is not zero wins/.test(rt), "R1.5 reason: zero support wording");
  expect(!/best version|Wins more than it loses|About even|Passes every deck check/.test(rt), "R1.5 reason: old certainty wording remains");
  expect(!p.errors.length, "reason script errors: " + p.errors.join(" | ").slice(0, 300));
  out.trophyDefault = trophy.complete([]).map((x) => x.key);

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
