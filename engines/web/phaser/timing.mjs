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

export function targetContact(actor, point, target) {
  return (target.target_x-actor.x)*actor.facing>0 && Math.abs(point.x-target.target_x)<56 && Math.abs(point.y-target.target_y)<64;
}

export function attackContact(metadata, rules = {}) {
  const attack = metadata.actions.attack;
  const effect = (metadata.events || []).find(e => e.action === 'attack');
  const index = rules.contact_frame ?? attack.contact_frame;
  if (index === undefined && effect) return null;
  return {action:'attack',start_ms:attack.frames.slice(0,index).reduce((n,f)=>n+f.duration_ms,0),
    at_px:rules.at_px ?? attack.at_px ?? effect?.at_px};
}
