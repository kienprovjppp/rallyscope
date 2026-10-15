// Local RallyScope launcher: node scripts/serve.mjs [port]
// Only these public assets are exposed; videos selected in the UI stay in-browser.
import {createServer} from 'node:http';
import {createReadStream, statSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const sample = 'runs/ppa_trim_rally_b/page/';
const routes = new Map([
  ['/', ['template/index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['template/index.html', 'text/html; charset=utf-8']],
  ['/bg.mp4', ['template/bg.mp4', 'video/mp4']],
  ['/data.json', [sample + 'data.json', 'application/json']],
  ['/rally.mp4', [sample + 'rally.mp4', 'video/mp4']],
  ['/rally.webm', [sample + 'rally.webm', 'video/webm']],
  ['/mp/vision_bundle.mjs', ['mp/vision_bundle.mjs', 'text/javascript']],
  ['/mp/wasm/vision_wasm_internal.js', ['mp/wasm/vision_wasm_internal.js', 'text/javascript']],
  ['/mp/pose_model.wasm', ['mp/pose_model.wasm', 'application/wasm']],
  ['/mp/vision_wasm_internal.wasm', ['mp/vision_wasm_internal.wasm', 'application/wasm']],
]);

export function createRallyServer() {
  return createServer((req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (req.method !== 'GET' && req.method !== 'HEAD') {res.writeHead(405, {Allow: 'GET, HEAD'});return res.end();}
    let path;
    try {path = new URL(req.url, 'http://localhost').pathname;} catch {res.writeHead(400);return res.end();}
    if (path === '/template/index.html') {res.writeHead(302, {Location: '/'});return res.end();}
    if (path === '/favicon.ico') {res.writeHead(204);return res.end();}
    const asset = routes.get(path);
    if (!asset) {res.writeHead(404);return res.end();}
    const file = resolve(root, asset[0]);
    let size;
    try {size = statSync(file).size;} catch {res.writeHead(404);return res.end();}
    const headers = {'Content-Type': asset[1], 'Accept-Ranges': 'bytes'};
    let start = 0, end = size - 1, status = 200;
    if (req.headers.range) {
      const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range);
      start = range ? Number(range[1]) : NaN; end = range?.[2] ? Number(range[2]) : size - 1;
      if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < start || start >= size) {
        res.writeHead(416, {'Content-Range': `bytes */${size}`});return res.end();
      }
      end = Math.min(end, size - 1);status = 206;
      headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
    }
    res.writeHead(status, {...headers, 'Content-Length': end - start + 1});
    if (req.method === 'HEAD') return res.end();
    const stream = createReadStream(file, {start, end});
    stream.on('error', () => res.destroy());res.on('close', () => stream.destroy());stream.pipe(res);
  });
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const port = Number(process.argv[2] ?? 8000);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Port must be between 0 and 65535');
  const server = createRallyServer();
  server.on('error', error => {console.error(error.code === 'EADDRINUSE' ? `Port ${port} đang dùng. Thử: node scripts/serve.mjs ${port + 1}` : error.message);process.exitCode = 1;});
  server.listen(port, '127.0.0.1', () => console.log(`RallyScope: http://127.0.0.1:${server.address().port}/`));
}
