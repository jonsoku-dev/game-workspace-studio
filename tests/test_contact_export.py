import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import web_game, web_revision
class ContactExportTest(unittest.TestCase):
    def test_only_opted_in_exports_and_revisions_pin_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'game').mkdir();(p/'game/index.html').write_text('<title>Test</title>')
            spec=dict(schema_version=1,title='test',controls='aim',genre='action',goal='cut')
            (p/'genre.json').write_text(json.dumps(spec))
            web_game.export(p,'base')
            self.assertNotIn('contact.mjs',web_revision.accept_export(p,'base')['runtimes'])
            spec['contact']=True;(p/'genre.json').write_text(json.dumps(spec))
            web_revision.build(p,'base','next','change','Use installed contact geometry')
            self.assertEqual((p/'next/contact.mjs').read_bytes(),(web_game.ROOT/'engines/web/contact.mjs').read_bytes())
            self.assertIn('contact.mjs',web_revision.accept_export(p,'next')['runtimes'])
            (p/'game/contact.mjs').write_text('shadow')
            with self.assertRaises(ValueError):web_game.export(p,'rejected')
            self.assertFalse((p/'rejected').exists())
