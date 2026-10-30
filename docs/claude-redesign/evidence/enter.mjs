// Picking by keyboard in Chrome (real key presses through the DevTools protocol, Node 22, no dependencies).
// Needs the site served on :8765. Tabs to the builder's card list, presses Enter on nine different cards and
// records where focus is after each press (it must stay on the pressed card, with a ring) and the picks count.
//   node enter.mjs > enter.json
import { spawn } from "node:child_process";
import path from "node:path";
const PORT = 9345, wait = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${path.join(process.env.TEMP || ".", "crdeck-cdp-enter")}`, "about:blank"], { stdio: "ignore" });
let target = null;
for (let i = 0; i < 50 && !target; i++) { await wait(200); try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch {} }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); p.resolve(m.result); } });
const send = (method, params = {}) => new Promise((resolve) => { const k = ++id; pending.set(k, { resolve }); ws.send(JSON.stringify({ id: k, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;
const key = async (k, code, vk) => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: k, code, windowsVirtualKeyCode: vk, ...(k === "Enter" && type === "keyDown" ? { text: "\r" } : {}) }); };
await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url: "http://127.0.0.1:8765/index.html#ranked~~" });
for (let t = 0; t < 150; t++) { await wait(200); if (await evaluate(`document.readyState === "complete" && document.querySelectorAll(".deck h3").length === 3 && !/Building|Loading/.test(document.querySelector("#status").textContent)`)) break; }
// Tab until a card in the list has focus
let f = null;
for (let i = 0; i < 80; i++) { await key("Tab", "Tab", 9); f = await evaluate(`document.activeElement && document.activeElement.dataset.key || null`); if (f && (await evaluate(`!!document.activeElement.closest("#cardlist")`))) break; }
const res = { first: f };
for (let n = 1; n <= 9; n++) {
  const k = await evaluate(`document.activeElement.dataset.key`);
  await key("Enter", "Enter", 13); await wait(60);
  const s = await evaluate(`(() => { const a = document.activeElement, cs = getComputedStyle(a); return { key: a.dataset.key || null, ring: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0 || (cs.boxShadow && cs.boxShadow !== "none"), picks: document.querySelectorAll("#seeds .seed.filled").length, note: document.querySelector("#seed-note").textContent }; })()`);
  res[`enter${n}`] = { pressedOn: k, focusAfter: s.key, ring: s.ring, picks: s.picks, note: s.note.slice(0, 80) };
  await key("Tab", "Tab", 9); await key("Tab", "Tab", 9);   // two cards on, so the next pick is a different card
}
console.log(JSON.stringify(res, null, 1));
ws.close(); chrome.kill();
