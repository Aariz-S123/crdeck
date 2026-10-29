// Screenshots and layout measurements with real device emulation, through the Chrome DevTools Protocol.
// No dependencies: Node 22's built-in WebSocket. Needs the site served on :8765
// (cd web && python -m http.server 8765 --bind 127.0.0.1).
//   node shots.mjs <out dir> [name=url ...]     (default: builder and deck explanation)
// Each view: desktop light 1440, mobile light 390, mobile dark 390. Writes <name>-<view>.png and layout.json
// (page width vs viewport width, so horizontal overflow is measured, not eyeballed).
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve(process.argv[2] || "."); fs.mkdirSync(OUT, { recursive: true });
const BASE = "http://127.0.0.1:8765";
const DECK = "ranked~26000047e-26000052b-26000057b-26000059b-27000012e-28000000b-28000001b-28000015b~28000015b-28000000b-28000001b";
const PAGES = process.argv.length > 3
  ? Object.fromEntries(process.argv.slice(3).map((a) => a.split(/=(.*)/s).slice(0, 2)))
  : { builder: `${BASE}/index.html#ranked~~`, reason: `${BASE}/reason.html#${DECK}` };
const VIEWS = (process.env.VIEWS || "desktop-light,mobile-light,mobile-dark").split(",");
const SPEC = {
  "desktop-light": { width: 1440, height: 1000, mobile: false, scheme: "light", scale: 1 },
  "desktop-dark": { width: 1440, height: 1000, mobile: false, scheme: "dark", scale: 1 },
  "tablet-light": { width: 768, height: 1024, mobile: true, scheme: "light", scale: 1 },
  "mobile-light": { width: 390, height: 844, mobile: true, scheme: "light", scale: 1 },
  "mobile-dark": { width: 390, height: 844, mobile: true, scheme: "dark", scale: 1 },
  // 200% zoom on a 1440 px window: the page lays out at 720 CSS px with 2 device pixels per CSS px
  "zoom200-light": { width: 720, height: 500, mobile: false, scheme: "light", scale: 2 },
};
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9333;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${path.join(process.env.TEMP || OUT, "crdeck-cdp")}`, "about:blank"], { stdio: "ignore" });
let target = null;
for (let i = 0; i < 50 && !target; i++) {
  await wait(200);
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch { /* not up yet */ }
}
if (!target) { chrome.kill(); throw new Error("Chrome DevTools did not start"); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map(), events = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); }
  else if (m.method) events.push(m);
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const k = ++id; pending.set(k, { resolve, reject }); ws.send(JSON.stringify({ id: k, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

await send("Page.enable"); await send("Runtime.enable");
await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true }); // always the files on disk now
const layout = {};
for (const [name, url] of Object.entries(PAGES)) for (const view of VIEWS) {
  const s = SPEC[view];
  await send("Emulation.setDeviceMetricsOverride", { width: s.width, height: s.height, deviceScaleFactor: s.scale, mobile: s.mobile });
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: s.scheme }] });
  await send("Page.navigate", { url: "about:blank" }); await wait(200);
  events.length = 0;
  await send("Page.navigate", { url });
  // wait until the page has rendered its results (no skeletons, no "Loading"/"Building" status), max 40 s
  for (let t = 0; t < 200; t++) {
    await wait(200);
    const busy = await evaluate(`document.readyState !== "complete" || !!document.querySelector(".skel") || /Loading|Building|Ranking/.test((document.querySelector("#status")||{}).textContent||"")`);
    if (!busy) break;
  }
  await wait(400);
  const m = await evaluate(`(() => { const d = document.documentElement; const wide = [...document.querySelectorAll("body *")].filter((e) => { const r = e.getBoundingClientRect(); return r.width && r.right > d.clientWidth + 1; }).slice(0, 5).map((e) => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (e.className && typeof e.className === "string" ? "." + e.className.split(" ")[0] : ""));
    return { viewport: d.clientWidth, page_width: d.scrollWidth, page_height: d.scrollHeight, overflow_px: d.scrollWidth - d.clientWidth, wider_than_viewport: wide,
      dark: matchMedia("(prefers-color-scheme: dark)").matches, viewport_meta: !!document.querySelector('meta[name="viewport"]'), doctype: !!document.doctype, lang: d.lang }; })()`);
  const errs = events.filter((e) => e.method === "Runtime.exceptionThrown").map((e) => e.params.exceptionDetails.exception ? e.params.exceptionDetails.exception.description : e.params.exceptionDetails.text);
  const height = Math.min(m.page_height, 6000);
  await send("Emulation.setDeviceMetricsOverride", { width: s.width, height, deviceScaleFactor: s.scale, mobile: s.mobile });
  await wait(300);
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: s.width, height, scale: 1 } });
  fs.writeFileSync(path.join(OUT, `${name}-${view}.png`), Buffer.from(shot.data, "base64"));
  layout[`${name}-${view}`] = Object.assign(m, { script_errors: errs });
  console.log(name, view, JSON.stringify(m), errs.length ? "ERRORS " + errs.join(" | ") : "");
}
fs.writeFileSync(path.join(OUT, "layout.json"), JSON.stringify(layout, null, 1));
ws.close(); chrome.kill();
