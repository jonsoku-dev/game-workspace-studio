#!/usr/bin/env python3
"""Publish an independently authored static web game without executing its source."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import unicodedata
import stat
import uuid

import graph
import runtime_inputs


ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 256
MAX_BYTES = 32 * 1024 * 1024
FORMATS = {'.html', '.css', '.js', '.mjs', '.json', '.png', '.jpg', '.jpeg',
           '.webp', '.gif', '.svg', '.ico', '.wav', '.mp3', '.ogg', '.woff', '.woff2'}
RESERVED = {'feedback.mjs', 'genre.json', 'web-game.json'}


def _relative(value):
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ValueError('Expected a bounded relative web path')
    parts = value.split('/')
    devices = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}
    for component in parts:
        if (not component or len(component) > 100 or component.startswith('.')
                or component.endswith(('.', ' ')) or any(ord(c) < 32 or c in '<>:"\\|?*#%' for c in component)
                or component.split('.')[0].lower() in devices):
            raise ValueError('Unsafe web path')
    return PurePosixPath(value)


def _read(root, relative):
    """Read only regular, single-link files through non-symlink directory descriptors."""
    parts = _relative(relative).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BYTES:
                raise ValueError('Expected a bounded regular file without hardlinks')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                data = stream.read(MAX_BYTES + 1)
            after = os.fstat(descriptor)
            if (len(data) > MAX_BYTES or len(data) != before.st_size
                    or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('Source changed while reading')
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _pin(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'byteCount': len(data)}


def _sources(project):
    sources = {'genre.json': _read(project, 'genre.json')}
    spec = json.loads(sources['genre.json'])
    required = {'schema_version', 'title', 'genre', 'goal', 'controls'}
    if (not isinstance(spec, dict) or not required <= set(spec) or set(spec) - required - {'stages'}
            or type(spec['schema_version']) is not int or spec['schema_version'] != 1
            or any(not isinstance(spec[k], str) or not spec[k].strip() or len(spec[k]) > 4000
                   for k in ('title', 'genre', 'goal', 'controls'))):
        raise ValueError('genre.json requires schema_version 1, title, genre, goal and controls strings')
    if 'stages' in spec:
        stages = spec['stages']
        if not isinstance(stages, list) or not 2 <= len(stages) <= 32:
            raise ValueError('Campaign requires 2 to 32 stages')
        ids = set()
        for stage in stages:
            if (not isinstance(stage, dict) or set(stage) != {'id', 'title', 'objective', 'tactic'}
                    or not isinstance(stage['id'], str) or len(stage['id']) > 64
                    or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', stage['id'])
                    or stage['id'] in ids
                    or any(not isinstance(stage[k], str) or not stage[k].strip() or len(stage[k]) > 4000
                           for k in ('title', 'objective', 'tactic'))):
                raise ValueError('Expected unique stage slugs and bounded title, objective and tactic strings')
            ids.add(stage['id'])
    reserved = RESERVED | ({'campaign.mjs'} if 'stages' in spec else set())
    game = project / 'game'
    if game.is_symlink() or not game.is_dir():
        raise ValueError('Expected game/ source directory')
    seen = set()
    total = len(sources['genre.json'])
    def scan_error(error):
        raise error
    for directory, dirs, files in os.walk(game, followlinks=False, onerror=scan_error):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(game).as_posix()
            _relative(relative)
            folded = unicodedata.normalize('NFC', relative).casefold()
            if (folded in seen or PurePosixPath(folded).parts[0] in reserved
                    or path.is_symlink()):
                raise ValueError('Reserved, conflicting or symlink source path')
            seen.add(folded)
            if len(seen) > MAX_FILES:
                raise ValueError('Too many web source entries')
            if name in dirs:
                continue
            if path.suffix.lower() not in FORMATS:
                raise ValueError('Unsupported web format')
            key = 'game/' + relative
            sources[key] = _read(project, key)
            total += len(sources[key])
            if total > MAX_BYTES:
                raise ValueError('Web sources exceed byte limit')
    if 'game/index.html' not in sources:
        raise ValueError('Expected game/index.html')
    return spec, sources


def export(project, out='build/play'):
    project = Path(project).resolve(strict=True)
    key = 'web-' + uuid.uuid4().hex
    work = {'id': key, 'agent': 'studio-web-game', 'label': 'Publish static web game', 'status': 'error'}
    phase = 'admission'
    output = None
    try:
        relative = _relative(str(out))
        if relative.parts[0].lower() in {'game', 'genre.json'}:
            raise ValueError('Output conflicts with project sources')
        output = project.joinpath(*relative.parts)
        for parent in (output, *output.parents):
            if parent == project:
                break
            if parent.is_symlink():
                raise ValueError('Output must not contain symlinks')
        if os.path.lexists(output):
            raise ValueError('Output must not exist')
        spec, sources = _sources(project)
        runtimes = {name: _read(ROOT, 'engines/web/' + name) for name in
                    (('feedback.mjs', 'campaign.mjs') if 'stages' in spec else ('feedback.mjs',))}
        # Observation admits existing bytes without claiming their authorship.
        observed = graph.record_work(project, {'id': key + '-inputs', 'agent': work['agent'],
            'label': 'Observe static web game inputs', 'status': 'complete', 'files': sorted(sources)})
        pins = {node['path']: node for node in graph.query(project, kind='Artifact')
                if node['@id'].startswith(observed + ':artifact:')}
        for source, data in sources.items():
            if any(pins[source][k] != v for k, v in _pin(data).items()):
                raise ValueError('Input changed before graph observation')
        provenance = {}
        phase = 'static-copy'
        with runtime_inputs.output_stage(output) as stage:
            for source, data in sources.items():
                if _read(project, source) != data:
                    raise ValueError('Input changed during publication')
                destination = source.removeprefix('game/')
                target = stage / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                provenance[destination] = {'source': source, 'artifact': pins[source]['@id'], **_pin(data)}
            for name, data in runtimes.items():
                if _read(ROOT, 'engines/web/' + name) != data:
                    raise ValueError('Installed runtime changed during publication')
                (stage / name).write_bytes(data)
                provenance[name] = {'source': 'studio/engines/web/' + name,
                                    'origin': 'installed-runtime', **_pin(data)}
            receipt = {'schema_version': 1, 'engine': 'web', 'work_id': key,
                       **{k: spec[k] for k in ('title', 'genre', 'goal', 'controls')},
                       **({'stages': spec['stages']} if 'stages' in spec else {}),
                       'index': (relative / 'index.html').as_posix(), 'provenance': provenance,
                       'files': [{'path': p, **_pin((stage / p).read_bytes())} for p in sorted(provenance)]}
            (stage / 'web-game.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        phase = 'graph-recording'
        generated = []
        hashes = {item['path']: item['sha256'] for item in receipt['files']}
        hashes['web-game.json'] = _pin((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))['sha256']
        for name in [*sorted(provenance), 'web-game.json']:
            path = output / name
            item = {'path': path.relative_to(project).as_posix(), 'sha256': hashes[name]}
            if 'artifact' in provenance.get(name, {}):
                item['wasDerivedFrom'] = [provenance[name]['artifact']]
            generated.append(item)
        work.update(status='complete', used=sorted(p['@id'] for p in pins.values()), generated=generated,
                    verification={'passed': True, 'checks': ['Source bytes verified against observed graph hashes',
                                                             'Static payload copied without executing project source']})
        activity = graph.record_work(project, work)
        return {'output': str(output), 'activity': activity, 'engine': 'web',
                'receipt': str(output / 'web-game.json')}
    except Exception as error:
        graph.record_work(project, {**{k: work[k] for k in ('id', 'agent', 'label')}, 'status': 'error',
            'verification': {'passed': False, 'checks': [phase, type(error).__name__,
                'Output path exists; inspect ownership before retry' if output is not None and output.exists()
                else 'Output was not published; retry after correcting the failure']}})
        raise


def initialize_campaign(project):
    """Create the installed playable starter in a new project, without overwriting work."""
    project = Path(project).absolute()
    with runtime_inputs.output_stage(project) as stage:
        outputs = []
        for name in ('genre.json', 'game/index.html', 'game/game.mjs', 'checks/first-play.json'):
            data = _read(ROOT, 'starter/campaign/' + name)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            outputs.append({'path': name, 'sha256': _pin(data)['sha256']})
        _sources(stage)
        activity = graph.record_work(stage, {'id': 'campaign-' + uuid.uuid4().hex, 'agent': 'studio-web-game',
            'label': 'Initialize playable campaign starter', 'status': 'complete', 'generated': outputs})
    return {'project': str(project), 'activity': activity}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--out', help='New project-relative export directory (default: build/play)')
    action.add_argument('--init-campaign', action='store_true', help='Create a playable two-stage starter in a new project')
    args = parser.parse_args(argv)
    try:
        result = initialize_campaign(args.project) if args.init_campaign else export(args.project, args.out or 'build/play')
        print(json.dumps(result))
    except Exception as error:
        if args.init_campaign:
            parser.exit(2, 'Campaign initialization failed (' + type(error).__name__ + '); use a new project path.\n')
        parser.exit(2, 'Web game export failed (' + type(error).__name__ + '); inspect the project graph failure record.\n')


if __name__ == '__main__':
    main()
