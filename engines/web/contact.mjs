// Coordinates are world pixels; times are seconds; velocities are pixels/second.
function point(value) {
  if (!value || !Number.isFinite(value.x) || !Number.isFinite(value.y)) throw new TypeError('Expected a finite {x,y} point');
  return { x: value.x, y: value.y };
}

/** Matches drawActor's translate(x,groundY), scale(face*height/bodyHeight), -pivot. */
export function socketToWorld(socket, { x, y, scale = 1, facing = 1, pivot = [0, 0] }) {
  point({ x, y });
  if (!Array.isArray(socket) || !Array.isArray(pivot) || ![...socket, ...pivot, scale, facing].every(Number.isFinite) || socket.length !== 2 || pivot.length !== 2 || scale <= 0) {
    throw new TypeError('Expected finite socket, pivot and positive scale');
  }
  return { x: x + (socket[0] - pivot[0]) * scale * (facing < 0 ? -1 : 1), y: y + (socket[1] - pivot[1]) * scale };
}

/** A round tool against a finite segment, including its endpoints. Depth > 0 penetrates.
 * Normal points from surface to tool. Slip is signed relative speed along a→b.
 * Tool angularVelocity is radians/second, positive clockwise in canvas y-down.
 * At zero separation the normal is the left perpendicular; a point segment uses +x.
 */
export function circleSegmentContact(tool, surface) {
  const center = point(tool), a = point(surface.a), b = point(surface.b);
  if (!Number.isFinite(tool.radius) || tool.radius < 0) throw new TypeError('Expected a nonnegative finite radius');
  const velocity = point(tool.velocity ?? { x: 0, y: 0 });
  const surfaceVelocity = point(surface.velocity ?? { x: 0, y: 0 });
  const spin = tool.angularVelocity ?? 0;
  if (!Number.isFinite(spin)) throw new TypeError('Expected finite angular velocity');
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy);
  const tangent = length ? { x: dx / length, y: dy / length } : { x: 0, y: 1 };
  const t = length ? Math.max(0, Math.min(1, ((center.x - a.x) * tangent.x + (center.y - a.y) * tangent.y) / length)) : 0;
  const closest = { x: a.x + t * dx, y: a.y + t * dy };
  const nx = center.x - closest.x, ny = center.y - closest.y, distance = Math.hypot(nx, ny);
  const normal = distance ? { x: nx / distance, y: ny / distance } : length ? { x: -tangent.y, y: tangent.x } : { x: 1, y: 0 };
  const depth = tool.radius - distance;
  return {
    hit: depth >= 0, point: closest, normal, depth, t, material: surface.material,
    slip: (velocity.x - surfaceVelocity.x + spin * tool.radius * normal.y) * tangent.x +
      (velocity.y - surfaceVelocity.y - spin * tool.radius * normal.x) * tangent.y,
  };
}

/** Call update once per candidate pair per simulation step, including misses.
 * Only enter/stay/exit are events. Exit retains the last touching coordinates.
 * reset() clears all, reset(weaponId) clears a weapon, reset(weaponId,targetId)
 * clears one pair. Omitted pairs otherwise remain active until updated.
 */
export function createContactTracker() {
  const weapons = new Map();
  return {
    update(weaponId, targetId, tool, surface) {
      const contact = circleSegmentContact(tool, surface);
      const targets = weapons.get(weaponId), previous = targets?.get(targetId);
      if (contact.hit) {
        if (!targets) weapons.set(weaponId, new Map([[targetId, contact]]));
        else targets.set(targetId, contact);
        return { phase: previous ? 'stay' : 'enter', ...contact };
      }
      if (!previous) return { phase: 'none' };
      targets.delete(targetId);
      if (!targets.size) weapons.delete(weaponId);
      return { phase: 'exit', ...previous, hit: false };
    },
    reset(weaponId, targetId) {
      if (!arguments.length) weapons.clear();
      else if (arguments.length === 1) weapons.delete(weaponId);
      else {
        const targets = weapons.get(weaponId);
        targets?.delete(targetId);
        if (targets && !targets.size) weapons.delete(weaponId);
      }
    },
  };
}

/** Store actual root/tip samples for a swept ribbon. Join consecutive samples only
 * when breakBefore is false; reset/teleport/time discontinuities start new ribbons.
 * sample() also prunes idle frames. Returned points are copies owned by the caller.
 */
export function createTrailHistory({ lifetime = .12, maxGap = lifetime, maxDistance = 128 } = {}) {
  if (![lifetime, maxGap, maxDistance].every(n => typeof n === 'number' && n > 0) || !Number.isFinite(lifetime)) throw new TypeError('Expected positive trail limits');
  let samples = [];
  return {
    sample(time, root, tip) {
      if (!Number.isFinite(time)) throw new TypeError('Expected finite sample time');
      root = point(root); tip = point(tip);
      const previous = samples.at(-1);
      const disconnected = !previous || time < previous.time || time - previous.time > maxGap ||
        Math.hypot(root.x - previous.root.x, root.y - previous.root.y) > maxDistance ||
        Math.hypot(tip.x - previous.tip.x, tip.y - previous.tip.y) > maxDistance;
      if (previous && time < previous.time) samples = [];
      samples = samples.filter(sample => time - sample.time < lifetime);
      samples.push({ time, root, tip, breakBefore: disconnected || !samples.length });
      samples[0].breakBefore = true;
      return samples.map(sample => ({ ...sample, root: { ...sample.root }, tip: { ...sample.tip } }));
    },
    reset() { samples = []; },
  };
}
