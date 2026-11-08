"""Export an admitted Studio mesh scene as a portable, offline web game."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from runtime_inputs import admit, copy_verified, output_stage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
def default_three():
    from scene import model_root
    return model_root() / 'three/node_modules/three'


def validate_effect(data):
    import math
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    def vector(value):
        return isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)
    if (data.get('schema_version') != 1 or data.get('kind') != 'mesh-particles' or
            data.get('units') != 'meters' or not number(data.get('duration_s')) or data['duration_s'] <= 0 or
            not isinstance(data.get('particles'), list) or not 0 < len(data['particles']) <= 256):
        raise ValueError('Invalid mesh-particles descriptor')
    for p in data['particles']:
        if (not all(vector(p.get(k)) for k in ('offset', 'drift', 'spin')) or
                not all(number(p.get(k)) for k in ('start_s', 'life_s', 'scale')) or
                not 0 <= p['start_s'] < data['duration_s'] or not 0 < p['life_s'] <= data['duration_s'] or p['scale'] <= 0):
            raise ValueError('Invalid mesh-particle parameters')


def export(sources, output, three=None):
    products, hashes = admit(sources)
    # The 3D sample consumes mesh products; sprite games have their own Phaser exporter.
    selected = []
    needed = set()
    for product in products:
        assets = {key: {role: path for role, path in files.items() if role in ('model', 'effect', 'validation', 'receipt', 'credits') or role.endswith(('_license', '_notice'))}
                  for key, files in product['assets'].items() if 'model' in files and any(n['asset'] == key for n in product['scene']['nodes'])}
        if not assets:
            continue
        nodes = [node for node in product['scene']['nodes'] if node['asset'] in assets]
        static = [node for node in nodes if 'effect' not in assets[node['asset']]]
        effects = [node for node in nodes if 'effect' in assets[node['asset']]]
        if not static or not effects:
            continue
        if (len(static) != 1 or static[0].get('parent') or static[0]['position'][1] != 0 or
                static[0]['scale'] != [1, 1, 1] or
                any(static[0]['rotation_degrees'][i] != 0 for i in (0, 2)) or
                any(node.get('parent') != static[0]['id'] for node in effects)):
            raise ValueError('Woods Alight requires one ground-level root model with unit scale, Y rotation only, and directly attached mesh effects')
        for files in assets.values():
            needed.update(files.values())
            if 'effect' in files:
                validate_effect(json.loads(Path(hashes[files['effect']]['_source']).read_bytes()))
        selected.append({**product, 'assets': assets, 'scene': {**product['scene'], 'nodes': nodes, 'assets': [{**asset, 'files': assets[asset['id']]} for asset in product['scene']['assets'] if asset['id'] in assets]}})
    if len(selected) != 1:
        raise ValueError('Woods Alight requires exactly one qualifying placed model and mesh-particle scene')
    lock = json.loads((HERE / 'three-lock.json').read_text())
    vendor = {}
    three = (three if three is not None else default_three()).resolve()
    for relative, digest in lock['files'].items():
        path = (three / relative).resolve()
        if not path.is_relative_to(three) or not path.is_file():
            raise ValueError(f'Missing or escaping Three.js dependency: {relative}')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Three.js dependency drift: {relative}')
        vendor[relative] = data
    with output_stage(output) as stage:
        provenance = copy_verified({key: hashes[key] for key in needed}, stage)
        for relative, data in vendor.items():
            path = stage / 'vendor/three' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in ('index.html', 'style.css', 'game.mjs', 'game-state.mjs'):
            (stage / name).write_bytes((HERE / name).read_bytes())
        (stage / 'products.json').write_text(json.dumps(selected, indent=2))
        (stage / 'provenance.json').write_text(json.dumps(provenance, indent=2))
        (stage / 'three-lock.json').write_text(json.dumps(lock, indent=2))
        (stage / 'README.txt').write_text('Woods Alight: serve this folder with python3 -m http.server 8765 --bind 127.0.0.1\nOpen http://127.0.0.1:8765. No installation or internet required.\nWASD/arrows: move. Space: restore/attack. R: restart. Touch buttons supported.\nThree.js MIT licence: vendor/three/LICENSE. Input provenance: provenance.json.\n')
        manifest = {str(p.relative_to(stage)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return selected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', nargs=2, action='append', required=True, metavar=('PROJECT', 'RUNTIME'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--three', type=Path)
    args = parser.parse_args()
    try:
        export([(Path(p), r) for p, r in args.source], args.output, args.three)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
