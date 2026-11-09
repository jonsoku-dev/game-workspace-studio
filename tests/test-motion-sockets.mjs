import assert from 'node:assert/strict';
import { mkdtemp, mkdir, copyFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';

globalThis.Image = class {
  naturalWidth = 64;
  naturalHeight = 32;
  set src(value) { queueMicrotask(() => this.onload()); }
};
const actor = {
  image: 'blade.webp', pivot: [16, 24], bodyHeight: 20,
  actions: { idle: [0, 1], release: [0, 1] }, action_ms: { release: [20, 80] },
  frames: [
    { id: 'guard', x: 0, y: 0, w: 32, h: 32, ms: 100, sockets: { weapon: [20, 12] } },
    { id: 'release', x: 32, y: 0, w: 32, h: 32, ms: 200, sockets: { grip: [8, 20] } },
  ],
};
async function load(t, data = actor) {
  const root = await mkdtemp(join(tmpdir(), 'motion-sockets-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'motion'));
  await copyFile(new URL('../starter/combat/game/combat-motion.mjs', import.meta.url), join(root, 'combat-motion.mjs'));
  await writeFile(join(root, 'motion/manifest.mjs'), `export default ${JSON.stringify({ blade: data })};`);
  return import(pathToFileURL(join(root, 'combat-motion.mjs')).href);
}

test('sampler and drawing share frame, exposure timing, pivot, scale and mirror', async t => {
  const { motionReady, sampleActorPose, drawActor } = await load(t);
  await motionReady;
  const options = { kind: 'blade', x: 100, groundY: 200, height: 40 };
  const sampled = sampleActorPose(options);
  assert.equal(sampled.index, 0);
  assert.deepEqual(sampled.socket('weapon'), { x: 108, y: 176 });
  assert.deepEqual(sampleActorPose({ ...options, face: -1 }).socket('weapon'), { x: 92, y: 176 });
  assert.equal(sampled.socket('missing'), null);
  assert.equal(sampled.socket('constructor'), null);
  assert.equal(sampleActorPose({ ...options, x: NaN }), false);
  assert.equal(sampleActorPose({ ...options, kind: 'missing' }), false);
  for (const timing of [{ time: .1 }, { pose: 'release', progress: .2 }, { pose: 'release', progress: 1 }]) {
    const input = { ...options, face: -1, ...timing };
    const current = sampleActorPose(input);
    assert.equal(current.index, 1);
    assert.equal(current.socket('weapon'), null);
    assert.deepEqual(current.socket('grip'), { x: 116, y: 192 });
    const calls = [];
    const ctx = { save() {}, restore() {}, translate(...args) { calls.push(args); },
      scale(...args) { calls.push(args); }, drawImage(...args) { calls.push(args.slice(1)); } };
    assert.equal(drawActor(ctx, input), true);
    assert.deepEqual(calls, [[100, 200], [-2, 2], [current.frame.x, 0, 32, 32, -16, -24, 32, 32]]);
  }
  assert.equal(sampleActorPose({ ...options, time: .3 }).index, 0);
});

test('runtime admission rejects invalid socket names, counts, coordinates and bounds', async t => {
  for (const sockets of [{ 'bad_name': [1, 2] }, { weapon: [null, 2] }, { weapon: [33, 2] },
    { weapon: [1] }, [], null, Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`point-${i}`, [1, 2]]))]) {
    const data = structuredClone(actor);
    data.frames[0].sockets = sockets;
    const { motionReady, sampleActorPose } = await load(t, data);
    await assert.rejects(motionReady, /Invalid motion sockets/);
    assert.equal(sampleActorPose({ kind: 'blade', x: 1, groundY: 2, height: 20 }), false);
  }
});

test('legacy frames without socket metadata remain sampleable and drawable', async t => {
  const legacy = structuredClone(actor);
  for (const frame of legacy.frames) delete frame.sockets;
  const { motionReady, sampleActorPose, drawActor } = await load(t, legacy);
  await motionReady;
  const options = { kind: 'blade', x: 100, groundY: 200, height: 40, time: .1 };
  assert.equal(sampleActorPose(options).index, 1);
  assert.equal(sampleActorPose(options).socket('weapon'), null);
  const ctx = { save() {}, restore() {}, translate() {}, scale() {}, drawImage() {} };
  assert.equal(drawActor(ctx, options), true);
});
