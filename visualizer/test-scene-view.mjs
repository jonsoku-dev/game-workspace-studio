import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setLocale } from './i18n.mjs';
import { renderErrorText, inspectionLabel } from './view-messages.mjs';

// Use the existing local loader for the pure timing checks; browsers use /model/loader.mjs.
const loader = new URL('../../assets/plugins/model-assets/three/loader.mjs', import.meta.url).href;
const source = (await readFile(new URL('./scene-view.mjs', import.meta.url), 'utf8')).replace("'/model/loader.mjs'", JSON.stringify(loader))
  .replace("'./view-messages.mjs'", JSON.stringify(new URL('./view-messages.mjs', import.meta.url).href));
const { effectFrameAt, actionPlaybackAt, showScene, createNodeHierarchy, particleStateAt, validateParticleEffect, inspectionDistance } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const frames = [{ duration_ms: 30 }, { duration_ms: 70 }, { duration_ms: 200 }];
for (const [time, expected] of [[0, 0], [29, 0], [30, 1], [99, 1], [100, 2], [299, 2], [300, 0], [330, 1]]) {
  assert.equal(effectFrameAt(frames, true, time), expected);
}
for (const [time, expected] of [[0, 0], [100, 2], [299, 2], [300, -1], [1299, -1], [1300, 0], [1330, 1]]) {
  assert.equal(effectFrameAt(frames, false, time), expected);
}
const action = { loop: false, frames: [{ duration_ms: 100 }, { duration_ms: 150 }, { duration_ms: 50 }] };
const contact = { start_ms: 100, frames: [{ duration_ms: 40 }, { duration_ms: 60 }] };
for (const [elapsed, frame, fx] of [[0, 0, -1], [99, 0, -1], [100, 1, 0], [139, 1, 0], [140, 1, 1], [199, 1, 1], [200, 1, -1], [300, 2, -1], [1299, 2, -1], [1300, 0, -1]]) {
  const state = actionPlaybackAt(action, [contact], elapsed);
  assert.equal(state.frame, frame);
  assert.equal(state.events[0], fx);
}
assert.equal(actionPlaybackAt({ ...action, loop: true }, [contact], 400).events[0], 0);
assert.equal(actionPlaybackAt(action, [{ ...contact, start_ms: 250, frames: [{ duration_ms: 500 }] }], 100).cycle_ms, 1750);
const shortLoop = { loop: true, frames: [{ duration_ms: 30 }, { duration_ms: 70 }] };
const longEffect = { start_ms: 30, frames: [{ duration_ms: 80 }, { duration_ms: 120 }] };
for (const [elapsed, actor, fx, started] of [[29, 0, -1, null], [30, 1, 0, 30], [99, 1, 0, 30],
  [100, 0, 0, 30], [110, 0, 1, 30], [129, 0, 1, 30], [130, 1, 0, 130], [229, 0, 1, 130], [230, 1, 0, 230]]) {
  const state = actionPlaybackAt(shortLoop, [longEffect], elapsed);
  assert.equal(state.frame, actor, `actor at ${elapsed}`);
  assert.deepEqual(state.events, [fx], `newest effect at ${elapsed}`);
  assert.deepEqual(state.event_started_ms, [started], `contact origin at ${elapsed}`);
}
// A very short loop and long effect still produce exactly one newest instance, without an elapsed-time loop.
const bounded = actionPlaybackAt({ loop: true, frames: [{ duration_ms: 1 }] },
  [{ start_ms: 0, frames: [{ duration_ms: 120000 }] }], 1e12 + 0.5);
assert.deepEqual(bounded.events, [0]);
assert.deepEqual(bounded.event_started_ms, [1e12]);
assert.equal(actionPlaybackAt(shortLoop, [{ start_ms: 30, frames: [{ duration_ms: 20 }] }], 100).events[0], -1);
const particle = { offset: [0.01, 0, -0.01], drift: [0.04, 0.18, -0.03], start_s: 0.25, life_s: 1.5, scale: 1.2, spin: [1, 2, 3] };
const descriptor = { schema_version: 1, kind: 'mesh-particles', units: 'meters', duration_s: 3.2, particles: [particle] };
validateParticleEffect(descriptor);
for (const change of [d => d.units = 'pixels', d => d.duration_s = 0, d => d.particles[0].life_s = 4, d => d.particles[0].start_s = -1, d => d.particles[0].drift[0] = Infinity]) {
  const bad = structuredClone(descriptor); change(bad);
  assert.throws(() => validateParticleEffect(bad), /mesh-particles/);
}
// The visualizer must reproduce the model-assets reference sampler (tools/ember.py) exactly.
const contract = JSON.parse(await readFile(new URL('../../assets/plugins/model-assets/tests/ember-samples.json', import.meta.url), 'utf8'));
for (const item of contract.samples) {
  const state = particleStateAt(item.particle, item.duration_s, item.elapsed_s);
  assert.equal(state.visible, item.expected.visible);
  for (const [a, b] of [...state.position, state.scale].map((v, i) => [v, [...item.expected.position, item.expected.scale][i]])) assert.ok(Math.abs(a - b) < 1e-9, `ember contract ${a} != ${b}`);
}
const at = particleStateAt(particle, descriptor.duration_s, 1);
const looped = particleStateAt(particle, descriptor.duration_s, 4.2);
assert.equal(at.visible, true);
assert.equal(particleStateAt(particle, 3.2, 2).visible, false);
assert.ok(Math.abs(at.scale - 1.2) < 1e-12);
assert.deepEqual(at.rotation, [0.75, 1.5, 2.25]);
for (let axis = 0; axis < 3; axis++) {
  assert.ok(Math.abs(at.position[axis] - looped.position[axis]) < 1e-12);
  assert.notEqual(at.position[axis], particleStateAt(particle, 3.2, 0.6).position[axis]);
}
const transform = { rotation_degrees: [0, 0, 0], scale: [1, 1, 1] };
const hierarchy = createNodeHierarchy([
  { ...transform, id: 'ember', parent: 'lantern', position: [0, 0.239, 0] },
  { ...transform, id: 'lantern', position: [1, 0, -2], rotation_degrees: [0, 90, 0], scale: [2, 2, 2] }
]);
hierarchy.root.updateMatrixWorld(true);
const group = hierarchy.groups.get('ember');
assert.deepEqual(group.matrixWorld.elements.slice(12, 15), [1, 0.478, -2]);
assert.equal(group.parent, hierarchy.groups.get('lantern'));
assert.throws(() => createNodeHierarchy([{ ...transform, id: 'a', parent: 'missing', position: [0, 0, 0] }]), /parent missing/);
assert.throws(() => createNodeHierarchy([
  { ...transform, id: 'a', parent: 'b', position: [0, 0, 0] }, { ...transform, id: 'b', parent: 'a', position: [0, 0, 0] }
]), /parent cycle/);
globalThis.cancelAnimationFrame = () => {};
const canvas = { dataset: {} };
await assert.rejects(showScene(canvas, { status: 'failed' }, () => '/unused'), /ready scene runtime/);
assert.equal(canvas.dataset.sceneState, 'error');
assert.equal(JSON.parse(canvas.dataset.sceneMetrics).frame_count, 0);
let aborted = false;
globalThis.fetch = async (_url, { signal }) => new Promise((_resolve, reject) => {
  signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Cancelled', 'AbortError')); });
});
const loading = showScene(canvas, { status: 'ready', schema_version: 1,
  coordinates: { units: 'meters', up: '+Y', handedness: 'right' }, nodes: [{}],
  assets: [{ id: 'model', producer: 'model-assets', files: { model: 'model.glb' } }] }, file => file);
const oldRejected = assert.rejects(loading, { name: 'AbortError' });
await assert.rejects(showScene(canvas, { status: 'failed' }, () => '/unused'), /ready scene runtime/);
await oldRejected;
assert.equal(aborted, true);
assert.equal(canvas.dataset.sceneState, 'error');
console.log('PASS: authored frame boundaries, one-shot review gap, invalid-runtime error state, pending-load cancellation, mesh-particle timing/XYZ motion, parent transforms and cycle/missing-parent rejection, named action contact timing/hold/replay/effect tail, loop-boundary survival/newest-contact retrigger/bounded long-effect playback');

// A fitted inspection camera leaves every box corner inside desktop and portrait views.
const { THREE } = await import(loader);
for (const aspect of [0.5, 1, 2]) {
  const direction = [0.5, 0.28, 1];
  const distance = inspectionDistance([-0.2, 0, -0.1], [0.2, 0.8, 0.1], direction, aspect);
  const camera = new THREE.PerspectiveCamera(38, aspect, 0.001, 100);
  const center = new THREE.Vector3(0, 0.4, 0);
  camera.position.copy(center).add(new THREE.Vector3(...direction).normalize().multiplyScalar(distance));
  camera.lookAt(center); camera.updateMatrixWorld();
  for (const x of [-0.2, 0.2]) for (const y of [0, 0.8]) for (const z of [-0.1, 0.1]) {
    const projected = new THREE.Vector3(x, y, z).project(camera);
    assert.ok(Math.abs(projected.x) < 1 && Math.abs(projected.y) < 1, `box clipped at aspect ${aspect}`);
  }
}
// Exercise the inspection lifecycle with real scene geometry and a minimal GPU boundary.
const boundary = `import { THREE as real } from ${JSON.stringify(loader)};
class Renderer {
  constructor() { this.shadowMap = {}; this.info = {render: {triangles: 2}}; }
  setPixelRatio() {} setSize() {} render() {} dispose() {}
  getContext() { return { VERSION: 1, drawingBufferWidth: 1, drawingBufferHeight: 1, RGBA: 1, UNSIGNED_BYTE: 1, getParameter: () => 'test', readPixels() {} }; }
}
export const THREE = {...real, WebGLRenderer: Renderer};
export const loadModel = () => {}; export const validateReceipt = () => {};`;
const testSource = source.replace(JSON.stringify(loader), JSON.stringify(`data:text/javascript;base64,${Buffer.from(boundary).toString('base64')}`));
const { showScene: inspectScene } = await import(`data:text/javascript;base64,${Buffer.from(testSource).toString('base64')}`);
let sequence = 0;
const scheduled = new Map(), callbacks = new Map();
globalThis.requestAnimationFrame = fn => { scheduled.set(++sequence, fn); return sequence; };
globalThis.cancelAnimationFrame = id => scheduled.delete(id);
globalThis.document = { documentElement: {}, hidden: false, addEventListener: (name, fn) => callbacks.set(name, fn), removeEventListener: name => callbacks.delete(name) };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
let intersectionCallback;
globalThis.IntersectionObserver = class {
  constructor(callback) { intersectionCallback = callback; }
  observe() {} disconnect() { intersectionCallback = null; }
};
globalThis.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
globalThis.createImageBitmap = async () => ({ width: 2, height: 2, close() {} });
globalThis.fetch = async () => ({ ok: true, blob: async () => new Blob(), json: async () => ({
  frames: [{ rect: {x: 0, y: 0, w: 1, h: 1}, duration_ms: 100 }, { rect: {x: 1, y: 0, w: 1, h: 1}, duration_ms: 100 }],
  loop: true, pivot_px_from_top_left: [0.5, 1]
}) });
const attributes = new Map();
globalThis.window = { addEventListener: (name, fn) => callbacks.set(name, fn), removeEventListener: name => callbacks.delete(name) };
const inspectCanvas = { dataset: {}, clientWidth: 320, clientHeight: 480, hasAttribute: name => attributes.has(name),
  setAttribute: (name, value) => attributes.set(name, value), getAttribute: name => attributes.get(name), removeAttribute: name => attributes.delete(name), addEventListener: (name, fn) => callbacks.set(name, fn), removeEventListener: name => callbacks.delete(name) };
const view = await inspectScene(inspectCanvas, { status: 'ready', schema_version: 1,
  coordinates: { units: 'meters', up: '+Y', handedness: 'right' },
  assets: [{ id: 'sprite', producer: 'pixel-effect', files: { metadata: 'meta', sheet: 'sheet' } }],
  nodes: [{ ...transform, id: 'sprite-node', asset: 'sprite', size_m: 1, position: [1, 2, 0] }]
}, file => file);
const flush = () => { const pending = [...scheduled.values()]; scheduled.clear(); for (const fn of pending) fn(performance.now()); };
assert.equal(inspectCanvas.getAttribute('aria-label'), inspectionLabel());
const initialFrames = view.metrics.frame_count;
setLocale('ja'); callbacks.get('studio:localechange')();
assert.equal(inspectCanvas.getAttribute('aria-label'), inspectionLabel());
assert.match(inspectCanvas.getAttribute('aria-label'), /シーン/);
assert.equal(view.metrics.frame_count, initialFrames, 'locale change preserves renderer and current frame');
inspectCanvas.setAttribute('aria-label', 'Authored label');
setLocale('ko'); callbacks.get('studio:localechange')();
assert.equal(inspectCanvas.getAttribute('aria-label'), 'Authored label', 'renderer respects a replacement authored label');
assert.equal(view.metrics.state, 'paused');
assert.equal(scheduled.size, 0, 'reduced motion does not run a continuous loop');
view.seek(100); flush();
assert.equal(view.metrics.elapsed_ms, 100);
assert.equal(view.metrics.effects[0].frame_index, 1);
assert.equal(scheduled.size, 0);
view.seek(0); flush();
assert.equal(view.metrics.effects[0].frame_index, 0);
view.zoom(1.2); flush();
assert.deepEqual(view.metrics.positions[0].position, [1, 2, 0], 'inspection leaves authored placement unchanged');
intersectionCallback([{isIntersecting: false}]);
const offscreenFrames = view.metrics.frame_count;
view.seek(100);
assert.equal(view.metrics.elapsed_ms, 100);
assert.equal(view.metrics.frame_count, offscreenFrames, 'offscreen paused inspection does not render');
assert.equal(scheduled.size, 0);
intersectionCallback([{isIntersecting: true}]);
assert.equal(view.metrics.rendered_elapsed_ms, 100, 'returning to view draws the requested pose immediately');
assert.equal(view.metrics.effects[0].frame_index, 1);
view.setPaused(false); flush();
assert.equal(scheduled.size, 1);
view.setPaused(true);
assert.equal(view.metrics.paused, true, 'pause state is observable without waiting for RAF');
assert.equal(JSON.parse(inspectCanvas.dataset.sceneMetrics).paused, true);
assert.equal(scheduled.size, 0, 'pausing cancels the pending animation frame');
view.seek(0);
for (let step = 0; step < 2; step++) {
  const previous = JSON.parse(inspectCanvas.dataset.sceneMetrics).elapsed_ms;
  view.seek(previous + 100);
}
assert.equal(view.metrics.elapsed_ms, 200, 'rapid steps accumulate without intervening RAF');
assert.equal(JSON.parse(inspectCanvas.dataset.sceneMetrics).elapsed_ms, 200);
assert.equal(view.metrics.effects[0].frame_index, 0, 'the visible paused pose redraws synchronously');
assert.equal(scheduled.size, 0, 'paused inspection creates no duplicate RAF');
view.setPaused(false);
assert.equal(view.metrics.paused, false, 'resume state is also published immediately');
assert.equal(scheduled.size, 1, 'normal playback stays asynchronous');
document.hidden = true; callbacks.get('visibilitychange')();
assert.equal(scheduled.size, 0, 'hidden scenes stop requesting frames');
const hiddenFrames = view.metrics.frame_count;
view.setPaused(true); view.seek(150);
assert.equal(view.metrics.frame_count, hiddenFrames, 'hidden inspection never renders');
assert.equal(view.metrics.elapsed_ms, 150, 'hidden inspection still exposes current control state');
assert.notEqual(view.metrics.rendered_elapsed_ms, 150, 'hidden controls do not claim an unrendered pose as rendered evidence');
assert.equal(scheduled.size, 0, 'hidden seek does not restart RAF');
view.setPaused(false);
document.hidden = false; callbacks.get('visibilitychange')(); flush();
assert.equal(scheduled.size, 1);
view.dispose();
assert.equal(scheduled.size, 0);
assert.equal(callbacks.size, 0, 'inspection and visibility listeners are released');
assert.equal(inspectCanvas.dataset.sceneState, 'disposed');
console.log('PASS: desktop/portrait camera fit, reduced-motion pause, synchronous pause/rapid seek, read-only zoom, hidden/offscreen suspension, rendered-time evidence and disposal');

const actionFrames = [
  { rect: {x: 0, y: 0, w: 1, h: 1}, duration_ms: 100 },
  { rect: {x: 1, y: 0, w: 1, h: 1}, duration_ms: 100 }
];
const available = ['idle', 'walk', 'run', 'attack', 'jump', 'hurt'];
const actionMetadata = { schema_version: 1, pivot_px_from_top_left: [0.5, 1],
  actions: Object.fromEntries(available.map(name => [name, {loop: name !== 'attack', frames: actionFrames}])),
  events: [{ action: 'attack', frame: 1, start_ms: 100, at_px: [1, 0], effect_anchor_px: [0.5, 1],
    pivot_px_from_top_left: [0.5, 1], frames: [actionFrames[0]] }]
};
globalThis.fetch = async file => ({ ok: true, blob: async () => new Blob(), json: async () => file === 'actor-meta' ? actionMetadata :
  {frames: [{duration: 100, frame: actionFrames[0].rect}]} });
const authoredRuntime = { status: 'ready', schema_version: 1,
  coordinates: { units: 'meters', up: '+Y', handedness: 'right' },
  assets: [{ id: 'actor', producer: 'pixel-action-set', files: { metadata: 'actor-meta', atlas: 'actor-sheet', effect_0_metadata: 'fx-meta', effect_0_sheet: 'fx-sheet' } }],
  nodes: [{ ...transform, id: 'actor-node', asset: 'actor', action: 'attack', size_m: 1, position: [1, 2, 0] }]
};
const authoredCopy = JSON.stringify(authoredRuntime);
assert.equal(inspectCanvas.getAttribute('aria-label'), 'Authored label', 'disposal preserves authored label');
const actionView = await inspectScene(inspectCanvas, authoredRuntime, file => file);
assert.equal(callbacks.has('studio:localechange'), false, 'authored canvas label needs no renderer locale listener');
assert.deepEqual(actionView.metrics.inspection.actions, available);
actionView.seek(150); flush();
assert.equal(actionView.metrics.effects[0].frame_index, 0, 'authored attack triggers its contact effect');
assert.equal(actionView.setAction('idle'), true); flush();
assert.equal(actionView.metrics.elapsed_ms, 0);
assert.equal(actionView.metrics.paused, true);
assert.equal(actionView.metrics.actions[0].action, 'idle');
assert.equal(actionView.metrics.actions[0].authored_action, 'attack');
assert.equal(actionView.metrics.inspection.action_override, 'idle');
actionView.seek(150); flush();
assert.equal(actionView.metrics.effects[0].frame_index, -1, 'attack contacts stay hidden during other previews');
for (const name of available) { assert.equal(actionView.setAction(name), true); flush(); assert.equal(actionView.metrics.actions[0].action, name); }
assert.equal(actionView.setAction('death'), false, 'a canonical but missing action is unavailable');
assert.equal(actionView.setAction('constructor'), false);
assert.equal(actionView.setAction(null), true); flush();
assert.equal(actionView.metrics.actions[0].action, 'attack');
assert.equal(actionView.metrics.actions[0].inspection_override, null);
actionView.seek(100); flush();
assert.equal(actionView.metrics.effects[0].frame_index, 0, 'restoring authored action restores contact timing');
assert.equal(JSON.stringify(authoredRuntime), authoredCopy, 'action inspection never rewrites the runtime source');
actionView.dispose();
assert.equal(scheduled.size, 0);
assert.equal(callbacks.size, 0);
console.log('PASS: metadata-limited six-action inspection, missing action rejection, authored action/provenance preservation, preview time reset, inactive contact suppression and original contact restoration');

// Every explicit renderer and shared GLB loader validation has localized feedback.
const rendererSource = await readFile(new URL('./scene-view.mjs', import.meta.url), 'utf8');
const loaderSource = await readFile(new URL(loader), 'utf8');
const errors = [...(rendererSource + loaderSource).matchAll(/throw new Error\('([^']+)'\)/g)].map(match => match[1]);
for (const locale of ['ko', 'ja']) {
  setLocale(locale);
  const fallback = renderErrorText(new Error('unknown detail')).split('\n')[0];
  for (const detail of [...errors, 'Unable to load scene asset (404)', 'Error creating WebGL context.']) {
    const error = new Error(detail);
    const before = error.message;
    const translated = renderErrorText(error);
    assert.notEqual(translated.split('\n')[0], fallback, `${locale}: ${detail}`);
    assert.ok(translated.endsWith(`\n${detail}`), 'original validation detail is preserved');
    assert.equal(error.message, before, 'error contract stays unchanged');
  }
  const detail = 'EACCES: /project/日本語/name.glb <raw> {value}';
  assert.equal(renderErrorText(new Error(detail)), `${fallback}\n${detail}`);
}
setLocale('ko');
// A renderer-owned fallback is removed on disposal and recreated in the next locale.
inspectCanvas.removeAttribute('aria-label');
const fallbackView = await inspectScene(inspectCanvas, authoredRuntime, file => file);
assert.equal(callbacks.has('studio:localechange'), true);
fallbackView.dispose();
assert.equal(inspectCanvas.hasAttribute('aria-label'), false);
assert.equal(callbacks.size, 0);
setLocale('ja');
const nextView = await inspectScene(inspectCanvas, authoredRuntime, file => file);
assert.match(inspectCanvas.getAttribute('aria-label'), /シーン/);
nextView.dispose();
assert.equal(callbacks.size, 0);
setLocale('ko');
console.log('PASS: KO/JA renderer and GLB feedback, unchanged raw diagnostics, fallback label locale refresh, authored label preservation and listener disposal');
