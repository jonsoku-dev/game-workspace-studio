#!/usr/bin/env python3
"""Compile explicitly anchored, authored poses through the installed Pixel sheet CLI.

Request v1: {"cell":[512,512],"pivot":[256,470],"kinds":{"blade":{
"body_height":270,"frames":[{"id":"guard","path":"guard.png",
"foot":[220,450],"scale":0.6,"duration_ms":100}],
"actions":{"idle":["guard"]}}}}. Optional crop is [left,top,right,bottom];
foot coordinates are relative to that crop. Paths resolve beside the request.
Optional actor action_ms maps action names to matching integer-ms lists;
each entry and each action total must be in 1..60000.
"""
import argparse
import hashlib
import json
import io
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from PIL import Image, ImageDraw
from web_game import _read
from runtime_inputs import output_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


def _compile(request, output, pixel_root):
    request = Path(request).absolute()
    if any(p.is_symlink() for p in (request, *request.parents)):
        raise ValueError('Symlink request paths are not admitted')
    output = Path(output)
    raw = _read(request.parent, request.name)
    if len(raw) > 1_048_576:
        raise ValueError('Request exceeds 1 MiB')
    spec = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(spec, dict):
        raise ValueError('Expected request object')
    cell, pivot = spec['cell'], spec['pivot']
    if spec.get('schema_version') != 1 or len(cell) != 2 or any(type(n) is not int or not 1 <= n <= 512 for n in cell):
        raise ValueError('Expected v1 request with cell sides in 1..512')
    if len(pivot) != 2 or any(type(n) is not int or not 0 <= n <= cell[i] for i, n in enumerate(pivot)):
        raise ValueError('Pivot must lie inside the cell')
    if not 1 <= len(spec['kinds']) <= 32:
        raise ValueError('Expected 1..32 kinds')
    counts = [len(actor['frames']) for actor in spec['kinds'].values()]
    if any(not 1 <= n <= 64 for n in counts) or sum(counts) > 256 or sum(counts) * cell[0] * cell[1] > 67_108_864:
        raise ValueError('Frame count or total pixel budget exceeded')
    manifest, evidence = {}, {'schema_version': 1, 'request_sha256': hashlib.sha256(raw).hexdigest(), 'kinds': {}}
    env = dict(os.environ)
    command = ['pixel-asset']
    if pixel_root:
        env['PYTHONPATH'] = str(Path(pixel_root).resolve(strict=True) / 'src')
        command = [sys.executable, '-m', 'pixel_asset_pipeline.cli']
    for kind, actor in spec['kinds'].items():
        if kind=='evidence' or not re.fullmatch('[a-z][a-z0-9-]{0,47}', kind):
            raise ValueError('Invalid kind name')
        stage = output / kind
        stage.mkdir()
        if type(actor['body_height']) not in (int, float) or not math.isfinite(actor['body_height']) or not 1 <= actor['body_height'] <= 512:
            raise ValueError('Body height must be finite and in 1..512')
        entries, records, ids = [], [], {}
        for i, item in enumerate(actor['frames']):
            ident = item['id']
            if ident in ids or not re.fullmatch('[a-zA-Z][a-zA-Z0-9-]{0,47}', ident):
                raise ValueError('Frame IDs must be unique safe names')
            source_bytes = _read(request.parent, item['path'])
            with Image.open(io.BytesIO(source_bytes), formats=['PNG', 'WEBP']) as original:
                if original.is_animated or original.width * original.height > 16_777_216:
                    raise ValueError('Source exceeds image budget')
                frame = original.convert('RGBA')
            if 'crop' in item:
                box = item['crop']
                if len(box) != 4 or any(type(n) is not int for n in box) or not 0 <= box[0] < box[2] <= frame.width or not 0 <= box[1] < box[3] <= frame.height:
                    raise ValueError('Crop outside source')
                frame = frame.crop(box)
            scale = item.get('scale', 1)
            if type(scale) not in (float, int) or not math.isfinite(scale) or not 0 < scale <= 4:
                raise ValueError('Scale must be in (0,4]')
            foot = item['foot']
            if len(foot) != 2 or not all(type(n) in (float, int) and math.isfinite(n) and 0 <= n <= frame.size[i] for i,n in enumerate(foot)):
                raise ValueError('Frame needs an explicit foot anchor')
            size = (max(1, round(frame.width * scale)), max(1, round(frame.height * scale)))
            if max(size) > 1024:
                raise ValueError('Resized frame exceeds 1024px')
            frame = frame.resize(size, Image.Resampling.LANCZOS)
            at = (round(pivot[0] - foot[0] * scale), round(pivot[1] - foot[1] * scale))
            bounds = frame.getbbox()
            if not bounds or at[0] + bounds[0] < 0 or at[1] + bounds[1] < 0 or at[0] + bounds[2] > cell[0] or at[1] + bounds[3] > cell[1]:
                raise ValueError(f'Visible pixels clipped for {kind}/{ident}; adjust cell or common source scale')
            canvas = Image.new('RGBA', tuple(cell))
            canvas.paste(frame, at)
            filename = f'{ident}.png'
            canvas.save(stage / filename)
            ids[ident] = i
            entries.append({'path': filename, 'duration_ms': item.get('duration_ms', 100)})
            records.append({'id': ident, 'source': item['path'], 'source_sha256': hashlib.sha256(source_bytes).hexdigest(), 'crop': item.get('crop'), 'source_foot': foot, 'source_scale': scale, 'frame_sha256': digest(stage / filename), 'rgba_sha256': hashlib.sha256(canvas.tobytes()).hexdigest(), 'bounds': canvas.getbbox()})
        actions = {}
        if 'idle' not in actor['actions']:
            raise ValueError('Every actor needs idle')
        for name, sequence in actor['actions'].items():
            if not re.fullmatch('[a-z][a-z0-9-]{0,47}', name) or not isinstance(sequence,list) or len(sequence)>64 or not sequence or any(ident not in ids for ident in sequence):
                raise ValueError(f'Unknown frame in {kind}/{name}')
            actions[name] = [ids[ident] for ident in sequence]
        action_ms = actor.get('action_ms', {})
        if not isinstance(action_ms, dict):
            raise ValueError('action_ms must be a state-to-duration-list object')
        for name, durations in action_ms.items():
            if (name not in actions or not isinstance(durations, list) or len(durations) != len(actions[name])
                    or any(type(ms) is not int or not 1 <= ms <= 60_000 for ms in durations) or sum(durations) > 60_000):
                raise ValueError(f'Invalid action_ms for {kind}/{name}')
        write(stage / 'request.json', {'schema_version': 1, 'frames': entries, 'pivot_px_from_top_left': pivot, 'loop': False})
        result = subprocess.run([*command, 'sheet', '--request', str(stage / 'request.json'), '--out', str(stage / 'pixel')], env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        metadata = json.loads((stage / 'pixel/sheet.json').read_text())
        with Image.open(stage / 'pixel/sheet.png') as packed:
            packed = packed.convert('RGBA')
            packed.save(output / f'{kind}.webp', lossless=True, exact=True, method=6)
            with Image.open(output / f'{kind}.webp') as web:
                if web.convert('RGBA').tobytes() != packed.tobytes():
                    raise ValueError('WebP round trip lost RGBA pixels')
            for i, item in enumerate(records):
                crop = packed.crop((i * cell[0], 0, (i + 1) * cell[0], cell[1]))
                if hashlib.sha256(crop.tobytes()).hexdigest() != item['rgba_sha256']:
                    raise ValueError('Packed frame differs from prepared source')
            contact = Image.new('RGB', (cell[0] * min(4, len(records)), cell[1] * ((len(records) + 3) // 4)), '#28766b')
            for i, item in enumerate(records):
                frame = packed.crop((i * cell[0], 0, (i + 1) * cell[0], cell[1]))
                x, y = (i % 4) * cell[0], (i // 4) * cell[1]
                contact.paste(frame, (x,y), frame)
                draw = ImageDraw.Draw(contact)
                draw.line((x,y+pivot[1],x+cell[0],y+pivot[1]), fill='#f7cf79')
                draw.text((x+8,y+8), item['id'], fill='white')
            contact.save(stage / 'contact.jpg', quality=92)
        manifest[kind] = {'image': f'{kind}.webp', 'pivot': pivot, 'bodyHeight': actor['body_height'], 'actions': actions, 'frames': [{'id': r['id'], **f['rect'], 'ms': f['duration_ms']} for r,f in zip(records,metadata['frames'])]}
        if action_ms:
            manifest[kind]['action_ms'] = action_ms
        write(output / f'{kind}.json', manifest[kind])
        evidence['kinds'][kind] = {'producer': 'pixel_asset_pipeline.cli sheet', 'cli_stdout': result.stdout.strip(), 'pixel_sheet_sha256': digest(stage / 'pixel/sheet.png'), 'webp_sha256': digest(output / f'{kind}.webp'), 'metadata_sha256': digest(output / f'{kind}.json'), 'action_ms': action_ms, 'exact_rgba_round_trip': True, 'unique_rgba_frames': len({r['rgba_sha256'] for r in records}), 'frames': records}
    write(output / 'evidence.json', evidence)
    (output / 'manifest.mjs').write_text('export default ' + json.dumps(manifest, indent=2) + ';\n')
    return manifest


def compile_motion(request, output, pixel_root=None):
    with output_stage(output) as stage:
        return _compile(request, stage, pixel_root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--pixel-root', help='Trusted installed Pixel plugin root; defaults to pixel-asset on PATH')
    args = parser.parse_args()
    result = compile_motion(args.request, args.out, args.pixel_root)
    print(json.dumps({"output": args.out, "frames": {kind: len(actor["frames"]) for kind, actor in result.items()}}))
