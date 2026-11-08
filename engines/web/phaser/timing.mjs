export function frameAt(frames, elapsed, loop = false) {
  const duration = frames.reduce((sum, f) => sum + f.duration_ms, 0);
  let t = loop ? elapsed % duration : Math.min(elapsed, duration - 0.0001);
  for (let i = 0; i < frames.length; i++) {
    if (t < frames[i].duration_ms) return i;
    t -= frames[i].duration_ms;
  }
  return frames.length - 1;
}

export function eventPosition(actor, pivot, event) {
  return {
    x: actor.x + (event.at_px[0] - pivot[0]) * actor.scale * actor.facing,
    y: actor.y + (event.at_px[1] - pivot[1]) * actor.scale,
  };
}
