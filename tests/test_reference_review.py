from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import graph
import reference_review as review


class ReferenceReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources = self.root / 'sources'
        self.project = self.root / 'project'
        self.sources.mkdir()
        self.project.mkdir()
        (self.sources / '한 글.zip').write_bytes(b'opaque zip bytes; never extract')
        (self.sources / 'nested').mkdir()
        (self.sources / 'nested/ref.txt').write_text('reference')
        (self.project / 'game.txt').write_text('Concrete implemented behavior anchor')
        (self.project / 'resource.bin').write_bytes(b'\x00\xffresource')
        self.mapping = review.inventory(self.sources)

    def save(self):
        (self.project / 'map.json').write_text(json.dumps(self.mapping))

    def applied(self):
        for item in self.mapping['sources']:
            item.update(status='applied', decision='Implemented in project',
                        evidence=[{'path': 'game.txt', 'contains': 'implemented behavior'}])
        self.save()

    def run_review(self):
        self.save()
        return review.review(self.project, self.sources, 'map.json')

    def codes(self, result):
        return {entry['code'] for entry in result['findings']}

    def test_inventory_nested_unicode_zip_and_no_mutation(self):
        (self.sources / '.DS_Store').write_bytes(b'metadata')
        result = review.inventory(self.sources)
        self.assertEqual({item['path'] for item in result['sources']}, {'한 글.zip', 'nested/ref.txt'})
        self.assertTrue(all(item['status'] == 'pending' for item in result['sources']))
        self.assertEqual(list(self.project.iterdir()), [self.project / 'game.txt', self.project / 'resource.bin'])
        self.assertEqual(result['sources'][1]['sha256'], hashlib.sha256((self.sources / '한 글.zip').read_bytes()).hexdigest())

    def test_complete_records_independent_map_evidence_and_immutable_report(self):
        self.applied()
        first = self.run_review()
        self.assertTrue(first['coverage_complete'])
        self.assertTrue(first['recorded'])
        self.assertFalse(first['behavior_verified'])
        self.assertEqual(first['counts']['matched'], 2)
        report = (self.project / first['report']).read_bytes()
        activity = graph.query(self.project, subject=first['activity'])[0]
        nodes = {n['@id']: n for n in graph.export_graph(self.project)['@graph']}
        observation = nodes[first['observation_activity']]
        self.assertEqual(activity['observed'], [observation['@id']])
        self.assertEqual({nodes[target]['path'] for target in observation['observed']}, {'map.json', 'game.txt'})
        self.assertFalse(any(n.get('partOf') == [observation['@id']] and 'Validation' in n['@type'] for n in nodes.values()))
        self.assertEqual(activity['used'], [])
        second = self.run_review()
        self.assertNotEqual(first['report'], second['report'])
        self.assertEqual((self.project / first['report']).read_bytes(), report)

    def test_pending_omission_new_removed_and_source_drift(self):
        self.assertIn('pending', self.codes(self.run_review()))
        self.applied()
        self.mapping['sources'].pop()
        self.assertIn('unmapped', self.codes(self.run_review()))
        self.mapping = review.inventory(self.sources)
        self.applied()
        (self.sources / 'new ref').write_text('new')
        (self.sources / 'nested/ref.txt').unlink()
        (self.sources / '한 글.zip').write_bytes(b'changed')
        self.assertEqual(self.codes(self.run_review()), {'unmapped', 'removed', 'source_changed'})

    def test_duplicate_mapping_and_traversal_never_pass(self):
        self.applied()
        self.mapping['sources'].append(self.mapping['sources'][0].copy())
        self.assertIn('duplicate', self.codes(self.run_review()))
        self.mapping['sources'][0]['path'] = '../outside'
        self.assertIn('invalid_input', self.codes(self.run_review()))

    def test_changed_and_missing_text_evidence(self):
        self.applied()
        (self.project / 'game.txt').write_text('different')
        result = self.run_review()
        self.assertIn('stale_evidence', self.codes(result))
        self.assertEqual(result['findings'][0]['evidence_path'], 'game.txt')
        (self.project / 'game.txt').unlink()
        self.assertIn('stale_evidence', self.codes(self.run_review()))

    def test_binary_evidence_pins_and_digest_drift(self):
        self.applied()
        for item in self.mapping['sources']:
            item['evidence'] = [{'path': 'resource.bin', 'sha256': hashlib.sha256(b'\x00\xffresource').hexdigest()}]
        self.assertTrue(self.run_review()['coverage_complete'])
        (self.project / 'resource.bin').write_bytes(b'changed')
        self.assertIn('stale_evidence', self.codes(self.run_review()))

    def test_deferred_and_unavailable_are_separate_and_not_full_coverage(self):
        self.applied()
        self.mapping['sources'][0].update(status='deferred', decision='User postponed until next iteration', evidence=[])
        self.mapping['unavailable'] = [{'name': 'missing attachment', 'reason': 'Attachment unavailable locally'}]
        result = self.run_review()
        self.assertFalse(result['coverage_complete'])
        self.assertTrue(result['recorded'])
        self.assertEqual(result['counts']['deferred'], 1)
        self.assertEqual(result['counts']['unavailable'], 1)
        self.assertEqual(result['counts']['matched'], 1)
        self.mapping['sources'][0]['decision'] = ''
        self.assertIn('decision_missing', self.codes(self.run_review()))

    def test_source_symlink_directory_hardlink_and_fifo_rejected(self):
        targets = [('link', lambda p: p.symlink_to(self.project, target_is_directory=True)),
                   ('hard', lambda p: os.link(self.sources / '한 글.zip', p)),
                   ('fifo', lambda p: os.mkfifo(p))]
        for name, create in targets:
            with self.subTest(name=name):
                path = self.sources / name
                create(path)
                with self.assertRaises((ValueError, OSError)):
                    review.inventory(self.sources)
                path.unlink()

    def test_evidence_traversal_symlink_and_hardlink_rejected(self):
        self.applied()
        (self.project / 'link').symlink_to(self.project / 'game.txt')
        os.link(self.project / 'resource.bin', self.project / 'hard')
        for path in ('../sources/nested/ref.txt', 'link', 'hard'):
            with self.subTest(path=path):
                self.mapping['sources'][0]['evidence'] = [{'path': path, 'contains': 'reference'}]
                self.assertIn('stale_evidence', self.codes(self.run_review()))

    def test_graph_failure_truthful_and_report_retained(self):
        self.applied()
        with patch.object(graph, 'record_work', side_effect=ValueError('private detail')):
            result = self.run_review()
        self.assertFalse(result['recorded'])
        self.assertFalse(result['coverage_complete'])
        self.assertIn('recording_error', result)
        self.assertNotIn('private detail', json.dumps(result))
        self.assertTrue((self.project / result['report']).exists())

    def test_change_between_verification_and_graph_has_durable_negative_verdict(self):
        self.applied()
        original = graph.record_work
        def changed(project, record):
            (self.project / 'game.txt').write_text('changed before graph snapshot')
            return original(project, record)
        with patch.object(graph, 'record_work', side_effect=changed):
            result = self.run_review()
        self.assertTrue(result['recorded'])
        self.assert_durable_negative(result)
        self.assertIn('observation_changed', self.codes(result))

    def assert_durable_negative(self, result):
        self.assertFalse(result['coverage_complete'])
        report = json.loads((self.project / result['report']).read_text())
        self.assertFalse(report['coverage_complete'])
        works = [n for n in graph.query(self.project, kind='ExternalWork')
                 if n['label'] == 'Review local reference coverage']
        self.assertTrue(all(n['status'] == 'error' for n in works))
        self.assertFalse(any(n['passed'] for n in graph.query(self.project, kind='Validation')))

    def test_source_mutation_at_observation_boundary_is_durably_negative(self):
        self.applied()
        original = graph.record_work
        def changed(project, record):
            if record['id'].endswith('-observations'):
                (self.sources / 'nested/ref.txt').write_text('changed source')
            return original(project, record)
        with patch.object(graph, 'record_work', side_effect=changed):
            result = self.run_review()
        self.assertTrue(result['recorded'])
        self.assert_durable_negative(result)
        self.assertIn('source_changed_during_review', self.codes(result))

    def test_terminal_record_failure_leaves_only_negative_report_and_no_pass(self):
        self.applied()
        original = graph.record_work
        def failed(project, record):
            if not record['id'].endswith('-observations'):
                raise ValueError('terminal record unavailable')
            return original(project, record)
        with patch.object(graph, 'record_work', side_effect=failed):
            result = self.run_review()
        self.assertFalse(result['recorded'])
        self.assert_durable_negative(result)
        reports = list((self.project / 'checks').glob('reference-review-*.json'))
        self.assertEqual(reports, [self.project / result['report']])
        self.assertEqual(graph.query(self.project, kind='Validation'), [])

    def test_explicit_root_alias_resolves_but_nested_symlink_does_not(self):
        alias = self.root / 'source-alias'
        alias.symlink_to(self.sources, target_is_directory=True)
        self.assertEqual(review.inventory(alias), self.mapping)
        self.applied()
        project_alias = self.root / 'project-alias'
        project_alias.symlink_to(self.project, target_is_directory=True)
        result = review.review(project_alias, alias, 'map.json')
        self.assertTrue(result['coverage_complete'])
        (self.sources / 'nested/link').symlink_to(self.project / 'game.txt')
        with self.assertRaises(ValueError):
            review.inventory(alias)

    def test_sources_cannot_cover_map_or_review_outputs(self):
        self.applied()
        result = review.review(self.project, self.project, 'map.json')
        self.assertTrue(result['recorded'])
        self.assert_durable_negative(result)
        self.assertIn('source_output_overlap', self.codes(result))
        refs = self.project / 'refs'
        refs.mkdir()
        (refs / 'reference.txt').write_text('reference')
        self.mapping = review.inventory(refs)
        self.applied()
        self.assertTrue(review.review(self.project, refs, 'map.json')['coverage_complete'])

    def test_project_sources_cannot_be_their_own_application_evidence(self):
        refs = self.project / 'refs'
        refs.mkdir()
        content = b'Concrete implementation copied into runtime'
        (refs / 'source.txt').write_bytes(content)
        self.mapping = review.inventory(refs)
        item = self.mapping['sources'][0]
        item.update(status='applied', decision='Implemented reference requirement',
                    evidence=[{'path': 'refs/source.txt', 'contains': 'Concrete implementation'}])
        self.save()
        result = review.review(self.project, refs, 'map.json')
        self.assert_durable_negative(result)
        self.assertIn('stale_evidence', self.codes(result))
        (self.project / 'runtime.txt').write_bytes(content)
        item['evidence'] = [{'path': 'runtime.txt', 'sha256': hashlib.sha256(content).hexdigest()}]
        self.save()
        result = review.review(self.project, refs, 'map.json')
        self.assertTrue(result['coverage_complete'])
        self.assertTrue(result['recorded'])

    def test_source_entry_bound_rejects_before_full_directory_sort(self):
        with patch.object(review, 'MAX_ENTRIES', 1):
            with self.assertRaises(ValueError):
                review.inventory(self.sources)

    def test_map_symlink_and_duplicate_json_keys_are_recorded_as_invalid(self):
        (self.project / 'map.json').symlink_to(self.sources / 'nested/ref.txt')
        result = review.review(self.project, self.sources, 'map.json')
        self.assertTrue(result['recorded'])
        self.assertIn('invalid_input', self.codes(result))
        (self.project / 'map.json').unlink()
        (self.project / 'map.json').write_text('{"schema_version":1,"schema_version":1,"sources":[],"unavailable":[]}')
        result = review.review(self.project, self.sources, 'map.json')
        self.assertTrue(result['recorded'])
        self.assertIn('invalid_input', self.codes(result))

    def test_linked_graph_storage_not_written(self):
        self.applied()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.project / '.game-studio').symlink_to(outside, target_is_directory=True)
        result = self.run_review()
        self.assertFalse(result['recorded'])
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_map_attempt_is_recorded(self):
        result = review.review(self.project, self.sources, 'missing.json')
        self.assertFalse(result['coverage_complete'])
        self.assertTrue(result['recorded'])
        self.assertIn('invalid_input', self.codes(result))

    def test_empty_sources_and_oversized_input_not_complete(self):
        self.applied()
        with patch.object(review, 'MAX_FILE_BYTES', 1):
            self.assertFalse(self.run_review()['coverage_complete'])
        for path in self.sources.rglob('*'):
            if path.is_file():
                path.unlink()
        self.mapping = review.inventory(self.sources)
        self.assertIn('empty_sources', self.codes(self.run_review()))

    def test_cli_inventory_and_review_exit_status(self):
        command = [sys.executable, str(Path(review.__file__)), 'inventory', '--sources', str(self.sources)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), self.mapping)
        self.applied()
        command[2:] = ['review', '--sources', str(self.sources), '--project', str(self.project), '--map', 'map.json']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['recorded'])


if __name__ == '__main__':
    unittest.main()
