import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import character
import graph


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        (self.project / 'art').mkdir()
        (self.project / 'art/source.png').write_bytes(b'png source fixture')
        (self.project / 'art/request.json').write_text(json.dumps({
            'schema_version': 1, 'source': 'source.png', 'actions': ['idle', 'attack']}))

    def producer(self, command, **kwargs):
        request = Path(command[command.index('--request') + 1])
        if 'source' in json.loads(request.read_text()):
            self.assertEqual((request.parent / 'source.png').read_bytes(), b'png source fixture')
        output = Path(command[-1])
        output.mkdir()
        (output / 'character.riv').write_bytes(b'RIVE fixture')
        (output / 'player.html').write_text('<html>self contained fixture</html>')
        return subprocess.CompletedProcess(command, 0, json.dumps({'status': 'ready', 'files': {
            'character': 'character.riv', 'player': 'player.html'}}), '')

    def run_build(self, producer=None, out='build/one'):
        with patch('character.shutil.which', return_value='/fixture/pixel-asset'), patch(
                'character.subprocess.run', side_effect=producer or self.producer):
            return character.build(self.project, 'art/request.json', out)

    def test_ready_pins_sources_and_generated_outputs(self):
        result = self.run_build()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['artistic_acceptance'], 'pending')
        nodes = {n['@id']: n for n in graph.export_graph(self.project)['@graph']}
        activity = nodes[result['activity']]
        self.assertEqual(len(activity['used']), 2)
        for pin in activity['used']:
            self.assertNotIn('wasGeneratedBy', nodes[pin])
        generated = [n for n in nodes.values() if result['activity'] in n.get('wasGeneratedBy', [])]
        self.assertTrue(any(n.get('path') == result['files']['character'] for n in generated))
        self.assertTrue(all(len(n.get('wasDerivedFrom', [])) == 1 for n in generated if '/inputs/' in n['path']))
        self.assertTrue(all(not n.get('wasDerivedFrom') for n in generated if '/bundle/' in n['path']))
        self.assertEqual(self.run_build()['status'], 'error')
        self.assertEqual((self.project / result['files']['character']).read_bytes(), b'RIVE fixture')

    def test_needs_review_preserves_diagnostics(self):
        def review(command, **kwargs):
            output = Path(command[-1]); output.mkdir()
            (output / 'diagnostic.json').write_text('{}')
            return subprocess.CompletedProcess(command, 1, json.dumps({
                'status': 'needs_review', 'files': {'report': 'diagnostic.json'}}), '')
        result = self.run_build(review)
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue((self.project / result['files']['report']).is_file())

    def test_partial_failure_is_recorded(self):
        def fail(command, **kwargs):
            output = Path(command[-1]); output.mkdir()
            (output / 'partial.png').write_bytes(b'partial')
            raise subprocess.TimeoutExpired(command, 300)
        result = self.run_build(fail)
        self.assertEqual(result['status'], 'error')
        self.assertTrue(any(n.get('path', '').endswith('partial.png') for n in graph.export_graph(self.project)['@graph']))

    def test_escaping_and_symlink_inputs_record_failure(self):
        for source in ('../../outside.png', 'link.png'):
            if source == 'link.png':
                (self.project / 'art/link.png').symlink_to(self.project / 'art/source.png')
            (self.project / 'art/request.json').write_text(json.dumps({
                'schema_version': 1, 'source': source, 'actions': ['idle']}))
            self.assertEqual(self.run_build()['status'], 'error')
        self.assertFalse((self.project / 'build/one').exists())
        self.assertEqual(len(graph.query(self.project, kind='ExternalWork')), 2)

    def test_malformed_or_escaping_producer_result(self):
        def tamper(command, **kwargs):
            result = self.producer(command, **kwargs)
            payload = json.loads(result.stdout)
            payload['files']['player'] = '../../art/source.png'
            result.stdout = json.dumps(payload)
            return result
        self.assertEqual(self.run_build(tamper)['status'], 'error')

    def test_input_tampering_during_execution_is_rejected(self):
        def tamper(command, **kwargs):
            result = self.producer(command, **kwargs)
            request = Path(command[command.index('--request') + 1])
            (request.parent / 'source.png').write_bytes(b'changed')
            return result
        self.assertEqual(self.run_build(tamper)['status'], 'error')

    def test_concurrent_output_creation_never_overwrites(self):
        original_mkdir = Path.mkdir
        output = self.project / 'build/one'
        def race(path, *args, **kwargs):
            if path == output:
                original_mkdir(path, *args, **kwargs)
                (path / 'foreign.txt').write_text('keep')
            return original_mkdir(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', race):
            self.assertEqual(self.run_build()['status'], 'error')
        self.assertEqual((output / 'foreign.txt').read_text(), 'keep')
        self.assertEqual(list(output.iterdir()), [output / 'foreign.txt'])

    def frame_request(self, actions=('attack', 'idle'), reference=True):
        poses = self.project / 'art/poses'
        poses.mkdir()
        (poses / 'idle.png').write_bytes(b'idle authored image')
        (poses / 'attack.png').write_bytes(b'attack authored image')
        manifest = {'schema_version': 1, 'size': [16, 16], 'actions': {
            'idle': {'loop': True, 'frames': [{'path': 'idle.png', 'duration_ms': 100}]},
            'attack': {'loop': False, 'frames': [
                {'path': 'attack.png', 'duration_ms': 80}, {'path': 'idle.png', 'duration_ms': 120}]},
            'unused': {'loop': False, 'frames': [{'path': '../../absent.png', 'duration_ms': 100}]}}}
        (poses / 'frames.json').write_text(json.dumps(manifest))
        request = {'schema_version': 1, 'frames': 'poses/frames.json', 'actions': list(actions)}
        if reference:
            request['reference'] = 'source.png'
        (self.project / 'art/request.json').write_text(json.dumps(request))
        return poses

    def test_authored_frames_select_and_reorder_without_unselected_inputs(self):
        self.frame_request()
        def authored(command, **kwargs):
            request_path = Path(command[command.index('--request') + 1])
            request = json.loads(request_path.read_text())
            manifest_path = request_path.parent / request['frames']
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(list(manifest['actions']), ['attack', 'idle'])
            self.assertEqual([f['duration_ms'] for f in manifest['actions']['attack']['frames']], [80, 120])
            self.assertEqual((manifest_path.parent / 'attack.png').read_bytes(), b'attack authored image')
            self.assertFalse((request_path.parent / 'absent.png').exists())
            return self.producer(command, **kwargs)
        result = self.run_build(authored)
        self.assertEqual(result['status'], 'ready')
        nodes = {n['@id']: n for n in graph.export_graph(self.project)['@graph']}
        used = [nodes[ident]['path'] for ident in nodes[result['activity']]['used']]
        self.assertEqual(set(used), {'art/request.json', 'art/poses/frames.json',
                                    'art/poses/attack.png', 'art/poses/idle.png', 'art/source.png'})
        self.assertEqual(json.loads((self.project / 'build/one/inputs/original-frames-manifest.json').read_text())['actions'].keys(),
                         dict.fromkeys(['idle', 'attack', 'unused']).keys())

    def test_authored_subset_does_not_read_unselected_pngs(self):
        poses = self.frame_request(actions=('idle',), reference=False)
        (poses / 'attack.png').unlink()
        def authored(command, **kwargs):
            request_path = Path(command[command.index('--request') + 1])
            self.assertFalse((request_path.parent / 'poses/attack.png').exists())
            return self.producer(command, **kwargs)
        result = self.run_build(authored)
        self.assertEqual(result['status'], 'ready')
        nodes = {n['@id']: n for n in graph.export_graph(self.project)['@graph']}
        self.assertEqual(len(nodes[result['activity']]['used']), 3)

    def test_authored_path_escape_and_frame_tamper_fail(self):
        poses = self.frame_request()
        def tamper(command, **kwargs):
            result = self.producer(command, **kwargs)
            (poses / 'attack.png').write_bytes(b'changed original')
            return result
        self.assertEqual(self.run_build(tamper)['status'], 'error')
        manifest = json.loads((poses / 'frames.json').read_text())
        manifest['actions']['attack']['frames'][0]['path'] = '../source.png'
        (poses / 'frames.json').write_text(json.dumps(manifest))
        self.assertEqual(self.run_build(out='build/two')['status'], 'error')

    def test_graph_output_and_hardlink_sources_are_rejected(self):
        self.assertEqual(self.run_build(out='.game-studio/characters')['status'], 'error')
        self.assertFalse((self.project / '.game-studio/characters').exists())
        os.link(self.project / 'art/source.png', self.project / 'art/alias.png')
        self.assertEqual(self.run_build()['status'], 'error')

    def test_request_and_selected_frame_limits(self):
        request = self.project / 'art/request.json'
        original = request.read_bytes()
        request.write_bytes(b' ' * 1_048_577)
        self.assertEqual(self.run_build()['status'], 'error')
        request.write_bytes(original)
        poses = self.frame_request()
        manifest = json.loads((poses / 'frames.json').read_text())
        manifest['actions']['attack']['frames'] *= 129
        (poses / 'frames.json').write_text(json.dumps(manifest))
        self.assertEqual(self.run_build()['status'], 'error')
        spec = json.loads(request.read_text())
        spec['actions'] = ['action' + str(i) for i in range(33)]
        request.write_text(json.dumps(spec))
        self.assertEqual(self.run_build()['status'], 'error')

    def test_media_and_manifest_budgets(self):
        poses = self.frame_request()
        manifest = poses / 'frames.json'
        original = manifest.read_bytes()
        manifest.write_bytes(b' ' * 1_048_577)
        self.assertEqual(self.run_build()['status'], 'error')
        manifest.write_bytes(original)
        with (poses / 'attack.png').open('wb') as stream:
            stream.truncate(33_554_432)
        self.assertEqual(self.run_build()['status'], 'error')
        self.assertFalse((self.project / 'build/one').exists())

    def test_authored_execution_and_admission_tampering(self):
        poses = self.frame_request()
        def tamper(command, **kwargs):
            result = self.producer(command, **kwargs)
            request = Path(command[command.index('--request') + 1])
            (request.parent / 'poses/idle.png').write_bytes(b'changed executed pose')
            return result
        self.assertEqual(self.run_build(tamper)['status'], 'error')
        def swap_before_invocation(_):
            (poses / 'idle.png').write_bytes(b'changed before invocation')
            return '/fixture/pixel-asset'
        with patch('character.shutil.which', side_effect=swap_before_invocation), patch('character.subprocess.run') as run:
            self.assertEqual(character.build(self.project, 'art/request.json', 'build/two')['status'], 'error')
            run.assert_not_called()

    def test_authored_png_symlink_and_ambiguous_request_rejected(self):
        poses = self.frame_request()
        (poses / 'idle.png').unlink()
        (poses / 'idle.png').symlink_to(poses / 'attack.png')
        self.assertEqual(self.run_build()['status'], 'error')
        path = self.project / 'art/request.json'
        request = json.loads(path.read_text())
        request['source'] = 'source.png'
        path.write_text(json.dumps(request))
        self.assertEqual(self.run_build()['status'], 'error')

    def test_motion_master_and_mask_are_copied_and_used(self):
        (self.project / 'art/mask.png').write_bytes(b'mask')
        (self.project / 'art/motion.json').write_text(json.dumps({'master': 'source.png',
            'rig': {'parts': [{'mask': 'mask.png'}]}}))
        (self.project / 'art/request.json').write_text(json.dumps({'schema_version': 1,
            'motion_request': 'motion.json', 'actions': ['idle']}))
        result = self.run_build()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual((self.project / 'build/one/inputs/files/mask.png').read_bytes(), b'mask')
        activity = graph.query(self.project, subject=result['activity'])[0]
        self.assertEqual(len(activity['used']), 4)


if __name__ == '__main__':
    unittest.main()
