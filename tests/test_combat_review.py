import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import combat_review
import graph


class CombatReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for name in ('motion', 'fx'):
            (self.project / 'game' / name).mkdir(parents=True)
        self.actor = {'image': 'job-0.webp', 'pivot': [8, 15], 'bodyHeight': 12,
                      'frames': [{'id': str(i), 'x': i * 16, 'y': 0, 'w': 16, 'h': 16, 'ms': 100}
                                 for i in range(9)],
                      'actions': {'idle': [0], 'move': [1], 'heavy': [2, 3], 'release': [4],
                                  'follow': [5], 'recover': [6, 0], 'hurt': [7], 'evade': [8]}}
        self.write_actor()
        Image.new('RGBA', (144, 16), '#fe6732').save(self.project / 'game/motion/job-0.webp', lossless=True)
        Image.new('RGBA', (48, 16), '#ffdb23').save(self.project / 'game/fx/job-clip-0.png')
        frame = lambda i, ms: {'x': i * 16, 'y': 0, 'w': 16, 'h': 16, 'ms': ms}
        self.jobs = {'knight': {'actor': 'job-0', 'motif': 'blade', 'clip': {
            'image': './fx/job-clip-0.png', 'pivot': [8, 8],
            'phases': {'charge': [frame(0, 100)], 'travel': [frame(1, 200)], 'impact': [frame(2, 40)]}}}}
        self.write_jobs()
        (self.project / 'game/fx/job-clip-0-credit.json').write_text(json.dumps({
            'license': 'fixture license', 'notice': 'fixture author', 'producer': {'source_sha256': 'fixture'}}))
        (self.project / 'game/timing.mjs').write_text('export const RECOVERY_MS = {"follow":180,"recover":200};')

    def write_actor(self):
        (self.project / 'game/motion/job-0.json').write_text(json.dumps(self.actor))

    def write_jobs(self):
        (self.project / 'game/jobs.mjs').write_text('export const JOBS = ' + json.dumps(self.jobs) + ';')

    def action_set(self, command, **kwargs):
        output = Path(command[-1]); output.mkdir()
        (output / 'action-set.json').write_text(json.dumps({'events': [{'start_ms': 300}]}))
        (output / 'preview.gif').write_bytes(b'fixture preview')
        return subprocess.CompletedProcess(command, 0, '{}', '')

    def run_build(self, out='reviews/knight'):
        with patch('combat_review.character.build', return_value={'status': 'ready'}) as character, patch(
                'combat_review.subprocess.run', side_effect=self.action_set) as action_set:
            result = combat_review.build(self.project, 'job-0', out)
        return result, character, action_set

    def test_real_states_contact_timing_and_project_graph(self):
        result, character, action_set = self.run_build()
        self.assertEqual(result['status'], 'ready')
        action_set.assert_not_called()
        self.assertIn('jump', result['action_set'])
        root = self.project / 'reviews/knight'
        manifest = json.loads((root / 'inputs/poses.json').read_text())
        self.assertNotIn('jump', manifest['actions'])
        self.assertNotIn('walk', manifest['actions'])
        timing = json.loads((root / 'timing.json').read_text())
        self.assertEqual(timing['contact_ms'], 300)
        durations = [f['duration_ms'] for f in manifest['actions']['attack']['frames']]
        self.assertEqual(durations, [50, 50, 200, 180, 100, 100])
        self.assertEqual(sum(durations[:3]), 300)
        self.assertEqual(manifest['pivot_px_from_top_left'], self.actor['pivot'])
        with Image.open(root / 'inputs/pose-4.png') as cropped, Image.open(self.project / 'game/motion/job-0.webp') as atlas:
            self.assertEqual(cropped.tobytes(), atlas.crop((64, 0, 80, 16)).convert('RGBA').tobytes())
        character.assert_called_once_with(self.project.resolve(), 'reviews/knight/inputs/character.json', 'reviews/knight/character')
        self.assertIn('data:image/png;base64,', (root / 'review.html').read_text())
        self.assertFalse((root / '.game-studio').exists())
        nodes = graph.export_graph(self.project)['@graph']
        activity = next(n for n in nodes if n['@id'] == result['activity'])
        self.assertTrue(activity['used'])
        self.assertTrue(any(n.get('path') == 'reviews/knight/review.html' for n in nodes))

    def test_action_set_only_with_all_genuine_authored_states(self):
        self.actor['actions'].update(walk=[1], run=[2], jump=[3])
        self.write_actor()
        result, _, producer = self.run_build()
        self.assertEqual(result['action_set'], 'reviews/knight/action-set/preview.gif')
        self.assertEqual(producer.call_args.args[0][:2], ['pixel-asset', 'action-set'])
        request = json.loads((self.project / 'reviews/knight/inputs/action-set.json').read_text())
        self.assertEqual(request['schema_version'], 1)
        self.assertEqual(set(request['actions']), {'idle', 'walk', 'run', 'attack', 'jump', 'hurt'})
        event = request['events'][0]
        self.assertEqual(event['frame'], 3)
        self.assertEqual(sum(f['duration_ms'] for f in request['actions']['attack']['frames'][:event['frame']]), 300)
        impact = json.loads((self.project / 'reviews/knight/inputs/impact.json').read_text())
        self.assertEqual(impact['frames'][0]['frame']['x'], 32)
        self.assertEqual(impact['frames'][0]['duration'], 40)

    def test_action_exposures_are_independent_of_reused_idle_hold(self):
        self.actor['frames'][0]['ms'] = 900
        self.actor['actions'].update(heavy=[0, 3], walk=[1], run=[2], jump=[3])
        self.actor['action_ms'] = {'heavy': [30, 70], 'recover': [160, 40], 'jump': [250]}
        self.write_actor()
        result, _, producer = self.run_build()
        self.assertEqual(result['status'], 'ready')
        producer.assert_called_once()
        root = self.project / 'reviews/knight/inputs'
        poses = json.loads((root / 'poses.json').read_text())['actions']
        self.assertEqual([f['duration_ms'] for f in poses['idle']['frames']], [900])
        self.assertEqual([f['duration_ms'] for f in poses['heavy']['frames']], [30, 70])
        self.assertEqual([f['duration_ms'] for f in poses['recover']['frames']], [160, 40])
        attack = poses['attack']['frames']
        self.assertEqual([f['duration_ms'] for f in attack], [30, 70, 200, 180, 160, 40])
        request = json.loads((root / 'action-set.json').read_text())
        self.assertEqual(request['actions']['attack']['frames'], attack)
        self.assertEqual(request['actions']['jump']['frames'][0]['duration_ms'], 250)
        self.actor['frames'][0]['ms'] = 1800
        self.write_actor()
        self.run_build('reviews/long-idle')
        updated = json.loads((self.project / 'reviews/long-idle/inputs/poses.json').read_text())['actions']
        self.assertEqual(updated['attack']['frames'], attack)
        self.assertEqual(updated['idle']['frames'][0]['duration_ms'], 1800)

    def test_invalid_action_exposure_maps_rejected_before_publication(self):
        invalid = [None, [], {'absent': [100]}, {'heavy': [100]},
                   {'heavy': [0, 100]}, {'heavy': [True, 100]},
                   {'heavy': [1.5, 100]}, {'heavy': [60001, 100]}]
        self.actor['actions']['recover'] = [0, 3, 6]
        invalid.append({'recover': [60000, 60000, 1]})
        for timings in invalid:
            with self.subTest(timings=timings):
                self.actor['action_ms'] = timings
                self.write_actor()
                with self.assertRaises(ValueError):
                    self.run_build()
                self.assertFalse((self.project / 'reviews/knight').exists())

    def test_default_actor_uses_shared_heavy_timing_and_bundled_impact(self):
        self.actor['image'] = 'blade.webp'
        (self.project / 'game/motion/manifest.mjs').write_text('export default ' + json.dumps({'blade': self.actor}) + ';')
        (self.project / 'game/motion/blade.webp').write_bytes((self.project / 'game/motion/job-0.webp').read_bytes())
        (self.project / 'game/jobs.mjs').write_text("export { DEFAULT_JOBS as JOBS } from './combat-fx.mjs';")
        (self.project / 'game/motif-ms.mjs').write_text('export const MOTIF_MS = ' + json.dumps({'blade': {'heavy': [220, 160, 480]}}) + ';')
        effect = {'image': 'fx/impact.png', 'pivot': [8, 8], 'frames': self.jobs['knight']['clip']['phases']['impact']}
        (self.project / 'game/fx/manifest.mjs').write_text('export default ' + json.dumps({'impact': effect}) + ';')
        (self.project / 'game/fx/impact.png').write_bytes((self.project / 'game/fx/job-clip-0.png').read_bytes())
        (self.project / 'game/fx/credits.json').write_text(json.dumps({'contact': {'license': 'fixture generated-pixel license', 'notice': 'fixture Pixel-generated contact'}}))
        with patch('combat_review.character.build', return_value={'status': 'ready'}):
            result = combat_review.build(self.project, 'blade', 'reviews/default')
        self.assertEqual(result['status'], 'ready')
        timing = json.loads((self.project / 'reviews/default/timing.json').read_text())
        self.assertEqual(timing['contact_ms'], 380)
        self.assertEqual(sum(f['ms'] for f in timing['phases']['impact']), 480)

    def test_input_aliases_and_escape_rejected_before_publication(self):
        path = self.project / 'game/motion/job-0.webp'
        original = path.read_bytes()
        path.unlink()
        target = self.project / 'original.webp'
        target.write_bytes(original)
        path.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            self.run_build()
        path.unlink()
        os.link(target, path)
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertFalse((self.project / 'reviews/knight').exists())
        for name in ('../escape', '.game-studio/review', 'game/review'):
            with self.assertRaises(ValueError):
                self.run_build(name)

    def test_existing_output_and_invalid_contact_do_not_overwrite(self):
        self.run_build()
        output = self.project / 'reviews/knight/review.html'
        previous = output.read_bytes()
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertEqual(output.read_bytes(), previous)
        self.jobs['knight']['clip']['phases']['travel'][0]['ms'] = -1
        self.write_jobs()
        with self.assertRaises(ValueError):
            self.run_build('reviews/bad')
        self.assertFalse((self.project / 'reviews/bad').exists())

    def test_job_actor_mismatch_and_malformed_frame_rejected(self):
        self.jobs['knight']['actor'] = 'job-1'
        self.write_jobs()
        with self.assertRaises(ValueError):
            self.run_build()
        self.jobs['knight']['actor'] = 'job-0'
        self.write_jobs()
        self.actor['frames'][0]['x'] = 9999
        self.write_actor()
        with self.assertRaises(ValueError):
            self.run_build()

    def test_unsupported_runtime_and_too_short_phase_rejected(self):
        with self.assertRaises(ValueError):
            combat_review.retime([{'duration_ms': 100}, {'duration_ms': 100}], 1)
        (self.project / 'game/timing.mjs').write_text('different runtime')
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertFalse((self.project / 'reviews/knight').exists())


if __name__ == '__main__':
    unittest.main()
