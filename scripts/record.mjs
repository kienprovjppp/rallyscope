// Render the analysis page to a 60 fps MP4, one frame at a time.
//
//   node record.mjs <page folder> out.mp4 [seconds]
//
// The recorder sets the time of every frame itself: __seekTo(t) (resolves after the
// video has seeked), then __draw(t), then a screenshot piped into ffmpeg. Nothing is
// driven by a virtual animation-frame clock. [seconds] defaults to the page's own
// duration (rally + 5 s of end cards).
import { createServer } from "node:http";
import { createReadStream, statSync, existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { spawn, execSync } from "node:child_process";
import { createRequire } from "node:module";

const [dir, out, secArg] = process.argv.slice(2);
if (!dir || !out) { console.error("usage: node record.mjs <page folder> out.mp4 [seconds]"); process.exit(1); }
const root = resolve(dir);
const FPS = 60;

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); }
catch { ({ chromium } = require(join(execSync("npm root -g").toString().trim(), "playwright"))); }

const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".mp4": "video/mp4",
  ".webm": "video/webm", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" };
const server = createServer((req, res) => {
  const p = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(root) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  const size = statSync(p).size, type = TYPES[extname(p)] || "application/octet-stream";
  const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
  if (m) {
    const a = m[1] ? +m[1] : 0, b = m[2] ? +m[2] : size - 1;
    res.writeHead(206, { "Content-Type": type, "Content-Range": `bytes ${a}-${b}/${size}`, "Accept-Ranges": "bytes", "Content-Length": b - a + 1 });
    createReadStream(p, { start: a, end: b }).pipe(res);
  } else {
    res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" });
    createReadStream(p).pipe(res);
  }
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const exe = process.env.CHROME_PATH || undefined;
const browser = await chromium.launch({ executablePath: exe, args: ["--autoplay-policy=no-user-gesture-required", "--hide-scrollbars"] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on("console", m => { if (m.type() === "error") console.error("[page]", m.text()); });
page.on("pageerror", e => console.error("[page error]", e.message));
await page.goto(`http://127.0.0.1:${port}/index.html?record=1`, { waitUntil: "load" });
await page.evaluate(() => window.__ready);
const total = secArg ? +secArg : await page.evaluate(() => window.__duration());
const N = Math.round(total * FPS);
console.log(`recording ${N} frames (${total.toFixed(2)} s) -> ${out}`);

const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
  "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
  { stdio: ["pipe", "inherit", "inherit"] });
const t0 = Date.now();
for (let i = 0; i < N; i++) {
  const t = i / FPS;
  await page.evaluate(t => window.__seekTo(t), t);
  await page.evaluate(t => window.__draw(t), t);
  const buf = await page.screenshot({ type: "jpeg", quality: 93 });
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
  if (i % 60 === 0) console.log(`  ${i}/${N}  ${((Date.now() - t0) / 1000).toFixed(0)} s`);
}
ff.stdin.end();
await new Promise(r => ff.on("close", r));
await browser.close();
server.close();
console.log("done", out);
