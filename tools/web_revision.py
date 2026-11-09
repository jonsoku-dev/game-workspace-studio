#!/usr/bin/env python3
"""Compare and verify a fresh static web game revision against an admitted export."""
import argparse
import json
import os
from pathlib import Path
import re
import uuid

import graph
import web_game


class RevisionError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__('Revision failed; inspect ' + result.get('report', 'project graph'))


def parse_case(data):
    from web_regression import parse_case as parse
    return parse(data)


def run_case(project, export_dir, case):
    from web_regression import run_case as run
    return run(project, export_dir, case)


def _relative(value):
    return web_game._relative(str(value)).as_posix()


def _inventory(project, relative):
    root = project / relative
    for parent in (root, *root.parents):
        if parent == project:
            break
        if parent.is_symlink():
            raise ValueError('Export path contains symlink')
    if not root.is_dir():
        raise ValueError('Export directory missing')
    result = {}
    def scan_error(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
        for name in dirs + files:
            path = Path(directory) / name
            local = path.relative_to(project).as_posix()
            _relative(local)
            if path.is_symlink():
                raise ValueError('Export contains symlink')
            if name in files:
                result[local] = web_game._pin(web_game._read(project, local))
            if len(result) > web_game.MAX_FILES + 4:
                raise ValueError('Export inventory exceeds limit')
    return result


def accept_export(project, relative):
    """Admit only bytes pinned by this project's successful web publisher activity."""
    project = Path(project).resolve(strict=True)
    relative = _relative(relative)
    receipt_path = relative + '/web-game.json'
    data = web_game._read(project, receipt_path)
    receipt = json.loads(data)
    if (not isinstance(receipt, dict) or receipt.get('schema_version') != 1 or receipt.get('engine') != 'web'
            or not isinstance(receipt.get('work_id'), str)
            or not re.fullmatch(r'web-[a-f0-9]{32}', receipt['work_id'])
            or receipt.get('index') != relative + '/index.html'
            or not isinstance(receipt.get('files'), list) or not 3 <= len(receipt['files']) <= web_game.MAX_FILES + 3
            or not isinstance(receipt.get('provenance'), dict)):
        raise ValueError('Invalid web export receipt')
    nodes = graph.query(project)
    by_id = {node['@id']: node for node in nodes}
    scope = graph.project_id(project)
    activity_id = scope + ':work:' + receipt['work_id']
    activity = by_id.get(activity_id, {})
    if (activity.get('status') != 'complete' or activity.get('label') != 'Publish static web game'
            or not any(by_id.get(agent, {}).get('label') == 'studio-web-game'
                       for agent in activity.get('wasAssociatedWith', []))
            or by_id.get(activity_id + ':validation', {}).get('passed') is not True):
        raise ValueError('Baseline has no complete web export activity')
    artifacts = {node['path']: node for node in nodes if 'Artifact' in node.get('@type', [])
                 and activity_id in node.get('wasGeneratedBy', [])}
    expected = {receipt_path: web_game._pin(data)}
    served = set()
    for item in receipt['files']:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'byteCount'}
                or not isinstance(item['path'], str) or item['path'] == 'web-game.json'
                or item['path'] in served or not isinstance(item['sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                or type(item['byteCount']) is not int or not 0 <= item['byteCount'] <= web_game.MAX_BYTES):
            raise ValueError('Invalid export asset pin')
        name = _relative(item['path'])
        served.add(name)
        expected[relative + '/' + name] = {key: item[key] for key in ('sha256', 'byteCount')}
    if (set(receipt['provenance']) != served or not {'genre.json', 'index.html', 'feedback.mjs'} <= served
            or set(artifacts) != set(expected) or _inventory(project, relative) != expected):
        raise ValueError('Export inventory differs from receipt or graph')
    for path, pin in expected.items():
        if any(artifacts[path].get(key) != value for key, value in pin.items()):
            raise ValueError('Export graph hash or byte count differs')
    sources = {}
    runtimes = {}
    for name, pin in receipt['provenance'].items():
        if not isinstance(pin, dict) or any(pin.get(k) != expected[relative + '/' + name][k]
                                           for k in ('sha256', 'byteCount')):
            raise ValueError('Export provenance pin differs')
        digest = {key: pin[key] for key in ('sha256', 'byteCount')}
        if pin.get('origin') == 'installed-runtime':
            if name not in {'feedback.mjs', 'campaign.mjs'} or pin.get('source') != 'studio/engines/web/' + name:
                raise ValueError('Unexpected installed runtime')
            runtimes[name] = digest
        else:
            source = 'genre.json' if name == 'genre.json' else 'game/' + name
            artifact = by_id.get(pin.get('artifact'), {})
            if (pin.get('source') != source or artifact.get('path') != source
                    or pin.get('artifact') not in activity.get('used', [])
                    or any(artifact.get(k) != v for k, v in digest.items())):
                raise ValueError('Export source provenance differs')
            sources[source] = digest
    if 'feedback.mjs' not in runtimes:
        raise ValueError('Missing installed feedback runtime')
    return {'directory': relative, 'receipt': receipt, 'receipt_artifact': artifacts[receipt_path]['@id'],
            'pins': expected, 'sources': sources, 'runtimes': runtimes}


def _current(project):
    spec, source_bytes = web_game._sources(project)
    runtime_bytes = {name: web_game._read(web_game.ROOT, 'engines/web/' + name) for name in
                     (('feedback.mjs', 'campaign.mjs') if 'stages' in spec else ('feedback.mjs',))}
    return {'sources': {p: web_game._pin(data) for p, data in source_bytes.items()},
            'runtimes': {p: web_game._pin(data) for p, data in runtime_bytes.items()}}


def _plugin():
    data = web_game._read(web_game.ROOT / '.codex-plugin', 'plugin.json')
    version = json.loads(data).get('version')
    if not isinstance(version, str) or not version or len(version) > 64:
        raise ValueError('Installed plugin manifest requires a bounded version')
    return {'version': version, **web_game._pin(data)}


def _changes(base, current):
    changes = []
    for group, origin in (('sources', 'project-source'), ('runtimes', 'installed-runtime')):
        before, after = base[group], current[group]
        for path in sorted(before.keys() | after.keys()):
            old, new = before.get(path), after.get(path)
            if old != new:
                changes.append({'path': path, 'origin': origin, 'kind': 'add' if old is None else
                                 'delete' if new is None else 'modify', 'from': old, 'to': new})
    return changes


def _check(project, relative, case):
    result = run_case(project, project / relative, case)
    if (not isinstance(result, dict) or type(result.get('passed')) is not bool
            or result.get('status') != ('passed' if result['passed'] else 'assertion_failed')
            or not result['passed'] and not isinstance(result.get('failed_assertion'), dict)):
        raise ValueError('Regression runner did not return a completed assertion result')
    if len(json.dumps(result, ensure_ascii=False).encode()) > 65536:
        raise ValueError('Regression result exceeds report limit')
    return result


def _report(project, report, used, case_path):
    relative = 'checks/' + report['id'] + '.json'
    data = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
    write_error = None
    try:
        if len(data) > 1048576:
            raise ValueError('Revision report exceeds limit')
        directory = project / 'checks'
        directory.mkdir(exist_ok=True)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(report['id'] + '.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
        finally:
            os.close(parent)
    except Exception as error:
        write_error = type(error).__name__
    record = {'id': report['id'], 'agent': 'studio-web-revision', 'label': 'Verify static web game revision',
              'status': 'complete' if report['passed'] and not write_error else 'error', 'used': sorted(set(used)),
              'generated': [] if write_error else [{'path': relative, 'sha256': web_game._pin(data)['sha256']}],
              'verification': {'passed': report['passed'] and not write_error, 'checks':
                  ['report-write-error', write_error] if write_error else [report['phase'],
                  'Structured check outcomes are pinned in ' + relative]}}
    if case_path and report.get('pin_checks', {}).get('case', {}).get('passed'):
        record['files'] = [case_path]
    try:
        activity = graph.record_work(project, record)
    except Exception as error:
        raise RevisionError({'passed': False, 'status': 'graph_error', 'error': type(error).__name__,
                             'report': relative, 'inspect': 'Inspect report and graph before retry; admission may be unknown'}) from error
    if write_error:
        raise RevisionError({'passed': False, 'status': 'report_error', 'error': write_error, 'activity': activity,
                             'inspect': 'Report could not be persisted; inspect checks directory and graph before retry'})
    return {'passed': report['passed'], 'status': report['status'], 'report': relative,
            'activity': activity, 'changes': report['changes'], 'output': report.get('output')}


def _attempt(project, base, *, out=None, kind=None, reason=None, check=None):
    project = Path(project).resolve(strict=True)
    report = {'schema_version': 1, 'id': 'web-revision-' + uuid.uuid4().hex, 'operation': 'build' if out is not None else 'diff',
              'passed': False, 'status': 'error', 'phase': 'admission', 'changes': [], 'checks': {}}
    used, accepted, current, case_data, case_path, candidate = [], None, None, None, None, None
    try:
        base = _relative(base)
        report['base'] = base
        accepted = accept_export(project, base)
        used.append(accepted['receipt_artifact'])
        report['base_receipt'] = {'artifact': accepted['receipt_artifact'], **accepted['pins'][base + '/web-game.json']}
        report['plugin'] = _plugin()
        current = _current(project)
        report['changes'] = _changes(accepted, current)
        if out is not None and not report['changes']:
            raise ValueError('Revision has no source or installed runtime changes')
        if out is not None:
            out = _relative(out)
            if (out == base or out.startswith(base + '/') or base.startswith(out + '/')
                    or out.split('/')[0].casefold() in {'game', 'genre.json', 'checks', '.game-studio'}):
                raise ValueError('Revision output conflicts with protected inputs')
            if os.path.lexists(project / out):
                raise ValueError('Revision output already exists')
            if kind not in {'change', 'bugfix'} or not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
                raise ValueError('Revision requires kind and a bounded nonempty reason')
            report.update(kind=kind, reason=reason, output=out)
            if kind == 'bugfix' and check is None:
                raise ValueError('Bugfix requires a comparison check')
            case = None
            if check is not None:
                case_path = _relative(check)
                case_data = web_game._read(project, case_path)
                if len(case_data) > 65536:
                    raise ValueError('Comparison case exceeds limit')
                case = parse_case(case_data)
                report['case'] = {'path': case_path, **web_game._pin(case_data)}
            if kind == 'bugfix':
                report['phase'] = 'baseline-check'
                report['checks']['before'] = _check(project, base, case)
                if report['checks']['before']['passed']:
                    raise ValueError('Bugfix comparison did not reproduce an assertion failure')
            report['phase'] = 'publish'
            web_game.export(project, out)
            candidate = accept_export(project, out)
            used.append(candidate['receipt_artifact'])
            report['new_receipt'] = {'artifact': candidate['receipt_artifact'], **candidate['pins'][out + '/web-game.json']}
            if candidate['sources'] != current['sources'] or candidate['runtimes'] != current['runtimes']:
                raise ValueError('Published bytes differ from intended revision')
            if case is not None:
                report['phase'] = 'candidate-check'
                report['checks']['after'] = _check(project, out, case)
                if not report['checks']['after']['passed']:
                    raise ValueError('Candidate failed comparison assertion')
        report.update(passed=True, status='verified', phase='verified')
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'phase': report['phase']}
        report['status'] = 'operational_error' if report['phase'] in {'baseline-check', 'candidate-check'} and (
            'before' if report['phase'] == 'baseline-check' else 'after') not in report['checks'] else 'rejected'
    final_pins = []
    if accepted is not None:
        final_pins.append(('baseline', lambda: accept_export(project, base)['pins'] == accepted['pins']))
    if current is not None:
        final_pins.append(('inputs', lambda: _current(project) == current))
    if candidate is not None:
        final_pins.append(('candidate', lambda: accept_export(project, out)['pins'] == candidate['pins']))
    if case_data is not None:
        final_pins.append(('case', lambda: web_game._read(project, case_path) == case_data))
    if 'plugin' in report:
        final_pins.append(('plugin', lambda: _plugin() == report['plugin']))
    report['pin_checks'] = {}
    for name, verify in final_pins:
        try:
            if not verify():
                raise ValueError('Revision bytes changed')
            report['pin_checks'][name] = {'passed': True}
        except Exception as error:
            report['pin_checks'][name] = {'passed': False, 'error': type(error).__name__}
            report.update(passed=False, status='rejected', phase='final-pins')
            report.setdefault('error', {'type': type(error).__name__, 'phase': 'final-pins'})
    result = _report(project, report, used, case_path if case_data is not None else None)
    if not report['passed']:
        raise RevisionError(result)
    return result


def diff(project, base):
    return _attempt(project, base)


def build(project, base, out, kind, reason, check=None):
    return _attempt(project, base, out=out, kind=kind, reason=reason, check=check)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('diff', 'build'):
        command = commands.add_parser(name)
        command.add_argument('--project', type=Path, required=True)
        command.add_argument('--base', required=True)
        if name == 'build':
            command.add_argument('--out', required=True)
            command.add_argument('--kind', choices=('change', 'bugfix'), required=True)
            command.add_argument('--reason', required=True)
            command.add_argument('--check')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = diff(**args) if command == 'diff' else build(**args)
    except RevisionError as error:
        print(json.dumps(error.result, ensure_ascii=False))
        return 2
    except Exception as error:
        print(json.dumps({'passed': False, 'status': 'operational_error', 'error': type(error).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
