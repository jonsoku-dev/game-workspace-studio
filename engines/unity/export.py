"""Export admitted Studio assets to a dependency-free offline Unity 6 project."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import runtime_inputs


def read(path):
    return json.loads(path.read_text())


def glb_static(path):
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<II', data, 4) != (2, len(data)):
        raise ValueError('Expected GLB 2')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A:
        raise ValueError('Missing GLB JSON')
    doc = json.loads(data[20:20 + length])
    if doc.get('skins') or doc.get('animations') or any(p.get('targets') for m in doc.get('meshes', []) for p in m['primitives']):
        raise ValueError('Only static meshes supported; skins/animation/morphs rejected')
    if doc.get('extensionsRequired'):
        raise ValueError('Raw GLB requires unsupported extensions')
    if any(item.get('uri') for key in ('buffers', 'images') for item in doc.get(key, [])):
        raise ValueError('GLB must be self-contained')
    return doc


def clips(metadata):
    result = []
    for name, action in metadata['actions'].items():
        frames = action['frames']
        if not frames or any(f['duration_ms'] <= 0 for f in frames) or sum(f['duration_ms'] for f in frames) != action['duration_ms']:
            raise ValueError('Invalid action timing')
        result.append(dict(name=name, loop=action['loop'], duration_ms=action['duration_ms'], frames=frames))
    return result


def export(sources, output, blender='blender'):
    if output.exists():
        raise ValueError('Output must not exist')
    products, hashes = runtime_inputs.admit(sources)
    output.parent.mkdir(parents=True, exist_ok=True)
    with runtime_inputs.output_stage(output) as stage:
        media = stage / 'Assets/StreamingAssets/Studio'
        media.mkdir(parents=True)
        provenance = runtime_inputs.copy_verified(hashes, media)
        converted = []
        for product in products:
            assets = []
            for ident, files in product['assets'].items():
                asset = {'id': ident}
                if 'atlas' in files:
                    metadata = read(media / files['metadata'])
                    asset.update(atlas=files['atlas'], cell_size=metadata['cell_size'],
                                 pivot=metadata['pivot_px_from_top_left'], clips=clips(metadata), events=[])
                    for i, event in enumerate(metadata.get('events', [])):
                        asset['events'].append({**event, 'sheet': files[f'effect_{i}_sheet'],
                                                'pivot': event['effect_anchor_px']})
                else:
                    if 'raw' not in files:
                        raise ValueError('Pinned raw GLB required for offline conversion')
                    raw = media / files['raw']
                    glb_static(raw)
                    target = raw.with_suffix('.mesh.json')
                    result = subprocess.run([blender, '--background', '--factory-startup', '--python-exit-code', '1',
                                             '--python', str(Path(__file__).with_name('convert.py')), '--', str(raw), str(target)],
                                            capture_output=True, text=True, timeout=180)
                    if result.returncode or not target.is_file():
                        raise ValueError('Blender static conversion failed: ' + result.stderr[-1500:])
                    mesh = read(target)
                    for part in mesh['parts']:
                        if len(part['vertices']) != len(part['normals']) or any(i < 0 or i >= len(part['vertices']) for i in part['triangles']):
                            raise ValueError('Invalid converted mesh')
                        if any(not math.isfinite(v) for p in part['vertices'] for v in p.values()):
                            raise ValueError('Nonfinite converted vertex')
                    asset['mesh'] = target.relative_to(media).as_posix()
                    converted.append({'source': files['raw'], 'source_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                                      'output': asset['mesh'], 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                                      'parts': len(mesh['parts']), 'triangles': sum(len(p['triangles']) // 3 for p in mesh['parts'])})
                    if 'effect' in files:
                        recipe = read(media / files['effect'])
                        if recipe['kind'] != 'mesh-particles' or recipe['duration_s'] <= 0:
                            raise ValueError('Unsupported effect recipe')
                        asset['effect'] = recipe
                assets.append(asset)
            product['assets'] = assets
        (media / 'products.json').write_text(json.dumps({'products': products}, indent=2, allow_nan=False))
        (media / 'provenance.json').write_text(json.dumps(provenance, indent=2))
        (media / 'conversion.json').write_text(json.dumps(converted, indent=2))
        (stage / 'Assets/Editor').mkdir()
        for relative in ('Assets/StudioRuntime.cs', 'Assets/StudioGame.cs', 'Assets/Editor/StudioBatch.cs'):
            shutil.copyfile(Path(__file__).parent / relative, stage / relative)
        shutil.copyfile(Path(__file__).with_name('README.md'), stage / 'README.md')
        (stage / 'Packages').mkdir()
        (stage / 'Packages/manifest.json').write_text('{"dependencies":{"com.unity.modules.imageconversion":"1.0.0","com.unity.modules.imgui":"1.0.0","com.unity.modules.jsonserialize":"1.0.0"}}\n')
        (stage / 'ProjectSettings').mkdir()
        (stage / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.0.60f1\n')
        manifest = [{'path': p.relative_to(media).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in sorted(media.rglob('*')) if p.is_file()]
        (media / 'integrity.json').write_text(json.dumps({'files': manifest}, indent=2))
    return converted


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', nargs=2, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--blender', default='blender')
    args = parser.parse_args()
    try:
        print(json.dumps(export([(Path(p), r) for p, r in args.source], args.output, args.blender), indent=2))
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
