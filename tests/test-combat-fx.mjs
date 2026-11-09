import assert from 'node:assert/strict';
import test from 'node:test';
import { createCombatFX, DEFAULT_JOBS } from '../starter/combat/game/combat-fx.mjs';

let imageCount = 0;
globalThis.Image = class {
  constructor() { imageCount++; this.naturalWidth = 960; this.naturalHeight = 640; }
  set src(url) {
    this.url = url;
    if (url.endsWith('bad-grid.png')) this.naturalWidth = 961;
    queueMicrotask(() => url.endsWith('fail.png') ? this.onerror() : this.onload());
  }
};
const frame = (x, ms) => ({ x, y: 0, w: 16, h: 16, ms });
const clip = {
  image: './fx/custom-clip.png', pivot: [8, 8],
  phases: { charge: [frame(0, 20), frame(16, 80)], travel: [frame(32, 30), frame(48, 70)], impact: [frame(64, 40), frame(80, 60)] },
};
const input = { x: 100, y: 300, targetX: 650, targetY: 310 };
function canvas() {
  const draws = [], translations = [];
  const ctx = new Proxy({
    globalAlpha: 1,
    drawImage(image, ...args) { draws.push({ image: image.url, args }); },
    translate(x, y) { translations.push([x, y]); },
  }, { get: (target, key) => key in target ? target[key] : () => {} });
  return { ctx, draws, translations };
}
function clipFrame(fx) {
  const view = canvas(); fx.draw(view.ctx);
  return view.draws.find(draw => draw.image.endsWith('custom-clip.png'))?.args[0];
}

test('all motif/move/motion lifecycles snapshot aim and contact exactly once across dt', async () => {
  for (const reducedMotion of [false, true]) for (const job of Object.keys(DEFAULT_JOBS)) for (const heavy of [false, true]) {
    const fx = createCombatFX({ reducedMotion }); await fx.ready;
    const allocated = imageCount, aim = { ...input, heavy };
    const d = fx.cast(job, aim); aim.targetX = 999;
    assert(Object.isFrozen(d)); assert.equal(d.targetX, 650);
    let calls = 0;
    fx.step(d.contactTime - .001, () => calls++); fx.draw(canvas().ctx); assert.equal(calls, 0);
    fx.step(.002, contact => { calls++; assert.equal(contact, d); return { hit: true, x: 660, y: 320 }; });
    const view = canvas(); fx.draw(view.ctx);
    assert(view.translations.some(([x, y]) => x === 660 && y === 320));
    fx.step(100, () => calls++); assert.equal(calls, 1); assert.equal(imageCount, allocated);
    fx.cast(job, { ...input, heavy }); fx.reset(); fx.step(100, () => calls++); assert.equal(calls, 1);
    fx.cast(job, { ...input, heavy }); fx.step(100, () => calls++); assert.equal(calls, 2);
  }
});

test('heavy clips use authored phase duration and real frame durations; light retains motif', async () => {
  const fx = createCombatFX({ jobs: { nova: { motif: 'astral', sheet: './fx/custom-sheet.png', clip } } }); await fx.ready;
  const d = fx.cast('nova', input);
  assert.deepEqual([d.windup, d.flight, d.decay, d.contactTime], [.1, .1, .1, .2]);
  const allocated = imageCount;
  fx.step(.01); assert.equal(clipFrame(fx), 0);
  fx.step(.02); assert.equal(clipFrame(fx), 16);
  fx.step(.09); assert.equal(clipFrame(fx), 32);
  fx.step(.03); assert.equal(clipFrame(fx), 48);
  let calls = 0;
  fx.step(.06, () => { calls++; return { hit: true, x: 670, y: 320 }; }); assert.equal(clipFrame(fx), 64);
  let view = canvas(); fx.draw(view.ctx); assert(view.translations.some(([x, y]) => x === 670 && y === 320));
  assert(view.draws.some(draw => draw.image.endsWith('custom-sheet.png')));
  fx.step(.05, () => calls++); assert.equal(clipFrame(fx), 80);
  fx.step(1, () => calls++); assert.equal(calls, 1); assert.equal(imageCount, allocated);
  const light = fx.cast('nova', { ...input, heavy: false });
  assert.deepEqual([light.windup, light.flight, light.decay], [.14, .26, .34]);
});

test('misses never draw post-contact clips or painted plumes; reduced motion keeps timing', async () => {
  for (const reducedMotion of [false, true]) {
    const fx = createCombatFX({ jobs: { nova: { motif: 'blade', clip } }, reducedMotion }); await fx.ready;
    const d = fx.cast('nova', input); fx.step(.01);
    assert.equal(clipFrame(fx), reducedMotion ? 16 : 0);
    let calls = 0; fx.step(.195, () => { calls++; return false; });
    const view = canvas(); fx.draw(view.ctx); assert.equal(view.draws.length, 0); assert.equal(calls, 1);
    fx.step(5, () => calls++); assert.equal(calls, 1);
    assert.equal(d.contactTime, .2);
  }
});

test('custom loading rejects invalid phase metadata, image geometry, bounds and load failure', async () => {
  assert.throws(() => createCombatFX({ jobs: { bad: { motif: 'blade', clip: { ...clip, phases: { ...clip.phases, travel: [] } } } } }), /phase clip/);
  assert.throws(() => createCombatFX({ jobs: { bad: { motif: 'blade', clip: { ...clip, pivot: [NaN, 8] } } } }), /phase clip/);
  assert.throws(() => createCombatFX({ jobs: { bad: { motif: 'blade', clip: { ...clip, phases: { ...clip.phases, impact: [frame(0, -1)] } } } } }), /phase clip/);
  const bounds = createCombatFX({ jobs: { bad: { motif: 'blade', clip: { ...clip, phases: { ...clip.phases, impact: [frame(959, 100)] } } } } });
  await assert.rejects(bounds.ready, /bounds/);
  await assert.rejects(createCombatFX({ jobs: { bad: { motif: 'rail', sheet: './fx/bad-grid.png' } } }).ready, /3×2/);
  await assert.rejects(createCombatFX({ jobs: { bad: { motif: 'rail', clip: { ...clip, image: './fx/fail.png' } } } }).ready, /failed to load/);
});

test('all feedback events expire, clear on reset and preserve reduced-motion simulation', async () => {
  for (const reducedMotion of [false, true]) {
    const fx = createCombatFX({ reducedMotion }); await fx.ready;
    for (const event of ['parry', 'evade', 'hurt', 'enemyImpact', 'exposed', 'win']) fx.react(event, { x: 400, y: 300 });
    fx.draw(canvas().ctx); fx.step(.1); fx.draw(canvas().ctx); fx.step(2);
    const view = canvas(); fx.draw(view.ctx); assert.equal(view.draws.length, 0);
    fx.react('win', { x: 400, y: 300 }); fx.reset(); fx.draw(view.ctx); assert.equal(view.draws.length, 0);
    assert.throws(() => fx.step(-1), TypeError);
    assert.throws(() => fx.react('unknown', input), RangeError);
  }
});

test('changing reduced motion during flight preserves cache, timeline and exactly one contact', async () => {
  const fx = createCombatFX({ jobs: { nova: { motif: 'astral', clip } } }); await fx.ready;
  const d = fx.cast('nova', input), allocated = imageCount;
  let calls = 0;
  fx.step(.12, () => calls++); assert.equal(calls, 0); assert.equal(clipFrame(fx), 32);
  fx.setReducedMotion(true); assert.equal(clipFrame(fx), 48);
  fx.step(.07, () => calls++); assert.equal(calls, 0);
  fx.setReducedMotion(false);
  fx.step(.02, () => { calls++; return true; }); assert.equal(calls, 1); assert.equal(d.contactTime, .2);
  fx.setReducedMotion(true); fx.draw(canvas().ctx); fx.step(10, () => calls++);
  assert.equal(calls, 1); assert.equal(imageCount, allocated);
});
