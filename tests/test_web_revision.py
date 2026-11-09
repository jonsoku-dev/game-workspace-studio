from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import graph
import web_game
import web_revision


class WebRevisionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'genre.json').write_text(json.dumps({
            'schema_version': 1, 'title': 'Test', 'genre': 'puzzle', 'goal': 'Win', 'controls': 'Click'}))
        (self.project / 'game').mkdir()
        (self.project / 'game/index.html').write_text('<button>Old</button>')
        (self.project / 'game/remove.css').write_text('button {color:red}')
        web_game.export(self.project, 'build/base')
        self.base = {p.relative_to(self.project / 'build/base').as_posix(): p.read_bytes()
                     for p in (self.project / 'build/base').rglob('*') if p.is_file()}

    def change(self):
        (self.project / 'game/index.html').write_text('<button>New</button>')

    def records(self):
        return [node for node in graph.query(self.project, kind='ExternalWork')
                if node['label'] == 'Verify static web game revision']

    def report(self, result):
        return json.loads((self.project / result['report']).read_text())

    def build(self, **kwargs):
        return web_revision.build(self.project, 'build/base', 'build/new',
                                  kwargs.pop('kind', 'change'), 'Change label', **kwargs)

    def test_actual_base_cli_diff_and_build_preserve_base_and_record_receipts(self):
        self.change()
        (self.project / 'game/remove.css').unlink()
        (self.project / 'game/add.js').write_text('export const added = true;')
        run = subprocess.run([sys.executable, str(web_game.ROOT / 'tools/web_revision.py'), 'diff',
                              '--project', str(self.project), '--base', 'build/base'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual([(c['path'], c['kind']) for c in result['changes']],
                         [('game/add.js', 'add'), ('game/index.html', 'modify'), ('game/remove.css', 'delete')])
        change = result['changes'][1]
        self.assertEqual(change['from'], web_game._pin(self.base['index.html']))
        self.assertEqual(change['to'], web_game._pin(b'<button>New</button>'))
        built = self.build()
        self.assertTrue(built['passed'])
        report = self.report(built)
        self.assertEqual(len(report['plugin']['sha256']), 64)
        self.assertEqual(report['plugin']['version'], json.loads((web_game.ROOT / '.codex-plugin/plugin.json').read_text())['version'])
        record = graph.query(self.project, subject=built['activity'])[0]
        self.assertEqual(set(record['used']), {report['base_receipt']['artifact'], report['new_receipt']['artifact']})
        self.assertEqual((self.project / 'build/new/index.html').read_text(), '<button>New</button>')
        for path, data in self.base.items():
            self.assertEqual((self.project / 'build/base' / path).read_bytes(), data)
        self.assertEqual(len(self.records()), 2)

    def test_empty_diff_succeeds_but_noop_build_and_existing_output_rejected(self):
        result = web_revision.diff(self.project, 'build/base')
        self.assertTrue(result['passed'])
        self.assertEqual(result['changes'], [])
        with self.assertRaises(web_revision.RevisionError):
            self.build()
        self.change()
        (self.project / 'build/new').mkdir()
        with self.assertRaises(web_revision.RevisionError):
            self.build()
        self.assertEqual(len(self.records()), 3)
        self.assertEqual(sorted(record['status'] for record in self.records()), ['complete', 'error', 'error'])

    def test_fake_tampered_and_extra_baselines_rejected(self):
        self.change()
        shutil.copytree(self.project / 'build/base', self.project / 'build/fake')
        with self.assertRaises(web_revision.RevisionError):
            web_revision.diff(self.project, 'build/fake')
        (self.project / 'build/base/index.html').write_text('tampered')
        with self.assertRaises(web_revision.RevisionError):
            web_revision.diff(self.project, 'build/base')
        (self.project / 'build/base/index.html').write_bytes(self.base['index.html'])
        (self.project / 'build/base/extra.js').write_text('extra')
        with self.assertRaises(web_revision.RevisionError):
            web_revision.diff(self.project, 'build/base')
        self.assertEqual(len(self.records()), 3)

    def test_escape_symlink_and_out_inside_base_rejected(self):
        self.change()
        (self.project / 'linked').symlink_to(self.project / 'build/base', target_is_directory=True)
        for base in ('../escape', 'linked', '/tmp/escape'):
            with self.subTest(base=base), self.assertRaises(web_revision.RevisionError):
                web_revision.diff(self.project, base)
        with self.assertRaises(web_revision.RevisionError):
            web_revision.build(self.project, 'build/base', 'build/base/nested', 'change', 'No')
        (self.project / 'case.json').symlink_to(self.project / 'genre.json')
        with self.assertRaises(web_revision.RevisionError):
            self.build(kind='bugfix', check='case.json')
        self.assertFalse((self.project / 'build/base/nested').exists())

    def case(self):
        (self.project / 'case.json').write_text('{"schema_version":1,"steps":[]}')
        return patch.object(web_revision, 'parse_case', return_value={'case': 'parsed'})

    def test_bugfix_requires_before_assertion_failure_and_after_pass(self):
        self.change()
        before = {'passed': False, 'status': 'assertion_failed', 'failed_assertion': {'selector': 'button'}}
        after = {'passed': True, 'status': 'passed', 'failed_assertion': None}
        with self.case(), patch.object(web_revision, 'run_case', side_effect=[before, after]) as runner:
            result = self.build(kind='bugfix', check='case.json')
        self.assertEqual([call.args[1].name for call in runner.call_args_list], ['base', 'new'])
        self.assertEqual(self.report(result)['checks'], {'before': before, 'after': after})
        self.assertEqual(len(self.records()), 1)

    def test_baseline_pass_or_operational_error_cannot_count_as_bug_reproduction(self):
        self.change()
        for outcome in ({'passed': True, 'status': 'passed'}, TimeoutError('driver unavailable'),
                        {'passed': False, 'status': 'operational_error'}):
            with self.subTest(outcome=outcome), self.case(), patch.object(web_revision, 'run_case') as runner:
                if isinstance(outcome, Exception):
                    runner.side_effect = outcome
                else:
                    runner.return_value = outcome
                with self.assertRaises(web_revision.RevisionError) as error:
                    self.build(kind='bugfix', check='case.json')
                report = self.report(error.exception.result)
                self.assertFalse(report['passed'])
                if outcome == {'passed': True, 'status': 'passed'}:
                    self.assertEqual([s['fault'] for s in report['next_steps']], ['not_reproduced'])
                if isinstance(outcome, TimeoutError):
                    self.assertEqual(report['error']['type'], 'TimeoutError')
                    self.assertNotIn('before', report['checks'])
                    self.assertEqual(report['status'], 'operational_error')
            self.assertFalse((self.project / 'build/new').exists())
        self.assertEqual(len(self.records()), 3)

    def test_candidate_assertion_failure_preserves_candidate_and_negative_report(self):
        self.change()
        failed = {'passed': False, 'status': 'assertion_failed', 'failed_assertion': {'selector': 'button'}}
        with self.case(), patch.object(web_revision, 'run_case', return_value=failed):
            with self.assertRaises(web_revision.RevisionError) as error:
                self.build(check='case.json')
        report = self.report(error.exception.result)
        self.assertEqual(report['checks']['after'], failed)
        self.assertFalse(report['passed'])
        self.assertTrue((self.project / 'build/new/web-game.json').exists())
        self.assertEqual(self.records()[0]['status'], 'error')

    def test_inputs_and_case_changed_by_runner_are_rejected(self):
        self.change()
        def changed(project, directory, case):
            (project / 'case.json').write_text('changed')
            return {'passed': True, 'status': 'passed'}
        with self.case(), patch.object(web_revision, 'run_case', side_effect=changed):
            with self.assertRaises(web_revision.RevisionError) as error:
                self.build(check='case.json')
        self.assertEqual(self.report(error.exception.result)['error']['phase'], 'final-pins')
        self.assertFalse(error.exception.result['passed'])

    def test_runtime_only_change_is_a_revision(self):
        plugin = self.project / 'plugin-fixture'
        (plugin / 'engines/web').mkdir(parents=True)
        (plugin / '.codex-plugin').mkdir()
        (plugin / '.codex-plugin/plugin.json').write_bytes((web_game.ROOT / '.codex-plugin/plugin.json').read_bytes())
        (plugin / 'engines/web/feedback.mjs').write_bytes((web_game.ROOT / 'engines/web/feedback.mjs').read_bytes() + b'\n// runtime fix\n')
        with patch.object(web_game, 'ROOT', plugin):
            result = self.build()
        self.assertEqual(len(result['changes']), 1)
        self.assertEqual(result['changes'][0]['origin'], 'installed-runtime')
        self.assertEqual(result['changes'][0]['path'], 'feedback.mjs')
        self.assertEqual((self.project / 'build/new/index.html').read_bytes(), self.base['index.html'])

    def test_failure_still_rechecks_inputs_and_preserves_negative_outcome(self):
        self.change()
        def changed(project, directory, case):
            (project / 'game/index.html').write_text('unexpected concurrent edit')
            (project / 'case.json').unlink()
            (project / 'case.json').symlink_to(project / 'genre.json')
            return {'passed': False, 'status': 'assertion_failed', 'failed_assertion': {'selector': 'button'}}
        with self.case(), patch.object(web_revision, 'run_case', side_effect=changed):
            with self.assertRaises(web_revision.RevisionError) as error:
                self.build(check='case.json')
        report = self.report(error.exception.result)
        self.assertFalse(report['checks']['after']['passed'])
        self.assertFalse(report['pin_checks']['inputs']['passed'])
        self.assertFalse(report['pin_checks']['case']['passed'])
        self.assertEqual(self.records()[0]['status'], 'error')

    def test_report_directory_symlink_is_rejected_without_writing_through_it(self):
        self.change()
        elsewhere = self.project / 'elsewhere'
        elsewhere.mkdir()
        (self.project / 'checks').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(web_revision.RevisionError) as error:
            web_revision.diff(self.project, 'build/base')
        self.assertEqual(error.exception.result['status'], 'report_error')
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.records()[0]['status'], 'error')

    def test_graph_recording_failure_is_not_reported_as_success_or_retried(self):
        self.change()
        original = graph.record_work
        attempts = []
        def fail(project, record):
            if record['agent'] == 'studio-web-revision':
                attempts.append(record)
                raise RuntimeError('graph failed')
            return original(project, record)
        with patch.object(graph, 'record_work', side_effect=fail):
            with self.assertRaises(web_revision.RevisionError) as error:
                self.build()
        self.assertEqual(error.exception.result['status'], 'graph_error')
        self.assertFalse(error.exception.result['passed'])
        self.assertTrue((self.project / error.exception.result['report']).is_file())
        self.assertTrue((self.project / 'build/new/web-game.json').exists())
        self.assertEqual(len(attempts), 1)

    def test_check_uses_published_export_without_current_sources_or_a_revision(self):
        shutil.rmtree(self.project / 'game')
        (self.project / 'genre.json').unlink()
        passed = {'passed': True, 'status': 'passed', 'observations': [{'step': 0, 'action': 'expect_text'}]}
        with self.case(), patch.object(web_revision, 'run_case', return_value=passed) as runner:
            result = web_revision.check(self.project, 'build/base', 'case.json')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['next_steps'], [])
        report = self.report(result)
        self.assertEqual(report['operation'], 'check')
        self.assertEqual(report['checks']['before'], passed)
        self.assertTrue(report['pin_checks']['case']['passed'])
        self.assertNotIn('inputs', report['pin_checks'])
        self.assertEqual(runner.call_args.args[1], self.project.resolve() / 'build/base')
        self.assertEqual(len(self.records()), 1)
        self.assertFalse((self.project / 'build/new').exists())

    def test_check_assertion_failure_has_actionable_step_and_nonzero_cli_status(self):
        steps = [{'click': 'button'}, {'expect_text': {'selector': 'button', 'contains': 'New'}}]
        (self.project / 'case.json').write_text(json.dumps({'schema_version': 1, 'steps': steps}))
        failed = {'passed': False, 'status': 'assertion_failed', 'observations': [],
                  'failed_assertion': {'step': 1, 'action': 'expect_text', 'selector': 'button',
                                       'observed': {'found': True, 'visible': True, 'text': 'Old'}}}
        with patch.object(web_revision, 'run_case', return_value=failed):
            with patch('builtins.print') as output:
                exit_code = web_revision.main(['check', '--project', str(self.project),
                                              '--base', 'build/base', '--check', 'case.json'])
        self.assertEqual(exit_code, 2)
        result = json.loads(output.call_args.args[0])
        self.assertEqual(result['status'], 'assertion_failed')
        self.assertEqual(result['next_steps'][0]['step'], 1)
        self.assertEqual(result['next_steps'][0]['action'], 'expect_text')
        self.assertEqual(result['next_steps'][0]['selector'], 'button')
        self.assertEqual(self.report(result)['checks']['before'], failed)
        self.assertEqual(self.records()[0]['status'], 'error')

    def test_check_and_build_preserve_only_bounded_operational_diagnostics(self):
        class OperationalFailure(ValueError):
            diagnostic = {'category': 'action', 'step': 0, 'fault': 'control_hidden',
                          'resource': 'index.html', 'message': '/private/secret https://external.invalid',
                          'observed': {'found': True, 'visible': False, 'count': 1,
                                       'rect': {'x': 0, 'y': 0, 'width': 0, 'height': 0},
                                       'text': 'not admitted'}}
        steps = [{'click': 'button'}, {'expect_text': {'selector': 'button', 'contains': 'New'}}]
        (self.project / 'case.json').write_text(json.dumps({'schema_version': 1, 'steps': steps}))
        self.change()
        for operation in ('check', 'build'):
            with self.subTest(operation=operation), patch.object(web_revision, 'run_case', side_effect=OperationalFailure('private')):
                with self.assertRaises(web_revision.RevisionError) as error:
                    if operation == 'check':
                        web_revision.check(self.project, 'build/base', 'case.json')
                    else:
                        self.build(check='case.json')
            result = error.exception.result
            report = self.report(result)
            self.assertEqual(result['status'], 'operational_error')
            self.assertEqual(report['diagnostic']['resource'], 'index.html')
            self.assertEqual(report['diagnostic']['observed']['rect']['width'], 0)
            self.assertNotIn('message', report['diagnostic'])
            self.assertNotIn('text', report['diagnostic']['observed'])
            self.assertEqual(result['next_steps'][0]['fault'], 'control_hidden')
            self.assertEqual(result['next_steps'][0]['action'], 'click')
            self.assertNotIn('private', json.dumps(report))

    def test_diagnostic_omits_unpinned_or_nonlocal_resource_paths(self):
        accepted = web_revision.accept_export(self.project, 'build/base')
        error = ValueError()
        for resource in ('../escape', '/private/secret', 'https://external.invalid/a', 'unlisted.js'):
            error.diagnostic = {'category': 'resource', 'fault': 'http_failure', 'step': None, 'resource': resource}
            self.assertNotIn('resource', web_revision._diagnostic(error, accepted))
        error.diagnostic = {'category': [], 'fault': 'invalid'}
        self.assertIsNone(web_revision._diagnostic(error, accepted))

    def test_check_rechecks_case_and_protects_report_directory(self):
        def changed(project, directory, case):
            (project / 'case.json').write_text('changed')
            return {'passed': True, 'status': 'passed'}
        with self.case(), patch.object(web_revision, 'run_case', side_effect=changed):
            with self.assertRaises(web_revision.RevisionError) as error:
                web_revision.check(self.project, 'build/base', 'case.json')
        self.assertEqual(error.exception.result['status'], 'operational_error')
        self.assertFalse(self.report(error.exception.result)['pin_checks']['case']['passed'])
        shutil.rmtree(self.project / 'checks')
        (self.project / 'elsewhere').mkdir()
        (self.project / 'checks').symlink_to(self.project / 'elsewhere', target_is_directory=True)
        with self.case(), patch.object(web_revision, 'run_case', return_value={'passed': True, 'status': 'passed'}):
            with self.assertRaises(web_revision.RevisionError) as error:
                web_revision.check(self.project, 'build/base', 'case.json')
        self.assertEqual(error.exception.result['status'], 'report_error')
        self.assertEqual(list((self.project / 'elsewhere').iterdir()), [])

    def installed_case(self):
        plugin = self.project / 'installed-plugin'
        (plugin / '.codex-plugin').mkdir(parents=True)
        (plugin / '.codex-plugin/plugin.json').write_bytes((web_game.ROOT / '.codex-plugin/plugin.json').read_bytes())
        (plugin / 'starter/checks').mkdir(parents=True)
        case = {'schema_version': 1, 'viewport': {'width': 390, 'height': 844},
                'steps': [{'expect_page': 'fits_viewport'}, {'expect_page': 'respects_hidden'}]}
        (plugin / 'starter/checks/web-health.json').write_text(json.dumps(case))
        return plugin, case

    def test_default_check_loads_installed_case_without_editing_source_or_observing_foreign_path(self):
        plugin, case = self.installed_case()
        shutil.rmtree(self.project / 'game')
        (self.project / 'genre.json').unlink()
        with patch.object(web_game, 'ROOT', plugin), patch.object(web_revision, 'run_case', return_value={
                'passed': True, 'status': 'passed'}) as runner, patch('builtins.print') as output:
            code = web_revision.main(['check', '--project', str(self.project), '--base', 'build/base'])
        self.assertEqual(code, 0)
        result = json.loads(output.call_args.args[0])
        report = self.report(result)
        self.assertEqual(runner.call_args.args[2], case)
        self.assertEqual(report['case'], {'origin': 'installed-runtime', 'path': 'starter/checks/web-health.json',
                         **web_game._pin((plugin / 'starter/checks/web-health.json').read_bytes())})
        self.assertEqual(report['viewport']['width'], 390)
        self.assertTrue(report['pin_checks']['case']['passed'])
        activity = graph.query(self.project, subject=result['activity'])[0]
        self.assertEqual(activity['observed'], [])
        self.assertEqual(result['changes'], [])
        self.assertFalse((self.project / 'starter').exists())

    def test_default_case_mutation_is_rechecked_even_after_assertion_failure(self):
        plugin, _ = self.installed_case()
        failed = {'passed': False, 'status': 'assertion_failed', 'failed_assertion': {
            'step': 0, 'action': 'expect_page', 'check': 'fits_viewport',
            'observed': {'matched': False, 'viewport_width': 390, 'scroll_width': 650, 'selector': 'main'}}}
        def changed(project, directory, case):
            (plugin / 'starter/checks/web-health.json').write_text('changed')
            return failed
        with patch.object(web_game, 'ROOT', plugin), patch.object(web_revision, 'run_case', side_effect=changed):
            with self.assertRaises(web_revision.RevisionError) as error:
                web_revision.check(self.project, 'build/base')
        report = self.report(error.exception.result)
        self.assertEqual(report['checks']['before'], failed)
        self.assertFalse(report['pin_checks']['case']['passed'])
        self.assertEqual(error.exception.result['status'], 'operational_error')
        self.assertEqual(self.records()[0]['observed'], [])

    def test_expect_page_next_steps_name_fault_element_and_observed_width(self):
        plugin, _ = self.installed_case()
        for step, rule, selector in ((0, 'fits_viewport', 'main'), (1, 'respects_hidden', '#next')):
            failed = {'passed': False, 'status': 'assertion_failed', 'failed_assertion': {
                'step': step, 'action': 'expect_page', 'check': rule,
                'observed': {'matched': False, 'viewport_width': 390, 'scroll_width': 650, 'selector': selector}}}
            with self.subTest(rule=rule), patch.object(web_game, 'ROOT', plugin), patch.object(web_revision, 'run_case', return_value=failed):
                with self.assertRaises(web_revision.RevisionError) as error:
                    web_revision.check(self.project, 'build/base')
            next_step = error.exception.result['next_steps'][0]
            self.assertEqual(next_step['fault'], rule)
            self.assertEqual(next_step['action'], 'expect_page')
            self.assertEqual(next_step['selector'], selector)
            self.assertEqual(next_step['viewport_width'], 390)
            self.assertIn('min-width' if step == 0 else 'display', next_step['instruction'])

    def test_installed_default_case_symlink_is_rejected_before_browser(self):
        plugin, _ = self.installed_case()
        path = plugin / 'starter/checks/web-health.json'
        path.unlink()
        path.symlink_to(self.project / 'genre.json')
        with patch.object(web_game, 'ROOT', plugin), patch.object(web_revision, 'run_case') as runner:
            with self.assertRaises(web_revision.RevisionError) as error:
                web_revision.check(self.project, 'build/base')
        runner.assert_not_called()
        report = self.report(error.exception.result)
        self.assertEqual(report['case']['origin'], 'installed-runtime')
        self.assertEqual(report['status'], 'operational_error')
        self.assertEqual(self.records()[0]['observed'], [])

    def test_layout_and_control_failure_advice_preserves_real_assertion_evidence(self):
        first = {'found': True, 'count': 1, 'visible': True, 'enabled': True,
                 'rect': {'x': 10, 'y': 20, 'width': 100, 'height': 50}}
        second = {**first, 'rect': {'x': 40, 'y': 30, 'width': 100, 'height': 50}}
        fixtures = [
            ({'expect_layout': {'selector': '#retry', 'relation': 'separate', 'other': '#restart'}},
             {**first, 'other': second, 'viewport_width': 390, 'matched': False}, 'layout_overlap'),
            ({'expect_layout': {'selector': '#retry', 'relation': 'inside_viewport'}},
             {**first, 'rect': {'x': 350, 'y': 20, 'width': 100, 'height': 50},
              'viewport_width': 390, 'matched': False}, 'outside_viewport'),
            ({'expect_control': {'selector': '#next', 'state': 'hidden'}},
             {**first, 'matched': False}, 'control_state_mismatch'),
            ({'expect_control': {'selector': '#next', 'state': 'enabled'}},
             {**first, 'enabled': False, 'matched': False}, 'control_state_mismatch'),
            ({'expect_control': {'selector': '#next', 'state': 'visible'}},
             {'found': False, 'count': 0, 'visible': False, 'enabled': False,
              'rect': None, 'matched': False}, 'control_missing'),
            ({'expect_layout': {'selector': '#retry', 'relation': 'separate', 'other': '#restart'}},
             {**first, 'other': {'found': False, 'count': 0, 'visible': False, 'enabled': False, 'rect': None},
              'viewport_width': 390, 'matched': False}, 'control_missing'),
            ({'expect_layout': {'selector': '#retry', 'relation': 'separate', 'other': '#restart'}},
             {**first, 'other': {**second, 'visible': False}, 'viewport_width': 390, 'matched': False}, 'control_hidden'),
        ]
        for assertion, observed, fault in fixtures:
            action, value = next(iter(assertion.items()))
            case = {'schema_version': 1, 'viewport': {'width': 390, 'height': 844}, 'steps': [assertion]}
            (self.project / 'case.json').write_text(json.dumps(case))
            failure = {'step': 0, 'action': action, **value, 'observed': observed}
            verdict = {'passed': False, 'status': 'assertion_failed', 'failed_assertion': failure,
                       'observations': [failure]}
            with self.subTest(action=action, fault=fault), patch.object(web_revision, 'run_case', return_value=verdict):
                with self.assertRaises(web_revision.RevisionError) as error:
                    web_revision.check(self.project, 'build/base', 'case.json')
            advice = error.exception.result['next_steps'][0]
            self.assertEqual(advice['fault'], fault)
            self.assertEqual(advice['selector'], value['selector'])
            self.assertEqual(advice['observed'], observed)
            self.assertNotIn('expected text', advice['instruction'])
            if action == 'expect_control':
                self.assertEqual(advice['expected_state'], value['state'])
            else:
                self.assertEqual(advice['relation'], value['relation'])
                if 'other' in value:
                    self.assertEqual(advice['other'], value['other'])
                    self.assertEqual(advice['observed']['other'], observed['other'])
            self.assertEqual(self.report(error.exception.result)['checks']['before']['failed_assertion'], failure)


if __name__ == '__main__':
    unittest.main()
