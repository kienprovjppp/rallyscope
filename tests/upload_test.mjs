// Headless test of the upload flow: serve a site folder, upload a clip, accept the court, wait for the analysis.
// usage: node upload_test.mjs <site folder> <clip.webm> <out prefix> [court.json]
// Optional court.json: {width, height, corners}, ordered far-left, far-right, near-right, near-left.
// PLAYWRIGHT_MODULE selects a local installation; BROWSER_CHANNEL=chrome uses installed Chrome.
// BROWSER_GPU=1 uses the native renderer instead of SwiftShader.
// The site folder holds index.html (from template/), data.json, rally.mp4/webm, mp/ (from the repo root) and
// mpjs/ (vision_bundle.mjs + wasm/ from `npm pack @mediapipe/tasks-vision@0.10.21`); the page is pointed at the
// local copies through window.__MP_BASE / window.__MP_DIR. Playwright Chromium has no H.264: test with VP9 webm.
import { createServer } from "node:http";
import { createReadStream, statSync, existsSync, writeFileSync, readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { extname, join, resolve } from "node:path";
import { execSync } from "node:child_process";
import { createRequire } from "node:module";

const [root_, clip, outPrefix, courtFile] = process.argv.slice(2);
const calibration = courtFile ? JSON.parse(readFileSync(courtFile, "utf8")) : null;
const root = resolve(root_);
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || join(execSync("npm root -g").toString().trim(), "playwright"));
const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".mp4": "video/mp4", ".webm": "video/webm",
  ".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm" };
const server = createServer((req, res) => {
  const p = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(root) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  const size = statSync(p).size, type = TYPES[extname(p)] || "application/octet-stream";
  const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
  if (m) { const a = m[1] ? +m[1] : 0, b = m[2] ? +m[2] : size - 1;
    res.writeHead(206, { "Content-Type": type, "Content-Range": `bytes ${a}-${b}/${size}`, "Accept-Ranges": "bytes", "Content-Length": b - a + 1 });
    createReadStream(p, { start: a, end: b }).pipe(res);
  } else { res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" }); createReadStream(p).pipe(res); }
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || undefined, args: ["--autoplay-policy=no-user-gesture-required",
  ...(process.env.BROWSER_GPU ? [] : ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"])] });
try {
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const logs = [];
page.on("console", m => { const t = `[${m.type()}] ${m.text()}`; logs.push(t); if (m.type() === "error" || m.type() === "warning") console.log(t.slice(0, 300)); });
page.on("pageerror", e => { logs.push("[pageerror] " + e.message); console.log("[pageerror]", e.message); });
await page.addInitScript(() => {
  window.__MP_BASE = "/mpjs"; window.__MP_DIR = "/mp/";
  // Observe the four handles actually drawn by setup; auto-detection can move them.
  // Keep instrumentation in the test, without exposing analyser state in the product.
  const arc = CanvasRenderingContext2D.prototype.arc;
  CanvasRenderingContext2D.prototype.arc = function(x, y, ...args) {
    if (this.canvas.id === "setupCv") {
      window.__courtHandles = [...(window.__courtHandles || []), [x, y]].slice(-4);
    }
    return arc.call(this, x, y, ...args);
  };
});
await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load" });
await page.evaluate(() => window.__ready);
await page.keyboard.press("Escape");
await page.locator("#intro").waitFor({state: "detached"});
console.log("page ready");
await page.setInputFiles("#file", clip);
await page.waitForFunction(() => !document.getElementById("setup").hidden, null, { timeout: 180000 });
await page.waitForTimeout(500);
await page.screenshot({ path: `${outPrefix}_setup.png`, fullPage: false });
const corners = await page.evaluate(() => document.getElementById("setupMsg").textContent);
console.log("setup:", corners);
if (calibration) {
  const {width, height, corners: target} = calibration;
  assert(width > 0 && height > 0 && target.length === 4, "invalid calibration fixture");
  const box = await page.locator("#setupCv").boundingBox();
  const size = await page.locator("#setupCv").evaluate(c => [c.width, c.height]);
  for (let i = 0; i < 4; i++) {
    const handles = await page.evaluate(() => window.__courtHandles);
    assert.equal(handles.length, 4, "setup must draw four handles");
    await page.mouse.move(box.x + handles[i][0] / size[0] * box.width, box.y + handles[i][1] / size[1] * box.height);
    await page.mouse.down();
    await page.mouse.move(box.x + target[i][0] / width * box.width, box.y + target[i][1] / height * box.height, {steps: 8});
    await page.mouse.up();
    const actual = await page.evaluate(i => window.__courtHandles[i], i);
    assert(Math.hypot(actual[0] - target[i][0] / width * size[0], actual[1] - target[i][1] / height * size[1]) < 2,
      `court handle ${i} did not reach its measured corner`);
  }
  await page.screenshot({path: `${outPrefix}_calibrated.png`});
}
await page.click("#btnGo");
const t0 = Date.now();
let lastStep = "";
for (;;) {
  const st = await page.evaluate(() => ({ proc: !document.getElementById("proc").hidden, step: document.getElementById("procStep").textContent,
    meta: document.getElementById("procMeta").textContent, title: document.getElementById("procTitle").textContent, auto: !!(typeof D !== "undefined" && D && D.meta && D.meta.auto) }));
  if (st.step !== lastStep) { console.log(`${((Date.now() - t0) / 1000).toFixed(0)}s`, st.title, "|", st.step, "|", st.meta); lastStep = st.step; }
  if (st.auto && !st.proc) break;
  if (st.title.startsWith("Chưa phân tích")) { console.log("FAILED:", st.step); break; }
  if (Date.now() - t0 > 40 * 60 * 1000) { console.log("timeout"); break; }
  if ((Date.now() - t0) % 60000 < 2000) await page.screenshot({ path: `${outPrefix}_proc.png` });
  await page.waitForTimeout(2000);
}
const summary = await page.evaluate(() => typeof D !== "undefined" && D && D.meta.auto ? {
  fps: D.meta.fps, frames: D.range.frames, start: D.range.start, end: D.range.end,
  strikes: D.strikes.map(s => [s.frame, s.t, s.player, s.type, s.kmh]), bounces: D.bounces.map(b => [b.frame, b.court, b.in]),
  players: D.players.map(p => [p.id, p.total, p.parts, p.notes, p.detected_pct]),
  ballFrames: D.series.ball.filter(Boolean).length } : null);
writeFileSync(`${outPrefix}_summary.json`, JSON.stringify(summary, null, 1));
console.log(JSON.stringify(summary && { ...summary, players: summary.players.map(p => [p[0], p[1], p[4]]) }));
if (summary) {
  await page.evaluate(() => window.scrollTo(0, 0));
  for (const t of [1.5, 3.8, 6.2]) { await page.evaluate(t => window.__seekTo(t), t); await page.evaluate(t => window.__draw(t), t); await page.screenshot({ path: `${outPrefix}_t${t}.png` }); }
  await page.screenshot({ path: `${outPrefix}_full.png`, fullPage: true });
}
writeFileSync(`${outPrefix}_console.txt`, logs.join("\n"));
assert(summary && summary.frames > 0 && summary.players.length === 4, "upload did not produce an analysis");
assert(!logs.some(s => s.startsWith("[pageerror]")), "uncaught browser error");
} finally {
  await browser.close();
  server.closeAllConnections();
  server.close();
}
