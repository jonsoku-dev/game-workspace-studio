"""First-use scaffold admission and real local motion integration."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import start


class StartTests(unittest.TestCase):
    def test_new_pins_idea_rules_original_inputs_and_japanese_guidance(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'my game'
            result = start.create(project, '森のロボットが訓練する', '森の訓練', 'ja', 5)
            self.assertEqual(result['state'], 'build_required')
            self.assertIn('5', result['goal'])
            self.assertIn('次', result['next_label'])
            self.assertIn("'" + str(project.resolve()) + "'", result['next_command'])
            scene = json.loads((project / 'scene.json').read_text())
            self.assertEqual(scene['playtest']['hits_to_win'], 5)
            self.assertEqual(scene['brief']['idea'], '森のロボットが訓練する')
            self.assertTrue(start.pinned(project, project / 'requests/master.png'))
            self.assertTrue(start.pinned(project, project / 'first-slice.json'))
            self.assertFalse((project / 'requests/motion').exists())
            self.assertEqual(set(p.name for p in (project / 'requests').iterdir()), {'master.png', 'motion.json', 'LICENSE.txt', 'NOTICE.md'})

    def test_existing_destination_and_broken_template_never_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'existing'
            project.mkdir()
            (project / 'mine').write_text('keep')
            with self.assertRaises(ValueError):
                start.create(project, 'idea', 'title')
            self.assertEqual((project / 'mine').read_text(), 'keep')
            missing = Path(temp) / 'missing'
            with patch.object(start, 'TEMPLATES', Path(temp) / 'absent'):
                with self.assertRaises(ValueError):
                    start.create(missing, 'idea', 'title')
            self.assertFalse(missing.exists())

    def test_invalid_brief_and_hit_count_do_not_create_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'new'
            for idea, hits in [('', 3), ('idea', 0), ('idea', 21), ('idea', True)]:
                with self.assertRaises(ValueError):
                    start.create(project, idea, 'title', hits=hits)
            self.assertFalse(project.exists())

    def test_partial_motion_identifies_safe_inspection_next_step(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'new'
            start.create(project, 'robot practices', 'Practice')
            (project / 'requests/motion').mkdir()
            result = start.status(project)
            self.assertEqual(result['state'], 'blocked_motion')
            self.assertIn('graph.py history', result['next_command'])
            with self.assertRaises(ValueError):
                start.build(project)

    def test_changed_source_is_not_approved_by_starter(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'new'
            start.create(project, 'robot practices', 'Practice')
            (project / 'requests/master.png').write_bytes(b'new art')
            self.assertEqual(start.status(project)['state'], 'blocked_source')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                start.build(project)

    def test_three_dimensional_route_contains_only_admitted_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'camp'
            result = start.create(project, 'A quiet camp', 'Camp', kind='3d')
            self.assertEqual(result['state'], 'build_required')
            self.assertIn('3D', result['goal'])
            self.assertEqual(set(p.name for p in (project / 'requests').iterdir()), {'embers.json', 'lantern.json'})
            self.assertNotIn('playtest', json.loads((project / 'scene.json').read_text()))
            start.scene.load_scene(project)


if __name__ == '__main__':
    unittest.main()
