import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('web_export', Path(__file__).with_name('export.py'))
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
LOCAL_THREE = Path(os.environ.get('MODEL_ASSETS_ROOT', web.ROOT / 'assets/plugins/model-assets')) / 'three/node_modules/three'
SOURCES = [(web.ROOT / 'examples/forest-camp', 'builds/lantern-embers-final/scene.runtime.json')]


class ExportTests(unittest.TestCase):
    def test_real_export_is_portable_and_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'web'
            products = web.export(SOURCES, output, LOCAL_THREE)
            self.assertEqual(len(products), 1)
            self.assertTrue((output / 'vendor/three/LICENSE').is_file())
            self.assertTrue((output / 'vendor/three/examples/jsm/libs/meshopt_decoder.module.js').is_file())
            self.assertIn('Arseny Kapoulkine', (output / 'MESHOPT-LICENSE.txt').read_text())
            self.assertTrue((output / 'vendor/three/examples/jsm/utils/SkeletonUtils.js').is_file())
            self.assertFalse(list(output.rglob('*.blend')))
            self.assertFalse(list(output.rglob('*.bytes')))
            self.assertFalse(list(output.rglob('model.glb')))
            for path, digest in json.loads((output / 'manifest.json').read_text()).items():
                self.assertEqual(hashlib.sha256((output / path).read_bytes()).hexdigest(), digest)
            for path, pin in json.loads((output / 'provenance.json').read_text()).items():
                self.assertEqual(hashlib.sha256((output / path).read_bytes()).hexdigest(), pin['sha256'])
                self.assertNotIn('_source', pin)
            with self.assertRaisesRegex(ValueError, 'Output must not exist'):
                web.export(SOURCES, output, LOCAL_THREE)

    def test_effect_only_scene_before_forest_is_not_published(self):
        products, hashes = web.admit(SOURCES)
        effect_only = copy.deepcopy(products[0])
        effect_only['assets'] = {'embers': effect_only['assets']['embers']}
        effect_only['scene']['nodes'] = [dict(n, parent=None) for n in effect_only['scene']['nodes'] if n['asset'] == 'embers']
        # An unused admitted artifact must not be copied or claimed as provenance.
        effect_only['assets']['embers']['model'] = 'unused/model.glb'
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'admit', return_value=([effect_only, products[0]], hashes)):
            out = Path(tmp) / 'web'
            selected = web.export(SOURCES, out, LOCAL_THREE)
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]['scene']['nodes'][0]['asset'], 'lantern')
            self.assertNotIn('unused/model.glb', (out / 'provenance.json').read_text())
            self.assertFalse((out / 'unused').exists())

    def test_ambiguous_or_unplaced_goal_leaves_no_output(self):
        products, hashes = web.admit(SOURCES)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'web'
            with patch.object(web, 'admit', return_value=(products + products, hashes)):
                with self.assertRaisesRegex(ValueError, 'exactly one qualifying'):
                    web.export(SOURCES, out, LOCAL_THREE)
            self.assertFalse(out.exists())
            products[0]['scene']['nodes'][0]['position'][1] = 2
            with patch.object(web, 'admit', return_value=(products, hashes)):
                with self.assertRaisesRegex(ValueError, 'ground-level root'):
                    web.export(SOURCES, out, LOCAL_THREE)
            self.assertFalse(out.exists())

    def test_vendor_drift_and_missing_dependency_leave_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            vendor = Path(tmp) / 'three'
            for relative in json.loads((web.HERE / 'three-lock.json').read_text())['files']:
                path = vendor / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(LOCAL_THREE / relative, path)
            (vendor / 'LICENSE').write_text('changed')
            out = Path(tmp) / 'web'
            with self.assertRaisesRegex(ValueError, 'dependency drift'):
                web.export(SOURCES, out, vendor)
            self.assertFalse(out.exists())
            (vendor / 'LICENSE').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing or escaping'):
                web.export(SOURCES, out, vendor)
            self.assertFalse(out.exists())

    def test_particle_descriptor_rejects_invalid_values(self):
        data = json.loads((SOURCES[0][0] / 'builds/lantern-embers-final/assets/embers/effect.json').read_text())
        web.validate_effect(data)
        for bad in (float('nan'), -1, True):
            data['particles'][0]['life_s'] = bad
            with self.assertRaises(ValueError):
                web.validate_effect(data)

    def test_mutated_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            shutil.copytree(SOURCES[0][0], source)
            runtime = source / SOURCES[0][1]
            runtime.write_text(runtime.read_text() + ' ')
            out = Path(tmp) / 'web'
            with self.assertRaisesRegex(ValueError, 'SSOT graph pin'):
                web.export([(source, SOURCES[0][1])], out, LOCAL_THREE)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
