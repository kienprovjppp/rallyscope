// Screenshots of the analysis page at given times, for checking before handover.
//
//   node shots.mjs <page folder> <out prefix> t1 t2 ...    (times in seconds; "end+2" = 2 s into the end cards)
//   node shots.mjs <page folder> <out prefix> --interactive  (the interactive page, full length)
import { createServer } from "node:http";
import { createReadStream, statSync, existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { execSync } from "node:child_process";
import { createRequire } from "node:module";

const [dir, prefix, ...times] = process.argv.slice(2);
const root = resolve(dir);
const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch { ({ chromium } = require(join(execSync("npm root -g").toString().trim(), "playwright"))); }
const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".mp4": "video/mp4", ".webm": "video/webm" };
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
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
const errors = [];
if (times[0] === "--interactive") {
  for (const [w, h, tag] of [[1440, 900, "desktop"], [390, 844, "phone"]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    page.on("pageerror", e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load" });
    await page.evaluate(() => window.__ready);
    await page.screenshot({ path: `${prefix}_${tag}.png`, fullPage: true });
    console.log(`${prefix}_${tag}.png`);
    await page.close();
  }
} else {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(`http://127.0.0.1:${port}/index.html?record=1`, { waitUntil: "load" });
  await page.evaluate(() => window.__ready);
  const dur = await page.evaluate(() => window.__duration() - 5);
  for (const s of times) {
    const t = s.startsWith("end+") ? dur + parseFloat(s.slice(4)) : parseFloat(s);
    await page.evaluate(t => window.__seekTo(t), t);
    await page.evaluate(t => window.__draw(t), t);
    const out = `${prefix}_${s.replace("+", "p")}.png`;
    await page.screenshot({ path: out });
    console.log(out);
  }
}
if (errors.length) console.log("PAGE ERRORS:\n" + errors.join("\n"));
await browser.close();
server.close();
