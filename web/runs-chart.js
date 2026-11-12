/* The live forecast, one Monte Carlo run at a time. future_paths.json holds a fixed sample of the runs that
   future_meta.json summarizes (scripts/future_meta.py writes both). Thin lines are single real runs; every range and
   middle value quoted here counts all runs and comes from future_meta.json. Nothing on this chart is illustrative.

   One card: is it likely to be played more or less, and how sure is that? Each run is colored by whether it ends above
   or below the latest measured share, and the counts lead.

   Compare cards: do they rise and fall together? Within one step, run r holds every card at once (one joint draw), so
   the same run can be read across cards. The cards share a scale as change from the share now (a rebased chart), and a
   pair grid shows every two cards against each other: scatter, correlation, and each card's own spread. */
(() => {
  "use strict";
  const HIST = 6;                      // measured periods shown before the forecast
  const NEAR = 14;                     // how close (chart units) the pointer must be to pick up a run
  const CMP_RUNS = 60;                 // runs drawn per card when several cards share the chart
  const CMP_MAX = 4, CMP_POOL = 40;    // cards compared at once; the most used cards searched for the opening comparison
  const COLORS = ["var(--elixir)", "var(--wild)", "var(--hero)", "var(--evo)"];
  let C = null, P = null, G = null;    // page context, the runs file, the geometry of the drawn chart
  const st = { mode: "one", fam: "cards", key: "", bands: true, tfm: true, pinned: 0, hover: 0, frame: 0, played: false, cmp: [], step: 0 };
  const $ = (s) => document.querySelector(s);
  const esc = (s) => UI.esc(s), pct = (x, d) => UI.pct(x, d), num = (n) => UI.num(n);
  const narrow = () => document.documentElement.clientWidth < 620;
  const still = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const name = (fam, key) => (fam === "cards" ? C.keyName(key) : C.styleName(key));
  const series = (fam) => C.F.forecast[fam].series.slice().sort((a, b) => b.no_change - a.no_change);
  const seriesOf = (fam, key) => C.F.forecast[fam].series.find((s) => s.key === key);
  const hours = (i) => C.F.settings.hours_per_step * (i + 1);
  // runs[step][run] as shares, for the chosen series; null when the file doesn't hold it
  function runsOf(fam, key) {
    const k = P && P[fam] ? P[fam].keys.indexOf(key) : -1;
    return k < 0 ? null : P[fam].runs[k].map((step) => step.map((v) => v * P.unit));
  }
  const above = (step, level) => step.filter((v) => v > level).length;
  const below = (step, level) => step.filter((v) => v < level).length;
  // what the drawn runs say about the last step, in plain words; the thresholds are shares of the drawn runs
  function verdict(up, down) {
    const u = up / (up + down || 1);
    if (u >= 0.9) return ["up", "very likely to be played more"];
    if (u >= 0.7) return ["up", "more likely to be played more than less"];
    if (u <= 0.1) return ["down", "very likely to be played less"];
    if (u <= 0.3) return ["down", "more likely to be played less than more"];
    return ["even", "could go either way"];
  }
  // ------------------------------------------------------------ two cards across the same runs
  const mean = (a) => a.reduce((t, v) => t + v, 0) / a.length;
  const median = (a) => { const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  function corr(a, b) {                // Pearson correlation
    const ma = mean(a), mb = mean(b);
    let sab = 0, sa = 0, sb = 0;
    for (let i = 0; i < a.length; i++) { const x = a[i] - ma, y = b[i] - mb; sab += x * y; sa += x * x; sb += y * y; }
    return sa && sb ? sab / Math.sqrt(sa * sb) : 0;
  }
  function sides(a, b) {               // runs where both land on the same side of their own middle, and on opposite sides
    const ma = median(a), mb = median(b);
    let same = 0, opposite = 0;
    for (let i = 0; i < a.length; i++) { const p = (a[i] - ma) * (b[i] - mb); if (p > 0) same++; else if (p < 0) opposite++; }
    return [same, opposite];
  }
  // below this, a correlation from this many runs can't be told from no link (95%, Fisher's approximation)
  const clear = () => 1.96 / Math.sqrt(Math.max(1, P.shown - 3));
  const signed = (r) => `${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}`;
  function linkWords(r) {
    const a = Math.abs(r);
    if (a < clear()) return "no clear link";
    return r > 0 ? (a >= 0.5 ? "move together" : "lean together") : (a >= 0.5 ? "move opposite ways" : "lean opposite ways");
  }

  function markup() {
    return `<div class="panel box runs" id="runs">
      <h3 id="runs-h">Will it be played more or less? Every line is one possible answer</h3>
      <div class="controls" role="group" aria-label="One card or several"><span class="lab">Show</span>
        <button class="chip" type="button" data-runs-mode="one" aria-pressed="true">One card</button>
        <button class="chip" type="button" data-runs-mode="compare" aria-pressed="false">Compare cards</button></div>
      <p class="runs-take" id="runs-take">A forecast is one number, and it will be off by some amount. This chart shows by how much.</p>
      <p id="runs-intro"></p>
      <div class="controls" id="runs-c-one" role="group" aria-label="What the runs chart shows">
        <label class="lab" for="runs-series">Card or style</label><select id="runs-series" class="sel"></select>
        <button class="chip" type="button" data-runs-toggle="bands" aria-pressed="true">50% and 90% ranges</button>
        <button class="chip" type="button" data-runs-toggle="tfm" aria-pressed="true">TimesFM's guess</button>
        <button class="chip" type="button" id="runs-play">Replay the runs</button>
      </div>
      <div class="controls" id="runs-c-cmp" role="group" aria-label="Which cards to compare" hidden>
        <span id="runs-chosen" class="runs-chosen"></span>
        <label class="lab" for="runs-add">Add a card</label><select id="runs-add" class="sel"></select>
        <span class="lab">Compare at</span><span id="runs-steps" class="runs-chosen"></span>
      </div>
      <div class="key" id="runs-key"></div>
      <div id="runs-stage" class="runs-stage"><div class="skel" style="height:240px"></div></div>
      <div id="runs-pairs" class="runs-pairs" hidden></div>
      <p id="runs-read" class="runs-read" role="status"></p>
      <label class="runs-trace" for="runs-trace"><span class="lab">Follow one run</span><input type="range" id="runs-trace" min="0" max="1" step="1" value="0"><output id="runs-trace-out" for="runs-trace">none</output></label>
      <div id="runs-stats"></div>
      <details class="more"><summary id="runs-table-sum">These runs as a table</summary><div class="body" id="runs-table"></div></details>
      <p class="muted small" id="runs-note"></p>
    </div>`;
  }

  function mount(context) {
    C = context;
    if (!$("#runs")) return;
    fetch("future_paths.json").then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((j) => { P = j; start(); })
      .catch(() => fail(`<b>The single runs haven't been saved in this copy of the site.</b> They live in future_paths.json, which <code>python scripts/future_meta.py</code> writes next to future_meta.json. The rest of this page doesn't need it.`));
  }
  function fail(html) {
    $("#runs-stage").innerHTML = `<p class="notice" role="status">${html}</p>`;
    ["#runs-take", "#runs-intro", "#runs .controls", "#runs-c-one", "#runs-c-cmp", "#runs-key", "#runs-pairs", "#runs-read", "#runs .runs-trace", "#runs-stats", "#runs details", "#runs-note"].forEach((s) => { const el = $(s); if (el) el.hidden = true; });
  }

  const listed = (fam) => series(fam).filter((s) => runsOf(fam, s.key));
  function start() {
    // both files must come from one run of the script, or the lines and the ranges would describe different forecasts
    if (P.written_at !== C.F.written_at) {
      return fail(`<b>The saved runs are from a different forecast than this page.</b> future_paths.json was written ${esc(P.written_at)}, future_meta.json ${esc(C.F.written_at)}. Run <code>python scripts/future_meta.py</code> to write both again.`);
    }
    const opts = (fam) => listed(fam).map((s) => `<option value="${fam}:${esc(s.key)}">${esc(name(fam, s.key))}</option>`).join("");
    const sel = $("#runs-series");
    sel.innerHTML = `<optgroup label="Cards, most used first">${opts("cards")}</optgroup><optgroup label="Deck styles">${opts("styles")}</optgroup>`;
    if (!sel.value) return fail("<b>No forecast series has saved runs.</b>");
    // start on the card whose runs agree most about the direction, so the first picture has something to say;
    // ties go to the more used card
    let first = null, lean = -1;
    listed("cards").forEach((s) => {
      const end = runsOf("cards", s.key).pop(), d = Math.abs(above(end, s.no_change) - below(end, s.no_change));
      if (d > lean) { lean = d; first = s; }
    });
    if (first) sel.value = `cards:${first.key}`;
    choose(sel.value);
    st.cmp = openingComparison();
    sel.addEventListener("change", () => { choose(sel.value); draw(); play(); });
    $("#runs-add").addEventListener("change", (ev) => {
      const k = ev.target.value;
      if (k && st.cmp.length < CMP_MAX && !st.cmp.includes(k)) { st.cmp.push(k); draw(); }
    });
    $("#runs").addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-runs-toggle]"), m = ev.target.closest("[data-runs-mode]"), x = ev.target.closest("[data-runs-remove]"), h = ev.target.closest("[data-runs-step]");
      if (t) { st[t.dataset.runsToggle] = !st[t.dataset.runsToggle]; t.setAttribute("aria-pressed", String(st[t.dataset.runsToggle])); draw(); }
      if (m && m.dataset.runsMode !== st.mode) {
        st.mode = m.dataset.runsMode; st.pinned = 0; st.hover = 0; $("#runs-trace").value = "0";
        document.querySelectorAll("[data-runs-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b === m)));
        draw();
      }
      if (x && st.cmp.length > 2) { st.cmp = st.cmp.filter((k) => k !== x.dataset.runsRemove); draw(); }
      if (h) { st.step = Number(h.dataset.runsStep); draw(); }
      if (ev.target.closest("#runs-play")) play();
    });
    const trace = $("#runs-trace");
    trace.max = String(P.shown);
    trace.addEventListener("input", () => { st.pinned = Number(trace.value); st.hover = 0; mark(); });
    const stage = $("#runs-stage");
    stage.addEventListener("pointermove", (ev) => { const r = nearest(ev); if (r !== st.hover) { st.hover = r; mark(); } });
    stage.addEventListener("pointerleave", () => { if (st.hover) { st.hover = 0; mark(); } });
    stage.addEventListener("click", (ev) => { if (st.mode !== "one") return; const r = nearest(ev); st.pinned = r === st.pinned ? 0 : r; trace.value = String(st.pinned); mark(); });
    draw();
    // the first time the chart scrolls into view, the runs are drawn one after another
    if (window.IntersectionObserver && !still()) {
      const seen = new IntersectionObserver((e) => { if (e.some((x) => x.isIntersecting) && !st.played) { seen.disconnect(); play(); } }, { threshold: 0.35 });
      seen.observe(stage);
    }
  }
  function choose(value) {
    const cut = value.indexOf(":");
    st.fam = value.slice(0, cut); st.key = value.slice(cut + 1); st.pinned = 0; st.hover = 0;
    const trace = $("#runs-trace"); if (trace) trace.value = "0";
  }
  // the comparison it opens on: among the most used cards, the two most strongly linked one step ahead (either way),
  // then the card that most moves against the first of them, so the opening grid shows both kinds of link
  function openingComparison() {
    const pool = listed("cards").slice(0, CMP_POOL).map((s) => ({ key: s.key, v: runsOf("cards", s.key)[0] }));
    if (pool.length < 2) return pool.map((p) => p.key);
    let best = [0, 1], top = -1;
    for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) { const r = Math.abs(corr(pool[i].v, pool[j].v)); if (r > top) { top = r; best = [i, j]; } }
    const out = [pool[best[0]].key, pool[best[1]].key];
    let third = -1, low = Infinity;
    pool.forEach((p, k) => { if (best.includes(k)) return; const r = corr(pool[best[0]].v, p.v); if (r < low) { low = r; third = k; } });
    if (third >= 0) out.push(pool[third].key);
    return out;
  }

  function draw() {
    cancelAnimationFrame(st.frame);
    const one = st.mode === "one";
    $("#runs-c-one").hidden = !one; $("#runs-c-cmp").hidden = one; $("#runs-pairs").hidden = one; $("#runs-stats").hidden = !one;
    if (one) drawOne(); else drawCompare();
    mark();
  }
  // the shared frame: measured periods on the left third, the forecast steps on the rest
  function frame(steps) {
    const n = C.F.data.periods.length, small = narrow();
    const W = small ? 360 : 760, H = small ? 300 : 380, L = 48, R = small ? 12 : 16, T = 26, B = 30;
    const lastX = L + (W - L - R) * (small ? 0.3 : 0.36);            // the forecast gets most of the width
    const XH = (i) => (HIST < 2 ? lastX : L + (lastX - L) * (i - (n - HIST)) / (HIST - 1));
    const XF = (j) => lastX + (W - R - lastX) * (j + 1) / steps;      // j = 0 is the first step ahead
    return { n, small, W, H, L, R, T, B, lastX, XH, XF };
  }

  // ------------------------------------------------------------ one card
  function drawOne() {
    const s = seriesOf(st.fam, st.key), runs = runsOf(st.fam, st.key), F = C.F, title = name(st.fam, st.key);
    const steps = s.median.length, { n, small, W, H, L, R, T, B, lastX, XH, XF } = frame(steps);
    const known = s.history.map((v, i) => ({ v, i })).filter((p) => p.v !== null && p.i >= n - HIST);
    const lastV = known.length ? known[known.length - 1].v : s.no_change;
    const vals = known.map((p) => p.v).concat(s.band90.flat(), s.timesfm_median, [s.no_change], runs.flat());
    let y0 = Math.min(...vals), y1 = Math.max(...vals); const pad = (y1 - y0) * 0.08 || 0.003; y0 = Math.max(0, y0 - pad); y1 += pad;
    const Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
    const dec = y1 - y0 < 0.02 ? 2 : 1;
    const line = (pts) => `M${lastX.toFixed(1)},${Y(lastV).toFixed(1)}${pts.map((v, j) => `L${XF(j).toFixed(1)},${Y(v).toFixed(1)}`).join("")}`;
    const end = runs[steps - 1], up = above(end, s.no_change), down = below(end, s.no_change);
    G = { mode: "one", W, H, lastX, lastV, XF, Y, runs, steps, line, level: s.no_change };

    let g = UI.ticks(y0, y1, 4).map((v) => `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/>
      <text x="${L - 5}" y="${Y(v) + 4}" text-anchor="end">${(v * 100).toFixed(dec)}%</text>`).join("");
    g += `<rect x="${lastX}" y="${T}" width="${W - R - lastX}" height="${H - T - B}" fill="var(--sunken)" opacity="0.55"/>
      <text x="${L}" y="14">measured</text><text x="${W - R}" y="14" text-anchor="end">forecast: ${num(P.shown)} of ${num(P.runs)} runs</text>`;
    known.forEach((p, k) => { if (!small || k === 0 || k === known.length - 1) g += `<text x="${XH(p.i)}" y="${H - 9}" text-anchor="middle">P${p.i + 1}</text>`; });
    for (let j = 0; j < steps; j++) g += `<text x="${XF(j)}" y="${H - 9}" text-anchor="${j === steps - 1 ? "end" : "middle"}">+${hours(j)}h</text>`;
    if (st.bands) {
      const area = (band) => `${line(band.map((b) => b[1]))}${band.slice().reverse().map((b, i) => `L${XF(band.length - 1 - i).toFixed(1)},${Y(b[0]).toFixed(1)}`).join("")}Z`;
      g += `<path d="${area(s.band90)}" fill="var(--muted)" opacity="0.13"/><path d="${area(s.band50)}" fill="var(--muted)" opacity="0.18"/>`;
    }
    g += `<g id="runs-lines">${end.map((v, r) => `<path class="run ${v > s.no_change ? "up" : v < s.no_change ? "down" : "level"}" d="${line(runs.map((step) => step[r]))}"/>`).join("")}</g>`;
    g += `<line class="soft" x1="${lastX}" y1="${Y(s.no_change)}" x2="${W - R}" y2="${Y(s.no_change)}"/>`;
    if (st.tfm) {
      g += `<path d="${line(s.timesfm_median)}" fill="none" stroke="var(--elixir)" stroke-width="2.5" stroke-linejoin="round"/>`;
      s.timesfm_median.forEach((m, j) => { const x = XF(j), y = Y(m); g += `<path d="M${x},${y - 5}L${x + 5},${y}L${x},${y + 5}L${x - 5},${y}Z" fill="var(--elixir)" stroke="var(--surface)" stroke-width="1.5"/>`; });
    }
    g += `<path d="${known.map((p, k) => `${k ? "L" : "M"}${XH(p.i).toFixed(1)},${Y(p.v).toFixed(1)}`).join("")}" fill="none" stroke="var(--ink)" stroke-width="2.5" stroke-linejoin="round"/>`;
    known.forEach((p) => { g += `<circle cx="${XH(p.i)}" cy="${Y(p.v)}" r="4" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"/>`; });
    // the answer, written where the lines end
    g += `<text class="runs-count up" x="${W - R - 6}" y="${T + 17}" text-anchor="end">${num(up)} end above ${pct(s.no_change)}</text>
      <text class="runs-count down" x="${W - R - 6}" y="${H - B - 8}" text-anchor="end">${num(down)} end below</text>`;
    g += `<g id="runs-one"></g>`;
    $("#runs-stage").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${title}: measured usage in the last ${known.length} periods, then ${num(P.shown)} single Monte Carlo runs for the next ${steps} steps of ${F.settings.hours_per_step} hours. ${num(up)} end above the share now and ${num(down)} below. The table below holds the numbers.`)}">${g}</svg>`;

    const [dir, words] = verdict(up, down), far = hours(steps - 1), b = s.band90[steps - 1];
    $("#runs-h").textContent = "Will it be played more or less? Every line is one possible answer";
    $("#runs-take").innerHTML = `<b class="runs-verdict ${dir}">${esc(title)}: ${words}</b> over the next ${far} hours. It is in ${pct(s.no_change)} of Ranked decks now. Of the ${num(P.shown)} possible futures drawn here, <b class="runs-up">${num(up)} end higher</b> and <b class="runs-down">${num(down)} end lower</b>, and nine in ten of all ${num(P.runs)} end between ${pct(b[0])} and ${pct(b[1])}.`;
    $("#runs-intro").innerHTML = `<b>Why this chart is here:</b> a forecast is one number, and it will be off by some amount. Each thin line is one way the next ${far} hours could go, according to the model. Lines that bunch together mean it is sure; lines that fan out mean it isn't. Blue lines end above the share now, orange lines below. These are the model's own possibilities, not promises: how often it has been right is under "Can you trust it?" at the top.`;
    $("#runs-key").innerHTML = `<span><i style="background:var(--ink)"></i>Measured share</span><span><i class="runs-thin" style="background:var(--pos)"></i>A run that ends higher than now</span><span><i class="runs-thin" style="background:var(--neg)"></i>A run that ends lower</span><span><i style="background:var(--elixir)"></i>TimesFM's middle guess</span><span><i style="background:var(--muted);opacity:.45"></i>Where half, and nine in ten, of all runs fall</span><span>dashed: the share now</span>`;
    $("#runs-note").textContent = `The ${num(P.shown)} drawn runs are the first ${num(P.shown)} of the ${num(P.runs)}; the runs are independent, so that is a fair sample. Ranges count all ${num(P.runs)}. Each step's runs are drawn separately, so a line joins ${steps} unrelated draws: read how far the lines spread at each step, not which way one line turns. A line's color is set by where it ends, ${far} hours ahead. Forecast written ${C.F.written_at}.`;
    $("#runs-table-sum").textContent = "These runs as a table";
    stats(s, runs); table(s, runs, title);
  }

  // ------------------------------------------------------------ several cards
  function drawCompare() {
    const F = C.F, cards = st.cmp.map((key, k) => ({ key, s: seriesOf("cards", key), runs: runsOf("cards", key), color: COLORS[k], title: name("cards", key) }));
    const steps = cards[0].s.median.length, step = Math.min(st.step, steps - 1), { n, small, W, H, L, R, T, B, lastX, XH, XF } = frame(steps);
    const drawn = Math.min(CMP_RUNS, P.shown);
    // one scale for cards of very different sizes: each card's change from its own share now
    const rel = (c, v) => v / c.s.no_change - 1;
    cards.forEach((c) => { c.known = c.s.history.map((v, i) => ({ v, i })).filter((p) => p.v !== null && p.i >= n - HIST); });
    const vals = [0].concat(...cards.map((c) => c.known.map((p) => rel(c, p.v)).concat(...c.runs.map((sr) => sr.slice(0, drawn).map((v) => rel(c, v))))));
    let y0 = Math.min(...vals), y1 = Math.max(...vals); const pad = (y1 - y0) * 0.06 || 0.01; y0 -= pad; y1 += pad;
    const Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
    const change = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(0)}%`;
    const line = (c, pts) => `M${lastX.toFixed(1)},${Y(0).toFixed(1)}${pts.map((v, j) => `L${XF(j).toFixed(1)},${Y(rel(c, v)).toFixed(1)}`).join("")}`;

    let g = UI.ticks(y0, y1, 4).map((v) => `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/>
      <text x="${L - 5}" y="${Y(v) + 4}" text-anchor="end">${change(v)}</text>`).join("");
    g += `<rect x="${lastX}" y="${T}" width="${W - R - lastX}" height="${H - T - B}" fill="var(--sunken)" opacity="0.55"/>
      <text x="${L}" y="14">measured, against the share now</text><text x="${W - R}" y="14" text-anchor="end">forecast: ${num(drawn)} runs per card</text>`;
    const anyKnown = cards[0].known;
    anyKnown.forEach((p, k) => { if (!small || k === 0 || k === anyKnown.length - 1) g += `<text x="${XH(p.i)}" y="${H - 9}" text-anchor="middle">P${p.i + 1}</text>`; });
    for (let j = 0; j < steps; j++) g += `<text x="${XF(j)}" y="${H - 9}" text-anchor="${j === steps - 1 ? "end" : "middle"}" ${j === step ? 'class="lbl" font-weight="700"' : ""}>+${hours(j)}h</text>`;
    g += `<line x1="${XF(step)}" y1="${T}" x2="${XF(step)}" y2="${H - B}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 4"/>`;
    g += `<g id="runs-lines">${cards.map((c) => Array.from({ length: drawn }, (_, r) => `<path class="run cmp" style="stroke:${c.color}" d="${line(c, c.runs.map((sr) => sr[r]))}"/>`).join("")).join("")}</g>`;
    g += `<line class="soft" x1="${L}" y1="${Y(0)}" x2="${W - R}" y2="${Y(0)}"/>`;
    cards.forEach((c) => {
      g += `<path d="${c.known.map((p, k) => `${k ? "L" : "M"}${XH(p.i).toFixed(1)},${Y(rel(c, p.v)).toFixed(1)}`).join("")}" fill="none" stroke="${c.color}" stroke-width="2.5" stroke-linejoin="round"/>`;
      g += `<path class="runs-mid" d="${line(c, c.s.median)}" fill="none" stroke="var(--surface)" stroke-width="5" stroke-linejoin="round"/><path class="runs-mid" d="${line(c, c.s.median)}" fill="none" stroke="${c.color}" stroke-width="2.5" stroke-linejoin="round"/>`;
    });
    g += `<circle cx="${lastX}" cy="${Y(0)}" r="4" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"/><g id="runs-one"></g>`;
    $("#runs-stage").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${cards.map((c) => c.title).join(", ")}: each card's change from its share now, measured in the last ${anyKnown.length} periods, then ${num(drawn)} Monte Carlo runs per card for the next ${steps} steps. The table below holds how the cards move together.`)}">${g}</svg>`;

    // every pair, from all the drawn runs of the chosen step
    const at = cards.map((c) => c.runs[step]);
    const pairs = [];
    for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) { const [same, opposite] = sides(at[i], at[j]); pairs.push({ i, j, r: corr(at[i], at[j]), same, opposite }); }
    const pairOf = (i, j) => pairs.find((p) => (p.i === i && p.j === j) || (p.i === j && p.j === i));
    G = { mode: "compare", W, H, lastX, XF, Y, steps, step, cards, at, hi: (c, r) => line(c, c.runs.map((sr) => sr[r - 1])) };
    $("#runs-pairs").innerHTML = pairGrid(cards, at, pairOf, step);

    const lead = pairs.slice().sort((a, b) => Math.abs(b.r) - Math.abs(a.r))[0], a = cards[lead.i].title, b = cards[lead.j].title, strong = Math.abs(lead.r) >= 0.5;
    const head = Math.abs(lead.r) < clear() ? `No clear link between these cards`
      : lead.r > 0 ? `${a} and ${b} ${strong ? "rise and fall together" : "tend to rise and fall together"}`
      : `When ${a} is played more, ${b} ${strong ? "is played less" : "tends to be played less"}`;
    $("#runs-h").textContent = "Do these cards rise and fall together?";
    $("#runs-take").innerHTML = `<b class="runs-verdict ${Math.abs(lead.r) < clear() ? "even" : lead.r > 0 ? "up" : "down"}">${esc(head)}</b> in the model's futures, ${hours(step)} hours ahead. In ${num(lead.r >= 0 ? lead.same : lead.opposite)} of the ${num(P.shown)} futures drawn here, the two landed on ${lead.r >= 0 ? "the same side" : "opposite sides"} of their own middle (correlation ${signed(lead.r)}: +1 is always together, 0 is no link, −1 is always opposite).`;
    $("#runs-intro").innerHTML = `<b>Why this chart is here:</b> cards aren't played alone. Cards from the same decks tend to gain and lose together, and one card often loses what its rival gains. Each future holds every card at once, so the same future can be read across cards. The lines put cards of different sizes on one scale: each card's change from its share now. The grid under them takes two cards at a time: a dot is one future, and a slanted cloud of dots means the two are linked. The link comes from how past forecasts for the two cards missed together, and from a deck holding 8 cards. It doesn't show that one card causes the other's change.`;
    $("#runs-chosen").innerHTML = cards.map((c) => `<button class="chip runs-pick" type="button" data-runs-remove="${esc(c.key)}" ${cards.length > 2 ? `aria-label="${esc(`Remove ${c.title}`)}"` : "disabled"}><i style="background:${c.color}"></i>${esc(c.title)}${cards.length > 2 ? '<span aria-hidden="true"> ×</span>' : ""}</button>`).join("");
    const add = $("#runs-add");
    add.innerHTML = `<option value="">${cards.length >= CMP_MAX ? `Up to ${CMP_MAX} cards` : "Choose a card"}</option>${listed("cards").filter((s) => !st.cmp.includes(s.key)).map((s) => `<option value="${esc(s.key)}">${esc(name("cards", s.key))}</option>`).join("")}`;
    add.disabled = cards.length >= CMP_MAX;
    $("#runs-steps").innerHTML = Array.from({ length: steps }, (_, j) => `<button class="chip" type="button" data-runs-step="${j}" aria-pressed="${j === step}">${hours(j)} hours</button>`).join("");
    $("#runs-key").innerHTML = `${cards.map((c) => `<span><i style="background:${c.color}"></i>${esc(c.title)}</span>`).join("")}<span>thin: one run</span><span>thick: measured, then the middle of all ${num(P.runs)} runs</span><span>dashed: no change from now</span>`;
    $("#runs-note").textContent = `The lines show the first ${num(drawn)} runs per card, to keep ${cards.length} cards readable; the grid and every count use all ${num(P.shown)} drawn runs, which are the first ${num(P.shown)} of ${num(P.runs)}. With ${num(P.shown)} runs, a correlation closer to zero than ${clear().toFixed(2)} can't be told from no link, and is called "no clear link". Each step is drawn separately, so cards are linked within a step, not along a line. Forecast written ${C.F.written_at}.`;
    $("#runs-table-sum").textContent = "How the cards move together, as a table";
    $("#runs-table").innerHTML = `<div class="tblwrap"><table class="nums"><caption class="sr">Every pair of the compared cards, ${hours(step)} hours ahead, over the ${num(P.shown)} drawn runs</caption>
      <thead><tr><th scope="col">Cards</th><th scope="col">Correlation</th><th scope="col">Same side of their own middle</th><th scope="col">Opposite sides</th><th scope="col">Reading</th></tr></thead>
      <tbody>${pairs.map((p) => `<tr><td>${esc(cards[p.i].title)} and ${esc(cards[p.j].title)}</td><td>${signed(p.r)}</td><td>${num(p.same)} of ${num(P.shown)}</td><td>${num(p.opposite)} of ${num(P.shown)}</td><td>${linkWords(p.r)}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted small">A forecast of how the cards move together, not a measurement.</p>`;
  }
  // the pair grid (a scatterplot matrix): below the diagonal, one dot per run for two cards; above it, their
  // correlation; on it, each card's own spread
  function pairGrid(cards, at, pairOf, step) {
    const k = cards.length, small = narrow(), cell = small ? Math.floor(344 / k) : Math.min(190, Math.floor(744 / k)), gap = 6, W = k * cell + (k - 1) * gap, m = small ? 8 : 12;
    const lim = at.map((v) => { const lo = Math.min(...v), hi = Math.max(...v), p = (hi - lo) * 0.06 || 0.001; return [lo - p, hi + p]; });
    const mid = at.map(median);
    const pos = (i, v, size) => m + (size - 2 * m) * (v - lim[i][0]) / (lim[i][1] - lim[i][0]);
    let g = "";
    for (let row = 0; row < k; row++) for (let col = 0; col < k; col++) {
      const x = col * (cell + gap), y = row * (cell + gap);
      let c = `<rect x="0" y="0" width="${cell}" height="${cell}" rx="6" fill="var(--sunken)" opacity="0.55"/>`;
      if (row === col) {
        const bins = 14, counts = new Array(bins).fill(0);
        at[row].forEach((v) => { counts[Math.min(bins - 1, Math.floor(bins * (v - lim[row][0]) / (lim[row][1] - lim[row][0])))]++; });
        const top = Math.max(...counts), bw = (cell - 2 * m) / bins, base = cell - 20, room = base - 34;
        c += counts.map((n, b) => `<rect x="${(m + b * bw + 0.5).toFixed(1)}" y="${(base - room * n / top).toFixed(1)}" width="${(bw - 1).toFixed(1)}" height="${(room * n / top).toFixed(1)}" fill="${cards[row].color}" opacity="0.85"/>`).join("");
        c += `<text class="lbl" x="${m}" y="17" font-weight="700">${esc(UI.shorten(cards[row].title, small ? 11 : 22))}</text>
          <text x="${m}" y="${cell - 6}">${pct(lim[row][0])}</text><text x="${cell - m}" y="${cell - 6}" text-anchor="end">${pct(lim[row][1])}</text>
          <rect class="hit" x="0" y="0" width="${cell}" height="${cell}" ${UI.tipAttr(cards[row].title, [`${hours(step)} hours ahead, ${num(P.shown)} drawn runs`, `from ${pct(Math.min(...at[row]), 2)} to ${pct(Math.max(...at[row]), 2)}, middle ${pct(mid[row], 2)}`])}/>`;
      } else {
        const p = pairOf(row, col), words = linkWords(p.r), lines = [`correlation ${signed(p.r)}: ${words}`, `same side of their own middle in ${num(p.same)} of ${num(P.shown)} runs, opposite in ${num(p.opposite)}`, `${hours(step)} hours ahead`];
        if (row > col) {
          c += `<line x1="${pos(col, mid[col], cell)}" y1="4" x2="${pos(col, mid[col], cell)}" y2="${cell - 4}" stroke="var(--line)"/><line x1="4" y1="${cell - pos(row, mid[row], cell)}" x2="${cell - 4}" y2="${cell - pos(row, mid[row], cell)}" stroke="var(--line)"/>`;
          c += `<g class="runs-dots">${at[col].map((v, r) => `<circle cx="${pos(col, v, cell).toFixed(1)}" cy="${(cell - pos(row, at[row][r], cell)).toFixed(1)}" r="${small ? 1.4 : 2}"/>`).join("")}</g><g class="runs-dot-one" data-pair="${row}-${col}"></g>`;
        } else {
          const tint = Math.abs(p.r) < clear() ? "var(--muted)" : p.r > 0 ? "var(--pos)" : "var(--neg)";
          c += `<rect x="0" y="0" width="${cell}" height="${cell}" rx="6" fill="${tint}" opacity="${(0.12 + 0.5 * Math.abs(p.r)).toFixed(2)}"/>
            <text class="val runs-r" x="${cell / 2}" y="${cell / 2 - 2}" text-anchor="middle">${signed(p.r)}</text><text class="lbl" x="${cell / 2}" y="${cell / 2 + 16}" text-anchor="middle">${small && k > 3 ? "" : words}</text>`;
        }
        c += `<rect class="hit" x="0" y="0" width="${cell}" height="${cell}" ${UI.tipAttr(`${cards[row].title} and ${cards[col].title}`, row > col ? [`across: ${cards[col].title}, up: ${cards[row].title}; each dot is one run`].concat(lines) : lines)}/>`;
      }
      g += `<g transform="translate(${x},${y})">${c}</g>`;
    }
    return `<h4>Two cards at a time, ${hours(step)} hours ahead</h4>
      <p class="muted small">Below the diagonal, each dot is one future: across is the column's card, up is the row's card, and the lines mark each card's middle. Dots running from bottom left to top right mean the two move together. Above the diagonal is the same link as one number.</p>
      <svg class="chart" viewBox="0 0 ${W} ${W}" style="max-width:${W}px" role="group" aria-label="${esc(`Pair grid for ${cards.map((c) => c.title).join(", ")}: scatter of the drawn runs for every two cards, their correlation, and each card's own spread`)}">${g}</svg>`;
  }

  // the followed run, drawn on top with its values
  function mark() {
    if (!G) return;
    const r = st.hover || st.pinned, host = $("#runs-one"), out = $("#runs-trace-out");
    out.textContent = st.pinned ? `run ${st.pinned}` : "none";
    document.querySelectorAll(".runs-dot-one").forEach((el) => { el.innerHTML = ""; });
    if (!r) {
      host.innerHTML = "";
      $("#runs-read").textContent = G.mode === "one" ? "Point at a line, tap it, or move the slider to follow one run." : "Move the slider to follow one future across every card.";
      return;
    }
    if (G.mode === "compare") {
      host.innerHTML = G.cards.map((c) => `<path d="${G.hi(c, r)}" fill="none" stroke="var(--surface)" stroke-width="6" stroke-linejoin="round"/><path d="${G.hi(c, r)}" fill="none" stroke="${c.color}" stroke-width="3" stroke-linejoin="round"/>`).join("");
      document.querySelectorAll(".runs-dot-one").forEach((el) => {
        const dot = el.previousElementSibling.children[r - 1];
        if (dot) el.innerHTML = `<circle cx="${dot.getAttribute("cx")}" cy="${dot.getAttribute("cy")}" r="5.5" fill="var(--surface)" stroke="var(--ink)" stroke-width="2.5"/>`;
      });
      $("#runs-read").innerHTML = `<b>Run ${num(r)} of ${num(P.runs)}, ${hours(G.step)} hours ahead:</b> ${G.cards.map((c, k) => `${esc(c.title)} ${pct(G.at[k][r - 1], 2)}`).join(", ")}. The ringed dots in the grid are this same future.`;
      return;
    }
    const v = G.runs.map((step) => step[r - 1]);
    host.innerHTML = `<path d="${G.line(v)}" fill="none" stroke="var(--surface)" stroke-width="5" stroke-linejoin="round"/><path d="${G.line(v)}" fill="none" stroke="var(--ink)" stroke-width="2.5" stroke-linejoin="round"/>
      ${v.map((x, j) => `<circle cx="${G.XF(j)}" cy="${G.Y(x)}" r="4" fill="var(--surface)" stroke="var(--ink)" stroke-width="2"/>`).join("")}`;
    $("#runs-read").innerHTML = `<b>Run ${num(r)} of ${num(P.runs)}:</b> ${v.map((x, j) => `${pct(x, 2)} after ${hours(j)} hours`).join(", ")}.`;
  }
  // the drawn run closest to the pointer, 1-based; 0 when none is close or the pointer is left of the forecast
  function nearest(ev) {
    const svg = $("#runs-stage svg");
    if (!G || G.mode !== "one" || !svg) return 0;
    const box = svg.getBoundingClientRect();
    if (!box.width) return 0;
    const x = (ev.clientX - box.left) * G.W / box.width, y = (ev.clientY - box.top) * G.H / box.height;
    if (x < G.lastX) return 0;
    const xs = [G.lastX].concat(G.runs.map((_, j) => G.XF(j)));
    let j = 0; while (j < G.steps - 1 && x > xs[j + 1]) j++;
    const t = Math.min(1, (x - xs[j]) / (xs[j + 1] - xs[j]));
    let best = 0, gap = NEAR;
    for (let r = 0; r < G.runs[0].length; r++) {
      const a = j === 0 ? G.lastV : G.runs[j - 1][r], b = G.runs[j][r], d = Math.abs(G.Y(a + (b - a) * t) - y);
      if (d < gap) { gap = d; best = r + 1; }
    }
    return best;
  }
  // draws the runs one after another, in about two seconds; with reduced motion they are simply all there
  function play() {
    st.played = true;
    cancelAnimationFrame(st.frame);
    const lines = [...document.querySelectorAll("#runs-lines .run")];
    if (still() || !window.requestAnimationFrame) { lines.forEach((l) => { l.style.display = ""; }); return; }
    lines.forEach((l) => { l.style.display = "none"; });
    const per = Math.max(1, Math.ceil(lines.length / 110));
    let shown = 0;
    const tick = () => {
      for (let k = 0; k < per && shown < lines.length; k++) lines[shown++].style.display = "";
      if (shown < lines.length) st.frame = requestAnimationFrame(tick);
    };
    st.frame = requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ the numbers
  function stats(s, runs) {
    $("#runs-stats").innerHTML = `<div class="nums3">${s.median.map((m, j) => `<div><b>${pct(m)}</b>
      <span>middle of all ${num(P.runs)} runs, ${hours(j)} hours ahead</span>
      <span>nine in ten runs: ${pct(s.band90[j][0])} to ${pct(s.band90[j][1])}</span>
      <span>${num(above(runs[j], s.no_change))} of the ${num(P.shown)} drawn end above the latest share (${pct(s.no_change)})</span></div>`).join("")}</div>`;
  }
  function table(s, runs, title) {
    $("#runs-table").innerHTML = `<div class="tblwrap"><table class="nums"><caption class="sr">${esc(title)}: the forecast at each step, from all runs and from the drawn runs</caption>
      <thead><tr><th scope="col">Hours ahead</th><th scope="col">TimesFM's middle guess</th><th scope="col">Middle of all runs</th><th scope="col">Half of all runs</th><th scope="col">Nine in ten of all runs</th><th scope="col">Lowest and highest drawn run</th><th scope="col">Drawn runs above the latest share</th></tr></thead>
      <tbody>${s.median.map((m, j) => `<tr><td>${hours(j)}</td><td>${pct(s.timesfm_median[j], 2)}</td><td>${pct(m, 2)}</td><td>${pct(s.band50[j][0], 2)} to ${pct(s.band50[j][1], 2)}</td><td>${pct(s.band90[j][0], 2)} to ${pct(s.band90[j][1], 2)}</td>
        <td>${pct(Math.min(...runs[j]), 2)} to ${pct(Math.max(...runs[j]), 2)}</td><td>${num(above(runs[j], s.no_change))} of ${num(P.shown)}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted small">Latest measured share: ${pct(s.no_change, 2)}. A forecast, not a measurement.</p>`;
  }

  window.RunsChart = { markup, mount };
})();
