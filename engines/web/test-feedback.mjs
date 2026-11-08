import assert from 'node:assert/strict';
import {createFeedback} from './feedback.mjs';

const originals = Object.fromEntries(['AudioContext', 'navigator', 'matchMedia', 'addEventListener', 'removeEventListener', 'document']
  .map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
const set = (key, value) => Object.defineProperty(globalThis, key, {configurable: true, value});
const listeners = new Map(), documentListeners = new Map();
const media = {matches: false}, activation = {isActive: false};
const contexts = [];
class Node {
  constructor() {
    this.frequency = {value: 0, setValueAtTime: value => { this.pitch = value; }, exponentialRampToValueAtTime() {}};
    this.gain = {setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {}};
    this.Q = {};
  }
  connect() {}
  disconnect() { this.disconnected = true; }
  start() { this.started = true; }
  stop() { this.stops = (this.stops || 0) + 1; }
}
class Context {
  constructor() { this.state = 'suspended'; this.currentTime = 0; this.sampleRate = 48000; this.sources = []; contexts.push(this); }
  createOscillator() { const node = new Node(); this.sources.push(node); return node; }
  createBufferSource() { return this.createOscillator(); }
  createGain() { return new Node(); }
  createBiquadFilter() { return new Node(); }
  createBuffer(channels, length) { return {getChannelData: () => new Float32Array(length)}; }
  resume() { this.state = 'running'; return Promise.resolve(); }
  suspend() { this.state = 'suspended'; return Promise.resolve(); }
  close() { this.state = 'closed'; return Promise.resolve(); }
}
try {
  set('navigator', {userActivation: activation});
  set('AudioContext', Context);
  set('matchMedia', () => media);
  set('addEventListener', (key, callback) => listeners.set(key, callback));
  set('removeEventListener', (key, callback) => { if (listeners.get(key) === callback) listeners.delete(key); });
  set('document', {hidden: false, addEventListener: (key, callback) => documentListeners.set(key, callback),
    removeEventListener: (key, callback) => { if (documentListeners.get(key) === callback) documentListeners.delete(key); }});
  const cues = [], feedback = createFeedback({onCue: cue => cues.push(cue)});
  assert.equal(feedback.emit('jump').audioStatus, 'muted');
  assert.equal(feedback.emit('equip').audioStatus, 'muted');
  assert.equal(contexts.length, 0, 'muted dispatcher never constructs audio');
  feedback.setEnabled(false);
  assert.equal(feedback.emit('hit').audioStatus, 'off');
  assert.equal(cues.length, 2);
  feedback.setEnabled(true);
  assert.equal(feedback.setSound(true), 'locked');
  assert.equal(contexts.length, 0, 'programmatic opt-in cannot unlock audio');
  activation.isActive = true;
  assert.equal(feedback.setSound(true), 'running');
  activation.isActive = false;
  const context = contexts[0];
  const first = feedback.emit('hit', {combo: 1});
  assert.equal(first.audioStatus, 'scheduled');
  assert.equal(context.sources.length, 3, 'impact layers bass, transient and filtered crunch');
  const lowPitch = context.sources[0].pitch;
  assert.equal(feedback.emit('hit', {combo: 999}).combo, 8);
  assert.ok(context.sources[3].pitch > lowPitch);
  assert.ok(context.sources[3].pitch < lowPitch * 1.5);
  assert.equal(feedback.emit('hit', {combo: NaN}).combo, 1);
  assert.equal(context.sources[6].pitch, lowPitch, 'unverified combo cannot advance pitch');
  assert.equal(feedback.emit('craft').audioStatus, 'unmapped');
  assert.equal(cues.at(-1).name, 'craft', 'custom semantics still reach the renderer');
  assert.equal(feedback.emit('dialogue', {soundAs: 'toString'}).audioStatus, 'unmapped');
  assert.equal(feedback.emit('equip', {soundAs: 'select'}).audioStatus, 'scheduled');
  feedback.setSound(false);
  assert.ok(context.sources.every(node => node.disconnected && node.stops === 2), 'mute cancels even queued sound');
  const count = context.sources.length;
  feedback.emit('win');
  assert.equal(context.sources.length, count);
  activation.isActive = true; feedback.setSound(true); activation.isActive = false;
  assert.equal(feedback.emit('move').audioStatus, 'scheduled');
  assert.equal(feedback.emit('move').audioStatus, 'throttled');
  assert.equal(feedback.emit('step').audioStatus, 'scheduled');
  assert.equal(feedback.emit('step').audioStatus, 'throttled');
  context.currentTime = .139;
  assert.equal(feedback.emit('step').audioStatus, 'throttled');
  context.currentTime = .141;
  assert.equal(feedback.emit('step').audioStatus, 'scheduled');
  feedback.setSound(false);
  assert.equal(feedback.emit('step').audioStatus, 'muted');
  activation.isActive = true; feedback.setSound(true); activation.isActive = false;
  const beforeFinish = context.sources.length;
  assert.equal(feedback.emit('finish').audioStatus, 'scheduled');
  assert.equal(context.sources.length - beforeFinish, 5, 'finish combines impact layers with fanfare');
  for (let i = 0; i < 30; i++) feedback.emit('crit');
  assert.ok(context.sources.filter(node => !node.disconnected).length <= 24, 'overlap is bounded');
  listeners.get('blur')();
  assert.equal(context.state, 'suspended');
  assert.equal(feedback.emit('hit').audioStatus, 'suspended');
  feedback.setSound(true);
  assert.equal(context.state, 'suspended', 'only a fresh gesture can resume');
  activation.isActive = true; feedback.setSound(true); activation.isActive = false;
  media.matches = true;
  assert.equal(feedback.reducedMotion, true);
  assert.equal(feedback.emit('select').reducedMotion, true);
  feedback.setEnabled(false);
  assert.ok(context.sources.every(node => node.disconnected));
  feedback.dispose(); feedback.dispose();
  assert.equal(context.state, 'closed');
  assert.equal(feedback.enabled, false);
  assert.equal(feedback.sound, false);
  assert.equal(feedback.emit('win').audioStatus, 'disposed');
  assert.equal(listeners.size + documentListeners.size, 0);

  set('AudioContext', undefined);
  const fallback = createFeedback({sound: true, onCue: cue => cues.push(cue)});
  activation.isActive = true;
  assert.equal(fallback.setSound(true), 'unavailable');
  assert.equal(fallback.emit('pickup').audioStatus, 'unavailable');
  assert.equal(cues.at(-1).name, 'pickup', 'unavailable audio preserves visual feedback');
  fallback.dispose();
  console.log('Feedback gating, trusted unlock, impact layers, bounded combo/overlap, mute, focus, reduced motion and disposal passed.');
} finally {
  for (const [key, descriptor] of Object.entries(originals)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
}
