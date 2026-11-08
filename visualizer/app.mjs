
const $ = id => document.getElementById(id);
const selectedProject = new URLSearchParams(location.search).get('project');
const scopedURL = path => selectedProject ? `${path}${path.includes('?') ? '&' : '?'}project=${encodeURIComponent(selectedProject)}` : path;
const state = {runs: [], nodes: [], project: '', run: null, node: null, renderer: null, epoch: 0, signature: '', previews: new Map(), detailVersion: 0, proofTimer: null, etag: '', refreshing: false};
const types = node => (Array.isArray(node?.['@type']) ? node['@type'] : [node?.['@type']]).filter(Boolean);
const kind = node => types(node).find(value => !['Entity', 'Activity', 'Agent'].includes(value)) || '항목';
const labels = {ready:'완료', error:'실패', running:'제작 중', pending:'대기', complete:'완료', reused:'재사용'};
const relations = {used:'입력으로 사용', wasGeneratedBy:'만든 작업', wasDerivedFrom:'유래한 입력', wasAssociatedWith:'제작 도구', dependsOn:'선행 의존 대상', attachedTo:'부착 대상', observed:'관측한 대상', failedWith:'발생한 오류', revisionOf:'상태 기록의 원본', partOf:'소속', placementOf:'배치한 에셋', includesProject:'등록 프로젝트'};
const kindNames = {Run:'실행', RunRevision:'상태 기록', RuntimeProduct:'런타임 장면', SceneRevision:'씬 입력', UnadmittedInput:'거절된 입력', Artifact:'산출물', SourceArtifact:'원본 파일', RequestRevision:'제작 요청', ExecutedRequest:'실행 요청', WorkStep:'제작 단계', Plugin:'제작 도구', Validation:'검사', ValidationEvidence:'검사 근거', ScenePlacement:'씬 배치', Error:'오류', ExternalWork:'외부 작업', Project:'프로젝트', Game:'게임', Workspace:'워크스페이스'};
const make = (tag, className, value) => { const el = document.createElement(tag); if (className) el.className = className; if (value != null) el.textContent = String(value); return el; };
const title = node => node.label || node.record?.output || node.snapshot?.brief?.title || node.path?.split('/').pop() || node.record?.scene_id || node.snapshot?.id || (kind(node) === 'Error' ? node.snapshot?.code : '') || `${kindNames[kind(node)] || kind(node)} · ${node['@id'].split(':').slice(-1)[0].slice(0, 18)}`;
const badge = status => make('span', `badge ${['ready','error','running','pending','complete','reused'].includes(status) ? status : ''}`, labels[status] || status || '기록');
function time(value) { if (!value) return '시간 정보 없음'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('ko-KR', {month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'}); }
function activeRun() { return state.runs.find(run => run.graph_id === state.run); }
function assetKind(asset) {
  if (asset.producer === 'pixel-action-set') return '2D 캐릭터 · 6동작';
  if (asset.producer === 'pixel-effect') return '2D 픽셀 이펙트';
  if (asset.producer === 'model-assets') return asset.files?.effect ? '3D 이펙트' : '3D 소품';
  return asset.producer || '에셋';
}
function failureReason(error = {}) {
  const reasons = {output_exists:'같은 출력 폴더가 이미 있어 제작을 시작하지 않았습니다.', timeout:'제작 제한 시간을 초과했습니다.', producer_timeout:'제작 제한 시간을 초과했습니다.', build_failed:'제작을 완료하지 못했습니다.', invalid_input:'씬 또는 제작 요청을 승인하지 못했습니다.'};
  return reasons[error.code] || error.reason || error.code || '기록된 실패 사유가 없습니다.';
}
function updateSceneProof() {
  const metrics = state.renderer?.metrics;
  if (!metrics) return;
  $('pause-view').textContent = metrics.paused ? '재생' : '일시정지';
  $('pause-view').setAttribute('aria-pressed', String(Boolean(metrics.paused)));
  $('step-view').disabled = !metrics.paused;
  $('scene-info').textContent = `${metrics.node_count || 0}개 배치 · ${metrics.frame_count || 0}프레임 · ${metrics.rendered_model_triangles || 0}삼각형`;
}

function sceneInput(run) {
  const runNode = state.nodes.find(node => node['@id'] === run?.graph_id);
  return state.nodes.find(node => runNode?.used?.includes(node['@id']) && types(node).includes('SceneRevision'))?.snapshot;
}
function runName(run) { return sceneInput(run)?.brief?.title || sceneInput(run)?.id || run.scene_id || '게임 장면'; }
function runRevision(run) { return run.output || run.runtime?.split('/').slice(0,-1).join('/') || `${labels[run.status] || '실행'} · ${time(run.started_at)}`; }
function renderBrief(brief) {
  const panel = $('game-brief'); panel.replaceChildren(); panel.hidden = !brief?.goal && !brief?.controls;
  if (panel.hidden) return;
  panel.append(make('span','brief-label','기록된 게임 기획'));
  fields(panel,[['목표',brief.goal],['조작 의도',brief.controls]]);
}

function pin(path) {
  if (typeof path !== 'string' || path.startsWith('/') || path.split('/').includes('..') || path.includes('\\')) throw Error('프로젝트 상대 경로가 아닙니다.');
  const candidates = state.nodes.filter(node => node.path === path && typeof node.sha256 === 'string' && /^[a-f0-9]{64}$/.test(node.sha256) && node['@id'].startsWith(`${state.project}:`));
  const current = candidates.find(node => node['@id'].startsWith(`${state.run}:`));
  if (current) return current;
  const runtime = state.nodes.find(node => node['@id'] === `${state.run}:runtime`);
  const pinned = candidates.filter(node => runtime?.wasDerivedFrom?.includes(node['@id']));
  if (!pinned.length || new Set(pinned.map(node => node.sha256)).size !== 1) throw Error('이 실행의 그래프에서 파일 해시를 확인할 수 없습니다.');
  return pinned[0];
}
function artifactURL(path) { const node = pin(path); return scopedURL(`/artifact?path=${encodeURIComponent(path)}&sha256=${node.sha256}`); }
function fields(container, entries) { const dl = make('dl', 'properties'); for (const [name, value] of entries) { if (value == null) continue; dl.append(make('dt','',name), make('dd','',typeof value === 'object' ? JSON.stringify(value) : value)); } container.append(dl); }
function switchTab(name) {
  for (const value of ['scene','graph']) { const selected = name === value; $(`tab-${value}`).setAttribute('aria-selected', String(selected)); $(`tab-${value}`).tabIndex = selected ? 0 : -1; $(`panel-${value}`).hidden = !selected; }
  if (name === 'graph') renderGraph();
}
for (const [index, name] of ['scene','graph'].entries()) {
  $(`tab-${name}`).addEventListener('click', () => switchTab(name));
  $(`tab-${name}`).addEventListener('keydown', event => { if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'scene' : event.key === 'End' ? 'graph' : ['scene','graph'][1-index]; switchTab(next); $(`tab-${next}`).focus(); } });
}
function renderRuns() {
  $('run-count').textContent = state.runs.length;
  $('runs').replaceChildren();
  if (!state.runs.length) $('runs').append(make('p','empty-small','아직 제작 기록이 없어요. Codex에서 첫 장면을 만들어 보세요.'));
  for (const run of state.runs) {
    const button = make('button', `run-item${state.run === run.graph_id ? ' selected' : ''}`);
    button.setAttribute('aria-pressed', String(state.run === run.graph_id));
    const top = make('div','run-top'); top.append(badge(run.status), make('time','',time(run.started_at)));
    button.append(top, make('strong','',runRevision(run)), make('span','run-id',runName(run)));
    if (run.status === 'running' && run.live === false) button.append(make('small','stale','실행 프로세스 연결 없음'));
    button.addEventListener('click', () => selectRun(run.graph_id)); $('runs').append(button);
  }
}
function placeholder(heading, description) { $('scene').hidden = true; $('scene-placeholder').hidden = false; $('scene-placeholder').querySelector('h3').textContent = heading; $('scene-placeholder').querySelector('p').textContent = description; }
async function selectRun(id) {
  state.run = id; const epoch = ++state.epoch; ++state.detailVersion; clearInterval(state.proofTimer); state.proofTimer = null;
  state.renderer?.dispose(); state.renderer = null; $('view-controls').hidden = true;
  renderRuns(); const run = activeRun();
  $('artifact-detail').hidden = true; $('scene-action').value=''; $('action-control').hidden=true; state.previews.clear(); $('assets').replaceChildren(); $('steps').replaceChildren(); $('run-message').hidden = true; $('run-message').replaceChildren();
  $('run-status').hidden = !run; renderBrief(run ? sceneInput(run)?.brief : null);
  if (!run) { $('run-title').textContent = '다음 장면을 기다리는 작업실'; $('run-subtitle').textContent = '첫 제작이 시작되면 과정과 결과가 여기에 모입니다.'; placeholder('아직 완성된 장면이 없어요','Codex 채팅에서 제작을 시작하면 여기에 기록됩니다.'); $('asset-count').textContent = '0개'; renderGraph(); return; }
  $('run-title').textContent = runName(run);
  $('run-subtitle').textContent = `${runRevision(run)} · ${time(run.started_at)}`;
  $('run-status').replaceWith(Object.assign(badge(run.status), {id:'run-status'}));
  $('scene-caption').textContent = run.status === 'ready' ? '실제 런타임 장면' : '제작 상태';
  const message = $('run-message');
  if (run.status === 'error') { message.hidden = false; message.className = 'notice error'; message.append(make('strong','','이 실행은 완료되지 않았어요'), make('p','',`${run.error?.stage || '알 수 없는 단계'} · ${failureReason(run.error)}${run.error?.type ? ` · ${run.error.type}` : ''}`)); placeholder('완료되지 않은 장면','아래 단계와 관계 탭에서 기록된 실패 근거를 확인하세요.'); }
  else if (run.status !== 'ready') { message.hidden = false; message.className = 'notice'; message.textContent = run.live === false ? '제작 중으로 기록되어 있지만 실행 프로세스가 연결되어 있지 않습니다.' : '제작 진행 상황을 자동으로 확인하고 있어요.'; placeholder('장면을 만들고 있어요','완료된 에셋과 단계는 아래에서 확인할 수 있어요.'); }
  else placeholder('장면을 불러오는 중','그래프에 고정된 런타임과 에셋을 확인하고 있어요.');
  renderAssets(run); renderSteps(run); renderGraph();
  const hero=run.assets?.find(asset=>asset.producer==='pixel-action-set') || run.assets?.[0];
  if(hero) {const files=Object.entries(hero.files || {});const image=files.find(([role])=>role==='preview') || files.find(([role])=>role==='review') || files.find(([,path])=>/\.(png|gif|webp|jpe?g)$/i.test(path));void showArtifact(hero,image?.[1] || files[0]?.[1],false);}
  if (run.status !== 'ready' || !run.runtime) return;
  try {
    const url = artifactURL(run.runtime); const response = await fetch(url); if (!response.ok) throw Error(`런타임 파일을 읽지 못했습니다 (${response.status}).`);
    const runtime = await response.json(); if (epoch !== state.epoch) return;
    if (runtime.brief?.title) $('run-title').textContent = runtime.brief.title;
    renderBrief(runtime.brief);
    $('scene').hidden = false; $('scene-placeholder').hidden = true;
    const assetURL = path => { if (epoch !== state.epoch) throw Error('선택한 실행이 변경되었습니다.'); return artifactURL(path); };
    const {showScene} = await import('./scene-view.mjs');
    if (epoch !== state.epoch) return;
    const renderer = await showScene($('scene'), runtime, assetURL);
    if (epoch !== state.epoch) { renderer.dispose(); return; }
    state.renderer = renderer;
    $('view-controls').hidden = !renderer.metrics?.inspection;
    $('rotate-view').hidden = !renderer.metrics?.inspection?.rotate;
    const actions=renderer.metrics?.inspection?.actions || [];
    $('scene-action').replaceChildren(Object.assign(make('option','','기록된 동작'),{value:''}),...actions.map(action=>Object.assign(make('option','',({idle:'대기',walk:'걷기',run:'달리기',attack:'공격',jump:'점프',hurt:'피격',death:'쓰러짐'})[action] || action),{value:action})));
    $('action-control').hidden = !actions.length || typeof renderer.setAction!=='function';
    updateSceneProof();
    state.proofTimer = setInterval(updateSceneProof, 500);
    $('scene-info').textContent = `${runtime.nodes?.length || 0}개 배치 · ${runtime.assets?.length || 0}개 에셋`;
    $('scene').setAttribute('aria-label', `${runtime.brief?.title || runtime.id || '게임'} 실제 장면`);
    void renderModelPreviews(runtime, assetURL, epoch, showScene);
  } catch (error) { if (epoch === state.epoch) placeholder('미리보기를 열 수 없어요', `${error.message} 파일이 변경되었거나 누락되었을 수 있어요.`); }
}
function renderSteps(run) {
  $('steps').append(make('h3','','제작 과정'));
  if (!run.steps?.length) { $('steps').append(make('p','muted',run.error?.stage === 'admission' ? '입력 승인 단계에서 중단되어 제작기가 실행되지 않았습니다.' : '기록된 제작 단계가 없습니다.')); return; }
  for (const [index, step] of run.steps.entries()) { const row = make('div','step'); row.append(make('span','step-number',String(index + 1).padStart(2,'0')), make('strong','',step.asset), make('span','muted',step.producer), badge(step.status)); if (step.validation) row.append(make('small','',step.validation.passed ? '계약 검사 통과' : '검사 실패')); $('steps').append(row); }
}
function renderAssets(run) {
  const assets = run.assets || []; $('asset-count').textContent = `${assets.length}개 에셋`;
  if (!assets.length) $('assets').append(make('p','empty-small','아직 납품된 에셋이 없습니다.'));
  for (const asset of assets) {
    const card = make('article','asset-card'); const preview = make('button','asset-preview'); preview.setAttribute('aria-label', `${asset.id} 파일 정보 보기`);
    const files = Object.entries(asset.files || {}); const images = files.filter(([, path]) => /\.(png|gif|webp|jpe?g)$/i.test(path));
    const image = images.find(([role]) => role === 'preview') || images.find(([role]) => role === 'review') || images.find(([role]) => role === 'atlas') || images[0];
    if (image) { try { const img = make('img'); img.src = artifactURL(image[1]); img.alt = `${asset.id} ${image[0] === 'sheet' ? '스프라이트 시트' : '원본 제작 미리보기'}`; if (image[0] !== 'sheet') img.className = asset.producer === 'pixel-action-set' ? 'authored-preview pixel-preview' : 'authored-preview'; img.loading = 'eager'; img.addEventListener('load', () => { const proof = make('span','image-proof',`${img.naturalWidth} × ${img.naturalHeight}`); preview.append(proof); }); img.addEventListener('error', () => { img.remove(); preview.append(make('span','preview-unavailable','이미지 파일을 읽을 수 없어요')); }); preview.append(img); } catch { preview.append(make('span','preview-unavailable','고정된 이미지 없음')); } }
    else { preview.append(make('span','model-glyph','◇'),make('span','preview-format',files.some(([,path])=>/\.glb$/i.test(path)) ? '3D MODEL · GLB' : 'ARTIFACT')); }
    state.previews.set(asset.id, preview);
    preview.addEventListener('click', () => showArtifact(asset, image?.[1] || files[0]?.[1]));
    const body = make('div','asset-body'); body.append(make('h4','',asset.id),make('p','muted',assetKind(asset))); const links = make('div','file-buttons');
    for (const [role,path] of files) { const button = make('button','file-button',role === 'effect' ? '이펙트 레시피' : role); button.addEventListener('click',()=>showArtifact(asset,path)); links.append(button); }
    body.append(links); card.append(preview,body); $('assets').append(card);
  }
}
async function renderModelPreviews(runtime, assetURL, epoch, showScene) {
  for (const asset of runtime.assets.filter(asset => asset.files?.model && !Object.values(asset.files).some(path => /\.(png|gif|webp|jpe?g)$/i.test(path)))) {
    if (epoch !== state.epoch) return;
    const preview = state.previews.get(asset.id);
    const nodes = runtime.nodes.filter(node => node.asset === asset.id);
    if (!preview || !nodes.length) continue;
    const canvas = make('canvas'); canvas.setAttribute('aria-label', `${asset.id} 실제 모델 미리보기`);
    preview.replaceChildren(canvas);
    let renderer;
    try {
      renderer = await showScene(canvas, {...runtime, assets:[asset], nodes}, assetURL);
      if (epoch !== state.epoch) return;
      const img = make('img'); img.src = canvas.toDataURL('image/png'); img.alt = `${asset.id} 실제 GLB 모델`;
      img.className = 'model-thumbnail'; preview.replaceChildren(img);
      if($('artifact-detail').dataset.asset===asset.id) {const dockImage=img.cloneNode();dockImage.className='artifact-image';$('artifact-detail').querySelector('.artifact-image')?.remove();$('artifact-detail').insertBefore(dockImage,$('artifact-detail').querySelector('.properties'));}
    } catch {
      if (epoch === state.epoch) preview.replaceChildren(make('span','preview-unavailable','모델 미리보기를 읽을 수 없어요'));
    } finally { renderer?.dispose(); }
  }
}
async function showArtifact(asset,path,scroll=true) {
  for (const [id, preview] of state.previews) preview.closest('.asset-card')?.classList.toggle('selected', id === asset.id);
  const version = ++state.detailVersion;
  const detail = $('artifact-detail'); detail.hidden = false; detail.dataset.asset=asset.id; detail.replaceChildren(make('h3','',asset.id),make('p','muted',assetKind(asset)));
  try { const node = pin(path); if (/\.(png|gif|webp|jpe?g)$/i.test(path)) { const img = make('img','artifact-image'); img.src = artifactURL(path); img.alt = `${asset.id} · ${path.split('/').pop()}`; detail.append(img); } if(!/\.(png|gif|webp|jpe?g)$/i.test(path)) {const existing=state.previews.get(asset.id)?.querySelector('img');if(existing) {const image=existing.cloneNode();image.className='artifact-image';detail.append(image);}} const placements=sceneInput(activeRun())?.nodes?.filter(item=>item.asset===asset.id) || []; const generators=(Array.isArray(node.wasGeneratedBy)?node.wasGeneratedBy:[node.wasGeneratedBy]).filter(Boolean).map(id=>state.nodes.find(item=>item['@id']===id)).filter(Boolean); fields(detail,[['제작기',asset.producer],['생성 근거',generators.map(title).join(', ') || '파일 기록 참조'],['배치',placements.map(item=>item.id).join(', ') || '없음'],['위치',placements[0]?.position],['크기 배율',placements[0]?.scale],['회전 (도)',placements[0]?.rotation_degrees],['기록된 동작',placements[0]?.action],['에셋',asset.id],['파일 경로',node.path],['SHA-256',node.sha256],['크기',`${node.byteCount ?? '—'} bytes`]]); const button = make('button','text-button','그래프에서 관계 보기 ↗'); button.addEventListener('click',()=>{state.node=node['@id']; switchTab('graph');}); detail.append(button); } catch(error) { detail.append(make('p','',error.message)); }
  if(scroll && matchMedia('(max-width: 700px)').matches) detail.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'nearest'});
  if (asset.producer === 'pixel-action-set' && asset.files?.metadata === path) { await showActionSummary(asset, path, detail, version); return; }
  if (asset.files?.effect !== path || asset.producer !== 'model-assets') return;
  const summary = make('section','effect-summary'); summary.append(make('h4','','3D 이펙트 레시피')); detail.append(summary);
  try {
    const response = await fetch(artifactURL(path));
    if (!response.ok) throw Error(`레시피를 읽지 못했습니다 (${response.status}).`);
    const recipe = await response.json();
    if (version !== state.detailVersion) return;
    if (recipe.schema_version !== 1 || recipe.kind !== 'mesh-particles' || recipe.units !== 'meters' || !Array.isArray(recipe.particles) || !Number.isFinite(recipe.duration_s) || recipe.duration_s <= 0) throw Error('지원하는 3D 이펙트 레시피 형식이 아닙니다.');
    const placements = sceneInput(activeRun())?.nodes?.filter(node => node.asset === asset.id) || [];
    const parents = placements.map(node => node.parent || node.attachedTo).filter(Boolean);
    fields(summary,[['종류','3D 메시 파티클'],['파티클 수',`${recipe.particles.length}개`],['재생 주기',`${recipe.duration_s}초`],['공간 단위','미터'],['부착 대상',parents.length ? parents.join(', ') : '독립 배치']]);
  } catch (error) { if (version === state.detailVersion) summary.append(make('p','muted',error.message)); }
}
async function showActionSummary(asset, path, detail, version) {
  const summary = make('section','effect-summary'); summary.append(make('h4','','캐릭터 동작과 이벤트')); detail.append(summary);
  try {
    const response = await fetch(artifactURL(path));
    if (!response.ok) throw Error(`동작 메타데이터를 읽지 못했습니다 (${response.status}).`);
    const metadata = await response.json();
    if (version !== state.detailVersion) return;
    if (metadata.schema_version !== 1 || !metadata.actions || typeof metadata.actions !== 'object' || Array.isArray(metadata.actions) || !Array.isArray(metadata.events)) throw Error('지원하는 캐릭터 동작 메타데이터가 아닙니다.');
    const placements = sceneInput(activeRun())?.nodes?.filter(node => node.asset === asset.id) || [];
    fields(summary,[['현재 동작',placements.map(node => `${node.id}: ${node.action || 'idle'}`).join(', ') || '배치 없음'],['동작 목록',Object.keys(metadata.actions).join(', ')],['캐릭터 피벗',metadata.pivot_px_from_top_left]]);
    for (const [name, action] of Object.entries(metadata.actions)) fields(summary,[[name,`${action.frames?.length || 0}프레임 · ${action.duration_ms ?? '—'}ms · ${action.loop ? '반복' : '한 번'}`]]);
    summary.append(make('h4','',`이벤트 · ${metadata.events.length}개`));
    for (const event of metadata.events) fields(summary,[['동작',event.action],['frame',event.frame],['start_ms',event.start_ms],['at_px',event.at_px],['effect_anchor_px',event.effect_anchor_px]]);
  } catch (error) { if (version === state.detailVersion) summary.append(make('p','muted',error.message)); }
}
function graphButton(node, subtitle) { const button=make('button','node-button'); button.append(make('small','node-kind',kindNames[kind(node)] || kind(node)),make('strong','',title(node))); if(subtitle) button.append(make('small','node-path',subtitle)); button.addEventListener('click',()=>{state.node=node['@id'];renderGraph();}); return button; }
function renderGraph() {
  $('graph-count').textContent = state.nodes.length;
  const existing = $('graph-type').value; const allTypes = [...new Set(state.nodes.map(kind))].sort();
  $('graph-type').replaceChildren(Object.assign(make('option','','모든 종류'),{value:''}),...allTypes.map(type=>Object.assign(make('option','',kindNames[type] || type),{value:type}))); $('graph-type').value = existing;
  const search = $('graph-search').value.trim().toLocaleLowerCase(); const type = $('graph-type').value;
  const filtered = state.nodes.filter(node => (!type || kind(node) === type) && `${title(node)} ${node.path || ''} ${node['@id']}`.toLocaleLowerCase().includes(search));
  if (!state.nodes.some(node => node['@id'] === state.node)) state.node = (state.nodes.find(node => node['@id'] === state.run) || filtered[0])?.['@id'];
  $('graph-nodes').replaceChildren();
  for (const node of filtered) { const button=graphButton(node,node.path || node.status); button.classList.toggle('selected',node['@id']===state.node); button.setAttribute('aria-pressed',String(node['@id']===state.node)); $('graph-nodes').append(button); }
  $('graph-results').textContent = `${filtered.length} / ${state.nodes.length}개 항목`;
  if (!filtered.length) $('graph-nodes').append(make('p','empty-small','일치하는 항목이 없습니다.'));
  let selected = state.nodes.find(node=>node['@id']===state.node);
  if (!selected) { selected=state.nodes.find(node=>node['@id']===state.run) || filtered[0]; state.node=selected?.['@id']; }
  $('graph-map').replaceChildren(); $('graph-summary').replaceChildren(); $('relations').replaceChildren(); $('graph-raw').textContent='';
  if (!selected) { $('graph-summary').append(make('p','muted','아직 그래프에 기록된 항목이 없습니다.')); return; }
  $('graph-summary').append(make('p','eyebrow',kindNames[kind(selected)] || kind(selected)),make('h3','',title(selected)));
  fields($('graph-summary'),[['파일',selected.path],['역할',selected.role],['상태',selected.status],['SHA-256',selected.sha256],['근거',selected.evidenceBasis],['검증 결과',selected.verification],['관측 시각',selected.recordedAt],['실패 단계',selected.snapshot?.stage],['오류',kind(selected) === 'Error' ? failureReason(selected.snapshot) : selected.snapshot?.code],['오류 종류',selected.snapshot?.type],['ID',selected['@id']]]);
  const byId = new Map(state.nodes.map(node=>[node['@id'],node]));
  const edges=[]; const context = state.context || {};
  for(const node of state.nodes) for(const [key,value] of Object.entries(node)) {
    if (!(context[key]?.['@type']==='@id' || Object.hasOwn(relations,key))) continue;
    for(const ref of Array.isArray(value)?value:[value]) { const target=typeof ref==='string'?ref:ref?.['@id']; if(byId.has(target)) edges.push({from:node['@id'],to:target,key}); }
  }
  renderGraphMap(selected, edges, byId);
  for(const incoming of [true,false]) {
    const group=make('section','relation-group'); const related=edges.filter(edge=>(incoming?edge.to===state.node:edge.from===state.node) && ($('revision-disclosure').open || ![edge.from,edge.to].some(id=>kind(byId.get(id))==='RunRevision')));
    group.append(make('h4','',`${incoming?'들어오는 관계':'나가는 관계'} · ${related.length}`));
    if(!related.length) group.append(make('p','muted','기록된 관계 없음'));
    for(const edge of related) { const row=make('div','relation-row'); row.append(make('span','edge-label',`${incoming?'←':'→'} ${relations[edge.key] || edge.key}`),graphButton(byId.get(incoming?edge.from:edge.to),edge.key)); group.append(row); }
    $('relations').append(group);
  }
  $('graph-raw').textContent=JSON.stringify(selected,null,2);
}
$('graph-search').addEventListener('input',renderGraph); $('graph-type').addEventListener('change',renderGraph);
function renderGraphMap(selected, edges, byId) {
  const allConnected = edges.filter(edge => edge.from === selected['@id'] || edge.to === selected['@id']);
  const revisions=allConnected.filter(edge=>[edge.from,edge.to].some(id=>kind(byId.get(id))==='RunRevision'));
  $('revision-disclosure').hidden=!revisions.length; $('revision-summary').textContent=`상태 기록 연결 ${revisions.length}개 포함하기`;
  const priority=edge=>['RuntimeProduct','SceneRevision','Artifact','WorkStep','ScenePlacement'].indexOf(kind(byId.get(edge.from===selected['@id']?edge.to:edge.from)));
  const connected=allConnected.filter(edge=>$('revision-disclosure').open || !revisions.includes(edge)).sort((a,b)=>(priority(a)<0?99:priority(a))-(priority(b)<0?99:priority(b)));
  const incoming = connected.filter(edge => edge.to === selected['@id']).slice(0,4);
  const outgoing = connected.filter(edge => edge.from === selected['@id']).slice(0,4);
  const rows = Math.max(incoming.length, outgoing.length, 1);
  const height = Math.max(210, rows * 74 + 52);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 1000 ${height}`);
  svg.setAttribute('role', 'group'); svg.setAttribute('aria-label', `${title(selected)}의 연결 ${connected.length}개`);
  const element = (tag, attrs, text) => { const item = document.createElementNS(svg.namespaceURI, tag); for(const [key,value] of Object.entries(attrs)) item.setAttribute(key,value); if(text != null) item.textContent=text; return item; };
  const middle = height / 2;
  function nodeBox(node,x,y,active=false) {
    const group = element('g', {class:`graph-node${active?' selected':''}`,transform:`translate(${x} ${y})`,role:'button',tabindex:'0','aria-label':`${kindNames[kind(node)] || kind(node)}: ${title(node)}`});
    const fullTitle=title(node); group.append(element('title',{},fullTitle),element('rect',{width:240,height:54}),element('text',{x:13,y:19,class:'map-kind'},kindNames[kind(node)] || kind(node)),element('text',{x:13,y:39},fullTitle.length>23?`${fullTitle.slice(0,22)}…`:fullTitle));
    const activate=()=>{state.node=node['@id'];renderGraph();}; group.addEventListener('click',activate); group.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();activate();}}); return group;
  }
  if(matchMedia('(max-width: 700px)').matches) {
    svg.setAttribute('viewBox','0 0 360 300');
    const items=[incoming[0],outgoing[0]].filter(Boolean);
    for(const [index,edge] of [[0,incoming[0]],[1,outgoing[0]]]) {
      if(!edge) continue;
      const from=index===0?72:166,to=index===0?112:206;
      svg.append(element('path',{class:'graph-edge',d:`M 180 ${from} L 180 ${to}`}));
      svg.append(element('text',{class:'graph-edge-label',x:190,y:(from+to)/2},`${relations[edge.key] || edge.key} ↓`));
      svg.append(nodeBox(byId.get(index===0?edge.from:edge.to),60,index===0?18:206));
    }
    svg.append(nodeBox(selected,60,112,true)); $('graph-map').append(svg);
    if(allConnected.length>items.length) $('graph-map').append(make('p','graph-map-note',`주요 연결 ${items.length}개 · 전체 ${allConnected.length}개 관계는 아래에서 확인`));
    return;
  }
  for (const [isIncoming, items] of [[true,incoming],[false,outgoing]]) {
    items.forEach((edge,index)=>{
      const y=26+index*74+Math.max(0,(height-52-items.length*74)/2), fromX=isIncoming?260:620, toX=isIncoming?380:740;
      const fromY=isIncoming?y+27:middle, toY=isIncoming?middle:y+27;
      svg.append(element('path',{class:'graph-edge',d:`M ${fromX} ${fromY} C ${(fromX+toX)/2} ${fromY}, ${(fromX+toX)/2} ${toY}, ${toX} ${toY}`}));
      svg.append(element('text',{class:'graph-edge-label',x:(fromX+toX)/2,y:y+18,'text-anchor':'middle'},`${relations[edge.key] || edge.key} →`));
      svg.append(nodeBox(byId.get(isIncoming?edge.from:edge.to),isIncoming?20:740,y));
    });
  }
  svg.append(nodeBox(selected,380,middle-27,true)); $('graph-map').append(svg);
  if(connected.length>incoming.length+outgoing.length) $('graph-map').append(make('p','graph-map-note',`주요 연결 ${incoming.length+outgoing.length}개 표시 · 전체 ${allConnected.length}개 관계는 아래에서 확인`));
  if(!connected.length) $('graph-map').append(make('p','empty-small','이 항목에 기록된 연결이 없습니다.'));
}
async function refresh() {
  if(state.refreshing) return;
  state.refreshing=true;
  try {
    const response=await fetch(scopedURL('/api/state'),{cache:'no-cache',headers:state.etag?{'If-None-Match':state.etag}:{}});
    if(response.status===304) { $('connection').textContent='프로젝트에 연결됨'; document.body.classList.remove('offline'); return; }
    if(!response.ok) throw Error(`HTTP ${response.status}`); const data=await response.json();
    if(!Array.isArray(data.runs)||!Array.isArray(data.graph?.['@graph'])) throw Error('상태 응답 형식 오류');
    state.etag=response.headers.get('ETag') || '';
    const signature=JSON.stringify(data); $('connection').textContent='프로젝트에 연결됨'; document.body.classList.remove('offline');
    if(signature===state.signature) return;
    const previousRun=activeRun(); const previousProjection=JSON.stringify(previousRun); state.signature=signature; state.runs=data.runs; state.nodes=data.graph['@graph']; state.context=data.graph['@context']; state.project=data.project_id;
    $('project-name').textContent=data.project_name || '제작 관찰실';
    const projects=Array.isArray(data.projects) ? data.projects : [];
    const browsing=projects.length>1; $('project-picker').hidden=!browsing; $('project-name').hidden=browsing;
    if(browsing) { $('project-picker').replaceChildren(...projects.map(project=>Object.assign(make('option','',project.name),{value:project.id}))); $('project-picker').value=data.project_id; }
    const activities=data.activities || []; $('activity-section').hidden=!activities.length; $('activities').replaceChildren();
    for(const activity of activities) {const button=make('button','activity-item'); button.append(make('strong','',activity.label), make('small','',`${labels[activity.status] || activity.status || '기록'} · ${time(activity.recorded_at)}`)); button.addEventListener('click',()=>{state.node=activity.graph_id;switchTab('graph');}); $('activities').append(button);}
    if(!state.run||!state.runs.some(run=>run.graph_id===state.run)) state.run=(state.runs.find(run=>run.status==='ready')||state.runs[0])?.graph_id || null;
    if(!previousRun||JSON.stringify(activeRun())!==previousProjection) await selectRun(state.run); else { renderRuns();renderGraph(); }
  } catch(error) { $('connection').textContent='연결을 확인 중'; document.body.classList.add('offline'); if(!state.signature) { $('run-title').textContent='작업실에 연결할 수 없어요'; placeholder('기록을 읽지 못했어요',error.message); } }
  finally {state.refreshing=false;}
}
$('project-picker').addEventListener('change',()=>location.assign(`/?project=${encodeURIComponent($('project-picker').value)}`));
$('toggle-history').addEventListener('click',()=>{const open=document.querySelector('.sidebar').classList.toggle('history-open');$('toggle-history').setAttribute('aria-expanded',String(open));$('toggle-history').textContent=open?'이력 접기':'이력 펼치기';});
$('revision-disclosure').addEventListener('toggle',renderGraph);
$('scene-action').addEventListener('change',()=>{const action=$('scene-action').value;const allowed=state.renderer?.metrics?.inspection?.actions || [];if(action && !allowed.includes(action)) return;state.renderer?.setAction(action || null);$('scene-caption').textContent=action?`동작 미리보기 · ${action} · 기록 유지`:'실제 런타임 장면';updateSceneProof();});
$('pause-view').addEventListener('click',()=>{state.renderer?.setPaused(!state.renderer.metrics.paused);updateSceneProof();});
$('step-view').addEventListener('click',()=>{state.renderer?.seek((state.renderer.metrics.elapsed_ms || 0)+100);updateSceneProof();});
$('rotate-view').addEventListener('click',()=>state.renderer?.rotate(Math.PI/8));
$('zoom-in').addEventListener('click',()=>state.renderer?.zoom(1.15));
$('zoom-out').addEventListener('click',()=>state.renderer?.zoom(1/1.15));
$('reset-view').addEventListener('click',()=>state.renderer?.resetView());
await refresh(); const refreshTimer=setInterval(refresh,4000);
matchMedia('(max-width: 700px)').addEventListener('change',()=>{if($('tab-graph').getAttribute('aria-selected')==='true') renderGraph();});
window.addEventListener('pagehide',()=>{clearInterval(refreshTimer);clearInterval(state.proofTimer);state.renderer?.dispose();});
