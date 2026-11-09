import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from combat_motion import compile_motion
from combat_starter import attach_actor
from web_game import _read


class MotionSocketTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        Image.new('RGBA', (14, 14), '#f0d080').save(self.root / 'source.png')
        self.item = {'id': 'guard', 'path': 'source.png', 'crop': [2, 3, 9, 12],
                     'foot': [3, 8], 'scale': .6, 'sockets': {'weapon-tip': [6, 2]}}
        states = ('idle', 'move', 'windup', 'release', 'follow', 'recover', 'hurt', 'evade', 'heavy')
        self.spec = {'schema_version': 1, 'cell': [32, 32], 'pivot': [16, 24], 'kinds': {
            'blade': {'body_height': 20, 'frames': [self.item, {**self.item, 'id': 'rest', 'sockets': {}}],
                      'actions': {state: ['guard', 'rest'] for state in states}}}}

    def compile(self):
        request = self.root / 'request.json'
        request.write_text(json.dumps(self.spec))
        return compile_motion(request, self.root / 'out')

    def test_crop_resize_paste_and_import_preserve_socket_metadata(self):
        actor = self.compile()['blade']
        # Crop 7x9 becomes 4x5. Existing foot alignment pastes at (14,19).
        self.assertEqual(actor['frames'][0]['sockets']['weapon-tip'], [14 + 6 * 4 / 7, 19 + 2 * 5 / 9])
        self.assertNotIn('sockets', actor['frames'][1])
        stage = self.root / 'stage'
        (stage / 'game/art').mkdir(parents=True)
        (stage / 'game/motion').mkdir()
        key, imported = attach_actor(stage, 0, self.root / 'out', 'blade.json', _read)
        self.assertEqual(key, 'job-0')
        self.assertEqual(imported['frames'], actor['frames'])
        self.assertEqual(json.loads((stage / 'game/motion/job-0.json').read_text())['frames'], actor['frames'])
        for sockets in ({'bad_name': [1, 2]}, {'weapon': [float('nan'), 2]}, {'weapon': [33, 2]},
                        {'weapon': [1]}, [], {f'point-{i}': [1, 2] for i in range(17)}):
            with self.subTest(sockets=sockets):
                invalid = copy.deepcopy(actor)
                invalid['frames'][0]['sockets'] = sockets
                (self.root / 'out/bad.json').write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, 'sockets'):
                    attach_actor(stage, 0, self.root / 'out', 'bad.json', _read)

    def test_source_socket_admission_is_bounded_and_atomic(self):
        for sockets in ({'bad_name': [1, 2]}, {'weapon': [float('nan'), 2]}, {'weapon': [8, 2]},
                        {'weapon': [True, 2]}, {'weapon': [1]}, None,
                        {f'point-{i}': [1, 2] for i in range(17)}):
            with self.subTest(sockets=sockets):
                self.item['sockets'] = sockets
                with self.assertRaises(ValueError):
                    self.compile()
                self.assertFalse((self.root / 'out').exists())

    def test_transformed_socket_must_fit_cell(self):
        self.item.update(foot=[0, 0], sockets={'weapon': [7, 9]})
        self.spec['pivot'] = [31, 31]
        with self.assertRaisesRegex(ValueError, 'socket outside cell'):
            self.compile()
        self.assertFalse((self.root / 'out').exists())

    def test_ids_differing_only_by_case_are_rejected(self):
        frames = self.spec['kinds']['blade']['frames']
        frames[1]['id'] = 'Guard'
        for actions in self.spec['kinds']['blade']['actions'].values():
            actions[1] = 'Guard'
        with self.assertRaisesRegex(ValueError, 'ignoring case'):
            self.compile()
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
