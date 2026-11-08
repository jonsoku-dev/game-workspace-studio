import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import graph
import review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, duration in [('first', 100), ('second', 140)]:
            (self.root / (name + '.json')).write_text(json.dumps({'actions': {'attack': {'duration_ms': duration}}}))
            scene = {'id': 'game', 'assets': [], 'nodes': [], 'contact_ms': duration}
            record = {'run_id': name, 'status': 'ready', 'scene': 'scene.json', 'runtime': name + '.json', 'steps': []}
            graph.update_run(self.root, record, scene)
        self.criteria = [{'id': 'visual', 'kind': 'technical', 'description': 'Pinned contact timing', 'required': True}]
        self.comparison = review.compare(self.root, 'first', 'second', 'ab', self.criteria)

    def result(self, status='pass', **extra):
        return [{'criterion': 'visual', 'status': status, 'reason': 'Direct frame inspection', **extra}]

    def check(self, key='look', **extra):
        return review.check(self.root, 'ab', key, 'second', 'human-reviewer', self.result(judgement='human', **extra))

    def choose(self, key='adopt', **extra):
        return review.choose(self.root, 'ab', key, 'second', 'human-reviewer', 'Contact timing verified', 'technical-pass', **extra)

    def test_pins_field_diffs_and_graph_projection(self):
        snapshot = self.comparison['snapshot']
        self.assertEqual(snapshot['b']['runtime']['sha256'], graph._digest((self.root / 'second.json').read_bytes()))
        self.assertIn({'path': '/runtime/actions/attack/duration_ms', 'a': 100, 'b': 140}, snapshot['diff'])
        self.assertIn({'path': '/scene/contact_ms', 'a': 100, 'b': 140}, snapshot['diff'])
        self.assertEqual(graph.query(self.root, kind='ReviewComparison'), [self.comparison])
        self.assertEqual(review.compare(self.root, 'first', 'second', 'ab', self.criteria), self.comparison)
        self.assertIsNone(review.resolve(self.root)['run'])

    def test_all_asset_action_timing_fields_are_compared(self):
        (self.root / 'request.json').write_text('{}')
        scene = {'id': 'game', 'nodes': [], 'assets': [
            {'id': name, 'producer': 'pixel-effect', 'request': 'request.json'} for name in ('hero', 'enemy')]}
        for run_id, offset in [('left', 0), ('right', 20)]:
            assets = []
            for name in ('hero', 'enemy'):
                path = run_id + '-' + name + '.json'
                (self.root / path).write_text(json.dumps({'actions': {'attack': {'contact_ms': 100 + offset}}}))
                assets.append({'id': name, 'files': {'metadata': path}})
            record = {'run_id': run_id, 'status': 'ready', 'scene': 'scene.json', 'runtime': 'first.json', 'assets': assets,
                      'steps': [{'asset': name, 'producer': 'pixel-effect', 'status': 'ready'} for name in ('hero', 'enemy')]}
            graph.update_run(self.root, record, scene)
        comparison = review.compare(self.root, 'left', 'right', 'multiple', self.criteria)
        changes = comparison['snapshot']['diff']
        for name in ('hero', 'enemy'):
            self.assertIn({'path': '/metadata/' + name + ':metadata/actions/attack/contact_ms', 'a': 100, 'b': 120}, changes)

    def test_no_automatic_or_pending_visual_approval(self):
        with self.assertRaisesRegex(ValueError, 'unmet'):
            self.choose()
        visual = [{'id': 'visual', 'kind': 'visual', 'description': 'Contact readability', 'required': True}]
        review.compare(self.root, 'first', 'second', 'visual-only', visual)
        with self.assertRaisesRegex(ValueError, 'human judgement'):
            review.check(self.root, 'visual-only', 'robot', 'second', 'agent', self.result())
        review.check(self.root, 'ab', 'pending', 'second', 'agent', self.result('pending'))
        self.check()
        with self.assertRaisesRegex(ValueError, 'unmet'):
            self.choose()
        self.assertFalse(graph.query(self.root, kind='ReviewDecision'))

    def test_failed_evidence_blocks_and_request_changes_is_explicit(self):
        self.check(status='fail')
        with self.assertRaisesRegex(ValueError, 'failed evidence'):
            self.choose()
        decision = review.choose(self.root, 'ab', 'reject', 'second', 'human', 'Contact still slides', 'request-changes')
        self.assertIsNone(decision['snapshot']['active_run'])

    def test_idempotence_supersession_and_cas(self):
        evidence = self.check()
        self.assertEqual(self.check(), evidence)
        first = self.choose()
        self.assertEqual(self.choose(), first)
        self.assertEqual(review.resolve(self.root), {'decision': first['@id'], 'run': None})
        with self.assertRaisesRegex(ValueError, 'decision changed'):
            self.choose('stale')
        second = review.choose(self.root, 'ab', 'changes', 'first', 'human', 'Need another option', 'request-changes', first['@id'])
        self.assertEqual(second['snapshot']['previous'], first['@id'])
        self.assertEqual(review.resolve(self.root)['run'], first['snapshot']['active_run'])
        with self.assertRaisesRegex(ValueError, 'different content'):
            review.choose(self.root, 'ab', 'adopt', 'second', 'other', 'Changed attribution', 'technical-pass')

    def test_concurrent_decisions_have_one_head(self):
        self.check()
        def choose(key):
            try:
                return self.choose(key)['@id']
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(choose, ['one', 'two']))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(len(graph.query(self.root, kind='ReviewDecision')), 1)

    def test_drift_unknown_runs_and_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            review.compare(self.root, 'first', 'missing', 'bad', self.criteria)
        with self.assertRaises(ValueError):
            self.check(evidence=['../escape'])
        (self.root / 'proof.txt').write_text('observed')
        self.check(evidence=['proof.txt'])
        (self.root / 'proof.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'pinned file changed'):
            self.choose()
        (self.root / 'second.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pinned file changed'):
            review.compare(self.root, 'first', 'second', 'new', self.criteria)

    def test_gameplay_requires_exact_verified_export_and_runtime(self):
        import playcheck
        criteria = [{'id': 'play', 'kind': 'gameplay', 'required': True, 'description': 'Miss, contact, win and reset'}]
        comparison = review.compare(self.root, 'first', 'second', 'play', criteria)
        export = self.root / 'export'
        export.mkdir()
        (export / 'game.json').write_text(json.dumps({'playtest': {'hits_to_win': 1},
            'metadata': {'actions': {'attack': {'frames': [{'duration_ms': 100}], 'contact_frame': 1}}},
            'runtime_pin': {'sha256': comparison['snapshot']['b']['runtime']['sha256']}}))
        observations = {'miss': {'hits': 0, 'contactEvents': [{'contact': False}]},
                        'win': {'hits': 1, 'finished': True, 'contactEvents': [
                            {'contact': True, 'start_ms': 100, 'observed_ms': 110}]},
                        'reset': {'hits': 0, 'finished': False, 'contactEvents': [], 'x': 210}}
        report = playcheck.assess(export, 'second', observations)
        proof = self.root / 'play.json'
        proof.write_text(json.dumps(report))
        results = [{'criterion': 'play', 'status': 'pass', 'reason': 'Recorded browser observations', 'evidence': ['play.json']}]
        forged = dict(report, runtime_sha256='0' * 64)
        proof.write_text(json.dumps(forged))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            review.check(self.root, 'play', 'bad', 'second', 'tester', results)
        proof.write_text(json.dumps(report))
        with self.assertRaises((ValueError, KeyError)):
            review.check(self.root, 'play', 'unanchored', 'second', 'tester', results)
        self.assertFalse(graph.query(self.root, kind='ReviewDecision'))

    def test_explicit_supersession_resolves_pending_and_failed_results(self):
        pending = review.check(self.root, 'ab', 'pending', 'second', 'tester', self.result('pending'))
        passing = review.check(self.root, 'ab', 'passing', 'second', 'tester', self.result(),
                               supersedes=[pending['@id']], resolution_reason='Inspection now available')
        self.assertEqual(review.check(self.root, 'ab', 'passing', 'second', 'tester', self.result(),
                         supersedes=[pending['@id']], resolution_reason='Inspection now available'), passing)
        first = self.choose()
        failing = review.check(self.root, 'ab', 'failed', 'second', 'tester', self.result('fail'))
        with self.assertRaisesRegex(ValueError, 'failed evidence'):
            self.choose('blocked', expected_decision=first['@id'])
        with self.assertRaisesRegex(ValueError, 'resolution reason'):
            review.check(self.root, 'ab', 'implicit', 'second', 'tester', self.result(), supersedes=[failing['@id']])
        review.check(self.root, 'ab', 'resolved', 'second', 'tester', self.result(),
                     supersedes=[failing['@id']], resolution_reason='Explicit rerun disproved the previous failure')
        self.choose('rechecked', expected_decision=first['@id'])
        self.assertEqual(len(graph.query(self.root, kind='ReviewEvidence')), 4)

    def test_concurrent_evidence_replacements_do_not_silently_conflict(self):
        pending = review.check(self.root, 'ab', 'pending', 'second', 'tester', self.result('pending'))
        def replace(key):
            try:
                return review.check(self.root, 'ab', key, 'second', 'tester', self.result(),
                                    supersedes=[pending['@id']], resolution_reason='Inspection completed')['@id']
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(replace, ['one', 'two']))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(len(review._active_evidence(self.root, self.comparison, self.comparison['snapshot']['b'])), 1)

    def test_technical_only_cannot_adopt_and_visual_requires_user_attestation(self):
        self.check()
        with self.assertRaisesRegex(ValueError, 'visual and gameplay'):
            review.choose(self.root, 'ab', 'invalid-adopt', 'second', 'person', 'Technical checks pass', 'adopt')
        criteria = [{'id': 'visual', 'kind': 'visual', 'required': True, 'description': 'Human visual acceptance'}]
        review.compare(self.root, 'first', 'second', 'human', criteria)
        with self.assertRaisesRegex(ValueError, 'user-chat'):
            review.check(self.root, 'human', 'agent', 'second', 'agent', self.result(judgement='human'))
        result = self.result(judgement='human', attestation={'source': 'user-chat', 'actor': 'person', 'statement': 'I inspected it and accept the contact.'})
        evidence = review.check(self.root, 'human', 'person', 'second', 'person', result)
        self.assertEqual(evidence['snapshot']['results'][0]['attestation']['actor'], 'person')

    def full_proof(self):
        import playcheck
        candidate = self.comparison['snapshot']['b']
        output = self.root / 'full-export'
        output.mkdir()
        (output / 'game.json').write_text(json.dumps({'playtest': {'hits_to_win': 1},
            'metadata': {'actions': {'attack': {'frames': [{'duration_ms': 100}], 'contact_frame': 1}}},
            'runtime_pin': candidate['runtime']}))
        inventory = [graph._snapshot(output, 'game.json', False)]
        receipt = {'schema_version': 1, 'engine': 'phaser', 'work_id': 'export-proof',
                   'inputs': [{k: candidate['runtime'][k] for k in ('@id', 'sha256', 'byteCount')}], 'files': inventory}
        (output / 'engine-export.json').write_text(json.dumps(receipt))
        generated = [{'path': 'full-export/' + name, 'sha256': graph._digest((output / name).read_bytes())}
                     for name in ('game.json', 'engine-export.json')]
        activity = graph.record_work(self.root, {'id': 'export-proof', 'agent': 'studio-engine-export',
            'label': 'Export phaser', 'status': 'complete', 'used': [candidate['runtime']['@id']], 'generated': generated,
            'verification': {'passed': True, 'checks': ['Unit fixture admitted export']}})
        receipt_artifact = next(n for n in graph.query(self.root, kind='Artifact') if n.get('path') == 'full-export/engine-export.json')
        observations = {'miss': {'hits': 0, 'contactEvents': [{'contact': False}]},
                        'win': {'hits': 1, 'finished': True, 'contactEvents': [{'contact': True, 'start_ms': 100, 'observed_ms': 110}]},
                        'reset': {'hits': 0, 'finished': False, 'contactEvents': [], 'x': 210}}
        report = playcheck.assess(output, 'second', observations)
        browser_id = graph.project_id(self.root) + ':work:browser-proof'
        report.update(export_dir='full-export', export_activity=activity, browser_activity=browser_id, driver='stagehand-mcp',
                      browser_observed_hashes=report['export_hashes'])
        (self.root / 'browser-report.json').write_text(json.dumps(report))
        graph.record_work(self.root, {'id': 'browser-proof', 'agent': 'stagehand-browser', 'status': 'complete',
            'label': 'Unit fixture browser observation (not real browser evidence)',
            'used': [candidate['runtime']['@id'], receipt_artifact['@id']],
            'generated': [{'path': 'browser-report.json', 'sha256': graph._digest((self.root / 'browser-report.json').read_bytes())}],
            'verification': {'passed': True, 'checks': ['Unit fixture only']}})
        return report

    def test_full_adoption_requires_both_anchored_gameplay_and_human_statement(self):
        self.full_proof()
        criteria = [{'id': 'art', 'kind': 'visual', 'required': True, 'description': 'Human visual acceptance'},
                    {'id': 'play', 'kind': 'gameplay', 'required': True, 'description': 'Browser play acceptance'}]
        review.compare(self.root, 'first', 'second', 'full', criteria)
        results = [{'criterion': 'play', 'status': 'pass', 'reason': 'Pinned browser run', 'evidence': ['browser-report.json']},
                   {'criterion': 'art', 'status': 'pass', 'reason': 'Human statement', 'judgement': 'human',
                    'attestation': {'source': 'user-chat', 'actor': 'person', 'statement': 'Fixture human acceptance'}}]
        evidence = review.check(self.root, 'full', 'full-proof', 'second', 'person', results)
        self.assertTrue(any(':work:browser-proof' in ident for ident in evidence['observed']))
        decision = review.choose(self.root, 'full', 'full-adopt', 'second', 'person', 'Both checks inspected', 'adopt')
        self.assertEqual(review.resolve(self.root)['run'], self.comparison['snapshot']['b']['run'])
        self.assertEqual(review.resolve(self.root)['decision'], decision['@id'])
        (self.root / 'full-export/game.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'pinned file changed'):
            review.choose(self.root, 'full', 'after-drift', 'second', 'person', 'Recheck', 'adopt', decision['@id'])

    def test_forged_browser_activity_and_wrong_receipt_input_are_rejected(self):
        report = self.full_proof()
        side = self.comparison['snapshot']['b']
        report['browser_activity'] = graph.project_id(self.root) + ':work:not-a-browser'
        (self.root / 'forged.json').write_text(json.dumps(report))
        with self.assertRaises((ValueError, KeyError)):
            review._gameplay(self.root, side, [graph._snapshot(self.root, 'forged.json', False)])
        report['browser_activity'] = graph.project_id(self.root) + ':work:browser-proof'
        # Even a passing self-assessment cannot substitute its own export receipts.
        report['export_activity'] = graph.project_id(self.root) + ':work:arbitrary'
        with self.assertRaisesRegex(ValueError, 'exact admitted'):
            review._export_anchor(self.root, side, report)

    def test_cli_smoke_in_temporary_project(self):
        command = [sys.executable, str(Path(review.__file__)), '--project', str(self.root)]
        args = self.root / 'compare-args.json'
        args.write_text(json.dumps({'a': 'first', 'b': 'second', 'review_id': 'cli', 'criteria': self.criteria}))
        result = subprocess.run(command + ['compare', '--record', str(args)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        comparison = json.loads(result.stdout)
        args.write_text(json.dumps({'review_id': 'cli', 'check_id': 'cli-proof', 'run_id': 'second', 'actor': 'person',
                                    'results': self.result(judgement='human')}))
        result = subprocess.run(command + ['check', '--record', str(args)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        args.write_text(json.dumps({'review_id': 'cli', 'decision_id': 'cli-choice', 'run_id': 'second', 'actor': 'person',
                                    'reason': 'Inspected', 'outcome': 'technical-pass'}))
        result = subprocess.run(command + ['choose', '--record', str(args)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run(command + ['resolve'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNone(json.loads(result.stdout)['run'])
        self.assertIsNotNone(json.loads(result.stdout)['decision'])


if __name__ == '__main__':
    unittest.main()
