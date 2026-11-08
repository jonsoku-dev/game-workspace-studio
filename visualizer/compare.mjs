import { t, formatNumber } from './i18n.mjs';
import { compareMessages } from './compare-messages.mjs';

const tr = (key, values) => t(compareMessages, key, values);
const hasType = (node, type) => [node?.['@type']].flat().includes(type);
const newest = nodes => [...nodes].sort((a, b) => String(b.recordedAt || '').localeCompare(String(a.recordedAt || '')));

// Only graph snapshots are review facts; viewing a scene never changes their status.
export function compareRecords(input) {
  const nodes = Array.isArray(input) ? input : input?.['@graph'] || [];
  return newest(nodes.filter(node => hasType(node, 'ReviewComparison'))).map(node => ({
    node, snapshot: node.snapshot,
    evidence: newest(nodes.filter(item => hasType(item, 'ReviewEvidence') && item.snapshot?.comparison === node['@id'])),
    decisions: newest(nodes.filter(item => hasType(item, 'ReviewDecision') && item.snapshot?.comparison === node['@id'])),
  }));
}

export function activeReviewEvidence(evidence) {
  const superseded = new Set(evidence.flatMap(node => node.snapshot?.supersedes || []));
  return evidence.filter(node => !superseded.has(node['@id']));
}

export function criterionResults(evidence, criterion, run) {
  return activeReviewEvidence(evidence).filter(node => !run || node.snapshot?.run === run).flatMap(node => {
    const result = node.snapshot?.results?.find(item => item.criterion === criterion);
    return result ? [{ ...result, actor: node.snapshot.actor, recordedAt: node.recordedAt,
      resolution_reason: node.snapshot.resolution_reason, supersedes: node.snapshot.supersedes || [] }] : [];
  });
}

export function latestCriterionResult(evidence, criterion, run) {
  return criterionResults(evidence, criterion, run)[0] || null;
}

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
function link(text, href) {
  const node = element('a', '', text);
  let url;
  try { url = new URL(href, location.href); } catch { return element('span', 'muted', text); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return element('span', 'muted', text);
  node.href = url.href;
  node.target = '_blank';
  node.rel = 'noopener noreferrer';
  return node;
}

let records = [], options = {}, selected = null, root, panel, observer, signature = null;
let renderers = [], epoch = 0, animation = 0, elapsed = 0, previous = null, playing = false;
let currentAction = '', clock, output, playButton;
const stop = () => {
  playing = false;
  previous = null;
  cancelAnimationFrame(animation);
  animation = 0;
  if (playButton) { playButton.textContent = tr('play'); playButton.setAttribute('aria-pressed', 'false'); }
};
function disposeScenes() {
  epoch++;
  stop();
  for (const renderer of renderers) renderer.dispose();
  renderers = [];
}
function seek(time) {
  elapsed = Math.max(0, time);
  for (const renderer of renderers) { renderer.setPaused(true); renderer.seek(elapsed); }
  if (clock) {
    clock.max = String(Math.max(10000, Math.ceil(elapsed / 1000) * 1000));
    clock.value = String(elapsed);
  }
  if (output) output.textContent = tr('clockValue', { time: formatNumber(Math.round(elapsed)) });
  if (root) root.dataset.compareTime = String(Math.round(elapsed));
}
function tick(now) {
  if (!playing || document.hidden || panel.hidden) { stop(); return; }
  if (previous !== null) seek(elapsed + now - previous);
  previous = now;
  animation = requestAnimationFrame(tick);
}
function control(text, id, callback) {
  const button = element('button', '', text);
  button.type = 'button'; button.id = id; button.addEventListener('click', callback);
  return button;
}
function renderEvidence(record) {
  const section = element('section', 'compare-evidence');
  section.append(element('h3', '', tr('criteria')));
  const grid = element('div', 'compare-criteria');
  for (const criterion of record.snapshot.criteria || []) {
    const item = element('article', 'compare-criterion');
    item.append(element('span', 'eyebrow', tr(criterion.kind)), element('h4', '', criterion.description),
      element('p', 'muted', `${criterion.id} · ${tr(criterion.required ? 'required' : 'optional')}`));
    for (const side of ['a', 'b']) {
      const results = criterionResults(record.evidence, criterion.id, record.snapshot[side].run);
      if (!results.length) item.append(element('p', 'compare-result pending', `${side.toUpperCase()} · ${tr('pending')}`));
      for (const result of results) {
        item.append(element('p', `compare-result ${result.status}`, `${side.toUpperCase()} · ${tr(result.status)}`));
        item.append(element('p', '', result.reason));
        item.append(element('p', 'muted', [result.actor, result.recordedAt, result.judgement === 'human' ? tr('human') : ''].filter(Boolean).join(' · ')));
        if (result.attestation?.statement) item.append(element('blockquote', '', result.attestation.statement));
        if (result.supersedes.length) item.append(element('p', '', `${tr('resolution')}: ${result.resolution_reason}`));
        for (const [index, file] of (result.evidence || []).entries()) {
          const row = element('p', 'compare-file');
          const label = tr('evidenceLink', { index: formatNumber(index + 1) });
          row.append(options.evidenceURL ? link(label, options.evidenceURL(file)) : element('span', 'muted', label));
          item.append(row);
        }
      }
    }
    grid.append(item);
  }
  section.append(grid, element('p', 'muted compare-note', tr('separation')));
  const latestDecision = record.decisions.find(node => !record.decisions.some(next => next.snapshot.previous === node['@id']));
  const decision = latestDecision?.snapshot;
  const decisionBox = element('section', 'compare-decision');
  decisionBox.append(element('h3', '', tr('decision')));
  if (decision) {
    decisionBox.append(element('p', '', tr(decision.outcome)), element('p', '', decision.reason),
      element('p', 'muted', `${decision.actor} · ${latestDecision.recordedAt || ''} · ${decision.run}`),
      element('p', 'muted', `${tr('activeRun')}: ${decision.active_run || tr('noActiveRun')}`));
  } else decisionBox.append(element('p', 'muted', tr('noDecision')));
  section.append(decisionBox);
  const details = element('details', 'production-details');
  details.append(element('summary', '', tr('details')));
  details.append(element('pre', '', JSON.stringify({ a: record.snapshot.a, b: record.snapshot.b, diff: record.snapshot.diff }, null, 2)));
  const evidenceHistory = element('details', 'production-details');
  evidenceHistory.append(element('summary', '', tr('recordedEvidence')), element('pre', '', JSON.stringify(record.evidence, null, 2)));
  section.append(evidenceHistory);
  section.append(details); root.append(section);
}
async function mountScenes(record, sides, status, actionSelect, tools) {
  const version = epoch;
  try {
    if (typeof options.loadRuntime !== 'function') throw new Error('No runtime resolver');
    const { showScene } = await import('./scene-view.mjs');
    for (const [index, key] of ['a', 'b'].entries()) {
      const pin = record.snapshot[key];
      const loaded = await options.loadRuntime(pin, record.node);
      if (version !== epoch) return;
      if (loaded.playURL) sides[index].links.replaceChildren(link(tr('firsthand', { side: key.toUpperCase() }), loaded.playURL));
      const renderer = await showScene(sides[index].canvas, loaded.runtime, loaded.assetURL);
      if (version !== epoch) { renderer.dispose(); return; }
      renderer.setPaused(true);
      renderers.push(renderer);
    }
    const shared = renderers[0].metrics.inspection.actions.filter(action => renderers[1].metrics.inspection.actions.includes(action));
    for (const action of shared) {
      const option = element('option', '', tr(action)); option.value = action; actionSelect.append(option);
    }
    if (shared.includes(currentAction)) {
      actionSelect.value = currentAction;
      for (const renderer of renderers) renderer.setAction(currentAction);
    } else currentAction = '';
    actionSelect.parentElement.hidden = !shared.length;
    tools.hidden = false;
    status.hidden = true;
    root.dataset.compareState = 'ready';
    seek(elapsed);
  } catch (error) {
    if (version !== epoch) return;
    disposeScenes();
    status.textContent = tr('unavailable');
    root.dataset.compareState = 'error';
  }
}
function render() {
  if (!root || !panel) return;
  disposeScenes();
  document.getElementById('tab-compare').textContent = tr('tab');
  root.replaceChildren();
  if (!records.length) { root.dataset.compareState = 'empty'; root.append(element('p', 'empty-small', tr('empty'))); return; }
  if (!selected || !records.some(record => record.node['@id'] === selected)) selected = records[0].node['@id'];
  const record = records.find(item => item.node['@id'] === selected);
  const header = element('div', 'compare-heading');
  const label = element('label', '', tr('picker'));
  const picker = element('select'); picker.id = 'compare-picker';
  for (const item of records) {
    const option = element('option', '', item.snapshot.id); option.value = item.node['@id']; picker.append(option);
  }
  picker.value = selected;
  picker.addEventListener('change', () => { selected = picker.value; elapsed = 0; currentAction = ''; render(); });
  label.append(picker); header.append(label, element('p', 'muted', tr('help'))); root.append(header);
  const tools = element('div', 'compare-controls'); tools.hidden = true;
  playButton = control(tr('play'), 'compare-play', () => {
    if (playing) stop();
    else { playing = true; previous = null; playButton.textContent = tr('pause'); playButton.setAttribute('aria-pressed', 'true'); animation = requestAnimationFrame(tick); }
  });
  playButton.setAttribute('aria-pressed', 'false');
  tools.append(playButton, control(tr('back'), 'compare-back', () => { stop(); seek(elapsed - 1000 / 60); }),
    control(tr('step'), 'compare-step', () => { stop(); seek(elapsed + 1000 / 60); }));
  const actionLabel = element('label', '', tr('actions'));
  const actionSelect = element('select'); actionSelect.id = 'compare-action';
  const authored = element('option', '', tr('recorded')); authored.value = ''; actionSelect.append(authored);
  actionLabel.append(actionSelect); tools.append(actionLabel);
  actionSelect.addEventListener('change', () => {
    stop(); currentAction = actionSelect.value;
    const changed = renderers.map(renderer => renderer.setAction(currentAction || null));
    if (changed.some(value => !value)) { currentAction = ''; actionSelect.value = ''; for (const renderer of renderers) renderer.setAction(null); }
    seek(0);
  });
  const timeline = element('label', 'compare-timeline', tr('clock'));
  clock = element('input'); clock.id = 'compare-clock'; clock.type = 'range'; clock.min = '0'; clock.max = '10000'; clock.step = '1'; clock.value = String(elapsed);
  clock.addEventListener('input', () => { stop(); seek(Number(clock.value)); });
  output = element('output'); output.htmlFor = clock.id;
  timeline.append(clock, output); tools.append(timeline); root.append(tools);
  const status = element('p', 'notice', tr('loading')); status.setAttribute('role', 'status'); root.append(status);
  const pair = element('div', 'compare-pair');
  const sides = ['a', 'b'].map(key => {
    const card = element('article', 'scene-card compare-side');
    const heading = element('div', 'card-heading');
    heading.append(element('h3', '', key.toUpperCase()), element('span', 'muted', record.snapshot[key].run_id));
    const stage = element('div', 'scene-stage');
    const canvas = element('canvas'); canvas.id = `compare-${key}`; canvas.setAttribute('aria-label', `${key.toUpperCase()} · ${record.snapshot[key].run_id}`);
    // The parent clock owns playback; avoid the scene viewer's independent keyboard controls.
    canvas.addEventListener('keydown', event => { if ([' ', '[', ']'].includes(event.key)) event.stopImmediatePropagation(); });
    stage.append(canvas);
    const links = element('div', 'compare-export'); links.append(element('span', 'muted', tr('noExport')));
    card.append(heading, stage, links); pair.append(card); return { canvas, links };
  });
  root.append(pair); renderEvidence(record);
  root.dataset.compareState = panel.hidden ? 'inactive' : 'loading';
  if (!panel.hidden) void mountScenes(record, sides, status, actionSelect, tools);
}

// loadRuntime(pin, comparisonNode) resolves only the comparison's pinned runtime/files.
// evidenceURL(filePin) supplies a project-scoped URL bound to its recorded path and SHA.
export function updateCompare(data, settings = {}) {
  records = compareRecords(data); options = settings;
  const nextSignature = JSON.stringify(records);
  const changed = signature !== nextSignature;
  signature = nextSignature;
  root = document.getElementById('compare-root'); panel = document.getElementById('panel-compare');
  if (!observer && panel) {
    observer = new MutationObserver(render);
    observer.observe(panel, { attributes: true, attributeFilter: ['hidden'] });
    window.addEventListener('studio:localechange', render);
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', () => {
      stop();
      // Scene viewers also listen to motion preferences; retain the shared clock afterward.
      requestAnimationFrame(() => { for (const renderer of renderers) renderer.setPaused(true); });
    });
  }
  if (changed) render();
}
