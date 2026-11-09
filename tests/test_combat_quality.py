import io
import json
from pathlib import Path
import sys
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import combat_quality
import web_game


ROOT = Path(__file__).resolve().parents[1]


def encoded(image, format='PNG'):
    output = io.BytesIO()
    image.save(output, format=format, lossless=True)
    return output.getvalue()


class CombatQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.default = web_game._sources(ROOT / 'starter/combat')[1]
        # Use the same checked-in knight/skill/clip art without needing a sibling
        # example checkout or invoking an external producer during unit tests.
        cls.custom = dict(cls.default)
        art = ROOT / 'starter/combat-brief'
        actor = json.loads((art / 'bell-knight.json').read_bytes())
        actor['image'] = 'job-0.webp'
        cls.custom['game/motion/default.mjs'] = cls.default['game/motion/manifest.mjs']
        cls.custom['game/motion/manifest.mjs'] = ("import base from './default.mjs';\nexport default {...base,..." + json.dumps({'job-0': actor}) + '};').encode()
        cls.custom['game/motion/job-0.json'] = json.dumps(actor).encode()
        cls.custom['game/motion/job-0.webp'] = (art / 'bell-knight.webp').read_bytes()
        sheet = Image.open(io.BytesIO(cls.custom['game/motion/job-0.webp'])).convert('RGBA')
        idle = sheet.crop((0, 0, 512, 512))
        cls.custom['game/art/job-0-idle.webp'] = encoded(idle.crop(idle.getbbox()), 'WEBP')
        cls.custom['game/fx/custom-0.webp'] = (art / 'resonance.webp').read_bytes()
        clip_request = json.loads((art / 'clip.json').read_bytes())
        frames, phases, tags = [], {}, []
        clip_sheet = Image.new('RGBA', (192 * 6, 192))
        with Image.open(art / 'resonance.gif') as gif:
            for phase, exposures in clip_request['phases'].items():
                start = len(frames)
                for exposure in exposures:
                    gif.seek(exposure['frame'])
                    cell = gif.convert('RGBA').resize((192, 192))
                    clip_sheet.paste(cell, (len(frames) * 192, 0))
                    frames.append({'x': len(frames) * 192, 'y': 0, 'w': 192, 'h': 192, 'ms': exposure['duration_ms']})
                phases[phase] = frames[start:]
                tags.append({'name': phase, 'from': start, 'to': len(frames) - 1})
        cls.custom['game/fx/job-clip-0.png'] = encoded(clip_sheet)
        meta = {'frames': [{'frame': {k: f[k] for k in ('x', 'y', 'w', 'h')}, 'duration': f['ms']} for f in frames],
                'meta': {'frameTags': tags, 'pixelfx': {'pivot': [96, 96]}}}
        cls.custom['game/fx/job-clip-0.json'] = json.dumps(meta).encode()
        jobs = {'bell-knight': {'name': '공명기사', 'skill': '황동 파문', 'motif': 'astral', 'actor': 'job-0',
                               'sheet': './fx/custom-0.webp', 'clip': {'image': './fx/job-clip-0.png', 'pivot': [96, 96], 'phases': phases}},
                'clock-ranger': {'name': '시계궁수', 'skill': '분침 사격', 'motif': 'rail'}}
        cls.custom['game/jobs.mjs'] = ('export const JOBS = ' + json.dumps(jobs) + ';').encode()

    def findings(self, sources):
        report = combat_quality.assess(sources)
        self.assertEqual(report['status'], 'failed', report)
        self.assertEqual(report['artistic_acceptance'], 'pending')
        json.dumps(report)
        return report['findings']

    def actor(self, sources, change):
        actor = json.loads(sources['game/motion/blade.json'])
        change(actor)
        sources['game/motion/blade.json'] = json.dumps(actor).encode()
        manifest = combat_quality._module(sources['game/motion/manifest.mjs'])
        manifest['blade'] = actor
        sources['game/motion/manifest.mjs'] = ('export default ' + json.dumps(manifest) + ';').encode()

    def test_known_good_default_and_custom_use_only_active_actors(self):
        for sources, expected in ((self.default, [14, 14, 14, 14, 11]), (self.custom, [18, 14, 11])):
            with self.subTest(expected=expected):
                before = dict(sources)
                report = combat_quality.assess(sources)
                self.assertEqual(report['findings'], [])
                self.assertEqual(report['status'], 'passed')
                self.assertEqual([a['used_poses'] for a in report['actors']], expected)
                self.assertEqual([a['distinct_poses'] for a in report['actors']], expected)
                self.assertEqual(report['artistic_acceptance'], 'pending')
                self.assertEqual(sources, before)
                json.dumps(report)
        sources = dict(self.custom)
        sources['game/motion/blade.json'] = b'broken unused actor'
        self.assertEqual(combat_quality.assess(sources)['status'], 'passed')

    def test_high_resolution_painted_sheet_remains_valid(self):
        sources = dict(self.default)
        image = Image.open(io.BytesIO(sources['game/fx/sword.webp'])).convert('RGBA')
        sources['game/fx/sword.webp'] = encoded(image.resize((3072, 2048), Image.Resampling.NEAREST), 'WEBP')
        self.assertEqual(combat_quality.assess(sources)['findings'], [])

    def test_dead_states_and_duplicate_indices_do_not_pad_visible_coverage(self):
        sources = dict(self.default)
        def change(actor):
            actor['actions']['idle'] = [6, 6]
            actor['actions']['unused'] = [12]
            actor['actions']['run'] = [12]
        self.actor(sources, change)
        findings = self.findings(sources)
        self.assertTrue(any(f['asset'].endswith('blade.json') and f['code'] == 'pose-coverage' for f in findings))

    def test_shared_job_parser_preserves_names_and_overrides(self):
        self.assertEqual(combat_quality.jobs_for(self.default)['blade']['name'], '검사')
        job = combat_quality.jobs_for(self.custom)['bell-knight']
        self.assertEqual(job['name'], '공명기사')
        self.assertEqual(job['actor'], 'job-0')
        self.assertIn('clip', job)

    def test_repeated_pose_with_tint_translation_and_hidden_rgb_fails(self):
        sources = dict(self.default)
        original = Image.open(io.BytesIO(sources['game/motion/blade.webp'])).convert('RGBA')
        pose = original.crop((0, 0, 512, 512))
        sheet = Image.new('RGBA', original.size, (255, 19, 73, 0))
        for i in range(14):
            colored = Image.new('RGBA', pose.size, (30 + i * 10, 150, 230, 0))
            colored.putalpha(pose.getchannel('A'))
            sheet.alpha_composite(colored, (i * 512 + i % 3, i % 2))
        sources['game/motion/blade.webp'] = encoded(sheet, 'WEBP')
        codes = {f['code'] for f in self.findings(sources)}
        self.assertIn('gait-move', codes)
        self.assertIn('action-silhouettes', codes)
        self.assertIn('phase-heavy', codes)

    def test_prettified_single_shape_skill_sheet_fails(self):
        sources = dict(self.default)
        sheet = Image.new('RGBA', (960, 640))
        for i in range(6):
            x, y = i % 3 * 320, i // 3 * 320
            draw = ImageDraw.Draw(sheet)
            radius = 64 + i * 4
            draw.ellipse((x+160-radius, y+160-radius, x+160+radius, y+160+radius), fill=(30+i*30, 120, 240, 255))
            # Color detail must not turn a repeated silhouette into authored motion.
            draw.ellipse((x+150, y+150, x+170, y+170), fill='white')
        sources['game/fx/sword.webp'] = encoded(sheet, 'WEBP')
        self.assertTrue(any(f['asset'] == 'game/fx/sword.webp' and f['code'] == 'effect-geometry' for f in self.findings(sources)))

    def test_tiny_and_empty_painted_skill_cells_fail_at_native_resolution(self):
        for extent in (0, 4, 30):
            sources = dict(self.default)
            sheet = Image.new('RGBA', (960, 640))
            if extent:
                draw = ImageDraw.Draw(sheet)
                for i in range(6):
                    x, y = i % 3 * 320, i // 3 * 320
                    draw.rectangle((x+150, y+150, x+150+extent, y+150+extent), fill='white')
            sources['game/fx/sword.webp'] = encoded(sheet, 'WEBP')
            self.assertTrue(any(f['code'] == 'effect-data' for f in self.findings(sources)))

    def test_one_millisecond_preparation_and_recovery_fail(self):
        sources = dict(self.default)
        self.actor(sources, lambda actor: actor['action_ms'].update(heavy=[99, 1], recover=[1, 99]))
        codes = {f['code'] for f in self.findings(sources)}
        self.assertIn('exposure-heavy', codes)
        self.assertIn('exposure-recover', codes)

    def test_actor_and_clip_runtime_metadata_drift_fail(self):
        sources = dict(self.default)
        actor = json.loads(sources['game/motion/blade.json'])
        actor['actions']['release'] = [6]
        sources['game/motion/blade.json'] = json.dumps(actor).encode()
        self.assertTrue(any('differs' in f['repair'] for f in self.findings(sources)))
        sources = dict(self.custom)
        jobs = combat_quality.jobs_for(sources)
        jobs['bell-knight']['clip']['phases']['charge'][0]['ms'] = 1
        sources['game/jobs.mjs'] = ('export const JOBS = ' + json.dumps(jobs) + ';').encode()
        self.assertTrue(any('clip differs' in f['repair'] for f in self.findings(sources)))

    def test_flat_native_size_background_and_portrait_fail(self):
        for asset, size in (('game/art/bell-tower.jpg', (1650, 825)), ('game/art/blade-idle.webp', (474, 588))):
            sources = dict(self.default)
            sources[asset] = encoded(Image.new('RGB', size, '#354354'))
            self.assertTrue(any('단색' in f['repair'] for f in self.findings(sources)))

    def test_undersized_and_missing_runtime_assets_fail(self):
        sources = dict(self.default)
        sources['game/art/bell-tower.jpg'] = encoded(Image.open(io.BytesIO(sources['game/art/bell-tower.jpg'])).resize((640, 310)))
        self.assertTrue(any(f['code'] == 'background-resolution' for f in self.findings(sources)))
        del sources['game/motion/warden.webp']
        self.assertTrue(any(f['asset'].endswith('warden.json') for f in self.findings(sources)))

    def test_unused_actor_and_shared_fx_are_required_for_start_preloads(self):
        for asset, code in (('game/motion/blade.webp', 'actor-preload'), ('game/fx/storm.png', 'effect-data')):
            sources = dict(self.custom)
            del sources[asset]
            self.assertTrue(any(f['code'] == code for f in self.findings(sources)))
        sources = dict(self.custom)
        manifest = combat_quality._module(sources['game/motion/default.mjs'])
        manifest['blade']['frames'][0]['x'] = 999999
        sources['game/motion/default.mjs'] = ('export default ' + json.dumps(manifest) + ';').encode()
        self.assertTrue(any(f['code'] == 'actor-preload' for f in self.findings(sources)))

    def test_malformed_metadata_returns_actionable_report(self):
        sources = dict(self.custom)
        jobs = combat_quality.jobs_for(sources)
        jobs['bell-knight']['actor'] = 1
        sources['game/jobs.mjs'] = ('export const JOBS = ' + json.dumps(jobs) + ';').encode()
        self.assertEqual(self.findings(sources)[0]['code'], 'unsupported-runtime')
        for path in ('game/motion/manifest.mjs', 'game/fx/manifest.mjs'):
            sources = dict(self.default)
            sources[path] = b'export default null;'
            self.assertNotIn('NoneType', self.findings(sources)[0]['repair'])
        sources = dict(self.default)
        sources['game/jobs.mjs'] = b'export const JOBS = ' + b'[' * 1100 + b'0' + b']' * 1100 + b';'
        self.assertEqual(self.findings(sources)[0]['code'], 'unsupported-runtime')

    def test_unsupported_javascript_is_not_executed(self):
        sources = dict(self.default)
        sources['game/jobs.mjs'] = b'export const JOBS = (() => { throw new Error("must not run"); })();'
        self.assertEqual(self.findings(sources)[0]['code'], 'unsupported-runtime')

    def test_bad_frame_bounds_and_invalid_input_are_reports(self):
        sources = dict(self.default)
        self.actor(sources, lambda actor: actor['frames'][0].update(x=999999))
        self.assertTrue(any(f['code'] == 'actor-data' for f in self.findings(sources)))
        for bad in (None, {}, {'game/jobs.mjs': 'text'}, {str(i): b'' for i in range(258)}):
            self.assertEqual(self.findings(bad)[0]['code'], 'unsupported-runtime')


if __name__ == '__main__':
    unittest.main()
