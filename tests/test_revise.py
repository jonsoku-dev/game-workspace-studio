import copy
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import graph
import revise
import runtime_inputs
import scene


class ReviseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(ROOT.parent / "examples/scout-actions", self.project,
                        ignore=shutil.ignore_patterns("build", ".game-studio"))
        data = scene.load_scene(self.project)
        self.record = {"run_id": "original", "status": "ready", "steps": [
            {"asset": "scout", "producer": "pixel-action-set", "status": "complete", "request": "request.json"}], "assets": []}
        graph.update_run(self.project, self.record, data)
        self.original = scene.read_json(self.project / "request.json")
        self.edit = {"schema_version": 1, "actions": {"attack": {
            "frames": [{"source": i, "duration_ms": 80} for i in range(6)], "event_frames": {"0": 3}}}}
        self.patch = self.project / "local.json"

    def run_revision(self, out="candidates/b"):
        scene.write_json(self.patch, self.edit)
        return revise.revise(self.project, "original", "scout", self.patch, out)

    def test_retime_preserves_original_and_unchanged_bytes_and_graph(self):
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        result = self.run_revision()
        folder = Path(result["candidate_folder"])
        request = scene.read_json(folder / "inputs/scout/request.json")
        self.assertEqual(request["actions"]["idle"], self.original["actions"]["idle"])
        self.assertEqual([f["duration_ms"] for f in request["actions"]["attack"]["frames"]], [80] * 6)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        for action in self.original["actions"].values():
            for frame in action["frames"]:
                self.assertEqual((folder / "inputs/scout" / frame["path"]).read_bytes(), (self.project / frame["path"]).read_bytes())
        review = scene.read_json(folder / "review.json")
        self.assertEqual(review["actions"]["attack"]["before"]["total_ms"], 800)
        self.assertEqual(review["actions"]["attack"]["after"]["total_ms"], 480)
        self.assertEqual(review["actions"]["attack"]["after"]["contacts"][0]["start_ms"], 240)
        self.assertFalse(review["actions"]["idle"]["changed"])
        self.assertTrue((folder / "attack-contact.png").is_file())
        self.assertTrue((folder / "attack-after-1x.gif").is_file())
        work = graph.query(self.project, subject=result["graph_id"])[0]
        self.assertIn(graph.project_id(self.project) + ":run:original", work["used"])
        self.assertIn("build", result["next_command"])
        with self.assertRaisesRegex(ValueError, "output exists"):
            self.run_revision()

    def test_reorder_remove_and_explicit_event_mapping(self):
        self.edit["actions"]["attack"] = {"frames": [{"source": 3}, {"source": 1}], "event_frames": {"0": 0}}
        result = self.run_revision()
        after = scene.read_json(Path(result["candidate_folder"]) / "inputs/scout/request.json")
        self.assertEqual(after["actions"]["attack"]["frames"], [self.original["actions"]["attack"]["frames"][i] for i in (3, 1)])
        self.assertEqual(after["events"][0]["frame"], 0)
        self.edit["actions"]["attack"]["event_frames"] = {"0": None}
        result = self.run_revision("candidates/c")
        self.assertEqual(scene.read_json(Path(result["candidate_folder"]) / "inputs/scout/request.json")["events"], [])

    def test_missing_event_mapping_and_invalid_values_rejected_without_output(self):
        for change in ({"event_frames": {}}, {"frames": [{"source": True}]},
                       {"frames": [{"source": 0, "duration_ms": 0}]},
                       {"frames": [{"source": 0, "cloud_url": "https://example.com"}]}):
            with self.subTest(change=change):
                saved = copy.deepcopy(self.edit)
                self.edit["actions"]["attack"].update(change)
                with self.assertRaises(ValueError):
                    self.run_revision()
                self.assertFalse((self.project / "candidates/b").exists())
                self.edit = saved

    def test_verified_replacement_and_anchor_clipping(self):
        from PIL import Image
        replacement = self.project / "replacement.png"
        image = Image.new("RGBA", (48, 48))
        image.putpixel((20, 20), (255, 0, 0, 255))
        image.save(replacement)
        entry = self.edit["actions"]["attack"]["frames"][0]
        entry.update(replacement="replacement.png", sha256=revise.digest(replacement.read_bytes()),
                     anchor={"from_px": [20, 20], "to_px": [24, 46]})
        result = self.run_revision()
        folder = Path(result["candidate_folder"])
        request = scene.read_json(folder / "inputs/scout/request.json")
        frame = request["actions"]["attack"]["frames"][0]
        with Image.open(folder / "inputs/scout" / frame["path"]) as shifted:
            self.assertEqual(shifted.getpixel((24, 46)), (255, 0, 0, 255))
        entry["anchor"]["to_px"] = [48, 48]
        with self.assertRaisesRegex(ValueError, "clip"):
            self.run_revision("candidates/c")
        entry["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "sha256"):
            self.run_revision("candidates/c")

    def test_changed_source_rejected_and_original_scene_snapshot_used(self):
        (self.project / "poses/attack-0.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "pinned source"):
            self.run_revision()
        self.assertFalse((self.project / "candidates/b").exists())

    def test_failure_records_error_and_retry_requires_fresh_output(self):
        with patch.object(revise, "evidence", side_effect=ValueError("review failed")):
            with self.assertRaisesRegex(ValueError, "review failed"):
                self.run_revision()
        self.assertTrue(any(n.get("status") == "error" for n in graph.query(self.project, kind="ExternalWork")))
        with self.assertRaisesRegex(ValueError, "output exists"):
            self.run_revision()
        self.assertEqual(self.run_revision("candidates/c")["status"], "prepared")

    def test_no_fx_playtest_marker_maps_or_requires_explicit_selection(self):
        data = scene.read_json(self.project / "scene.json")
        data["playtest"] = {"contact_frame": 3}
        original = copy.deepcopy(self.original)
        original["events"] = []
        scene.write_json(self.project / "request.json", original)
        graph.update_run(self.project, {"run_id": "marker", "status": "ready", "steps": [
            {"asset": "scout", "producer": "pixel-action-set", "status": "ready", "request": "request.json"}], "assets": []}, data)
        self.edit["actions"]["attack"] = {"frames": [{"source": 3}, {"source": 1}]}
        scene.write_json(self.patch, self.edit)
        result = revise.revise(self.project, "marker", "scout", self.patch, "candidates/marker")
        self.assertEqual(scene.read_json(Path(result["scene"]))["playtest"]["contact_frame"], 0)
        self.edit["actions"]["attack"]["frames"] = [{"source": 3}, {"source": 3}]
        scene.write_json(self.patch, self.edit)
        with self.assertRaisesRegex(ValueError, "explicit"):
            revise.revise(self.project, "marker", "scout", self.patch, "candidates/ambiguous")
        self.edit["actions"]["attack"]["contact_frame"] = 1
        scene.write_json(self.patch, self.edit)
        result = revise.revise(self.project, "marker", "scout", self.patch, "candidates/explicit")
        self.assertEqual(scene.read_json(Path(result["scene"]))["playtest"]["contact_frame"], 1)

    def test_build_failure_preserves_source_and_records_retry_guidance(self):
        scene.write_json(self.patch, self.edit)
        with patch.object(scene, "build", side_effect=ValueError("producer failed")):
            with self.assertRaisesRegex(ValueError, "A is preserved"):
                revise.revise(self.project, "original", "scout", self.patch, "candidates/failure", build=True)
        self.assertEqual(graph.history(self.project)[0]["status"], "ready")
        self.assertTrue(any(n.get("status") == "error" for n in graph.query(self.project, kind="ExternalWork")))

    def test_mixed_scene_preserves_model_source_outside_request_folder(self):
        data = scene.load_scene(self.project)
        (self.project / "models").mkdir()
        (self.project / "source.blend").write_bytes(b"pinned blend")
        scene.write_json(self.project / "models/request.json", {"schema_version": 1, "source_blend": "../source.blend"})
        data["assets"].append({"id": "prop", "producer": "model-assets", "request": "models/request.json"})
        record = {"run_id": "mixed", "status": "ready", "steps": [
            {"asset": "scout", "producer": "pixel-action-set", "status": "ready", "request": "request.json"},
            {"asset": "prop", "producer": "model-assets", "status": "ready", "request": "models/request.json"}], "assets": []}
        graph.update_run(self.project, record, data)
        scene.write_json(self.patch, self.edit)
        result = revise.revise(self.project, "mixed", "scout", self.patch, "candidates/mixed")
        folder = Path(result["candidate_folder"]) / "inputs/prop"
        request = scene.read_json(folder / "request.json")
        self.assertEqual((folder / request["source_blend"]).read_bytes(), b"pinned blend")

    def test_concurrent_same_output_has_one_writer(self):
        scene.write_json(self.patch, self.edit)
        def attempt(_):
            try:
                return revise.revise(self.project, "original", "scout", self.patch, "candidates/shared")["status"]
            except (ValueError, FileExistsError):
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, range(2)))
        self.assertEqual(sorted(results), ["conflict", "prepared"])
        works = graph.query(self.project, kind="ExternalWork")
        self.assertEqual(len(works), 1)

    def test_prepared_next_command_builds_in_original_project_with_source_artifact(self):
        result = self.run_revision()
        command = shlex.split(result["next_command"])
        self.assertEqual(command[command.index("--project") + 1], str(self.project.resolve()))
        self.assertIn("--source-artifact", command)
        built = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        built = json.loads(built.stdout)
        self.assertEqual(built["status"], "ready")
        run = graph.query(self.project, subject=graph.project_id(self.project) + ":run:" + built["run_id"])[0]
        self.assertIn(command[command.index("--source-artifact") + 1], run["used"])
        self.assertFalse((Path(result["candidate_folder"]) / ".game-studio").exists())

    def test_cli_and_real_build_smoke(self):
        base = scene.build(self.project, "build/base", 60)
        (self.project / "poses/attack-0.png").write_bytes(b"current source changed")
        (self.project / "scene.json").write_text("{}")
        scene.write_json(self.patch, self.edit)
        command = [sys.executable, str(ROOT / "tools/revise.py"), "--project", str(self.project),
                   "--base", base["run_id"], "--asset", "scout", "--patch", str(self.patch), "--out", "candidates/b"]
        cli = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        result = json.loads(cli.stdout)
        import review
        command += ["--build"]
        command[command.index("--out") + 1] = "candidates/c"
        cli = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        result = json.loads(cli.stdout)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(Path(result["candidate_project"]), self.project.resolve())
        self.assertTrue(result["run"].startswith(graph.project_id(self.project) + ":run:"))
        runtime = scene.read_json(self.project / result["files"]["scene"])
        metadata = scene.read_json(self.project / runtime["assets"][0]["files"]["metadata"])
        comparison = review.compare(self.project, base["run_id"], result["run_id"], "retime-comparison", [
            {"id": "timing", "kind": "technical", "required": True, "description": "Attack frame holds are 80ms"},
            {"id": "motion", "kind": "visual", "required": True, "description": "Review contact and motion"}])
        self.assertTrue(comparison)
        nodes = {n["@id"]: n for n in graph.export_graph(self.project)["@graph"]}
        generated_scene = next(n["@id"] for n in nodes.values()
                               if n.get("wasGeneratedBy") == [result["graph_id"]]
                               and n.get("path") == "candidates/c/scene.json")
        self.assertIn(generated_scene, nodes[result["run"]]["used"])
        revision = next(nodes[x] for x in nodes[result["run"]]["used"] if "SceneRevision" in nodes[x]["@type"])
        self.assertIn(generated_scene, revision["wasDerivedFrom"])
        admitted, media = runtime_inputs.admit([(self.project, result["files"]["scene"])])
        self.assertEqual(admitted[0]["runtime_pin"]["@id"], result["run"] + ":runtime")
        self.assertTrue(media)
        base_run = next(r for r in graph.history(self.project) if r["run_id"] == base["run_id"])
        self.assertEqual(base_run["status"], "ready")
        self.assertEqual(metadata["actions"]["attack"]["duration_ms"], 480)
        self.assertEqual(metadata["events"][0]["start_ms"], 240)


if __name__ == "__main__":
    unittest.main()
