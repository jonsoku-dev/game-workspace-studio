#!/usr/bin/env python3
"""Produce a PNG-to-Rive character and record its Studio project graph."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

import graph


def local(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('Expected a relative path')
    path = root / name
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink paths are not admitted')
    path = path.resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Path escapes its root')
    return path


def read(path, limit):
    """Read one bounded regular file without following leaf links or file aliases."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Expected a regular file without hardlink aliases')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.stat(follow_symlinks=False)
    stable = ('st_ino', 'st_dev', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
    if (len(data) > limit or any(getattr(before, key) != getattr(after, key) for key in stable)
            or current.st_ino != after.st_ino
            or any(getattr(current, key) != getattr(after, key) for key in stable)
            or not stat.S_ISREG(current.st_mode)):
        raise ValueError('Input exceeds its budget or changed during read')
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def work(project, label, status='complete', **fields):
    return graph.record_work(project, {'id': uuid.uuid4().hex, 'label': label,
        'agent': 'studio-character', 'status': status, **fields})


def files_under(root):
    files = []
    for base, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(base) / name
            if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
                raise ValueError('Producer output contains a file alias')
        files.extend(Path(base) / name for name in names if (Path(base) / name).is_file())
    return sorted(files)


def build(project, request_name, output_name):
    project = Path(project).resolve(strict=True)
    output = None
    owned = False
    used = []
    pins = {}
    executed_pins = {}
    invoked = False
    phase = 'admission'
    try:
        request = local(project, request_name)
        output = local(project, output_name)
        if output.relative_to(project).parts[0] == '.game-studio':
            raise ValueError('Output cannot occupy Studio graph storage')
        if os.path.lexists(output):
            raise ValueError('Output must be a fresh project-relative directory')
        raw = read(request, 1_048_576)
        spec = json.loads(raw)
        if (not isinstance(spec, dict) or set(spec) - {'schema_version', 'frames', 'reference', 'source', 'motion_request', 'actions', 'title', 'language'}
                or type(spec.get('schema_version')) is not int or spec.get('schema_version') != 1
                or sum(field in spec for field in ('frames', 'source', 'motion_request')) != 1
                or ('reference' in spec and 'frames' not in spec)):
            raise ValueError('Expected character v1 request with exactly frames, source or motion_request')
        actions = spec.get('actions')
        if (not isinstance(actions, list) or not 1 <= len(actions) <= 32 or any(not isinstance(a, str) or not 1 <= len(a.strip()) <= 80 for a in actions)
                or len(actions) != len(set(actions))):
            raise ValueError('actions requires distinct ordered names')
        if spec.get('language', 'ko') not in ('ko', 'ja') or ('title' in spec and (not isinstance(spec['title'], str) or not spec['title'].strip() or len(spec['title']) > 120)):
            raise ValueError('Expected a nonempty title and language ko or ja')
        pins[request] = raw
        media_size = 0

        def pin(path, media=False):
            nonlocal media_size
            if path == request or (media and path == source and field != 'source'):
                raise ValueError('Source file aliases its JSON request')
            if path not in pins:
                data = read(path, 33_554_432 - media_size if media else 1_048_576)
                pins[path] = data
                if media:
                    media_size += len(data)
            return pins[path]

        field = next(field for field in ('frames', 'source', 'motion_request') if field in spec)
        source = local(request.parent, spec[field])
        pin(source, media=field == 'source')
        if field == 'frames':
            manifest = json.loads(pins[source])
            if not isinstance(manifest, dict) or not isinstance(manifest.get('actions'), dict):
                raise ValueError('Expected a pose manifest with named actions')
            selected = {}
            frame_count = 0
            for action in actions:
                entry = manifest['actions'][action]
                if (not isinstance(entry, dict) or set(entry) != {'loop', 'frames'}
                        or type(entry['loop']) is not bool or not isinstance(entry['frames'], list)
                        or not entry['frames']):
                    raise ValueError('Expected an authored action with loop and frames')
                frame_count += len(entry['frames'])
                if frame_count > 256:
                    raise ValueError('Selected actions exceed 256 frames')
                for frame in entry['frames']:
                    if not isinstance(frame, dict) or set(frame) != {'path', 'duration_ms'}:
                        raise ValueError('Expected a PNG path and duration_ms')
                    pin(local(source.parent, frame['path']), media=True)
                selected[action] = entry
            executed_pins[source] = json.dumps({**manifest, 'actions': selected}, ensure_ascii=False).encode()
            if 'reference' in spec:
                pin(local(request.parent, spec['reference']), media=True)
        if field == 'motion_request':
            motion = json.loads(pins[source])
            if (not isinstance(motion, dict) or not isinstance(motion.get('rig'), dict)
                    or not isinstance(motion['rig'].get('parts'), list)
                    or any(not isinstance(part, dict) for part in motion['rig']['parts'])):
                raise ValueError('Expected an authored motion request and rig parts')
            pin(local(source.parent, motion.get('master')), media=True)
            for part in motion['rig']['parts']:
                if 'mask' in part:
                    pin(local(source.parent, part['mask']), media=True)
        executed_pins = {**pins, **executed_pins}
        if any(path == output or path.is_relative_to(output) for path in pins):
            raise ValueError('Output contains a source input')
        names = [p.relative_to(project).as_posix() for p in pins]
        observed = work(project, 'Observe character source inputs', files=names)
        nodes = graph.export_graph(project)['@graph']
        used = [n['@id'] for n in nodes if n['@id'].startswith(observed + ':artifact:')]
        admitted_pins = {n['path']: n for n in nodes if n['@id'] in used}
        if any(read(local(project, p.relative_to(project).as_posix()), max(len(data), 1)) != data or admitted_pins[p.relative_to(project).as_posix()]['sha256'] != sha(data)
               for p, data in pins.items()):
            raise ValueError('Source inputs changed during admission')
        phase = 'discovery'
        launcher = shutil.which('pixel-asset')
        if not launcher:
            raise ValueError('Install pixel-asset with character support')
        phase = 'inputs'
        output.parent.mkdir(parents=True, exist_ok=True)
        if local(project, output_name) != output:
            raise ValueError('Output parent changed during admission')
        output.mkdir(exist_ok=False)
        owned = True
        inputs = output / 'inputs' / 'files'
        inputs.mkdir(parents=True)
        for path, data in executed_pins.items():
            target = inputs / path.relative_to(request.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        executed = inputs / request.name
        if field == 'frames':
            (output / 'inputs' / 'original-frames-manifest.json').write_bytes(pins[source])
        if any(read(local(project, p.relative_to(project).as_posix()), max(len(data), 1)) != data
               for p, data in pins.items()):
            raise ValueError('Source inputs changed before production')
        phase = 'producer'
        invoked = True
        completed = subprocess.run([launcher, 'character', '--request', str(executed), '--out', str(output / 'bundle')],
                                   capture_output=True, text=True, timeout=300)
        phase = 'bundle-validation'
        try:
            result = json.loads(completed.stdout)
        except (ValueError, TypeError):
            raise ValueError('Character producer returned no valid JSON result') from None
        if not isinstance(result, dict) or result.get('status') not in ('ready', 'needs_review'):
            raise ValueError('Character producer failed or returned an invalid status')
        if (result['status'] == 'ready') != (completed.returncode == 0):
            raise ValueError('Character producer status and exit code disagree')
        returned = result.get('files')
        if not isinstance(returned, dict) or not returned:
            raise ValueError('Character producer omitted its output files')
        bundle = output / 'bundle'
        admitted = {}
        for role, name in returned.items():
            path = local(bundle, name)
            if not path.is_file():
                raise ValueError('Character producer returned a missing file')
            admitted[role] = path.relative_to(project).as_posix()
        if result['status'] == 'ready' and not {'character', 'player'} <= admitted.keys():
            raise ValueError('Ready character requires character and player files')
        if any(read(local(project, p.relative_to(project).as_posix()), max(len(data), 1)) != data for p, data in pins.items()):
            raise ValueError('Source inputs changed during production')
        for path, data in executed_pins.items():
            if read(local(inputs, path.relative_to(request.parent).as_posix()), max(len(data), 1)) != data:
                raise ValueError('Pinned execution input changed during production')
        files_under(output)
        response = {**result, 'files': admitted, 'out': output.relative_to(project).as_posix(),
                    'artistic_acceptance': 'pending'}
        if result['status'] == 'needs_review':
            response.update(recoverable=True, next='Review diagnostics and authored frames; retry with a fresh --out directory')
        with (output / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(response, stream, ensure_ascii=False, indent=2)
        generated = [{'path': p.relative_to(project).as_posix(), 'sha256': sha(p.read_bytes()),
                      'wasDerivedFrom': used} for p in files_under(output)]
        response['activity'] = work(project, 'Produce character with pixel-asset character', used=used, generated=generated)
        return response
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        # Failure reports contain bounded diagnostic categories, never producer stderr or request contents.
        response = {'status': 'error', 'message': 'Character production failed; inspect inputs, CLI availability and preserved output.',
                    'phase': phase, 'recoverable': True, 'next': 'Inspect diagnostics and retry with a fresh --out directory'}
        generated = []
        if owned:
            response['out'] = output.relative_to(project).as_posix()
            safe = []
            for base, dirs, names in os.walk(output, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
                safe.extend(Path(base) / n for n in names if not (Path(base) / n).is_symlink() and (Path(base) / n).is_file() and (Path(base) / n).stat().st_nlink == 1)
            diagnostic = output / ('failure-' + uuid.uuid4().hex + '.json')
            with diagnostic.open('x', encoding='utf-8') as stream:
                json.dump(response, stream, ensure_ascii=False, indent=2)
            safe.append(diagnostic)
            generated = [{'path': p.relative_to(project).as_posix(), 'sha256': sha(p.read_bytes())} for p in safe]
        response['activity'] = work(project, 'Character production failed', status='error', used=used if invoked else [], generated=generated)
        return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--request', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.project, args.request, args.out)
    except (OSError, ValueError, KeyError, TypeError):
        result = {'status': 'error', 'message': 'Cannot access the Studio project directory or graph'}
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr if result['status'] == 'error' else sys.stdout)
    return 0 if result['status'] == 'ready' else 2


if __name__ == '__main__':
    sys.exit(main())
