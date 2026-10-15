// Run with: node tests/ball_tracking_test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const html = readFileSync(new URL('../template/index.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('function solveBall('), html.indexOf('// ------------------------------------------------------------------ audio:'));
const { solveBall } = vm.runInNewContext(`${source}; ({solveBall})`);
for (const fps of [30, 60]) {
  const n = fps, scale = 60 / fps;
  const moving = t => [100 + 300 * t / fps, 200, 0.4, 1];
  const dots = t => [[700 + (t % 3 - 1), 400, 0, 1], [900, 500, 0, 1]];
  const candidates = Array.from({length: n}, (_, t) => [moving(t), ...dots(t)]);
  const before = JSON.stringify(candidates);
  const track = solveBall(candidates, n, scale, fps);
  assert.equal(JSON.stringify(candidates), before, 'must not mutate observations');
  track.forEach((p, t) => assert.deepEqual(Array.from(p), moving(t).slice(0, 2), 'follow moving ball, not static dots'));
  assert(solveBall(Array.from({length: n}, (_, t) => dots(t)), n, scale, fps).every(p => p === null), 'only stationary dots: no ball');
  const gap = candidates.map((cs, t) => t >= fps / 3 && t < fps / 2 ? cs.slice(1) : cs);
  solveBall(gap, n, scale, fps).forEach((p, t) => {
    if (t >= fps / 3 && t < fps / 2) assert.equal(p, null, 'occlusion must not switch to a dot');
    else assert.deepEqual(Array.from(p), moving(t).slice(0, 2));
  });
}
assert.equal(solveBall([], 0, 1).length, 0);
const turn = Array.from({length: 60}, (_, t) => [[100 + 0.3 * (t - 30) ** 2, 200, 0, 1]]);
solveBall(turn, 60, 1).forEach((p, t) => assert.deepEqual(Array.from(p), turn[t][0].slice(0, 2), 'preserve a brief turn'));
console.log('Ball tracking: moving ball, static dots, jitter, occlusion, 30/60 fps passed');

if (process.argv.includes('--browser')) {
  const require = createRequire(import.meta.url);
  const root = execFileSync('cmd.exe', ['/c', 'npm.cmd root -g'], {encoding: 'utf8'}).trim();
  const { chromium } = require(join(root, 'playwright'));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.addScriptTag({content: source});
    const track = await page.evaluate(() => solveBall(Array.from({length: 60}, (_, t) => [
      [100 + 5 * t, 200, 0.4, 1], [700, 400, 0, 1], [900, 500, 0, 1],
    ]), 60, 1, 60));
    track.forEach((p, t) => assert.deepEqual(p, [100 + 5 * t, 200]));
    console.log('Chromium: moving ball with two static dots passed');
  } finally {
    await browser.close();
  }
}
