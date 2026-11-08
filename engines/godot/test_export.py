import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('adapter', Path(__file__).with_name('export.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class ExportTests(unittest.TestCase):
    def test_real_products_copy_and_pin(self):
        root = Path(__file__).resolve().parents[3]
        sources = [(root / 'examples/forest-camp', 'builds/lantern-embers-final/scene.runtime.json'),
                   (root / 'examples/scout-actions', 'builds/attack-contact/scene.runtime.json')]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game'
            products = adapter.export(sources, out)
            self.assertEqual(products[0]['scene']['nodes'][1]['parent'], 'camp-lantern')
            pins = json.loads((out / 'provenance.json').read_text())
            self.assertTrue(any('LICENSE' in p for p in pins))
            self.assertTrue(any(p.endswith('model.glb.bytes') for p in pins))
            self.assertTrue(any(p.endswith('model.web.glb.bytes') for p in pins))
            for path, pin in pins.items():
                self.assertEqual(hashlib.sha256((out / path).read_bytes()).hexdigest(), pin['sha256'])
            with self.assertRaises(ValueError):
                adapter.export(sources, out)

    def test_ssot_drift_rejected_without_output(self):
        root = Path(__file__).resolve().parents[3] / 'examples/forest-camp'
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'source'
            adapter.shutil.copytree(root / '.game-studio', project / '.game-studio')
            runtime = 'builds/lantern-embers-final/scene.runtime.json'
            dest = project / runtime
            dest.parent.mkdir(parents=True)
            dest.write_text((root / runtime).read_text() + ' ')
            out = Path(tmp) / 'game'
            with self.assertRaisesRegex(ValueError, 'SSOT graph pin'):
                adapter.export([(project, runtime)], out)
            self.assertFalse(out.exists())

    def test_artifact_drift_rejected_without_output(self):
        root = Path(__file__).resolve().parents[3] / 'examples/forest-camp'
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'source'
            adapter.shutil.copytree(root, project)
            model = project / 'builds/lantern-embers-final/assets/lantern/model.web.glb'
            model.write_bytes(model.read_bytes() + b'x')
            out = Path(tmp) / 'game'
            with self.assertRaisesRegex(ValueError, 'Artifact drift'):
                adapter.export([(project, 'builds/lantern-embers-final/scene.runtime.json')], out)
            self.assertFalse(out.exists())

    def test_runtime_reuses_linked_original_artifacts(self):
        root = Path(__file__).resolve().parents[3] / 'examples/forest-camp'
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'source'
            adapter.shutil.copytree(root, project)
            shard = next(p for p in (project / '.game-studio/runs').glob('*.jsonld') if 'lantern-embers-final/scene.runtime.json' in p.read_text())
            document = json.loads(shard.read_text())
            original = next(n for n in document['@graph'] if 'RuntimeProduct' in n.get('@type', []))
            scope = original['@id'].split(':run:')[0]
            run_id = scope + ':run:engine-reuse-test'
            relative = 'builds/engine-reuse-test/scene.runtime.json'
            path = project / relative
            path.parent.mkdir(parents=True)
            adapter.shutil.copyfile(project / original['path'], path)
            runtime = {**original, '@id': run_id + ':runtime', 'path': relative, 'wasGeneratedBy': [run_id], 'wasDerivedFrom': [original['@id']]}
            document['@graph'] = [{'@id': run_id, '@type': ['Activity', 'Run'], 'record': {'status': 'ready'}, 'partOf': [scope]}, runtime]
            (project / '.game-studio/runs/engine-reuse-test.jsonld').write_text(json.dumps(document))
            products = adapter.export([(project, relative)], Path(tmp) / 'game')
            self.assertEqual(products[0]['runtime_pin']['@id'], run_id + ':runtime')
            self.assertTrue(products[0]['assets']['lantern']['raw'].endswith('model.glb.bytes'))

    def test_reject_escape_and_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with self.assertRaises(ValueError):
                adapter.export([(p, '../outside.json')], p / 'out')
            scene = {'schema_version': 1, 'status': 'ready', 'coordinates': {'units': 'meters', 'up': '+Y', 'handedness': 'right'}, 'assets': [{'id': 'test', 'files': {}}], 'nodes': [{'id': 'n', 'asset': 'test', 'parent': 'n', 'position': [0, 0, 0], 'rotation_degrees': [0, 0, 0], 'scale': [1, 1, 1]}]}
            (p / 'runtime.json').write_text(json.dumps(scene))
            pin = {'runtime.json': {'sha256': hashlib.sha256((p / 'runtime.json').read_bytes()).hexdigest(), 'byteCount': (p / 'runtime.json').stat().st_size}}
            with patch('runtime_inputs.graph_pins', return_value=pin):
                with self.assertRaisesRegex(ValueError, 'Cyclic'):
                    adapter.export([(p, 'runtime.json')], p / 'out')
            self.assertFalse((p / 'out').exists())


if __name__ == '__main__':
    unittest.main()
