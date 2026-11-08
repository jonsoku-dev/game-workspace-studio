import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('playcheck', Path(__file__).parents[1] / 'tools/playcheck.py')
playcheck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(playcheck)


class PlaycheckTests(unittest.TestCase):
    def test_reassesses_behavior_and_rejects_export_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'game.json').write_text(json.dumps({'runtime_pin': {'sha256': 'abc'}, 'metadata': {'actions': {'attack': {}}, 'events': [{'action': 'attack', 'start_ms': 320}]}, 'playtest': {'hits_to_win': 1}}))
            observations = {'miss': {'hits': 0, 'contactEvents': [{'contact': False}]},
                            'win': {'hits': 1, 'finished': True, 'contactEvents': [{'contact': True, 'start_ms': 320, 'observed_ms': 335}]},
                            'reset': {'hits': 0, 'finished': False, 'contactEvents': [], 'x': 210}}
            report = playcheck.assess(root, 'run', observations)
            self.assertTrue(playcheck.verify(report, root)['passed'])
            report['criteria']['win']['pass'] = False
            with self.assertRaises(ValueError):
                playcheck.verify(report, root)
            report = playcheck.assess(root, 'run', observations)
            (root / 'new.txt').write_text('drift')
            with self.assertRaises(ValueError):
                playcheck.verify(report, root)
            observations['win']['contactEvents'][0]['observed_ms'] = 200
            self.assertFalse(playcheck.assess(root, 'run', observations)['passed'])

    def test_import_is_not_browser_proof_and_report_is_portable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'game.json').write_text(json.dumps({'runtime_pin': {'sha256': 'abc'}, 'metadata': {'actions': {'attack': {}}, 'events': [{'action': 'attack', 'start_ms': 320}]}, 'playtest': {'hits_to_win': 1}}))
            observations = {'miss': {'hits': 0, 'contactEvents': [{'contact': False}]},
                            'win': {'hits': 1, 'finished': True, 'contactEvents': [{'contact': True, 'start_ms': 320, 'observed_ms': 335}]},
                            'reset': {'hits': 0, 'finished': False, 'contactEvents': [], 'x': 210}}
            report = playcheck.assess(root, 'run', observations)
            self.assertEqual(report['driver'], 'observation-import')
            report.update(export_dir='play/export', export_activity='export', browser_activity='browser', driver='stagehand-mcp')
            with self.assertRaises(ValueError):
                playcheck.verify(report, root)
            report['browser_observed_hashes'] = report['export_hashes']
            self.assertTrue(playcheck.verify(report, root)['passed'])
            report['browser_observed_hashes'] = {}
            with self.assertRaises(ValueError):
                playcheck.verify(report, root)

    def test_browser_config_disabled_and_python310_fail_before_spawn(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
        import playcheck_browser
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'config.toml').write_text('[mcp_servers.stagehand]\nenabled=false\n')
            with patch.dict(playcheck_browser.os.environ, {'CODEX_HOME': temp}), patch.object(playcheck_browser.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ValueError, 'Enabled local'):
                    playcheck_browser.MCP()
                spawn.assert_not_called()
            with patch.object(playcheck_browser, 'tomllib', None), patch.object(playcheck_browser.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ValueError, 'Python 3.11'):
                    playcheck_browser.MCP()
                spawn.assert_not_called()

    def test_explicit_marker_scores_after_early_fx_and_checks_visible_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            effect={'action':'attack','start_ms':0,'frames':[{'duration_ms':100}]*4}
            (root/'game.json').write_text(json.dumps({'runtime_pin':{'sha256':'abc'},'metadata':{'events':[effect],'actions':{'attack':{'frames':[{'duration_ms':100}]*4}}},'playtest':{'hits_to_win':1,'contact_frame':2}}))
            impact={'hits':1,'finished':True,'actor_elapsed_ms':210,'effects':[{'start_ms':0,'elapsed_ms':210,'frame':'2'}],'contactEvents':[{'contact':True,'start_ms':200,'observed_ms':210}]}
            observations={'miss':{'hits':0,'contactEvents':[{'contact':False}]},'win':impact,'impact':impact,'reset':{'hits':0,'finished':False,'x':210,'contactEvents':[]},'fx_onset':{'hits':0,'contactEvents':[],'effects':[{}],'actor_elapsed_ms':20}}
            self.assertTrue(playcheck.assess(root,'run',observations)['passed'])
            impact['effects'][0]['frame']='1'
            self.assertFalse(playcheck.assess(root,'run',observations)['passed'])
            impact['effects'][0]['frame']='2'
            impact['contactEvents'][0]['start_ms']=0
            self.assertFalse(playcheck.assess(root,'run',observations)['passed'])

    def test_http_serves_only_pinned_snapshot_and_rejects_forged_host(self):
        import sys
        import http.client
        import threading
        sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
        import playcheck_browser
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'index.html').write_bytes(b'<p>pinned</p>')
            (root/'game.mjs').write_bytes(b'export const pinned = true;')
            pins = playcheck.hashes(root)
            server = playcheck_browser.inventory_server(root, pins)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                (root/'index.html').write_bytes(b'unpinned replacement')
                (root/'new.txt').write_bytes(b'unpinned inserted file')
                (root/'game.mjs').unlink()
                (root/'game.mjs').symlink_to(root/'new.txt')
                def get(path, host=None, method='GET'):
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    conn.request(method, path, headers={'Host': host} if host else {})
                    response = conn.getresponse()
                    result = response.status, response.read(), dict(response.getheaders())
                    conn.close()
                    return result
                status, data, headers = get('/')
                self.assertEqual((status,data),(200,b'<p>pinned</p>'))
                self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
                self.assertEqual(get('/game.mjs')[:2],(200,b'export const pinned = true;'))
                self.assertIn('javascript',get('/game.mjs')[2]['Content-Type'])
                self.assertEqual(get('/new.txt')[0],404)
                self.assertEqual(get('/products/')[0],404)
                self.assertEqual(get('/../new.txt')[0],404)
                self.assertEqual(get('/',host='attacker.example')[0],400)
                self.assertEqual(get('http://attacker.example/index.html')[0],400)
                self.assertEqual(get('/',method='HEAD')[:2],(200,b''))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            with self.assertRaises(ValueError):
                playcheck_browser.inventory_server(root, pins)
