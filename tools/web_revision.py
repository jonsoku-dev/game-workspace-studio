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


def _diagnostic(error, accepted):
    diagnostic = getattr(error, 'diagnostic', None)
    if not isinstance(diagnostic, dict):
        return None
    categories = {'setup', 'navigation', 'resource', 'page', 'action', 'runner', 'transport', 'export'}
    category, fault, step = diagnostic.get('category'), diagnostic.get('fault'), diagnostic.get('step')
    if not isinstance(category, str) or category not in categories or not isinstance(fault, str) or not re.fullmatch('[a-z_]{1,64}', fault):
        return None
    result = {'category': category, 'fault': fault,
              'step': step if type(step) is int and 0 <= step < 16 else None}
    resource = diagnostic.get('resource')
    if isinstance(resource, str) and accepted is not None:
        try:
            resource = _relative(resource)
            if accepted['directory'] + '/' + resource in accepted['pins']:
                result['resource'] = resource
        except ValueError:
            pass
    observed = diagnostic.get('observed')
    if isinstance(observed, dict):
        state = {key: observed[key] for key in ('found', 'visible', 'enabled', 'disabled', 'connected')
                 if type(observed.get(key)) is bool}
        if type(observed.get('count')) is int and 0 <= observed['count'] <= 10000:
            state['count'] = observed['count']
        rect = observed.get('rect')
        if isinstance(rect, dict) and set(rect) == {'x', 'y', 'width', 'height'} and all(
                type(value) in (int, float) and abs(value) <= 10000000 for value in rect.values()):
            state['rect'] = dict(rect)
        if state:
            result['observed'] = state
    return result


def _next_steps(report):
    if report['passed']:
        return []
    diagnostic = report.get('diagnostic')
    failure = report['checks'].get('after', report['checks'].get('before', {})).get('failed_assertion')
    if diagnostic:
        category, fault, step = diagnostic['category'], diagnostic['fault'], diagnostic['step']
    elif failure:
        action = failure.get('action')
        observed = failure.get('observed', {})
        if action == 'expect_page':
            fault = failure.get('check')
        elif action in {'expect_control', 'expect_layout'}:
            other = observed.get('other', {})
            if observed.get('found') is False or other.get('found') is False:
                fault = 'control_missing'
            elif action == 'expect_control':
                fault = 'control_state_mismatch'
            elif observed.get('visible') is False or other.get('visible') is False:
                fault = 'control_hidden'
            else:
                fault = 'layout_overlap' if failure.get('relation') == 'separate' else 'outside_viewport'
        else:
            fault = 'text_mismatch'
        category, step = 'assertion', failure.get('step')
    else:
        category, fault, step = 'export' if report['phase'] in {'admission', 'final-pins'} else 'runner', 'verification_incomplete', None
    instructions = {
        'control_missing': 'Inspect the declared selector and the preceding step that should create this control.',
        'control_hidden': 'Inspect the control visibility and recorded rectangle; make the intended screen visible before this action.',
        'control_disabled': 'Inspect the disabled state and the preceding prerequisite action before enabling this control.',
        'control_state_mismatch': 'Compare the expected control state with observed visibility and enabled state; inspect hidden/display rules or disabled attributes and the preceding screen transition.',
        'layout_overlap': 'Compare both recorded rectangles; inspect their shared layout, absolute positioning, spacing and wrapping at this viewport width to separate the controls.',
        'outside_viewport': 'Compare the recorded rectangle with the viewport width; inspect fixed widths, min-width, horizontal offsets and container padding.',
        'selector_ambiguous': 'Use a selector that identifies exactly one intended control.',
        'action_failed': 'Inspect the recorded control state and rectangle for an overlay or a blocked interaction.',
        'text_mismatch': 'Compare the expected text with the observed state and trace the preceding action before changing code or the case.',
        'fits_viewport': 'Inspect the reported overflowing element at this viewport width for fixed widths, min-width, padding and unbroken content; rerun at the same width.',
        'respects_hidden': 'Inspect the reported [hidden] element and CSS display overrides; preserve its hidden state before rerunning the check.',
    }
    fallback = {
        'setup': 'Restore the browser and requested viewport, then rerun this case before editing game code.',
        'transport': 'Restore the Stagehand connection and rerun this case; no assertion verdict was obtained.',
        'navigation': 'Inspect local navigation targets and the selected control before rerunning this case.',
        'resource': 'Inspect the pinned local resource and its source reference; do not replace the accepted baseline.',
        'page': 'Inspect the local entry module and initialization for a page error, then rerun the case.',
        'export': 'Inspect the receipt, graph admission and final byte pins; retain existing exports and use a fresh output path.',
        'runner': 'Inspect case syntax and runner availability, then rerun the same pinned case.',
        'action': 'Inspect the declared action and recorded control state, then rerun the case.',
    }
    item = {'category': category, 'fault': fault, 'step': step,
            'instruction': instructions.get(fault, fallback.get(category, fallback['runner']))}
    steps = report.get('steps', [])
    if type(step) is int and 0 <= step < len(steps):
        action = next(iter(steps[step]))
        value = steps[step][action]
        item['action'] = action
        if action == 'expect_page':
            item['check'] = value
            observed = failure.get('observed', {}) if failure else {}
            for name in ('viewport_width', 'scroll_width'):
                width = observed.get(name)
                if type(width) in (int, float) and 0 <= width <= 10000000:
                    item[name] = width
            if isinstance(observed.get('selector'), str) and len(observed['selector']) <= 240:
                item['selector'] = observed['selector']
        else:
            item['selector'] = value if isinstance(value, str) else value['selector']
            if action in {'expect_control', 'expect_layout'}:
                if action == 'expect_control':
                    item['expected_state'] = value['state']
                else:
                    item['relation'] = value['relation']
                    if 'other' in value:
                        item['other'] = value['other']
                item['observed'] = failure.get('observed', {}) if failure else {}
    return [item]


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
            'activity': activity, 'changes': report['changes'], 'output': report.get('output'),
            'next_steps': report.get('next_steps', []),
            **({'asset_review':report['asset_review']} if 'asset_review' in report else {}),
            **({'diagnostic': report['diagnostic']} if 'diagnostic' in report else {})}


def _attempt(project, base, *, out=None, kind=None, reason=None, check=None, operation=None):
    project = Path(project).resolve(strict=True)
    report = {'schema_version': 1, 'id': 'web-revision-' + uuid.uuid4().hex, 'operation': operation or ('build' if out is not None else 'diff'),
              'passed': False, 'status': 'error', 'phase': 'admission', 'changes': [], 'checks': {}}
    used, accepted, current, case_data, case_path, candidate = [], None, None, None, None, None
    case_root = project
    try:
        base = _relative(base)
        report['base'] = base
        accepted = accept_export(project, base)
        used.append(accepted['receipt_artifact'])
        report['base_receipt'] = {'artifact': accepted['receipt_artifact'], **accepted['pins'][base + '/web-game.json']}
        report['plugin'] = _plugin()
        if operation != 'check':
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
        if check is not None or operation == 'check':
            installed = check is None
            case_root = web_game.ROOT if installed else project
            case_path = 'starter/checks/web-health.json' if installed else _relative(check)
            report['case'] = {'origin': 'installed-runtime' if installed else 'project-source', 'path': case_path}
            case_data = web_game._read(case_root, case_path)
            report['case'].update(web_game._pin(case_data))
            if len(case_data) > 65536:
                raise ValueError('Comparison case exceeds limit')
            case = parse_case(case_data)
            report['steps'] = case.get('steps', [])
            if 'viewport' in case:
                report['viewport'] = case['viewport']
        if operation == 'check':
            if case is None:
                raise ValueError('Check requires a case')
            report['phase'] = 'baseline-check'
            result = _check(project, base, case)
            report['checks']['before'] = result
            report.update(passed=result['passed'], status=result['status'])
        elif out is not None:
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
        if operation != 'check':
            report.update(passed=True, status='verified', phase='verified')
    except Exception as error:
        if isinstance(error, web_game.asset_review.AssetFloorError):
            report['asset_review'] = error.review
            report['phase'] = 'asset-review'
            report.pop('output',None)
        report['error'] = {'type': type(error).__name__, 'phase': report['phase']}
        diagnostic = _diagnostic(error, candidate or accepted)
        if diagnostic:
            report['diagnostic'] = diagnostic
        report['status'] = 'operational_error' if operation == 'check' or report['phase'] in {'baseline-check', 'candidate-check'} and (
            'before' if report['phase'] == 'baseline-check' else 'after') not in report['checks'] else 'rejected'
    final_pins = []
    if accepted is not None:
        final_pins.append(('baseline', lambda: accept_export(project, base)['pins'] == accepted['pins']))
    if current is not None:
        final_pins.append(('inputs', lambda: _current(project) == current))
    if candidate is not None:
        final_pins.append(('candidate', lambda: accept_export(project, out)['pins'] == candidate['pins']))
    if case_data is not None:
        final_pins.append(('case', lambda: web_game._read(case_root, case_path) == case_data))
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
            report.update(passed=False, status='operational_error' if operation == 'check' else 'rejected', phase='final-pins')
            report.setdefault('error', {'type': type(error).__name__, 'phase': 'final-pins'})
    report['next_steps'] = ([{'action':'Open asset comparison; repair flagged assets and rebuild.',
                               'board':report['asset_review']['board'],
                               'art_direction':report['asset_review']['art_direction']}]
                            if 'asset_review' in report else _next_steps(report))
    result = _report(project, report, used, case_path if case_data is not None and
                     report.get('case', {}).get('origin') == 'project-source' else None)
    if not report['passed']:
        raise RevisionError(result)
    return result


def diff(project, base):
    return _attempt(project, base)


def build(project, base, out, kind, reason, check=None):
    return _attempt(project, base, out=out, kind=kind, reason=reason, check=check)


def check(project, base, check=None):
    return _attempt(project, base, check=check, operation='check')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('diff', 'build', 'check'):
        command = commands.add_parser(name)
        command.add_argument('--project', type=Path, required=True)
        command.add_argument('--base', required=True)
        if name == 'build':
            command.add_argument('--out', required=True)
            command.add_argument('--kind', choices=('change', 'bugfix'), required=True)
            command.add_argument('--reason', required=True)
            command.add_argument('--check')
        elif name == 'check':
            command.add_argument('--check')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = {'diff': diff, 'build': build, 'check': check}[command](**args)
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
