import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('phaser_export', Path(__file__).with_name('export.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
ROOT = Path(__file__).resolve().parents[4]
PHASER_PACKAGE = Path(os.environ.get('STUDIO_ROOT', ROOT / 'studio')) / 'engines/web/phaser/node_modules/phaser'
PROJECT = ROOT / 'examples/scout-actions'
RUNTIME = 'builds/attack-contact/scene.runtime.json'


class PhaserExportTests(unittest.TestCase):
    def test_bundle_uses_real_pinned_library_and_graph_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game'
            adapter.export(PROJECT, RUNTIME, out, PHASER_PACKAGE)
            game = json.loads((out / 'game.json').read_text())
            self.assertEqual(game['metadata']['events'][0]['start_ms'], 320)
            for name, pin in json.loads((out / 'provenance.json').read_text()).items():
                if name.startswith('products/'):
                    self.assertEqual(adapter.hashlib.sha256((out / name).read_bytes()).hexdigest(), pin['sha256'])
                    self.assertIn('artifact', pin)
            self.assertEqual(adapter.hashlib.sha256((out / 'vendor/phaser.min.js').read_bytes()).hexdigest(), json.loads((adapter.HERE / 'runtime-lock.json').read_text())['files']['dist/phaser.min.js'])
            self.assertTrue((out / 'vendor/PHASER-LICENSE.txt').exists())
            self.assertTrue(any(out.rglob('*NOTICE')))
            with self.assertRaises(ValueError):
                adapter.export(PROJECT, RUNTIME, out, PHASER_PACKAGE)

    def test_drift_and_missing_dependency_do_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game'
            with self.assertRaisesRegex(ValueError, 'explicitly'):
                adapter.export(PROJECT, RUNTIME, out, Path(tmp) / 'missing')
            self.assertFalse(out.exists())
            project = Path(tmp) / 'source'
            adapter.shutil.copytree(PROJECT, project)
            atlas = project / 'builds/attack-contact/assets/scout/atlas.png'
            atlas.write_bytes(atlas.read_bytes() + b'drift')
            with self.assertRaisesRegex(ValueError, 'drift'):
                adapter.export(project, RUNTIME, out, PHASER_PACKAGE)
            self.assertFalse(out.exists())

    def test_bundled_notices_preserve_attribution_and_full_licenses(self):
        lock = json.loads((adapter.HERE / 'runtime-lock.json').read_text())
        package = PHASER_PACKAGE
        library = {name: (package / name).read_bytes() for name in lock['files']}
        notices = adapter.bundled_notices(library)
        text = notices.decode('utf-8')
        for owner in ('Mapbox', 'Vladimir Agafonkin', 'CodeAndWeb GmbH', 'RoboWhale', 'Minko Gechev', 'Gavin Kistner', 'Paul Bourke', 'Liam Brummitt'):
            self.assertIn(owner, text)
        for block in adapter.re.findall(r'/\*[\s\S]*?\*/', library['dist/phaser.js'].decode('utf-8')):
            if 'ISC License' in block or 'Redistribution and use in source and binary forms' in block or 'CodeAndWeb GmbH' in block:
                self.assertIn(block, text)
        self.assertIn(library['src/physics/matter-js/lib/license.js'].decode('utf-8'), text)
        self.assertIn('THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS', text)
        self.assertLess(len(notices), 12000)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'game'
            adapter.export(PROJECT, RUNTIME, out, PHASER_PACKAGE)
            self.assertEqual((out / 'vendor/PHASER-BUNDLED-NOTICES.txt').read_bytes(), notices)
            provenance = json.loads((out / 'provenance.json').read_text())['vendor/PHASER-BUNDLED-NOTICES.txt']
            self.assertEqual(provenance['sha256'], adapter.hashlib.sha256(notices).hexdigest())
            self.assertEqual(provenance['source_files']['dist/phaser.js'], lock['files']['dist/phaser.js'])
            self.assertFalse((out / 'vendor/phaser.js').exists())

    def test_modified_notice_sources_rejected(self):
        lock = json.loads((adapter.HERE / 'runtime-lock.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / 'node_modules/phaser'
            package.mkdir(parents=True)
            (package / 'package.json').write_text('{"version":"3.90.0"}')
            for name in lock['files']:
                dest = package / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((PHASER_PACKAGE / name).read_bytes())
            for name in ('dist/phaser.js', 'src/physics/matter-js/lib/license.js'):
                original = (package / name).read_bytes()
                (package / name).write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                    adapter.export(PROJECT, RUNTIME, Path(tmp) / 'output', package)
                self.assertFalse((Path(tmp) / 'output').exists())
                (package / name).write_bytes(original)

    def test_invalid_atlas_rect_rejected(self):
        metadata = json.loads((PROJECT / 'builds/attack-contact/assets/scout/action-set.json').read_text())
        runtime = json.loads((PROJECT / RUNTIME).read_text())
        metadata['actions']['attack']['frames'][0]['rect']['x'] = 999999
        with self.assertRaisesRegex(ValueError, 'rectangle'):
            adapter.validate(metadata, runtime['assets'][0]['files'], PROJECT)


if __name__ == '__main__':
    unittest.main()
