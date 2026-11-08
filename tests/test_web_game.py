from concurrent.futures import ThreadPoolExecutor
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import graph
import web_game


class WebGameTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.spec = {'schema_version': 1, 'title': 'Independent game', 'genre': 'puzzle',
                     'goal': 'Click the target', 'controls': 'Click / touch'}
        (self.project / 'genre.json').write_text(json.dumps(self.spec))
        (self.project / 'game/scripts').mkdir(parents=True)
        (self.project / 'game/index.html').write_bytes(b'<button>Play</button><script type="module" src="scripts/main.mjs"></script>')
        (self.project / 'game/scripts/main.mjs').write_bytes(
            b'import {createFeedback} from "../feedback.mjs";\n'
            b'const feedback = createFeedback();\n'
            b'document.querySelector("button").onclick = event => { event.target.textContent = "Win"; };\n')

    def export(self, out='build/play'):
        return web_game.export(self.project, out)

    def errors(self):
        return [n for n in graph.query(self.project, kind='ExternalWork') if n['status'] == 'error']

    def test_minimum_real_cli_preserves_bytes_paths_hashes_and_precise_derivation(self):
        before = {p.relative_to(self.project).as_posix(): p.read_bytes()
                  for p in self.project.rglob('*') if p.is_file()}
        command = [sys.executable, str(web_game.ROOT / 'tools/web_game.py'), '--project', str(self.project), '--out', 'build/play']
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        output = Path(result['output'])
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertEqual(receipt['index'], 'build/play/index.html')
        self.assertEqual(receipt['title'], self.spec['title'])
        self.assertEqual(receipt['controls'], self.spec['controls'])
        for source, data in before.items():
            self.assertEqual((self.project / source).read_bytes(), data)
            destination = source.removeprefix('game/')
            self.assertEqual((output / destination).read_bytes(), data)
        for item in receipt['files']:
            data = (output / item['path']).read_bytes()
            self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(item['byteCount'], len(data))
        self.assertEqual((output / 'feedback.mjs').read_bytes(), (web_game.ROOT / 'engines/web/feedback.mjs').read_bytes())
        self.assertEqual(receipt['provenance']['feedback.mjs']['origin'], 'installed-runtime')
        nodes = graph.export_graph(self.project)['@graph']
        by_id = {n['@id']: n for n in nodes}
        work = by_id[result['activity']]
        self.assertEqual(len(work['used']), len(before))
        generated = [n for n in nodes if result['activity'] in n.get('wasGeneratedBy', [])]
        self.assertEqual(len(generated), len(receipt['files']) + 1)
        for node in generated:
            destination = Path(node['path']).relative_to('build/play').as_posix()
            pin = receipt['provenance'].get(destination, {})
            self.assertEqual(node['wasDerivedFrom'], [pin['artifact']] if 'artifact' in pin else [])
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(len(self.errors()), 1)

    def test_malformed_manifest_missing_index_and_invalid_paths_record_failures(self):
        for spec in ({}, {**self.spec, 'schema_version': True}, {**self.spec, 'controls': []}, []):
            with self.subTest(spec=spec):
                (self.project / 'genre.json').write_text(json.dumps(spec))
                with self.assertRaises(ValueError):
                    self.export()
        (self.project / 'genre.json').write_text(json.dumps(self.spec))
        (self.project / 'game/index.html').unlink()
        with self.assertRaises(ValueError):
            self.export()
        for out in ('../escape', '/tmp/escape', 'game/out', '.game-studio/out', 'build/../escape', 'build\\escape'):
            with self.subTest(out=out), self.assertRaises(ValueError):
                self.export(out)
        self.assertFalse((self.project / 'build/play').exists())
        self.assertEqual(len(self.errors()), 11)

    def test_output_serves_unchanged_sources_and_host_module_over_loopback(self):
        result = self.export()
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=result['output']))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for relative in ('index.html', 'scripts/main.mjs', 'feedback.mjs'):
                with urlopen(f'http://127.0.0.1:{server.server_port}/{relative}', timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), (Path(result['output']) / relative).read_bytes())
                    if relative.endswith('.mjs'):
                        self.assertIn('javascript', response.headers['Content-Type'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_graph_failure_after_publication_preserves_output_and_records_retry_warning(self):
        original = graph.record_work
        def fail_publish_record(project, record):
            if record['status'] == 'complete' and record.get('generated'):
                raise RuntimeError('private graph failure')
            return original(project, record)
        with patch.object(graph, 'record_work', side_effect=fail_publish_record), self.assertRaises(RuntimeError):
            self.export()
        self.assertTrue((self.project / 'build/play/web-game.json').is_file())
        checks = graph.query(self.project, subject=self.errors()[0]['@id'] + ':validation')[0]['checks']
        self.assertEqual(checks[0], 'graph-recording')
        self.assertIn('Output path exists', checks[-1])

    def test_reserved_conflicting_and_unsupported_source_paths_rejected(self):
        for name in ('feedback.mjs', 'FEEDBACK.MJS', 'genre.json', 'web-game.json', 'secret.py',
                     '.hidden.js', 'trailing..', 'nul.js', 'bad#fragment.js'):
            path = self.project / 'game' / name
            path.write_text('rejected')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.export()
            path.unlink()
        with patch.object(web_game.os, 'walk', return_value=[(str(self.project / 'game'), [], ['index.html', 'INDEX.html'])]):
            with self.assertRaises(ValueError):
                self.export()

    def test_localized_asset_names_keep_their_bytes(self):
        path = self.project / 'game/달 그림.png'
        path.write_bytes(b'original bytes')
        result = self.export()
        self.assertEqual((Path(result['output']) / path.name).read_bytes(), path.read_bytes())

    def test_symlink_hardlink_special_file_and_output_links_rejected(self):
        source = self.project / 'game/linked.js'
        source.symlink_to(self.project / 'game/index.html')
        with self.assertRaises(ValueError):
            self.export()
        source.unlink()
        os.link(self.project / 'game/index.html', source)
        with self.assertRaises(ValueError):
            self.export()
        source.unlink()
        os.mkfifo(source)
        with self.assertRaises(ValueError):
            self.export()
        source.unlink()
        source.symlink_to(self.project / 'game', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export()
        source.unlink()
        (self.project / 'linked').symlink_to(self.project / 'game', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export('linked/play')
        self.assertFalse((self.project / 'game/play').exists())

    def test_limits_and_changed_inputs_leave_failure_evidence_without_partial_output(self):
        with patch.object(web_game, 'MAX_FILES', 1), self.assertRaises(ValueError):
            self.export()
        with patch.object(web_game, 'MAX_BYTES', 8), self.assertRaises(ValueError):
            self.export()
        original = web_game._read
        def changed(root, relative):
            data = original(root, relative)
            if relative == 'game/index.html' and graph.query(self.project, kind='Artifact'):
                return data + b'changed'
            return data
        with patch.object(web_game, '_read', side_effect=changed), self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.project / 'build/play').exists())
        self.assertEqual(len(self.errors()), 3)
        self.assertFalse(list(self.project.glob('build/.engine-export-*')))
        self.export()

    def test_copy_failure_is_private_and_concurrent_publication_has_one_winner(self):
        original = Path.write_bytes
        def broken(path, data):
            if '.engine-export-' in str(path):
                raise RuntimeError('sensitive SHOULD_NOT_APPEAR')
            return original(path, data)
        with patch.object(Path, 'write_bytes', broken), self.assertRaises(RuntimeError):
            self.export()
        self.assertFalse((self.project / 'build/play').exists())
        self.assertNotIn('SHOULD_NOT_APPEAR', json.dumps(graph.export_graph(self.project)))
        def attempt(_):
            try:
                return self.export()
            except (OSError, ValueError):
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertTrue((self.project / 'build/play/web-game.json').is_file())
        self.assertEqual(len(self.errors()), 2)


if __name__ == '__main__':
    unittest.main()
