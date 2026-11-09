import manifest from './fx/manifest.mjs';
import {MOTIF_MS} from './motif-ms.mjs';

export const DEFAULT_JOBS = {
  blade: { name: '검사', skill: '초승달 베기', motif: 'blade' },
  brawler: { name: '격투가', skill: '지진권', motif: 'brawler' },
  astral: { name: '성술사', skill: '별무리 낙하', motif: 'astral' },
  rail: { name: '사수', skill: '플라스마 창', motif: 'rail' },
};

const MOTIFS = {
  blade: { sheet: 'sword', color: '#74eedb', ink: '#225c88', light: 'sword-cut', heavy: 'sword-cleave' },
  brawler: { sheet: 'fist', color: '#ffc270', ink: '#a83c68', light: 'fist-rise', heavy: 'fist-quake' },
  astral: { sheet: 'star', color: '#dbacff', ink: '#5351a8', light: 'star-volley', heavy: 'star-rain' },
  rail: { sheet: 'gun', color: '#80dfff', ink: '#4265b5', light: 'gun-flash', heavy: 'gun-plasma' },
};
const REACTIONS = { parry: [.28, '#e6fbff'], evade: [.30, '#83e8e0'], hurt: [.24, '#ff859c'], enemyImpact: [.32, '#ffc987'], exposed: [.70, '#ffe59a'], win: [1.35, '#dcbdff'] };
const clamp = value => Math.max(0, Math.min(1, value));
const mix = (a, b, t) => a + (b - a) * t;

// dt is seconds; the game owns damage, hit-stop and camera motion.
export function createCombatFX({ jobs = DEFAULT_JOBS, reducedMotion = false } = {}) {
  const images = new Map();
  let active = [];
  let reactions = [];
  function load(path) {
    const url = new URL(path, import.meta.url).href;
    if (images.has(url)) return images.get(url).ready;
    const image = new Image();
    const entry = { image, loaded: false };
    entry.ready = new Promise((resolve, reject) => {
      image.onload = () => { entry.loaded = true; resolve(image); };
      image.onerror = () => reject(new Error(`Combat FX image failed to load: ${url}`));
    });
    images.set(url, entry);
    image.src = url;
    return entry.ready;
  }
  const sheets = new Map();
  const impacts = new Map();
  const clips = new Map();
  const pending = [];
  for (const [key, job] of Object.entries(jobs)) {
    const style = MOTIFS[job.motif ?? key];
    if (!style) throw new RangeError(`Unknown combat motif for job ${key}`);
    const path = job.sheet || `./fx/${style.sheet}.webp`;
    sheets.set(key, path);
    pending.push(load(path).then(image => {
      if (image.naturalWidth < 3 || image.naturalHeight < 2 || image.naturalWidth % 3 || image.naturalHeight % 2) {
        throw new Error(`Combat painted sheet must contain a 3×2 grid of equal cells: ${path}`);
      }
    }));
    const impact = job.impact ?? { ...manifest.impact, image: `./${manifest.impact.image}` };
    if (!impact.frames?.length || !Array.isArray(impact.pivot) || impact.pivot.length !== 2 || !impact.pivot.every(Number.isFinite) || impact.frames.some(frame => ![frame.x, frame.y, frame.w, frame.h, frame.ms].every(Number.isFinite) || frame.x < 0 || frame.y < 0 || frame.w <= 0 || frame.h <= 0 || frame.ms <= 0)) {
      throw new TypeError(`Invalid combat impact for job ${key}`);
    }
    impacts.set(key, impact);
    pending.push(load(impact.image).then(image => {
      if (impact.frames.some(frame => frame.x + frame.w > image.naturalWidth || frame.y + frame.h > image.naturalHeight)) {
        throw new Error(`Combat impact frames exceed image bounds: ${impact.image}`);
      }
    }));
    if (job.clip) {
      const clip = job.clip;
      const phases = ['charge', 'travel', 'impact'];
      if (typeof clip.image !== 'string' || !Array.isArray(clip.pivot) || clip.pivot.length !== 2 || !clip.pivot.every(Number.isFinite) || phases.some(phase => !Array.isArray(clip.phases?.[phase]) || !clip.phases[phase].length || clip.phases[phase].some(frame => ![frame.x, frame.y, frame.w, frame.h, frame.ms].every(Number.isFinite) || frame.x < 0 || frame.y < 0 || frame.w <= 0 || frame.h <= 0 || frame.ms <= 0))) {
        throw new TypeError(`Invalid combat phase clip for job ${key}`);
      }
      const frames = phases.flatMap(phase => clip.phases[phase]);
      const timing = phases.map(phase => clip.phases[phase].reduce((sum, frame) => sum + frame.ms, 0) / 1000);
      if (!timing.every(Number.isFinite)) throw new TypeError(`Invalid combat phase duration for job ${key}`);
      clips.set(key, { ...clip, timing, width: Math.max(...frames.map(frame => frame.w)) });
      pending.push(load(clip.image).then(image => {
        if (frames.some(frame => frame.x + frame.w > image.naturalWidth || frame.y + frame.h > image.naturalHeight)) {
          throw new Error(`Combat clip frames exceed image bounds: ${clip.image}`);
        }
      }));
    }
    for (const id of [style.light, style.heavy]) {
      if (!manifest[id]) throw new Error(`Missing combat FX manifest entry: ${id}`);
      pending.push(load(`./${manifest[id].image}`));
    }
  }
  for (const id of ['storm', 'star-seal', 'detonation', 'sword-wheel', 'fist-quake', 'land', 'impact']) pending.push(load(`./${manifest[id].image}`));
  const ready = Promise.all(pending);
  // Keep an early load failure observable through ready without an unhandled rejection.
  ready.catch(() => {});
  function cast(jobKey, { x, y, targetX, targetY, face = 1, heavy = true }) {
    const job = jobs[jobKey];
    if (!job) throw new RangeError(`Unknown combat job: ${jobKey}`);
    if (![x, y, targetX, targetY, face].every(Number.isFinite)) throw new TypeError('Combat FX coordinates and face must be finite');
    const motif = job.motif ?? jobKey;
    const style = MOTIFS[motif];
    const [baseWindup,baseFlight,baseDecay]=MOTIF_MS[motif][heavy?'heavy':'light'].map(ms=>ms/1000);
    const [windup, flight, decay] = heavy && clips.has(jobKey) ? clips.get(jobKey).timing : [baseWindup, baseFlight, baseDecay];
    const descriptor = Object.freeze({ jobKey, motif, x, y, targetX, targetY, face: face < 0 ? -1 : 1, heavy: !!heavy, windup, flight, decay, contactTime: windup + flight });
    active.push({ descriptor, time: 0, contacted: false, hit: false, hitX: targetX, hitY: targetY });
    return descriptor;
  }
  function react(event, { x, y, face = 1 }) {
    if (!REACTIONS[event]) throw new RangeError(`Unknown combat reaction: ${event}`);
    if (![x, y, face].every(Number.isFinite)) throw new TypeError('Combat reaction coordinates must be finite');
    reactions.push({ event, x, y, face: face < 0 ? -1 : 1, time: 0 });
  }
  function step(dt, onContact) {
    if (!Number.isFinite(dt) || dt < 0) throw new TypeError('Combat FX dt must be finite and nonnegative');
    for (const reaction of reactions) reaction.time += dt;
    reactions = reactions.filter(reaction => reaction.time < REACTIONS[reaction.event][0]);
    // Snapshot prevents a callback casting another move from advancing it in this step.
    for (const effect of [...active]) {
      effect.time += dt;
      const d = effect.descriptor;
      if (!effect.contacted && effect.time >= d.contactTime) {
        effect.contacted = true;
        const result = onContact?.(d);
        effect.hit = result === true || result?.hit === true;
        if (effect.hit && Number.isFinite(result?.x) && Number.isFinite(result?.y)) {
          effect.hitX = result.x; effect.hitY = result.y;
        }
      }
    }
    active = active.filter(effect => effect.time < effect.descriptor.contactTime + effect.descriptor.decay);
  }
  function imageAt(path) { return images.get(new URL(path, import.meta.url).href); }
  function painted(ctx, key, frame, x, y, width, height, face, alpha) {
    const entry = imageAt(sheets.get(key));
    if (!entry?.loaded) return;
    const image = entry.image, w = image.naturalWidth / 3, h = image.naturalHeight / 2;
    ctx.save();
    ctx.globalAlpha *= alpha;
    ctx.translate(x, y); ctx.scale(face, 1);
    ctx.drawImage(image, frame % 3 * w, Math.floor(frame / 3) * h, w, h, -width / 2, -height / 2, width, height);
    ctx.restore();
  }
  function pixel(ctx, spec, progress, x, y, face, scale, alpha) {
    const entry = imageAt(spec.image.startsWith('fx/') ? `./${spec.image}` : spec.image);
    if (!entry?.loaded) return;
    const duration = spec.frames.reduce((sum, frame) => sum + frame.ms, 0);
    let elapsed = progress * duration, frame = spec.frames.at(-1);
    for (const candidate of spec.frames) {
      elapsed -= candidate.ms;
      if (elapsed < 0) { frame = candidate; break; }
    }
    ctx.save(); ctx.translate(x, y); ctx.scale(face * scale, scale);
    ctx.globalAlpha *= alpha;
    ctx.drawImage(entry.image, frame.x, frame.y, frame.w, frame.h, -spec.pivot[0], -spec.pivot[1], frame.w, frame.h);
    ctx.restore();
  }
  function stroke(ctx, color, width, points) {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(points[0], points[1]);
    if (points.length === 8) ctx.bezierCurveTo(...points.slice(2));
    else ctx.lineTo(points[2], points[3]);
    ctx.stroke();
  }
  function drawClip(ctx, effect, clip) {
    const d = effect.descriptor, t = effect.time;
    const phase = t < d.windup ? 'charge' : t < d.contactTime ? 'travel' : 'impact';
    if (phase === 'impact' && !effect.hit) return;
    const elapsed = phase === 'charge' ? t : phase === 'travel' ? t - d.windup : t - d.contactTime;
    const duration = phase === 'charge' ? d.windup : phase === 'travel' ? d.flight : d.decay;
    const progress = clamp(elapsed / duration);
    let x = phase === 'impact' ? effect.hitX : d.x, y = phase === 'impact' ? effect.hitY : d.y;
    if (phase === 'travel') {
      x = mix(d.x, d.targetX, progress); y = mix(d.y, d.targetY, progress);
      if (!reducedMotion && d.motif === 'blade') y -= Math.sin(progress * Math.PI) * 52;
      if (!reducedMotion && d.motif === 'brawler') y += Math.sin(progress * Math.PI) * 22;
      if (!reducedMotion && d.motif === 'astral') {
        const summon = clamp(progress / .32), fall = clamp((progress - .32) / .68);
        x = mix(d.x, d.targetX, summon); y = mix(d.y - 60, d.targetY - 230, summon) + fall * fall * 230;
      }
      if (reducedMotion) { x = d.targetX; y = d.targetY; }
    }
    const frames = clip.phases[phase];
    const selected = reducedMotion ? [frames[Math.floor(frames.length / 2)]] : frames;
    const alpha = reducedMotion ? .5 : phase === 'impact' ? 1 - progress * .65 : .95;
    const width = reducedMotion ? 105 : phase === 'charge' ? 190 : phase === 'travel' ? 270 : 420;
    pixel(ctx, { image: clip.image, pivot: clip.pivot, frames: selected }, progress, x, y, d.face, width / clip.width, alpha);
    if (phase === 'impact' && !reducedMotion) {
      painted(ctx, d.jobKey, Math.min(5, 2 + Math.floor(progress * 4)), x, y, 400, 370, d.face, (1 - progress) * .3);
    }
  }
  function draw(ctx) {
    ctx.save();
    for (const effect of active) {
      const d = effect.descriptor, style = MOTIFS[d.motif], t = effect.time;
      const clip = d.heavy && clips.get(d.jobKey);
      if (clip) { drawClip(ctx, effect, clip); continue; }
      const power = d.heavy ? 1 : .57;
      const charge = clamp(t / d.windup);
      const travel = clamp((t - d.windup) / d.flight);
      const after = (t - d.contactTime) / d.decay;
      const flightX = mix(d.x, d.targetX, travel), flightY = mix(d.y, d.targetY, travel);
      const angle = Math.atan2(d.targetY - d.y, d.targetX - d.x);
      ctx.save();
      if (t < d.windup) {
        ctx.globalAlpha = reducedMotion ? .30 : .18 + charge * .38;
        ctx.strokeStyle = style.color; ctx.lineWidth = 1.5;
        // An aim mark remains visible without tracking a moving target.
        ctx.beginPath(); ctx.ellipse(d.targetX, d.targetY + 24, 15 + power * 8, 5, 0, 0, Math.PI * 2); ctx.stroke();
        painted(ctx, d.jobKey, 0, d.x, d.y, (90 + charge * 110) * power, (90 + charge * 110) * power, d.face, reducedMotion ? .25 : .45 + charge * .45);
        if (!reducedMotion && d.motif === 'astral') pixel(ctx, manifest['star-seal'], charge * .35, d.targetX, d.targetY + 34, d.face, .80 * power, charge * .75);
        if (!reducedMotion && d.motif === 'brawler') pixel(ctx, manifest.land, charge * .7, d.x, d.y + 34, d.face, 1.8 * power, charge * .6);
        ctx.translate(d.x, d.y);
        if (!reducedMotion) ctx.rotate((1 - charge) * -.4 * d.face);
        ctx.beginPath(); ctx.arc(0, 0, 12 + charge * 13 * power, -.8, Math.PI * 1.2); ctx.stroke();
        if (d.motif === 'astral') {
          ctx.rotate(Math.PI / 4); ctx.strokeRect(-13, -13, 26, 26);
        } else if (d.motif === 'rail') {
          stroke(ctx, style.color, 2, [0, -6, d.face * 32 * charge, -6]);
        }
      } else if (t < d.contactTime) {
        ctx.globalAlpha = reducedMotion ? .36 : .85;
        if (reducedMotion) {
          stroke(ctx, style.color, 2, [d.x, d.y, d.targetX, d.targetY]);
        } else {
          const frame = 1;
          if (d.motif === 'blade') {
            const lift = -Math.sin(travel * Math.PI) * 52 * power;
            for (let i = 0; i < 3; i++) {
              const back = Math.max(0, travel - .13 * i);
              painted(ctx, d.jobKey, frame, mix(d.x, d.targetX, back), mix(d.y, d.targetY, back) + lift, (260 - i * 36) * power, (250 - i * 32) * power, d.face, .9 - i * .24);
            }
            ctx.translate(flightX, flightY + lift); ctx.rotate(-.8 * d.face + travel * 1.4 * d.face);
            ctx.strokeStyle = '#e8fff2'; ctx.lineWidth = 4 * power;
            ctx.beginPath(); ctx.ellipse(0, 0, 36 * power, 104 * power, 0, -1.5, 1.5); ctx.stroke();
          } else if (d.motif === 'brawler') {
            const groundY = mix(d.y, d.targetY, travel) + 34;
            pixel(ctx, manifest['fist-quake'], travel * .45, flightX, groundY, d.face, 1.25 * power, .85);
            painted(ctx, d.jobKey, frame, flightX, groundY - 30 - Math.sin(travel * Math.PI) * 22, 255 * power, 235 * power, d.face, .9);
            for (let i = 0; i < 4; i++) {
              const bx = mix(d.x, flightX, i / 4);
              stroke(ctx, style.color, (5 - i) * power, [bx - d.face * 22, groundY, bx, groundY - 12 - i * 6]);
            }
          } else if (d.motif === 'astral') {
            const summon = clamp(travel / .32), fall = clamp((travel - .32) / .68);
            const ax = mix(d.x, d.targetX, summon), ay = mix(d.y - 60, d.targetY - 230, summon) + fall * fall * 230;
            pixel(ctx, manifest['star-seal'], .35 + travel * .35, d.targetX, d.targetY + 34, d.face, 1.1 * power, .65);
            for (let i = 2; i >= 0; i--) painted(ctx, d.jobKey, frame, ax - d.face * i * 15 * (1 - summon), ay - i * 34 * fall, (210 - i * 25) * power, (210 - i * 25) * power, d.face, .9 - i * .25);
            stroke(ctx, '#f5dcff', 3 * power, [ax, ay - 65 * fall, ax, ay]);
          } else {
            const endX = mix(d.x, d.targetX, travel), endY = mix(d.y, d.targetY, travel);
            ctx.save(); ctx.translate(d.x, d.y); ctx.rotate(angle);
            const length = Math.hypot(endX - d.x, endY - d.y);
            for (const [width, color] of [[24, style.ink], [12, style.color], [3, '#ecfdff']]) stroke(ctx, color, width * power, [0, 0, length, 0]);
            ctx.restore();
            painted(ctx, d.jobKey, frame, endX, endY, 260 * power, 180 * power, d.face, .9);
            pixel(ctx, manifest['gun-flash'], travel * .4, d.x, d.y, d.face, .8 * power, .8);
          }
        }
      } else if (effect.hit) {
        const fade = 1 - clamp(after);
        const x = effect.hitX, y = effect.hitY;
        if (reducedMotion) {
          ctx.globalAlpha = fade * .6;
          stroke(ctx, style.color, 3, [x - 9, y - 9, x + 9, y + 9]);
          stroke(ctx, style.color, 3, [x + 9, y - 9, x - 9, y + 9]);
          painted(ctx, d.jobKey, 4, x, y, 75 * power, 65 * power, d.face, .35);
        } else {
          // Painted body, authored pixel silhouette and fine ink wisps have separate decay.
          painted(ctx, d.jobKey, Math.min(5, 2 + Math.floor(after * 4)), x, y, ({ blade: 425, brawler: 400, astral: 470, rail: 390 }[d.motif]) * power, ({ blade: 380, brawler: 420, astral: 450, rail: 340 }[d.motif]) * power, d.face, fade * .82);
          pixel(ctx, manifest[d.heavy ? style.heavy : style.light], clamp(after), x, y, d.face, power * 1.25, fade * .85);
          pixel(ctx, impacts.get(d.jobKey), clamp(after * 1.6), x, y, d.face, power * .95, fade);
          if (d.heavy) {
            if (d.motif === 'blade' && after > .12) pixel(ctx, manifest['sword-wheel'], clamp((after - .12) / .88), x, y + 24, d.face, 1.5, fade * .65);
            if (d.motif === 'brawler') pixel(ctx, manifest['fist-quake'], clamp(after * 1.15), x, y + 34, d.face, 1.8, fade * .85);
            if (d.motif === 'astral') {
              pixel(ctx, manifest['star-seal'], .65 + after * .35, x, y + 34, d.face, 1.5, fade * .8);
              if (after > .08) pixel(ctx, manifest.storm, clamp((after - .08) / .92), x, y + 34, d.face, 1.25, fade * .9);
            }
            if (d.motif === 'rail' && after > .14) pixel(ctx, manifest.detonation, clamp((after - .14) / .86), x, y + 32, d.face, 1.2, fade * .75);
          }
          ctx.globalAlpha = fade * fade * .7;
          for (let i = 0; i < 9; i++) {
            const a = i * 2.399 + angle, radius = (25 + after * 135) * power;
            const ex = x + Math.cos(a) * radius, ey = y + Math.sin(a) * radius * .68;
            stroke(ctx, i % 3 ? style.color : style.ink, (i % 3 ? 1.5 : 4) * power,
              [x + Math.cos(a) * radius * .55, y + Math.sin(a) * radius * .35, ex, ey]);
          }
          if (after < .17) {
            ctx.globalAlpha = (1 - after / .17) * .9;
            stroke(ctx, '#fff8e6', 3, [x - 12 * power, y + 15 * power, x + 12 * power, y - 15 * power]);
          }
        }
      }
      ctx.restore();
    }
    for (const reaction of reactions) {
      const { event, x, y, face, time } = reaction;
      const [duration, color] = REACTIONS[event], p = time / duration, fade = 1 - p;
      ctx.save(); ctx.globalAlpha = fade * (reducedMotion ? .5 : .9);
      if (reducedMotion) {
        stroke(ctx, color, 2, [x - 12, y, x + 12, y]);
      } else if (event === 'parry') {
        pixel(ctx, manifest.impact, clamp(p * 1.6), x, y, face, 1.65, fade);
        ctx.strokeStyle = color; ctx.lineWidth = 4 * fade;
        ctx.beginPath(); ctx.ellipse(x, y, 14 + p * 24, 45 + p * 20, -.4 * face, -1.5, 1.5); ctx.stroke();
      } else if (event === 'evade') {
        for (let i = 0; i < 4; i++) stroke(ctx, color, 2, [x - face * (15 + p * 55 + i * 8), y - 20 + i * 12, x - face * (40 + p * 70 + i * 8), y - 14 + i * 12]);
        pixel(ctx, manifest.land, p, x, y + 34, face, 1.4, fade * .6);
      } else if (event === 'hurt' || event === 'enemyImpact') {
        pixel(ctx, manifest.impact, p, x, y, face, event === 'hurt' ? 1 : 1.6, fade);
        for (let i = 0; i < 5; i++) {
          const a = i * 1.25, r = 12 + p * 45;
          stroke(ctx, color, 2, [x + Math.cos(a) * r * .5, y + Math.sin(a) * r * .5, x + Math.cos(a) * r, y + Math.sin(a) * r]);
        }
      } else if (event === 'exposed') {
        for (const side of [-1, 1]) {
          const offset = 18 + p * 18;
          stroke(ctx, color, 3, [x + side * offset, y - 17, x + side * (offset + 9), y]);
          stroke(ctx, color, 3, [x + side * (offset + 9), y, x + side * offset, y + 17]);
        }
      } else if (event === 'win') {
        pixel(ctx, manifest['star-seal'], p, x, y + 34, face, 1.5, fade * .75);
        for (let i = 0; i < 14; i++) {
          const a = i * 2.399, r = 20 + p * 170;
          const sx = x + Math.cos(a) * r, sy = y + Math.sin(a) * r * .5 - p * 80;
          stroke(ctx, i % 2 ? '#ffe2a8' : color, 3, [sx, sy - 4, sx, sy + 4]);
        }
      }
      ctx.restore();
    }
    ctx.restore();
  }
  return { ready, cast, react, step, draw, setReducedMotion(value) { reducedMotion = !!value; }, reset() { active = []; reactions = []; } };
}
