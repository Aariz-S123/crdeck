// Keyboard walk with real key presses, through the Chrome DevTools Protocol (Node 22's built-in WebSocket,
// no dependencies). Needs the site served on :8765 (cd web && python -m http.server 8765 --bind 127.0.0.1).
//   node keys.mjs <out.json> [name=url ...]     (default: every page)
// For each page: press Tab up to 400 times and record every focused element; check that each one shows a
// visible focus indicator (outline or box-shadow from :focus-visible), that focus never gets stuck (no trap),
// and that the walk comes back around; then press Shift+Tab once and Escape once and check nothing breaks.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve(process.argv[2] || "keys.json");
const B = "http://127.0.0.1:8765";
const DECK = "ranked~26000047e-26000052b-26000057b-26000059b-27000012e-28000000b-28000001b-28000015b~28000015b-28000000b-28000001b";
const PAGES = process.argv.length > 3 ? Object.fromEntries(process.argv.slice(3).map((a) => a.split(/=(.*)/s).slice(0, 2)))
  : { builder: `${B}/index.html#ranked~~`, reason: `${B}/reason.html#${DECK}`, counters: `${B}/counters.html#ranked`, cards: `${B}/cards.html#ranked`,
      meta: `${B}/meta.html#ranked`, seasons: `${B}/seasons.html#ranked`, model: `${B}/model.html#ranked` };
const PORT = 9335, wait = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${path.join(process.env.TEMP || ".", "crdeck-cdp-keys")}`, "about:blank"], { stdio: "ignore" });
let target = null;
for (let i = 0; i < 50 && !target; i++) { await wait(200); try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch { /* starting */ } }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map(), errors = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); }
  else if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text);
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const k = ++id; pending.set(k, { resolve, reject }); ws.send(JSON.stringify({ id: k, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;
const key = async (k, code, vk, shift = false) => {
  const mod = shift ? 8 : 0;
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: vk, modifiers: mod });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: vk, modifiers: mod });
};
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true });
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
// what is focused, and does it show a focus indicator? (outline, or a box-shadow that differs from the unfocused one)
const PROBE = `(() => { const e = document.activeElement; if (!e || e === document.body) return null;
  const s = getComputedStyle(e), r = e.getBoundingClientRect();
  // HTML controls show an outline or box-shadow; chart marks (SVG) show a stroke in the focus color instead
  const svg = e instanceof SVGElement;
  const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || (s.boxShadow && s.boxShadow !== "none") ||
    (svg && s.stroke && s.stroke !== "none" && parseFloat(s.strokeWidth) > 0);
  const label = (e.getAttribute("aria-label") || e.textContent || e.value || e.tagName).replace(/\\s+/g, " ").trim().slice(0, 40);
  // an element is known by its place in the document, not on screen: inside a scrolling list (the builder's
  // cards) every focused button scrolls into the same spot, which a position-based key mistook for a wrap
  return { tag: e.tagName.toLowerCase(), id: e.id || null, label, ring, visible: r.width > 0 && r.height > 0,
    path: e.tagName + (e.id ? "#" + e.id : "") + "@" + Array.prototype.indexOf.call(document.getElementsByTagName("*"), e) }; })()`;
const report = {};
for (const [name, url] of Object.entries(PAGES)) {
  errors.length = 0;
  await send("Page.navigate", { url: "about:blank" }); await wait(150);
  await send("Page.navigate", { url });
  for (let t = 0; t < 200; t++) { await wait(200); if (!(await evaluate(`document.readyState !== "complete" || !!document.querySelector(".skel") || /Loading|Building|Ranking/.test((document.querySelector("#status")||{}).textContent||"")`))) break; }
  await wait(500);
  const seen = [], noRing = [], hidden = [];
  let wrapped = false, stuck = 0, last = null, shiftOk = null;
  for (let i = 0; i < 400; i++) {
    await key("Tab", "Tab", 9);
    const f = await evaluate(PROBE);
    if (!f) { if (seen.length) { wrapped = true; break; } continue; }   // focus left the page: the walk came around
    if (last && f.path === last) { if (++stuck > 3) break; } else stuck = 0;
    last = f.path;
    if (seen.includes(f.path)) { wrapped = true; break; }
    seen.push(f.path);
    if (seen.length === 4) {   // Shift+Tab from the 4th stop must return to the 3rd, then Tab goes on again
      await key("Tab", "Tab", 9, true);
      const b = await evaluate(PROBE);
      shiftOk = !!b && b.path === seen[2];
      await key("Tab", "Tab", 9);
    }
    if (!f.ring) noRing.push(`${f.tag}${f.id ? "#" + f.id : ""} "${f.label}"`);
    if (!f.visible) hidden.push(`${f.tag} "${f.label}"`);
  }
  await key("Escape", "Escape", 27);
  const tipHidden = await evaluate(`!document.getElementById("tip") || document.getElementById("tip").hidden`);
  report[name] = { stops: seen.length, wrapped, trapped: stuck > 3, no_focus_ring: noRing.slice(0, 10), no_focus_ring_count: noRing.length,
    hidden_focus: hidden.slice(0, 10), shift_tab_ok: shiftOk, tooltip_hidden_after_escape: tipHidden, script_errors: errors.slice() };
  console.log(name, JSON.stringify(report[name]));
}
fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
ws.close(); chrome.kill();
