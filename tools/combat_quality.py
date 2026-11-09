"""Read-only minimum craft checks for the generated combat runtime's pinned bytes.

These checks establish functional asset coverage, never artistic acceptance. Supported
metadata modules contain JSON, or the starter's explicit default/base imports; no JS runs.
"""
from collections import Counter
import io
import json
import math
import re

from PIL import Image, ImageChops


MOTIFS = {'blade': 'sword', 'brawler': 'fist', 'astral': 'star', 'rail': 'gun'}
MAX_PIXELS = 16_777_216


def _module(raw, prefix='export default '):
    text = raw.decode('utf-8').strip()
    if not text.startswith(prefix) or not text.endswith(';'):
        raise ValueError('Use the generated JSON metadata module; JavaScript expressions are not assessed')
    return json.loads(text[len(prefix):-1])


def jobs_for(sources):
    """Parse supported pinned job metadata without executing a module."""
    raw = sources['game/jobs.mjs']
    if raw.decode().strip() == "export { DEFAULT_JOBS as JOBS } from './combat-fx.mjs';":
        match = re.search(r'export const DEFAULT_JOBS = \{(.*?)\n\};', sources['game/combat-fx.mjs'].decode(), re.S)
        if not match:
            raise ValueError('Expected explicit starter DEFAULT_JOBS object')
        pattern = r"(\w+): \{ name: '([^']*)', skill: '([^']*)', motif: '(\w+)' \},?"
        entries = re.findall(pattern, match[1])
        if re.sub(pattern, '', match[1]).strip() or not entries:
            raise ValueError('Use supported default jobs metadata or generated JSON jobs')
        jobs = {key: {'name': name, 'skill': skill, 'motif': motif} for key, name, skill, motif in entries}
    else:
        jobs = _module(raw, 'export const JOBS = ')
    if (not isinstance(jobs, dict) or not 1 <= len(jobs) <= 8
            or any(not isinstance(key, str) or not isinstance(job, dict)
                   or job.get('motif') not in MOTIFS
                   or ('actor' in job and (not isinstance(job['actor'], str)
                       or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', job['actor'])))
                   for key, job in jobs.items())):
        raise ValueError('Expected 1..8 named jobs with supported combat motifs')
    return jobs


def runtime_actors(sources):
    raw=sources.__getitem__
    manifest_raw = raw('game/motion/manifest.mjs').decode().strip()
    prefix = "import base from './default.mjs';\nexport default {...base,..."
    if manifest_raw.startswith(prefix) and manifest_raw.endswith('};'):
        manifest = _module(raw('game/motion/default.mjs'))
        extra = json.loads(manifest_raw[len(prefix):-2])
        if not isinstance(manifest, dict) or not isinstance(extra, dict):
            raise ValueError('Expected base and custom motion metadata objects')
        manifest.update(extra)
    else:
        manifest = _module(raw('game/motion/manifest.mjs'))
    if not isinstance(manifest, dict) or not 1 <= len(manifest) <= 32:
        raise ValueError('Expected combat runtime motion metadata')
    return manifest


def _shape(image):
    # Alpha alone ignores hidden RGB and recoloring; crop removes pure translation.
    alpha = image.getchannel('A').point(lambda a: 255 if a >= 32 else 0)
    box = alpha.getbbox()
    if box is None:
        raise ValueError('Frame has no visible painted pixels')
    return alpha.crop(box).resize((64, 64), Image.Resampling.NEAREST)


def _distance(a, b):
    return ImageChops.difference(a, b).histogram()[255] / 4096


def _distinct(shapes):
    unique = []
    for shape in shapes:
        if all(_distance(shape, other) >= .025 for other in unique):
            unique.append(shape)
    return len(unique)


def _scene_detail(image):
    sample = image.resize((64, 64), Image.Resampling.NEAREST)
    pixels = sample.tobytes()
    visible = [pixels[i:i+3] for i in range(0, len(pixels), 4) if pixels[i+3] >= 32]
    if not visible:
        raise ValueError('초상화·배경에 실제 보이는 그림을 복구하세요.')
    quantized = [tuple(channel // 16 for channel in pixel) for pixel in visible]
    if max(Counter(quantized).values()) > len(quantized) * .98:
        raise ValueError('단색 면으로 대체된 초상화·배경에 실제 인물·무대의 형태와 디테일을 복구하세요.')


def assess(sources):
    """Return a JSON-compatible report from the exact mapping pinned by web_game._sources."""
    report = {'status': 'failed', 'findings': [], 'actors': [], 'effects': [],
              'artistic_acceptance': 'pending'}

    def fail(asset, code, repair):
        if 'NoneType' in repair:
            repair = '메타데이터 항목이 비어 있습니다. 해당 에셋의 객체·배열·필수 필드를 복구하세요.'
        report['findings'].append({'asset': asset, 'code': code, 'repair': repair})

    def raw(path):
        if path not in sources:
            raise ValueError('Missing runtime asset: ' + path)
        return sources[path]

    decoded_pixels = {}

    def picture(path):
        data = raw(path)
        with Image.open(io.BytesIO(data)) as image:
            if (image.format not in ('PNG', 'WEBP', 'JPEG') or getattr(image, 'is_animated', False)
                    or image.width * image.height > MAX_PIXELS):
                raise ValueError('Use a static PNG/WebP/JPEG within 16 megapixels')
            decoded_pixels[path] = image.width * image.height
            if len(decoded_pixels) > 64 or sum(decoded_pixels.values()) > 64 * 1024 * 1024:
                raise ValueError('Asset decoding exceeds 64 images / 64 megapixels total')
            return image.convert('RGBA')

    def local(value, folder='game/'):
        if not isinstance(value, str) or not re.fullmatch(r'(?:\./)?[a-zA-Z0-9_/-]+\.(?:png|webp|jpg|jpeg)', value) or '..' in value:
            raise ValueError('Use a local generated image path without traversal')
        return folder + value.removeprefix('./')

    def cells(entries, image, fading=False, cell_limit=512, minimum_coverage=0):
        limit = 128 if fading else 64
        if not isinstance(entries, list) or not 1 <= len(entries) <= limit:
            raise ValueError('Use 1..%s bounded frame rectangles' % limit)
        painted = []
        for f in entries:
            if (not isinstance(f, dict) or any(type(f.get(k)) is not int for k in ('x', 'y', 'w', 'h', 'ms'))
                    or not 0 <= f['x'] < f['x'] + f['w'] <= image.width
                    or not 0 <= f['y'] < f['y'] + f['h'] <= image.height
                    or not 1 <= f['w'] <= cell_limit or not 1 <= f['h'] <= cell_limit or not 1 <= f['ms'] <= 60000):
                raise ValueError('Repair frame bounds and positive exposure durations')
            cell = image.crop((f['x'], f['y'], f['x'] + f['w'], f['y'] + f['h']))
            box = cell.getchannel('A').point(lambda a: 255 if a >= 32 else 0).getbbox()
            if box is None and fading:
                continue
            if box is None or min(box[2]-box[0], box[3]-box[1]) < (1 if fading else 12):
                raise ValueError('각 프레임에 최소 %s픽셀 크기의 보이는 그림을 그리세요.' % (1 if fading else 12))
            if (box[2]-box[0]) * (box[3]-box[1]) < f['w'] * f['h'] * minimum_coverage:
                raise ValueError('스킬 그림이 셀 안에서 너무 작습니다. 보이는 형태의 경계 영역이 셀의 8% 이상을 차지하도록 그리세요.')
            painted.append(_shape(cell))
        return painted

    try:
        if (not isinstance(sources, dict) or not 1 <= len(sources) <= 257
                or any(not isinstance(k, str) or not isinstance(v, bytes) for k, v in sources.items())
                or sum(map(len, sources.values())) > 32 * 1024 * 1024):
            raise ValueError('Expected at most 257 pinned byte sources totaling 32 MiB')
        jobs = jobs_for(sources)
        manifest = runtime_actors(sources)
        fx_manifest = _module(raw('game/fx/manifest.mjs'))
        if not isinstance(fx_manifest, dict):
            raise ValueError('Expected an object mapping effect names to metadata')
        active = {'warden': 'enemy'}
        for job in jobs.values():
            if not isinstance(job, dict) or job.get('motif') not in MOTIFS:
                raise ValueError('Every active job needs a supported combat motif')
            active[job.get('actor', job['motif'])] = 'player'
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError, RecursionError) as error:
        fail('game', 'unsupported-runtime', str(error))
        return report

    # motionReady preloads every manifest entry before enabling Start. Structural
    # validity applies to unused actors too; pose craft applies only below to active actors.
    for name, actor in manifest.items():
        asset = 'game/motion/manifest.mjs:' + str(name)
        try:
            if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', name)
                    or not isinstance(actor, dict)):
                raise ValueError('각 미리 로드하는 캐릭터에 안전한 이름과 메타데이터 객체를 지정하세요.')
            image = picture(local(actor.get('image'), 'game/motion/'))
            entries, actions = actor.get('frames'), actor.get('actions')
            if not isinstance(entries, list) or not 1 <= len(entries) <= 64 or not isinstance(actions, dict):
                raise ValueError('미리 로드하는 캐릭터의 frames와 actions를 복구하세요.')
            for frame in entries:
                if (not isinstance(frame, dict)
                        or any(type(frame.get(k)) is not int for k in ('x', 'y', 'w', 'h', 'ms'))
                        or not 0 <= frame['x'] < frame['x'] + frame['w'] <= image.width
                        or not 0 <= frame['y'] < frame['y'] + frame['h'] <= image.height
                        or not 1 <= frame['ms'] <= 60000):
                    raise ValueError('캐릭터 미리 로드가 실패합니다. 시트 안의 프레임 범위와 시간을 복구하세요.')
            timings = actor.get('action_ms', {})
            if not isinstance(timings, dict):
                raise ValueError('캐릭터 action_ms를 상태별 시간 배열 객체로 복구하세요.')
            for state, times in timings.items():
                if (not isinstance(actions.get(state), list) or not isinstance(times, list)
                        or len(times) != len(actions[state])
                        or any(type(ms) is not int or not 1 <= ms <= 60000 for ms in times)
                        or sum(times) > 60000):
                    raise ValueError('캐릭터 미리 로드를 위해 action_ms와 동작 프레임의 길이·시간을 맞추세요.')
            pivot = actor.get('pivot')
            if (not isinstance(pivot, list) or len(pivot) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in pivot)):
                raise ValueError('캐릭터의 기준점 pivot에 유한한 좌표 2개를 지정하세요.')
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, Image.DecompressionBombError) as error:
            fail(asset, 'actor-preload', str(error))

    for name, role in sorted(active.items()):
        asset = 'game/motion/' + str(name) + '.json'
        try:
            actor = manifest[name]
            if actor != json.loads(raw(asset)):
                raise ValueError('Runtime manifest differs from actor JSON; regenerate both from the same motion metadata')
            sheet = picture(local(actor['image'], 'game/motion/'))
            shapes = cells(actor['frames'], sheet)
            pivot = actor['pivot']
            if (not isinstance(pivot, list) or len(pivot) != 2
                    or any(type(v) is not int or not 0 <= v <= actor['frames'][0][k] for v, k in zip(pivot, ('w', 'h')))
                    or type(actor.get('bodyHeight')) not in (int, float) or not 1 <= actor['bodyHeight'] <= 512):
                raise ValueError('Repair the common foot pivot and positive bodyHeight')
            actions = actor['actions']
            required = {'move', 'windup', 'heavy', 'release', 'follow', 'recover', 'hurt'}
            if role == 'player':
                required.update(('idle', 'evade', 'jump'))
            if not isinstance(actions, dict) or not required <= actions.keys() or len(actions) > 30:
                raise ValueError('필수 동작 상태를 제작하세요: ' + ', '.join(sorted(required - set(actions or {}))))
            action_ms = actor.get('action_ms', {})
            if not isinstance(action_ms, dict) or action_ms.keys() - actions.keys():
                raise ValueError('Action exposure metadata must name existing states')
            exposures = {}
            for state, seq in actions.items():
                if (not isinstance(seq, list) or not 1 <= len(seq) <= 64
                        or any(type(i) is not int or not 0 <= i < len(shapes) for i in seq)):
                    raise ValueError('Use valid authored frame indices for ' + state)
                durations = action_ms.get(state, [actor['frames'][i]['ms'] for i in seq])
                if (not isinstance(durations, list) or len(durations) != len(seq)
                        or any(type(ms) is not int or not 1 <= ms <= 60000 for ms in durations)
                        or sum(durations) > (60000 if state in action_ms else 120000)):
                    raise ValueError('Repair bounded per-state exposure timing for ' + state)
                exposures[state] = durations
            active_states = required | ({'walk'} & actions.keys() if role == 'player' else set())
            used = set(i for state in active_states for i in actions[state])
            distinct = _distinct([shapes[i] for i in sorted(used)])
            minimum = 14 if role == 'player' else 11
            if distinct < minimum:
                fail(asset, 'pose-coverage', '실제 사용하는 서로 다른 포즈를 최소 %s개 제작하세요 (%s). 기본 플레이어/파수꾼의 활성 포즈는 14/11개입니다.' % (minimum, role))
            for state in ('move', 'walk'):
                if state in active_states and _distinct([shapes[i] for i in actions[state]]) < 4:
                    fail(asset, 'gait-' + state, state + '에 팔다리 형태가 다른 보행 포즈 4개를 제작하세요. 색상·위치 변경만으로는 충족되지 않습니다.')
            for state in ('windup', 'heavy', 'recover'):
                seq = actions[state]
                if len(seq) < 2 or _distinct([shapes[i] for i in seq]) < 2:
                    fail(asset, 'phase-' + state, state + '에 준비·회복을 구분할 수 있는 포즈 2개를 제작하세요.')
                elif (exposures[state][1 if state != 'recover' else 0] * 4 < sum(exposures[state])):
                    fail(asset, 'exposure-' + state, '두 번째 준비 포즈와 첫 번째 회복 포즈를 해당 상태 시간의 25% 이상 노출하세요 (기본값 65% / 70%).')
            roles = ['release', 'follow', 'recover', 'hurt'] + (['idle', 'evade', 'jump'] if role == 'player' else [])
            representatives = [shapes[actions['heavy'][-1]]] + [shapes[actions[state][0]] for state in roles]
            if _distinct(representatives) < len(representatives):
                fail(asset, 'action-silhouettes', '대기·준비·발동·후속·회복·피격·회피' + ('·점프' if role == 'player' else '') + '의 몸과 무기 형태가 서로 구분되도록 제작하세요.')
            report['actors'].append({'asset': asset, 'role': role, 'used_poses': len(used), 'distinct_poses': distinct, 'active_states': sorted(active_states), 'frames': len(shapes)})
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, RecursionError, Image.DecompressionBombError) as error:
            fail(asset, 'actor-data', str(error))

    def effect(path, entries, minimum, kind, pivot=None):
        try:
            image = picture(path)
            shapes = cells(entries, image, fading=kind != 'painted skill',
                           cell_limit=1024 if kind == 'painted skill' else 512,
                           minimum_coverage=.08 if kind == 'painted skill' else 0)
            if pivot is not None and (not isinstance(pivot, list) or len(pivot) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in pivot)):
                raise ValueError('Repair the effect pivot within the native cell')
            count = _distinct(shapes)
            if count < minimum:
                fail(path, 'effect-geometry', '%s개 이상의 서로 다른 %s 형태를 시간 순서대로 그리세요. 한 형태의 색상·크기·위치 변경만으로는 충족되지 않습니다.' % (minimum, kind))
            report['effects'].append({'asset': path, 'kind': kind, 'frames': len(shapes), 'distinct_shapes': count})
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, RecursionError, Image.DecompressionBombError) as error:
            fail(path, 'effect-data', str(error))

    checked = set()
    for key, job in jobs.items():
        try:
            sheet_path = local(job.get('sheet', 'fx/' + MOTIFS[job['motif']] + '.webp'))
            if sheet_path not in checked:
                checked.add(sheet_path)
                image = picture(sheet_path)
                if image.width % 3 or image.height % 2 or image.width < 960 or image.height < 640 or image.width > 3072 or image.height > 2048 or image.width // 3 != image.height // 2:
                    raise ValueError('선명한 3×2 스킬 시트를 복구하세요. 각 셀은 기본 에셋과 같이 최소 320×320이어야 합니다.')
                w, h = image.width // 3, image.height // 2
                effect(sheet_path, [{'x': i % 3 * w, 'y': i // 3 * h, 'w': w, 'h': h, 'ms': 100} for i in range(6)], 4, 'painted skill')
            impact = job.get('impact', fx_manifest['impact'])
            effect(local(impact['image']), impact['frames'], 2, 'impact', impact['pivot'])
            if 'clip' in job:
                clip = job['clip']
                clip_path = local(clip['image'])
                metadata = json.loads(raw(clip_path.rsplit('.', 1)[0] + '.json'))
                if not isinstance(metadata['frames'], list) or not 1 <= len(metadata['frames']) <= 64:
                    raise ValueError('Use 1..64 clip frames')
                authored_frames = [{**f['frame'], 'ms': f['duration']} for f in metadata['frames']]
                if not isinstance(metadata['meta']['frameTags'], list) or len(metadata['meta']['frameTags']) != 3:
                    raise ValueError('Use exactly three clip phase tags')
                phases = {tag['name']: authored_frames[tag['from']:tag['to']+1] for tag in metadata['meta']['frameTags']}
                if clip['phases'] != phases or clip['pivot'] != metadata['meta']['pixelfx']['pivot']:
                    raise ValueError('Runtime clip differs from clip JSON; regenerate jobs and clip metadata together')
                for phase in ('charge', 'travel', 'impact'):
                    effect(local(clip['image']), clip['phases'][phase], 1 if phase != 'impact' else 2, phase + ' clip', clip['pivot'])
            portrait = local(job.get('actor', job['motif']) + '-idle.webp', 'game/art/')
            image = picture(portrait)
            if image.width < 240 or image.height < 290:
                fail(portrait, 'portrait-resolution', '초상화를 최소 240×290으로 복구하세요 (커스텀 기준 242×299, 기본 474×588).')
            _shape(image)
            _scene_detail(image)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, RecursionError, Image.DecompressionBombError) as error:
            fail('game/jobs.mjs:' + key, 'job-assets', str(error))
    # These entries are drawn by the supported runtime's motif and reaction paths.
    motif_effects = {'blade': ('sword-cut', 'sword-cleave'), 'brawler': ('fist-rise', 'fist-quake'),
                     'astral': ('star-volley', 'star-rain'), 'rail': ('gun-flash', 'gun-plasma')}
    active_effects = {'storm', 'star-seal', 'detonation', 'sword-wheel', 'fist-quake', 'land', 'impact'}
    for job in jobs.values():
        active_effects.update(motif_effects[job['motif']])
    for name in sorted(active_effects):
        try:
            entry = fx_manifest[name]
            effect(local(entry['image']), entry['frames'], 1, 'runtime ' + name, entry['pivot'])
        except (ValueError, TypeError, KeyError) as error:
            fail('game/fx/manifest.mjs:' + name, 'effect-data', str(error))
    try:
        image = picture('game/art/bell-tower.jpg')
        _scene_detail(image)
        if image.width < 1280 or image.height < 620:
            fail('game/art/bell-tower.jpg', 'background-resolution', '배경을 화면 크기인 최소 1280×620으로 복구하세요 (기본 배경 1650×825).')
    except (ValueError, OSError, Image.DecompressionBombError) as error:
        fail('game/art/bell-tower.jpg', 'background-data', str(error))
    report['status'] = 'failed' if report['findings'] else 'passed'
    return report
