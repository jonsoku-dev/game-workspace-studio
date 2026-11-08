import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import export_game
import graph
import workspace_graph


class EngineDispatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'game'
        self.source.mkdir()
        self.manifest = self.root / 'workspace.json'
        self.manifest.write_text(json.dumps({'schema_version': 1, 'workspace_id': str(uuid.uuid4()),
                                             'projects': ['.', 'game']}))
        graph.record_work(self.root, {'id': 'plan', 'agent': 'studio', 'status': 'complete', 'label': 'Plan'})
        self.scene = {'id': 'sample', 'assets': [], 'nodes': []}
        self.runtime = {'schema_version': 1, 'status': 'ready', 'assets': [], 'nodes': [],
                        'coordinates': {'units': 'meters', 'up': '+Y', 'handedness': 'right'}}
        (self.source / 'runtime.json').write_text(json.dumps(self.runtime))
        record = {'run_id': 'ready', 'status': 'ready', 'scene': 'scene.json', 'assets': [],
                  'steps': [], 'runtime': 'runtime.json'}
        graph.update_run(self.source, record, self.scene)

    def export(self, out='exports/godot', **kwargs):
        return export_game.export_game('godot', '.', self.manifest, [('game', 'runtime.json')], out, **kwargs)

    def test_actual_godot_export_pins_foreign_runtime_and_inventory(self):
        before = self.manifest.read_bytes()
        result = self.export()
        output = Path(result['output'])
        self.assertTrue((output / 'project.godot').is_file())
        inventory = json.loads((output / 'engine-export.json').read_text())
        self.assertEqual(inventory['engine'], 'godot')
        for item in inventory['files']:
            data = (output / item['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
            self.assertEqual(len(data), item['byteCount'])
        local = graph.query(self.root, subject=result['activity'])[0]
        self.assertEqual(local['used'], [])
        source = graph.query(self.source, kind='RuntimeProduct')[0]
        self.assertEqual(local['snapshot']['workspace_inputs'][0]['@id'], source['@id'])
        merged = workspace_graph.export_workspace(self.manifest)
        work = next(n for n in merged['@graph'] if n['@id'] == result['activity'])
        self.assertEqual(work['used'], [source['@id']])
        generated = [n for n in merged['@graph'] if result['activity'] in n.get('wasGeneratedBy', [])]
        self.assertEqual(len(generated), len([p for p in output.rglob('*') if p.is_file()]))
        self.assertEqual(before, self.manifest.read_bytes())
        with self.assertRaises(ValueError):
            self.export()
        errors = [n for n in graph.query(self.root, kind='ExternalWork') if n['status'] == 'error']
        self.assertEqual(len(errors), 1)
        self.assertEqual(json.loads((output / 'engine-export.json').read_text()), inventory)

    def test_failure_is_durable_private_and_retry_gets_new_activity(self):
        adapter = export_game._adapter('godot')
        def broken(sources, output):
            output.mkdir()
            (output / 'partial').write_text('incomplete')
            raise RuntimeError('sensitive credential SHOULD_NOT_APPEAR')
        with patch.object(export_game, '_adapter', return_value=adapter), patch.object(adapter, 'export', broken):
            with self.assertRaises(RuntimeError):
                self.export()
        self.assertFalse((self.root / 'exports/godot').exists())
        document = graph.export_graph(self.root)
        self.assertNotIn('SHOULD_NOT_APPEAR', json.dumps(document))
        errors = [n for n in document['@graph'] if 'ExternalWork' in n['@type'] and n['status'] == 'error']
        self.assertEqual(len(errors), 1)
        result = self.export()
        self.assertNotEqual(errors[0]['@id'], result['activity'])

    def test_conflicting_exports_publish_only_one_complete_output(self):
        def attempt(_):
            try:
                return self.export()
            except (ValueError, OSError):
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        output = self.root / 'exports/godot'
        self.assertTrue((output / 'engine-export.json').is_file())
        self.assertTrue((output / 'project.godot').is_file())
        works = graph.query(self.root, kind='ExternalWork')
        self.assertEqual(sum(w['status'] == 'error' for w in works), 1)

    def test_drift_unregistered_source_and_option_mismatch_rejected(self):
        (self.source / 'runtime.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.root / 'exports/godot').exists())
        (self.root / 'unknown').mkdir()
        with self.assertRaises(ValueError):
            export_game.export_game('godot', '.', self.manifest, [('unknown', 'runtime.json')], 'out')
        with self.assertRaises(ValueError):
            self.export(three_package=self.root)

    def test_receipts_use_shared_artifact_ids_without_byte_equality_inference(self):
        (self.source / 'shared.bin').write_bytes(b'shared')
        (self.source / 'unused.bin').write_bytes(b'shared')
        digest = hashlib.sha256(b'shared').hexdigest()
        graph.record_work(self.source, {'id': 'assets', 'agent': 'studio', 'status': 'complete',
            'label': 'Assets', 'generated': [{'path': name, 'sha256': digest}
                                           for name in ('shared.bin', 'unused.bin')]})
        artifacts = {n['path']: n for n in graph.query(self.source, kind='Artifact')}
        runtime = graph.query(self.source, kind='RuntimeProduct')[0]
        class Adapter:
            def export(adapter, sources, output):
                output.mkdir()
                (output / 'shared.bin').write_bytes(b'shared')
                (output / 'products.json').write_text(json.dumps([{'runtime_pin': runtime}]))
                (output / 'provenance.json').write_text(json.dumps({'shared.bin': {
                    'source': 'shared.bin', 'artifact': artifacts['shared.bin']['@id'], 'sha256': digest}}))
        with patch.object(export_game, '_adapter', return_value=Adapter()):
            result = self.export()
        merged = workspace_graph.export_workspace(self.manifest)
        used = next(n['used'] for n in merged['@graph'] if n['@id'] == result['activity'])
        self.assertEqual(set(used), {runtime['@id'], artifacts['shared.bin']['@id']})
        self.assertNotIn(artifacts['unused.bin']['@id'], used)
        second = self.export(out='exports/second')
        merged = workspace_graph.export_workspace(self.manifest)
        first = next(n for n in merged['@graph'] if n['@id'] == result['activity'])
        self.assertIn(artifacts['shared.bin']['@id'], first['used'])
        self.assertNotEqual(result['activity'], second['activity'])

    def test_workspace_snapshot_pins_reject_tampering_and_preserve_old_context(self):
        result = self.export()
        shard = self.source / '.game-studio/runs/ready.jsonld'
        document = json.loads(shard.read_text())
        document['@context'] = copy.deepcopy(graph.LEGACY_CONTEXT)
        shard.write_text(json.dumps(document))
        self.assertTrue(workspace_graph.export_workspace(self.manifest))
        source = graph.query(self.source, kind='RuntimeProduct')[0]
        for node in document['@graph']:
            if node['@id'] == source['@id']:
                node['sha256'] = '0' * 64
        shard.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'pin mismatch'):
            workspace_graph.export_workspace(self.manifest)
        self.assertTrue(graph.query(self.root, subject=result['activity']))


if __name__ == '__main__':
    unittest.main()
