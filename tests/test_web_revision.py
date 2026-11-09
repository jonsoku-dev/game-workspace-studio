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


if __name__ == '__main__':
    unittest.main()
