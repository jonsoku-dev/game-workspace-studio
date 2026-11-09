import manifest from './motion/manifest.mjs';

const sheets = new Map();
const clamp = value => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
export const motionReady = Promise.all(Object.entries(manifest).map(([kind, actor]) => {
  const image = new Image();
  const entry = { image, loaded: false };
  sheets.set(kind, entry);
  return new Promise((resolve, reject) => {
    image.onload = () => {
      const badTiming = actor.action_ms !== undefined && (actor.action_ms === null || typeof actor.action_ms !== 'object' || Array.isArray(actor.action_ms) || Object.entries(actor.action_ms).some(([state, durations]) =>
        !actor.actions[state] || !Array.isArray(durations) || durations.length !== actor.actions[state].length || durations.some(ms => !Number.isInteger(ms) || ms < 1 || ms > 60000) || durations.reduce((sum, ms) => sum + ms, 0) > 60000));
      const badSockets = actor.frames.some(frame => frame.sockets !== undefined &&
        (frame.sockets === null || typeof frame.sockets !== 'object' || Array.isArray(frame.sockets) ||
          Object.keys(frame.sockets).length > 16 || Object.entries(frame.sockets).some(([name, point]) =>
            !/^[a-z][a-z0-9-]{0,47}$/.test(name) || !Array.isArray(point) || point.length !== 2 ||
            point.some((value, axis) => !Number.isFinite(value) || value < 0 || value > (axis ? frame.h : frame.w)))));
      if (badSockets) { reject(new Error(`Invalid motion sockets: ${kind}`)); return; }
      if (badTiming) { reject(new Error(`Invalid motion action timing: ${kind}`)); return; }
      if (!actor.frames.length || actor.frames.some(f => f.x < 0 || f.y < 0 || f.w <= 0 || f.h <= 0 || f.x + f.w > image.naturalWidth || f.y + f.h > image.naturalHeight || f.ms <= 0)) {
        reject(new Error(`Invalid motion atlas bounds: ${kind}`));
        return;
      }
      entry.loaded = true;
      resolve();
    };
    image.onerror = () => reject(new Error(`Motion atlas failed to load: ${kind}`));
    image.src = new URL(`./motion/${actor.image}`, import.meta.url).href;
  });
}));
motionReady.catch(() => {});

// Socket points are frame-local cell pixels, independent of atlas coordinates.
export function sampleActorPose({ kind, x, groundY, height, face = 1, pose = 'idle', progress = 0, time = 0 }) {
  const actor = manifest[kind];
  const entry = sheets.get(kind);
  if (!actor || !entry?.loaded || !Number.isFinite(height) || height <= 0 || !Number.isFinite(x) || !Number.isFinite(groundY)) return false;
  const alias = pose === 'walk' || pose === 'run' ? 'move' : pose === 'jump' ? 'evade' : 'idle';
  const state = actor.actions[pose] ? pose : actor.actions[alias] ? alias : 'idle';
  const sequence = actor.actions[state];
  const durations = actor.action_ms?.[state] ?? sequence.map(index => actor.frames[index].ms);
  const total = durations.reduce((sum, ms) => sum + ms, 0);
  const looping = ['idle', 'move', 'walk', 'run'].includes(state);
  let remaining = looping ? ((Math.max(0, time) * 1000) % total) : clamp(progress) * total;
  let index = sequence.at(-1);
  for (let position = 0; position < sequence.length; position++) {
    if (remaining < durations[position]) { index = sequence[position]; break; }
    remaining -= durations[position];
  }
  const frame = actor.frames[index];
  const scale = height / actor.bodyHeight;
  const direction = face < 0 ? -1 : 1;
  return { actor, frame, index, state, scale, face: direction,
    socket(name) {
      const point = Object.hasOwn(frame.sockets ?? {}, name) ? frame.sockets[name] : null;
      return point ? { x: x + (point[0] - actor.pivot[0]) * scale * direction,
        y: groundY + (point[1] - actor.pivot[1]) * scale } : null;
    } };
}

export function drawActor(ctx, options) {
  const sampled = sampleActorPose(options);
  if (!sampled) return false;
  const { actor, frame, scale, face } = sampled;
  const { x, groundY } = options;
  const entry = sheets.get(options.kind);
  ctx.save();
  ctx.translate(x, groundY);
  ctx.scale(face < 0 ? -scale : scale, scale);
  ctx.drawImage(entry.image, frame.x, frame.y, frame.w, frame.h,
    -actor.pivot[0], -actor.pivot[1], frame.w, frame.h);
  ctx.restore();
  return true;
}
