/* The Balance watch page: which cards look out of line on the two numbers Supercell says it watches (use rate and
 * win rate), as two ranked lists in tiers, a map of every card, a card detail panel and the track record.
 * Reads balance_watch.json (scripts/balance_watch.py; design fixed in docs/balance/DESIGN.md) and the calendar copy
 * balance_events.json. Never loads a model file. Tiers only: the page shows no probability anywhere.
 * Needs common.js (global UI) loaded first when it runs in a page. Exposes the global CRBalance. */
(function (root) {
  "use strict";
  const Z90 = 1.6448536269514722;
  const EDGE_MAX = 4, USAGE_MAX = 0.4, SHOW_FIRST = 12, MOMENTUM_GLYPH = 0.10;
  const MAP_X = [0.003, 0.4], MAP_TICKS = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4];
  const TIER_WORD = { nerf_watch: "Watch closely", nerf_possible: "Possible", buff_watch: "Watch closely", buff_possible: "Possible", none: "No signal", not_enough_data: "Not enough data" };
  const DIR_WORD = { nerf: "possible nerf", buff: "possible buff" };
  const ROLES = [["all", "All cards"], ["win_condition", "Win conditions"], ["spell", "Spells"], ["building", "Buildings"], ["troop", "Troops"]];
  const ROLE_WORD = { win_condition: "win condition", spell: "spell", building: "building", troop: "troop" };
  const MINUS = "−";

  // ------------------------------------------------------------ pure helpers (also used by tests/web/balance_test.cjs)
  const signed = (v, d = 1) => (v >= 0 ? "+" : MINUS) + Math.abs(v).toFixed(d);
  // a share as a percentage, one more decimal under 1% so small shares stay readable
  const share = (x) => (100 * x).toFixed(Math.abs(x) < 0.01 ? 2 : 1) + "%";
  const tierDir = (t) => (t.startsWith("nerf") ? "nerf" : t.startsWith("buff") ? "buff" : null);

  // The win edge to draw. When the spread between cards is above 0 the list scored the shrunk edge, so that is shown
  // with its range. When the spread is 0 every shrunk edge is exactly 0 (DESIGN.md, Corrections, 2026-11-16): a dot at 0
  // would read as "exactly average", so the raw edge is drawn with its own 90% range and the page says so.
  function edgeOf(card, body) {
    if (!card.edge_known) return null;
    if (body.score.tau2 > 0) return { pts: card.edge_pts, lo: card.edge_lo, hi: card.edge_hi, kind: "shrunk" };
    const se = card.edge_raw_se_pts;
    if (se === null || se === undefined) return { pts: card.edge_raw_pts, lo: null, hi: null, kind: "raw" };
    return { pts: card.edge_raw_pts, lo: card.edge_raw_pts - Z90 * se, hi: card.edge_raw_pts + Z90 * se, kind: "raw" };
  }
  const crossesZero = (e) => !!e && e.lo !== null && e.lo < 0 && e.hi > 0;
  const usageOf = (card, which) => (which === "all" ? card.usage_all : card.usage_top);

  // the cards of one direction that reached a tier, in rank order
  function listOf(body, dir, role = "all") {
    return body.cards.filter((c) => tierDir(c.tier) === dir && (role === "all" || c.role === role)).sort((a, b) => a.rank - b.rank);
  }
  function tierCounts(body) {
    const n = {};
    for (const c of body.cards) n[c.tier] = (n[c.tier] || 0) + 1;
    return n;
  }
  function momentumWord(m) {
    if (m === null || m === undefined) return null;
    return m > MOMENTUM_GLYPH ? "rising" : m < -MOMENTUM_GLYPH ? "falling" : "steady";
  }
  // the sentence a screen reader hears for one row; every number in it is the one drawn
  function rowName(card, body, which = "top") {
    const e = edgeOf(card, body), u = usageOf(card, which), avg = body.reference.avg_usage, dir = tierDir(card.tier);
    const parts = [`${card.name}, ${dir ? DIR_WORD[dir] + ", " + TIER_WORD[card.tier].toLowerCase() : TIER_WORD[card.tier].toLowerCase()}.`];
    if (e) parts.push(`Win edge ${e.kind === "raw" ? "before shrinking " : ""}${signed(e.pts)} points${e.lo !== null ? `, range ${signed(e.lo)} to ${signed(e.hi)}` : ""}.`);
    else parts.push("Win edge unknown: too few games with known ratings.");
    parts.push(`Used in ${share(u)} of decks${which === "all" ? " across every league and arena" : ""}, ${u >= avg ? `about ${(u / avg).toFixed(1)} times the average card` : `the average card is in ${share(avg)}`}.`);
    const mw = momentumWord(card.momentum);
    if (mw) parts.push(`Use ${mw} this week.`);
    return parts.join(" ");
  }
  // x and y of the map, in its own units (log usage, edge points), clamped to the drawn area
  function mapPos(card, body, W, H, pad) {
    const e = edgeOf(card, body), u = Math.max(MAP_X[0], Math.min(MAP_X[1], card.usage_top || 0));
    const x = pad.l + (W - pad.l - pad.r) * (Math.log(u) - Math.log(MAP_X[0])) / (Math.log(MAP_X[1]) - Math.log(MAP_X[0]));
    const yv = (v) => pad.t + (H - pad.t - pad.b) * (1 - (Math.max(-EDGE_MAX, Math.min(EDGE_MAX, v)) + EDGE_MAX) / (2 * EDGE_MAX));
    return { x, y: yv(e ? e.pts : 0), lo: e && e.lo !== null ? yv(e.lo) : null, hi: e && e.hi !== null ? yv(e.hi) : null, known: !!e, clampedX: (card.usage_top || 0) < MAP_X[0] };
  }
  // "stale": the list says so, or its cutoff is more than three days before now
  function isStale(body, now) {
    if (body.status === "stale") return true;
    return (now - Date.parse(body.cutoff)) / 86400000 > 3;
  }
  function outsideBand(body) {
    const el = body.cards.filter((c) => c.eligible && c.wr_raw !== null && c.wr_raw !== undefined);
    return { n: el.filter((c) => c.wr_raw < body.reference.wr_band[0] || c.wr_raw > body.reference.wr_band[1]).length, of: el.length };
  }

  const api = { Z90, EDGE_MAX, USAGE_MAX, SHOW_FIRST, MAP_X, TIER_WORD, DIR_WORD, edgeOf, crossesZero, usageOf, listOf, tierCounts, momentumWord, rowName, mapPos, isStale, outsideBand, share, signed };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.CRBalance = api;
  if (typeof document === "undefined" || !root.UI || !document.getElementById("balance-page")) return;

  // ------------------------------------------------------------ the page
  const { $, esc, num } = root.UI;
  const view = { role: "all", usage: "top", all: { nerf: false, buff: false }, mapOpen: null };
  let BODY = null, CAL = null;
  const day = (iso) => UI.date(iso);
  const dayBefore = (iso) => UI.date(new Date(Date.parse(iso) - 1).toISOString());
  const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 920px)").matches;

  UI.startStatic("balance.html", async () => {
    $("#body").innerHTML = skeleton();
    try {
      const [body] = await Promise.all([UI.getJSON("balance_watch.json"), UI.loadBalance()]);
      BODY = body; CAL = UI.balanceEvents();
      render();
    } catch (e) { failed(e); }
  });

  function skeleton() {
    const rows = `<div class="skel" style="height:56px"></div>`.repeat(3);
    return `<div class="lists"><section class="panel box" aria-hidden="true">${rows}</section><section class="panel box" aria-hidden="true">${rows}</section></div>`;
  }
  function failed(e) {
    const missing = e instanceof UI.LoadError && e.kind === "missing";
    $("#body").innerHTML = `<div class="panel empty" role="alert"><b>${missing ? "The balance watch file (balance_watch.json) isn't in this copy of the site." : "The balance watch didn't load."}</b>
      <span>${missing ? "It is written by scripts/balance_watch.py. Nothing else on the site is affected." : "Check your connection and try again."}</span>
      <button class="btn" type="button" data-retry>Try again</button>
      <details class="more tech"><summary>Technical details</summary><div class="body"><code>${esc(e.message || String(e))}</code></div></details></div>`;
    $("[data-retry]").onclick = () => location.reload();
  }

  function render() {
    const b = BODY, last = b.calendar.last_event;
    const now = typeof root.CRBalanceNow === "number" ? root.CRBalanceNow : Date.now();
    const src = last ? `<a href="${esc(last.source_url)}" rel="noopener">${last.source_kind === "official" ? "official notes" : "community tracker"}</a>` : "";
    const banner = `<p class="banner" id="banner"><b>Research preview.</b> <span>Not yet tested on any real balance update.</span>
      <span>Battles ${esc(day(b.window.start))} to ${esc(dayBefore(b.window.end))}.</span>
      ${last ? `<span>Last balance update ${esc(day(last.effective_date))} (${src}).</span>` : ""} <span>Next update: date not announced.</span></p>`;
    const stale = isStale(b, now) ? `<p class="notice" id="stale" role="status"><b>These numbers are from ${esc(day(b.cutoff))}.</b> Newer battles haven't been added yet${b.status === "stale" ? ", and the balance calendar hasn't been checked against the official notes for over 45 days" : ""}.</p>` : "";
    if (b.status === "insufficient") {
      $("#body").innerHTML = banner + stale + `<div class="panel empty" id="insufficient" role="status"><b>No list right now.</b>
        <span>${last && b.window.ready_on ? `The last balance update was on ${esc(day(last.effective_date))}. This list comes back after 7 days of new battles (on ${esc(day(b.window.ready_on))}).` : esc(b.status_reason || "Too few battles since the last update.")}</span></div>` + trackHtml() + methodHtml();
      return;
    }
    const counts = tierCounts(b);
    if (view.mapOpen === null) view.mapOpen = !narrow();   // phones start with the table, wider screens with the map
    $("#body").innerHTML = banner + stale + `
      <div class="controls">
        <div class="chips" role="group" aria-label="Card type">${ROLES.map(([k, l]) => `<button class="chip" type="button" data-role="${k}" aria-pressed="${view.role === k}">${l}</button>`).join("")}</div>
        <div class="chips" role="group" aria-label="Usage shown">
          <button class="chip" type="button" data-usage="top" aria-pressed="${view.usage === "top"}">Top players</button>
          <button class="chip" type="button" data-usage="all" aria-pressed="${view.usage === "all"}">Every league and arena</button></div>
        <p class="muted small measure" id="usagenote">${view.usage === "top" ? "Usage among top Path of Legends players, the group the list is scored on." : "Usage across every Ranked league and Trophy Road arena, each counting the same. Shown for comparison only: the list is always scored on top players."}</p>
      </div>
      ${b.score.tau2 > 0 ? "" : `<p class="notice small" id="edgenote"><b>On this list the win edge adds nothing to the score.</b> After allowing for luck, the method fixed in advance found no spread between cards, so every card's shrunk edge is 0 and the order comes from usage, its weekly change and new releases. The dots show each card's edge before that step, with its own range. The project's design notes say why and how it may be repaired.</p>`}
      <div class="lists">
        ${listHtml("nerf", counts)}
        ${listHtml("buff", counts)}
      </div>
      <section class="panel box detail" id="detail" aria-labelledby="detail-h" hidden></section>
      ${mapHtml()}
      ${trackHtml()}
      ${methodHtml()}`;
    drawMap();
  }

  // ------------------------------------------------------------ the two lists
  function listHtml(dir, counts) {
    const rows = listOf(BODY, dir, view.role), avg = BODY.reference.avg_usage, open = view.all[dir];
    const head = dir === "nerf" ? "Possible nerfs" : "Possible buffs";
    const nWatch = counts[`${dir}_watch`] || 0, nPos = counts[`${dir}_possible`] || 0;
    const tickX = 8 + 144 * avg / USAGE_MAX;
    const row = (c, i) => {
      const e = edgeOf(c, BODY), u = usageOf(c, view.usage), mw = momentumWord(c.momentum);
      const X = (v) => 8 + 144 * (Math.max(-EDGE_MAX, Math.min(EDGE_MAX, v)) + EDGE_MAX) / (2 * EDGE_MAX);
      const strip = e ? `<svg class="strip" viewBox="0 0 160 26" aria-hidden="true" focusable="false">
          <line x1="8" y1="13" x2="152" y2="13" stroke="var(--line)" stroke-width="2"/>
          <line x1="${X(0)}" y1="5" x2="${X(0)}" y2="21" stroke="var(--muted)" stroke-width="1"/>
          ${e.lo !== null ? `<line class="range${crossesZero(e) ? " dashed" : ""}" x1="${X(e.lo).toFixed(1)}" y1="13" x2="${X(e.hi).toFixed(1)}" y2="13" stroke="var(--ink)" stroke-width="2"${crossesZero(e) ? ' stroke-dasharray="3 3"' : ""}/>` : ""}
          <circle class="dot" cx="${X(e.pts).toFixed(1)}" cy="13" r="4.5" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"/>
          ${i === 0 ? `<text x="8" y="25" font-size="8" fill="var(--muted)">${MINUS}4</text><text x="${X(0)}" y="25" font-size="8" fill="var(--muted)" text-anchor="middle">even</text><text x="152" y="25" font-size="8" fill="var(--muted)" text-anchor="end">+4 pts</text>` : ""}
        </svg>` : `<span class="small muted">edge unknown</span>`;
      const bar = `<svg class="ubar" viewBox="0 0 160 26" aria-hidden="true" focusable="false">
          <rect x="8" y="8" width="144" height="10" rx="3" fill="var(--sunken)"/>
          <rect class="ufill" x="8" y="8" width="${(144 * Math.min(u, USAGE_MAX) / USAGE_MAX).toFixed(1)}" height="10" rx="3" fill="${dir === "nerf" ? "var(--warn)" : "var(--wild)"}"/>
          <line x1="${tickX.toFixed(1)}" y1="4" x2="${tickX.toFixed(1)}" y2="22" stroke="var(--ink)" stroke-width="1.5"/>
          ${i === 0 ? `<text x="${tickX.toFixed(1)}" y="26" font-size="8" fill="var(--muted)" text-anchor="middle">average card</text>` : ""}
        </svg>`;
      return `<li${i >= SHOW_FIRST && !open ? " hidden" : ""}><button class="row" type="button" data-card="${c.card_id}" aria-label="${esc(rowName(c, BODY, view.usage))}">
        <span class="rtop"><span class="rank">${c.rank}</span><span class="nm">${esc(c.name)}</span><span class="pill ${dir} ${c.tier.endsWith("watch") ? "watch" : "possible"}">${TIER_WORD[c.tier]}</span></span>
        <span class="rsub small muted">${num(c.sides_top)} games by ${num(c.players_top)} players · ${ROLE_WORD[c.role]}</span>
        <span class="rviz"><span class="vlab small">Win edge</span>${strip}<span class="vlab small">Usage ${share(u)}${mw ? ` <span class="mom ${mw}" aria-hidden="true">${mw === "rising" ? "▲" : mw === "falling" ? "▼" : "–"}</span>` : ""}</span>${bar}</span>
        ${c.reasons.length ? `<span class="why small">${c.reasons.map(esc).join(" ")}</span>` : ""}
      </button></li>`;
    };
    const rest = rows.length - SHOW_FIRST;
    return `<section class="panel box list ${dir}" aria-labelledby="${dir}-h">
      <h2 id="${dir}-h">${head}</h2>
      <p class="muted small">${nWatch} to watch closely, ${nPos} possible${view.role !== "all" ? `; ${rows.length} shown for this card type` : ""}. Ranked by a score fixed in advance; press a card for its details.</p>
      ${rows.length ? `<ol class="rows" id="${dir}-list">${rows.map(row).join("")}</ol>` : `<p class="muted" id="${dir}-empty">No card of this type is on this list.</p>`}
      ${rest > 0 && !open ? `<button class="btn small" type="button" data-showall="${dir}">Show all ${rows.length}</button>` : ""}
      <details class="more alt"><summary>Show as a table</summary><div class="body"><div class="tblwrap">${tableHtml(rows, `${head}, as a table`)}</div></div></details>
    </section>`;
  }
  function tableHtml(rows, caption) {
    const e = (c) => edgeOf(c, BODY);
    return `<table class="nums"><caption class="sr">${esc(caption)}</caption><thead><tr><th scope="col">Card</th><th scope="col">Tier</th><th scope="col">Win edge (points)</th><th scope="col">90% range</th><th scope="col">Usage</th><th scope="col">Weekly change</th><th scope="col">Games</th><th scope="col">Players</th></tr></thead>
      <tbody>${rows.map((c) => `<tr><td>${esc(c.name)}</td><td>${TIER_WORD[c.tier]}</td><td>${e(c) ? signed(e(c).pts) : "unknown"}</td><td>${e(c) && e(c).lo !== null ? `${signed(e(c).lo)} to ${signed(e(c).hi)}` : "n/a"}</td><td>${share(usageOf(c, view.usage))}</td><td>${momentumWord(c.momentum) || "n/a"}</td><td>${num(c.sides_top)}</td><td>${num(c.players_top)}</td></tr>`).join("")}</tbody></table>`;
  }

  // ------------------------------------------------------------ the card detail panel
  function detail(cid) {
    const c = BODY.cards.find((x) => x.card_id === cid);
    if (!c) return;
    const e = edgeOf(c, BODY), dir = tierDir(c.tier), avg = BODY.reference.avg_usage;
    const ev = c.last_change && CAL ? CAL.events.find((x) => x.id === c.last_change.event_id) : null;
    const groups = BODY.groups.filter((g) => g.usage[String(cid)] !== null && g.usage[String(cid)] !== undefined).sort((a, b) => b.sides - a.sides);
    const change = dir === "nerf" ? `If its use falls back toward the average card (${share(avg)} of decks) and its win edge stays near even, it leaves the list.`
      : dir === "buff" ? `If more players pick it up (toward ${share(avg)} of decks, the average card) and its win edge stays near even, it leaves the list.`
      : c.eligible ? "It would join a list if its use or its win edge moved well away from the other cards'." : `It needs at least ${num(BODY.score.min_card_sides)} games by top players since the last update before it is ranked.`;
    const el = $("#detail");
    el.hidden = false;
    el.innerHTML = `<div class="dhead"><h2 id="detail-h" tabindex="-1">${esc(c.name)}</h2>
        <span class="pill ${dir || "none"}">${dir ? `${DIR_WORD[dir]} · ${TIER_WORD[c.tier].toLowerCase()}` : TIER_WORD[c.tier]}</span>
        <button class="btn small" type="button" data-close>Close</button></div>
      <dl class="kv dlist">
        <dt>Usage, top players</dt><dd>${share(c.usage_top)} of decks (90% range ${share(c.usage_lo)} to ${share(c.usage_hi)}), ${c.usage_top >= avg ? `about ${(c.usage_top / avg).toFixed(1)} times` : "under"} the average card (${share(avg)})</dd>
        <dt>Usage, every league and arena</dt><dd>${share(c.usage_all)} of decks</dd>
        <dt>Win edge</dt><dd>${e ? `${signed(e.pts, 2)} points${e.lo !== null ? ` (90% range ${signed(e.lo, 2)} to ${signed(e.hi, 2)})` : ""}${e.kind === "raw" ? ", before shrinking" : ""}${crossesZero(e) ? ". The range crosses zero, so this could be luck." : ""}` : "unknown: too few games with known ratings"}${c.edge_known ? ` <span class="muted">from ${num(c.edge_sides)} games with known ratings</span>` : ""}</dd>
        <dt>Weekly change in use</dt><dd>${c.momentum === null ? "not measured (fewer than 14 days since the last update)" : `${momentumWord(c.momentum)}: ${share(c.usage_prev)} of decks, then ${share(c.usage_last)}`}</dd>
        <dt>Games and players</dt><dd>${num(c.sides_top)} games by ${num(c.players_top)} top players</dd>
        <dt>Last balance change</dt><dd>${c.last_change ? `${esc(day(c.last_change.date))}, ${esc(c.last_change.label)}${ev ? ` (<a href="${esc(ev.source_url)}" rel="noopener">${ev.source_kind === "official" ? "official notes" : "community tracker"}</a>)` : ""}, ${num(c.days_since_change)} days before this list` : "none in the calendar (it starts in August 2026)"}</dd>
        <dt>Released in the last 60 days</dt><dd>${c.release_recent ? `yes${c.released ? ` (newest form ${esc(day(c.released))})` : ""}` : "no"}</dd>
      </dl>
      ${c.reasons.length ? `<p><b>Why it is listed:</b> ${c.reasons.map(esc).join(" ")}</p>` : ""}
      <p><b>What would change this:</b> ${esc(change)}</p>
      ${groups.length ? `<details class="more"><summary>Usage by league and arena (${groups.length})</summary><div class="body"><div class="tblwrap"><table class="nums"><caption class="sr">Usage of ${esc(c.name)} by league and arena</caption>
        <thead><tr><th scope="col">League or arena</th><th scope="col">Games</th><th scope="col">Usage</th></tr></thead><tbody>${groups.map((g) => `<tr><td>${esc(g.group)}</td><td>${num(g.sides)}</td><td>${share(g.usage[String(cid)])}</td></tr>`).join("")}</tbody></table></div></div></details>` : ""}
      <p class="muted small">This list is a research preview. It hasn't been tested on enough past updates to say how often it is right.</p>`;
    const h = $("#detail-h"); h.focus({ preventScroll: true }); UI.scrollTo(el);
  }

  // ------------------------------------------------------------ the map of every card
  function mapHtml() {
    const ob = outsideBand(BODY);
    return `<section class="panel box" aria-labelledby="map-h" id="mapsec">
      <h2 id="map-h">Where every card sits</h2>
      <p class="muted small measure">Each dot is a card: how often top players use it (left to right, on a log scale) and how much more or less often decks with it win than their players' ratings predict (up and down). The lines through dots are 90% ranges. Being far out on this map is not proof of a coming change.</p>
      <div class="key" aria-hidden="true"><span><i style="background:var(--warn)"></i>Possible nerf</span><span><i style="background:var(--wild)"></i>Possible buff</span><span><i style="background:var(--map-other)"></i>No signal</span><span><i style="background:transparent;box-shadow:inset 0 0 0 2px var(--muted)"></i>Not enough data</span></div>
      <button class="btn small" type="button" data-map aria-expanded="${!!view.mapOpen}">${view.mapOpen ? "Hide the map" : "Show the map"}</button>
      <div id="map" ${view.mapOpen ? "" : "hidden"}></div>
      <p class="muted small measure" id="bandnote">${ob.n ? `${ob.n} of ${ob.of} cards have a raw win rate outside the 45 to 55% reference range among top players.` : `Every card's raw win rate is inside the 45 to 55% reference range among top players.`} That range is community-reported, not an official rule, so it is not drawn as a target here.</p>
      <details class="more alt"${narrow() ? " open" : ""}><summary>Show every card as a table</summary><div class="body"><div class="tblwrap">${tableHtml(BODY.cards.slice().sort((a, b) => b.usage_top - a.usage_top), "Every card, most used first")}</div></div></details>
    </section>`;
  }
  function drawMap() {
    const el = $("#map"); if (!el || el.hidden) return;
    const W = 640, H = 380, pad = { l: 44, r: 14, t: 16, b: 40 };
    const xv = (u) => pad.l + (W - pad.l - pad.r) * (Math.log(u) - Math.log(MAP_X[0])) / (Math.log(MAP_X[1]) - Math.log(MAP_X[0]));
    const yv = (v) => pad.t + (H - pad.t - pad.b) * (1 - (v + EDGE_MAX) / (2 * EDGE_MAX));
    const avg = BODY.reference.avg_usage, [b0, b1] = BODY.reference.usage_band;
    let g = `<rect x="${xv(b0).toFixed(1)}" y="${pad.t}" width="${(xv(b1) - xv(b0)).toFixed(1)}" height="${H - pad.t - pad.b}" fill="var(--sunken)"/>
      <text x="${((xv(b0) + xv(b1)) / 2).toFixed(1)}" y="${pad.t + 10}" text-anchor="middle" font-size="9">7 to 9% (reported, not official)</text>`;
    for (const v of [-4, -2, 0, 2, 4]) g += `<line x1="${pad.l}" y1="${yv(v)}" x2="${W - pad.r}" y2="${yv(v)}" stroke="${v === 0 ? "var(--muted)" : "var(--grid)"}" stroke-width="1"/><text x="${pad.l - 6}" y="${yv(v) + 4}" text-anchor="end">${v === 0 ? "even" : signed(v, 0)}</text>`;
    for (const t of MAP_TICKS) g += `<text x="${xv(t).toFixed(1)}" y="${H - pad.b + 14}" text-anchor="middle">${share(t).replace(/\.0+%$/, "%")}</text>`;
    g += `<line x1="${xv(avg).toFixed(1)}" y1="${pad.t}" x2="${xv(avg).toFixed(1)}" y2="${H - pad.b}" stroke="var(--ink)" stroke-width="1" stroke-dasharray="4 3"/>
      <text x="${(xv(avg) + 4).toFixed(1)}" y="${H - pad.b - 6}" font-size="9">average card (8 ÷ ${BODY.cards.length})</text>
      <text x="${W - pad.r}" y="${H - 4}" text-anchor="end">Usage among top players (log scale) →</text><text x="${pad.l}" y="${pad.t - 4}">Win edge, points</text>`;
    const colour = (c) => (tierDir(c.tier) === "nerf" ? "var(--warn)" : tierDir(c.tier) === "buff" ? "var(--wild)" : "var(--map-other)");
    const order = BODY.cards.slice().sort((a, b) => (a.tier === "none") - (b.tier === "none") || a.usage_top - b.usage_top).reverse();
    for (const c of order) {
      const p = mapPos(c, BODY, W, H, pad), e = edgeOf(c, BODY);
      if (p.lo !== null) g += `<line x1="${p.x.toFixed(1)}" y1="${p.lo.toFixed(1)}" x2="${p.x.toFixed(1)}" y2="${p.hi.toFixed(1)}" stroke="${colour(c)}" stroke-width="1.5" opacity="0.7"/>`;
      const lines = [`${TIER_WORD[c.tier]}${tierDir(c.tier) ? ` (${DIR_WORD[tierDir(c.tier)]})` : ""}`, `used in ${share(c.usage_top)} of decks${p.clampedX ? " (drawn at the left edge)" : ""}`,
        e ? `win edge ${signed(e.pts)} points${e.lo !== null ? `, range ${signed(e.lo)} to ${signed(e.hi)}` : ""}` : "win edge unknown"];
      g += `<circle class="mdot" data-card="${c.card_id}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${c.tier.endsWith("watch") ? 5.5 : 4}" fill="${c.eligible && p.known ? colour(c) : "var(--surface)"}" stroke="${c.eligible && p.known ? "var(--surface)" : "var(--muted)"}" stroke-width="1.5" ${UI.tipAttr(c.name, lines, false)}/>`;
      if (c.tier.endsWith("watch")) g += `<text class="lbl" x="${(p.x + 7).toFixed(1)}" y="${(p.y + 4).toFixed(1)}" font-size="10">${esc(c.name)}</text>`;
    }
    const many = BODY.cards.filter((c) => c.usage_top >= 3 * avg).length, few = BODY.cards.filter((c) => c.usage_top < avg / 3).length;
    el.innerHTML = `<svg class="chart map" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`Map of ${BODY.cards.length} cards by usage and win edge. ${many} cards are used at least 3 times as often as the average card, and ${few} less than a third as often. The table below lists every card.`)}">${g}</svg>`;
  }

  // ------------------------------------------------------------ track record and method
  function trackHtml() {
    const rows = BODY.track_record || [], name = (id) => (BODY.cards.find((c) => c.card_id === id) || { name: String(id) }).name;
    const real = rows.filter((r) => !r.pilot);
    const cell = (r, b, d) => (b === "random" ? r.baselines.random[d].toFixed(1) : String(r.baselines[b][d]));
    const tr = (r) => `<tr><th scope="row">${esc(day(r.effective_date))}${r.pilot ? ' <span class="muted small">(one retrospective pilot)</span>' : ""}</th>
      <td>${r.nerf.hits} of ${r.nerf.labels_eligible}${r.nerf.hit_cards.length ? ` <span class="muted small">(${r.nerf.hit_cards.map(name).map(esc).join(", ")})</span>` : ""}</td>
      <td>${r.buff.hits} of ${r.buff.labels_eligible}${r.buff.hit_cards.length ? ` <span class="muted small">(${r.buff.hit_cards.map(name).map(esc).join(", ")})</span>` : ""}</td>
      ${["random", "usage_only", "edge_only", "band_rule", "recency", "trend"].map((b) => `<td>${cell(r, b, "nerf")} + ${cell(r, b, "buff")}</td>`).join("")}</tr>`;
    return `<section class="panel box" aria-labelledby="track-h" id="track">
      <h2 id="track-h">Track record</h2>
      <p class="measure">${real.length ? `${real.length} real update${real.length === 1 ? "" : "s"} scored so far. Fewer than 6 is too few to say how often the list is right.` : "No real update scored yet."} Every list is saved before an update and checked against the official notes afterwards; a saved list is never changed.</p>
      ${rows.length ? `${rows.some((r) => r.pilot) ? `<p class="muted small measure">The pilot was scored once, from battles collected after the update and from a smaller, less active group of players. It shows the method runs, not that it works: with 4 changed cards in each direction, a few hits can happen by chance.</p>` : ""}
        <div class="tblwrap"><table class="nums"><caption class="sr">Scored updates: changed cards found in the top ${BODY.score.k} of each list, against simple baselines</caption>
        <thead><tr><th scope="col">Update</th><th scope="col">Nerfs found</th><th scope="col">Buffs found</th><th scope="col">Random (expected)</th><th scope="col">Most and least used</th><th scope="col">Highest and lowest win edge</th><th scope="col">45 to 55% rule</th><th scope="col">Changed last time</th><th scope="col">Rising and falling use</th></tr></thead>
        <tbody>${rows.map(tr).join("")}</tbody></table></div>
        <p class="muted small measure">"Found" counts changed cards in the top ${BODY.score.k} of the list in the same direction. Baseline columns read nerfs + buffs found by each simple rule, also in its top ${BODY.score.k}.</p>` : ""}
    </section>`;
  }
  function methodHtml() {
    const w = BODY.score.weights;
    return `<details class="more panel box" id="method"><summary>How this list is made</summary><div class="body small measure">
      <p>Every number comes from top Path of Legends players' battles since the last balance update, up to 14 days. Battles on the day of an update are left out, because the hour of the change is unknown. A card needs at least ${num(BODY.score.min_card_sides)} games, and must have been out for 14 days, before it is ranked.</p>
      <ul>
        <li><b>Usage:</b> the share of decks holding the card, compared with the average card. Decks hold 8 cards, so the average card is in 8 ÷ ${BODY.cards.length} = ${share(BODY.reference.avg_usage)} of decks.</li>
        <li><b>Win edge:</b> how much more or less often decks with the card win than their players' ratings alone predict, in percentage points. It is pulled toward 0 by how noisy it is (shrinking), so a card with few games can't top the list by luck.</li>
        <li><b>Weekly change:</b> this week's usage against the week before.</li>
        <li><b>New release:</b> the card or one of its forms came out in the last 60 days. This counts toward a possible nerf only.</li>
      </ul>
      <p>Each number is turned into a score that compares the card with the others (a robust z-score), and the scores are added with fixed weights:</p>
      <div class="formula">${UI.tex(String.raw`\begin{aligned}\text{nerf} &= \max(0, z_E) + \max(0, z_U) + ${w.momentum}\max(0, z_M) + ${w.release}\,R \\ \text{buff} &= \max(0, -z_E) + \max(0, -z_U) + ${w.momentum}\max(0, -z_M)\end{aligned}`,
        `nerf = max(0, zE) + max(0, zU) + ${w.momentum} max(0, zM) + ${w.release} R;  buff = max(0, −zE) + max(0, −zU) + ${w.momentum} max(0, −zM)`, true)}</div>
      <p>A card counts toward the side with the higher score. On each side, ranks 1 to 5 with a score above 1 are "Watch closely", ranks up to 15 with a score above 0.5 are "Possible". The weights and cut-offs were written down before any result and are not tuned to past updates.</p>
      <p>Two ranges often quoted by players are shown only as references: a 45 to 55% win rate (community-reported) and 7 to 9% usage (from a reported designer interview). Neither is an official rule, and neither is used in the score.</p>
      <p>No probability is given. With one update scored, nobody can say how often a listed card really changes. That number needs at least 10 scored updates.</p>
    </div></details>
    <details class="more panel box" id="limits"><summary>Assumptions and limits</summary><div class="body small measure"><ul>
      <li>Top Path of Legends players stand in for the play the game's makers watch. The data has no tournament battles.</li>
      <li>Player ratings are assumed to capture skill well enough that the win edge is about the cards.</li>
      <li>Cards change for reasons this data can't see, such as how they feel to play against, or plans for new cards.</li>
      <li>A player's games depend on each other, so ranges come from resampling players, not single games.</li>
      <li>The balance calendar is filled from official notes where they could be read, and from a community tracker otherwise.</li>
    </ul></div></details>`;
  }

  // ------------------------------------------------------------ events
  document.addEventListener("click", (ev) => {
    if (!BODY) return;
    const t = ev.target.closest("[data-role],[data-usage],[data-showall],[data-card],[data-close],[data-map]");
    if (!t) return;
    if (t.dataset.role) { view.role = t.dataset.role; render(); const b = $(`[data-role="${view.role}"]`); if (b) b.focus(); }
    else if (t.dataset.usage) { view.usage = t.dataset.usage; render(); const b = $(`[data-usage="${view.usage}"]`); if (b) b.focus(); }
    else if (t.dataset.showall) {
      const dir = t.dataset.showall; view.all[dir] = true;
      const hidden = [...document.querySelectorAll(`#${dir}-list li[hidden]`)];
      hidden.forEach((li) => { li.hidden = false; });
      t.remove();
      if (hidden.length) hidden[0].querySelector("button").focus();
    } else if (t.hasAttribute("data-close")) { const id = $("#detail").dataset.from; $("#detail").hidden = true; const b = id && $(`.row[data-card="${id}"]`); if (b) b.focus(); }
    else if (t.hasAttribute("data-map")) { view.mapOpen = !view.mapOpen; t.setAttribute("aria-expanded", String(view.mapOpen)); t.textContent = view.mapOpen ? "Hide the map" : "Show the map"; $("#map").hidden = !view.mapOpen; drawMap(); }
    else if (t.dataset.card && t.classList.contains("row")) { $("#detail").dataset.from = t.dataset.card; detail(Number(t.dataset.card)); }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && BODY && $("#detail") && !$("#detail").hidden) { const c = $("[data-close]"); if (c) c.click(); } });
})(typeof self !== "undefined" ? self : this);
