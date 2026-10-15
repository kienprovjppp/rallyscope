import assert from 'node:assert/strict';
import test from 'node:test';
import {createRallyServer} from '../scripts/serve.mjs';

test('local launcher serves the template, sample and AI assets from one origin', async t => {
  const server = createRallyServer();
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  t.after(() => {server.closeAllConnections();server.close();});
  const base = `http://127.0.0.1:${server.address().port}`;
  const page = await fetch(base + '/');
  assert.match(await page.text(), /async function loadPose/);
  for (const path of ['/mp/vision_bundle.mjs', '/mp/wasm/vision_wasm_internal.js', '/data.json']) {
    const response = await fetch(base + path);
    assert.equal(response.status, 200, path);
    await response.arrayBuffer();
  }
  const model = await fetch(base + '/mp/pose_model.wasm', {headers: {Range: 'bytes=0-15'}});
  assert.equal(model.status, 206);
  assert.equal((await model.arrayBuffer()).byteLength, 16);
  assert.match(model.headers.get('content-range'), /^bytes 0-15\//);
  assert.equal((await fetch(base + '/template/index.html', {redirect: 'manual'})).status, 302);
  const head = await fetch(base + '/rally.webm', {method: 'HEAD'});
  assert.equal(head.status, 200);
  assert.equal((await head.arrayBuffer()).byteLength, 0);
  for (const path of ['/.git/config', '/AGENTS.md', '/mp/../README.md', '/missing', '/mp/%2e%2e%5cREADME.md']) {
    assert.equal((await fetch(base + path)).status, 404, path);
  }
  assert.equal((await fetch(base + '/mp/pose_model.wasm', {headers: {Range: 'bytes=999999999-'}})).status, 416);
  assert.equal((await fetch(base + '/', {method: 'POST'})).status, 405);
});
