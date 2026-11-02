// Future meta page checks. Expected values are read from web/future_meta.json here, not from the page's own helpers.
//   cd tests/web && node future_test.cjs     (prints JSON; exit 1 if any check fails)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");
const WEB = path.join(__dirname, "..", "..", "web");
const src = Object.fromEntries(["engine.js", "learn.js", "common.js"].map((f) => [f, fs.readFileSync(path.join(WEB, f), "utf8")]));
const { Engine } = require(path.join(WEB, "engine.js"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [], out = {};
const expect = (c, m) => { if (!c) fails.push(m); };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const F = JSON.parse(fs.readFileSync(path.join(WEB, "future_meta.json"), "utf8"));
const ranked = new Engine(JSON.parse(fs.readFileSync(path.join(WEB, "models", "ranked.json"), "utf8")));
const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";

async function open(opts = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e && (e.stack || e.message || e))));
  let html = fs.readFileSync(path.join(WEB, "future.html"), "utf8");
  for (const [f, code] of Object.entries(src)) html = html.replace(`<script src="${f}"></script>`, () => `<script>${code}</script>`);
  const dom = new JSDOM(html, {
    url: `http://localhost/future.html${opts.hash || ""}`, runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.fetch = async (u) => {
        const rel = String(u).replace(/^http:\/\/localhost\//, ""), f = path.join(WEB, rel);
        if ((opts.missing || []).includes(rel) || !fs.existsSync(f)) return { ok: false, status: 404, json: async () => ({}) };
        let j = JSON.parse(fs.readFileSync(f, "utf8"));
        if (rel === "future_meta.json" && opts.transform) j = opts.transform(j);
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
const pageText = (d) => { const v = d.body.cloneNode(true); v.querySelectorAll("script,style").forEach((s) => s.remove()); return v.textContent.replace(/\s+/g, " "); };
const ready = (d) => d.querySelector("#decklist article");

(async () => {
  let p = await open(), d = p.d;
  expect(await until(() => ready(d)), "page never drew its decks");
  const all = pageText(d);

  // ---- menu and page
  expect(text(d.querySelector('.subnav a[aria-current="page"]')) === "Future meta", "sub-menu doesn't mark the page");
  expect(text(d.querySelector('nav.nav:not(.subnav) a[aria-current]')) === "Explore trends", "Explore trends not marked as the section");
  expect(p.w.location.hash === "#ranked", "page isn't on Ranked");

  // ---- the verdict comes first and matches the export
  const heads = [...d.querySelectorAll("#body section h2")].map(text);
  out.sections = heads;
  expect(heads[0] === "Can you trust it?", "the track record is not first");
  expect(JSON.stringify(heads) === JSON.stringify(["Can you trust it?", "What makes a meta deck good?", "What may be played next", "Decks to consider", "The full track record", "Assumptions and limits"]), `sections: ${heads}`);
  const trust = text(d.querySelector("#body section"));
  out.summary = text(d.querySelector(".summary p"));
  expect(trust.includes(F.gate.passed ? "Beat no change" : "Did not beat no change"), "gate pill disagrees with the export");
  const s1 = F.forecast.cards.summary[0];
  expect(trust.includes(s1.mae.timesfm_hourly.toFixed(3)) && trust.includes(s1.mae.no_change.toFixed(3)), "headline errors not from the export");
  expect(trust.includes(`${F.gate.wins} of ${F.gate.periods}`), "periods won not from the export");
  if (s1.coverage_90 !== undefined) expect(trust.includes(pct(s1.coverage_90, 0)), "coverage not from the export");
  const ff = F.recommend.check_top.new_to_deck.lists.future_field;
  if (ff.adjusted_win_rate !== null) expect(trust.includes(pct(ff.adjusted_win_rate)), "deck check rate not from the export");
  if (!F.gate.passed) expect(/ideas to try|has not beaten/.test(out.summary), "a failed gate isn't stated first");
  const newLists = F.recommend.check_top.new_to_deck.lists, allLists = F.recommend.check_top.all_players.lists;
  const clearNew = ["most_played", "last_record", "all_candidates"].filter((k) => newLists[k].verdict === "better").length;
  expect(/no clear edge/.test(out.summary) === (clearNew === 0), "headline disagrees with the new-to-deck verdicts");
  expect(trust.includes("Across all players"), "the all-players reading isn't next to the lead check");
  if (allLists.future_field.adjusted_win_rate !== null) expect(trust.includes(pct(allLists.future_field.adjusted_win_rate)), "all-players rate not from the export");
  const pe = F.recommend.picks_estimate;
  if (pe.new_to_deck !== null && ff.adjusted_win_rate !== null) expect(trust.includes(pct(pe.new_to_deck)), "past picks' estimate not shown");
  expect(/Expect less than these estimates/.test(all) === (pe.new_to_deck !== null && ff.adjusted_win_rate !== null), "the estimates warning next to the decks");

  // ---- signals
  const T = F.quality.targets;
  const shownSignals = () => d.querySelectorAll("#target svg .hit").length;
  expect(shownSignals() === Math.min(12, T.next_edge.signals.length), "edge chart row count");
  const heldEdge = T.next_edge.signals.filter((s) => s.holds_up).length;
  expect(d.querySelectorAll('#target table tbody tr').length === T.next_edge.signals.length, "signal table not complete");
  const claim = text(d.querySelector("#target .takeaway"));
  out.edge_claim = claim;
  if (!T.next_edge.predicts) expect(/did not predict/.test(claim), "edge sentence claims prediction without R2 above 0");
  else expect(/a little better|clearly better/.test(claim), "edge sentence ignores a real out-of-time gain");
  F.data.events.forEach((e) => {
    expect(all.includes(e.text), "a recent event isn't shown");
    expect(all.includes(e.mean_abs_points.toFixed(2)), "the measured shift across the event isn't shown");
    e.new_forms.forEach((n) => expect(all.includes(ranked.name(Number(n.key.split(":")[0]))), "a card new since the event isn't named"));
    if (e.sampled_players.after && e.sampled_players.before) expect(all.includes(pct(e.sampled_players.after.win_rate)), "the sampled players' jump in win rate isn't shown");
  });
  if (F.data.events.length) {
    const svgRings = [...d.querySelectorAll("#fans circle")].filter((c) => c.getAttribute("fill") === "var(--surface)");
    expect(svgRings.length === 6, "the since-the-season-started ring isn't on every card chart");
    expect(text(d.querySelector("#fans .mcell .read")).includes("Since the season started"), "the chart's reading misses the since-season share");
    expect(F.recommend.consider.every((x) => x.since_event), "listed decks lack their since-season record");
  }
  F.data.skipped_origins.forEach((x) => expect(text(d.querySelector("#body")).includes(`the end of P${x.origin}`), `skipped origin ${x.origin} isn't stated`));
  if (heldEdge === 0 && T.next_edge.predicts) expect(/No single signal/.test(claim), "edge sentence names no-one correctly");
  d.querySelector('[data-target="next_growth"]').click(); await wait(10);
  out.growth_claim = text(d.querySelector("#target .takeaway"));
  expect(/usage/.test(text(d.querySelector("#target h3"))), "usage target didn't draw");
  expect(d.querySelector('[data-target="next_growth"]').getAttribute("aria-pressed") === "true", "target control state");
  if (!T.next_growth.predicts) expect(/did not predict/.test(out.growth_claim), "usage sentence claims prediction without R2 above 0");

  // ---- the short answer names every signal that holds up, with its size from the export
  const answer = [...d.querySelectorAll("#body section .panel.box")].find((b) => text(b.querySelector("h3")) === "The short answer");
  expect(answer, "no short answer");
  for (const [k, t] of Object.entries(T)) {
    const conv = (c) => (k === "next_edge" ? c : 100 * (Math.exp(c) - 1));
    for (const s of t.signals.filter((x) => x.holds_up)) expect(text(answer).includes(Math.abs(conv(s.coef)).toFixed(2)), `short answer misses ${s.signal} (${k})`);
  }
  out.short_answer = text(answer).slice(0, 700);

  // ---- forecast charts
  expect(d.querySelectorAll("#fans .mcell").length === 6, "not six card charts");
  const series = F.forecast.cards.series.slice().sort((a, b) => b.no_change - a.no_change);
  const first = text(d.querySelector("#fans .mcell b"));
  out.first_fan = text(d.querySelector("#fans .mcell"));
  const topEntry = series[0].key.split(":");
  expect(first.includes(ranked.name(Number(topEntry[0]))), "first chart isn't the most used card");
  expect(text(d.querySelector("#fans .mcell .read")).includes(pct(series[0].median[0])), "first chart's reading isn't its forecast");
  expect(d.querySelectorAll("#fans .mcell line.soft").length === 6, "no 'no change' line on the charts");
  expect(d.querySelector('#fans path[fill="var(--elixir)"]'), "no forecast bands drawn");
  d.querySelector('[data-fanview="moves"]').click(); await wait(10);
  const moves = F.forecast.cards.series.slice().sort((a, b) => Math.abs(b.median[0] - b.no_change) - Math.abs(a.median[0] - a.no_change));
  expect(text(d.querySelector("#fans .mcell b")).includes(ranked.name(Number(moves[0].key.split(":")[0]))), "moves view isn't sorted by predicted move");
  d.querySelector('[data-fanview="used"]').click(); await wait(10);
  const sel = d.querySelector("#fancard");
  expect(sel.options.length === F.forecast.cards.series.length + 1, "card picker doesn't list every forecast card");
  const rare = series[series.length - 1].key;
  sel.value = rare; sel.dispatchEvent(new p.w.Event("change", { bubbles: true })); await wait(10);
  expect(d.querySelectorAll("#fans .mcell").length === 7, "added card didn't draw");
  expect(/table/.test(all) && [...d.querySelectorAll("details.more summary")].some((s) => /as a table/.test(text(s))), "no table version of the charts");
  const stylesShown = [...d.querySelectorAll("section .multiples")][1].querySelectorAll(".mcell").length;
  expect(stylesShown === F.forecast.styles.series.length, "style charts incomplete");

  // ---- decks
  const R = F.recommend;
  const articles = () => [...d.querySelectorAll("#decklist article")];
  expect(articles().length === R.consider.length, "deck cards don't match the list");
  out.first_deck = text(articles()[0]).slice(0, 220);
  R.consider.forEach((x, i) => {
    const t = text(articles()[i]);
    expect(t.includes(pct(x.estimate)) && t.includes(pct(x.range[0])) && t.includes(pct(x.range[1])), `deck ${i}: estimate not from the export`);
    // real, legal decks only, linking to their own explanation
    const es = x.deck.split("|").map((k) => { const [id, form] = k.split(":"); return { id: Number(id), form }; });
    expect(es.length === 8 && ranked.checkDeck(es).legal, `deck ${i} isn't legal in the site's engine`);
    expect(/^reason\.html#ranked~/.test(articles()[i].querySelector("a.btn").getAttribute("href")), `deck ${i}: link`);
    const m = x.math;
    expect(Math.abs(m.own - m.field_mean + m.fit + m.delta - m.z_now) < 1e-3, `deck ${i}: the math rows don't add up`);
    expect(Math.abs(1 / (1 + Math.exp(-m.z_now)) - m.estimate_now) < 1e-3, `deck ${i}: log-odds and estimate disagree`);
    if (x.explain) {
      const e = x.explain.next_edge;
      expect(Math.abs(e.intercept + Object.values(e.parts).reduce((a, b) => a + b, 0) - e.prediction) < 1e-2, `deck ${i}: signal parts don't add up`);
    }
  });
  const estimates = R.consider.map((x) => x.estimate);
  expect(estimates.every((v, i) => i === 0 || v <= estimates[i - 1] + 1e-4), "decks to consider aren't in estimate order");
  const ids = (x) => new Set(x.deck.split("|").map((k) => k.split(":")[0]));
  R.consider.forEach((a, i) => R.consider.slice(0, i).forEach((b) => { const B = ids(b); expect([...ids(a)].filter((k) => !B.has(k)).length >= F.settings.min_diff, "listed decks too similar"); }));
  d.querySelector('[data-deckview="popular"]').click(); await wait(10);
  expect(articles().length === R.popular.length, "most-played view");
  expect(/most played/.test(text(articles()[0]).toLowerCase()), "most-played label");
  d.querySelector('[data-deckview="consider"]').click(); await wait(10);

  // ---- no green tick on estimates, since past picks came in below them
  expect(!d.querySelector("#decklist .pill.good"), "a deck estimate wears a good-news pill");

  // ---- track record: nothing hidden
  const rec = [...d.querySelectorAll("#body section")].find((s) => text(s.querySelector("h2")) === "The full track record");
  expect(rec.querySelectorAll("svg .hit").length >= F.forecast.cards.rows.filter((r) => r.horizon === 1).length, "per-period chart missing rows");
  for (const [k, v] of Object.entries(F.recommend.check_top.new_to_deck.lists)) if (v.adjusted_win_rate !== null) expect(text(rec).includes(pct(v.adjusted_win_rate)), `deck check: ${k} missing`);
  // a list with too few games stays in the tables, but is neither drawn nor quoted as a result
  const newCheck = F.recommend.check_top.new_to_deck.lists, labels = [...rec.querySelectorAll(".two .box h4")].find((h) => text(h) === "Players new to the deck").parentElement;
  const drawn = labels.querySelectorAll("svg .hit").length, enough = Object.entries(newCheck).filter(([k, v]) => k === "future_field" || (v.enough_games && v.adjusted_win_rate !== null)).length;
  expect(drawn === enough, `deck check chart draws ${drawn} rows, expected ${enough}`);
  // tables keep the site's table layout (a page style once turned them into grids)
  expect(!/\.nums\s*\{/.test(fs.readFileSync(path.join(WEB, "future.html"), "utf8")), "the page restyles the site's table.nums");
  expect(text(rec).includes(s1.mae.last3_mean.toFixed(3)), "last-3 baseline missing from the table");
  for (const fam of ["styles", "decks"]) expect(text(rec).includes(F.forecast[fam].summary[0].mae.timesfm_hourly.toFixed(3)), `${fam} family missing from the table`);
  if (s1.mae.replicator_mc !== undefined) expect(text(rec).includes(s1.mae.replicator_mc.toFixed(3)), "older forecast missing from the table");
  F.assumptions.forEach((a, i) => expect(all.includes(a.text.slice(0, 40)), `assumption ${i} missing`));
  expect(text(d.querySelector("#body")).includes(F.model.repo), "model not named");

  // ---- wording rules from the project
  const visible = pageText(d);
  expect(!/—/.test(visible), "em dash on the page");
  expect(!/\bundefined\b|\bNaN\b|\[object/.test(visible), `broken value on the page: ${(visible.match(/.{40}(undefined|NaN|\[object).{40}/) || [""])[0]}`);
  expect(!/best deck/i.test(visible), "a 'best deck' claim");
  expect(!/guarantee/i.test(visible), "a guarantee");
  expect(p.errors.length === 0, `script errors: ${p.errors.join(" | ")}`);
  // every interactive mark has words for keyboard and screen-reader users
  expect([...d.querySelectorAll(".chart .hit[tabindex]")].every((h) => h.getAttribute("aria-label")), "a focusable mark without a label");
  expect([...d.querySelectorAll(".chip")].every((b) => b.hasAttribute("aria-pressed")), "a toggle without its state");

  // ---- states
  p = await open({ missing: ["future_meta.json"] }); d = p.d;
  expect(await until(() => /hasn't been built/.test(pageText(d))), "missing file not explained");
  expect(p.errors.length === 0, "missing file made a script error");

  // a failed gate and no prediction must read as such, whatever the data says today
  p = await open({ transform: (j) => { j.gate = { ...j.gate, passed: false, wins: 0 }; j.quality.targets.next_edge.predicts = false; j.quality.targets.next_edge.r2 = -0.02; for (const k of Object.keys(j.recommend.check_top.new_to_deck.lists)) if (j.recommend.check_top.new_to_deck.lists[k].verdict) j.recommend.check_top.new_to_deck.lists[k].verdict = "not_clear"; return j; } }); d = p.d;
  await until(() => ready(d));
  expect(/has not beaten assuming nothing changes/.test(text(d.querySelector(".summary p"))) && /ideas to try/.test(text(d.querySelector(".summary p"))), "failed gate wording");
  expect(/did not predict/.test(text(d.querySelector("#target .takeaway"))), "no-prediction wording");
  expect(p.errors.length === 0, "failed-gate variant made a script error");

  // early-run state: no calibrated periods yet
  p = await open({ transform: (j) => { delete j.forecast.cards.summary[0].coverage_90; delete j.forecast.cards.summary[0].coverage_50; j.forecast.cards.summary[0].calibrated_periods = 0; return j; } }); d = p.d;
  await until(() => ready(d));
  expect(/Too few earlier forecasts/.test(text(d.querySelector("#body section"))), "uncalibrated wording");
  expect(!/undefined|NaN/.test(pageText(d)), "uncalibrated state shows a broken value");

  out.fails = fails;
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
