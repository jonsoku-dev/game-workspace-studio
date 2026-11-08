import {updateCompare} from './compare.mjs';
import './shell-i18n.mjs';
import {t, localeTag, formatNumber, localizedUrl} from './i18n.mjs';
import {appMessages} from './app-messages.mjs';
import {renderErrorText, inspectionLabel} from './view-messages.mjs';

const tr = (key, vars) => t(appMessages, key, vars);
const translatedValue = key => Object.hasOwn(appMessages, key) ? tr(key) : key;
const num = value => formatNumber(value);
const resolve = value => typeof value === 'function' ? value() : value;
const bindings = new WeakMap();
function bindText(element, value, attribute = 'textContent') {
  if (typeof value === 'function') {
    if (!bindings.has(element)) bindings.set(element, new Map());
    bindings.get(element).set(attribute, value);
  } else {
    bindings.get(element)?.delete(attribute);
  }
  const text = String(resolve(value) ?? '');
  if (attribute === 'textContent') element.textContent = text;
  else element.setAttribute(attribute, text);
}
function lookup(names, key) {
  return Object.hasOwn(names, key) ? tr(names[key]) : undefined;
}
function uiError(key, vars) {
  const error = new Error(tr(key, vars));
  error.uiMessage = {key, vars};
  return error;
}
function errorText(error) {
  return error.uiMessage ? tr(error.uiMessage.key, error.uiMessage.vars) : renderErrorText(error);
}
const actionKeys = {idle:'대기', walk:'걷기', run:'달리기', attack:'공격', jump:'점프', hurt:'피격', death:'쓰러짐'};
const actionName = action => lookup(actionKeys, action) || action;
const roleName = role => {
  const effect = /^effect_(\d+)_(sheet|metadata|license|notice)$/.exec(role);
  if (effect) return tr('효과 파일', {index:num(Number(effect[1]) + 1), role:roleName(effect[2])});
  const names = {effect:'이펙트 레시피',preview:'미리보기',review:'검토 이미지',atlas:'아틀라스',sheet:'스프라이트 시트',metadata:'메타데이터',model:'3D 모델',source:'원본 파일',receipt:'컴파일 기록',validation:'검사',blend:'Blender 원본',raw:'원본 파일',credits:'크레딧',license:'라이선스',notice:'고지'};
  return Object.hasOwn(names, role) ? tr(names[role]) : role;
};
const statusName = status => lookup(labels, status) || status;

const $ = id => document.getElementById(id);
const selectedProject = new URLSearchParams(location.search).get('project');
const scopedURL = path => selectedProject ? `${path}${path.includes('?') ? '&' : '?'}project=${encodeURIComponent(selectedProject)}` : path;
const state = {runs: [], nodes: [], project: '', run: null, node: null, renderer: null, epoch: 0, signature: '', previews: new Map(), detailVersion: 0, proofTimer: null, etag: '', refreshing: false};
const types = node => (Array.isArray(node?.['@type']) ? node['@type'] : [node?.['@type']]).filter(Boolean);
const kind = node => types(node).find(value => !['Entity', 'Activity', 'Agent'].includes(value)) || 'Entity';
const labels = {ready:'완료', error:'실패', running:'제작 중', pending:'대기', complete:'완료', reused:'재사용'};
const relations = {used:'입력으로 사용', wasGeneratedBy:'만든 작업', wasDerivedFrom:'유래한 입력', wasAssociatedWith:'제작 도구', dependsOn:'선행 의존 대상', attachedTo:'부착 대상', observed:'관측한 대상', failedWith:'발생한 오류', revisionOf:'상태 기록의 원본', partOf:'소속', placementOf:'배치한 에셋', includesProject:'등록 프로젝트'};
const kindNames = {Run:'실행', RunRevision:'상태 기록', RuntimeProduct:'런타임 장면', SceneRevision:'씬 입력', UnadmittedInput:'거절된 입력', Artifact:'산출물', SourceArtifact:'원본 파일', RequestRevision:'제작 요청', ExecutedRequest:'실행 요청', WorkStep:'제작 단계', Plugin:'제작 도구', Validation:'검사', ValidationEvidence:'검사 근거', ScenePlacement:'씬 배치', Error:'오류', ExternalWork:'외부 작업', Project:'프로젝트', Game:'게임', Workspace:'워크스페이스', Entity:'항목', Agent:'제작 도구', Activity:'외부 작업', MotionRecipe:'3D 이펙트 레시피'};
const make = (tag, className, value) => { const el = document.createElement(tag); if (className) el.className = className; if (value != null) bindText(el, value); return el; };
function generatedLabel(node) {
  if (kind(node) === 'WorkStep' && node.evidenceBasis === 'producer-report') {
    if (node.label === 'Blender source/export') return tr('Blender 소스·내보내기');
    if (node.label === 'Webstage compilation') return tr('Webstage 컴파일');
  }
  if (kind(node) === 'Validation' && node.evidenceBasis === 'producer-report' && node.label === 'Three.js model inspection') return tr('Three.js 모델 검사');
  return node.label;
}
const title = node => generatedLabel(node) || node.snapshot?.brief?.title || node.path?.split('/').pop() || node.record?.scene_id || node.snapshot?.id || (kind(node) === 'Error' ? node.snapshot?.code : '') || `${lookup(kindNames, kind(node)) || kind(node)} · ${node['@id'].split(':').slice(-1)[0].slice(0, 18)}`;
const badge = status => make('span', `badge ${['ready','error','running','pending','complete','reused'].includes(status) ? status : ''}`,() => (lookup(labels, status) || status || tr('기록')));
function time(value) { if (!value) return tr('시간 정보 없음'); const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : date.toLocaleString(localeTag(), {month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'}); }
function activeRun() { return state.runs.find(run => run.graph_id === state.run); }
function assetKind(asset) {
  if (asset.producer === 'pixel-action-set') return tr('2D 캐릭터 · 6동작');
  if (asset.producer === 'pixel-effect') return tr('2D 픽셀 이펙트');
  if (asset.producer === 'model-assets') return asset.files?.effect ? tr('3D 이펙트') : tr('3D 소품');
  return asset.producer || tr('에셋');
}
const failureMessages = {
  output_exists:'같은 출력 폴더가 이미 있어 제작을 시작하지 않았습니다.',
  timeout:'제작 제한 시간을 초과했습니다.', producer_timeout:'제작 제한 시간을 초과했습니다.',
  build_failed:'제작을 완료하지 못했습니다.', invalid_input:'씬 또는 제작 요청을 승인하지 못했습니다.',
  invalid_brief:'제목·목표·조작 의도가 있는 게임 기획이 필요합니다.',
  invalid_schema:'버전 1 형식의 올바른 JSON 입력이 필요합니다.',
  invalid_scene:'씬의 에셋·노드·변환 설정을 확인하세요.',
  invalid_reuse:'에셋의 제작 요청 또는 정확한 재사용 실행과 에셋을 선택하세요.',
  reuse_not_ready:'이 프로젝트에서 완료된 실행을 선택하세요.',
  reuse_mismatch:'재사용 원본 에셋·제작기·고정 파일이 일치하지 않습니다.',
  missing_input:'선언한 프로젝트 입력 파일을 복원하세요.',
  confinement:'입출력 경로는 프로젝트 경계 안의 상대 경로여야 합니다.',
  missing_tool:'필요한 제작기를 설치하거나 활성화하세요.',
  interrupted:'제작이 중단되었습니다. 새 출력 폴더로 다시 실행하세요.',
  input_mismatch:'고정된 입력을 복원하거나 새 실행을 시작하세요.',
  producer_failed:'제작기 입력과 설치 상태를 확인한 뒤 새 출력으로 다시 실행하세요.',
  invalid_bundle:'제작기 산출물의 계약을 확인하세요.'
};
function failureReason(error = {}) {
  const explanation = failureMessages[error.code] ? tr(failureMessages[error.code]) : tr('기록된 실패 사유가 없습니다.');
  return `${explanation}${error.code ? ` (${error.code})` : ''}${!failureMessages[error.code] && error.reason ? ` · ${error.reason}` : ''}`;
}
const stageName = stage => translatedValue(({admission:'입력 승인',inputs:'입력 고정',discovery:'제작기 검색',producer:'제작기 실행','bundle-validation':'산출물 검사','reuse-validation':'재사용 검사',publish:'런타임 생성'})[stage] || stage);
const evidenceName = value => value === 'producer-report' ? tr('제작기 보고') : value;
function updateSceneProof() {
  const metrics = state.renderer?.metrics;
  if (!metrics) return;
  bindText($('pause-view'), () => (metrics.paused ? tr('재생') : tr('일시정지')));
  $('pause-view').setAttribute('aria-pressed', String(Boolean(metrics.paused)));
  $('step-view').disabled = !metrics.paused;
  bindText($('scene-info'), () => (tr('sceneMetrics',{nodes:num(metrics.node_count || 0),frames:num(metrics.frame_count || 0),triangles:num(metrics.rendered_model_triangles || 0)})));
}

function sceneInput(run) {
  const runNode = state.nodes.find(node => node['@id'] === run?.graph_id);
  return state.nodes.find(node => runNode?.used?.includes(node['@id']) && types(node).includes('SceneRevision'))?.snapshot;
}
function runName(run) { return sceneInput(run)?.brief?.title || sceneInput(run)?.id || run.scene_id || tr('게임 장면'); }
function renderBrief(brief) {
  const panel = $('game-brief'); panel.replaceChildren(); panel.hidden = !brief?.goal && !brief?.controls;
  if (panel.hidden) return;
  panel.append(make('span','brief-label',() => (tr('기록된 게임 기획'))));
  fields(panel,() => ([[tr('목표'),brief.goal],[tr('조작 의도'),brief.controls]]));
}

function pin(path) {
  if (typeof path !== 'string' || path.startsWith('/') || path.split('/').includes('..') || path.includes('\\')) throw uiError('프로젝트 상대 경로가 아닙니다.');
  const candidates = state.nodes.filter(node => node.path === path && typeof node.sha256 === 'string' && /^[a-f0-9]{64}$/.test(node.sha256) && node['@id'].startsWith(`${state.project}:`));
  const current = candidates.find(node => node['@id'].startsWith(`${state.run}:`));
  if (current) return current;
  const runtime = state.nodes.find(node => node['@id'] === `${state.run}:runtime`);
  const pinned = candidates.filter(node => runtime?.wasDerivedFrom?.includes(node['@id']));
  if (!pinned.length || new Set(pinned.map(node => node.sha256)).size !== 1) throw uiError('이 실행의 그래프에서 파일 해시를 확인할 수 없습니다.');
  return pinned[0];
}
function artifactURL(path) { const node = pin(path); return scopedURL(`/artifact?path=${encodeURIComponent(path)}&sha256=${node.sha256}`); }
function fields(container, entries) {
  const dl = make('dl', 'properties');
  resolve(entries).forEach(([name, value], index) => {
    if (value == null) return;
    const read = () => resolve(entries)[index];
    dl.append(make('dt', '', () => read()[0]), make('dd', '', () => {
      const current = read()[1];
      return typeof current === 'object' ? JSON.stringify(current) : typeof current === 'number' ? num(current) : typeof current === 'boolean' ? tr(current ? '통과' : '실패') : current;
    }));
  });
  container.append(dl);
}
function comparisonFileURL(file) {
  return scopedURL(`/artifact?path=${encodeURIComponent(file.path)}&sha256=${encodeURIComponent(file.sha256)}`);
}
async function loadComparisonRuntime(side) {
  const runtimePin = side.runtime;
  const response = await fetch(comparisonFileURL(runtimePin));
  if (!response.ok) throw Error('Comparison runtime is unavailable');
  const bytes = await response.arrayBuffer();
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  if (bytes.byteLength !== runtimePin.byteCount ||
      Array.from(new Uint8Array(hash), n => n.toString(16).padStart(2,'0')).join('') !== runtimePin.sha256) {
    throw Error('Comparison runtime pin changed');
  }
  const files = new Map(side.artifacts.map(file => [file.path,file]));
  const assetURL = path => {
    if (!files.has(path)) throw Error('File is outside the pinned comparison');
    return comparisonFileURL(files.get(path));
  };
  const run = state.runs.find(candidate => candidate.graph_id === side.run);
  return {runtime:JSON.parse(new TextDecoder().decode(bytes)),assetURL,playURL:run?.playable_url};
}
const tabs = ['scene','compare','graph'];
function switchTab(name) {
  for (const value of tabs) {
    const selected = name === value;
    $(`tab-${value}`).setAttribute('aria-selected',String(selected));
    $(`tab-${value}`).tabIndex = selected ? 0 : -1;
    $(`panel-${value}`).hidden = !selected;
  }
  if (name === 'graph') renderGraph();
  const address = new URL(location.href);
  if (name === 'scene') address.searchParams.delete('view');
  else address.searchParams.set('view', name);
  history.replaceState(history.state, '', address);
}
for (const [index,name] of tabs.entries()) {
  $(`tab-${name}`).addEventListener('click',()=>switchTab(name));
  $(`tab-${name}`).addEventListener('keydown',event=>{
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1)
      : tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    switchTab(next); $(`tab-${next}`).focus();
  });
}
function placeGallery(gallery) {
  const hasPosters = gallery.childElementCount > 0;
  const overview = hasPosters && !state.runs.length;
  const rail = $('project-rail');
  const home = $('project-overview');
  rail.hidden = !hasPosters || overview;
  home.hidden = !overview;
  document.body.classList.toggle('workspace-overview', overview);
  const parent = overview ? home : rail;
  if (gallery.parentNode !== parent) parent.append(gallery);
}
function renderProjects(projects) {
  const gallery = $('project-gallery');
  const focusedProject = gallery.contains(document.activeElement) ? document.activeElement.dataset.project : null;
  gallery.replaceChildren();
  const visualProjects = projects.filter(project => project.preview);
  gallery.hidden = !visualProjects.length;
  for (const project of visualProjects) {
    const preview = project.preview;
    if (typeof preview.path !== 'string' || preview.path.startsWith('/') || preview.path.includes('\\') || preview.path.split('/').includes('..') || !/^[a-f0-9]{64}$/.test(preview.sha256)) continue;
    const link = make('a', 'project-tile');
    link.dataset.project = project.id;
    bindText(link, () => localizedUrl(`/?project=${encodeURIComponent(project.id)}`), 'href');
    bindText(link, () => tr('프로젝트 열기', {name:project.title || project.name}), 'aria-label');
    if (project.id === state.project) {
      link.classList.add('selected');
      link.setAttribute('aria-current', 'page');
    }
    const imageFrame = make('span', 'project-preview');
    const image = make('img');
    image.alt = '';
    image.loading = 'lazy';
    image.decoding = 'async';
    image.src = `/artifact?project=${encodeURIComponent(project.id)}&path=${encodeURIComponent(preview.path)}&sha256=${preview.sha256}`;
    image.addEventListener('error', () => {
      const focused = document.activeElement === link;
      link.remove();
      gallery.hidden = !gallery.children.length;
      placeGallery(gallery);
      if (focused) {
        const next = gallery.querySelector('a');
        if (next) next.focus();
        else { $('history-details').open = true; $('project-picker').focus(); }
      }
    });
    imageFrame.append(image);
    link.append(imageFrame, make('span', 'project-title', () => project.title || project.name));
    gallery.append(link);
    if (focusedProject === project.id) link.focus({preventScroll:true});
  }
  placeGallery(gallery);
}

function updatePlayLink(run) {
  const link = $('play-game');
  link.hidden = true;
  link.removeAttribute('href');
  if (run?.status !== 'ready' || typeof run.playable_url !== 'string') return;
  try {
    const url = new URL(run.playable_url);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if (url.protocol !== 'http:' || !loopback || url.username || url.password || (url.port || '80') === (location.port || '80')) return;
    link.href = url.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.hidden = false;
  } catch {
    // An invalid supplied URL leaves the selected run without a play link.
  }
}

function renderRuns() {
  bindText($('run-count'), () => (num(state.runs.length)));
  $('runs').replaceChildren();
  if (!state.runs.length) $('runs').append(make('p','empty-small',() => (tr('아직 제작 기록이 없어요. Codex에서 첫 장면을 만들어 보세요.'))));
  for (const run of state.runs) {
    const button = make('button', `run-item${state.run === run.graph_id ? ' selected' : ''}`);
    button.setAttribute('aria-pressed', String(state.run === run.graph_id));
    const top = make('div','run-top'); top.append(badge(run.status), make('time','',() => (time(run.started_at))));
    button.append(top, make('strong','',() => runName(run)));
    if (run.status === 'running' && run.live === false) button.append(make('small','stale',() => (tr('실행 프로세스 연결 없음'))));
    button.addEventListener('click', () => selectRun(run.graph_id)); $('runs').append(button);
  }
}
function placeholder(heading, description) { $('scene').hidden = true; $('scene-placeholder').hidden = false; bindText($('scene-placeholder').querySelector('h3'), () => (resolve(heading))); bindText($('scene-placeholder').querySelector('p'), () => (resolve(description))); }
async function selectRun(id) {
  state.run = id; const epoch = ++state.epoch; ++state.detailVersion; clearInterval(state.proofTimer); state.proofTimer = null;
  state.renderer?.dispose(); state.renderer = null; $('view-controls').hidden = true;
  renderRuns(); const run = activeRun();
  updatePlayLink(run);
  bindings.delete($('run-message'));
  $('artifact-detail').hidden = true;
  $('artifact-detail').replaceChildren();
  delete $('artifact-detail').dataset.asset;
  delete $('artifact-detail').dataset.path;
  $('scene-action').value=''; $('action-control').hidden=true; state.previews.clear(); $('assets').replaceChildren(); $('steps').replaceChildren(); $('run-message').hidden = true; $('run-message').replaceChildren();
  $('run-status').hidden = !run; renderBrief(run ? sceneInput(run)?.brief : null);
  if (!run) { bindText($('run-title'), () => (tr(document.body.classList.contains('workspace-overview') ? '프로젝트 선택' : '다음 장면을 기다리는 작업실'))); bindText($('run-subtitle'), () => (tr('첫 제작이 시작되면 과정과 결과가 여기에 모입니다.'))); placeholder(() => (tr('아직 완성된 장면이 없어요')),() => (tr('Codex 채팅에서 제작을 시작하면 여기에 기록됩니다.'))); bindText($('asset-count'), () => (tr('0개'))); renderGraph(); return; }
  bindText($('run-title'), () => (runName(run)));
  bindText($('run-subtitle'), () => time(run.started_at));
  $('run-status').replaceWith(Object.assign(badge(run.status), {id:'run-status'}));
  bindText($('scene-caption'), () => (run.status === 'ready' ? tr('실제 런타임 장면') : tr('제작 상태')));
  const message = $('run-message');
  if (run.status === 'error') { message.hidden = false; message.className = 'notice error'; message.append(make('strong','',() => (tr('이 실행은 완료되지 않았어요'))), make('p','',() => (`${stageName(run.error?.stage) || tr('알 수 없는 단계')} · ${failureReason(run.error)}${run.error?.type ? ` · ${run.error.type}` : ''}`))); if (run.error?.reason) { const raw = make('details','raw-details'); raw.append(make('summary','',() => tr('원문 실패 기록')),make('pre','',() => JSON.stringify(run.error,null,2))); message.append(raw); } placeholder(() => (tr('완료되지 않은 장면')),() => (tr('아래 단계와 관계 탭에서 기록된 실패 근거를 확인하세요.'))); }
  else if (run.status !== 'ready') { message.hidden = false; message.className = 'notice'; bindText(message, () => run.live === false ? tr('제작 중으로 기록되어 있지만 실행 프로세스가 연결되어 있지 않습니다.') : tr('제작 진행 상황을 자동으로 확인하고 있어요.')); placeholder(() => (tr('장면을 만들고 있어요')),() => (tr('완료된 에셋과 단계는 아래에서 확인할 수 있어요.'))); }
  else placeholder(() => (tr('장면을 불러오는 중')),() => (tr('그래프에 고정된 런타임과 에셋을 확인하고 있어요.')));
  renderAssets(run); renderSteps(run); renderGraph();
  if (run.status !== 'ready' || !run.runtime) return;
  try {
    const url = artifactURL(run.runtime); const response = await fetch(url); if (!response.ok) throw uiError('runtimeFetch',{status:response.status});
    const runtime = await response.json(); if (epoch !== state.epoch) return;
    if (runtime.brief?.title) bindText($('run-title'), () => (runtime.brief.title));
    renderBrief(runtime.brief);
    $('scene').hidden = false; $('scene-placeholder').hidden = true;
    const assetURL = path => { if (epoch !== state.epoch) throw uiError('선택한 실행이 변경되었습니다.'); return artifactURL(path); };
    const {showScene} = await import('./scene-view.mjs');
    if (epoch !== state.epoch) return;
    const renderer = await showScene($('scene'), runtime, assetURL);
    if (epoch !== state.epoch) { renderer.dispose(); return; }
    state.renderer = renderer;
    $('view-controls').hidden = !renderer.metrics?.inspection;
    $('rotate-view').hidden = !renderer.metrics?.inspection?.rotate;
    const actions=renderer.metrics?.inspection?.actions || [];
    $('scene-action').replaceChildren(Object.assign(make('option','',() => (tr('기록된 동작'))),{value:''}),...actions.map(action=>Object.assign(make('option','',() => (actionName(action))),{value:action})));
    $('action-control').hidden = !actions.length || typeof renderer.setAction!=='function';
    updateSceneProof();
    state.proofTimer = setInterval(updateSceneProof, 500);
    bindText($('scene-info'), () => (tr('sceneAssets',{nodes:num(runtime.nodes?.length || 0),assets:num(runtime.assets?.length || 0)})));
    bindText($('scene'), () => (`${runtime.brief?.title || runtime.id || tr('게임')}. ${inspectionLabel()}`), 'aria-label');
    void renderModelPreviews(runtime, assetURL, epoch, showScene);
  } catch (error) { if (epoch === state.epoch) placeholder(() => (tr('미리보기를 열 수 없어요')),() => (tr('previewError',{error:errorText(error)}))); }
}
function renderSteps(run) {
  $('steps').append(make('h3','',() => (tr('제작 과정'))));
  if (!run.steps?.length) { $('steps').append(make('p','muted',() => (run.error?.stage === 'admission' ? tr('입력 승인 단계에서 중단되어 제작기가 실행되지 않았습니다.') : tr('기록된 제작 단계가 없습니다.')))); return; }
  for (const [index, step] of run.steps.entries()) { const row = make('div','step'); row.append(make('span','step-number',() => (String(index + 1).padStart(2,'0'))), make('strong','',() => (step.asset)), make('span','muted',() => (step.producer)), badge(step.status)); if (step.validation) row.append(make('small','',() => (step.validation.passed ? tr('계약 검사 통과') : tr('검사 실패')))); $('steps').append(row); }
}
function assetPreview(asset) {
  const files = Object.entries(asset.files || {});
  const images = files.filter(([, path]) => /\.(png|gif|webp|jpe?g)$/i.test(path));
  return images.find(([role]) => role === 'preview') || images.find(([role]) => role === 'review') || images.find(([role]) => role === 'atlas') || images[0];
}
function renderAssets(run) {
  const assets = run.assets || [];
  bindText($('asset-count'), () => tr('assetCount', {count:num(assets.length)}));
  if (!assets.length) $('assets').append(make('p', 'empty-small', () => tr('아직 납품된 에셋이 없습니다.')));
  for (const asset of assets) {
    const card = make('article', 'asset-card');
    const preview = make('button', 'asset-preview');
    preview.type = 'button';
    preview.setAttribute('aria-controls', 'artifact-detail');
    preview.setAttribute('aria-expanded', 'false');
    bindText(preview, () => tr('assetLabel', {name:asset.id}), 'aria-label');
    const image = assetPreview(asset);
    if (image) {
      try {
        const img = make('img');
        img.src = artifactURL(image[1]);
        img.alt = '';
        img.className = asset.producer === 'pixel-action-set' ? 'authored-preview pixel-preview' : 'authored-preview';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.addEventListener('error', () => {
          img.remove();
          preview.append(make('span', 'preview-unavailable', () => tr('이미지 파일을 읽을 수 없어요')));
        });
        preview.append(img);
      } catch {
        preview.append(make('span', 'preview-unavailable', () => tr('고정된 이미지 없음')));
      }
    } else {
      const glyph = make('span', 'model-glyph', '◇');
      glyph.setAttribute('aria-hidden', 'true');
      preview.append(glyph);
    }
    state.previews.set(asset.id, preview);
    preview.addEventListener('click', () => showArtifact(asset, image?.[1] || Object.values(asset.files || {})[0]));
    card.append(preview, make('h4', '', () => asset.id));
    $('assets').append(card);
  }
}
async function renderModelPreviews(runtime, assetURL, epoch, showScene) {
  for (const asset of runtime.assets.filter(asset => asset.files?.model && !Object.values(asset.files).some(path => /\.(png|gif|webp|jpe?g)$/i.test(path)))) {
    if (epoch !== state.epoch) return;
    const preview = state.previews.get(asset.id);
    const nodes = runtime.nodes.filter(node => node.asset === asset.id);
    if (!preview || !nodes.length) continue;
    const canvas = make('canvas'); bindText(canvas, () => (`${tr('modelPreview',{name:asset.id})}. ${inspectionLabel()}`), 'aria-label');
    preview.replaceChildren(canvas);
    let renderer;
    try {
      renderer = await showScene(canvas, {...runtime, assets:[asset], nodes}, assetURL);
      if (epoch !== state.epoch) return;
      const img = make('img'); img.src = canvas.toDataURL('image/png'); bindText(img, () => (tr('modelImage',{name:asset.id})), 'alt');
      img.className = 'model-thumbnail'; preview.replaceChildren(img);
      if (!$('artifact-detail').hidden && $('artifact-detail').dataset.asset === asset.id) {
        const dockImage = img.cloneNode();
        bindText(dockImage, () => tr('modelImage', {name:asset.id}), 'alt');
        dockImage.className = 'artifact-image';
        $('artifact-detail').querySelector('.artifact-visual')?.replaceChildren(dockImage);
      }
    } catch {
      if (epoch === state.epoch) preview.replaceChildren(make('span','preview-unavailable',() => (tr('모델 미리보기를 읽을 수 없어요'))));
    } finally { renderer?.dispose(); }
  }
}
function closeArtifact() {
  const detail = $('artifact-detail');
  const preview = state.previews.get(detail.dataset.asset);
  ++state.detailVersion;
  detail.hidden = true;
  for (const button of state.previews.values()) {
    button.setAttribute('aria-expanded', 'false');
    button.closest('.asset-card')?.classList.remove('selected');
  }
  preview?.focus({preventScroll:true});
}
async function showArtifact(asset, path, scroll = true) {
  const detail = $('artifact-detail');
  const restoreFileFocus = !scroll && detail.contains(document.activeElement);
  let selectedFileButton;
  const keepTechnicalOpen = detail.dataset.asset === asset.id && detail.querySelector('.artifact-technical')?.open;
  for (const [id, preview] of state.previews) {
    preview.closest('.asset-card')?.classList.toggle('selected', id === asset.id);
    preview.setAttribute('aria-expanded', String(id === asset.id));
  }
  const version = ++state.detailVersion;
  detail.hidden = false;
  detail.tabIndex = -1;
  detail.dataset.asset = asset.id;
  detail.dataset.path = path;
  detail.replaceChildren();
  const heading = make('div', 'artifact-heading');
  const close = make('button', 'artifact-close', () => tr('검사 닫기'));
  close.type = 'button';
  close.addEventListener('click', closeArtifact);
  heading.append(make('h3', '', () => asset.id), close);
  const visual = make('div', 'artifact-visual');
  const technical = make('details', 'artifact-technical');
  technical.open = Boolean(keepTechnicalOpen);
  technical.append(make('summary', '', () => tr('파일과 제작 근거')));
  detail.append(heading, make('p', 'muted', () => assetKind(asset)), visual);
  try {
    const node = pin(path);
    if (/\.(png|gif|webp|jpe?g)$/i.test(path)) {
      const image = make('img', 'artifact-image');
      image.src = artifactURL(path);
      bindText(image, () => `${asset.id} · ${path.split('/').pop()}`, 'alt');
      visual.append(image);
    } else {
      const existing = state.previews.get(asset.id)?.querySelector('img');
      if (existing) {
        const image = existing.cloneNode();
        image.className = 'artifact-image';
        bindText(image, () => asset.id, 'alt');
        visual.append(image);
      }
    }
    const graph = make('button', 'text-button', () => tr('그래프에서 관계 보기 ↗'));
    graph.type = 'button';
    graph.addEventListener('click', () => {
      state.node = node['@id'];
      switchTab('graph');
      $('graph-map').tabIndex = -1;
      $('graph-map').focus();
    });
    detail.append(graph);
    const files = make('div', 'file-buttons');
    for (const [role, filePath] of Object.entries(asset.files || {})) {
      const button = make('button', 'file-button', () => roleName(role));
      button.type = 'button';
      button.setAttribute('aria-pressed', String(filePath === path));
      if (filePath === path) selectedFileButton = button;
      button.addEventListener('click', () => showArtifact(asset, filePath, false));
      files.append(button);
    }
    technical.append(files);
    const placements = sceneInput(activeRun())?.nodes?.filter(item => item.asset === asset.id) || [];
    const generators = (Array.isArray(node.wasGeneratedBy) ? node.wasGeneratedBy : [node.wasGeneratedBy]).filter(Boolean).map(id => state.nodes.find(item => item['@id'] === id)).filter(Boolean);
    fields(technical, () => [
      [tr('제작기'), asset.producer], [tr('생성 근거'), generators.map(title).join(', ') || tr('파일 기록 참조')],
      [tr('배치'), placements.map(item => item.id).join(', ') || tr('없음')], [tr('위치'), placements[0]?.position],
      [tr('크기 배율'), placements[0]?.scale], [tr('회전 (도)'), placements[0]?.rotation_degrees],
      [tr('기록된 동작'), placements[0]?.action ? actionName(placements[0].action) : null],
      [tr('에셋'), asset.id], [tr('파일 경로'), node.path], ['SHA-256', node.sha256],
      [tr('크기'), `${node.byteCount == null ? '—' : num(node.byteCount)} bytes`],
    ]);
    const raw = make('details', 'raw-details');
    raw.append(make('summary', '', () => tr('원본 파일 기록')), make('pre', '', () => JSON.stringify(node, null, 2)));
    technical.append(raw);
  } catch (error) {
    technical.append(make('p', '', () => errorText(error)));
  }
  detail.append(technical);
  if (restoreFileFocus) selectedFileButton?.focus({preventScroll:true});
  if (scroll) {
    detail.focus({preventScroll:true});
    detail.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'nearest'});
  }
  if (asset.producer === 'pixel-action-set' && asset.files?.metadata) { await showActionSummary(asset, asset.files.metadata, technical, version); return; }
  if (!asset.files?.effect || asset.producer !== 'model-assets') return;
  const summary = make('section','effect-summary'); summary.append(make('h4','',() => (tr('3D 이펙트 레시피')))); technical.append(summary);
  try {
    const response = await fetch(artifactURL(asset.files.effect));
    if (!response.ok) throw uiError('recipeFetch',{status:response.status});
    const recipe = await response.json();
    if (version !== state.detailVersion) return;
    if (recipe.schema_version !== 1 || recipe.kind !== 'mesh-particles' || recipe.units !== 'meters' || !Array.isArray(recipe.particles) || !Number.isFinite(recipe.duration_s) || recipe.duration_s <= 0) throw uiError('지원하는 3D 이펙트 레시피 형식이 아닙니다.');
    const placements = sceneInput(activeRun())?.nodes?.filter(node => node.asset === asset.id) || [];
    const parents = placements.map(node => node.parent || node.attachedTo).filter(Boolean);
    fields(summary,() => ([[tr('종류'),tr('3D 메시 파티클')],[tr('파티클 수'),tr('count',{count:num(recipe.particles.length)})],[tr('재생 주기'),tr('seconds',{count:num(recipe.duration_s)})],[tr('공간 단위'),tr('미터')],[tr('부착 대상'),parents.length ? parents.join(', ') : tr('독립 배치')]]));
  } catch (error) { if (version === state.detailVersion) summary.append(make('p','muted',() => (errorText(error)))); }
}
async function showActionSummary(asset, path, detail, version) {
  const summary = make('section','effect-summary'); summary.append(make('h4','',() => (tr('캐릭터 동작과 이벤트')))); detail.append(summary);
  try {
    const response = await fetch(artifactURL(path));
    if (!response.ok) throw uiError('actionFetch',{status:response.status});
    const metadata = await response.json();
    if (version !== state.detailVersion) return;
    if (metadata.schema_version !== 1 || !metadata.actions || typeof metadata.actions !== 'object' || Array.isArray(metadata.actions) || !Array.isArray(metadata.events)) throw uiError('지원하는 캐릭터 동작 메타데이터가 아닙니다.');
    const placements = sceneInput(activeRun())?.nodes?.filter(node => node.asset === asset.id) || [];
    fields(summary,() => ([[tr('현재 동작'),placements.map(node => `${node.id}: ${actionName(node.action || 'idle')}`).join(', ') || tr('배치 없음')],[tr('동작 목록'),Object.keys(metadata.actions).map(actionName).join(', ')],[tr('캐릭터 피벗'),metadata.pivot_px_from_top_left]]));
    for (const [name, action] of Object.entries(metadata.actions)) fields(summary,() => ([[actionName(name),tr('actionStats',{frames:num(action.frames?.length || 0),duration:action.duration_ms == null ? '—' : num(action.duration_ms),loop:action.loop ? tr('반복') : tr('한 번')})]]));
    summary.append(make('h4','',() => (tr('events',{count:num(metadata.events.length)}))));
    for (const event of metadata.events) fields(summary,() => ([[tr('동작'),actionName(event.action)],[tr('프레임'),event.frame == null ? null : num(event.frame)],[tr('시작 (ms)'),event.start_ms == null ? null : num(event.start_ms)],[tr('위치 (px)'),event.at_px],[tr('이펙트 기준점 (px)'),event.effect_anchor_px]]));
  } catch (error) { if (version === state.detailVersion) summary.append(make('p','muted',() => (errorText(error)))); }
}
function graphButton(node, subtitle) { const button=make('button','node-button'); button.append(make('small','node-kind',() => (lookup(kindNames, kind(node)) || kind(node))),make('strong','',() => (title(node)))); if(subtitle) button.append(make('small','node-path',() => (node.path || (subtitle === node.status ? statusName(node.status) : lookup(relations, subtitle) || subtitle)))); button.addEventListener('click',()=>{state.node=node['@id'];renderGraph();}); return button; }
function renderGraph() {
  bindText($('graph-count'), () => (num(state.nodes.length)));
  const existing = $('graph-type').value; const allTypes = [...new Set(state.nodes.map(kind))].sort();
  $('graph-type').replaceChildren(Object.assign(make('option','',() => (tr('모든 종류'))),{value:''}),...allTypes.map(type=>Object.assign(make('option','',() => (lookup(kindNames, type) || type)),{value:type}))); $('graph-type').value = existing;
  const search = $('graph-search').value.trim().toLocaleLowerCase(); const type = $('graph-type').value;
  const filtered = state.nodes.filter(node => (!type || kind(node) === type) && `${title(node)} ${node.path || ''} ${node['@id']}`.toLocaleLowerCase().includes(search));
  if (!state.nodes.some(node => node['@id'] === state.node)) state.node = (state.nodes.find(node => node['@id'] === state.run) || filtered[0])?.['@id'];
  $('graph-nodes').replaceChildren();
  for (const node of filtered) { const button=graphButton(node,node.path || node.status); button.classList.toggle('selected',node['@id']===state.node); button.setAttribute('aria-pressed',String(node['@id']===state.node)); $('graph-nodes').append(button); }
  bindText($('graph-results'), () => (tr('results',{count:num(filtered.length),total:num(state.nodes.length)})));
  if (!filtered.length) $('graph-nodes').append(make('p','empty-small',() => (tr('일치하는 항목이 없습니다.'))));
  let selected = state.nodes.find(node=>node['@id']===state.node);
  if (!selected) { selected=state.nodes.find(node=>node['@id']===state.run) || filtered[0]; state.node=selected?.['@id']; }
  $('graph-map').replaceChildren(); $('graph-summary').replaceChildren(); $('relations').replaceChildren(); bindText($('graph-raw'), () => (''));
  if (!selected) { $('graph-summary').append(make('p','muted',() => (tr('아직 그래프에 기록된 항목이 없습니다.')))); return; }
  $('graph-summary').append(make('p','eyebrow',() => (lookup(kindNames, kind(selected)) || kind(selected))),make('h3','',() => (title(selected))));
  fields($('graph-summary'),() => ([[tr('파일'),selected.path],[tr('역할'),selected.role ? roleName(selected.role) : null],[tr('상태'),statusName(selected.status)],['SHA-256',selected.sha256],[tr('근거'),evidenceName(selected.evidenceBasis)],[tr('검증 결과'),selected.verification],[tr('관측 시각'),selected.recordedAt ? time(selected.recordedAt) : null],[tr('실패 단계'),stageName(selected.snapshot?.stage)],[tr('오류'),kind(selected) === 'Error' ? failureReason(selected.snapshot) : selected.snapshot?.code],[tr('오류 종류'),selected.snapshot?.type],[tr('원문 실패 사유'),kind(selected) === 'Error' ? selected.snapshot?.reason : null],['ID',selected['@id']]]));
  const byId = new Map(state.nodes.map(node=>[node['@id'],node]));
  const edges=[]; const context = state.context || {};
  for(const node of state.nodes) for(const [key,value] of Object.entries(node)) {
    if (!(context[key]?.['@type']==='@id' || Object.hasOwn(relations,key))) continue;
    for(const ref of Array.isArray(value)?value:[value]) { const target=typeof ref==='string'?ref:ref?.['@id']; if(byId.has(target)) edges.push({from:node['@id'],to:target,key}); }
  }
  renderGraphMap(selected, edges, byId);
  for(const incoming of [true,false]) {
    const group=make('section','relation-group'); const related=edges.filter(edge=>(incoming?edge.to===state.node:edge.from===state.node) && ($('revision-disclosure').open || ![edge.from,edge.to].some(id=>kind(byId.get(id))==='RunRevision')));
    group.append(make('h4','',() => (`${incoming?tr('들어오는 관계'):tr('나가는 관계')} · ${num(related.length)}`)));
    if(!related.length) group.append(make('p','muted',() => (tr('기록된 관계 없음'))));
    for(const edge of related) { const row=make('div','relation-row'); row.append(make('span','edge-label',() => (`${incoming?'←':'→'} ${lookup(relations, edge.key) || edge.key}`)),graphButton(byId.get(incoming?edge.from:edge.to),edge.key)); group.append(row); }
    $('relations').append(group);
  }
  bindText($('graph-raw'), () => (JSON.stringify(selected,null,2)));
}
$('graph-search').addEventListener('input',renderGraph); $('graph-type').addEventListener('change',renderGraph);
function renderGraphMap(selected, edges, byId) {
  const allConnected = edges.filter(edge => edge.from === selected['@id'] || edge.to === selected['@id']);
  const revisions=allConnected.filter(edge=>[edge.from,edge.to].some(id=>kind(byId.get(id))==='RunRevision'));
  $('revision-disclosure').hidden=!revisions.length; bindText($('revision-summary'), () => (tr('revisionCount',{count:num(revisions.length)})));
  const priority=edge=>['RuntimeProduct','SceneRevision','Artifact','WorkStep','ScenePlacement'].indexOf(kind(byId.get(edge.from===selected['@id']?edge.to:edge.from)));
  const connected=allConnected.filter(edge=>$('revision-disclosure').open || !revisions.includes(edge)).sort((a,b)=>(priority(a)<0?99:priority(a))-(priority(b)<0?99:priority(b)));
  const incoming = connected.filter(edge => edge.to === selected['@id']).slice(0,4);
  const outgoing = connected.filter(edge => edge.from === selected['@id']).slice(0,4);
  const rows = Math.max(incoming.length, outgoing.length, 1);
  const height = Math.max(210, rows * 74 + 52);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 1000 ${height}`);
  svg.setAttribute('role', 'group'); bindText(svg, () => (tr('connections',{name:title(selected),count:num(connected.length)})), 'aria-label');
  const element = (tag, attrs, text) => { const item = document.createElementNS(svg.namespaceURI, tag); for(const [key,value] of Object.entries(attrs)) { if (typeof value === 'function') bindText(item, value, key); else item.setAttribute(key,value); } if(text != null) bindText(item,text); return item; };
  const middle = height / 2;
  function nodeBox(node,x,y,active=false) {
    const group = element('g', {class:`graph-node${active?' selected':''}`,transform:`translate(${x} ${y})`,role:'button',tabindex:'0','aria-label':() => `${lookup(kindNames, kind(node)) || kind(node)}: ${title(node)}`});
    const fullTitle=() => title(node); group.append(element('title',{},() => (fullTitle())),element('rect',{width:240,height:54}),element('text',{x:13,y:19,class:'map-kind'},() => (lookup(kindNames, kind(node)) || kind(node))),element('text',{x:13,y:39},() => (fullTitle().length>23?`${fullTitle().slice(0,22)}…`:fullTitle())));
    const activate=()=>{state.node=node['@id'];renderGraph();}; group.addEventListener('click',activate); group.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();activate();}}); return group;
  }
  if(matchMedia('(max-width: 700px)').matches) {
    svg.setAttribute('viewBox','0 0 360 300');
    const items=[incoming[0],outgoing[0]].filter(Boolean);
    for(const [index,edge] of [[0,incoming[0]],[1,outgoing[0]]]) {
      if(!edge) continue;
      const from=index===0?72:166,to=index===0?112:206;
      svg.append(element('path',{class:'graph-edge',d:`M 180 ${from} L 180 ${to}`}));
      svg.append(element('text',{class:'graph-edge-label',x:190,y:(from+to)/2},() => (`${lookup(relations, edge.key) || edge.key} ↓`)));
      svg.append(nodeBox(byId.get(index===0?edge.from:edge.to),60,index===0?18:206));
    }
    svg.append(nodeBox(selected,60,112,true)); $('graph-map').append(svg);
    if(allConnected.length>items.length) $('graph-map').append(make('p','graph-map-note',() => (tr('mapNote',{count:num(items.length),total:num(allConnected.length)}))));
    return;
  }
  for (const [isIncoming, items] of [[true,incoming],[false,outgoing]]) {
    items.forEach((edge,index)=>{
      const y=26+index*74+Math.max(0,(height-52-items.length*74)/2), fromX=isIncoming?260:620, toX=isIncoming?380:740;
      const fromY=isIncoming?y+27:middle, toY=isIncoming?middle:y+27;
      svg.append(element('path',{class:'graph-edge',d:`M ${fromX} ${fromY} C ${(fromX+toX)/2} ${fromY}, ${(fromX+toX)/2} ${toY}, ${toX} ${toY}`}));
      svg.append(element('text',{class:'graph-edge-label',x:(fromX+toX)/2,y:y+18,'text-anchor':'middle'},() => (`${lookup(relations, edge.key) || edge.key} →`)));
      svg.append(nodeBox(byId.get(isIncoming?edge.from:edge.to),isIncoming?20:740,y));
    });
  }
  svg.append(nodeBox(selected,380,middle-27,true)); $('graph-map').append(svg);
  if(connected.length>incoming.length+outgoing.length) $('graph-map').append(make('p','graph-map-note',() => (tr('mapNote',{count:num(incoming.length+outgoing.length),total:num(allConnected.length)}))));
  if(!connected.length) $('graph-map').append(make('p','empty-small',() => (tr('이 항목에 기록된 연결이 없습니다.'))));
}
async function refresh() {
  if(state.refreshing) return;
  state.refreshing=true;
  try {
    const response=await fetch(scopedURL('/api/state'),{cache:'no-cache',headers:state.etag?{'If-None-Match':state.etag}:{}});
    if(response.status===304) { bindText($('connection'), () => (tr('프로젝트에 연결됨'))); document.body.classList.remove('offline'); return; }
    if(!response.ok) throw Error(`HTTP ${response.status}`); const data=await response.json();
    if(!Array.isArray(data.runs)||!Array.isArray(data.graph?.['@graph'])) throw uiError('상태 응답 형식 오류');
    state.etag=response.headers.get('ETag') || '';
    const signature=JSON.stringify(data); bindText($('connection'), () => (tr('프로젝트에 연결됨'))); document.body.classList.remove('offline');
    if(signature===state.signature) return;
    const previousRun=activeRun(); const previousProjection=JSON.stringify(previousRun); state.signature=signature; state.runs=data.runs; state.nodes=data.graph['@graph']; state.context=data.graph['@context']; state.project=data.project_id;
    updateCompare(state.nodes.filter(node=>state.project && node['@id'].startsWith(state.project+':')), {loadRuntime:loadComparisonRuntime, evidenceURL:comparisonFileURL});
    bindText($('project-name'), () => (data.project_name || tr('제작 관찰실')));
    const projects=Array.isArray(data.projects) ? data.projects : [];
    const browsing=projects.length>1; $('project-picker').hidden=!browsing; $('project-name').hidden=browsing;
    if(browsing) { $('project-picker').replaceChildren(...projects.map(project=>Object.assign(make('option','',() => (project.name)),{value:project.id}))); $('project-picker').value=data.project_id; }
    renderProjects(projects);
    const activities=data.activities || []; $('activity-section').hidden=!activities.length; $('activities').replaceChildren();
    for(const activity of activities) {const button=make('button','activity-item'); button.append(make('strong','',() => (activity.label)), make('small','',() => (`${lookup(labels, activity.status) || activity.status || tr('기록')} · ${time(activity.recorded_at)}`))); button.addEventListener('click',()=>{state.node=activity.graph_id;switchTab('graph');}); $('activities').append(button);}
    if(!state.run||!state.runs.some(run=>run.graph_id===state.run)) state.run=(state.runs.find(run=>run.status==='ready')||state.runs[0])?.graph_id || null;
    if(!previousRun||JSON.stringify(activeRun())!==previousProjection) await selectRun(state.run); else { renderRuns();renderGraph(); }
  } catch(error) { bindText($('connection'), () => (tr('연결을 확인 중'))); document.body.classList.add('offline'); if(!state.signature) { bindText($('run-title'), () => (tr('작업실에 연결할 수 없어요'))); placeholder(() => (tr('기록을 읽지 못했어요')),() => (errorText(error))); } }
  finally {state.refreshing=false;}
}
$('artifact-detail').addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closeArtifact(); }
});
$('project-picker').addEventListener('change',()=>location.assign(localizedUrl(`/?project=${encodeURIComponent($('project-picker').value)}`)));
$('revision-disclosure').addEventListener('toggle',renderGraph);
$('scene-action').addEventListener('change',()=>{const action=$('scene-action').value;const allowed=state.renderer?.metrics?.inspection?.actions || [];if(action && !allowed.includes(action)) return;state.renderer?.setAction(action || null);bindText($('scene-caption'), () => (action?tr('actionPreview',{action:actionName(action)}):tr('실제 런타임 장면')));updateSceneProof();});
$('pause-view').addEventListener('click',()=>{state.renderer?.setPaused(!state.renderer.metrics.paused);updateSceneProof();});
$('step-view').addEventListener('click',()=>{state.renderer?.seek((state.renderer.metrics.elapsed_ms || 0)+100);updateSceneProof();});
$('rotate-view').addEventListener('click',()=>state.renderer?.rotate(Math.PI/8));
$('zoom-in').addEventListener('click',()=>state.renderer?.zoom(1.15));
$('zoom-out').addEventListener('click',()=>state.renderer?.zoom(1/1.15));
$('reset-view').addEventListener('click',()=>state.renderer?.resetView());
// Bind the app-owned initial shell before the first asynchronous state request.
bindText($('play-game'), () => tr('게임 열기'));
updatePlayLink(null);
for (const [id, key] of Object.entries({
  connection:'연결 중', 'project-name':'제작 관찰실', 'run-title':'장면을 불러오는 중',
  'scene-caption':'실제 런타임 장면', 'scene-info':'미터 · +Y 위 · 오른손 좌표',
  'pause-view':'일시정지', 'revision-summary':'상태 기록 연결'
})) bindText($(id), () => tr(key));
bindText($('scene-placeholder').querySelector('h3'), () => tr('기록을 불러오는 중'));
bindText($('scene-placeholder').querySelector('p'), () => tr('그래프에 고정된 실제 장면과 에셋을 확인합니다.'));
window.addEventListener('studio:localechange', () => {
  for (const element of document.querySelectorAll('*')) {
    for (const [attribute, read] of bindings.get(element) || []) bindText(element, read, attribute);
  }
});

const initialView = new URLSearchParams(location.search).get('view');
if (tabs.includes(initialView)) switchTab(initialView);
await refresh(); const refreshTimer=setInterval(refresh,4000);
matchMedia('(max-width: 700px)').addEventListener('change',()=>{if($('tab-graph').getAttribute('aria-selected')==='true') renderGraph();});
window.addEventListener('pagehide',()=>{clearInterval(refreshTimer);clearInterval(state.proofTimer);state.renderer?.dispose();});
