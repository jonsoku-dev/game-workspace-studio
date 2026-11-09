#!/usr/bin/env python3
"""Inventory explicit local references and record bounded coverage checks, not behavior approval."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

import graph

MAX_ENTRIES = 2048
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_MAP_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


def _relative(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or value.startswith('/') or '\\' in value
            or any(part in ('', '.', '..') for part in value.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Use a bounded relative path without traversal or control characters')
    return value


def _root(value):
    path = Path(os.path.abspath(value)).resolve(strict=True)
    for component in [*reversed(path.parents), path]:
        info = component.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError('Root and parent directories must be real local directories')
    return path


@contextmanager
def _open(root, name):
    parts = _relative(name).split('/')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('Only regular files with one hard link are accepted')
            yield stream, info
    finally:
        os.close(directory)


def _read(root, name, limit, content=False):
    with _open(root, name) as (stream, before):
        if before.st_size > limit:
            raise ValueError('File exceeds review size limit')
        digest, size, chunks = hashlib.sha256(), 0, []
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError('File exceeds review size limit')
            digest.update(chunk)
            if content:
                chunks.append(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('File changed during review; retry with stable files')
    pin = {'path': name, 'sha256': digest.hexdigest(), 'byteCount': size}
    return (pin, b''.join(chunks)) if content else pin


def inventory(sources):
    root = _root(sources)
    result, total, entries = [], 0, 0
    def walk(directory, prefix=''):
        nonlocal total, entries
        with os.scandir(directory) as children:
            bounded = []
            for child in children:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ValueError('Source folder exceeds entry limit')
                bounded.append(child)
            for child in sorted(bounded, key=lambda entry: entry.name):
                name = prefix + child.name
                _relative(name)
                info = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError('Source folder contains a symlink; remove unsafe entries')
                if child.name in ('.DS_Store', '__MACOSX') or child.name.startswith('._'):
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or info.st_nlink > 1 and stat.S_ISREG(info.st_mode):
                        raise ValueError('Unsafe metadata entry')
                    continue
                if stat.S_ISDIR(info.st_mode):
                    # Open relative to the current descriptor to reject swapped symlink directories.
                    descriptor = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    try:
                        walk(descriptor, name + '/')
                    finally:
                        os.close(descriptor)
                elif stat.S_ISREG(info.st_mode):
                    pin = _read(root, name, MAX_FILE_BYTES)
                    total += pin['byteCount']
                    if total > MAX_TOTAL_BYTES:
                        raise ValueError('Source folder exceeds total byte limit')
                    result.append({'path': name, 'sha256': pin['sha256'], 'status': 'pending', 'decision': '', 'evidence': []})
                else:
                    raise ValueError('Source folder contains a nonregular entry')
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(descriptor)
    finally:
        os.close(descriptor)
    return {'schema_version': 1, 'sources': result, 'unavailable': []}


def _text(value, limit=2048):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _parse(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate map field')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'sources', 'unavailable'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['sources'], list) or len(value['sources']) > MAX_ENTRIES
            or not isinstance(value['unavailable'], list) or len(value['unavailable']) > MAX_ENTRIES):
        raise ValueError('Expected schema_version 1, bounded sources and unavailable lists')
    return value


def _graph_paths(project):
    # graph.py resolves paths; refuse linked graph storage before handing it any writes.
    for relative in ('.game-studio', 'checks'):
        folder = project / relative
        if folder.exists() or folder.is_symlink():
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError('Graph/report storage must be a real directory')
            count = 0
            for directory, dirs, files in os.walk(folder, followlinks=False):
                for name in dirs + files:
                    count += 1
                    info = (Path(directory) / name).lstat()
                    if count > 20000 or stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                        raise ValueError('Unsafe or excessive graph/report storage')


def review(project, sources, map_path):
    project = _root(project)
    key = 'reference-review-' + str(uuid.uuid4())
    report = {'schema_version': 1, 'coverage_complete': False, 'behavior_verified': False,
              'coverage_basis': 'Pinned map/evidence observation and final source inventory; not continuous monitoring',
              'counts': {'sources': 0, 'matched': 0, 'deferred': 0, 'pending': 0, 'unavailable': 0},
              'findings': [], 'deferred': [], 'unavailable': [], 'source_pins': [], 'map_pin': None, 'evidence_pins': []}
    pins = {}
    def finding(path, code, action, evidence_path=None):
        item = {'path': path, 'code': code, 'action': action}
        if evidence_path is not None:
            item['evidence_path'] = evidence_path
        report['findings'].append(item)
    source_root = None
    try:
        source_root = _root(sources)
        map_local = project / _relative(map_path)
        outputs = [project / 'checks', project / '.game-studio']
        if (map_local.is_relative_to(source_root)
                or any(source_root.is_relative_to(path) or path.is_relative_to(source_root) for path in outputs)):
            finding('', 'source_output_overlap', 'Select a distinct input-only source folder outside map, checks and .game-studio storage')
            raise ValueError('Source/output overlap')
        actual = {item['path']: item for item in inventory(source_root)['sources']}
        report['counts']['sources'] = len(actual)
        report['source_pins'] = [{'path': item['path'], 'sha256': item['sha256']} for item in actual.values()]
        map_pin, data = _read(project, map_path, MAX_MAP_BYTES, True)
        report['map_pin'] = map_pin
        mapping = _parse(data)
        seen = set()
        for item in mapping['sources']:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'status', 'decision', 'evidence'}:
                raise ValueError('Each source requires path, sha256, status, decision and evidence')
            name = _relative(item['path'])
            if name in seen:
                finding(name, 'duplicate', 'Keep exactly one map entry for this source')
                continue
            seen.add(name)
            if name not in actual:
                finding(name, 'removed', 'Restore the source or explicitly reconcile its removal in the map')
                continue
            if not _digest(item['sha256']) or item['sha256'] != actual[name]['sha256']:
                finding(name, 'source_changed', 'Review the current source and update its digest, decision and evidence')
                continue
            status = item['status']
            if status == 'pending':
                report['counts']['pending'] += 1
                finding(name, 'pending', 'Apply with concrete evidence or defer with an explicit reason')
                continue
            if not _text(item['decision']):
                finding(name, 'decision_missing', 'Write a nonempty application decision or deferral reason')
                continue
            if status == 'deferred':
                report['counts']['deferred'] += 1
                report['deferred'].append({'path': name, 'reason': item['decision']})
                continue
            evidence = item['evidence']
            if status != 'applied' or not isinstance(evidence, list) or not 1 <= len(evidence) <= 16:
                finding(name, 'evidence_missing', 'Mark applied with 1..16 concrete project-local evidence anchors')
                continue
            valid = True
            for anchor in evidence:
                path = None
                try:
                    if not isinstance(anchor, dict) or set(anchor) not in ({'path', 'contains'}, {'path', 'sha256'}):
                        raise ValueError('Invalid evidence')
                    path = _relative(anchor['path'])
                    if (path == map_path or path.startswith(('.game-studio/', 'checks/reference-review-'))
                            or (project / path).is_relative_to(source_root)):
                        raise ValueError('Review evidence must be independent of raw source inputs')
                    pin, content = _read(project, path, MAX_EVIDENCE_BYTES, True)
                    if 'contains' in anchor:
                        if not _text(anchor['contains'], 1024) or anchor['contains'] not in content.decode('utf-8'):
                            raise ValueError('Text anchor missing')
                    elif not _digest(anchor['sha256']) or anchor['sha256'] != pin['sha256']:
                        raise ValueError('Evidence digest changed')
                    pins[path] = pin
                except (OSError, ValueError, UnicodeError):
                    valid = False
                    finding(name, 'stale_evidence', 'Restore or replace missing, unsafe or changed evidence and rerun review', path)
            if valid:
                report['counts']['matched'] += 1
        for name in sorted(actual.keys() - seen):
            finding(name, 'unmapped', 'Add this source to the map and apply it with evidence or defer with a reason')
        for item in mapping['unavailable']:
            if (not isinstance(item, dict) or set(item) != {'name', 'reason'}
                    or not _text(item['name'], 240) or '/' in item['name'] or '\\' in item['name']
                    or not _text(item['reason'])):
                raise ValueError('Unavailable sources require a short name and explicit reason')
            report['unavailable'].append(item)
        report['counts']['unavailable'] = len(report['unavailable'])
        if not actual:
            finding('', 'empty_sources', 'Provide the explicit local source files before claiming coverage')
        report['coverage_complete'] = bool(actual) and not report['findings'] and not report['unavailable'] and not report['deferred']
    except (OSError, ValueError, TypeError, RecursionError):
        finding('', 'invalid_input', 'Check the source folder and map schema, paths, limits and file permissions')
    report['evidence_pins'] = list(pins.values())
    observation = None
    recording_error = None
    try:
        _graph_paths(project)
        observed = list(dict.fromkeys(([map_path] if report['map_pin'] else []) + list(pins)))
        observation = graph.record_work(project, {
            'id': key + '-observations', 'label': 'Observe local reference map and evidence',
            'agent': 'studio-reference-review', 'status': 'complete', 'files': observed})
        nodes = {node['path']: node for node in graph.query(project, kind='Artifact')
                 if node['@id'].startswith(observation + ':artifact:')}
        for pin in ([report['map_pin']] if report['map_pin'] else []) + list(pins.values()):
            if any(nodes[pin['path']][field] != pin[field] for field in ('sha256', 'byteCount')):
                finding(pin['path'], 'observation_changed', 'Restore stable map/evidence and rerun; independent graph observation differs')
                report['coverage_complete'] = False
        if report['source_pins']:
            current = [{'path': item['path'], 'sha256': item['sha256']} for item in inventory(source_root)['sources']]
            if current != report['source_pins']:
                finding('', 'source_changed_during_review', 'Keep the entire input-only source folder stable and rerun review')
                report['coverage_complete'] = False
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        report['coverage_complete'] = False
        recording_error = 'Graph observation failed; repair local storage or unstable evidence and rerun'
        finding('', 'observation_failed', 'Repair graph storage or unstable source/map/evidence files and rerun')

    relative = 'checks/' + key + '.json'
    activity = None
    report_written = False
    try:
        _graph_paths(project)
        graph._atomic(graph._local(project, relative), report, exclusive=True)
        report_written = True
        activity = graph.record_work(project, {
            'id': key, 'label': 'Review local reference coverage', 'agent': 'studio-reference-review',
            'status': 'complete' if report['coverage_complete'] else 'error',
            'observed': [observation] if observation else [],
            'generated': [{'path': relative, 'sha256': _read(project, relative, MAX_EVIDENCE_BYTES)['sha256']}],
            'verification': {'passed': report['coverage_complete'], 'checks': ['Local source coverage only; behavior is not verified']}})
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        recording_error = 'Graph recording failed; repair local graph/report storage and rerun'
        # Only discard our own unadmitted report; admitted immutable reports are never rewritten.
        admitted = None
        try:
            if (project / '.game-studio/project.json').is_file():
                admitted = graph.project_id(project) + ':work:' + key
            node = graph.query(project, subject=admitted) if admitted else []
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            node = []
        if node:
            activity = admitted
        else:
            report['coverage_complete'] = False
            finding('', 'recording_failed', 'Repair graph storage and rerun; no terminal coverage pass was admitted')
            if report_written:
                graph._local(project, relative).unlink()
            relative = 'checks/' + key + '-failed.json'
            try:
                _graph_paths(project)
                graph._atomic(graph._local(project, relative), report, exclusive=True)
            except (OSError, ValueError):
                pass
    result = {'report': relative, **report, 'recorded': activity is not None, 'activity': activity,
              'observation_activity': observation}
    if recording_error:
        result['recording_error'] = recording_error
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'review'))
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--map', dest='map_path')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inventory':
            result = inventory(args.sources)
        else:
            if args.project is None or args.map_path is None:
                raise ValueError('Review requires --project and project-relative --map')
            result = review(args.project, args.sources, args.map_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if args.command == 'inventory' or result['coverage_complete'] and result['recorded'] else 1
    except (OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({'error': 'Invalid or unsafe local input; check paths, schema and size limits'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
