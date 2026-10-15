// Run with: node --test tests/court_tracking_test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../template/index.html', import.meta.url), 'utf8');
const section = (start, end) => {
  const a = html.indexOf(start), b = html.indexOf(end, a);
  assert(a >= 0 && b > a, `missing analyser section: ${start}`);
  return html.slice(a, b);
};
const source = [
  section('const clamp =', 'const st ='),
  section('const CWd =', 'const KEEP ='),
  section('function median(', '// ------------------------------------------------------------------ video helpers'),
  section('const cropCv =', '// ------------------------------------------------------------------ background and court'),
  section('function minMax1(', 'function lineMask('),
  section('function lineMask(', 'function courtModel('),
  section('function courtModel(', '// ------------------------------------------------------------------ setup screen'),
  section('function makeBallFinder(', '// ------------------------------------------------------------------ audio:'),
  section('function torsoColor(', '// ------------------------------------------------------------------ post-processing'),
].join('\n');

const aw = 960, ah = 540;
// The baselines slope and both sidelines converge: screen Y is not court depth.
const corners = [[300, 160], [720, 215], [850, 480], [110, 435]];

function analyser() {
  const scene = [];
  let sceneAt = () => scene, time = 0, clock = 0;
  const pixels = new Uint8ClampedArray(aw * ah * 4).fill(65);
  const mk = () => {
    const canvas = {};
    canvas.getContext = () => ({
      fillRect() {},
      drawImage(_src, x, y, w, h) { canvas.crop = [x, y, w, h]; },
      getImageData() {
        const data = pixels.slice();
        for (const p of sceneAt(time)) if (p.color) {
          for (const [a, b, c, e, color] of [[11, 12, 23, 24, p.color.slice(0, 3)], [23, 24, 25, 26, p.color.slice(3)]]) {
            const left = Math.floor(Math.min(p[a].x, p[b].x, p[c].x, p[e].x)), right = Math.ceil(Math.max(p[a].x, p[b].x, p[c].x, p[e].x));
            const top = Math.floor(Math.min(p[a].y, p[b].y)), bottom = Math.ceil((p[c].y + p[e].y) / 2);
            for (let y = Math.max(0, top); y <= Math.min(ah - 1, bottom); y++) for (let x = Math.max(0, left); x <= Math.min(aw - 1, right); x++) data.set(color, (y * aw + x) * 4);
          }
        }
        return {data};
      },
      beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {},
    });
    return canvas;
  };
  // Fake only the expensive neural inference. Cropping, projection, duplicate
  // removal and player selection all execute the production implementation.
  const LM = {detect(canvas) {
    const [x, y, w, h] = canvas.crop, side = Math.max(w, h);
    return {landmarks: sceneAt(time).filter(p => p[23].x >= x && p[23].x < x + w && p[23].y >= y && p[23].y < y + h)
      .map(p => p.map(q => ({x: (q.x - x) / side, y: (q.y - y) / side, visibility: q.visibility ?? 1})))};
  }};
  const api = vm.runInNewContext(`${source}; ({courtModel, hom, detectCourt, findPlayers, playerInCourt, makeBallFinder, solveBall, framePass})`, {
    mk, LM, c2d: c => c.getContext('2d'), $: () => mk(),
    seekV: async (_av, t) => { time = t; }, tick: async () => {},
    check() {}, say() {}, prog() {}, PCOL: ['red', 'green', 'blue', 'pink'],
    grayThumb: () => [], medAbsDiff: () => 0, performance: {now: () => ++clock * 200},
    clearInterval, setInterval,
  });
  const cm = api.courtModel(corners, aw, ah);
  const pose = (x, y) => {
    const [fx, fy] = api.hom(cm.Hinv, [x, y]);
    const height = 0.3 * (fy - cm.hz) / 1.15;
    const p = Array.from({length: 33}, () => ({x: fx, y: fy - height / 2}));
    p[0] = {x: fx, y: fy - height};
    for (const [left, right, fraction, width] of [[11, 12, 0.8, 0.15], [23, 24, 0.5, 0.1], [25, 26, 0.25, 0.08], [27, 28, 0, 0.07]]) {
      p[left] = {x: fx - width * height, y: fy - fraction * height};
      p[right] = {x: fx + width * height, y: fy - fraction * height};
    }
    return p;
  };
  return {...api, cm, scene, pose, setSceneAt: fn => { sceneAt = fn; }};
}

test('angled camera keeps two real players on each calibrated half', () => {
  const a = analyser();
  a.scene.push(...[[1.4, 3], [4.7, 3], [1.4, 11], [4.7, 11]].map(([x, y]) => a.pose(x, y)));
  const players = a.findPlayers({}, corners, a.cm, aw, ah);
  assert.equal(players.far.length, 2);
  assert.equal(players.near.length, 2);
  for (const p of [...players.far, ...players.near]) {
    assert(p.g[0] >= 0 && p.g[0] <= 6.1 && p.g[1] >= 0 && p.g[1] <= 13.41);
  }
});

test('an occluded far player is not replaced by a spectator three metres behind the baseline', () => {
  const a = analyser();
  a.scene.push(...[[1.4, 3], [1.4, 11], [4.7, 11], [4.7, -3]].map(([x, y]) => a.pose(x, y)));
  const players = a.findPlayers({}, corners, a.cm, aw, ah);
  assert.equal(players.near.length, 2);
  assert.equal(players.far.length, 1, 'leave a missing player empty instead of seeding a spectator');
});

test('a partial near-player detection with uncertain ankles cannot seed a far player', () => {
  const a = analyser();
  a.scene.push(...[[1.4, 3], [1.4, 11], [4.7, 11]].map(([x, y]) => a.pose(x, y)));
  // A cropped near body can have confident hips/shoulders but hallucinated feet
  // projecting into the far half. These ankle confidences match the video failure.
  const partial = a.pose(4.7, 3);
  partial[27].visibility = 0.37;
  partial[28].visibility = 0.14;
  a.scene.push(partial);
  const players = a.findPlayers({}, corners, a.cm, aw, ah);
  assert.equal(players.near.length, 2);
  assert.equal(players.far.length, 1, 'uncertain feet must not establish another player identity');
});

test('moderately confident hallucinated feet from a cropped body cannot establish a player', () => {
  const a = analyser();
  a.scene.push(...[[1.4, 3], [1.4, 11], [4.7, 11]].map(([x, y]) => a.pose(x, y)));
  const partial = a.pose(4.7, 3);
  partial[27].visibility = 0.479;
  partial[28].visibility = 0.437;
  a.scene.push(partial);
  assert.equal(a.findPlayers({}, corners, a.cm, aw, ah).far.length, 1, 'these feet are too uncertain to seed a new identity');
});

test('a server 2.5 metres behind the baseline remains eligible with an angled camera', () => {
  const a = analyser();
  a.scene.push(...[[1.4, 3], [4.7, -2.5], [1.4, 11], [4.7, 11]].map(([x, y]) => a.pose(x, y)));
  const players = a.findPlayers({}, corners, a.cm, aw, ah);
  assert.equal(players.near.length, 2);
  assert.equal(players.far.length, 2);
  assert(players.far.some(p => Math.abs(p.g[1] + 2.5) < 0.001), 'keep the real serving player outside the baseline');
});

test('non-finite body coordinates and confidence cannot pass court validation', () => {
  const a = analyser();
  const pose = Float32Array.from(a.pose(1.4, 3).flatMap(p => [p.x, p.y, 1]));
  assert(a.playerInCourt(pose, a.cm, ah), 'the original pose must be eligible');
  for (const joint of [11, 23, 27]) for (const component of [0, 1, 2]) {
    const invalid = pose.slice();
    invalid[joint * 3 + component] = NaN;
    assert(a.playerInCourt(invalid, a.cm, ah) === null, `reject NaN at joint ${joint}, component ${component}`);
  }
});

test('reacquiring a lost player cannot move its skeleton to the crowd behind the court', async () => {
  const a = analyser();
  const players = [[1.4, 3], [4.7, 3], [1.4, 11], [4.7, 11]].map(([x, y]) => a.pose(x, y));
  const crowd = a.pose(4.7, -3);
  a.setSceneAt(t => t === 0 ? players : [players[0], players[2], players[3], crowd]);
  const {recs} = await a.framePass({pause() {}}, {
    aw, ah, corners, cm: a.cm, t0: 0, t1: 0.8, bg: background(), ref: [],
  });
  assert(recs[0].lm.every(Boolean), 'all four real players must first be acquired');
  for (const r of recs) for (const pts of r.lm.filter(Boolean)) {
    const ground = a.hom(a.cm.H, [(pts[81] + pts[84]) / 2, (pts[82] + pts[85]) / 2]);
    assert(ground[1] > -1, `frame ${r.t.toFixed(3)} assigned a spectator at court depth ${ground[1].toFixed(2)} m`);
  }
});

test('players on the same team keep their identities after an occlusion and crossing', async () => {
  const a = analyser(), near = [a.pose(1.4, 11), a.pose(4.7, 11)];
  const green = a.pose(1.4, 3), black = a.pose(4.7, 3);
  green.color = [25, 50, 45, 25, 100, 75]; black.color = [25, 50, 45, 20, 25, 30];
  const greenAfter = a.pose(4.7, 3), blackAfter = a.pose(1.4, 3);
  greenAfter.color = green.color; blackAfter.color = black.color;
  a.setSceneAt(t => t < 0.1 ? [...near, green, black] : t < 0.19 ? near : [...near, greenAfter, blackAfter]);
  const {recs} = await a.framePass({pause() {}}, {aw, ah, corners, cm: a.cm, t0: 0, t1: 1.5, bg: background(), ref: []});
  const recovered = [0, 0];
  for (const r of recs.filter(r => r.t >= 0.19)) for (const [id, expected] of [[2, greenAfter], [3, blackAfter]]) {
    if (!r.lm[id]) continue;
    recovered[id - 2]++;
    assert(Math.abs(r.lm[id][69] - expected[23].x) < 5, `P${id + 1} switched to its teammate after losing sight`);
  }
  assert(recovered.every(n => n >= 2), 'the tracker must recover both original players');
});

test('lighting changes on matching red shirts do not override shorts colour and swap near players', async () => {
  const a = analyser(), far = [a.pose(1.4, 3), a.pose(4.7, 3)];
  const blue = a.pose(4.7, 11), black = a.pose(1.4, 11), blueAfter = a.pose(1.4, 11), blackAfter = a.pose(4.7, 11);
  blue.color = [120, 55, 69, 18, 29, 67]; black.color = [177, 111, 109, 17, 19, 24];
  blueAfter.color = [148, 69, 88, 27, 37, 83]; blackAfter.color = [117, 27, 32, 21, 11, 17];
  a.setSceneAt(t => t < 0.1 ? [...far, blue, black] : t < 0.19 ? far : [...far, blueAfter, blackAfter]);
  const {recs} = await a.framePass({pause() {}}, {aw, ah, corners, cm: a.cm, t0: 0, t1: 1.5, bg: background(), ref: []});
  const recovered = [0, 0];
  for (const r of recs.filter(r => r.t >= 0.19)) for (const [id, expected] of [[0, blueAfter], [1, blackAfter]]) {
    if (!r.lm[id]) continue;
    recovered[id]++;
    assert(Math.abs(r.lm[id][69] - expected[23].x) < 5, `P${id + 1} changed identity with shirt brightness`);
  }
  assert(recovered.every(n => n >= 2), 'recover both original near players');
});

function background() {
  const d = new Uint8ClampedArray(aw * ah * 4);
  for (let i = 0; i < d.length; i += 4) d.set([65, 65, 70, 255], i);
  return d;
}
function yellow(d, x, y) { d.set([230, 235, 25, 255], (y * aw + x) * 4); }
function ball(d, x, y) {
  for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
    if (dx * dx + dy * dy <= 4) yellow(d, x + dx, y + dy);
  }
}

function courtImage(a, half = false) {
  const d = background(), start = half ? 6.705 : 0;
  const segments = [[[0, start], [6.1, start]], [[0, 13.41], [6.1, 13.41]],
    [[0, start], [0, 13.41]], [[6.1, start], [6.1, 13.41]],
    [[0, 8.835], [6.1, 8.835]], [[3.05, 8.835], [3.05, 13.41]]];
  if (!half) segments.push([[0, 4.575], [6.1, 4.575]], [[3.05, 0], [3.05, 4.575]]);
  for (const [u, v] of segments) {
    const p = a.hom(a.cm.Hinv, u), q = a.hom(a.cm.Hinv, v), n = Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]));
    for (let k = 0; k <= n; k++) for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const x = Math.round(p[0] + (q[0] - p[0]) * k / n) + dx, y = Math.round(p[1] + (q[1] - p[1]) * k / n) + dy;
      if (x >= 0 && y >= 0 && x < aw && y < ah) d.set([240, 240, 240, 255], (y * aw + x) * 4);
    }
  }
  return d;
}

test('automatic court detection accepts a complete angled court', () => {
  const a = analyser(), result = a.detectCourt(courtImage(a), aw, ah);
  assert(result, 'the full court has both kitchen lines');
  result.forEach((p, i) => assert(Math.hypot(p[0] - corners[i][0], p[1] - corners[i][1]) < 8));
});

test('automatic court detection does not present the near half as a complete court', () => {
  const a = analyser();
  assert.equal(a.detectCourt(courtImage(a, true), aw, ah), null, 'ask for manual calibration when the far half is missing');
});

test('moving small yellow ball is retained while an unchanged yellow logo is masked', () => {
  const a = analyser(), bg = background();
  ball(bg, 500, 130);
  const find = a.makeBallFinder(bg, aw, ah, corners);
  for (let t = 0; t < 8; t++) {
    const d = bg.slice();
    ball(d, 400 + 6 * t, 330);
    const candidates = find(d);
    assert.equal(candidates.length, 1);
    assert(Math.hypot(candidates[0][0] - (400 + 6 * t), candidates[0][1] - 330) < 1);
  }
});

test('a moving ball close to a yellow sign is not erased by the background mask padding', () => {
  const a = analyser(), bg = background();
  ball(bg, 500, 330);
  const find = a.makeBallFinder(bg, aw, ah, corners), d = bg.slice();
  ball(d, 494, 330);
  assert(find(d).some(p => Math.hypot(p[0] - 494, p[1] - 330) < 1), 'keep a changed ball inside the padded sign mask');
});

test('a near-camera ball is not rejected by the LED size limit', () => {
  const a = analyser(), bg = background(), d = bg.slice();
  for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) if (dx * dx + dy * dy <= 16) yellow(d, 500 + dx, 330 + dy);
  assert(a.makeBallFinder(bg, aw, ah, corners)(d).some(p => Math.hypot(p[0] - 500, p[1] - 330) < 1), 'retain a round ball larger than the far-court ball');
});

test('changing yellow LED patches are not ball candidates beside the real moving ball', () => {
  const a = analyser(), bg = background(), find = a.makeBallFinder(bg, aw, ah, corners);
  for (let t = 0; t < 8; t++) {
    const d = bg.slice();
    ball(d, 400 + 6 * t, 330);
    // A moving 12x9 advertising tile was absent from the median background.
    for (let y = 125; y < 134; y++) for (let x = 550 + 2 * t; x < 562 + 2 * t; x++) yellow(d, x, y);
    const candidates = find(d);
    assert.equal(candidates.length, 1, 'reject the large LED patch without losing the small ball');
    assert(Math.hypot(candidates[0][0] - (400 + 6 * t), candidates[0][1] - 330) < 1);
  }
});

test('slowly jittering small logo cannot win the ball path or fill an occlusion', () => {
  const a = analyser(), n = 30;
  const candidates = Array.from({length: n}, (_, t) => {
    const logo = [550 + 0.15 * t + 0.5 * Math.sin(t / 3), 130, 0, 1];
    return t >= 12 && t < 17 ? [logo] : [[350 + 6 * t, 330, 0.4, 1], logo];
  });
  a.solveBall(candidates, n, 1, 30).forEach((p, t) => {
    if (t >= 12 && t < 17) assert.equal(p, null, 'a missing ball must not become the logo');
    else assert.deepEqual(Array.from(p), [350 + 6 * t, 330]);
  });
});

test('brief flashing stationary logos do not become isolated ball tracks', () => {
  const a = analyser(), n = 180;
  const candidates = Array.from({length: n}, (_, t) => {
    const flashing = (t >= 30 && t <= 41) || (t >= 86 && t <= 91) || (t >= 116 && t <= 122);
    return flashing ? [[700 + (t % 3) * 0.3, 400, 0, 1]] : [];
  });
  const track = a.solveBall(candidates, n, 1, 60);
  assert(track.every(p => p === null), 'a 5-12 frame LED flash has no moving ball trajectory');
});
