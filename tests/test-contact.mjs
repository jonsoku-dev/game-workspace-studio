import assert from 'node:assert/strict';
import test from 'node:test';
import { socketToWorld, circleSegmentContact, createContactTracker, createTrailHistory } from '../engines/web/contact.mjs';

const surface = { a: { x: 0, y: 0 }, b: { x: 10, y: 0 }, material: 'stone' };
const tool = (x, y, radius = 2) => ({ x, y, radius });

test('socket follows actor pivot, height scale and facing in both directions', () => {
  const actor = { x: 100, y: 200, scale: 3, pivot: [24, 46] };
  assert.deepEqual(socketToWorld([46, 25], actor), { x: 166, y: 137 });
  assert.deepEqual(socketToWorld([46, 25], { ...actor, facing: -1 }), { x: 34, y: 137 });
  assert.deepEqual(socketToWorld(actor.pivot, { ...actor, facing: -1 }), { x: 100, y: 200 });
  assert.throws(() => socketToWorld([NaN, 1], actor), TypeError);
});

test('surface point, outward normal, signed depth, relative slip and material', () => {
  const contact = circleSegmentContact({ ...tool(4, 1), velocity: { x: 7, y: 9 } }, { ...surface, velocity: { x: 2, y: 0 } });
  assert.deepEqual(contact, { hit: true, point: { x: 4, y: 0 }, normal: { x: 0, y: 1 }, depth: 1, t: .4, material: 'stone', slip: 5 });
  const below = circleSegmentContact(tool(4, -3), surface);
  assert.equal(below.hit, false); assert.equal(below.depth, -1);
  assert.deepEqual(below.normal, { x: 0, y: -1 });
  const diagonal = circleSegmentContact(tool(2, 4), { a: { x: 0, y: 0 }, b: { x: 4, y: 4 } });
  assert(Math.abs(diagonal.point.x - 3) < 1e-12);
  assert(Math.abs(diagonal.point.y - 3) < 1e-12);
  assert(Math.abs(diagonal.normal.x + Math.SQRT1_2) < 1e-12);
  assert(Math.abs(diagonal.normal.y - Math.SQRT1_2) < 1e-12);
});

test('finite endpoints, exact tangency and degenerate segment are supported', () => {
  for (const [x, expected, nx] of [[-2, 0, -1], [12, 10, 1]]) {
    const contact = circleSegmentContact(tool(x, 0), surface);
    assert.equal(contact.hit, true); assert.equal(contact.depth, 0);
    assert.deepEqual(contact.point, { x: expected, y: 0 });
    assert.deepEqual(contact.normal, { x: nx, y: 0 });
  }
  const pointSurface = { a: { x: 1, y: 1 }, b: { x: 1, y: 1 } };
  assert.deepEqual(circleSegmentContact(tool(1, 1), pointSurface).normal, { x: 1, y: 0 });
  assert.deepEqual(circleSegmentContact(tool(5, 0), surface).normal, { x: -0, y: 1 });
  assert.throws(() => circleSegmentContact(tool(0, 0, -1), surface), TypeError);
});

test('a stationary spinning disc has signed surface slip, including moving surfaces', () => {
  assert.equal(circleSegmentContact({ ...tool(5, 1), angularVelocity: 10 }, surface).slip, 20);
  assert.equal(circleSegmentContact({ ...tool(5, -1), angularVelocity: 10 }, surface).slip, -20);
  assert.equal(circleSegmentContact({ ...tool(5, 1), angularVelocity: -10 }, { ...surface, velocity: { x: 3, y: 0 } }).slip, -23);
});

test('misses emit no contact; sustained pairs enter once, exit once and reenter', () => {
  const tracker = createContactTracker();
  const update = (x, y, weapon = 'hammer', target = 'rock') => tracker.update(weapon, target, tool(x, y), surface);
  assert.deepEqual(update(5, 4), { phase: 'none' });
  assert.equal(update(5, 1).phase, 'enter');
  assert.equal(update(6, 1).phase, 'stay');
  assert.equal(update(5, 1, 'other').phase, 'enter');
  assert.equal(update(5, 1, 'hammer', 'other').phase, 'enter');
  const exit = update(5, 4);
  assert.equal(exit.phase, 'exit'); assert.equal(exit.hit, false);
  assert.deepEqual(exit.point, { x: 6, y: 0 });
  assert.equal(update(5, 4).phase, 'none');
  assert.equal(update(5, 1).phase, 'enter');
  tracker.reset('hammer', 'rock');
  assert.equal(update(5, 1).phase, 'enter');
  assert.equal(update(5, 1, 'hammer', 'other').phase, 'stay');
  assert.equal(update(5, 1, 'other').phase, 'stay');
  tracker.reset('hammer');
  assert.equal(update(5, 1, 'hammer', 'other').phase, 'enter');
  tracker.reset(); assert.equal(update(5, 1).phase, 'enter');
});

test('trail retains both swept points, expires, and never bridges reset or teleport', () => {
  const trail = createTrailHistory({ lifetime: .1, maxDistance: 20 });
  const sample = (time, x) => trail.sample(time, { x, y: 1 }, { x: x + 8, y: 2 });
  assert.equal(sample(0, 0)[0].breakBefore, true);
  const joined = sample(.02, 2);
  assert.equal(joined.length, 2); assert.equal(joined[1].breakBefore, false);
  assert.deepEqual(joined[1].tip, { x: 10, y: 2 });
  joined[1].tip.x = 999;
  assert.equal(sample(.03, 3)[1].tip.x, 10);
  assert.equal(sample(.04, 40).at(-1).breakBefore, true);
  assert.equal(trail.sample(.05, { x: 40, y: 1 }, { x: 100, y: 2 }).at(-1).breakBefore, true);
  const expired = sample(.2, 41);
  assert.equal(expired.length, 1); assert.equal(expired[0].breakBefore, true);
  trail.reset(); assert.equal(sample(.21, 42).length, 1);
  assert.equal(sample(.1, 43).length, 1);
  assert.throws(() => sample(NaN, 1), TypeError);
  assert.throws(() => createTrailHistory({ lifetime: 0 }), TypeError);
  assert.throws(() => createTrailHistory({ maxDistance: '20' }), TypeError);
});
