from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import web_game
import web_revision
from PIL import Image


class AssetExportFlow(unittest.TestCase):
    def test_revision_returns_repair_board_and_leaves_baseline_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'duel'
            web_game.initialize_combat(project)
            first=web_game.export(project,'play/baseline')
            baseline=Path(first['receipt']).read_bytes()
            self.assertEqual(first['asset_review']['status'],'passed')
            self.assertTrue((project/first['asset_review']['board']).is_file())
            self.assertIn('검사',(project/'art-direction.md').read_text())
            actor=project/'game/motion/blade.webp'
            with Image.open(actor) as im:
                still=im.crop((0,0,512,512))
                replacement=Image.new('RGBA',im.size)
                for x in range(0,im.width,512):
                    replacement.paste(still,(x,0))
            replacement.save(actor,lossless=True)
            with self.assertRaises(web_revision.RevisionError) as caught:
                web_revision.build(project,'play/baseline','play/failed','change','Replace actor')
            summary=caught.exception.result
            quality=summary['asset_review']
            self.assertEqual(quality['status'],'failed')
            self.assertFalse((project/'play/failed').exists())
            self.assertEqual(Path(first['receipt']).read_bytes(),baseline)
            self.assertTrue((project/quality['art_direction']).is_file())
            self.assertIn('gait-move',{item['code'] for item in quality['findings']})

    def test_missing_sheet_and_untrusted_name_remain_reviewable_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'duel'
            web_game.initialize_combat(project,web_game.ROOT/'starter/combat-brief/falcon.json')
            script=project/'game/jobs.mjs'
            script.write_text(script.read_text().replace('빙정사수','</script><img onerror=alert(1)>'))
            (project/'game/fx/custom-0.webp').unlink()
            _,sources=web_game._sources(project)
            q=web_game.asset_review.inspect(project,sources,web_game.ROOT,web_game._read,web_game._sources)
            page=(project/q['board']).read_text()
            self.assertEqual(q['status'],'failed')
            self.assertIn('Content-Security-Policy',page)
            self.assertNotIn('</script><img onerror=alert(1)>',page)
            embedded=json.loads(page.split('id="data" type="application/json">')[1].split('</script>')[0])
            self.assertEqual(embedded['reference']['actors'][0]['name'],'공명기사')
            self.assertGreater(len(embedded['images']),0)

    def test_unrelated_web_game_keeps_original_export_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)
            (project/'game').mkdir()
            (project/'game/index.html').write_text('<title>puzzle</title>')
            (project/'game/combat-fx.mjs').write_text('// standalone optional effect')
            (project/'genre.json').write_text(json.dumps(dict(schema_version=1,title='puzzle',genre='puzzle',controls='click',goal='match')))
            receipt=web_game.export(project)
            self.assertNotIn('asset_review',receipt)
