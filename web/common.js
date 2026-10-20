/* Shared code for every page of the site: loading a mode's model, the site bar and mode
 * switch, links between pages, number formatting, the tooltip, and the charts.
 * Needs engine.js (global CRDeck) loaded first. Exposes the global UI. */
(function (root) {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";
  const signed = (x, d = 3) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);
  const PTS = 100; // ranking-score points: 1 point = 1 percentage point of estimated win rate
  const fmtPts = (v, d = 2) => (v >= 0 ? "+" : "−") + Math.abs(v * PTS).toFixed(d);
  const shorten = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const num = (n) => Number(n).toLocaleString();

  // data times are UTC ("2026-10-19 16:15:39+00:00" or "2026-10-19 10:30 UTC"); show them in the viewer's time zone
  function toDate(t) {
    let s = String(t).trim().replace(" UTC", "Z").replace(" ", "T");
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function when(t, withDate = true) {
    const d = toDate(t);
    if (!d) return String(t);
    return d.toLocaleString(undefined, Object.assign(withDate ? { month: "short", day: "numeric" } : {}, { hour: "numeric", minute: "2-digit", timeZoneName: "short" }));
  }

  // ------------------------------------------------------------ links between pages
  // A page's state travels in a plain #anchor token: <mode>~<deck>~<picked cards>,
  // each card written as its id plus b (base), e (Evolution) or h (Hero), joined by "-".
  const FORM_LETTER = { base: "b", evo: "e", hero: "h" }, LETTER_FORM = { b: "base", e: "evo", h: "hero" };
  const entTok = (e) => `${e.id}${FORM_LETTER[e.form]}`;
  function parseEnts(s) {
    if (!s) return [];
    return s.split("-").map((t) => { const m = /^(\d+)([beh])$/.exec(t); return m ? { id: Number(m[1]), form: LETTER_FORM[m[2]] } : null; }).filter(Boolean);
  }
  function token(slug, deck, seeds) {
    const d = deck && deck.length ? deck.map(entTok).join("-") : "", s = seeds && seeds.length ? seeds.map(entTok).join("-") : "";
    return s || d ? `${slug}~${d}~${s}` : slug;
  }
  function readHash() {
    const h = decodeURIComponent(location.hash.replace(/^#/, ""));
    const [slug, deck, seeds] = h.split("~");
    return { slug: slug || null, deck: deck !== undefined ? parseEnts(deck) : null, seeds: seeds !== undefined ? parseEnts(seeds) : null };
  }
  function setHash(tok) { history.replaceState(null, "", "#" + tok); }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } return null; }

  // ------------------------------------------------------------ site bar and mode switch
  const PAGES = [["index.html", "Build decks"], ["cards.html", "All cards"], ["meta.html", "Meta"], ["model.html", "How it works"]];
  const LOGO = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5c3.6 4.5 6.5 8 6.5 11.5a6.5 6.5 0 0 1-13 0C5.5 10.5 8.4 7 12 2.5z" fill="var(--elixir)"/><path d="M9.2 14.5a2.9 2.9 0 0 0 2.8 2.9" stroke="var(--surface)" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>`;
  function siteBar(page, slug) {
    const el = $("#site"); if (!el) return;
    el.innerHTML = `<a class="brand" href="index.html#${esc(slug || "")}">${LOGO}crdeck</a>
      <nav class="nav" aria-label="Pages">${PAGES.map(([href, label]) =>
        `<a href="${href}#${esc(slug || "")}"${href === page ? ' aria-current="page"' : ""}>${label}</a>`).join("")}</nav>`;
  }
  // Mode buttons (Ranked / Trophy Road / All), then a League or Arena list for the chosen mode.
  // Every configured league and arena is listed with its battle count; ones with too few battles
  // stay visible but cannot be picked. Sorted by game order or by battles.
  const MODE_SHORT = { ranked: "Ranked", trophy_road: "Trophy Road", all: "All modes" };
  function modeBar(INDEX, slug, onPick) {
    const el = $("#modebar"); if (!el) return;
    const cur = INDEX.modes.find((m) => m.slug === slug) || {};
    const tops = INDEX.modes.filter((m) => !m.group && m.status === "exported");
    const groups = INDEX.modes.filter((m) => m.group && m.mode === cur.mode);
    const sort = store("crdeck.groupSort") === "battles" ? "battles" : "order";
    const sorted = groups.slice().sort((a, b) => sort === "battles" ? b.ok_battles - a.ok_battles || a.order - b.order : a.order - b.order);
    const word = groups.length ? groups[0].group_word || "Group" : "";
    const usable = groups.filter((g) => g.status === "exported").length;
    const top = tops.find((m) => m.mode === cur.mode);
    const opt = (g) => {
      const floor = g.min_trophies !== undefined && g.min_trophies !== null ? ` (${num(g.min_trophies)}+ trophies)` : "";
      const ok = g.status === "exported";
      return `<option value="${esc(g.slug)}"${g.slug === slug ? " selected" : ""}${ok ? "" : " disabled"}>${esc(g.group)}${floor} · ${num(g.ok_battles)} battles${ok ? "" : " · too few"}</option>`;
    };
    el.innerHTML = `<span class="lab" id="modelab">Learn from</span>
      <div class="modes" role="group" aria-labelledby="modelab">${tops.map((m) => `<button class="chip" data-slug="${esc(m.slug)}" aria-pressed="${m.mode === cur.mode}"
        title="${num(m.ok_battles)} battles">${esc(MODE_SHORT[m.mode] || m.label)}</button>`).join("")}</div>
      ${groups.length ? `<div class="groupbar">
        <label class="lab" for="groupsel">${esc(word)}</label>
        <select id="groupsel" class="sel">${top ? `<option value="${esc(top.slug)}"${!cur.group ? " selected" : ""}>Every ${esc(word.toLowerCase())} · ${num(top.ok_battles)} battles</option>` : ""}${sorted.map(opt).join("")}</select>
        <label class="lab" for="groupsort">Sort</label>
        <select id="groupsort" class="sel"><option value="order"${sort === "order" ? " selected" : ""}>Game order</option><option value="battles"${sort === "battles" ? " selected" : ""}>Most battles</option></select>
        <span class="muted small">${usable} of ${groups.length} ${esc(word.toLowerCase())}s have enough battles to build from.</span>
      </div>` : ""}`;
    el.onclick = (ev) => { const b = ev.target.closest("[data-slug]"); if (b && b.dataset.slug !== slug) onPick(b.dataset.slug); };
    const gs = $("#groupsel", el), so = $("#groupsort", el);
    if (gs) gs.onchange = () => { if (gs.value !== slug) onPick(gs.value); };
    if (so) so.onchange = () => { store("crdeck.groupSort", so.value); modeBar(INDEX, slug, onPick); };
  }
  const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(`${u} answered HTTP ${r.status}`); return r.json(); });
  let INDEX = null;
  async function loadIndex() { if (!INDEX) INDEX = await getJSON("modes.json"); return INDEX; }
  function pickSlug(INDEX, wanted) {
    const ok = (s) => s && INDEX.modes.some((m) => m.slug === s && m.status === "exported");
    if (ok(wanted)) return wanted;
    const saved = store("crdeck.mode");
    return ok(saved) ? saved : INDEX.default;
  }
  async function loadMode(slug) {
    const entry = INDEX.modes.find((m) => m.slug === slug && m.status === "exported");
    const m = await getJSON(entry.file);
    store("crdeck.mode", slug);
    return { entry, m, E: new CRDeck.Engine(m) };
  }
  function facts(entry, m) {
    const el = $("#facts"); if (!el) return;
    el.innerHTML = `<span><b>${num(entry.ok_battles)}</b> ${esc(entry.label)} battles</span>
      <span><b>${num(Object.keys(m.deck_appearances || {}).length)}</b> different decks</span>
      <span>Newest battle <b>${esc(when(m.meta.counts.last_battle))}</b></span>`;
  }
  function failed(where, e) {
    const el = $(where); if (!el) return;
    el.innerHTML = `<div class="panel empty"><b>The data files did not load.</b><span>${esc(e.message)}. Check your connection and reload the page.</span></div>`;
  }

  // ------------------------------------------------------------ small pieces
  function drop(c) {
    const v = c.elixir_variable ? "?" : (c.elixir === null ? "?" : Math.round(c.elixir));
    return `<span class="drop${c.elixir_variable ? " var" : ""}" role="img" aria-label="${c.elixir_variable ? "variable" : v} elixir"><span>${v}</span></span>`;
  }
  const typeName = (c) => (c.champion ? "Champion" : c.type[0].toUpperCase() + c.type.slice(1));
  const FORM_WORD = { base: "", evo: "Evolution", hero: "Hero" };
  const SLOT_WORD = { evo: "EVO", hero: "HERO", wild: "WILD" };
  function archName(a) {
    if (a.label === CRDeck.NO_LABELS) return "Deck";
    if (a.label === CRDeck.UNCERTAIN) return "Mixed style";
    return a.label;
  }
  function tile(E, e, slots, seedIds, original) {
    const c = E.card(e.id), k = CRDeck.keyOf(e), slot = slots[k];
    const fn = e.form === "evo" ? "Evolution" : e.form === "hero" ? "Hero" : c.champion ? "Champion" : "";
    return `<div class="tile${slot ? " s-" + slot : ""}${original && !original.includes(k) ? " changed" : ""}" title="${esc(E.describe(e))}${slot ? ", " + slot + " slot" : ""}">
      ${slot ? `<span class="slot ${slot}">${SLOT_WORD[slot]}</span>` : ""}
      ${drop(c)}<span class="tn">${esc(c.name)}</span>${fn ? `<span class="fn">${fn}</span>` : ""}${seedIds && seedIds.has(e.id) ? `<span class="yours">Your pick</span>` : ""}
    </div>`;
  }
  const SLOT_KEY = `<div class="slotkey" aria-label="Slot colors"><span><i style="background:var(--evo)"></i>Evolution slot</span><span><i style="background:var(--hero)"></i>Hero slot</span><span><i style="background:var(--wild)"></i>Wild slot (Evolution, Hero or Champion)</span></div>`;
  function verdict(score) {
    // plain-language reading of the estimate and its interval, computed from them
    const [a, b] = score.interval;
    if (a > 0.5) return ["good", "Wins more than it loses"];
    if (b < 0.5) return ["bad", "Loses more than it wins"];
    return ["weak", "About even"];
  }

  // ------------------------------------------------------------ tooltip (hover and keyboard focus)
  function tipAttr(title, lines) {
    return `data-tip="${esc(JSON.stringify({ title, lines }))}" tabindex="0" aria-label="${esc(`${title}: ${lines.join("; ")}`)}"`;
  }
  function initTip() {
    const tip = document.createElement("div"); tip.id = "tip"; tip.hidden = true; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip);
    const show = (el, x, y) => {
      try { const t = JSON.parse(el.getAttribute("data-tip")); tip.innerHTML = `<b>${esc(t.title)}</b>${t.lines.map(esc).join("<br>")}`; } catch { return; }
      tip.hidden = false;
      const w = tip.offsetWidth, h = tip.offsetHeight, vw = document.documentElement.clientWidth;
      tip.style.left = Math.max(8, Math.min(vw - w - 8, x + 12)) + "px";
      tip.style.top = Math.max(8, y - h - 12) + "px";
    };
    document.body.addEventListener("pointermove", (ev) => { const el = ev.target.closest && ev.target.closest("[data-tip]"); if (el) show(el, ev.clientX, ev.clientY); else tip.hidden = true; });
    document.body.addEventListener("pointerleave", () => { tip.hidden = true; });
    document.body.addEventListener("focusin", (ev) => { const el = ev.target.closest && ev.target.closest("[data-tip]"); if (!el) return; const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); });
    document.body.addEventListener("focusout", () => { tip.hidden = true; });
  }

  // ------------------------------------------------------------ chart helpers
  function niceStep(span, n) {
    const raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / mag;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  }
  function ticks(lo, hi, n = 4) {
    const st = niceStep(hi - lo, n), out = [];
    for (let v = Math.ceil(lo / st) * st; v <= hi + st * 1e-9; v += st) out.push(Math.abs(v) < st * 1e-9 ? 0 : v);
    return out;
  }
  function tickLabel(v, step) {
    if (v === 0) return "0";
    const dec = Math.min(3, Math.max(0, -Math.floor(Math.log10(step) + 1e-9) + (step / Math.pow(10, Math.floor(Math.log10(step))) === 2.5 ? 1 : 0)));
    return (v > 0 ? "+" : "−") + Math.abs(v).toFixed(dec);
  }
  function barPath(x0, x1, y, h) {
    // square at the zero baseline, 4px rounded at the data end
    const r = Math.min(4, Math.abs(x1 - x0) / 2, h / 2);
    if (Math.abs(x1 - x0) < 0.5) return `M${x0},${y}h0.5v${h}h-0.5z`;
    if (x1 > x0) return `M${x0},${y}H${x1 - r}A${r},${r} 0 0 1 ${x1},${y + r}V${y + h - r}A${r},${r} 0 0 1 ${x1 - r},${y + h}H${x0}Z`;
    return `M${x0},${y}H${x1 + r}A${r},${r} 0 0 0 ${x1},${y + r}V${y + h - r}A${r},${r} 0 0 0 ${x1 + r},${y + h}H${x0}Z`;
  }

  // win-rate meter: 40% to 60% (widened in 5-point steps if the interval reaches past it), 50% marked
  function meter(score) {
    const [a, b] = score.interval, p = score.meta_win_prob;
    const lo = Math.min(0.4, Math.floor(a * 20) / 20), hi = Math.max(0.6, Math.ceil(b * 20) / 20);
    const W = 300, X = (v) => 8 + (W - 16) * (v - lo) / (hi - lo);
    return `<svg viewBox="0 0 ${W} 34" role="img" aria-label="Estimated win rate ${pct(p)}, likely between ${pct(a)} and ${pct(b)}">
      <line x1="8" y1="12" x2="${W - 8}" y2="12" stroke="var(--line)" stroke-width="4" stroke-linecap="round"/>
      <line x1="${X(0.5)}" y1="4" x2="${X(0.5)}" y2="20" stroke="var(--muted)" stroke-width="1"/>
      <line x1="${X(a)}" y1="12" x2="${X(b)}" y2="12" stroke="var(--elixir)" stroke-width="6" stroke-linecap="round" opacity="0.35"/>
      <circle cx="${X(p)}" cy="12" r="5.5" fill="var(--elixir)" stroke="var(--surface)" stroke-width="2"/>
      <text x="8" y="31" font-size="10" fill="var(--muted)">${Math.round(lo * 100)}%</text>
      <text x="${X(0.5)}" y="31" font-size="10" fill="var(--muted)" text-anchor="middle">50% (even)</text>
      <text x="${W - 8}" y="31" font-size="10" fill="var(--muted)" text-anchor="end">${Math.round(hi * 100)}%</text>
    </svg>`;
  }

  // regression weight (log-odds) of each card form with its 90% interval
  function coefChart(items) {
    const z = 1.6448536269514722;
    let lo = Math.min(0, ...items.map((it) => it.weight - z * (it.se || 0))), hi = Math.max(0, ...items.map((it) => it.weight + z * (it.se || 0)));
    const pad = (hi - lo) * 0.08 || 0.01; lo -= pad; hi += pad;
    const W = 360, L = 134, R = 12, rowH = 26, top = 6, H = top + items.length * rowH + 22;
    const X = (v) => L + (W - L - R) * (v - lo) / (hi - lo);
    let g = ticks(lo, hi, 4).map((v) => `<line x1="${X(v)}" y1="${top}" x2="${X(v)}" y2="${H - 18}" stroke="var(--grid)" stroke-width="1"/>
      <text x="${X(v)}" y="${H - 5}" text-anchor="middle">${tickLabel(v, niceStep(hi - lo, 4))}</text>`).join("");
    g += `<line x1="${X(0)}" y1="${top}" x2="${X(0)}" y2="${H - 18}" stroke="var(--muted)" stroke-width="1"/>`;
    items.forEach((it, k) => {
      const y = top + k * rowH + rowH / 2, col = it.role === "old" ? "var(--muted)" : "var(--elixir)", ci = z * (it.se || 0);
      g += `<text class="lbl" x="${L - 10}" y="${y + 4}" text-anchor="end">${esc((it.role === "old" ? "Now: " : "") + shorten(it.name, 19))}</text>`;
      g += it.known
        ? `<line x1="${X(it.weight - ci)}" y1="${y}" x2="${X(it.weight + ci)}" y2="${y}" stroke="${col}" stroke-width="2" stroke-linecap="round"/>
           <circle cx="${X(it.weight)}" cy="${y}" r="4.5" fill="${col}" stroke="var(--surface)" stroke-width="2"/>`
        : `<text x="${X(0) + 6}" y="${y + 4}">not enough games</text>`;
      g += `<rect class="hit" x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" ${tipAttr(it.name, it.known
        ? [`weight ${signed(it.weight, 4)}`, `90% range ${(it.weight - ci).toFixed(4)} to ${(it.weight + ci).toFixed(4)}`, `${num(it.games)} games to learn from`]
        : ["no learned weight: too few games to learn from"])}/>`;
    });
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="group" aria-label="How much each card helps, as learned from battles">${g}</svg>`;
  }

  // the regression line (model win rate by deck strength) over real held-out results
  function lineChart(E, CAL, deckU, deckWp) {
    const bins = CAL.bins;
    const us = bins.map((b) => b.u).concat([deckU]);
    let x0 = Math.min(...us), x1 = Math.max(...us); const xp = (x1 - x0) * 0.08 || 0.02; x0 -= xp; x1 += xp;
    const curve = []; for (let k = 0; k <= 40; k++) { const u = x0 + (x1 - x0) * k / 40; curve.push([u, E.winProbFromU(u)]); }
    const ys = bins.flatMap((b) => [b.lo, b.hi]).concat(curve.map((c) => c[1]), [deckWp, 0.5]);
    let y0 = Math.min(...ys), y1 = Math.max(...ys); const yp = (y1 - y0) * 0.1 || 0.01; y0 -= yp; y1 += yp;
    const W = 360, H = 224, L = 42, R = 12, T = 20, B = 36;
    const X = (u) => L + (W - L - R) * (u - x0) / (x1 - x0), Y = (p) => T + (H - T - B) * (1 - (p - y0) / (y1 - y0));
    const yStep = niceStep((y1 - y0) * 100, 4) / 100, xStep = niceStep(x1 - x0, 4);
    let g = "";
    ticks(y0, y1, 4).forEach((v) => { g += `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/>
      <text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${(v * 100).toFixed(yStep * 100 < 1 ? 1 : 0)}%</text>`; });
    ticks(x0, x1, 4).forEach((v) => { g += `<text x="${X(v)}" y="${H - B + 14}" text-anchor="middle">${tickLabel(v, xStep)}</text>`; });
    g += `<line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" stroke="var(--line)" stroke-width="1"/>`;
    g += `<text x="${L}" y="${T - 8}">Win rate</text><text x="${W - R}" y="${H - 4}" text-anchor="end">Deck strength (sum of card weights) →</text>`;
    bins.forEach((b) => {
      g += `<line x1="${X(b.u)}" y1="${Y(b.lo)}" x2="${X(b.u)}" y2="${Y(b.hi)}" stroke="var(--ink)" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
        <circle cx="${X(b.u)}" cy="${Y(b.win)}" r="4" fill="var(--ink)" stroke="var(--surface)" stroke-width="2"/>
        <rect class="hit" x="${X(b.u) - 9}" y="${T}" width="18" height="${H - T - B}" ${tipAttr("Real decks in the test battles", [
          `won ${pct(b.win)} (90% range ${pct(b.lo)} to ${pct(b.hi)})`, `the line predicts ${pct(b.model)}`,
          `${num(b.battles)} appearances of ${num(b.decks)} decks`])}/>`;
    });
    g += `<path d="${curve.map((c, k) => `${k ? "L" : "M"}${X(c[0]).toFixed(1)},${Y(c[1]).toFixed(1)}`).join("")}" fill="none" stroke="var(--elixir)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const dx = X(deckU), dy = Y(deckWp), right = dx > W - 120;
    g += `<line x1="${dx}" y1="${dy}" x2="${dx}" y2="${H - B}" stroke="var(--elixir)" stroke-width="1" opacity="0.6"/>
      <circle cx="${dx}" cy="${dy}" r="6" fill="var(--elixir)" stroke="var(--surface)" stroke-width="2"/>
      <text class="lbl" x="${right ? dx - 10 : dx + 10}" y="${dy - 9}" text-anchor="${right ? "end" : "start"}" font-weight="700">This deck ${pct(deckWp)}</text>
      <rect class="hit" x="${dx - 10}" y="${dy - 10}" width="20" height="20" ${tipAttr("This deck", [`strength ${signed(deckU, 3)}`, `estimated win rate ${pct(deckWp)}`,
        deckU > bins[bins.length - 1].uHi ? "stronger than every group of real decks: the line is extended past the data" : "inside the range of real decks"])}/>`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="group" aria-label="Predicted win rate by deck strength, with real results">${g}</svg>`;
  }

  // one small multiple per swap: the ranking-score change split into its exact parts
  function partsChart(x, dom) {
    const rows = x.parts.concat([{ key: "total", label: "Total change", value: x.total, detail: "the number swaps are ranked by" }]);
    const W = 360, L = 134, R = 50, rowH = 20, top = 4, H = top + rows.length * rowH + 4;
    const X = (v) => L + (W - L - R) * (v + dom) / (2 * dom);
    let g = `<line x1="${X(0)}" y1="${top}" x2="${X(0)}" y2="${H - 2}" stroke="var(--muted)" stroke-width="1"/>`;
    rows.forEach((r, k) => {
      const tot = r.key === "total", h = tot ? 13 : 10, y = top + k * rowH + (rowH - h) / 2;
      if (tot) g += `<line x1="0" y1="${top + k * rowH}" x2="${W}" y2="${top + k * rowH}" stroke="var(--line)" stroke-width="1"/>`;
      g += `<text class="${tot ? "lbl" : ""}" x="${L - 10}" y="${y + h / 2 + 4}" text-anchor="end"${tot ? ' font-weight="700"' : ""}>${esc(r.label)}</text>
        <path d="${barPath(X(0), X(r.value), y, h)}" fill="${r.value >= 0 ? "var(--pos)" : "var(--neg)"}"/>`;
      if (tot) g += `<text class="val" x="${r.value >= 0 ? X(r.value) + 5 : X(r.value) - 5}" y="${y + h / 2 + 4}" text-anchor="${r.value >= 0 ? "start" : "end"}">${fmtPts(r.value)}</text>`;
      g += `<rect class="hit" x="0" y="${top + k * rowH}" width="${W}" height="${rowH}" ${tipAttr(r.label, [`${fmtPts(r.value, 3)} points`, r.detail])}/>`;
    });
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="group" aria-label="Score change split by cause">${g}</svg>`;
  }

  // ------------------------------------------------------------ tables and the model-notes text
  function fmtCell(v) {
    if (v === null || v === undefined) return "n/a";
    if (Array.isArray(v)) return v.map(fmtCell).join(" to ");
    if (typeof v === "number") return Number.isInteger(v) ? num(v) : (Math.abs(v) < 1e-3 && v !== 0 ? v.toExponential(2) : v.toFixed(4));
    if (typeof v === "boolean") return v ? "yes" : "no";
    if (typeof v === "object") return esc(JSON.stringify(v));
    return esc(String(v));
  }
  function recordsTable(rows, caption) {
    if (!rows || !rows.length) return `<p class="muted small">No rows.</p>`;
    const cols = Object.keys(rows[0]);
    return `<table class="nums">${caption ? `<caption class="sr">${esc(caption)}</caption>` : ""}<thead><tr>${cols.map((c) => `<th scope="col">${esc(c.replace(/_/g, " "))}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${fmtCell(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  function kv(obj) {
    return `<dl class="kv">${Object.entries(obj).filter(([, v]) => typeof v !== "object" || v === null || Array.isArray(v))
      .map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${fmtCell(v)}</dd>`).join("")}</dl>`;
  }
  function md(text) {
    // minimal Markdown for docs/model-notes.md: paragraphs, bullets, tables, **bold**, `code`
    const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const out = []; let list = null, table = null;
    const flush = () => { if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } if (table) { out.push(`<div class="tblwrap"><table class="nums">${table.join("")}</table></div>`); table = null; } };
    for (const line of text.split("\n")) {
      if (/^\s*\|/.test(line)) {
        if (/^\s*\|\s*-/.test(line)) continue;
        const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
        if (!table) { flush(); table = [`<tr>${cells.map((c) => `<th scope="col">${c}</th>`).join("")}</tr>`]; } else table.push(`<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`);
      } else if (/^\s*- /.test(line)) { if (table) flush(); (list = list || []).push(`<li>${inline(line.replace(/^\s*- /, ""))}</li>`); }
      else if (!line.trim()) flush();
      else if (/^### /.test(line)) { flush(); out.push(`<p><b>${inline(line.slice(4))}</b></p>`); }
      else { flush(); out.push(`<p>${inline(line)}</p>`); }
    }
    flush();
    return out.join("");
  }

  // ------------------------------------------------------------ page start
  // Loads the index and the mode named in the link (or the last one used), draws the site bar
  // and mode switch, then calls render({INDEX, entry, m, E}). Switching mode reloads the model.
  async function start(page, render, opts = {}) {
    document.documentElement.lang = "en";
    initTip();
    try {
      await loadIndex();
      const h = readHash(), slug = pickSlug(INDEX, h.slug);
      const go = async (s, first) => {
        if (opts.onLoading) opts.onLoading();
        const ctx = await loadMode(s);
        ctx.INDEX = INDEX; ctx.hash = first ? h : { slug: s, deck: null, seeds: null };
        siteBar(page, s); modeBar(INDEX, s, (n) => go(n, false).catch((e) => failed(opts.failTarget || "main", e)));
        facts(ctx.entry, ctx.m);
        render(ctx);
      };
      siteBar(page, slug);
      await go(slug, true);
    } catch (e) {
      siteBar(page, null);
      failed(opts.failTarget || "main", e);
    }
  }

  root.UI = { $, esc, pct, signed, fmtPts, shorten, num, when, toDate, entTok, parseEnts, token, readHash, setHash, store,
    drop, typeName, FORM_WORD, archName, tile, SLOT_KEY, verdict, tipAttr, niceStep, ticks, tickLabel, barPath,
    meter, coefChart, lineChart, partsChart, fmtCell, recordsTable, kv, md, start, failed };
})(typeof self !== "undefined" ? self : this);
