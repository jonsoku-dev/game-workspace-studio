import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import struct
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("scene", ROOT / "tools/scene.py")
scene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scene)


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(ROOT / "examples/forest-camp", self.project,
                        ignore=shutil.ignore_patterns("build", ".game-studio"))
        self.data = scene.read_json(self.project / "scene.json")

    def save(self):
        scene.write_json(self.project / "scene.json", self.data)

    def pixel_only(self):
        self.data["assets"] = [{"id": "reward", "producer": "pixel-effect", "request": "requests/reward.json"}]
        self.data["nodes"] = [{"id": "camp-reward", "asset": "reward", "position": [1, 0.45, -2],
                               "rotation_degrees": [0, 0, 0], "scale": [1, 1, 1], "size_m": 0.5}]
        self.save()

    def action_project(self):
        folder = self.project / "requests"
        (folder / "poses").mkdir()
        (folder / "fx").mkdir()
        for name, data in {"poses/shared.png": b"original-frame", "fx/atlas.png": b"original-fx",
                           "fx/atlas.json": b'{"schema_version":1}', "fx/LICENSE": b"CC0", "fx/NOTICE": b"Source notice"}.items():
            (folder / name).write_bytes(data)
        actions = {name: {"loop": name in ("idle", "walk", "run"),
                          "frames": [{"path": "poses/shared.png", "duration_ms": 100}] * 3}
                   for name in ("idle", "walk", "run", "attack", "jump", "hurt")}
        request = {"schema_version": 1, "cell_size": [16, 16], "pivot_px_from_top_left": [8, 14],
                   "actions": actions, "events": [{"action": "attack", "frame": 0, "sheet": "fx/atlas.png",
                       "metadata": "fx/atlas.json", "license": "fx/LICENSE", "notice": "fx/NOTICE"}]}
        scene.write_json(folder / "actions.json", request)
        self.data["assets"] = [{"id": "actor", "producer": "pixel-action-set", "request": "requests/actions.json"}]
        self.data["nodes"] = [{"id": "actor-node", "asset": "actor", "action": "attack", "position": [0, 0, 0],
                               "rotation_degrees": [0, 0, 0], "scale": [1, 1, 1], "size_m": 0.5}]
        self.save()
        return request

    def test_action_set_stages_only_named_inputs_and_keeps_provenance(self):
        request = self.action_project()
        (self.project / "requests/unrelated.txt").write_text("not an input")
        calls = []
        copy = scene.copy_pinned

        def copy_once(source, target, pin):
            calls.append(source)
            return copy(source, target, pin)

        def run(command, timeout):
            self.assertEqual(command[1], "action-set")
            staged = Path(command[command.index("--request") + 1])
            self.assertEqual(scene.read_json(staged), request)
            self.assertEqual((staged.parent / "poses/shared.png").read_bytes(), b"original-frame")
            self.assertEqual((staged.parent / "fx/LICENSE").read_bytes(), b"CC0")
            self.assertFalse((staged.parent / "unrelated.txt").exists())
            (self.project / "requests/poses/shared.png").write_bytes(b"changed-after-staging")
            bundle = Path(command[command.index("--out") + 1])
            bundle.mkdir(parents=True)
            files = {"atlas": "atlas.png", "metadata": "action-set.json", "preview": "preview.gif", "credits": "credits.json"}
            for filename in files.values():
                (bundle / filename).write_bytes(b"output")
            scene.write_json(bundle / files["metadata"], {"schema_version": 1, "actions": request["actions"]})
            return {"schema_version": 1, "status": "ready", "files": files}

        identity = {"name": "pixel-asset-pipeline", "version": "test-installed", "sha256": "test-launcher"}
        with patch.object(scene, "pixel_producer", return_value=(Path("/installed/pixel-asset"), identity)), patch.object(scene, "run_json", side_effect=run), patch.object(scene, "copy_pinned", side_effect=copy_once):
            result = scene.build(self.project, "build/action-set", 30)
        self.assertEqual(len(calls), 5, "repeated frame paths should copy once")
        runtime = scene.read_json(self.project / result["files"]["scene"])
        self.assertEqual(runtime["nodes"][0]["action"], "attack")
        snapshot = self.project / runtime["assets"][0]["request"]
        self.assertEqual((snapshot.parent / "poses/shared.png").read_bytes(), b"original-frame")
        self.assertEqual(scene.graph.history(self.project)[0]["steps"][0]["implementation"], identity)
        imported = scene.graph.query(self.project, kind="Imported2DInput")
        self.assertEqual(len(imported), 5)

    @unittest.skipUnless(shutil.which("pixel-asset"), "installed pixel-asset unavailable")
    def test_actual_standalone_action_set(self):
        request = self.action_project()
        request["events"] = []
        request["cell_size"] = [8, 8]
        request["pivot_px_from_top_left"] = [4, 7]
        scene.write_json(self.project / "requests/actions.json", request)

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", 8, 8, 8, 6, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress((b"\x00" + bytes([68, 98, 74, 255]) * 8) * 8)) + chunk(b"IEND", b"")
        (self.project / "requests/poses/shared.png").write_bytes(png)
        result = scene.build(self.project, "build/actual-action-set", 30)
        runtime = scene.read_json(self.project / result["files"]["scene"])
        self.assertEqual(runtime["nodes"][0]["action"], "attack")
        files = runtime["assets"][0]["files"]
        manifest = scene.read_json(self.project / files["metadata"])
        self.assertEqual(set(manifest["actions"]), set(request["actions"]))
        self.assertEqual(len(manifest["actions"]["attack"]["frames"]), 3)
        self.assertTrue((self.project / files["atlas"]).is_file())
        self.assertTrue((self.project / files["preview"]).is_file())
        self.assertEqual(len(scene.graph.query(self.project, kind="Imported2DInput")), 1)

    def test_action_set_rejects_unavailable_output_action(self):
        self.action_project()

        def run(command, timeout):
            bundle = Path(command[command.index("--out") + 1])
            bundle.mkdir(parents=True)
            files = {"atlas": "atlas.png", "metadata": "action-set.json", "preview": "preview.gif", "credits": "credits.json"}
            for filename in files.values():
                (bundle / filename).write_bytes(b"output")
            scene.write_json(bundle / files["metadata"], {"schema_version": 1, "actions": {"idle": {}}})
            return {"schema_version": 1, "status": "ready", "files": files}

        with patch.object(scene, "pixel_producer", return_value=(Path("/installed/pixel-asset"), {})), patch.object(scene, "run_json", side_effect=run):
            with self.assertRaises(ValueError):
                scene.build(self.project, "build/missing-action", 30)
        self.assertFalse((self.project / "build/missing-action/scene.runtime.json").exists())
        self.assertEqual(scene.graph.history(self.project)[0]["error"]["stage"], "bundle-validation")

    def test_action_set_rejects_unknown_action_and_escaped_input(self):
        request = self.action_project()
        self.data["nodes"][0]["action"] = "missing"
        self.save()
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)
        self.data["nodes"][0]["action"] = "attack"
        self.save()
        for path in ("../scene.json", str(self.project / "scene.json")):
            request["actions"]["idle"]["frames"][0]["path"] = path
            scene.write_json(self.project / "requests/actions.json", request)
            with self.assertRaises(ValueError):
                scene.load_scene(self.project)
        (self.project / "requests/outside.png").symlink_to(self.project / "scene.json")
        request["actions"]["idle"]["frames"][0]["path"] = "outside.png"
        scene.write_json(self.project / "requests/actions.json", request)
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)

    def test_action_set_detects_input_drift_before_execution(self):
        self.action_project()
        update = scene.graph.update_run
        changed = False

        def mutate(project, record, data):
            nonlocal changed
            result = update(project, record, data)
            if not changed:
                changed = True
                (self.project / "requests/poses/shared.png").write_bytes(b"changed-before-copy")
            return result

        with patch.object(scene.graph, "update_run", side_effect=mutate), patch.object(scene, "run_json") as producer:
            with self.assertRaises(ValueError):
                scene.build(self.project, "build/drift", 30)
            producer.assert_not_called()
        self.assertEqual(scene.graph.history(self.project)[0]["error"]["stage"], "inputs")

    def ready_source(self, producer="pixel-effect"):
        self.pixel_only()
        self.data["assets"][0]["producer"] = producer
        if producer == "model-assets":
            self.data["assets"][0]["request"] = "requests/lantern.json"
        self.save()

        def run(command, timeout):
            bundle = Path(command[command.index("--out") + 1])
            bundle.mkdir(parents=True)
            files = {role: role + ".json" for role in scene.PRODUCERS[producer]}
            if producer == "model-assets":
                files["model"] = "compiled.glb"
            for name in files.values():
                (bundle / name).write_text("{}")
            if producer == "model-assets":
                scene.write_json(bundle / files["validation"], {"passed": True})
            return {"schema_version": 1, "status": "ready", "files": files}

        with patch.object(scene, "pixel_producer", return_value=(Path("pixel"), {})), patch.object(scene, "model_root", return_value=self.project), patch.object(scene, "run_json", side_effect=run):
            result = scene.build(self.project, "build/original", 30)
        source = scene.graph.history(self.project)[0]
        self.data["assets"] = [{"id": "reward", "producer": producer,
                                "reuse": {"run_id": result["run_id"], "asset": "reward"}}]
        self.data["nodes"][0]["position"] = [2, 3, 4]
        self.save()
        return source

    def test_explicit_reuse_preserves_files_and_original_provenance_without_producers(self):
        for producer in ("pixel-effect", "model-assets"):
            with self.subTest(producer=producer):
                if (self.project / "build").exists():
                    shutil.rmtree(self.project / "build")
                    shutil.rmtree(self.project / ".game-studio")
                source = self.ready_source(producer)
                original = {path: (self.project / path).read_bytes() for path in source["assets"][0]["files"].values()}
                with patch.object(scene, "pixel_producer", side_effect=AssertionError("producer discovery")), patch.object(scene, "model_root", side_effect=AssertionError("producer discovery")), patch.object(scene, "run_json", side_effect=AssertionError("producer execution")):
                    result = scene.build(self.project, "build/placement", 30)
                runtime = scene.read_json(self.project / result["files"]["scene"])
                self.assertEqual(runtime["assets"][0]["files"], source["assets"][0]["files"])
                self.assertEqual(runtime["nodes"][0]["position"], [2, 3, 4])
                for path, data in original.items():
                    self.assertEqual((self.project / path).read_bytes(), data)
                reused = scene.graph.history(self.project)[-1]
                self.assertEqual(reused["steps"][0]["status"], "reused")
                self.assertEqual(reused["assets"][0]["reuse"]["run"], source["graph_id"])
                nodes = scene.graph.export_graph(self.project)["@graph"]
                self.assertFalse(any("Artifact" in node["@type"] and node["@id"].startswith(reused["graph_id"] + ":artifact:") for node in nodes))
                self.data["assets"][0]["reuse"]["run_id"] = reused["graph_id"]
                self.save()
                scene.build(self.project, "build/chained", 30)

    def test_reuse_rejects_drift_missing_nonready_and_ambiguous_inputs(self):
        source = self.ready_source()
        path = self.project / source["assets"][0]["files"]["sheet"]
        original = path.read_bytes()
        cases = [("drift", "reuse_mismatch"), ("missing", "missing_input"),
                 ("run", "reuse_not_ready"), ("producer", "reuse_mismatch"), ("request", "invalid_reuse")]
        for mode, code in cases:
            with self.subTest(mode=mode):
                path.write_bytes(original)
                self.data["assets"][0] = {"id": "reward", "producer": "pixel-effect",
                    "reuse": {"run_id": source["run_id"], "asset": "reward"}}
                if mode == "drift":
                    path.write_bytes(b"changed")
                elif mode == "missing":
                    path.unlink()
                elif mode == "run":
                    self.data["assets"][0]["reuse"]["run_id"] = "nonexistent"
                elif mode == "producer":
                    self.data["assets"][0]["producer"] = "model-assets"
                else:
                    self.data["assets"][0]["request"] = "requests/reward.json"
                self.save()
                with self.assertRaises(ValueError):
                    scene.build(self.project, "build/rejected-" + mode, 30)
                failure = scene.graph.history(self.project)[-1]["error"]
                self.assertEqual(failure["code"], code)
                self.assertNotIn(str(self.project), json.dumps(failure))
                self.assertFalse((self.project / ("build/rejected-" + mode)).exists())

    def test_reuse_rejects_source_symlink_escape(self):
        source = self.ready_source()
        path = self.project / source["assets"][0]["files"]["sheet"]
        outside = Path(self.temp.name) / "outside-artifact"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            scene.build(self.project, "build/escaped", 30)
        error = scene.graph.history(self.project)[-1]["error"]
        self.assertEqual(error["code"], "confinement")
        self.assertNotIn(str(outside), json.dumps(error))

    def test_reuse_drift_during_build_records_failure_without_publishing(self):
        source = self.ready_source()
        original = scene.resolve_reuse
        calls = 0

        def drift(project, asset):
            nonlocal calls
            calls += 1
            if calls == 3:
                (project / source["assets"][0]["files"]["sheet"]).write_bytes(b"drift")
            return original(project, asset)

        with patch.object(scene, "resolve_reuse", side_effect=drift):
            with self.assertRaises(ValueError):
                scene.build(self.project, "build/drift", 30)
        failure = scene.graph.history(self.project)[-1]
        self.assertEqual(failure["status"], "error")
        self.assertEqual(failure["error"]["code"], "reuse_mismatch")
        self.assertTrue((self.project / "build/drift/failure.json").is_file())
        self.assertFalse((self.project / "build/drift/scene.runtime.json").exists())

    def test_concurrent_reuse_uses_distinct_outputs(self):
        self.ready_source()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda suffix: scene.build(self.project, "build/" + suffix, 30), ("left", "right")))
        self.assertEqual([result["status"] for result in results], ["ready", "ready"])
        self.assertNotEqual(results[0]["run_id"], results[1]["run_id"])
        self.assertEqual(len(scene.graph.history(self.project)), 3)

    def test_safe_actionable_admission_errors(self):
        for field, value, code in (("schema_version", 9, "invalid_schema"),
                                   ("brief", {}, "invalid_brief")):
            original = self.data[field]
            self.data[field] = value
            self.save()
            with self.assertRaises(ValueError):
                scene.build(self.project, "build/invalid-" + field, 30)
            error = scene.graph.history(self.project)[-1]["error"]
            self.assertEqual(error["code"], code)
            self.assertTrue(error["reason"])
            self.data[field] = original
        self.save()
        with self.assertRaises(ValueError):
            scene.build(self.project, "../secret-path", 30)
        self.assertEqual(scene.graph.history(self.project)[-1]["error"]["code"], "confinement")
        for name in (".game-studio/runs/x.jsonld", ".game-studio/tmp", ".game-studio"):
            with self.assertRaises(ValueError):
                scene.build(self.project, name, 30)
            self.assertEqual(scene.graph.history(self.project)[-1]["error"]["code"], "confinement")
        self.assertFalse((self.project / ".game-studio/runs/x.jsonld").exists())
        self.assertFalse((self.project / ".game-studio/tmp").exists())

    def test_example_and_invalid_boundaries(self):
        scene.load_scene(self.project)
        for value in ("../outside.json", "/etc/passwd"):
            self.data["assets"][0]["request"] = value
            self.save()
            with self.assertRaises(ValueError):
                scene.load_scene(self.project)
        self.data["assets"][0]["request"] = "requests/reward.json"
        self.data["nodes"][0]["position"] = [float("nan"), 0, 0]
        (self.project / "scene.json").write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)

    def test_parent_hierarchy_is_local_and_acyclic(self):
        loaded = scene.load_scene(self.project)
        self.assertEqual(loaded["nodes"][1]["parent"], "camp-lantern")
        self.assertEqual(loaded["nodes"][1]["position"], [0, 0.239, 0])
        for parent in ("unknown", "camp-embers", None):
            self.data["nodes"][1]["parent"] = parent
            self.save()
            with self.assertRaises(ValueError):
                scene.load_scene(self.project)
        self.data["nodes"][1]["parent"] = "camp-lantern"
        self.data["nodes"][0]["parent"] = "camp-embers"
        self.save()
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)
        del self.data["nodes"][0]["parent"]
        self.data["nodes"].reverse()
        self.save()
        scene.load_scene(self.project)

    def effect(self):
        return {"schema_version": 1, "kind": "mesh-particles", "units": "meters", "duration_s": 3.2,
                "particles": [{"offset": [0, 0, 0], "drift": [0.01, 0.08, 0.01], "spin": [0, 1, 0],
                               "start_s": 0, "life_s": 2, "scale": 1}]}

    def test_native_effect_recipe_validation(self):
        scene.verify_effect(self.effect())
        for field, value in (("duration_s", float("nan")), ("duration_s", True), ("particles", []),
                             ("kind", "sprite")):
            recipe = self.effect()
            recipe[field] = value
            with self.assertRaises(ValueError):
                scene.verify_effect(recipe)
        for field, value in (("life_s", 0), ("scale", -1), ("start_s", 3.2), ("drift", [0, float("inf"), 0])):
            recipe = self.effect()
            recipe["particles"][0][field] = value
            with self.assertRaises(ValueError):
                scene.verify_effect(recipe)

    def test_embers_requires_effect_and_pins_mesh_and_motion(self):
        self.data["assets"] = [a for a in self.data["assets"] if a["id"] == "embers"]
        self.data["nodes"] = [n for n in self.data["nodes"] if n["asset"] == "embers"]
        del self.data["nodes"][0]["parent"]
        self.save()

        mode = "missing"

        def run(command, timeout):
            bundle = Path(command[command.index("--out") + 1])
            bundle.mkdir(parents=True)
            files = {key: key + ".json" for key in scene.PRODUCERS["model-assets"]}
            files["model"] = "compiled.glb"
            for value in files.values():
                (bundle / value).write_text('{}')
            scene.write_json(bundle / files["validation"], {"passed": True})
            result = {"schema_version": 1, "status": "ready", "files": files}
            if mode != "missing":
                files["effect"] = "effect.json"
                scene.write_json(bundle / "effect.json", {} if mode == "malformed" else self.effect())
            return result

        with patch.object(scene, "model_root", return_value=Path(self.temp.name)), patch.object(scene, "run_json", side_effect=run):
            for mode in ("missing", "malformed"):
                with self.assertRaises(ValueError):
                    scene.build(self.project, f"build/{mode}", 30)
                self.assertFalse((self.project / f"build/{mode}/scene.runtime.json").exists())
                self.assertEqual(scene.graph.history(self.project)[-1]["error"]["stage"], "bundle-validation")
            mode = "ready"
            result = scene.build(self.project, "build/embers", 30)
        runtime = scene.read_json(self.project / result["files"]["scene"])
        files = runtime["assets"][0]["files"]
        self.assertTrue((self.project / files["model"]).is_file())
        self.assertEqual(scene.read_json(self.project / files["effect"]), self.effect())
        artifacts = scene.graph.query(self.project, kind="Artifact")
        self.assertEqual({a["role"] for a in artifacts} & {"model", "effect"}, {"model", "effect"})
        record = scene.graph.history(self.project)[-1]
        self.assertIn("mesh-particles-contract", record["steps"][0]["validation"]["checks"])

    def test_unknown_asset_and_duplicates(self):
        self.data["nodes"][0]["asset"] = "missing"
        self.save()
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)
        self.data["nodes"][0]["asset"] = "lantern"
        self.data["assets"].append(self.data["assets"][0])
        self.save()
        with self.assertRaises(ValueError):
            scene.load_scene(self.project)

    def test_symlink_escape(self):
        (self.project / "outside").symlink_to(self.project.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            scene.build(self.project, "outside/run", 30)

    @unittest.skipUnless(os.name == "posix", "process-group cleanup targets POSIX")
    def test_timeout_stops_delayed_grandchild(self):
        marker = Path(self.temp.name) / "late-artifact"
        child = ("import signal,time; from pathlib import Path; "
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 f"time.sleep(0.5); Path({str(marker)!r}).write_text('late')")
        producer = ("import subprocess,sys,time; "
                    f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)")
        with self.assertRaises(subprocess.TimeoutExpired):
            scene.run_json([sys.executable, "-c", producer], 0.2)
        time.sleep(0.6)
        self.assertFalse(marker.exists(), "timed-out producer descendant wrote an artifact")

    @unittest.skipUnless(os.name == "posix", "process-group cleanup targets POSIX")
    def test_keyboard_interrupt_stops_and_reaps_producer(self):
        with patch.object(scene.subprocess, "Popen") as popen, patch.object(scene.os, "killpg") as killpg:
            process = popen.return_value.__enter__.return_value
            process.pid = 123456
            process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
            with self.assertRaises(KeyboardInterrupt):
                scene.run_json(["producer"], 1)
            killpg.assert_called_once_with(123456, signal.SIGKILL)
            self.assertEqual(process.communicate.call_count, 2)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_installed_model_discovery(self):
        root = Path(self.temp.name) / "plugins/cache/model-assets/model-assets/0.1.0"
        (root / "tools").mkdir(parents=True)
        (root / "tools/build.py").touch()
        listing = {"installed": [{"name": "model-assets", "marketplaceName": "model-assets",
                                  "installed": True, "enabled": True, "version": "0.1.0"}]}
        with patch.dict(os.environ, {"CODEX_HOME": self.temp.name}, clear=True), patch.object(scene, "run_json", return_value=listing):
            self.assertEqual(scene.model_root(), root.resolve())
            listing["installed"][0]["enabled"] = False
            with self.assertRaises(ValueError):
                scene.model_root()

    def test_model_implementation_fingerprints_sources_and_lock(self):
        root = Path(self.temp.name) / "producer"
        for name in ("tools/build.py", "tools/blender_worker.py", "tools/lantern.py", "tools/ember.py", "three/inspect.mjs",
                     "three/loader.mjs", "three/package-lock.json", ".codex-plugin/plugin.json"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"version":"test-revision"}' if name.endswith("plugin.json") else name)
        first = scene.model_implementation(root)
        self.assertEqual(first["version"], "test-revision")
        self.assertEqual(first, scene.model_implementation(root))
        copied = Path(self.temp.name) / "copied-producer"
        shutil.copytree(root, copied)
        self.assertEqual(first, scene.model_implementation(copied))
        for name in ("tools/lantern.py", "tools/ember.py", "three/package-lock.json"):
            path = root / name
            path.write_text(path.read_text() + "changed")
            self.assertNotEqual(first["sha256"], scene.model_implementation(root)["sha256"])

    def test_pixel_implementation_tracks_actual_launcher_without_host_paths(self):
        launcher = Path(self.temp.name) / "pixel-launcher"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        alias = Path(self.temp.name) / "pixel-asset"
        alias.symlink_to(launcher)
        with patch.object(scene.shutil, "which", return_value=str(alias)):
            executable, identity = scene.pixel_producer()
            self.assertEqual(executable, launcher.resolve())
            self.assertEqual(identity["version"], "unknown")
            self.assertNotIn(self.temp.name, json.dumps(identity))
            original = identity["sha256"]
            launcher.write_text(f"#!{sys.executable}\n")
            with patch.object(scene, "run_json", return_value={"version": "distribution-revision"}) as metadata:
                _, identity = scene.pixel_producer()
            self.assertEqual(identity["version"], "distribution-revision")
            self.assertEqual(metadata.call_args.args[0][0], sys.executable)
            self.assertNotEqual(original, identity["sha256"])

    def test_bundle_escape_and_failed_validation(self):
        bundle = self.project / "bundle"
        bundle.mkdir()
        files = {key: key for key in scene.PRODUCERS["model-assets"]}
        files["model"] = "model.glb"
        for value in files.values():
            (bundle / value).write_text("{}")
        result = {"schema_version": 1, "status": "ready", "files": files}
        with self.assertRaises(ValueError):
            scene.verify_bundle(bundle, result, "model-assets")
        (bundle / "validation").write_text('{"passed":true}')
        scene.verify_bundle(bundle, result, "model-assets")
        files["model"] = "../scene.json"
        with self.assertRaises(ValueError):
            scene.verify_bundle(bundle, result, "model-assets")

    def test_assembly_bundle_needs_review_sheet_and_passing_checks(self):
        bundle = self.project / "assembly"
        bundle.mkdir()
        files = {key: key for key in scene.PRODUCERS["model-assets"]}
        files["model"] = "model.glb"
        for value in files.values():
            (bundle / value).write_text("{}")
        checks = {"animations_preserved": True, "every_animation_moves": True}
        (bundle / "validation").write_text(json.dumps({"passed": True, "assembly_checks": checks}))
        result = {"schema_version": 2, "status": "ready", "files": files}
        with self.assertRaisesRegex(ValueError, "review sheet"):
            scene.verify_bundle(bundle, result, "model-assets")
        files["review"] = "review.png"
        (bundle / "review.png").write_bytes(b"png")
        scene.verify_bundle(bundle, result, "model-assets")
        (bundle / "validation").write_text(json.dumps({"passed": True, "assembly_checks": dict(checks, every_animation_moves=False)}))
        with self.assertRaises(ValueError):
            scene.verify_bundle(bundle, result, "model-assets")
        with self.assertRaises(ValueError):
            scene.verify_bundle(bundle, dict(result, schema_version=2), "pixel-effect")

    def test_interrupted_build_records_failure(self):
        self.pixel_only()
        with patch.object(scene, "run_json", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                scene.build(self.project, "build/interrupted", 1)
        record = scene.graph.history(self.project)[0]
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["error"]["type"], "KeyboardInterrupt")
        self.assertEqual(record["error"]["code"], "interrupted")
        self.assertTrue((self.project / "build/interrupted/failure.json").is_file())

    def test_failure_history_and_retry(self):
        self.pixel_only()
        with patch.object(scene, "run_json", side_effect=subprocess.TimeoutExpired("secret-host-path", 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                scene.build(self.project, "build/failed", 1)
        history = list((self.project / ".game-studio/runs").glob("*.jsonld"))
        record = scene.graph.history(self.project)[0]
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["steps"][0]["status"], "error")
        self.assertEqual(record["error"]["code"], "timeout")
        self.assertNotIn("secret-host-path", history[0].read_text())
        self.assertFalse((self.project / "build/failed/scene.runtime.json").exists())
        with self.assertRaises(ValueError):
            scene.build(self.project, "build/failed", 1)
        self.assertEqual(scene.graph.history(self.project)[-1]["error"]["code"], "output_exists")

    def test_admission_failure_is_safe_graph_history(self):
        self.data["nodes"][0]["asset"] = "unknown"
        self.save()
        with self.assertRaises(ValueError):
            scene.build(self.project, "build/invalid", 30)
        record = scene.graph.history(self.project)[0]
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["error"]["stage"], "admission")
        self.assertFalse((self.project / "build/invalid").exists())

    def test_source_blend_is_copied_and_rebased(self):
        self.data["assets"] = [a for a in self.data["assets"] if a["id"] == "lantern"]
        self.data["nodes"] = [n for n in self.data["nodes"] if n["asset"] == "lantern"]
        self.save()
        (self.project / "models").mkdir()
        source = self.project / "models/lantern.blend"
        source.write_bytes(b"BLENDER-test-source")
        scene.write_json(self.project / "requests/lantern.json", {
            "schema_version": 1, "name": "Existing lantern", "source_blend": "../models/lantern.blend"})

        def run(command, timeout):
            request = Path(command[command.index("--request") + 1])
            spec = scene.read_json(request)
            copied_source = request.parent / spec["source_blend"]
            self.assertEqual(copied_source.read_bytes(), b"BLENDER-test-source")
            self.assertNotEqual(copied_source, source)
            bundle = Path(command[command.index("--out") + 1])
            bundle.mkdir(parents=True)
            files = {key: key + ".json" for key in scene.PRODUCERS["model-assets"]}
            files["model"] = "compiled.glb"
            for value in files.values():
                (bundle / value).write_text('{}')
            scene.write_json(bundle / files["validation"], {"passed": True})
            return {"schema_version": 1, "status": "ready", "files": files}

        with patch.object(scene, "model_root", return_value=Path(self.temp.name)), patch.object(scene, "run_json", side_effect=run):
            scene.build(self.project, "build/source", 30)
        self.assertEqual(scene.read_json(self.project / "requests/lantern.json")["source_blend"], "../models/lantern.blend")
        source.write_bytes(b"edited-after-build")
        copied = self.project / "build/source/inputs/lantern.source.blend"
        self.assertEqual(copied.read_bytes(), b"BLENDER-test-source")

    @unittest.skipUnless(shutil.which("pixel-asset"), "installed pixel-asset unavailable")
    def test_requests_are_pinned_before_producer(self):
        self.pixel_only()
        original = scene.run_json

        def run(command, timeout):
            if "--request" not in command:
                return original(command, timeout)
            (self.project / "requests/reward.json").write_text('{"changed":true}')
            request = Path(command[command.index("--request") + 1])
            self.assertEqual(scene.read_json(request)["preset"], "pickup")
            return original(command, timeout)

        with patch.object(scene, "run_json", side_effect=run):
            result = scene.build(self.project, "build/pinned", 30)
        runtime = scene.read_json(self.project / result["files"]["scene"])
        request = self.project / runtime["assets"][0]["request"]
        self.assertEqual(scene.read_json(request)["preset"], "pickup")

    @unittest.skipUnless(shutil.which("pixel-asset"), "installed pixel-asset unavailable")
    def test_same_output_has_one_writer(self):
        self.pixel_only()
        barrier = Barrier(2)
        original = scene.load_scene

        def synchronized(project, scene_name):
            value = original(project, scene_name)
            barrier.wait(timeout=5)
            return value

        def build():
            try:
                return scene.build(self.project, "build/concurrent", 30)["status"]
            except (ValueError, FileExistsError):
                return "rejected"

        with patch.object(scene, "load_scene", side_effect=synchronized):
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(lambda _: build(), range(2)))
        self.assertEqual(sorted(statuses), ["ready", "rejected"])
        runtime = scene.read_json(self.project / "build/concurrent/scene.runtime.json")
        self.assertEqual(runtime["status"], "ready")
        self.assertFalse((self.project / "build/concurrent/failure.json").exists())

    def test_stage_is_fresh_and_runnable(self):
        target = Path(self.temp.name) / "staged"
        subprocess.run([sys.executable, str(ROOT / "tools/stage.py"), "--out", str(target)], check=True,
                       capture_output=True)
        result = subprocess.run([sys.executable, str(target / "tools/scene.py"), "validate", "--project",
                                 str(target / "examples/forest-camp")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((target / ".git").exists())
        self.assertFalse((target / "assets/generated").exists())
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run([sys.executable, str(ROOT / "tools/stage.py"), "--out", str(target)],
                           check=True, capture_output=True)

    @unittest.skipUnless(shutil.which("pixel-asset"), "installed pixel-asset unavailable")
    def test_actual_pixel_and_fresh_retry(self):
        self.pixel_only()
        for output in ("build/first", "build/retry"):
            result = scene.build(self.project, output, 30)
            runtime = scene.read_json(self.project / result["files"]["scene"])
            self.assertEqual(runtime["nodes"][0]["position"], [1, 0.45, -2])
            asset = runtime["assets"][0]
            self.assertTrue((self.project / asset["files"]["sheet"]).is_file())
            metadata = scene.read_json(self.project / asset["files"]["metadata"])
            self.assertEqual(len(metadata["frames"]), 10)
        history = scene.graph.history(self.project)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["implementation"]["name"], "game-studio")
        self.assertEqual(history[0]["steps"][0]["implementation"]["name"], "pixel-asset-pipeline")
        with self.assertRaises(ValueError):
            scene.build(self.project, "build/first", 30)


if __name__ == "__main__":
    unittest.main()
