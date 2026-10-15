import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../template/index.html', import.meta.url), 'utf8');
const constants = html.slice(Math.min(html.indexOf('const MP_BASE ='), html.indexOf('const MP_DIR =')), html.indexOf('const CWd ='));
test('the default AI runtime resolves beside the page without a CDN override', () => {
  const paths = vm.runInNewContext(`${constants}; ({MP_BASE, MP_DIR})`, {
    window: {}, location: {href: 'http://127.0.0.1:8000/index.html'}, URL,
  });
  assert.equal(new URL(paths.MP_BASE + '/vision_bundle.mjs', 'http://127.0.0.1:8000/').origin, 'http://127.0.0.1:8000');
});

test('opening a video from file:// explains how to start localhost before analysing', async () => {
  const source = html.slice(html.indexOf('async function run(file)'), html.indexOf('$("file").addEventListener("change"'));
  const elements = new Map(), $ = id => { if (!elements.has(id)) elements.set(id, {}); return elements.get(id); };
  let videoReads = 0, message = '';
  const run = vm.runInNewContext(`let job=null; class Cancelled extends Error {}; ${source}; run`, {
    window: {}, URL: {createObjectURL: () => 'blob:test'}, location: {protocol: 'file:'},
    document: {createElement: () => ({pause() {}})}, $, showOnly() {}, prog() {},
    say: s => {message=s;}, console: {error() {}},
    waitMeta: async () => {videoReads++; throw new Error('Unexpected video read');},
  });
  await run({name: 'clip.mp4'});
  assert.match(message, /localhost|127\.0\.0\.1/);
  assert.equal(videoReads, 0, 'reject file:// before background sampling and model loading');
});

test('model loading failures identify the missing asset and preserve HTTP status', async () => {
  const source = html.slice(html.indexOf('async function loadPose()'), html.indexOf('// detect poses in a square crop'));
  for (const [fetch, expected] of [
    [async () => {throw new TypeError('Failed to fetch');}, /mp\/pose_model\.wasm.*Failed to fetch/],
    [async () => ({ok: false, status: 404}), /mp\/pose_model\.wasm.*HTTP 404/],
  ]) {
    const loadPose = vm.runInNewContext(`let mpLib={},poseBuf=null,LM=null;${source};loadPose`, {fetch,MP_DIR:'mp/',say() {}});
    await assert.rejects(loadPose(), expected);
  }
});
