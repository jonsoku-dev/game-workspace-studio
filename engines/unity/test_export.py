import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('unity_export', Path(__file__).with_name('export.py'))
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
ROOT = Path(__file__).resolve().parents[3]
DOTNET = os.environ.get('DOTNET') or shutil.which('dotnet')
SOURCES = [(ROOT / 'examples/forest-camp', 'builds/lantern-embers-final/scene.runtime.json'),
           (ROOT / 'examples/scout-actions', 'builds/attack-contact/scene.runtime.json')]


class UnityExportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('blender'), 'Local Blender required')
    def test_real_conversion_is_deterministic_and_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = [Path(tmp) / 'first', Path(tmp) / 'second']
            reports = [exporter.export(SOURCES, p) for p in outputs]
            self.assertEqual(reports[0], reports[1])
            self.assertEqual([(p['parts'], p['triangles']) for p in reports[0]], [(54, 23160), (1, 8)])
            media = outputs[0] / 'Assets/StreamingAssets/Studio'
            for relative, pin in json.loads((media / 'provenance.json').read_text()).items():
                self.assertEqual(hashlib.sha256((media / relative).read_bytes()).hexdigest(), pin['sha256'])
            for pin in json.loads((media / 'integrity.json').read_text())['files']:
                self.assertEqual(hashlib.sha256((media / pin['path']).read_bytes()).hexdigest(), pin['sha256'])
            self.assertTrue((outputs[0] / 'Assets/StudioGame.cs').is_file())
            modules = json.loads((outputs[0] / 'Packages/manifest.json').read_text())['dependencies']
            self.assertEqual(modules, {name: '1.0.0' for name in ('com.unity.modules.imageconversion', 'com.unity.modules.imgui', 'com.unity.modules.jsonserialize')})
            products = json.loads((media / 'products.json').read_text())['products']
            scout = products[1]['assets'][0]
            self.assertEqual(len(scout['clips']), 6)
            self.assertEqual(scout['pivot'], [24, 46])
            self.assertEqual(scout['events'][0]['start_ms'], 320)
            self.assertEqual(products[0]['scene']['nodes'][1]['parent'], 'camp-lantern')
            for converted in reports[0]:
                mesh = json.loads((media / converted['output']).read_text())
                for part in mesh['parts']:
                    self.assertEqual(len(part['vertices']), len(part['triangles']))
                    for i in range(0, len(part['triangles']), 3):
                        self.assertEqual(part['triangles'][i:i+3], [i, i+2, i+1])
            with self.assertRaises(ValueError):
                exporter.export(SOURCES, outputs[0])

    @unittest.skipUnless(shutil.which('blender'), 'Local Blender required')
    def test_base_color_texture_and_off_origin_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / 'fixture.py'
            script.write_text("""import bpy, sys
from pathlib import Path
p=Path(sys.argv[-1])
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh=bpy.data.meshes.new('triangle')
mesh.from_pydata([(2,3,4),(3,3,4),(2,4,4)],[],[(0,1,2)])
obj=bpy.data.objects.new('offset-triangle',mesh)
bpy.context.collection.objects.link(obj)
mesh.uv_layers.new()
mat=bpy.data.materials.new('textured'); mat.use_nodes=True
image=bpy.data.images.new('color',1,1); image.generated_color=(1,0,0,1)
image.filepath_raw=str(p/'color.png'); image.file_format='PNG'; image.save(); image.pack()
node=mat.node_tree.nodes.new('ShaderNodeTexImage'); node.image=image
bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
mat.node_tree.links.new(node.outputs['Color'],bsdf.inputs['Base Color'])
obj.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath=str(p/'fixture.glb'),export_format='GLB')
""")
            subprocess.run(['blender', '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(script), '--', str(root)], capture_output=True, check=True)
            target = root / 'mesh.json'
            subprocess.run(['blender', '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(Path(__file__).with_name('convert.py')), '--', str(root / 'fixture.glb'), str(target)], capture_output=True, check=True)
            part = json.loads(target.read_text())['parts'][0]
            self.assertTrue(part['texture'])
            self.assertEqual((root / part['texture']).read_bytes(), (root / 'color.png').read_bytes())
            self.assertEqual(part['vertices'][0], {'x': 2.0, 'y': 4.0, 'z': 3.0})
            self.assertEqual(len(part['uv']), 3)

    @unittest.skipUnless(DOTNET or (shutil.which('mcs') and shutil.which('mono')), 'No C# compiler/runtime; set DOTNET or install Mono separately')
    def test_actual_game_state_without_unity(self):
        source = Path(__file__).with_name('Assets') / 'StudioGame.cs'
        state = source.read_text().split('public class StudioGame : MonoBehaviour')[0].replace('using UnityEngine;', '')
        program = r'''public static class Check {
    static void Require(bool value) { if (!value) throw new System.Exception("Game state check failed"); }
    static string FeedbackStep(StudioGameState game, StudioGameFeedback feedback, float x, float z, bool attack, bool reset, float seconds) {
        bool started = attack && !game.Attacking && !game.Won && !reset;
        game.Step(x,z,attack,reset,seconds);
        return feedback.Observe(game,started,reset);
    }
    static void CheckFeedback() {
        var game = new StudioGameState(0.32f, 0.8f);
        var feedback = new StudioGameFeedback(0.32f);
        Require(FeedbackStep(game,feedback,0,0,false,true,0) == "restart");
        Require(FeedbackStep(game,feedback,1,0,false,false,1) == "move");
        Require(FeedbackStep(game,feedback,1,0,false,false,0.1f) == "stop");
        Require(FeedbackStep(game,feedback,0,0,true,false,0) == "attack");
        Require(FeedbackStep(game,feedback,0,0,true,false,0.319f) == "");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.001f) == "miss");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.481f) == "");
        Require(FeedbackStep(game,feedback,0,0,false,true,0) == "restart");
        Require(FeedbackStep(game,feedback,0,0,false,false,0) == "");
        FeedbackStep(game,feedback,-1,0,false,false,0.5f);
        FeedbackStep(game,feedback,0,1,false,false,0.25f);
        Require(FeedbackStep(game,feedback,0,0,true,false,0) == "attack");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.319f) == "");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.001f) == "pickup");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.481f) == "");
        FeedbackStep(game,feedback,1,0,false,false,0.5f);
        FeedbackStep(game,feedback,0,1,false,false,0.5f);
        Require(FeedbackStep(game,feedback,0,0,true,false,0.801f) == "pickup");
        FeedbackStep(game,feedback,1,0,false,false,0.5f);
        FeedbackStep(game,feedback,0,-1,false,false,0.5f);
        Require(FeedbackStep(game,feedback,0,0,true,false,0.32f) == "win");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.481f) == "");
        Require(FeedbackStep(game,feedback,0,0,true,false,0) == "");
        Require(FeedbackStep(game,feedback,0,0,false,true,0) == "restart");
        Require(FeedbackStep(game,feedback,0,0,false,false,0) == "");
        Require(FeedbackStep(game,feedback,0,0,true,false,0.1f) == "attack");
        Require(FeedbackStep(game,feedback,0,0,false,true,0) == "restart");
        Require(FeedbackStep(game,feedback,0,0,false,false,0.8f) == "");
    }
    public static void Main() {
        CheckFeedback();
        var game = new StudioGameState(0.32f, 0.8f);
        game.Step(1,0,false,false,1); Require(game.X == 2);
        game.Step(0,0,true,false,0); game.Step(0,0,false,false,0.8f);
        Require(!game.Collected[0] && !game.Collected[1] && !game.Collected[2]);
        game.Step(0,0,false,true,0);
        game.Step(-1,0,false,false,0.5f); game.Step(0,1,false,false,0.25f);
        game.Step(0,0,true,false,0); Require(!game.Collected[0]);
        game.Step(0,0,false,false,0.319f); Require(!game.Collected[0]);
        game.Step(0,0,false,false,0.001f); Require(game.Collected[0]);
        game.Step(0,0,false,false,0.481f);
        game.Step(1,0,false,false,0.5f); game.Step(0,1,false,false,0.5f);
        game.Step(0,0,true,false,0); game.Step(0,0,false,false,0.801f);
        Require(game.Collected[1] && !game.Won);
        game.Step(1,0,false,false,0.5f); game.Step(0,-1,false,false,0.5f);
        game.Step(0,0,true,false,0); game.Step(0,0,false,false,0.32f); Require(game.Won);
        game.Step(0,0,false,true,0); Require(!game.Won && game.X == 0 && game.Z == 0 && !game.Attacking);
    }
}'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Check.cs'; path.write_text(state + program)
            if DOTNET:
                env = {**os.environ, 'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1',
                       'DOTNET_NOLOGO': '1', 'DOTNET_GENERATE_ASPNET_CERTIFICATE': 'false', 'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH': 'false',
                       'DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE': 'true', 'DOTNET_CLI_HOME': str(Path(tmp) / 'home'), 'NUGET_PACKAGES': str(Path(tmp) / 'nuget')}
                version = subprocess.run([DOTNET, '--version'], capture_output=True, text=True, check=True, env=env).stdout.strip()
                framework = 'net' + version.split('.')[0] + '.0'
                (Path(tmp) / 'Check.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>' + framework + '</TargetFramework><NuGetAudit>false</NuGetAudit></PropertyGroup></Project>')
                config = Path(tmp) / 'NuGet.Config'
                config.write_text('<configuration><packageSources><clear /></packageSources></configuration>')
                built = subprocess.run([DOTNET, 'build', str(Path(tmp) / 'Check.csproj'), '--configfile', str(config), '--output', str(Path(tmp) / 'out')], capture_output=True, text=True, env=env, timeout=90)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                ran = subprocess.run([DOTNET, str(Path(tmp) / 'out/Check.dll')], capture_output=True, text=True, env=env, timeout=15)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            else:
                executable = Path(tmp) / 'check.exe'
                subprocess.run(['mcs', '-out:' + str(executable), str(path)], capture_output=True, check=True)
                subprocess.run(['mono', str(executable)], capture_output=True, check=True)

    def test_drift_and_escaping_input_leave_no_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaises(ValueError):
                exporter.export([(Path(tmp), '../outside.json')], out)
            project = Path(tmp) / 'source'
            shutil.copytree(SOURCES[0][0], project)
            model = project / 'builds/lantern-embers-final/assets/lantern/model.glb'
            model.write_bytes(model.read_bytes() + b'drift')
            with self.assertRaisesRegex(ValueError, 'drift'):
                exporter.export([(project, SOURCES[0][1])], out)
            self.assertFalse(out.exists())

    def test_unsupported_glb_and_invalid_timing_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.glb'
            path.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                exporter.glb_static(path)
            metadata = {'actions': {'idle': {'loop': True, 'duration_ms': 1, 'frames': [{'duration_ms': -1}]}}}
            with self.assertRaisesRegex(ValueError, 'timing'):
                exporter.clips(metadata)

    def test_failed_converter_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            with self.assertRaises(OSError):
                exporter.export(SOURCES, out, '/nonexistent/studio-blender')
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
