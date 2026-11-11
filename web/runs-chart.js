/* The live forecast, one Monte Carlo run at a time. future_paths.json holds a fixed sample of the runs that
   future_meta.json summarizes (scripts/future_meta.py writes both). Thin lines are single real runs; every range and
   middle value quoted here counts all runs and comes from future_meta.json. Nothing on this chart is illustrative. */
(() => {
  "use strict";
  const HIST = 6;                      // measured periods shown before the forecast
  const NEAR = 14;                     // how close (chart units) the pointer must be to pick up a run
  let C = null, P = null, G = null;    // page context, the runs file, the geometry of the drawn chart
  const st = { fam: "cards", key: "", bands: true, tfm: true, pinned: 0, hover: 0, frame: 0, played: false };
  const $ = (s) => document.querySelector(s);
  const esc = (s) => UI.esc(s), pct = (x, d) => UI.pct(x, d), num = (n) => UI.num(n);
  const narrow = () => document.documentElement.clientWidth < 620;
  const still = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const name = (fam, key) => (fam === "cards" ? C.keyName(key) : C.styleName(key));
  const series = (fam) => C.F.forecast[fam].series.slice().sort((a, b) => b.no_change - a.no_change);
  const find = () => C.F.forecast[st.fam].series.find((s) => s.key === st.key);
  const hours = (i) => C.F.settings.hours_per_step * (i + 1);
  // runs[step][run] as shares, for the chosen series; null when the file doesn't hold it
  function runsOf(fam, key) {
    const k = P && P[fam] ? P[fam].keys.indexOf(key) : -1;
    return k < 0 ? null : P[fam].runs[k].map((step) => step.map((v) => v * P.unit));
  }

  function markup() {
    return `<div class="panel box runs" id="runs">
      <h3>The forecast, one run at a time</h3>
      <p id="runs-intro">The ranges on this page come from a Monte Carlo: many separate runs, each one a possible future. Here are the runs themselves.</p>
      <div class="controls" role="group" aria-label="What the runs chart shows">
        <label class="lab" for="runs-series">Card or style</label><select id="runs-series" class="sel"></select>
        <button class="chip" type="button" data-runs-toggle="bands" aria-pressed="true">50% and 90% ranges</button>
        <button class="chip" type="button" data-runs-toggle="tfm" aria-pressed="true">TimesFM's guess</button>
        <button class="chip" type="button" id="runs-play">Replay the runs</button>
      </div>
      <div class="key"><span><i style="background:var(--ink)"></i>Measured share</span><span><i class="runs-thin"></i>One run</span><span><i style="background:var(--pos)"></i>TimesFM's middle guess</span><span><i style="background:var(--elixir)"></i>Middle of all runs, 50% and 90% ranges</span><span>dashed: no change</span></div>
      <div id="runs-stage" class="runs-stage"><div class="skel" style="height:240px"></div></div>
      <p id="runs-read" class="runs-read" role="status"></p>
      <label class="runs-trace" for="runs-trace"><span class="lab">Follow one run</span><input type="range" id="runs-trace" min="0" max="1" step="1" value="0"><output id="runs-trace-out" for="runs-trace">none</output></label>
      <div id="runs-stats"></div>
      <details class="more"><summary>These runs as a table</summary><div class="body" id="runs-table"></div></details>
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
    ["#runs .controls", "#runs .key", "#runs-read", "#runs .runs-trace", "#runs-stats", "#runs details", "#runs-note"].forEach((s) => { const el = $(s); if (el) el.hidden = true; });
  }

  function start() {
    // both files must come from one run of the script, or the lines and the ranges would describe different forecasts
    if (P.written_at !== C.F.written_at) {
      return fail(`<b>The saved runs are from a different forecast than this page.</b> future_paths.json was written ${esc(P.written_at)}, future_meta.json ${esc(C.F.written_at)}. Run <code>python scripts/future_meta.py</code> to write both again.`);
    }
    const opts = (fam) => series(fam).filter((s) => runsOf(fam, s.key)).map((s) => `<option value="${fam}:${esc(s.key)}">${esc(name(fam, s.key))}</option>`).join("");
    const sel = $("#runs-series");
    sel.innerHTML = `<optgroup label="Cards, most used first">${opts("cards")}</optgroup><optgroup label="Deck styles">${opts("styles")}</optgroup>`;
    if (!sel.value) return fail("<b>No forecast series has saved runs.</b>");
    choose(sel.value);
    sel.addEventListener("change", () => { choose(sel.value); draw(); play(); });
    $("#runs").addEventListener("click", (ev) => {
      const t = ev.target.closest("[data-runs-toggle]");
      if (t) { st[t.dataset.runsToggle] = !st[t.dataset.runsToggle]; t.setAttribute("aria-pressed", String(st[t.dataset.runsToggle])); draw(); }
      if (ev.target.closest("#runs-play")) play();
    });
    const trace = $("#runs-trace");
    trace.max = String(P.shown);
    trace.addEventListener("input", () => { st.pinned = Number(trace.value); st.hover = 0; mark(); });
    const stage = $("#runs-stage");
    stage.addEventListener("pointermove", (ev) => { const r = nearest(ev); if (r !== st.hover) { st.hover = r; mark(); } });
    stage.addEventListener("pointerleave", () => { if (st.hover) { st.hover = 0; mark(); } });
    stage.addEventListener("click", (ev) => { const r = nearest(ev); st.pinned = r === st.pinned ? 0 : r; trace.value = String(st.pinned); mark(); });
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

  // ------------------------------------------------------------ the chart
  function draw() {
    cancelAnimationFrame(st.frame);
    const s = find(), runs = runsOf(st.fam, st.key), F = C.F, title = name(st.fam, st.key);
    const n = F.data.periods.length, steps = s.median.length, small = narrow();
    const W = small ? 360 : 760, H = small ? 300 : 380, L = 44, R = small ? 12 : 16, T = 26, B = 30;
    const known = s.history.map((v, i) => ({ v, i })).filter((p) => p.v !== null && p.i >= n - HIST);
    const lastV = known.length ? known[known.length - 1].v : s.no_change;
    const vals = known.map((p) => p.v).concat(s.band90.flat(), s.timesfm_median, [s.no_change], runs.flat());
    let y0 = Math.min(...vals), y1 = Math.max(...vals); const pad = (y1 - y0) * 0.08 || 0.003; y0 = Math.max(0, y0 - pad); y1 += pad;
    const lastX = L + (W - L - R) * (small ? 0.3 : 0.36);            // the forecast gets most of the width
    const XH = (i) => (HIST < 2 ? lastX : L + (lastX - L) * (i - (n - HIST)) / (HIST - 1));
    const XF = (j) => lastX + (W - R - lastX) * (j + 1) / steps;      // j = 0 is the first step ahead
    const Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
    const dec = y1 - y0 < 0.02 ? 2 : 1;
    const line = (pts) => `M${lastX.toFixed(1)},${Y(lastV).toFixed(1)}${pts.map((v, j) => `L${XF(j).toFixed(1)},${Y(v).toFixed(1)}`).join("")}`;
    G = { W, H, lastX, lastV, XF, Y, runs, steps, line };

    let g = UI.ticks(y0, y1, 4).map((v) => `<line x1="${L}" y1="${Y(v)}" x2="${W - R}" y2="${Y(v)}" stroke="var(--grid)" stroke-width="1"/>
      <text x="${L - 5}" y="${Y(v) + 4}" text-anchor="end">${(v * 100).toFixed(dec)}%</text>`).join("");
    g += `<rect x="${lastX}" y="${T}" width="${W - R - lastX}" height="${H - T - B}" fill="var(--sunken)" opacity="0.55"/>
      <text x="${L}" y="14">measured</text><text x="${W - R}" y="14" text-anchor="end">forecast: ${num(P.shown)} of ${num(P.runs)} runs</text>`;
    known.forEach((p, k) => { if (!small || k === 0 || k === known.length - 1) g += `<text x="${XH(p.i)}" y="${H - 9}" text-anchor="middle">P${p.i + 1}</text>`; });
    for (let j = 0; j < steps; j++) g += `<text x="${XF(j)}" y="${H - 9}" text-anchor="${j === steps - 1 ? "end" : "middle"}">+${hours(j)}h</text>`;
    if (st.bands) {
      const area = (band) => `${line(band.map((b) => b[1]))}${band.slice().reverse().map((b, i) => `L${XF(band.length - 1 - i).toFixed(1)},${Y(b[0]).toFixed(1)}`).join("")}Z`;
      g += `<path d="${area(s.band90)}" fill="var(--elixir)" opacity="0.10"/><path d="${area(s.band50)}" fill="var(--elixir)" opacity="0.16"/>`;
    }
    g += `<line class="soft" x1="${lastX}" y1="${Y(s.no_change)}" x2="${W - R}" y2="${Y(s.no_change)}"/>`;
    g += `<g id="runs-lines">${runs[0].map((_, r) => `<path class="run" d="${line(runs.map((step) => step[r]))}"/>`).join("")}</g>`;
    if (st.tfm) {
      g += `<path d="${line(s.timesfm_median)}" fill="none" stroke="var(--pos)" stroke-width="2.5" stroke-linejoin="round"/>`;
      s.timesfm_median.forEach((m, j) => { const x = XF(j), y = Y(m); g += `<path d="M${x},${y - 5}L${x + 5},${y}L${x},${y + 5}L${x - 5},${y}Z" fill="var(--pos)" stroke="var(--surface)" stroke-width="1.5"/>`; });
    }
    g += `<path d="${known.map((p, k) => `${k ? "L" : "M"}${XH(p.i).toFixed(1)},${Y(p.v).toFixed(1)}`).join("")}" fill="none" stroke="var(--ink)" stroke-width="2.5" stroke-linejoin="round"/>`;
    known.forEach((p) => { g += `<circle cx="${XH(p.i)}" cy="${Y(p.v)}" r="4" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"/>`; });
    s.median.forEach((m, j) => { g += `<circle cx="${XF(j)}" cy="${Y(m)}" r="4" fill="var(--elixir)" stroke="var(--surface)" stroke-width="1.5"/>`; });
    g += `<g id="runs-one"></g>`;
    $("#runs-stage").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${title}: measured usage in the last ${known.length} periods, then ${num(P.shown)} single Monte Carlo runs for the next ${steps} steps of ${F.settings.hours_per_step} hours. The table below holds the numbers.`)}">${g}</svg>`;

    $("#runs-intro").innerHTML = `Each thin line is one real run of the Monte Carlo for <b>${esc(title)}</b>: a possible share of Ranked decks at each of the next ${steps} steps of ${F.settings.hours_per_step} hours. ${num(P.shown)} of the ${num(P.runs)} runs are drawn. The blue line is TimesFM's own middle guess, which the runs are drawn around.`;
    $("#runs-note").textContent = `The ${num(P.shown)} drawn runs are the first ${num(P.shown)} of the ${num(P.runs)}; the runs are independent, so that is a fair sample. Ranges and middle values count all ${num(P.runs)}. Each step's runs are drawn separately, so a line joins ${steps} unrelated draws: read how far the lines spread at each step, not which way one line turns. Forecast written ${C.F.written_at}.`;
    stats(s, runs, title); table(s, runs, title); mark();
  }

  // the followed run, drawn on top with its values
  function mark() {
    if (!G) return;
    const r = st.hover || st.pinned, host = $("#runs-one"), out = $("#runs-trace-out");
    out.textContent = st.pinned ? `run ${st.pinned}` : "none";
    if (!r) {
      host.innerHTML = "";
      $("#runs-read").textContent = "Point at a line, tap it, or move the slider to follow one run.";
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
    if (!G || !svg) return 0;
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
  const above = (step, level) => step.filter((v) => v > level).length;
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
