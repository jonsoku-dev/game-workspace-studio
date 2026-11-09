import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("graph", Path(__file__).resolve().parents[1] / "tools/graph.py")
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "request.json").write_text('{"kind":"effect"}')
        (self.root / "image.png").write_bytes(b"actual image")
        self.scene = {"id": "game", "assets": [{"id": "spark", "producer": "pixel-effect", "request": "request.json"}],
                      "nodes": [{"id": "placed", "asset": "spark", "position": [1, 0, 2]}]}

    def record(self, ident="run1"):
        return {"schema_version": 1, "run_id": ident, "status": "running", "scene": "scene.json",
                "started_at": "2026-11-08T00:00:00Z", "steps": [{"asset": "spark", "producer": "pixel-effect", "status": "pending"}]}

    def finish(self, record):
        graph.update_run(self.root, record, self.scene)
        record["steps"][0].update(status="ready", validation={"passed": True, "checks": ["file-contract"]})
        record["assets"] = [{"id": "spark", "files": {"sheet": "image.png"}}]
        record["status"] = "ready"
        record["runtime"] = "runtime.json"
        (self.root / "runtime.json").write_text('{"ready":true}')
        graph.update_run(self.root, record, self.scene)

    def test_causality_revisions_and_pins(self):
        record = self.record()
        graph.update_run(self.root, record, self.scene)
        (self.root / "request.json").write_text('{"kind":"changed"}')
        self.finish(record)
        document = graph.export_graph(self.root)
        nodes = {n["@id"]: n for n in document["@graph"]}
        artifacts = graph.query(self.root, kind="Artifact")
        artifact = artifacts[0]
        self.assertNotIn("snapshotBase64", artifact)
        placement = graph.query(self.root, kind="ScenePlacement")[0]
        self.assertEqual(placement["placementOf"], [artifact["@id"]])
        self.assertEqual(artifact["sha256"], graph._digest(b"actual image"))
        step = nodes[artifact["wasGeneratedBy"][0]]
        request = nodes[step["used"][0]]
        self.assertEqual(request["sha256"], graph._digest(b'{"kind":"effect"}'))
        validation = graph.query(self.root, kind="Validation")[0]
        self.assertEqual(validation["used"], [artifact["@id"]])
        evidence = graph.query(self.root, kind="ValidationEvidence")[0]
        self.assertEqual(evidence["wasGeneratedBy"], [validation["@id"]])
        self.assertEqual(len(graph.query(self.root, kind="RunRevision")), 3)
        self.assertEqual(graph.history(self.root)[0]["status"], "ready")
        self.assertFalse(any(k.startswith("_graph_") for k in graph.history(self.root)[0]))

    def test_repeated_scene_and_parallel_writers(self):
        def write(ident):
            record = self.record(ident)
            self.finish(record)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(write, ["first", "second"]))
        self.assertEqual(len(graph.history(self.root)), 2)
        self.assertEqual(len(graph.query(self.root, kind="ScenePlacement")), 2)
        self.assertEqual(len(list((self.root / ".game-studio/runs").glob("*.jsonld"))), 2)

    def test_dangling_and_foreign_subject_rejected(self):
        self.finish(self.record())
        document = graph.export_graph(self.root)
        document["@graph"][0]["used"] = ["urn:game-studio:missing"]
        with self.assertRaises(ValueError):
            graph.validate_graph(document)
        path = self.root / ".game-studio/runs/foreign.jsonld"
        path.write_text(json.dumps({"@context": graph.CONTEXT, "schema_version": 1,
                                    "@graph": [{"@id": "urn:game-studio:foreign", "@type": ["Entity"]}]}))
        with self.assertRaises(ValueError):
            graph.export_graph(self.root)

    def test_failure_and_invalid_admission(self):
        record = self.record()
        record.update(status="error", steps=[], error={"code": "admission_failed"})
        graph.update_run(self.root, record, {})
        self.assertEqual(len(graph.query(self.root, kind="Error")), 1)
        self.assertFalse(graph.query(self.root, kind="RuntimeProduct"))
        self.assertFalse(graph.query(self.root, kind="WorkStep"))

    def test_external_observations_and_path_conflicts(self):
        self.finish(self.record())
        run = graph.query(self.root, kind="Run")[0]["@id"]
        record = {"id": "inspect", "label": "Inspect output", "agent": "tester", "status": "complete",
                  "observed": [run], "files": ["image.png"],
                  "verification": {"passed": True, "checks": ["manually inspected"]}}
        ident = graph.record_work(self.root, record)
        work = graph.query(self.root, subject=ident)[0]
        self.assertIn(run, work["observed"])
        self.assertIn("recordedAt", work)
        self.assertNotIn("started_at", work)
        artifact = graph.query(self.root, subject=work["observed"][-1])[0]
        self.assertNotIn("wasGeneratedBy", artifact)
        with self.assertRaises(ValueError):
            graph.record_work(self.root, record)
        for field, value in [("used", ["urn:game-studio:unknown"]), ("files", ["../outside"])]:
            invalid = dict(record, id="bad", **{field: value})
            with self.assertRaises(ValueError):
                graph.record_work(self.root, invalid)
        invalid = dict(record, id="bad", **{"@id": run})
        with self.assertRaises(ValueError):
            graph.record_work(self.root, invalid)

    def test_recorded_paths_are_canonical_project_relative(self):
        (self.root / "sub").mkdir()
        (self.root / "sub/y.json").write_text("{}")
        digest = __import__("hashlib").sha256(b"{}").hexdigest()
        plain = graph.record_work(self.root, {"id": "plain", "label": "Plain", "agent": "t", "status": "complete",
                                               "files": ["image.png"], "generated": [{"path": "sub/y.json", "sha256": digest}]})
        dotted = graph.record_work(self.root, {"id": "dotted", "label": "Dotted", "agent": "t", "status": "complete",
                                                "files": ["./image.png"], "generated": [{"path": "sub//y.json", "sha256": digest}]})
        for ident in (plain, dotted):
            artifacts = [n for n in graph.query(self.root, kind="Artifact") if n["@id"].startswith(ident + ":")]
            self.assertEqual(sorted(a["path"] for a in artifacts), ["image.png", "sub/y.json"])
        suffix = lambda ident: sorted(n["@id"].rsplit(":", 1)[1] for n in graph.query(self.root, kind="Artifact")
                                      if n["@id"].startswith(ident + ":"))
        self.assertEqual(suffix(plain), suffix(dotted))
        with self.assertRaises(ValueError):
            graph.record_work(self.root, {"id": "dup", "label": "Dup", "agent": "t", "status": "complete",
                                          "files": ["image.png", "./image.png"]})

    def test_workspace_input_pins_are_verified_when_workspace_given(self):
        source, exporter = self.root / "source", self.root / "exporter"
        for folder in (source, exporter):
            folder.mkdir()
        (source / "runtime.json").write_text("{}")
        graph.update_run(source, {"run_id": "r", "status": "ready", "started_at": "2026-11-01",
                                  "runtime": "runtime.json"}, {"id": "s", "brief": {"title": "S"}, "assets": [], "nodes": []})
        runtime = graph.query(source, kind="RuntimeProduct")[0]
        pin = {k: runtime[k] for k in ("@id", "sha256", "byteCount")}
        graph.record_work(exporter, {"id": "seed", "label": "Seed", "agent": "t", "status": "complete"})
        manifest = self.root / "workspace.json"
        manifest.write_text(json.dumps({"schema_version": 1, "workspace_id": "fa361f61-ab51-4ee7-8539-49daee605c9d",
                                        "projects": ["source", "exporter"]}))
        base = {"label": "Export", "agent": "t", "status": "complete"}
        for bad in (dict(pin, sha256="0" * 64), dict(pin, **{"@id": pin["@id"] + "-missing"})):
            with self.assertRaisesRegex(ValueError, "registered entity"):
                graph.record_work(exporter, dict(base, id="bad", workspace_inputs=[bad]), manifest)
        own = graph.project_id(exporter) + ":work:not-yet-recorded"
        with self.assertRaisesRegex(ValueError, "other projects"):
            graph.record_work(exporter, dict(base, id="own", workspace_inputs=[dict(pin, **{"@id": own})]))
        graph.record_work(exporter, dict(base, id="good", workspace_inputs=[pin]), manifest)
        self.assertEqual(graph.main(["record", "--project", str(exporter), "--record", str(self._write(
            dict(base, id="cli", workspace_inputs=[pin])))]), 2)

    def _write(self, record):
        path = self.root / "record-cli.json"
        path.write_text(json.dumps(record))
        return path

    def test_same_content_different_request_paths_and_portable_copy(self):
        self.finish(self.record())
        shutil.copyfile(self.root / "request.json", self.root / "another.json")
        changed = copy.deepcopy(self.scene)
        changed["assets"][0]["request"] = "another.json"
        graph.update_run(self.root, self.record("other"), changed)
        self.assertEqual(len(graph.query(self.root, kind="RequestRevision")), 2)
        destination = self.root / "copy"
        shutil.copytree(self.root / ".game-studio", destination / ".game-studio")
        self.assertEqual(graph.export_graph(self.root), graph.export_graph(destination))
        self.assertEqual(graph.CONTEXT["snapshot"]["@type"], "@json")
        self.assertIsInstance(graph.CONTEXT, dict)
        self.assertTrue(all(not Path(n.get("path", ".")).is_absolute()
                            for n in graph.export_graph(destination)["@graph"]))

    def test_source_revision_changes_without_request_change(self):
        (self.root / "request.json").write_text('{"source_blend":"source.blend"}')
        (self.root / "source.blend").write_bytes(b"first")
        graph.update_run(self.root, self.record("first"), self.scene)
        (self.root / "source.blend").write_bytes(b"second")
        graph.update_run(self.root, self.record("second"), self.scene)
        self.assertEqual(len(graph.query(self.root, kind="RequestRevision")), 2)
        self.assertEqual(len(graph.query(self.root, kind="SourceArtifact")), 2)
        self.assertEqual(len(graph.history(self.root)), 2)

    def test_source_escape_error_is_admitted_without_producer_claim(self):
        (self.root / "request.json").write_text('{"source_blend":"../escape.blend"}')
        record = self.record()
        with self.assertRaises(ValueError):
            graph.update_run(self.root, record, self.scene)
        record.update(status="error", error={"code": "invalid_input"})
        graph.update_run(self.root, record, self.scene)
        self.assertEqual(graph.history(self.root)[0]["status"], "error")
        self.assertFalse(graph.query(self.root, kind="WorkStep"))

    def test_model_report_backed_derivation(self):
        files = {"source": "source.blend", "raw": "raw.glb", "metadata": "metadata.json",
                 "model": "model.glb", "receipt": "receipt.json", "validation": "validation.json"}
        for path in files.values():
            (self.root / path).write_bytes(b"model")
        (self.root / "metadata.json").write_text(json.dumps({"blender_version": "5.2",
                                  "flags": {"roundtrip_verified": True}}))
        (self.root / "receipt.json").write_text(json.dumps({"contract": {"id": "webstage-asset", "version": "1.0"},
            "ok": True, "kind": "gltf", "violations": [], "input": {"path": "raw.glb"},
            "output": {"path": "model.glb", "bytes": 5}}))
        (self.root / "validation.json").write_text('{"passed":true,"three_version":"0.180.0"}')
        record = self.record()
        record["steps"][0].update(status="ready", producer="model-assets")
        record["assets"] = [{"id": "spark", "files": files}]
        model_scene = copy.deepcopy(self.scene)
        model_scene["assets"][0]["producer"] = "model-assets"
        record["runtime"] = "runtime.json"
        (self.root / "runtime.json").write_text('{"ready":true}')
        graph.update_run(self.root, record, model_scene)
        nodes = {n["@id"]: n for n in graph.export_graph(self.root)["@graph"]}
        model = next(n for n in nodes.values() if n.get("role") == "model")
        raw = nodes[model["wasDerivedFrom"][0]]
        self.assertEqual(raw["role"], "raw")
        compiler = nodes[model["wasGeneratedBy"][0]]
        self.assertEqual(compiler["used"], [raw["@id"]])
        self.assertEqual(compiler["evidenceBasis"], "producer-report")
        check = next(n for n in nodes.values() if n.get("label") == "Three.js model inspection")
        self.assertIn(model["@id"], check["used"])
        placement = graph.query(self.root, kind="ScenePlacement")[0]
        self.assertEqual(placement["placementOf"], [model["@id"]])

    def test_implementation_fingerprint_scopes_agents(self):
        for ident, fingerprint in (("first", "aaa"), ("second", "bbb"), ("same", "aaa")):
            record = self.record(ident)
            record["implementation"] = {"name": "studio", "sha256": "runner"}
            record["steps"][0].update(status="running", implementation={"name": "pixel-effect", "version": "1", "sha256": fingerprint})
            graph.update_run(self.root, record, self.scene)
        plugins = graph.query(self.root, kind="Plugin")
        pixel = [p for p in plugins if p["label"] == "pixel-effect"]
        self.assertEqual(len(pixel), 2)
        self.assertEqual({p["implementation"]["sha256"] for p in pixel}, {"aaa", "bbb"})
        runs = graph.query(self.root, kind="Run")
        self.assertEqual(len({r["wasAssociatedWith"][0] for r in runs}), 1)
        legacy = self.record("legacy")
        legacy["steps"][0]["status"] = "running"
        graph.update_run(self.root, legacy, self.scene)
        self.assertEqual(len([p for p in graph.query(self.root, kind="Plugin") if p["label"] == "pixel-effect"]), 3)
        self.assertEqual(graph.CONTEXT["implementation"]["@type"], "@json")

    def test_mesh_effect_attachment_preserves_recipe_and_old_pixel_history(self):
        self.finish(self.record("pixel"))
        pixel_path = self.root / ".game-studio/runs/pixel.jsonld"
        legacy = json.loads(pixel_path.read_text())
        legacy["@context"] = graph.LEGACY_CONTEXT
        pixel_path.write_text(json.dumps(legacy))
        legacy_bytes = pixel_path.read_bytes()
        (self.root / "mesh.glb").write_bytes(b"mesh")
        recipe = {"schema_version": 1, "kind": "mesh-particles", "units": "meters",
                  "duration_s": 3.2, "particles": [{"offset": [0, 0, 0], "drift": [0, 1, 0],
                  "spin": [0, 1, 0], "start_s": 0, "life_s": 1.2, "scale": 1}]}
        (self.root / "effect.json").write_text(json.dumps(recipe))
        scene = copy.deepcopy(self.scene)
        scene["assets"][0]["producer"] = "model-assets"
        scene["nodes"].append({"id": "embers", "asset": "spark", "parent": "placed", "position": [0, 0.5, 0]})
        record = self.record("mesh")
        record["steps"][0].update(producer="model-assets", status="ready")
        record["assets"] = [{"id": "spark", "files": {"model": "mesh.glb", "effect": "effect.json"}}]
        record["runtime"] = "runtime.json"
        graph.update_run(self.root, record, scene)
        (self.root / "effect.json").write_text('{"changed":true}')
        graph.update_run(self.root, record, scene)
        document = graph.export_graph(self.root)
        nodes = {node["@id"]: node for node in document["@graph"]}
        emitter = next(node for node in nodes.values() if node["@id"].endswith(":placement:embers"))
        parent = nodes[emitter["attachedTo"][0]]
        self.assertEqual(parent["snapshot"]["id"], "placed")
        self.assertNotIn("dependsOn", emitter)
        self.assertEqual({nodes[ident]["role"] for ident in emitter["placementOf"]}, {"model", "effect"})
        effect = graph.query(self.root, kind="MotionRecipe")[0]
        self.assertEqual(effect["snapshot"], recipe)
        self.assertEqual(effect["sha256"], graph._digest(json.dumps(recipe).encode()))
        self.assertEqual(len(graph.history(self.root)), 2)
        self.assertEqual(pixel_path.read_bytes(), legacy_bytes)
        self.assertEqual(document["@context"], graph.CONTEXT)
        pixel = next(n for n in nodes.values() if n["@id"].endswith(":run:pixel:placement:placed"))
        self.assertEqual({nodes[i]["role"] for i in pixel["placementOf"]}, {"sheet"})
        self.assertNotIn("attachedTo", pixel)

    def test_context_redefinition_and_dangling_attachment_rejected(self):
        self.finish(self.record())
        document = graph.export_graph(self.root)
        document["@context"] = copy.deepcopy(graph.LEGACY_CONTEXT)
        document["@context"]["used"] = "https://untrusted.invalid/used"
        with self.assertRaises(ValueError):
            graph.validate_graph(document)
        document["@context"] = graph.CONTEXT
        document["@graph"][0]["attachedTo"] = ["urn:game-studio:absent"]
        with self.assertRaises(ValueError):
            graph.validate_graph(document)

    def test_action_import_pins_generated_outputs_and_runtime_edges(self):
        self.finish(self.record("old-pixel"))
        old_shard = self.root / ".game-studio/runs/old-pixel.jsonld"
        old_bytes = old_shard.read_bytes()
        source = self.root / "imported"
        (source / "poses").mkdir(parents=True)
        for name, content in {"poses/idle.png": b"pose", "fx.png": b"fx",
                              "fx.json": b'{"pixelfx":{"pivot":[8,8]}}',
                              "LICENSE": b"license", "NOTICE": b"attribution"}.items():
            (source / name).write_bytes(content)
        (source / "unrelated.png").write_bytes(b"never declared")
        request = {"schema_version": 1, "cell_size": [16, 16], "pivot_px_from_top_left": [8, 15],
                   "actions": {"idle": {"loop": True, "frames": [{"path": "poses/idle.png", "duration_ms": 100}]}},
                   "events": [{"action": "attack", "frame": 0, "sheet": "fx.png", "metadata": "fx.json",
                               "license": "LICENSE", "notice": "NOTICE"}]}
        (source / "request.json").write_text(json.dumps(request))
        action_scene = copy.deepcopy(self.scene)
        action_scene["assets"][0].update(producer="pixel-action-set", request="imported/request.json")
        record = self.record("action")
        record["steps"][0].update(producer="pixel-action-set", status="running")
        graph.update_run(self.root, record, action_scene)
        pins = record["_graph_inputs"]["requests"]["spark"]["sources"]
        self.assertEqual({p["path"] for p in pins}, {"imported/poses/idle.png", "imported/fx.png",
                         "imported/fx.json", "imported/LICENSE", "imported/NOTICE"})
        self.assertTrue(all(set(p) == {"path", "sha256", "byteCount"} for p in pins))
        # A changed source after admission cannot change this run's pins.
        (source / "poses/idle.png").write_bytes(b"changed pose")
        output = self.root / "output"
        output.mkdir()
        files = {"atlas": "output/atlas.png", "metadata": "output/actions.json",
                 "effect_0_sheet": "output/fx.png", "effect_0_metadata": "output/fx.json",
                 "effect_0_license": "output/LICENSE", "effect_0_notice": "output/NOTICE"}
        for role, path in files.items():
            original = {"effect_0_sheet": "fx.png", "effect_0_metadata": "fx.json",
                        "effect_0_license": "LICENSE", "effect_0_notice": "NOTICE"}.get(role)
            (self.root / path).write_bytes((source / original).read_bytes() if original else b"generated")
        record["assets"] = [{"id": "spark", "files": files}]
        record["steps"][0]["status"] = "ready"
        record["runtime"] = "runtime.json"
        graph.update_run(self.root, record, action_scene)
        document = graph.export_graph(self.root)
        nodes = {n["@id"]: n for n in document["@graph"]}
        imported = graph.query(self.root, kind="Imported2DInput")
        self.assertEqual(len(imported), 5)
        self.assertTrue(all("wasGeneratedBy" not in node for node in imported))
        self.assertTrue(all("snapshotBase64" not in node and "snapshot" not in node for node in imported))
        pose = next(node for node in imported if node["path"].endswith("idle.png"))
        self.assertEqual(pose["sha256"], graph._digest(b"pose"))
        atlas = graph.query(self.root, kind="ActionAtlas")[0]
        step = nodes[atlas["wasGeneratedBy"][0]]
        self.assertTrue({n["@id"] for n in imported} <= set(step["used"]))
        placement = next(n for n in nodes.values() if n["@id"].endswith(":run:action:placement:placed"))
        self.assertEqual({nodes[i]["role"] for i in placement["placementOf"]},
                         {"atlas", "metadata", "effect_0_sheet", "effect_0_metadata"})
        self.assertFalse(set(placement["placementOf"]) & {n["@id"] for n in imported})
        fx = next(n for n in graph.query(self.root, kind="CopiedEffectInput") if n["role"] == "effect_0_sheet")
        self.assertTrue(any(nodes[i].get("path") == "imported/fx.png" for i in fx["wasDerivedFrom"]))
        self.assertEqual(old_shard.read_bytes(), old_bytes)
        later = self.record("changed-action")
        later["steps"][0].update(producer="pixel-action-set", status="running")
        graph.update_run(self.root, later, action_scene)
        self.assertEqual(len(graph.query(self.root, kind="RequestRevision")), 3)
        self.assertEqual(len(graph.history(self.root)), 3)
        self.assertEqual(document["@context"], graph.CONTEXT)

    def test_action_input_containment(self):
        request_root = self.root / "requests"
        request_root.mkdir()
        (self.root / "outside.png").write_bytes(b"outside request root")
        for declared in ("../outside.png", "/etc/passwd", "linked.png"):
            (request_root / "linked.png").unlink(missing_ok=True)
            (request_root / "linked.png").symlink_to(self.root / "outside.png")
            request = {"actions": {"idle": {"frames": [{"path": declared}]}}}
            (request_root / "request.json").write_text(json.dumps(request))
            with self.assertRaises(ValueError):
                graph._request(self.root, "requests/request.json", "pixel-action-set")

    def test_read_only_missing_project(self):
        self.assertEqual(graph.history(self.root), [])
        self.assertFalse((self.root / ".game-studio").exists())

    def test_external_generated_revisions_are_explicit_and_hash_verified(self):
        original = {"id": "make-v1", "label": "Independent deliverable", "agent": "author", "status": "complete",
                    "files": ["request.json"], "generated": [{"path": "image.png", "sha256": graph._digest(b"actual image")} ]}
        work_id = graph.record_work(self.root, original)
        artifact = next(n for n in graph.query(self.root, kind="Artifact") if n.get("wasGeneratedBy") == [work_id])
        self.assertEqual(artifact["wasDerivedFrom"], [])
        self.assertEqual(original.get("observed"), None)
        prior_bytes = (self.root / ".game-studio/runs/work-make-v1.jsonld").read_bytes()
        (self.root / "image.png").write_bytes(b"revision two")
        revised = {"id": "make-v2", "label": "Revision", "agent": "author", "status": "complete",
                   "used": [artifact["@id"]], "observed": [work_id],
                   "generated": [{"path": "image.png", "sha256": graph._digest(b"revision two"),
                                  "wasDerivedFrom": [artifact["@id"]]}]}
        revision_id = graph.record_work(self.root, revised)
        revision = next(n for n in graph.query(self.root, kind="Artifact") if n.get("wasGeneratedBy") == [revision_id])
        self.assertNotEqual(artifact["@id"], revision["@id"])
        self.assertEqual(revision["wasDerivedFrom"], [artifact["@id"]])
        self.assertEqual(graph.query(self.root, subject=revision_id)[0]["used"], [artifact["@id"]])
        self.assertEqual((self.root / ".game-studio/runs/work-make-v1.jsonld").read_bytes(), prior_bytes)
        self.assertEqual(artifact["sha256"], graph._digest(b"actual image"))
        for change in ({"generated": [{"path": "image.png", "sha256": "wrong"}]},
                       {"used": []}, {"used": [work_id]},
                       {"files": ["./image.png"]},
                       {"generated": revised["generated"] * 2},
                       {"generated": [{"path": "../outside", "sha256": "wrong"}]},
                       {"generated": [{"path": "image.png", "sha256": graph._digest(b"revision two"), "unknown": True}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                graph.record_work(self.root, dict(revised, id="rejected", **change))
        (self.root / "link").symlink_to(self.root.parent)
        with self.assertRaises(ValueError):
            graph.record_work(self.root, dict(revised, id="escape", generated=[{"path": "link/outside", "sha256": "wrong"}]))
        self.assertFalse((self.root / ".game-studio/runs/work-rejected.jsonld").exists())

    def reuse_record(self, source="run1", selected=None, ident="reuse"):
        source_run = next(n for n in graph.query(self.root, kind="Run") if n["record"]["run_id"] == source)
        source_asset = source_run["record"]["assets"][0]
        artifacts = source_asset.get("reuse", {}).get("artifacts") or [
            n["@id"] for n in graph.query(self.root, kind="Artifact") if n["@id"].startswith(source_run["@id"] + ":artifact:")]
        reuse = {"run_id": source, "asset": "spark", "run": source_run["@id"], "artifacts": artifacts}
        scene = copy.deepcopy(self.scene)
        scene["assets"][0].pop("request")
        scene["assets"][0]["reuse"] = {"run_id": selected or source, "asset": "spark"}
        record = self.record(ident)
        record.update(status="ready", runtime="runtime.json", assets=[{"id": "spark", "files": source_asset["files"], "reuse": reuse}])
        record["steps"][0].update(status="reused", reuse=reuse, validation={"passed": True, "checks": ["hash match"]})
        return record, scene

    def test_reuse_points_to_original_artifacts_without_regeneration(self):
        self.finish(self.record())
        old_path = self.root / ".game-studio/runs/run1.jsonld"
        old_bytes = old_path.read_bytes()
        original = graph.query(self.root, kind="Artifact")[0]
        record, scene = self.reuse_record()
        (self.root / "request.json").unlink()
        graph.update_run(self.root, record, scene)
        self.assertEqual(record["_graph_inputs"]["requests"], {})
        self.assertEqual(len(graph.query(self.root, kind="Artifact")), 1)
        placement = next(n for n in graph.query(self.root, kind="ScenePlacement") if ":run:reuse:" in n["@id"])
        self.assertEqual(placement["placementOf"], [original["@id"]])
        runtime = next(n for n in graph.query(self.root, kind="RuntimeProduct") if ":run:reuse:" in n["@id"])
        self.assertIn(original["@id"], runtime["wasDerivedFrom"])
        step = next(n for n in graph.query(self.root, kind="WorkStep") if ":run:reuse:" in n["@id"])
        self.assertEqual(step["status"], "reused")
        self.assertIn(original["@id"], step["used"])
        self.assertEqual(old_path.read_bytes(), old_bytes)
        chained, scene = self.reuse_record(source="reuse", selected=graph.project_id(self.root) + ":run:reuse", ident="chained")
        graph.update_run(self.root, chained, scene)
        self.assertEqual(len(graph.query(self.root, kind="Artifact")), 1)
        graph.validate_graph(graph.export_graph(self.root))
        (self.root / "image.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            graph.update_run(self.root, record, scene)

    def test_reuse_rejects_forged_source_ids_and_files(self):
        self.finish(self.record())
        for mutation in ("artifacts", "files", "status", "run", "source"):
            record, scene = self.reuse_record()
            if mutation == "artifacts":
                record["steps"][0]["reuse"]["artifacts"] = [graph.project_id(self.root)]
            elif mutation == "files":
                record["assets"][0]["files"] = {"sheet": "request.json"}
            elif mutation == "status":
                record["steps"][0]["status"] = "ready"
            elif mutation == "run":
                record["steps"][0]["reuse"]["run"] = graph.project_id(self.root) + ":run:absent"
            else:
                scene["assets"][0]["reuse"]["run_id"] = "absent"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                graph.update_run(self.root, record, scene)

    def test_duplicate_edges_and_causal_cycles_rejected(self):
        self.finish(self.record())
        document = graph.export_graph(self.root)
        artifact = next(n for n in document["@graph"] if "Artifact" in n["@type"])
        artifact["wasDerivedFrom"] = [artifact["@id"]]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            graph.validate_graph(document)
        artifact["wasDerivedFrom"] = artifact["wasGeneratedBy"] * 2
        with self.assertRaises(ValueError):
            graph.validate_graph(document)

    def test_deep_chains_and_back_edges(self):
        for relation in ("dependsOn", "attachedTo"):
            with self.subTest(relation=relation):
                nodes = [graph._node(f"urn:game-studio:deep:{index}", "WorkStep") for index in range(2001)]
                for current, following in zip(nodes, nodes[1:]):
                    current[relation] = [following["@id"]]
                document = {"@context": graph.CONTEXT, "schema_version": 1, "@graph": nodes}
                self.assertIs(graph.validate_graph(document), document)
                nodes[-1][relation] = [nodes[0]["@id"]]
                with self.assertRaisesRegex(ValueError, "cyclic"):
                    graph.validate_graph(document)

        nodes = [graph._node("urn:game-studio:separate:a", "Entity", used=["urn:game-studio:separate:b"]),
                 graph._node("urn:game-studio:separate:b", "Entity", attachedTo=["urn:game-studio:separate:a"])]
        graph.validate_graph({"@context": graph.CONTEXT, "schema_version": 1, "@graph": nodes})


if __name__ == "__main__":
    unittest.main()
