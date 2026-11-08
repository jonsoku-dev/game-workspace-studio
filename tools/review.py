#!/usr/bin/env python3
"""Pinned A/B reviews and explicit decisions in the project's JSON-LD graph."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path

import graph


@contextmanager
def _locked(project):
    path = graph._local(project, '.game-studio/review.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('review lock cannot be a symlink')
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _nodes(project):
    return {node['@id']: node for node in graph.export_graph(project)['@graph']}


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' requires nonempty text')
    return value


def _ident(project, kind, key):
    return graph.project_id(project) + ':review:' + kind + ':' + graph._slug(key)


def _find(project, kind, key):
    ident = key if key.startswith('urn:') else _ident(project, kind, key)
    node = _nodes(project).get(ident)
    expected = {'comparison': 'ReviewComparison', 'evidence': 'ReviewEvidence', 'decision': 'ReviewDecision'}[kind]
    if node is None or expected not in node['@type']:
        raise ValueError('unknown ' + kind)
    return node


def _save(project, kind, key, snapshot, references):
    ident = _ident(project, kind, key)
    existing = _nodes(project)
    if ident in existing:
        if existing[ident]['snapshot'] != snapshot:
            raise ValueError('review id already used with different content')
        return existing[ident]
    types = {'comparison': 'ReviewComparison', 'evidence': 'ReviewEvidence', 'decision': 'ReviewDecision'}
    node = graph._node(ident, types[kind], snapshot=snapshot, observed=list(dict.fromkeys(references)),
                       partOf=[graph.project_id(project)], recordedAt=datetime.now(timezone.utc).isoformat())
    document = {'@context': graph.CONTEXT, 'schema_version': 1, '@graph': [node]}
    graph.validate_graph({**document, '@graph': list(existing.values()) + [node]})
    filename = 'review-' + graph._digest(ident.encode()) + '.jsonld'
    graph._atomic(graph._local(project, '.game-studio/runs/' + filename), document, exclusive=True)
    return node


def _verify_pin(project, pin):
    actual = graph._snapshot(project, pin['path'], False)
    if any(actual[field] != pin[field] for field in ('sha256', 'byteCount')):
        raise ValueError('pinned file changed: ' + pin['path'])


def _pin(node):
    return {field: node[field] for field in ('@id', 'path', 'sha256', 'byteCount', 'role') if field in node}


def _candidate(project, run_id):
    nodes = _nodes(project)
    scope = graph.project_id(project)
    ident = run_id if run_id.startswith('urn:') else scope + ':run:' + graph._slug(run_id)
    run = nodes.get(ident, {})
    if 'Run' not in run.get('@type', []) or run.get('status') != 'ready':
        raise ValueError('comparison requires exact ready runs in this project')
    runtime = nodes.get(ident + ':runtime', {})
    if 'RuntimeProduct' not in runtime.get('@type', []):
        raise ValueError('run has no RuntimeProduct')
    revisions = [n for n in nodes.values() if 'RunRevision' in n['@type'] and n.get('revisionOf') == [ident]]
    revision = max(revisions, key=lambda n: n['sequence'])
    scene = next(nodes[target] for target in run['used'] if 'SceneRevision' in nodes[target]['@type'])
    artifacts = [nodes[target] for target in runtime.get('wasDerivedFrom', []) if 'Artifact' in nodes[target]['@type']]
    result = {'run_id': run['record']['run_id'], 'run': ident, 'runtime': _pin(runtime),
              'revision': {'@id': revision['@id'], 'sha256': revision['sha256']},
              'scene': {'@id': scene['@id'], 'sha256': scene['sha256']}, 'artifacts': [_pin(n) for n in artifacts]}
    for pin in [result['runtime']] + result['artifacts']:
        _verify_pin(project, pin)
    content = {'scene': scene['snapshot'], 'runtime': json.loads(graph._local(project, runtime['path']).read_text()), 'metadata': {}}
    # Compare actual action/event timing fields, not only output filenames or hashes.
    for artifact in artifacts:
        if artifact.get('role') in ('metadata', 'effect') or artifact['path'].endswith('.json'):
            owners = [asset['id'] for asset in run['record'].get('assets', [])
                      if artifact['path'] in asset.get('files', {}).values()]
            key = ':'.join(owners + [artifact.get('role', artifact['path'])])
            content['metadata'][key] = json.loads(graph._local(project, artifact['path']).read_text())
    return result, content


def _diff(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for key in sorted(a.keys() | b.keys()):
            child = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in a or key not in b:
                result.append({'path': child, 'a': a.get(key), 'b': b.get(key), 'missing': 'a' if key not in a else 'b'})
            else:
                result.extend(_diff(a[key], b[key], child))
        return result
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [change for index, (left, right) in enumerate(zip(a, b)) for change in _diff(left, right, path + '/' + str(index))]
    return [] if type(a) is type(b) and a == b else [{'path': path, 'a': a, 'b': b}]


def compare(project, a, b, review_id, criteria):
    """Pin ready candidates and scoped acceptance requirements; never approve them."""
    if not isinstance(criteria, list) or not criteria:
        raise ValueError('comparison requires explicit scoped criteria')
    for criterion in criteria:
        if (not isinstance(criterion, dict) or set(criterion) != {'id', 'kind', 'required', 'description'}
                or criterion['kind'] not in ('technical', 'visual', 'gameplay') or type(criterion['required']) is not bool):
            raise ValueError('invalid criterion')
        graph._slug(criterion['id'])
        _text(criterion['description'], 'criterion description')
    if len({c['id'] for c in criteria}) != len(criteria):
        raise ValueError('duplicate criteria')
    with _locked(project):
        left, left_content = _candidate(project, a)
        right, right_content = _candidate(project, b)
        if left['run'] == right['run'] or left['scene']['@id'].split(':scene:')[0] != right['scene']['@id'].split(':scene:')[0]:
            raise ValueError('select two distinct same-project runs')
        snapshot = {'id': review_id, 'a': left, 'b': right, 'criteria': criteria, 'diff': _diff(left_content, right_content)}
        references = [pin['@id'] for side in (left, right) for pin in [side['runtime'], side['revision'], side['scene']] + side['artifacts']]
        return _save(project, 'comparison', review_id, snapshot, references)


def _side(comparison, run_id):
    for side in ('a', 'b'):
        candidate = comparison['snapshot'][side]
        if run_id in (candidate['run_id'], candidate['run']):
            return candidate
    raise ValueError('evidence/decision run must be a compared candidate')


def check(project, review_id, check_id, run_id, actor, results, supersedes=None, resolution_reason=None):
    """Record attributed evidence; visual passes require an explicit human judgement."""
    _text(actor, 'actor')
    with _locked(project):
        comparison = _find(project, 'comparison', review_id)
        side = _side(comparison, run_id)
        criteria = {c['id']: c for c in comparison['snapshot']['criteria']}
        if not isinstance(results, list) or not results:
            raise ValueError('check requires results')
        normalized = []
        proof_references = []
        seen = set()
        for result in results:
            if (not isinstance(result, dict) or set(result) - {'criterion', 'status', 'reason', 'evidence', 'judgement', 'attestation'}
                    or result.get('criterion') not in criteria or result.get('status') not in ('pass', 'fail', 'pending')):
                raise ValueError('invalid criterion result')
            criterion = criteria[result['criterion']]
            if criterion['id'] in seen:
                raise ValueError('duplicate criterion result')
            seen.add(criterion['id'])
            _text(result.get('reason'), 'result reason')
            paths = result.get('evidence', [])
            if not isinstance(paths, list) or len(set(paths)) != len(paths):
                raise ValueError('evidence requires unique project-relative files')
            pins = [graph._snapshot(project, path, False) for path in paths]
            if result['status'] == 'pass':
                if criterion['kind'] == 'visual':
                    _visual(actor, result)
                if criterion['kind'] == 'gameplay':
                    if not pins:
                        raise ValueError('gameplay pass requires pinned actual gameplay evidence')
                    proof_references.extend(_gameplay(project, side, pins))
            normalized.append({**result, 'evidence': pins})
        supersedes = [] if supersedes is None else supersedes
        if not isinstance(supersedes, list) or any(not isinstance(i, str) for i in supersedes) or len(set(supersedes)) != len(supersedes):
            raise ValueError('supersedes requires unique exact evidence IDs')
        snapshot = {'id': check_id, 'comparison': comparison['@id'], 'run': side['run'], 'actor': actor, 'results': normalized,
                    'supersedes': supersedes, 'resolution_reason': resolution_reason}
        ident = _ident(project, 'evidence', check_id)
        if ident in _nodes(project):
            return _save(project, 'evidence', check_id, snapshot, [])
        active = {n['@id']: n for n in _active_evidence(project, comparison, side)}
        if supersedes:
            _text(resolution_reason, 'explicit supersession resolution reason')
        for target in supersedes:
            if target not in active:
                raise ValueError('can supersede only active evidence for the same comparison and candidate')
            previous_criteria = {r['criterion'] for r in active[target]['snapshot']['results']}
            if not previous_criteria <= seen:
                raise ValueError('supersession must replace every previous criterion result')
        return _save(project, 'evidence', check_id, snapshot, [comparison['@id'], side['runtime']['@id']] + supersedes + proof_references)


def _active_evidence(project, comparison, side):
    evidence = [n for n in _nodes(project).values() if 'ReviewEvidence' in n['@type']
                and n['snapshot']['comparison'] == comparison['@id'] and n['snapshot']['run'] == side['run']]
    superseded = {ident for node in evidence for ident in node['snapshot'].get('supersedes', [])}
    return [n for n in evidence if n['@id'] not in superseded]


def _visual(actor, result):
    attestation = result.get('attestation')
    if (result.get('judgement') != 'human' or not isinstance(attestation, dict)
            or set(attestation) != {'source', 'actor', 'statement'}
            or attestation.get('source') != 'user-chat' or attestation.get('actor') != actor):
        raise ValueError('visual pass requires explicit user-chat human judgement attestation')
    _text(attestation['statement'], 'user judgement statement')


def _positive_work(nodes, ident, agent):
    work = nodes.get(ident, {})
    agents = [nodes[target].get('label') for target in work.get('wasAssociatedWith', [])]
    checks = [node for node in nodes.values() if 'Validation' in node['@type'] and node.get('partOf') == [ident]]
    if ('ExternalWork' not in work.get('@type', []) or work.get('status') != 'complete' or agent not in agents
            or not checks or any(node.get('passed') is not True for node in checks)):
        raise ValueError('positive admitted ' + agent + ' activity required')
    return work


def _export_anchor(project, side, report):
    nodes = _nodes(project)
    output = graph._local(project, report['export_dir'])
    receipt_path = str((output / 'engine-export.json').relative_to(Path(project).resolve()))
    receipt = json.loads(graph._local(project, receipt_path).read_text())
    ident = graph.project_id(project) + ':work:' + graph._slug(receipt['work_id'])
    if report.get('export_activity') != ident or receipt.get('schema_version') != 1 or receipt.get('engine') != 'phaser':
        raise ValueError('gameplay report requires exact admitted Phaser export activity/receipt')
    work = _positive_work(nodes, ident, 'studio-engine-export')
    if side['runtime']['@id'] not in work.get('used', []):
        raise ValueError('engine export did not use compared RuntimeProduct')
    generated = {n['path']: n for n in nodes.values() if 'Artifact' in n['@type'] and n.get('wasGeneratedBy') == [ident]}
    receipt_pin = generated.get(receipt_path)
    if receipt_pin is None:
        raise ValueError('engine receipt is not an admitted generated artifact')
    for pin in generated.values():
        _verify_pin(project, pin)
    inputs = receipt.get('inputs', [])
    input_ids = set()
    for pin in inputs:
        node = nodes.get(pin.get('@id'), {})
        if (pin.get('@id') in input_ids or pin.get('@id') not in work.get('used', [])
                or any(node.get(key) != pin.get(key) for key in ('sha256', 'byteCount'))):
            raise ValueError('export input pins do not match admitted inputs')
        input_ids.add(pin['@id'])
        _verify_pin(project, node)
    if side['runtime']['@id'] not in input_ids:
        raise ValueError('receipt did not pin compared RuntimeProduct')
    files = receipt.get('files', [])
    expected = {}
    for pin in files:
        path = graph._local(output, pin['path'])
        relative = str(path.relative_to(Path(project).resolve()))
        admitted = generated.get(relative)
        if relative in expected or admitted is None or any(admitted[key] != pin.get(key) for key in ('sha256', 'byteCount')):
            raise ValueError('export inventory is not anchored in admitted artifacts')
        expected[relative] = admitted['sha256']
    expected[receipt_path] = receipt_pin['sha256']
    actual = {str(path.relative_to(Path(project).resolve())) for path in output.rglob('*') if path.is_file()}
    if actual != set(expected) or any(path.is_symlink() for path in output.rglob('*')):
        raise ValueError('export tree differs from admitted inventory')
    bundle = json.loads((output / 'game.json').read_text())
    runtime_pin = bundle.get('runtime_pin', {})
    if any(runtime_pin.get(key) != side['runtime'][key] for key in ('@id', 'sha256', 'byteCount')):
        raise ValueError('game receipt does not match candidate runtime')
    return output, ident, receipt_pin['@id']


def _browser_anchor(project, side, report_pin, report, receipt):
    if report.get('driver') != 'stagehand-mcp':
        raise ValueError('imported observations are not independently executed browser evidence')
    nodes = _nodes(project)
    ident = report.get('browser_activity')
    if not isinstance(ident, str):
        raise ValueError('admitted browser activity required')
    work = _positive_work(nodes, ident, 'stagehand-browser')
    if not {side['runtime']['@id'], receipt} <= set(work.get('used', [])):
        raise ValueError('browser activity must use compared runtime and exact export receipt')
    canonical = str(graph._local(project, report_pin['path']).relative_to(Path(project).resolve()))
    artifacts = [n for n in nodes.values() if 'Artifact' in n['@type'] and n.get('wasGeneratedBy') == [ident]
                 and n.get('path') == canonical and all(n.get(key) == report_pin[key] for key in ('sha256', 'byteCount'))]
    if len(artifacts) != 1:
        raise ValueError('browser report must be the exact generated artifact of its admitted browser activity')
    _verify_pin(project, artifacts[0])
    return [ident, artifacts[0]['@id']]


def _gameplay(project, side, pins):
    import playcheck
    references = []
    for pin in pins:
        report = json.loads(graph._local(project, pin['path']).read_text())
        if (not isinstance(report, dict) or report.get('schema_version') != 1
                or report.get('run_id') not in (side['run'], side['run_id'])
                or report.get('runtime_sha256') != side['runtime']['sha256'] or report.get('passed') is not True):
            continue
        output, activity, receipt = _export_anchor(project, side, report)
        playcheck.verify(report, output)
        references.extend([activity, receipt])
        references.extend(_browser_anchor(project, side, pin, report, receipt))
    if not references:
        raise ValueError('gameplay evidence does not match pinned candidate')
    return references


def _head(project):
    decisions = [n for n in _nodes(project).values() if 'ReviewDecision' in n['@type']]
    superseded = {n['snapshot']['previous'] for n in decisions}
    heads = [n for n in decisions if n['@id'] not in superseded]
    if len(heads) > 1:
        raise ValueError('conflicting decision heads; reconcile graph before choosing')
    return heads[0] if heads else None


def resolve(project):
    head = _head(project)
    return {'decision': head['@id'] if head else None, 'run': head['snapshot']['active_run'] if head else None}


def choose(project, review_id, decision_id, run_id, actor, reason, outcome, expected_decision=None):
    _text(actor, 'actor')
    _text(reason, 'decision reason')
    if outcome not in ('adopt', 'request-changes', 'technical-pass'):
        raise ValueError('explicit adopt/request-changes/technical-pass outcome required')
    with _locked(project):
        comparison = _find(project, 'comparison', review_id)
        side = _side(comparison, run_id)
        key = _ident(project, 'decision', decision_id)
        old = _nodes(project).get(key)
        if old:
            expected = {'id': decision_id, 'comparison': comparison['@id'], 'run': side['run'], 'actor': actor,
                        'reason': reason, 'outcome': outcome, 'previous': expected_decision}
            if any(old['snapshot'].get(k) != v for k, v in expected.items()):
                raise ValueError('decision id already used with different content')
            return old
        head = _head(project)
        if (head['@id'] if head else None) != expected_decision:
            raise ValueError('decision changed; reread and supply expected_decision')
        evidence = _active_evidence(project, comparison, side)
        if outcome in ('adopt', 'technical-pass'):
            required_kinds = {c['kind'] for c in comparison['snapshot']['criteria'] if c['required']}
            if outcome == 'adopt' and not {'visual', 'gameplay'} <= required_kinds:
                raise ValueError('product adoption requires required visual and gameplay criteria; use technical-pass for scoped checks')
            if outcome == 'technical-pass' and 'technical' not in required_kinds:
                raise ValueError('technical-pass requires required technical criteria')
            if _candidate(project, side['run'])[0] != side:
                raise ValueError('candidate revision changed; create a new comparison')
            results = {}
            for node in evidence:
                for result in node['snapshot']['results']:
                    criterion = next(c for c in comparison['snapshot']['criteria'] if c['id'] == result['criterion'])
                    if outcome == 'adopt' and criterion['kind'] == 'visual' and result['status'] == 'pass':
                        _visual(node['snapshot']['actor'], result)
                    for pin in result['evidence']:
                        _verify_pin(project, pin)
                    results.setdefault(result['criterion'], []).append(result)
            relevant = {c['id'] for c in comparison['snapshot']['criteria']
                        if outcome == 'adopt' or c['kind'] == 'technical'}
            if any(r['status'] == 'fail' for key, values in results.items() if key in relevant for r in values):
                raise ValueError('failed evidence blocks decision; explicitly supersede with resolution rationale')
            for criterion in comparison['snapshot']['criteria']:
                if criterion['id'] not in relevant:
                    continue
                checks = results.get(criterion['id'], [])
                if criterion['required'] and (not checks or any(r['status'] != 'pass' for r in checks)):
                    raise ValueError('required criterion unmet: ' + criterion['id'])
                if criterion['kind'] == 'gameplay':
                    for result in checks:
                        if result['status'] == 'pass':
                            _gameplay(project, side, result['evidence'])
        snapshot = {'id': decision_id, 'comparison': comparison['@id'], 'run': side['run'], 'actor': actor,
                    'reason': reason, 'outcome': outcome, 'previous': expected_decision,
                    'active_run': side['run'] if outcome == 'adopt' else (head['snapshot']['active_run'] if head else None)}
        return _save(project, 'decision', decision_id, snapshot,
                     [comparison['@id'], side['runtime']['@id']] + [n['@id'] for n in evidence] + ([head['@id']] if head else []))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('compare', 'check', 'choose', 'resolve'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--record', type=Path, help='JSON arguments for compare/check/choose')
    args = parser.parse_args(argv)
    try:
        if args.command == 'resolve':
            result = resolve(args.project)
        else:
            if args.record is None:
                raise ValueError('--record is required')
            record = json.loads(args.record.read_text())
            result = globals()[args.command](args.project, **record)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
