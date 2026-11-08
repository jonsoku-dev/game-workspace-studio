// [start Hz, end Hz, seconds, gain, oscillator type, delay seconds]
const tones = {
  move: [[130, 90, .045, .035, 'triangle']],
  step: [[95, 48, .065, .045, 'sine']],
  stop: [[100, 65, .05, .03, 'sine']],
  jump: [[220, 620, .13, .07, 'triangle']],
  land: [[110, 45, .11, .11, 'sine']],
  pickup: [[660, 880, .09, .07, 'sine'], [990, 1320, .12, .06, 'sine', .06]],
  interact: [[330, 440, .09, .06, 'triangle']],
  denied: [[165, 110, .14, .06, 'square']],
  pause: [[440, 220, .12, .05, 'sine']],
  resume: [[220, 440, .12, .05, 'sine']],
  restart: [[220, 330, .08, .05, 'triangle'], [440, 660, .12, .05, 'triangle', .08]],
  attack: [[250, 65, .09, .08, 'triangle']],
  miss: [[360, 120, .13, .045, 'sine']],
  hit: [[105, 38, .13, .16, 'sine'], [850, 220, .035, .065, 'triangle']],
  crit: [[145, 45, .17, .18, 'sine'], [1250, 330, .05, .08, 'triangle']],
  hurt: [[190, 60, .2, .09, 'sawtooth']],
  progress: [[440, 550, .09, .055, 'sine'], [660, 770, .1, .055, 'sine', .07]],
  win: [[523, 523, .16, .06, 'triangle'], [659, 659, .16, .06, 'triangle', .1], [784, 1047, .24, .07, 'triangle', .2]],
  lose: [[330, 247, .18, .055, 'triangle'], [220, 110, .25, .06, 'triangle', .14]],
  finish: [[125, 35, .18, .18, 'sine'], [1100, 240, .045, .075, 'triangle'], [523, 784, .15, .06, 'sine', .06], [1047, 1047, .22, .06, 'sine', .18]],
  menu: [[300, 360, .055, .035, 'sine']],
  select: [[600, 900, .075, .045, 'triangle']],
};

export function createFeedback({onCue, enabled = true, sound = false} = {}) {
  let isEnabled = Boolean(enabled), wantsSound = Boolean(sound), disposed = false;
  let context, noise, unavailable = false, lastMove = -Infinity, lastStep = -Infinity;
  const active = new Set();
  const motion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
  const status = () => disposed ? 'disposed' : !isEnabled ? 'off' : !wantsSound ? 'muted'
    : unavailable ? 'unavailable' : !context ? 'locked' : context.state;

  function cancel() {
    for (const voice of [...active]) voice.cancel();
  }
  function blur() {
    cancel();
    if (context?.state === 'running') void context.suspend().catch(() => {});
  }
  function hide() { if (globalThis.document?.hidden) blur(); }
  globalThis.addEventListener?.('blur', blur);
  globalThis.document?.addEventListener('visibilitychange', hide);

  function voice(source, gain, duration, delay = 0, filter) {
    // Bound overlap even if a host emits a burst of events.
    while (active.size >= 24) active.values().next().value.cancel();
    const start = context.currentTime + delay;
    const output = context.createGain();
    output.gain.setValueAtTime(0, start);
    output.gain.linearRampToValueAtTime(gain, start + .003);
    output.gain.exponentialRampToValueAtTime(.0001, start + duration);
    source.connect(filter || output);
    if (filter) filter.connect(output);
    output.connect(context.destination);
    const item = {cancel() {
      source.onended = null;
      try { source.stop(); } catch { /* Already ended. */ }
      source.disconnect(); output.disconnect(); filter?.disconnect(); active.delete(item);
    }};
    source.onended = () => { source.disconnect(); output.disconnect(); filter?.disconnect(); active.delete(item); };
    active.add(item);
    source.start(start); source.stop(start + duration + .005);
  }

  function play(name, combo) {
    const now = context.currentTime;
    if (name === 'move' && now - lastMove < .09) return 'throttled';
    if (name === 'move') lastMove = now;
    if (name === 'step' && now - lastStep < .14) return 'throttled';
    if (name === 'step') lastStep = now;
    const pitch = combo ? 1 + (combo - 1) * .065 : 1;
    for (const [from, to, seconds, gain, type, delay = 0] of tones[name]) {
      const oscillator = context.createOscillator();
      oscillator.type = type;
      oscillator.frequency.setValueAtTime(from * pitch, now + delay);
      oscillator.frequency.exponentialRampToValueAtTime(to * pitch, now + delay + seconds);
      voice(oscillator, gain, seconds, delay);
    }
    if (name === 'hit' || name === 'crit' || name === 'land' || name === 'finish') {
      if (!noise) {
        noise = context.createBuffer(1, Math.ceil(context.sampleRate * .08), context.sampleRate);
        const data = noise.getChannelData(0);
        let seed = 17;
        for (let i = 0; i < data.length; i++) { seed = (seed * 16807) % 2147483647; data[i] = seed / 1073741823.5 - 1; }
      }
      const source = context.createBufferSource(); source.buffer = noise;
      const filter = context.createBiquadFilter(); filter.type = 'bandpass';
      filter.frequency.value = (name === 'land' ? 280 : 1800) * pitch; filter.Q.value = .7;
      voice(source, name === 'crit' ? .15 : .09, .065, 0, filter);
    }
    return 'scheduled';
  }

  return {
    get enabled() { return isEnabled && !disposed; },
    get sound() { return wantsSound && !disposed; },
    get reducedMotion() { return Boolean(motion?.matches); },
    emit(name, details = {}) {
      const soundName = Object.hasOwn(tones, details.soundAs) ? details.soundAs : name;
      const combo = soundName === 'hit' || soundName === 'crit'
        ? Math.max(1, Math.min(8, Number.isInteger(details.combo) ? details.combo : 1)) : undefined;
      const cue = {name, detail: details, enabled: isEnabled && !disposed, sound: wantsSound && !disposed,
        reducedMotion: Boolean(motion?.matches), audioStatus: status(), ...(combo === undefined ? {} : {combo})};
      if (disposed || !isEnabled) return cue;
      if (wantsSound && !Object.hasOwn(tones, soundName)) cue.audioStatus = 'unmapped';
      else if (wantsSound && context?.state === 'running') {
        try { cue.audioStatus = play(soundName, combo); }
        catch { cancel(); cue.audioStatus = 'unavailable'; }
      }
      onCue?.(cue);
      return cue;
    },
    setEnabled(value) { if (!disposed) { isEnabled = Boolean(value); if (!isEnabled) cancel(); } return status(); },
    // Hosts call this directly inside a trusted click/key/pointer handler. emit never unlocks audio.
    setSound(value) {
      if (disposed) return 'disposed';
      wantsSound = Boolean(value);
      if (!wantsSound) { cancel(); return status(); }
      if (globalThis.navigator?.userActivation?.isActive !== true) return status();
      try {
        const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext;
        if (!AudioContext) { unavailable = true; return status(); }
        context ||= new AudioContext();
        if (context.state === 'suspended') void context.resume().catch(() => {});
      } catch { unavailable = true; }
      return status();
    },
    dispose() {
      if (disposed) return;
      disposed = true; cancel();
      globalThis.removeEventListener?.('blur', blur);
      globalThis.document?.removeEventListener('visibilitychange', hide);
      if (context && context.state !== 'closed') void context.close().catch(() => {});
      noise = null;
    },
  };
}
