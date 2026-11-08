"""Copy pinned Studio runtime products into a standalone offline Godot project."""
import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
import shutil
import struct
import tempfile


def glb_json(path):
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
        raise ValueError(f'Not a GLB 2: {path}')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or struct.unpack_from('<I', data, 8)[0] != len(data):
        raise ValueError(f'Invalid GLB: {path}')
    return json.loads(data[20:20 + length])


def graph_pins(project, runtime):
    spec = importlib.util.spec_from_file_location('studio_graph', Path(__file__).resolve().parents[2] / 'tools/graph.py')
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    nodes = graph.export_graph(project)['@graph']
    by_id = {n['@id']: n for n in nodes}
    candidates = [n for n in nodes if 'RuntimeProduct' in n.get('@type', []) and n.get('path') == runtime]
    for candidate in candidates:
        runs = [by_id[i] for i in candidate.get('wasGeneratedBy', [])]
        if not any(r.get('record', {}).get('status') == 'ready' for r in runs):
            continue
        if hashlib.sha256((project / runtime).read_bytes()).hexdigest() != candidate['sha256']:
            continue
        admitted = {candidate['@id']: candidate}
        pending = list(candidate.get('wasDerivedFrom', []))
        pending += [i for n in nodes if 'ScenePlacement' in n.get('@type', []) and candidate['@id'] in n.get('partOf', []) for i in n.get('placementOf', [])]
        while pending:
            ident = pending.pop()
            if ident in admitted:
                continue
            node = by_id[ident]
            admitted[ident] = node
            pending.extend(node.get('wasDerivedFrom', []))
        pins = {}
        for node in admitted.values():
            if 'path' not in node or 'sha256' not in node:
                continue
            if node['path'] in pins and pins[node['path']]['sha256'] != node['sha256']:
                raise ValueError('Conflicting linked artifact pins')
            pins[node['path']] = node
        return pins
    raise ValueError('Runtime has no matching successful SSOT graph pin')


def export(sources, output):
    if output.exists():
        raise ValueError('Output must not exist (prevents overwriting a project)')
    prepared = []
    hashes = {}
    for project, runtime in sources:
        project = project.resolve()
        def source(relative):
            path = (project / relative).resolve()
            if not path.is_relative_to(project) or not path.is_file():
                raise ValueError(f'Missing or escaping input: {relative}')
            return path
        path = source(runtime)
        pins = graph_pins(project, runtime)
        def pinned(relative):
            original = source(relative)
            data = original.read_bytes()
            pin = pins.get(relative, {})
            if hashlib.sha256(data).hexdigest() != pin.get('sha256') or len(data) != pin.get('byteCount'):
                raise ValueError(f'Artifact drift or missing SSOT pin: {relative}')
            return original
        runtime_bytes = path.read_bytes()
        if hashlib.sha256(runtime_bytes).hexdigest() != pins[runtime]['sha256'] or len(runtime_bytes) != pins[runtime]['byteCount']:
            raise ValueError('Runtime changed during export')
        scene = json.loads(runtime_bytes)
        if scene.get('schema_version') != 1 or scene.get('status') != 'ready' or scene['coordinates'] != {'units': 'meters', 'up': '+Y', 'handedness': 'right'}:
            raise ValueError('Expected ready Studio v1 meter/Y-up/right-handed scene')
        assets = {}
        for asset in scene['assets']:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', asset['id']) or asset['id'] in assets:
                raise ValueError('Invalid or duplicate asset id')
            files = asset['files']
            roles = ['atlas', 'metadata', 'credits'] if 'atlas' in files else ['model', 'raw', 'effect', 'validation', 'receipt']
            roles += [role for role in files if role.startswith('effect_')]
            copied = {}
            for role in roles:
                if role not in files:
                    continue
                original = pinned(files[role])
                if role in ('model', 'raw'):
                    doc = glb_json(original)
                    if any(x.get('uri') for x in doc.get('buffers', [])) or any(x.get('uri') for x in doc.get('images', [])):
                        raise ValueError('Only self-contained GLBs supported')
                relative = f"products/{len(prepared)}/{asset['id']}/{original.name}"
                if role in ('model', 'raw'):
                    relative += '.bytes'
                if relative in hashes:
                    raise ValueError('Duplicate asset destination')
                hashes[relative] = {'source': files[role], '_source': str(original), 'sha256': pins[files[role]]['sha256'], 'artifact': pins[files[role]]['@id']}
                copied[role] = 'res://' + relative
            if 'model' in files and not json.loads(source(files['validation']).read_text()).get('passed'):
                raise ValueError('Model validation did not pass')
            assets[asset['id']] = copied
        ids = [node['id'] for node in scene['nodes']]
        if len(set(ids)) != len(ids) or any(n['asset'] not in assets or n.get('parent', n['id']) not in ids for n in scene['nodes']):
            raise ValueError('Invalid node/asset/parent reference')
        for node in scene['nodes']:
            for field in ('position', 'rotation_degrees', 'scale'):
                values = node[field]
                if len(values) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                    raise ValueError('Invalid node transform')
            seen = {node['id']}
            parent = node.get('parent')
            while parent:
                if parent in seen:
                    raise ValueError('Cyclic node hierarchy')
                seen.add(parent)
                parent = next(n for n in scene['nodes'] if n['id'] == parent).get('parent')
        prepared.append({'scene': scene, 'assets': assets, 'runtime_pin': pins[runtime]})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.godot-export-', dir=output.parent) as tmp:
        stage = Path(tmp) / 'project'
        stage.mkdir()
        for relative, item in hashes.items():
            dest = stage / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = Path(item['_source']).read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Pinned input changed during export')
            dest.write_bytes(data)
        for name in ('project.godot', 'main.tscn', 'main.gd', 'studio_runtime.gd', 'probe.gd', 'export_presets.cfg'):
            shutil.copyfile(Path(__file__).parent / name, stage / name)
        (stage / 'products.json').write_text(json.dumps(prepared, indent=2))
        (stage / 'provenance.json').write_text(json.dumps({p: {k: v for k, v in pin.items() if k != '_source'} for p, pin in hashes.items()}, indent=2))
        if output.exists():
            raise ValueError('Output appeared during export')
        stage.rename(output)
    return prepared


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', nargs=2, action='append', required=True, metavar=('PROJECT', 'RUNTIME'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export([(Path(p), r) for p, r in args.source], args.output)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
