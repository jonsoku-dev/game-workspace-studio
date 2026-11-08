"""Export a graph-pinned 2D action set as a self-hosted Phaser training game."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import math
import re

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'tools'))
spec = importlib.util.spec_from_file_location('runtime_inputs', HERE.parents[2] / 'tools/runtime_inputs.py')
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


def bundled_notices(library):
    source = library['dist/phaser.js'].decode('utf-8')
    blocks = re.findall(r'/\*[\s\S]*?\*/|(?m:^[ \t]*//[^\n]*(?:\n[ \t]*//[^\n]*)*)', source)
    notices = []
    for block in blocks:
        if not re.search(r'@copyright|Copyright \(c\)|Redistribution and use|Permission is hereby', block, re.I):
            continue
        owners = re.findall(r'@copyright[^\n]*', block)
        if owners and all(re.search(r'(Phaser Studio Inc\.|Photon Storm Ltd\.)', owner) for owner in owners):
            continue
        if block not in notices:
            notices.append(block)
    notices.append(library['src/physics/matter-js/lib/license.js'].decode('utf-8'))
    return ('Phaser 3.90.0 bundled third-party notices\n'
            'Verbatim comments from dist/phaser.js and src/physics/matter-js/lib/license.js.\n'
            'Phaser and EventEmitter3 MIT license texts are distributed separately.\n\n'
            + '\n\n'.join(notices)).encode('utf-8')


def validate_frames(items, image):
    data = image.read_bytes()
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Action textures must be PNG')
    width, height = struct.unpack('>II', data[16:24])
    if not items:
        raise ValueError('Empty animation')
    for item in items:
        r = item['rect']
        if any(type(r[k]) is not int for k in ('x', 'y', 'w', 'h')) or min(r['x'], r['y']) < 0 or min(r['w'], r['h']) <= 0 or r['x'] + r['w'] > width or r['y'] + r['h'] > height:
            raise ValueError('Atlas rectangle outside texture')
        if type(item['duration_ms']) is not int or item['duration_ms'] <= 0:
            raise ValueError('Invalid frame duration')


def validate(metadata, files, root, rules=None):
    def point(value):
        if not isinstance(value, list) or len(value) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in value):
            raise ValueError('Invalid pivot or anchor')
    if metadata.get('schema_version') != 1 or not {'idle', 'walk', 'attack'}.issubset(metadata['actions']):
        raise ValueError('Training game requires action-set v1 idle, walk and attack')
    point(metadata['pivot_px_from_top_left'])
    for action in metadata['actions'].values():
        validate_frames(action['frames'], root / files['atlas'])
        if action['duration_ms'] != sum(f['duration_ms'] for f in action['frames']) or type(action['loop']) is not bool:
            raise ValueError('Invalid action timing')
    attack_events = []
    for i, event in enumerate(metadata.get('events', [])):
        for kind in ('sheet', 'metadata', 'license', 'notice'):
            if Path(files[f'effect_{i}_{kind}']).name != event[kind]:
                raise ValueError('Event file does not match admitted product')
        action = metadata['actions'][event['action']]
        if type(event['start_ms']) is not int or not 0 <= event['start_ms'] < action['duration_ms']:
            raise ValueError('Event outside action')
        if action['loop']:
            raise ValueError('Training game events require non-looping actions')
        validate_frames(event['frames'], root / files[f'effect_{i}_sheet'])
        if event['duration_ms'] != sum(f['duration_ms'] for f in event['frames']):
            raise ValueError('Invalid effect timing')
        point(event['at_px'])
        point(event.get('effect_anchor_px', event['pivot_px_from_top_left']))
        if event['action'] == 'attack':
            attack_events.append(event)
    rules = {} if rules is None else rules
    if not isinstance(rules, dict):
        raise ValueError('playtest must be an object')
    if set(rules) - {'mode', 'hits_to_win', 'target_x', 'target_y', 'contact_frame', 'at_px'}:
        raise ValueError('Unsupported playtest fields')
    if rules.get('mode', 'land_hits') not in ('land_hits', 'courier_trial'):
        raise ValueError('Unsupported playtest mode')
    if rules.get('mode') == 'courier_trial' and not {'jump', 'hurt'} <= metadata['actions'].keys():
        raise ValueError('Courier trial requires jump and hurt actions')
    if type(rules.get('hits_to_win', 3)) is not int or not 1 <= rules.get('hits_to_win', 3) <= 100:
        raise ValueError('hits_to_win must be an integer from 1 to 100')
    for key, default, low, high in [('target_x', 650, 100, 860), ('target_y', 300, 100, 400)]:
        value = rules.get(key, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid ' + key)
    if rules.get('mode') == 'courier_trial' and (rules.get('target_x',650) != 650 or rules.get('target_y',300) != 300 or rules.get('hits_to_win',3) > 20):
        raise ValueError('Courier trial uses target (650,300) and 1..20 base hits')
    attack = metadata['actions']['attack']
    if not attack_events or 'contact_frame' in rules or 'contact_frame' in attack:
        attack = metadata['actions']['attack']
        frame = rules.get('contact_frame', attack.get('contact_frame'))
        if type(frame) is not int or not 0 <= frame < len(attack['frames']) or attack['loop']:
            raise ValueError('Attack requires contact_frame or one contact effect')
        point(rules.get('at_px', attack.get('at_px', attack_events[0]['at_px'] if attack_events else None)))
    if len(attack_events) > 1:
        raise ValueError('Training game requires exactly one attack contact event')


def export(project, runtime, output, phaser_package=None):
    output = Path(output)
    if output.exists():
        raise ValueError('Output must not exist')
    package = Path(phaser_package) if phaser_package else HERE / 'node_modules/phaser'
    lock = json.loads((HERE / 'runtime-lock.json').read_text())
    try:
        if json.loads((package / 'package.json').read_text())['version'] != lock['version']:
            raise ValueError('Phaser version mismatch')
        library = {name: (package / name).read_bytes() for name in lock['files']}
    except OSError as error:
        raise ValueError('Install pinned Phaser explicitly: npm ci --ignore-scripts --no-audit --no-fund in studio/engines/web/phaser') from error
    if any(hashlib.sha256(data).hexdigest() != lock['files'][name] for name, data in library.items()):
        raise ValueError('Phaser runtime integrity mismatch')
    products, hashes = inputs.admit([(Path(project), runtime)])
    runtime_scene = products[0]['scene']
    assets = products[0]['assets']
    bindings = inputs.feedback_effects(runtime_scene)
    actors = [value for value in assets.values() if 'atlas' in value]
    if len(actors) != 1 or len(assets) != 1 + len(set(bindings.values())):
        raise ValueError('Phaser requires one action-set and explicitly bound pixel effects')
    with inputs.output_stage(output) as stage:
        provenance = inputs.copy_verified(hashes, stage)
        files = actors[0]
        metadata = json.loads((stage / files['metadata']).read_text())
        rules = products[0]['scene'].get('playtest', {})
        validate(metadata, files, stage, rules)
        effects = {}
        for event, asset in bindings.items():
            sheet = assets[asset]
            frames = json.loads((stage / sheet['metadata']).read_text())
            if (frames.get('schema_version') != 1 or frames.get('loop') is not False
                    or not isinstance(frames.get('frames'), list) or not 1 <= len(frames['frames']) <= 256):
                raise ValueError('Feedback requires a non-looping effect sheet with timed frames')
            validate_frames(frames['frames'], stage / sheet['sheet'])
            w, h = (frames['frames'][0]['rect'][k] for k in ('w','h'))
            pivot = frames.get('pivot_px_from_top_left')
            if not isinstance(pivot, list) or len(pivot) != 2 or any(type(v) is not int or not 0 <= v <= n for v,n in zip(pivot,(w,h))):
                raise ValueError('Feedback sheet pivot outside its native frame')
            report = json.loads((stage / sheet['effect']).read_text())
            if report.get('passed') is not True:
                raise ValueError('Feedback effect has no successful producer inspection')
            still = report.get('reduced_motion_frame', 0)
            if type(still) is not int or not 0 <= still < len(frames['frames']):
                raise ValueError('Invalid reduced-motion frame in feedback effect')
            frames['reduced_motion_frame'] = still
            frames['duration_ms'] = sum(f['duration_ms'] for f in frames['frames'])
            effects[event] = {'sheet': sheet['sheet'], 'metadata': frames}
        for name in ('index.html', 'style.css', 'game.mjs', 'timing.mjs', 'trial.mjs', 'cue-sheets.mjs'):
            shutil.copyfile(HERE / name, stage / name)
        shutil.copyfile(HERE.parent / 'feedback.mjs', stage / 'feedback.mjs')
        vendor = stage / 'vendor'
        vendor.mkdir()
        (vendor / 'phaser.min.js').write_bytes(library['dist/phaser.min.js'])
        (vendor / 'PHASER-LICENSE.txt').write_bytes(library['LICENSE.md'])
        (vendor / 'EVENTEMITTER3-LICENSE.txt').write_bytes(library['../eventemitter3/LICENSE'])
        notices = bundled_notices(library)
        (vendor / 'PHASER-BUNDLED-NOTICES.txt').write_bytes(notices)
        provenance['vendor/PHASER-BUNDLED-NOTICES.txt'] = {'package':'phaser', 'version':lock['version'], 'source':lock['source'], 'sha256':hashlib.sha256(notices).hexdigest(), 'source_files':{name:lock['files'][name] for name in ('dist/phaser.js','src/physics/matter-js/lib/license.js')}}
        for destination, source in [('vendor/phaser.min.js', 'dist/phaser.min.js'), ('vendor/PHASER-LICENSE.txt', 'LICENSE.md'), ('vendor/EVENTEMITTER3-LICENSE.txt', '../eventemitter3/LICENSE')]:
            provenance[destination] = {'package':'phaser', 'version':lock['version'], 'source':lock['source'], 'sha256':lock['files'][source], 'license':'MIT'}
        (stage / 'provenance.json').write_text(json.dumps(provenance, indent=2))
        game = {'schema_version':1, 'files':files, 'metadata':metadata, 'playtest':rules, 'brief':runtime_scene.get('brief', {}), 'runtime_pin':products[0]['runtime_pin']}
        if 'feedback' in runtime_scene:
            game['feedback'] = {'schema_version':1, 'effects':effects}
        (stage / 'game.json').write_text(json.dumps(game, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phaser-package', type=Path)
    args = parser.parse_args()
    try:
        export(args.project, args.runtime, args.output, args.phaser_package)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
