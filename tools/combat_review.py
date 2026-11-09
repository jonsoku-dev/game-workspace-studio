#!/usr/bin/env python3
"""Optional review of a generated combat game's authored actor and heavy contact timing."""
import argparse
import base64
import io
import json
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image
import character
import graph
from runtime_inputs import output_stage
from web_game import _read


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def module_json(raw, prefix):
    text = raw.decode().strip()
    if not text.startswith(prefix) or not text.endswith(';'):
        raise ValueError('Expected generated JSON module')
    return json.loads(text[len(prefix):-1])


def image(data, format):
    with Image.open(io.BytesIO(data), formats=[format]) as source:
        if source.is_animated or source.width * source.height > 16_777_216:
            raise ValueError('Image exceeds review budget')
        return source.convert('RGBA')


def frames(entries, sheet):
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise ValueError('Expected 1..64 frames')
    for f in entries:
        if (not isinstance(f, dict) or any(type(f.get(k)) is not int for k in ('x', 'y', 'w', 'h', 'ms'))
                or not 0 <= f['x'] < f['x'] + f['w'] <= sheet.width
                or not 0 <= f['y'] < f['y'] + f['h'] <= sheet.height
                or not 1 <= f['w'] <= 512 or not 1 <= f['h'] <= 512 or not 1 <= f['ms'] <= 60000):
            raise ValueError('Invalid frame bounds or duration')
    return entries


IMPACT_RATE = 1.6  # mirrors starter/combat/game/combat-fx.mjs IMPACT_RATE


def retime(sequence, duration):
    """Match drawActor's normalized phase progress, retaining every authored exposure."""
    total = sum(f['duration_ms'] for f in sequence)
    boundaries = [0]
    elapsed = 0
    for f in sequence:
        elapsed += f['duration_ms']
        boundaries.append((elapsed * duration + total // 2) // total)
    if any(b <= a for a, b in zip(boundaries, boundaries[1:])):
        raise ValueError('Phase too short to preserve every authored exposure')
    return [{**f, 'duration_ms': b - a} for f, a, b in zip(sequence, boundaries, boundaries[1:])]


def prepare(project, actor_name, clip_index, stage, pin):
    defaults = actor_name in ('blade', 'brawler', 'astral', 'rail')
    actor = (module_json(pin('game/motion/manifest.mjs', 1_048_576), 'export default ')[actor_name]
             if defaults else json.loads(pin(f'game/motion/{actor_name}.json', 65536)))
    if not isinstance(actor, dict) or actor.get('image') != actor_name + '.webp':
        raise ValueError('Expected generated actor image name')
    sheet = image(pin(f'game/motion/{actor["image"]}', 8_388_608), 'WEBP')
    entries = frames(actor['frames'], sheet)
    size = [entries[0]['w'], entries[0]['h']]
    if any([f['w'], f['h']] != size for f in entries):
        raise ValueError('Actor frames need one common canvas')
    pivot = actor['pivot']
    if not isinstance(pivot, list) or len(pivot) != 2 or any(type(v) is not int or not 0 <= v <= size[i] for i, v in enumerate(pivot)):
        raise ValueError('Invalid common foot pivot')
    actions = actor['actions']
    required = {'idle', 'move', 'heavy', 'release', 'follow', 'recover', 'hurt'}
    if (not isinstance(actions, dict) or not required <= actions.keys() or len(actions) > 30
            or any(not re.fullmatch('[a-z][a-z0-9-]{0,47}', name) for name in actions)
            or any(not isinstance(seq, list) or not 1 <= len(seq) <= 64
                   or any(type(i) is not int or not 0 <= i < len(entries) for i in seq) for seq in actions.values())):
        raise ValueError('Invalid authored action sequences')
    action_ms = actor.get('action_ms', {})
    if not isinstance(action_ms, dict) or action_ms.keys() - actions.keys():
        raise ValueError('Action timing must name existing authored states')
    exposures = {}
    for name, seq in actions.items():
        durations = action_ms.get(name, [entries[i]['ms'] for i in seq])
        if (not isinstance(durations, list) or len(durations) != len(seq)
                or any(type(ms) is not int or not 1 <= ms <= 60000 for ms in durations)
                or sum(durations) > (60000 if name in action_ms else 120000)):
            raise ValueError('Action timing requires matching positive bounded exposure durations')
        exposures[name] = durations
    jobs_raw = pin('game/jobs.mjs', 65536)
    if defaults:
        if jobs_raw.decode().strip() != "export { DEFAULT_JOBS as JOBS } from './combat-fx.mjs';":
            raise ValueError('Default actor requires generated default jobs module')
        job = {'actor': actor_name, 'motif': actor_name}
    else:
        jobs = module_json(jobs_raw, 'export const JOBS = ')
        if not isinstance(jobs, dict) or not 0 <= clip_index < len(jobs):
            raise ValueError('Clip index outside generated jobs')
        job = list(jobs.values())[clip_index]
        if job.get('actor') != actor_name:
            raise ValueError('Selected job does not use this actor')
    recovery = module_json(pin('game/timing.mjs', 65536), 'export const RECOVERY_MS = ')
    if (not isinstance(recovery, dict) or set(recovery) != {'follow', 'recover'}
            or any(type(n) is not int or not 1 <= n <= 60000 for n in recovery.values())):
        raise ValueError('Invalid generated recovery timing')
    clip = job.get('clip')
    if clip:
        if clip.get('image') != f'./fx/job-clip-{clip_index}.png':
            raise ValueError('Expected generated clip image')
        fx = image(pin(f'game/fx/job-clip-{clip_index}.png', 16_777_216), 'PNG')
        phases = {name: frames(clip['phases'][name], fx) for name in ('charge', 'travel', 'impact')}
        fx_pivot = clip['pivot']
        credits = json.loads(pin(f'game/fx/job-clip-{clip_index}-credit.json', 1_048_576))
        license_text, notice = credits['license'], credits['notice']
        timing = [sum(f['ms'] for f in phases[name]) for name in phases]
    else:
        fx_manifest = module_json(pin('game/fx/manifest.mjs', 1_048_576), 'export default ')
        effect = job.get('impact', fx_manifest['impact'])
        name = effect['image'].removeprefix('./')
        if not name.startswith('fx/'):
            raise ValueError('Expected local impact image')
        fx = image(pin('game/' + name, 16_777_216), 'PNG')
        phases = {'impact': frames(effect['frames'], fx)}
        fx_pivot = effect['pivot']
        credits = json.loads(pin('game/fx/credits.json', 1_048_576))
        license_text, notice = credits['contact']['license'], credits['contact']['notice']
        motifs = module_json(pin('game/motif-ms.mjs', 65536), 'export const MOTIF_MS = ')
        timing = motifs[job['motif']]['heavy']
        if not isinstance(timing, list) or len(timing) != 3:
            raise ValueError('Invalid generated motif timing')
        # The runtime plays painted/default impacts at IMPACT_RATE and holds the last frame for the rest of decay.
        played = round(timing[2] / IMPACT_RATE)
        phases['impact'] = [{**f, 'ms': r['duration_ms']} for f, r in zip(phases['impact'], retime(
            [{'duration_ms': f['ms']} for f in phases['impact']], played))]
        phases['impact'][-1]['ms'] += timing[2] - played
    if (any(type(t) is not int or not 1 <= t <= 60000 for t in timing)
            or not isinstance(fx_pivot, list) or len(fx_pivot) != 2
            or any(type(v) is not int or not 0 <= v <= phases['impact'][0][k] for v, k in zip(fx_pivot, ('w', 'h')))
            or not isinstance(license_text, str) or not license_text.strip()
            or not isinstance(notice, str) or not notice.strip()):
        raise ValueError('Invalid effect timing, pivot or license')
    inputs = stage / 'inputs'
    inputs.mkdir()
    fx.save(inputs / 'effect.png')
    (inputs / 'LICENSE').write_text(license_text)
    (inputs / 'NOTICE').write_text(notice)
    write(inputs / 'effect-credit.json', credits)
    authored = {}
    for i, f in enumerate(entries):
        sheet.crop((f['x'], f['y'], f['x'] + f['w'], f['y'] + f['h'])).save(inputs / f'pose-{i}.png')
    for name, seq in actions.items():
        authored[name] = {'loop': name in ('idle', 'move', 'walk', 'run'),
                          'frames': [{'path': f'pose-{i}.png', 'duration_ms': ms} for i, ms in zip(seq, exposures[name])]}
    attack = []
    for state, duration in zip(('heavy', 'release', 'follow', 'recover'), (*timing[:2], recovery['follow'], recovery['recover'])):
        attack.extend(retime(authored[state]['frames'], duration))
    authored['attack'] = {'loop': False, 'frames': attack}
    if sum(len(a['frames']) for a in authored.values()) * size[0] * size[1] > 16_777_216:
        raise ValueError('Rive frame pixel budget exceeded')
    write(inputs / 'poses.json', {'schema_version': 1, 'size': size,
                                 'pivot_px_from_top_left': pivot, 'actions': authored})
    write(inputs / 'character.json', {'schema_version': 1, 'frames': 'poses.json',
                                    'title': '전투 동작 검토', 'actions': list(authored)})
    impact = phases['impact']
    if len({(f['w'], f['h']) for f in impact}) != 1:
        raise ValueError('Impact needs equal effect cells')
    write(inputs / 'impact.json', {'frames': [{'frame': {k: f[k] for k in ('x', 'y', 'w', 'h')},
          'duration': f['ms'], 'rotated': False, 'trimmed': False} for f in impact],
          'meta': {'image': 'effect.png', 'pixelfx': {'frameSize': [impact[0]['w'], impact[0]['h']],
          'frames': len(impact), 'loop': False, 'pivot': fx_pivot}}})
    missing = sorted({'idle', 'walk', 'run', 'jump', 'hurt'} - actions.keys())
    contact = timing[0] + timing[1]
    report = {'schema_version': 1, 'actor': actor_name, 'clip_index': clip_index,
              'pivot': pivot, 'size': size, 'charge_ms': timing[0], 'travel_ms': timing[1],
              'contact_ms': contact, 'follow_ms': recovery['follow'], 'recover_ms': recovery['recover'],
              'attack': attack, 'phases': phases, 'effect_pivot': fx_pivot,
              'action_set': 'skipped: missing authored ' + ', '.join(missing) if missing else 'eligible',
              'limits': ['Isolated heavy attack timing view; game camera, hit-stop, target motion and procedural overlays excluded.',
                         'Authored exposures retained; phase durations follow game normalized progress, rounded to milliseconds.',
                         'Rive player shows actor states; review.html shows contact FX. Artistic acceptance pending.']}
    if not missing:
        base = {name: authored[name] for name in ('idle', 'walk', 'run', 'attack', 'jump', 'hurt')}
        event = {'action': 'attack', 'frame': len(actions['heavy']) + len(actions['release']),
                 'sheet': 'effect.png', 'metadata': 'impact.json', 'license': 'LICENSE', 'notice': 'NOTICE',
                 'at_px': [size[0], max(0, pivot[1] - size[1] // 3)],
                 'attribution': 'Exact generated game impact phase; see effect-credit.json for provenance.'}
        write(inputs / 'action-set.json', {'schema_version': 1, 'cell_size': size, 'pivot_px_from_top_left': pivot,
                                           'actions': base, 'events': [event]})
    write(stage / 'timing.json', report)
    return report


def review_html(stage, report):
    """Embed admitted images so the timed review also works directly from a local file."""
    inputs = stage / 'inputs'
    names = {f['path'] for f in report['attack']} | {'effect.png'}
    pictures = {name: 'data:image/png;base64,' + base64.b64encode((inputs / name).read_bytes()).decode() for name in names}
    data = json.dumps({'timing': report, 'pictures': pictures}, ensure_ascii=False).replace('<', '\\u003c')
    (stage / 'review.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Combat contact review</title>
<style>body{background:#152526;color:#eff6ec;font:16px system-ui;margin:24px}canvas{background:#334c48;width:100%;max-width:1000px}input{width:70%}button,a{font:inherit;color:inherit}a{margin:16px}pre{white-space:pre-wrap}</style>
<h1>Heavy attack · contact review</h1><p>Exact game actor exposures and effect phases. Scrub to inspect the contact boundary.</p>
<button id="play">Play attack</button><a href="character/bundle/player.html">Open Rive states</a>
<p><label>Time <input id="scrub" type="range" min="0" step="1" value="0"></label> <output id="time"></output></p>
<canvas id="view" width="1000" height="650" role="img" aria-label="Actor attack with contact-timed effect"></canvas><pre id="notes"></pre>
<script>const data=''' + data + ''';
const t=data.timing, images={}, canvas=document.querySelector('#view'), ctx=canvas.getContext('2d'), slider=document.querySelector('#scrub');
const end=Math.max(t.contact_ms+t.follow_ms+t.recover_ms,t.contact_ms+t.phases.impact.reduce((s,f)=>s+f.ms,0));slider.max=end;
document.querySelector('#notes').textContent=`Contact: ${t.contact_ms} ms; charge ${t.charge_ms} ms; travel ${t.travel_ms} ms.\\nSix-action export: ${t.action_set}\\n`+t.limits.join('\\n');
function at(frames,ms,key){for(const f of frames){ms-=f[key];if(ms<0)return f;}return frames.at(-1);}
function draw(ms){ctx.clearRect(0,0,1000,650);const scale=Math.min(.9,460/t.size[1]),foot=[260,570];const f=at(t.attack,ms,'duration_ms');ctx.drawImage(images[f.path],foot[0]-t.pivot[0]*scale,foot[1]-t.pivot[1]*scale,t.size[0]*scale,t.size[1]*scale);
ctx.strokeStyle='#87aaa0';ctx.beginPath();ctx.moveTo(40,foot[1]);ctx.lineTo(960,foot[1]);ctx.stroke();
const phase=ms<t.charge_ms?'charge':ms<t.contact_ms?'travel':'impact';const elapsed=phase==='charge'?ms:phase==='travel'?ms-t.charge_ms:ms-t.contact_ms;const seq=t.phases[phase];
if(seq&&elapsed<seq.reduce((s,f)=>s+f.ms,0)){const fx=at(seq,elapsed,'ms'),progress=Math.min(1,elapsed/Math.max(1,t.travel_ms));const x=phase==='charge'?350:phase==='travel'?350+350*progress:700,y=400;ctx.drawImage(images['effect.png'],fx.x,fx.y,fx.w,fx.h,x-t.effect_pivot[0],y-t.effect_pivot[1],fx.w,fx.h);}
ctx.fillStyle='#fff';ctx.font='20px system-ui';ctx.fillText(`${phase} · ${Math.round(ms)} ms`,32,35);document.querySelector('#time').textContent=`${Math.round(ms)} / ${end} ms · ${phase}`;slider.value=ms;}
let start=null,playing=false;function tick(now){if(!playing)return;if(start===null)start=now;const ms=Math.min(end,now-start);draw(ms);if(ms<end)requestAnimationFrame(tick);else playing=false;}
document.querySelector('#play').onclick=()=>{playing=true;start=null;requestAnimationFrame(tick);};slider.oninput=()=>{playing=false;draw(Number(slider.value));};
Promise.all(Object.entries(data.pictures).map(([name,src])=>new Promise((resolve,reject)=>{const i=new Image();images[name]=i;i.onload=resolve;i.onerror=reject;i.src=src;}))).then(()=>draw(0)).catch(()=>{document.querySelector('#notes').textContent='Image decode failed';});
</script></html>''')


def build(project, actor, output_name, clip_index=None):
    project = Path(project).resolve(strict=True)
    if not re.fullmatch(r'job-\d{1,2}|blade|brawler|astral|rail', actor):
        raise ValueError('Expected generated actor job-N or default combat motif')
    if clip_index is None:
        clip_index = int(actor[4:]) if actor.startswith('job-') else ('blade', 'brawler', 'astral', 'rail').index(actor)
    if type(clip_index) is not int or not 0 <= clip_index < 32:
        raise ValueError('Invalid clip index')
    output = character.local(project, output_name)
    if output.relative_to(project).parts[0] in ('.game-studio', 'game'):
        raise ValueError('Review output cannot replace game or graph storage')
    pins = {}
    def pin(name, limit):
        raw = _read(project, name)
        if len(raw) > limit or sum(len(b) for b in pins.values()) + len(raw) > 33_554_432:
            raise ValueError('Review inputs exceed budget')
        pins[name] = raw
        return raw
    with output_stage(output) as stage:
        report = prepare(project, actor, clip_index, stage, pin)
        write(stage / 'provenance.json', {name: {'sha256': character.sha(raw), 'byteCount': len(raw)} for name, raw in pins.items()})
        review_html(stage, report)
        if any(_read(project, name) != raw for name, raw in pins.items()):
            raise ValueError('Review inputs changed during preparation')
    observed = character.work(project, 'Observe combat review source inputs', files=list(pins))
    nodes = graph.export_graph(project)['@graph']
    used = [n['@id'] for n in nodes if n['@id'].startswith(observed + ':artifact:')]
    if any(_read(project, name) != raw for name, raw in pins.items()):
        raise ValueError('Review inputs changed during graph admission')
    character_result = character.build(project, output_name + '/inputs/character.json', output_name + '/character')
    result = {'status': character_result['status'], 'review': output_name + '/review.html',
              'timing': output_name + '/timing.json', 'character': character_result,
              'action_set': report['action_set'], 'artistic_acceptance': 'pending'}
    if report['action_set'] == 'eligible' and character_result['status'] == 'ready':
        completed = subprocess.run(['pixel-asset', 'action-set', '--request', str(output / 'inputs/action-set.json'),
                                    '--out', str(output / 'action-set')], capture_output=True, text=True, timeout=300)
        if completed.returncode:
            result.update(status='needs_review', action_set='failed; inspect preserved request and inputs')
        else:
            metadata = json.loads(character.read(output / 'action-set/action-set.json', 1_048_576))
            if metadata['events'][0]['start_ms'] != report['contact_ms']:
                raise ValueError('Action-set contact does not match generated game')
            character.read(output / 'action-set/preview.gif', 33_554_432)
            result['action_set'] = output_name + '/action-set/preview.gif'
    if any(_read(project, name) != raw for name, raw in pins.items()):
        raise ValueError('Review source changed during production')
    write(output / 'result.json', result)
    generated = [{'path': p.relative_to(project).as_posix(), 'sha256': character.sha(character.read(p, 33_554_432))}
                 for p in character.files_under(output)]
    result['activity'] = character.work(project, 'Produce optional combat contact review',
        status='error' if result['status'] == 'error' else 'complete', used=used, generated=generated)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--clip-index', type=int)
    args = parser.parse_args(argv)
    try:
        result = build(args.project, args.actor, args.out, args.clip_index)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        result = {'status': 'error', 'message': 'Review failed; check generated actor, timing, licenses and fresh output path.'}
        if args.project.is_dir():
            try:
                result['activity'] = character.work(args.project.resolve(), 'Combat contact review failed', status='error')
            except (OSError, ValueError, KeyError, TypeError):
                pass
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'ready' else 2


if __name__ == '__main__':
    sys.exit(main())
