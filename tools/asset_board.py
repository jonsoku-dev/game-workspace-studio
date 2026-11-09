"""Self-contained visual comparison from admitted project bytes, never filesystem inputs."""
import base64
import io
import json
from pathlib import Path

from PIL import Image
from combat_quality import jobs_for, runtime_actors


def _module(sources, name, prefix):
    raw = sources[name]
    if len(raw) > 2_097_152:
        raise ValueError('메타데이터 크기 초과')
    text = raw.decode('utf-8').strip()
    if not text.startswith(prefix) or not text.endswith(';'):
        raise ValueError('생성된 JSON 모듈이 아님')
    return json.loads(text[len(prefix):-1])


def _picture(sources, name):
    data = sources[name]
    if len(data) > 16_777_216:
        raise ValueError('이미지 바이트 예산 초과')
    with Image.open(io.BytesIO(data), formats=['PNG', 'WEBP', 'JPEG']) as image:
        if getattr(image, 'is_animated', False) or image.width * image.height > 16_777_216:
            raise ValueError('이미지 픽셀 예산 초과')
        image.load()
        mime = Image.MIME[image.format]
        size = image.size
    return {'url': 'data:' + mime + ';base64,' + base64.b64encode(data).decode(), 'size': size}


def _frames(frames, size):
    if not isinstance(frames, list) or not 1 <= len(frames) <= 64:
        raise ValueError('프레임은 1..64개 필요')
    for f in frames:
        if (not isinstance(f, dict) or any(type(f.get(k)) is not int for k in ('x', 'y', 'w', 'h', 'ms'))
                or not 0 <= f['x'] < f['x'] + f['w'] <= size[0]
                or not 0 <= f['y'] < f['y'] + f['h'] <= size[1]
                or not 1 <= f['ms'] <= 60000):
            raise ValueError('프레임 영역 또는 노출 시간 오류')
    return frames


def _pivot(value, frames):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(n) is not int or not 0 <= n <= min(f[k] for f in frames)
                   for n, k in zip(value, ('w', 'h')))):
        raise ValueError('공통 피벗 오류')
    return value


def _project(sources):
    result = {'title': '제목 없음', 'actors': [], 'portraits': [], 'signatures': [], 'errors': [], 'background': None}
    try:
        result['title'] = str(json.loads(sources['genre.json']).get('title', '제목 없음'))
    except (RecursionError, KeyError, ValueError, TypeError, AttributeError):
        result['errors'].append('genre.json 제목을 읽지 못함')
    try:
        result['background'] = _picture(sources, 'game/art/bell-tower.jpg')
    except (RecursionError, KeyError, ValueError, OSError, Image.DecompressionBombError):
        result['errors'].append('게임 배경 없음 또는 손상. 단색 대비만 확인 가능')
    try:
        jobs = jobs_for(sources)
    except (RecursionError, KeyError, ValueError, UnicodeError, TypeError):
        jobs = {}
        result['errors'].append('직업 목록을 읽지 못함. 생성된 jobs.mjs와 기본 combat-fx.mjs를 복구하세요')
    try:
        recovery = _module(sources, 'game/timing.mjs', 'export const RECOVERY_MS = ')
        motifs = _module(sources, 'game/motif-ms.mjs', 'export const MOTIF_MS = ')
    except (RecursionError, KeyError, ValueError, UnicodeError):
        recovery, motifs = {}, {}
        result['errors'].append('런타임 단계 시간 없음. 해당 동작은 재생하지 않음')
    for key, job in jobs.items():
        try:
            if not isinstance(job, dict):
                raise ValueError('직업 정의 오류')
            kind = job.get('actor', job.get('motif'))
            name = str(job.get('name', key))
            try:
                sheet = job.get('sheet', './fx/' + {'blade': 'sword', 'brawler': 'fist', 'astral': 'star', 'rail': 'gun'}[job['motif']] + '.webp')
                signature = _picture(sources, 'game/' + sheet.removeprefix('./'))
                if signature['size'][0] % 3 or signature['size'][1] % 2:
                    raise ValueError('3×2 시트 아님')
                result['signatures'].append({'name': name, 'job':key, 'picture': signature})
            except (RecursionError, KeyError, ValueError, OSError, Image.DecompressionBombError, AttributeError):
                result['errors'].append(name + ' 시그니처 시트 없음 또는 손상. 3×2 원화 시트를 복구하세요')
            portrait = 'game/art/' + str(kind) + '-idle.webp'
            try:
                result['portraits'].append({'name': name, 'picture': _picture(sources, portrait)})
            except (RecursionError, KeyError, ValueError, OSError, Image.DecompressionBombError):
                result['errors'].append(name + ' 초상 없음 또는 손상')
            actor = runtime_actors(sources)[kind]
            picture = _picture(sources, 'game/motion/' + actor['image'])
            frames = _frames(actor['frames'], picture['size'])
            pivot = _pivot(actor['pivot'], frames)
            height = actor['bodyHeight']
            if type(height) not in (int, float) or not 1 <= height <= 512:
                raise ValueError('몸높이 오류')
            phases = []
            timing = motifs[job['motif']]['heavy']
            clip = job.get('clip')
            effect = None
            if clip:
                fx_picture = _picture(sources, 'game/' + clip['image'].removeprefix('./'))
                fx_phases = {p: _frames(clip['phases'][p], fx_picture['size']) for p in ('charge', 'travel', 'impact')}
                fx_pivot = _pivot(clip['pivot'], sum(fx_phases.values(), []))
                timing = [sum(f['ms'] for f in fx_phases[p]) for p in ('charge', 'travel', 'impact')]
                effect = {'picture': fx_picture, 'pivot': fx_pivot, 'phases': fx_phases, 'clip': True}
            else:
                try:
                    fx = job.get('impact') or _module(sources, 'game/fx/manifest.mjs', 'export default ')['impact']
                    fx_picture = _picture(sources, 'game/' + fx['image'].removeprefix('./'))
                    fx_frames = _frames(fx['frames'], fx_picture['size'])
                    effect = {'picture': fx_picture, 'pivot': _pivot(fx['pivot'], fx_frames), 'phases': {'impact': fx_frames}, 'clip': False}
                except (RecursionError, KeyError, ValueError, OSError, Image.DecompressionBombError):
                    result['errors'].append(name + ' 접촉 FX 없음 또는 손상')
            durations = [timing[0], timing[1], recovery['follow'], recovery['recover']]
            if any(type(n) is not int or not 1 <= n <= 60000 for n in durations + [timing[2]]):
                raise ValueError('단계 시간 오류')
            for state, duration in zip(('heavy', 'release', 'follow', 'recover'), durations):
                seq = actor['actions'][state]
                if (not isinstance(seq, list) or not 1 <= len(seq) <= 64
                        or any(type(i) is not int or not 0 <= i < len(frames) for i in seq)):
                    raise ValueError('동작 프레임 인덱스 오류')
                ms = actor.get('action_ms', {}).get(state, [frames[i]['ms'] for i in seq])
                if (not isinstance(ms, list) or len(ms) != len(seq)
                        or any(type(n) is not int or not 1 <= n <= 60000 for n in ms)):
                    raise ValueError('action_ms 오류')
                phases.append({'state': state, 'duration': duration, 'frames': [frames[i] for i in seq], 'ms': ms})
            extra_actions = {}
            for state in ('idle', 'move', 'hurt'):
                sequence = actor['actions'].get(state)
                if (not isinstance(sequence, list) or not sequence
                        or any(type(i) is not int or not 0 <= i < len(frames) for i in sequence)):
                    result['errors'].append(name + ' ' + state + ' 동작 없음. 원화와 actions 연결을 복구하세요')
                    continue
                ms = actor.get('action_ms', {}).get(state, [frames[i]['ms'] for i in sequence])
                if (not isinstance(ms, list) or len(ms) != len(sequence)
                        or any(type(n) is not int or not 1 <= n <= 60000 for n in ms)):
                    result['errors'].append(name + ' ' + state + ' 노출 시간 오류. action_ms를 수선하세요')
                    continue
                extra_actions[state] = {'frames': [frames[i] for i in sequence], 'ms': ms}
            result['actors'].append({'extraActions': extra_actions, 'job':key, 'name': name, 'kind': kind, 'picture': picture, 'pivot': pivot,
                                     'bodyHeight': height, 'phases': phases, 'effect': effect, 'impactMs': timing[2], 'motif': job['motif']})
        except (RecursionError, KeyError, ValueError, TypeError, AttributeError, IndexError, OSError, Image.DecompressionBombError) as error:
            result['errors'].append(str(key) + ' 재생 불가 (' + type(error).__name__ + '). 원화 시트·프레임 경계·단계 시간·공통 피벗을 복구하고 다시 컴파일하세요')
    return result


def write_board(output, sources, report, reference_sources):
    """Write one offline HTML file. Inputs are pinned {relative_name: bytes} mappings.

    report is displayed as text only and needs no private scoring/metric fields.
    The caller supplies a canonical initialized reference project by the same contract.
    Returns the output Path; does not read assets from disk or mutate input mappings.
    """
    payload = {'project': _project(sources), 'reference': _project(reference_sources), 'report': report}
    # Store identical sheets once when classes or reference panels share their art.
    table = {}
    ids = {}
    def intern(item):
        if isinstance(item, dict):
            url=item.get('url')
            if isinstance(url,str) and url.startswith('data:image/'):
                if url not in ids:
                    key=str(len(ids))
                    ids[url]=key
                    table[key]=url
                item['image_id']=ids[url]
                del item['url']
            for child in item.values():
                intern(child)
        elif isinstance(item,list):
            for child in item:
                intern(child)
    intern(payload['project']); intern(payload['reference'])
    payload['images']=table
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    output = Path(output)
    output.write_text(_HTML.replace('__PAYLOAD__', encoded), encoding='utf-8')
    return output


_HTML = r'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'">
<title>전투 에셋 비교</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#111b23;color:#e9eff1;font:15px/1.6 system-ui,sans-serif}main{max-width:1440px;margin:auto;padding:24px}h1{font-size:28px}h2{font-size:21px}p{max-width:1000px}button,select,input{font:inherit}button,select{min-height:44px;background:#253946;color:#fff;border:1px solid #8da5af;border-radius:5px;padding:6px 12px}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #f7cb76;outline-offset:3px}.controls{display:flex;flex-wrap:wrap;align-items:center;gap:14px;position:sticky;top:0;background:#111b23;z-index:1;padding:12px 0}.columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.pane{min-width:0;border:1px solid #3a535f;padding:16px}.viewport{overflow:auto;border:1px solid #59717b}canvas{display:block;width:640px;height:360px}.portraits{display:flex;flex-wrap:wrap;gap:12px}.portraits figure{margin:0;width:150px}.portraits img{width:150px;height:116px;object-fit:contain;background:#29414e}figcaption,small{font-size:12px;color:#bacbd0}.error{color:#ffc997;white-space:pre-wrap}.exposures{display:flex;gap:12px;overflow:auto;margin-top:16px}.exposures figure{margin:0;flex:0 0 180px}.exposures canvas{width:180px;height:190px}.exposures figcaption{max-width:180px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1c2c35;padding:16px}.status{color:#f7cb76}input[type=range]{width:min(430px,60vw)}@media(max-width:1000px){.columns{grid-template-columns:1fr}main{padding:12px}.controls{position:static}}
</style>
<main><h1>전투 에셋 비교</h1>
<p>두 캐릭터를 같은 발선과 전투 크기(몸높이 248px)에 놓았습니다. 재생하거나 진행 바를 움직여 준비 자세와 명중 순간을 비교하세요.</p>
<section id="verdict" aria-live="polite"></section>
<div class="controls"><button id="play" aria-pressed="false">재생</button><button id="reset">처음</button><label>동작 <select id="mode"><option value="attack">강공격</option><option value="move">이동</option><option value="hurt">피격</option><option value="idle">대기</option></select></label><label>속도 <select id="speed"><option value="1">1× 실제 시간</option><option value="0.25">0.25× 느리게</option></select></label><label>배경 <select id="background"><option value="game">실제 게임 배경</option><option value="#162631">어두운 대비</option><option value="#b1b9b4">밝은 대비</option><option value="#755c6b">중간 대비</option></select></label><label>진행 <input id="seek" type="range" min="0" max="1" step="0.001" value="0"></label><output id="clock">0 ms</output></div>
<div class="columns" id="columns"></div>
<details><summary>기술 검사 보고서와 원본 해시</summary><pre id="report"></pre></details>
<p>여기서는 원화와 명중 클립을 분리해 봅니다. 실제 게임에서 카메라·히트스톱·모션 감소·배경 위 판독성도 확인하세요.</p></main>
<script id="data" type="application/json">__PAYLOAD__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent);
function hydrate(node){
 if(!node||typeof node!=='object')return;
 if(Object.hasOwn(node,'image_id'))node.url=data.images[node.image_id];
 else for(const child of Object.values(node))hydrate(child);
}
hydrate(data.project);hydrate(data.reference);
const el=(tag,text,parent)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;};
const pictures=new Map();
function picture(spec){if(!spec)return null;if(!pictures.has(spec.url)){const im=new Image();im.onload=()=>draw();im.onerror=()=>{im.dataset.failed='true';};im.src=spec.url;pictures.set(spec.url,im);}const im=pictures.get(spec.url);return im.complete&&im.naturalWidth?im:null;}
function sprite(ctx,spec,f,pivot,x,y,scale){const im=picture(spec);if(im)ctx.drawImage(im,f.x,f.y,f.w,f.h,x-pivot[0]*scale,y-pivot[1]*scale,f.w*scale,f.h*scale);else{ctx.fillStyle='#ffca9e';ctx.fillText('이미지 로딩 중 또는 실패',12,28);}}
function exposure(frames,ms,progress){let t=Math.max(0,Math.min(1,progress))*ms.reduce((a,b)=>a+b,0);for(let i=0;i<frames.length;i++){if(t<ms[i])return frames[i];t-=ms[i];}return frames.at(-1);}
function duration(actor){const mode=document.getElementById('mode').value;if(mode!=='attack'){const action=actor.extraActions[mode];return mode==='hurt'?300:Math.max(1000,action?.ms.reduce((a,b)=>a+b,0)||1000);}return Math.max(actor.phases.reduce((n,p)=>n+p.duration,0),actor.phases[0].duration+actor.phases[1].duration+actor.impactMs);}
const panes=[];
for(const [key,label] of [['project','현재 프로젝트'],['reference','공명기사 기준']]){
 const source=data[key],root=el('section',undefined,document.getElementById('columns'));root.className='pane';el('h2',label,root);el('p',source.title,root);
 const portraits=el('div',undefined,root);portraits.className='portraits';for(const p of source.portraits){const f=el('figure',undefined,portraits),im=el('img',undefined,f);im.alt=p.name+' 초상';im.src=p.picture.url;im.onerror=()=>{im.alt+=' 이미지 실패';};el('figcaption',p.name+' · 선택 카드 150 × 116px',f);}
 const signatureHeading=el('h3','시그니처 원화 3×2 전체 노출',root);
 const signatures=el('div',undefined,root);signatures.className='exposures';
 for(const sheet of source.signatures){for(let i=0;i<6;i++){const fig=el('figure',undefined,signatures),c=el('canvas',undefined,fig);c.width=180;c.height=190;c.setAttribute('role','img');c.setAttribute('aria-label',sheet.name+' 시그니처 원화 '+i);el('figcaption',sheet.name+' · 원화 #'+i+' (준비 0 / 이동 1 / 접촉 2..5)',fig);fig._draw=()=>{const ctx=c.getContext('2d');ctx.fillStyle='#29414e';ctx.fillRect(0,0,180,190);const w=sheet.picture.size[0]/3,h=sheet.picture.size[1]/2; sprite(ctx,sheet.picture,{x:i%3*w,y:Math.floor(i/3)*h,w,h},[w/2,h/2],90,95,Math.min(180/w,190/h));};}}
 const select=el('select',undefined,root);select.setAttribute('aria-label',label+' 동작 선택');source.actors.forEach((a,i)=>{const o=el('option',a.name+' / '+a.kind,select);o.value=String(i);});
 const viewport=el('div',undefined,root);viewport.className='viewport';viewport.tabIndex=0;viewport.setAttribute('aria-label',label+' 실제 크기 그림. 가로 스크롤 가능');const canvas=el('canvas',undefined,viewport);canvas.width=640;canvas.height=360;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',label+' 발 선 고정 전투 동작과 FX');
 const status=el('p',undefined,root);const strips=el('div',undefined,root);strips.className='exposures';
 el('p','단계별 모든 노출. 아래 표본은 0.5× 확대율이며 위 플레이어는 실제 크기입니다.',root);
 for(const error of source.errors)el('p',error,root).className='error';
 if(!source.actors.length)el('p','재생 가능한 자산 없음. 보고서의 원본 수선 항목을 확인하세요.',root).className='error';
 root.append(el('h3','초상 / 선택 카드'),portraits,signatureHeading,signatures);
 const pane={source,select,canvas,status,strips,signatures};panes.push(pane);select.onchange=()=>{buildStrip(pane);draw();};buildStrip(pane);
}
function buildStrip(pane){pane.strips.replaceChildren();const a=pane.source.actors[Number(pane.select.value)];if(!a)return;
 for(const p of a.phases){const total=p.ms.reduce((x,y)=>x+y,0);p.frames.forEach((f,i)=>{const fig=el('figure',undefined,pane.strips),c=el('canvas',undefined,fig);c.width=180;c.height=190;c.setAttribute('role','img');c.setAttribute('aria-label',a.name+' '+p.state+' 노출 '+i);el('figcaption',p.state+' #'+i+' · 원본 '+p.ms[i]+'ms / 게임 '+(p.duration*p.ms[i]/total).toFixed(1)+'ms',fig);fig._draw=()=>{const ctx=c.getContext('2d');ctx.fillStyle='#29414e';ctx.fillRect(0,0,180,190);ctx.strokeStyle='#f5cb7b';ctx.beginPath();ctx.moveTo(0,165);ctx.lineTo(180,165);ctx.stroke();sprite(ctx,a.picture,f,a.pivot,90,165,124/a.bodyHeight);};});}
 if(a.effect)for(const [phase,frames]of Object.entries(a.effect.phases))for(const [i,f]of frames.entries()){const fig=el('figure',undefined,pane.strips),c=el('canvas',undefined,fig);c.width=180;c.height=190;c.setAttribute('role','img');c.setAttribute('aria-label',phase+' FX 노출 '+i);el('figcaption','FX '+phase+' #'+i+' · '+f.ms+'ms',fig);fig._draw=()=>{const ctx=c.getContext('2d');ctx.fillStyle='#29414e';ctx.fillRect(0,0,180,190);sprite(ctx,a.effect.picture,f,a.effect.pivot,90,95,.5);};}
}
let elapsed=0,playing=false,previous=0;
const play=document.getElementById('play'),seek=document.getElementById('seek');
function maxDuration(){return Math.max(1,...panes.map(p=>{const a=p.source.actors[Number(p.select.value)];return a?duration(a):0;}));}
function draw(){const max=maxDuration();elapsed=Math.min(elapsed,max);seek.value=String(elapsed/max);document.getElementById('clock').textContent=Math.round(elapsed)+' ms / '+max+' ms';
 for(const pane of panes){const ctx=pane.canvas.getContext('2d'),a=pane.source.actors[Number(pane.select.value)],bg=document.getElementById('background').value;ctx.fillStyle=bg==='game'?'#29414e':bg;ctx.fillRect(0,0,640,360);
 if(bg==='game'){const im=picture(pane.source.background);if(im){const scale=Math.max(1280/im.width,620/im.height);ctx.drawImage(im,(1280-im.width*scale)/2-320,(620-im.height*scale)/2-230,im.width*scale,im.height*scale);const shade=ctx.createLinearGradient(0,-230,0,390);shade.addColorStop(0,'#08131b92');shade.addColorStop(.55,'#18333d15');shade.addColorStop(1,'#0718209c');ctx.fillStyle=shade;ctx.fillRect(0,0,640,360);}}
 ctx.strokeStyle='#f5cb7b';ctx.beginPath();ctx.moveTo(0,310);ctx.lineTo(640,310);ctx.stroke();ctx.fillStyle='#fff';ctx.font='12px system-ui';ctx.fillText('발 피벗 / 실제 몸높이 248px',12,344);
 for(const fig of pane.signatures.children)if(fig._draw)fig._draw();
 if(!a)continue;const mode=document.getElementById('mode').value;
 if(mode!=='attack'){const action=a.extraActions[mode];if(action){const total=action.ms.reduce((n,ms)=>n+ms,0),p=mode==='hurt'?Math.min(1,elapsed/300):(elapsed%total)/total;sprite(ctx,a.picture,exposure(action.frames,action.ms,p),a.pivot,200,310,248/a.bodyHeight);pane.status.textContent=mode+' · '+(mode==='hurt'?'게임 300ms':total+'ms 원화 노출 주기');}else pane.status.textContent=mode+' 동작 없음. actions와 원화를 수선하세요';for(const fig of pane.strips.children)if(fig._draw)fig._draw();continue;}
 let t=elapsed,state=a.phases.at(-1),progress=1;for(const p of a.phases){if(t<p.duration){state=p;progress=t/p.duration;break;}t-=p.duration;}
 sprite(ctx,a.picture,exposure(state.frames,state.ms,progress),a.pivot,200,310,248/a.bodyHeight);
 const charge=a.phases[0].duration,travel=a.phases[1].duration,contact=charge+travel,fx=a.effect;let phase=elapsed<charge?'charge':elapsed<contact?'travel':'impact';
 const signature=pane.source.signatures.find(sheet=>sheet.job===a.job);
 if(signature&&elapsed<contact+a.impactMs){
   const image=signature.picture,w=image.size[0]/3,h=image.size[1]/2;
   const impact=Math.max(0,(elapsed-contact)/a.impactMs),i=elapsed<charge?0:elapsed<contact?1:Math.min(5,2+Math.floor(impact*4));
   const x=phase==='charge'?200:phase==='travel'?200+250*(elapsed-charge)/travel:450;
   const width=phase==='charge'?104:phase==='travel'?165:380;
   ctx.save();ctx.globalAlpha=(phase==='impact'?1-impact*.65:.9)*(fx?.clip ? .42 : 1);
   sprite(ctx,image,{x:i%3*w,y:Math.floor(i/3)*h,w,h},[w/2,h/2],x,190,width/w);ctx.restore();
 }
 if(fx&&elapsed<contact+a.impactMs&&fx.phases[phase]){const frames=fx.phases[phase],start=phase==='charge'?0:phase==='travel'?charge:contact,ms=phase==='charge'?charge:phase==='travel'?travel:a.impactMs,p=Math.max(0,Math.min(1,(elapsed-start)/ms));let x=phase==='impact'?450:200,y=190;if(phase==='travel'){x=200+250*p;if(a.motif==='blade')y-=Math.sin(p*Math.PI)*52;if(a.motif==='brawler')y+=Math.sin(p*Math.PI)*22;if(a.motif==='astral'){const summon=Math.min(1,p/.32),fall=Math.max(0,(p-.32)/.68);x=200+250*summon;y=130-170*summon+fall*fall*230;}}
 const width=phase==='charge'?190:phase==='travel'?270:420,scale=fx.clip?width/Math.max(...Object.values(fx.phases).flat().map(f=>f.w)):.95;ctx.save();ctx.globalAlpha=fx.clip?(phase==='impact'?1-p*.65:.95):1-p;sprite(ctx,fx.picture,exposure(frames,frames.map(f=>f.ms),fx.clip?p:Math.min(1,p*1.6)),fx.pivot,x,y,scale);ctx.restore();}
 ctx.strokeStyle='#d2dee4';ctx.beginPath();ctx.moveTo(442,190);ctx.lineTo(458,190);ctx.moveTo(450,182);ctx.lineTo(450,198);ctx.stroke();
 pane.status.textContent=state.state+' · '+state.duration+'ms · 접촉 '+contact+'ms · '+(fx?.clip?'charge / travel / impact 원본 노출':'기술 원화 및 접촉 이미지 비교 · 게임의 추가 연출은 별도')+' · 비교용 목표 십자';
 for(const fig of pane.strips.children)if(fig._draw)fig._draw();
 }}
function setPlaying(value){playing=value;play.textContent=value?'일시정지':'재생';play.setAttribute('aria-pressed',String(value));}
play.onclick=()=>{if(elapsed>=maxDuration())elapsed=0;setPlaying(!playing);};document.getElementById('reset').onclick=()=>{elapsed=0;setPlaying(false);draw();};seek.oninput=()=>{elapsed=Number(seek.value)*maxDuration();setPlaying(false);draw();};document.getElementById('background').onchange=draw;document.getElementById('mode').onchange=()=>{elapsed=0;setPlaying(false);draw();};
const verdict=document.getElementById('verdict');
el('strong',data.report.status==='passed'?'기술 기준 통과 · 시각 검토 필요':'수정이 필요한 에셋',verdict);
if(data.report.findings.length){const ul=el('ul',undefined,verdict);for(const f of data.report.findings){el('li',f.asset+' · '+f.repair,ul)}}
document.getElementById('report').textContent=JSON.stringify(data.report,null,2);
function tick(now){const active=playing;if(playing){elapsed+=(previous?now-previous:0)*Number(document.getElementById('speed').value);if(elapsed>=maxDuration()){elapsed=maxDuration();setPlaying(false);}}previous=now;if(active)draw();requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script></html>'''
