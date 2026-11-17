/* Approximate loss surfaces for any pair of Ranked card forms on "How it works".
 * web/loss_surface.json (scripts/export_web.py, crdeck.landscape.snapshot) holds, computed once in Python,
 * every card form's fitted weight w, the loss J0 there, its gradient g and the card-form block of the
 * Hessian H (upper triangle, row by row). A custom pair (a, b) is drawn from the local quadratic
 *     J(a, b) ≈ J0 + g_a d_a + g_b d_b + ½ (H_aa d_a² + 2 H_ab d_a d_b + H_bb d_b²),  d = (a − w_a, b − w_b)
 * with every other weight fixed. No battle data, no exact recomputation: the three exact slices in
 * modes.json stay the only exact ones.
 *   validate(snap, ref)    checks the file (and its id against modes.json); {ok, reason, S}
 *   pairBlock(S, ka, kb)   the six numbers one pair needs; throws on unknown or identical keys
 *   quadLoss / quadGrad    the quadratic and its exact gradient
 *   customSlice(S, ka, kb) the same shape as an exact slice, so the page's renderer draws it unchanged
 *   ticks, categoryGroups, formOptions: small helpers for labels, the category list and the selectors
 * Works in the browser (global `CRLoss`) and in Node (module.exports).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CRLoss = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const GRID = 41, ARROWS = 9, PATH_STEPS = 40, STEP = 0.3; // the same as crdeck/landscape.py
  const TYPES = ["troop", "spell", "building"];
  const fin = (x) => typeof x === "number" && Number.isFinite(x);

  // H[i][j] in the packed upper triangle (i <= j after swapping), as crdeck.landscape.packed_index
  function packedIndex(i, j, m) { if (i > j) [i, j] = [j, i]; return i * m - (i * (i - 1)) / 2 + (j - i); }

  function validate(snap, ref) {
    const bad = (reason) => ({ ok: false, reason });
    if (!snap || typeof snap !== "object") return bad("the file is missing or not JSON");
    if (snap.schema_version !== 1) return bad(`unknown schema version ${snap.schema_version}`);
    if (snap.source_mode !== "ranked") return bad("it is not for the Ranked model");
    if (ref && ref.snapshot_id !== snap.snapshot_id) return bad("it doesn't match this export (different snapshot id)");
    const F = snap.forms;
    if (!Array.isArray(F) || F.length < 2) return bad("it lists fewer than two card forms");
    const m = F.length, keys = [], seen = new Set();
    for (const f of F) {
      if (!Array.isArray(f) || typeof f[0] !== "string" || typeof f[1] !== "string" || typeof f[2] !== "string") return bad("a card form record is malformed");
      if (!TYPES.includes(f[3])) return bad(`card form ${f[0]} has no troop, spell or building type`);
      if (seen.has(f[0])) return bad(`card form ${f[0]} is listed twice`);
      seen.add(f[0]); keys.push(f[0]);
    }
    const arr = (a, n, what) => (Array.isArray(a) && a.length === n && a.every(fin) ? null : `${what} has the wrong length or a non-number`);
    const e = arr(snap.weights, m, "weights") || arr(snap.g, m, "the gradient") || arr(snap.h_packed, (m * (m + 1)) / 2, "the curvature");
    if (e) return bad(e);
    if (![snap.J0, snap.C, snap.n_train, snap.half_width].every(fin) || snap.C <= 0 || snap.n_train <= 0 || snap.half_width <= 0) return bad("J0, C, N or the range is invalid");
    for (let i = 0; i < m; i++) if (!(snap.h_packed[packedIndex(i, i, m)] > 0)) return bad(`curvature of ${keys[i]} is not positive`);
    const index = new Map(keys.map((k, i) => [k, i]));
    return { ok: true, reason: null, S: { snap, m, keys, index, forms: F } };
  }

  function pairBlock(S, ka, kb) {
    if (ka === kb) throw new Error("the same card form can't be on both axes");
    const ia = S.index.get(ka), ib = S.index.get(kb);
    if (ia === undefined || ib === undefined) throw new Error(`no fitted weight for ${ia === undefined ? ka : kb}`);
    const h = S.snap.h_packed, m = S.m;
    const B = { ia, ib, wa: S.snap.weights[ia], wb: S.snap.weights[ib], ga: S.snap.g[ia], gb: S.snap.g[ib],
      haa: h[packedIndex(ia, ia, m)], hab: h[packedIndex(ia, ib, m)], hbb: h[packedIndex(ib, ib, m)], J0: S.snap.J0 };
    if (!(B.haa > 0 && B.haa * B.hbb - B.hab * B.hab > 0)) throw new Error("this pair's curvature is not a bowl, so no local picture");
    return B;
  }
  const quadLoss = (B, da, db) => B.J0 + B.ga * da + B.gb * db + 0.5 * (B.haa * da * da + 2 * B.hab * da * db + B.hbb * db * db);
  const quadGrad = (B, da, db) => [B.ga + B.haa * da + B.hab * db, B.gb + B.hab * da + B.hbb * db];
  const maxEig = (B) => (B.haa + B.hbb) / 2 + Math.sqrt(((B.haa - B.hbb) / 2) ** 2 + B.hab * B.hab);

  // Renderer-compatible slice (same fields as crdeck.landscape.surface) from the quadratic alone.
  function customSlice(S, ka, kb) {
    const B = pairBlock(S, ka, kb), r = S.snap.half_width, n = GRID;
    const lin = (c) => Array.from({ length: n }, (_, i) => c - r + (2 * r * i) / (n - 1));
    const a = lin(B.wa), b = lin(B.wb);
    a[(n - 1) / 2] = B.wa; b[(n - 1) / 2] = B.wb;
    const loss = a.map((x) => b.map((y) => quadLoss(B, x - B.wa, y - B.wb)));
    const step = (n - 1) / (ARROWS - 1), gi = [];
    for (let i = 0; i < n; i += step) gi.push(i);
    const grad_a = gi.map((i) => gi.map((j) => quadGrad(B, a[i] - B.wa, b[j] - B.wb)[0]));
    const grad_b = gi.map((i) => gi.map((j) => quadGrad(B, a[i] - B.wa, b[j] - B.wb)[1]));
    // illustrative gradient descent from a corner; a step that would leave the drawn range is halved until it fits
    // (on a convex quadratic a shorter step along −∇J never raises J, so the path still only goes down)
    const lr = STEP / maxEig(B), path = [];
    let da = 0.9 * r, db = 0.9 * r;
    for (let k = 0; k <= PATH_STEPS; k++) {
      const [gA, gB] = quadGrad(B, da, db);
      path.push([B.wa + da, B.wb + db, quadLoss(B, da, db), gA, gB]);
      let t = lr, na = da - t * gA, nb = db - t * gB;
      for (let h = 0; h < 40 && (Math.abs(na) > r || Math.abs(nb) > r); h++) { t /= 2; na = da - t * gA; nb = db - t * gB; }
      if (Math.abs(na) <= r && Math.abs(nb) <= r) { da = na; db = nb; }
    }
    const games = S.forms.map((f) => f[4]);
    return { keys: [ka, kb], fitted: [B.wa, B.wb], games: [games[B.ia] || 0, games[B.ib] || 0], a, b, loss, grad_a, grad_b,
      arrow_step: step, fitted_loss: B.J0, fitted_grad: [B.ga, B.gb], path, learning_rate: lr, n_train: S.snap.n_train, C: S.snap.C,
      half_width: r, curvature: [B.haa, B.hab, B.hbb], approximate: true };
  }

  // At least three readable ticks inside [lo, hi], with enough decimals that neighbours never print the same.
  function ticks(lo, hi, want = 4) {
    if (!(hi > lo)) return [{ v: lo, label: String(+lo.toPrecision(6)) }];
    const raw = (hi - lo) / want, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    let step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    let vs = [];
    for (let t = 0; t < 3 && vs.length < 3; t++) {
      vs = [];
      for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) vs.push(v);
      if (vs.length < 3) step /= 2;
    }
    if (vs.length < 3) vs = [lo, (lo + hi) / 2, hi];
    let dec = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
    const fmt = (v, d) => (Math.abs(v) < step * 1e-6 ? 0 : v).toFixed(d).replace("-", "−");
    while (dec < 12 && new Set(vs.map((v) => fmt(v, dec))).size < vs.length) dec++;
    return vs.map((v) => ({ v, label: fmt(v, dec) }));
  }

  const FORM_WORD = { base: "", evo: " (Evolution)", hero: " (Hero)" };
  const formLabel = (f) => f[1] + (FORM_WORD[f[2]] === undefined ? ` (${f[2]})` : FORM_WORD[f[2]]);
  // selector options: every fitted card form once, by name (then form), labelled with its form
  function formOptions(S) {
    return S.forms.map((f) => ({ key: f[0], label: formLabel(f), type: f[3] }))
      .sort((x, y) => x.label.localeCompare(y.label, "en") || (x.key < y.key ? -1 : 1));
  }
  // every fitted form once, under its card type, strongest weight first
  function categoryGroups(S) {
    const g = { troop: [], spell: [], building: [] };
    S.forms.forEach((f, i) => g[f[3]].push({ key: f[0], label: formLabel(f), weight: S.snap.weights[i], games: f[4] }));
    const names = { troop: "Troops", spell: "Spells", building: "Buildings" };
    return TYPES.map((t) => ({ type: t, title: names[t], items: g[t].sort((x, y) => y.weight - x.weight),
      empty: g[t].length ? null : `No ${names[t].toLowerCase()} have a fitted weight in this model.` }));
  }

  return { GRID, ARROWS, PATH_STEPS, STEP, packedIndex, validate, pairBlock, quadLoss, quadGrad, maxEig, customSlice, ticks, formLabel, formOptions, categoryGroups };
});
