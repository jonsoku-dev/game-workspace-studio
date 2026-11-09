import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import web_game

class CombatStarterTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)

    def test_new_game_contains_offline_assets_and_preserves_existing_output(self):
        project=self.root/'tower'
        web_game.initialize_combat(project)
        receipt=web_game.export(project)
        manifest=json.loads(Path(receipt['receipt']).read_bytes())
        files={f['path'] for f in manifest['files']}
        self.assertTrue({'combat-motion.mjs','combat-fx.mjs','fx/credits.json','fx/fist.webp'} <= files)
        self.assertTrue(any(name.startswith('motion/') for name in files))
        with self.assertRaises((ValueError,OSError)):
            web_game.initialize_combat(project)
        self.assertTrue(Path(receipt['receipt']).is_file())

    def test_user_job_ids_and_distinct_sheets_survive_export(self):
        original=web_game.ROOT/'starter/combat-brief/resonance.webp'
        (self.root/'bell.webp').write_bytes(original.read_bytes())
        custom={'schema_version':1,'title':'별의 종','jobs':[
            {'id':'pitch','name':'공명','skill':'파문','motif':'astral','sheet':'bell.webp'},
            {'id':'echo','name':'메아리','skill':'별빛','motif':'astral'}]}
        brief=self.root/'brief.json';brief.write_text(json.dumps(custom))
        project=self.root/'choir'
        web_game.initialize_combat(project,brief)
        receipt=web_game.export(project)
        out=Path(receipt['output'])
        self.assertEqual(json.loads((out/'genre.json').read_bytes())['title'],'별의 종')
        self.assertEqual((out/'fx/custom-0.webp').read_bytes(),original.read_bytes())
        run=subprocess.run(['node','--input-type=module','-e',
            "import {JOBS} from './jobs.mjs'; console.log(JSON.stringify(JOBS));"],cwd=out,text=True,capture_output=True,check=True)
        jobs=json.loads(run.stdout)
        self.assertEqual(jobs['pitch']['sheet'],'./fx/custom-0.webp')
        self.assertNotIn('sheet',jobs['echo'])

    def test_invalid_brief_or_unsafe_sheet_is_atomic(self):
        base={'id':'bell','name':'종','skill':'음파','motif':'blade'}
        brief=self.root/'brief.json';project=self.root/'rejected'
        (self.root/'alias.webp').symlink_to(web_game.ROOT/'starter/combat-brief/resonance.webp')
        for jobs in ([base,base],[{**base,'sheet':'../outside.webp'}],[{**base,'sheet':'alias.webp'}],
                     [{**base,'motif':'typo'}],[{**base,'palette':['#ffffff']*3}]):
            with self.subTest(jobs=jobs):
                brief.write_text(json.dumps({'schema_version':1,'title':'invalid','jobs':jobs}))
                with self.assertRaises((ValueError,OSError)):
                    web_game.initialize_combat(project,brief)
                self.assertFalse(project.exists())
