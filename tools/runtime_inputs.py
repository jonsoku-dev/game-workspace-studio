"""Verify local Studio runtime products before a game engine consumes them."""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

import graph


def glb_json(path):
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
        raise ValueError(f'Not a GLB 2: {path}')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or struct.unpack_from('<I', data, 8)[0] != len(data):
        raise ValueError(f'Invalid GLB: {path}')
    return json.loads(data[20:20 + length])


def graph_pins(project, runtime):
    nodes = graph.export_graph(project)['@graph']
    by_id = {n['@id']: n for n in nodes}
    candidates = [n for n in nodes if 'RuntimeProduct' in n.get('@type', []) and n.get('path') == runtime]
    for candidate in candidates:
        runs = [by_id[i] for i in candidate.get('wasGeneratedBy', [])]
        if not any(r.get('record', {}).get('status') == 'ready' for r in runs):
            continue
        if hashlib.sha256((project / runtime).read_bytes()).hexdigest() != candidate['sha256']:
            continue
        # Older reused scenes can point at their original RuntimeProduct.
        # SceneRevision digests identify canonical JSON, not file bytes.
        products = set()
        pending = [candidate]
        seen = set()
        while pending:
            product = pending.pop()
            if product['@id'] in seen:
                continue
            seen.add(product['@id'])
            dependencies = set(product.get('wasDerivedFrom', []))
            for node in nodes:
                if 'ScenePlacement' in node.get('@type', []) and product['@id'] in node.get('partOf', []):
                    dependencies.update(node.get('placementOf', []))
            for ident in dependencies:
                node = by_id[ident]
                if 'RuntimeProduct' in node['@type']:
                    pending.append(node)
                elif 'Artifact' in node['@type']:
                    products.add(ident)
        pins = {runtime: candidate}
        for ident in sorted(products):
            node = by_id[ident]
            if node['path'] in pins and pins[node['path']]['sha256'] != node['sha256']:
                raise ValueError('Conflicting linked artifact pins')
            pins[node['path']] = node
        return pins
    raise ValueError('Runtime has no matching successful SSOT graph pin')


def admit(sources):
    """Validate ready runtime inputs and return product-relative media paths and their pins."""
    prepared = []
    hashes = {}
    for project, runtime in sources:
        project = project.resolve()
        def source(relative):
            if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
                raise ValueError('Expected a project-relative input path')
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
            if asset.get('producer') == 'pixel-effect':
                roles = ['sheet', 'metadata', 'effect']
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
                if relative in hashes:
                    raise ValueError('Duplicate asset destination')
                hashes[relative] = {'source': files[role], '_source': str(original), 'sha256': pins[files[role]]['sha256'], 'artifact': pins[files[role]]['@id']}
                copied[role] = relative
            if 'model' in files and json.loads(pinned(files['validation']).read_text()).get('passed') is not True:
                raise ValueError('Model validation did not pass')
            assets[asset['id']] = copied
        ids = [node['id'] for node in scene['nodes']]
        if len(set(ids)) != len(ids) or any(n['asset'] not in assets or n.get('parent', n['id']) not in ids for n in scene['nodes']):
            raise ValueError('Invalid node/asset/parent reference')
        for node in scene['nodes']:
            for field in ('position', 'rotation_degrees', 'scale'):
                values = node[field]
                if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                    raise ValueError('Invalid node transform')
            seen = {node['id']}
            parent = node.get('parent')
            while parent:
                if parent in seen:
                    raise ValueError('Cyclic node hierarchy')
                seen.add(parent)
                parent = next(n for n in scene['nodes'] if n['id'] == parent).get('parent')
        prepared.append({'scene': scene, 'assets': assets, 'runtime_pin': pins[runtime]})
    return prepared, hashes


def copy_verified(hashes, destination):
    provenance = {}
    for relative, item in hashes.items():
        dest = destination / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = Path(item['_source']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Pinned input changed during export')
        dest.write_bytes(data)
        provenance[relative] = {key: value for key, value in item.items() if key != '_source'}
    return provenance


@contextmanager
def output_stage(output):
    """Prepare a sibling directory and publish it atomically without overwriting another export."""
    output = Path(output).absolute()
    if os.path.lexists(output):
        raise ValueError('Output must not exist')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.engine-export-', dir=output.parent) as temp:
        stage = Path(temp) / 'output'
        stage.mkdir()
        yield stage
        if sys.platform == 'win32':
            stage.rename(output)
            return
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            rename = libc.renameatx_np
            flag = 0x4
        elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
            rename = libc.renameat2
            flag = 1
        else:
            raise RuntimeError('This platform lacks atomic no-replace directory publication')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-1, os.fsencode(stage), -1, os.fsencode(output), flag):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(output))
