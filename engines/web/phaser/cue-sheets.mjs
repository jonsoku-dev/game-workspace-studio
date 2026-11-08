export function effectPlayback(metadata, frames = metadata.frames) {
  return {
    duration: frames.reduce((sum, frame) => sum + frame.duration_ms, 0),
    reducedFrame: Number.isInteger(metadata.reduced_motion_frame)
      ? Math.max(0, Math.min(frames.length - 1, metadata.reduced_motion_frame))
      : Math.floor((frames.length - 1) / 2),
  };
}

export function loadCueSheets(scene, effects = {}) {
  for (const [name, effect] of Object.entries(effects)) {
    scene.load.image(`cue-${name}`, effect.sheet);
  }
}

export function prepareCueSheets(scene, effects = {}) {
  return Object.fromEntries(
    Object.entries(effects).map(([name, effect]) => {
      const metadata = effect.metadata;
      const size = Array.isArray(metadata.size)
        ? metadata.size
        : [metadata.size, metadata.size];
      const frames =
        metadata.frames ||
        Array.from({ length: metadata.frame_count }, (_, index) => ({
          rect: { x: index * size[0], y: 0, w: size[0], h: size[1] },
          duration_ms: metadata.duration_ms / metadata.frame_count,
        }));
      frames.forEach(({ rect }, index) => {
        scene.textures
          .get(`cue-${name}`)
          .add(String(index), 0, rect.x, rect.y, rect.w, rect.h);
      });
      return [name, { metadata, frames, ...effectPlayback(metadata, frames) }];
    }),
  );
}

export function spawnCueSheet(
  scene,
  bindings,
  name,
  { x, y, facing = 1, reducedMotion = false, scale = 2 },
) {
  const binding = bindings[name];
  if (!binding) return null;
  const cue = {
    ...binding,
    object: scene.add
      .image(x, y, `cue-${name}`, "0")
      .setScale(scale)
      .setFlipX(facing < 0)
      .setDepth(10),
    facing,
    elapsed: 0,
  };
  setSheetFrame(cue, reducedMotion ? cue.reducedFrame : 0);
  return cue;
}

export function advanceCueSheet(cue, delta, reducedMotion) {
  cue.elapsed += delta;
  if (cue.elapsed >= cue.duration) {
    cue.object.destroy();
    return false;
  }
  let elapsed = cue.elapsed;
  let index = 0;
  if (reducedMotion) index = cue.reducedFrame;
  else {
    while (
      index < cue.frames.length - 1 &&
      elapsed >= cue.frames[index].duration_ms
    ) {
      elapsed -= cue.frames[index].duration_ms;
      index++;
    }
  }
  setSheetFrame(cue, index);
  return true;
}

function setSheetFrame(cue, index) {
  const rect = cue.frames[index].rect;
  const pivot = cue.metadata.effect_anchor_px ||
    cue.metadata.pivot_px_from_top_left || [rect.w / 2, rect.h];
  cue.object
    .setFrame(String(index))
    .setOrigin(
      cue.facing < 0 ? 1 - pivot[0] / rect.w : pivot[0] / rect.w,
      pivot[1] / rect.h,
    );
}
