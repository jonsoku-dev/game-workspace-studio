#!/usr/bin/env python3
"""Export registered, graph-pinned Studio products through an installed engine adapter."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import uuid

import graph
import runtime_inputs
import workspace_graph


ENGINES = {'godot': 'godot/export.py', 'three': 'web/export.py',
           'phaser': 'web/phaser/export.py', 'unity': 'unity/export.py'}


def _adapter(engine):
    path = Path(__file__).resolve().parents[1] / 'engines' / ENGINES[engine]
    spec = importlib.util.spec_from_file_location('studio_export_' + engine, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export_game(engine, project, workspace, sources, out, *, three_package=None,
                phaser_package=None, blender=None):
    manifest = Path(workspace).resolve(strict=True)
    _, registered = workspace_graph.registered_projects(manifest)
    def member(name):
        path = (manifest.parent / name).resolve(strict=True)
        if path not in registered:
            raise ValueError('Export projects must be registered in the workspace')
        return path
    project = member(project)
    if engine not in ENGINES:
        raise ValueError('Unknown engine')
    output = graph._local(project, str(out))
    key = 'export-' + uuid.uuid4().hex
    work = {'id': key, 'agent': 'studio-engine-export', 'label': 'Export ' + engine,
            'status': 'error'}
    phase = 'admission'
    try:
        if os.path.lexists(output):
            raise ValueError('Output must not exist')
        if output.is_relative_to(project / '.game-studio'):
            raise ValueError('Output must not use Studio graph storage')
        if (three_package is not None and engine != 'three' or
                phaser_package is not None and engine != 'phaser' or
                blender is not None and engine != 'unity'):
            raise ValueError('Package/converter option does not match engine')
        sources = [(member(p), r) for p, r in sources]
        if not sources or len(set(sources)) != len(sources):
            raise ValueError('Provide distinct registered runtime sources')
        if engine == 'phaser' and len(sources) != 1:
            raise ValueError('Phaser requires exactly one source')
        unified = workspace_graph.export_workspace(manifest)
        by_id = {n['@id']: n for n in unified['@graph']}
        local_ids = {n['@id'] for n in graph.export_graph(project)['@graph']}
        adapter = _adapter(engine)
        phase = 'engine-export'
        with runtime_inputs.output_stage(output) as stage:
            payload = stage / 'payload'
            if engine == 'phaser':
                adapter.export(*sources[0], payload, phaser_package=phaser_package)
            else:
                options = {}
                if three_package is not None:
                    options['three'] = Path(three_package)
                if blender is not None:
                    options['blender'] = str(blender)
                adapter.export(sources, payload, **options)
            for path in payload.iterdir():
                path.rename(stage / path.name)
            payload.rmdir()
            phase = 'receipt-validation'
            media = stage / 'Assets/StreamingAssets/Studio' if engine == 'unity' else stage
            provenance = json.loads((media / 'provenance.json').read_text())
            receipt = json.loads((media / ('game.json' if engine == 'phaser' else 'products.json')).read_text())
            products = [receipt] if engine == 'phaser' else receipt['products'] if engine == 'unity' else receipt
            used = set()
            for product in products:
                pin = product['runtime_pin']
                node = by_id.get(pin['@id'])
                if not node or 'RuntimeProduct' not in node['@type'] or any(node.get(k) != pin.get(k) for k in ('sha256', 'byteCount')):
                    raise ValueError('Engine runtime receipt does not match registered graph')
                used.add(pin['@id'])
            for relative, pin in provenance.items():
                path = graph._local(media, relative)
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
                    raise ValueError('Engine provenance content mismatch')
                if 'artifact' in pin:
                    node = by_id.get(pin['artifact'])
                    if not node or 'Entity' not in node['@type'] or node.get('sha256') != pin['sha256'] or node.get('byteCount') != path.stat().st_size:
                        raise ValueError('Engine artifact receipt does not match registered graph')
                    used.add(pin['artifact'])
            inventory = []
            for path in sorted(stage.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Engine output must be self-contained without symlinks')
                if path.is_file():
                    inventory.append({'path': path.relative_to(stage).as_posix(),
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                      'byteCount': path.stat().st_size})
            record = {'schema_version': 1, 'engine': engine, 'work_id': key,
                      'inputs': [{k: by_id[i][k] for k in ('@id', 'sha256', 'byteCount')} for i in sorted(used)],
                      'files': inventory}
            (stage / 'engine-export.json').write_text(json.dumps(record, indent=2) + '\n')
        phase = 'graph-recording'
        work.update(status='complete', used=sorted(used & local_ids),
                    workspace_inputs=[{k: by_id[i][k] for k in ('@id', 'sha256', 'byteCount')} for i in sorted(used - local_ids)],
                    generated=[{'path': p.relative_to(project).as_posix(),
                                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                               for p in sorted(output.rglob('*')) if p.is_file()],
                    verification={'passed': True, 'checks': ['Engine receipts matched registered graph pins',
                                                             'Complete output inventory hashed before publication']})
        ident = graph.record_work(project, work)
        return {'output': str(output), 'activity': ident, 'engine': engine}
    except Exception as error:
        # Adapter exceptions may contain credentials or subprocess output; retain only the safe failure category.
        graph.record_work(project, {'id': key, 'agent': work['agent'], 'label': work['label'], 'status': 'error',
            'verification': {'passed': False, 'checks': [phase, type(error).__name__,
                'Output path exists; inspect ownership before retry' if output.exists() else 'Output was not published; retry after correcting the failure']}})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=ENGINES, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source', nargs=2, action='append', required=True, metavar=('PROJECT', 'RUNTIME'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--three-package', type=Path)
    parser.add_argument('--phaser-package', type=Path)
    parser.add_argument('--blender')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_game(args.engine, args.project, args.workspace, args.source, args.out,
                                    three_package=args.three_package, phaser_package=args.phaser_package,
                                    blender=args.blender)))
    except Exception as error:
        parser.exit(2, 'Engine export failed (' + type(error).__name__ + '); inspect the project graph failure record.\n')


if __name__ == '__main__':
    main()
