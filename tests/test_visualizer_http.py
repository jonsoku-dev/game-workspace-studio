import base64
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import graph
import visualize


class StateEndpointTests(unittest.TestCase):
    def test_conditional_requests_invalidate_and_reject_foreign_files(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder).resolve()
            server = ThreadingHTTPServer(("127.0.0.1", 0), visualize.handler(project, None, {}))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def get(resource, **headers):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    try:
                        connection.request("GET", resource, headers=headers)
                        res = connection.getresponse()
                        if res.status == 200:
                            policy = res.getheader("Content-Security-Policy")
                            self.assertIn("'wasm-unsafe-eval'", policy)
                            self.assertNotIn("'unsafe-eval'", policy)
                        return res.status, res.getheader("ETag"), res.read()
                    finally:
                        connection.close()
                with patch.object(visualize, "state", wraps=visualize.state) as projection:
                    status, tag, body = get("/api/state")
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)["runs"], [])
                    self.assertEqual(get("/api/state", **{"If-None-Match": tag}), (304, tag, b""))
                    self.assertEqual(projection.call_count, 1)
                    graph.record_work(project, {"id": "planning", "agent": "studio",
                                                "label": "Inspect starting scene", "status": "complete"})
                    status, updated, body = get("/api/state", **{"If-None-Match": tag})
                    self.assertEqual(status, 200)
                    self.assertNotEqual(updated, tag)
                    self.assertEqual(json.loads(body)["activities"][0]["label"], "Inspect starting scene")
                    self.assertEqual(projection.call_count, 2)
                    self.assertEqual(get("/api/state", **{"Host": "external.invalid"})[0], 403)
                    self.assertEqual(get("/artifact?path=../other&sha256=00")[0], 404)
                    self.assertEqual(get("/api/state?project=foreign")[0], 404)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_workspace_switch_accepts_only_registered_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ("first", "second"):
                project = root / name
                project.mkdir()
                graph.record_work(project, {"id": "start", "agent": "studio",
                                           "label": name, "status": "complete"})
            workspace = root / "workspace.json"
            workspace.write_text(json.dumps({"schema_version": 1, "workspace_id": str(uuid.uuid4()),
                                             "projects": ["first", "second"]}))
            server = ThreadingHTTPServer(("127.0.0.1", 0), visualize.handler(root / "first", workspace, {}, True))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def status(query):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    try:
                        connection.request("GET", "/api/state?project=" + query)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()
                code, body = status(graph.project_id(root / "second"))
                self.assertEqual(code, 200)
                data = json.loads(body)
                self.assertEqual(data["project_name"], "second")
                self.assertEqual([a["label"] for a in data["activities"]], ["second"])
                self.assertEqual([a["name"] for a in data["projects"]], ["first", "second"])
                self.assertEqual(status("../elsewhere")[0], 404)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_browse_cards_use_placed_graph_pins_and_reused_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            first, empty, foreign = [root / name for name in ("first", "empty", "foreign")]
            for project in (first, empty, foreign):
                project.mkdir()
                graph.record_work(project, {"id": "start", "label": "Start", "agent": "studio", "status": "complete"})
            # A real PNG and graph-produced run fixture, with an unplaced decoy first.
            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=")
            for project in (first, foreign):
                (project / "request.json").write_text('{}')
                (project / "poster.png").write_bytes(image)
                (project / "decoy.png").write_bytes(image)
                (project / "model.glb").write_bytes(b"glTF fixture")
                (project / "runtime.json").write_text('{"status":"ready"}')
            scene = {"id": "camp", "brief": {"title": "Pinned camp"},
                     "assets": [{"id": name, "producer": "model-assets", "request": "request.json"}
                                for name in ("decoy", "hero")],
                     "nodes": [{"id": "hero-node", "asset": "hero"}]}
            record = {"run_id": "source", "status": "ready", "started_at": "2026-11-01",
                      "runtime": "runtime.json", "steps": [
                          {"asset": name, "producer": "model-assets", "status": "ready"}
                          for name in ("decoy", "hero")], "assets": [
                          {"id": "decoy", "files": {"preview": "decoy.png"}},
                          {"id": "hero", "files": {"model": "model.glb", "preview": "poster.png"}}]}
            graph.update_run(first, record, scene)
            source_run = graph.project_id(first) + ":run:source"
            original = [n["@id"] for n in graph.query(first, kind="Artifact")
                        if n["path"] in {"model.glb", "poster.png"}]
            reuse = {"run_id": "source", "asset": "hero", "run": source_run, "artifacts": original}
            reused_scene = {**scene, "brief": {"title": "Reused camp"}, "assets": [
                {"id": "hero", "producer": "model-assets", "reuse": {"run_id": "source", "asset": "hero"}}]}
            reused = {"run_id": "reuse", "status": "ready", "started_at": "2026-11-02",
                      "runtime": "runtime.json", "steps": [{"asset": "hero", "producer": "model-assets",
                      "status": "reused", "reuse": reuse}], "assets": [
                      {"id": "hero", "files": record["assets"][1]["files"], "reuse": reuse}]}
            graph.update_run(first, reused, reused_scene)
            graph.update_run(first, {"run_id": "later-error", "status": "error", "started_at": "2026-11-03"}, {})
            workspace = root / "workspace.json"
            workspace.write_text(json.dumps({"schema_version": 1, "workspace_id": str(uuid.uuid4()),
                                             "projects": ["first", "empty", "foreign"]}))
            cache = visualize.SnapshotCache(first, workspace, True)
            with patch.object(graph, "export_graph", wraps=graph.export_graph) as exports, \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("metadata must not read images")):
                tag, body, allowed = cache.get()
                self.assertEqual(exports.call_count, 3)
                self.assertEqual(cache.get(), (tag, body, allowed))
                self.assertEqual(exports.call_count, 3)
            cards = json.loads(body)["projects"]
            pin = {"path": "poster.png", "sha256": hashlib.sha256(image).hexdigest()}
            self.assertEqual(cards[0], {"id": graph.project_id(first), "name": "first", "title": "Reused camp",
                                        "kind": "3d", "preview": pin, "run_count": 3})
            self.assertEqual(cards[1], {"id": graph.project_id(empty), "name": "empty", "title": "empty",
                                        "kind": None, "preview": None, "run_count": 0})
            self.assertIsNone(cards[2]["preview"])
            self.assertEqual(visualize.state(first, workspace)["projects"], [])
            (first / "poster.png").write_bytes(b"changed")
            self.assertEqual(cache.get(), (tag, body, allowed))
            with self.assertRaises(RuntimeError):
                visualize.artifact(first, pin["path"], pin["sha256"], allowed)
            with self.assertRaises(FileNotFoundError):
                visualize.artifact(empty, pin["path"], pin["sha256"], visualize.SnapshotCache(empty, workspace).get()[2])
            # A newer 2D run must use the placed actor's sheet when no authored preview exists.
            (first / "actions.json").write_text('{"actions":{}}')
            (first / "atlas.png").write_bytes(image)
            action_scene = {"id": "actor", "brief": {"title": "Actor"}, "assets": [
                {"id": "effect", "producer": "pixel-effect", "request": "request.json"},
                {"id": "actor", "producer": "pixel-action-set", "request": "actions.json"}], "nodes": [
                {"id": "effect-first", "asset": "effect"}, {"id": "actor-node", "asset": "actor"}]}
            action_record = {"run_id": "actions", "status": "ready", "started_at": "2026-11-04",
                             "runtime": "runtime.json", "steps": [
                {"asset": "effect", "producer": "pixel-effect", "status": "ready"},
                {"asset": "actor", "producer": "pixel-action-set", "status": "ready"}], "assets": [
                {"id": "effect", "files": {"sheet": "decoy.png", "preview": "decoy.png"}},
                {"id": "actor", "files": {"atlas": "atlas.png"}}]}
            graph.update_run(first, action_record, action_scene)
            new_tag, body, _ = cache.get()
            self.assertNotEqual(new_tag, tag)
            card = json.loads(body)["projects"][0]
            self.assertEqual((card["title"], card["kind"], card["run_count"]), ("Actor", "2d", 4))
            self.assertEqual(card["preview"], {"path": "atlas.png", "sha256": pin["sha256"]})

    def test_playtest_link_requires_exact_exported_runtime_and_safe_separate_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, exporter = root / "source", root / "exporter"
            source.mkdir()
            exporter.mkdir()
            (source / "runtime.json").write_text('{}')
            scene = {"id": "source-scene", "brief": {"title": "Stored source"}, "assets": [], "nodes": []}
            for ident in ("selected", "unrelated"):
                graph.update_run(source, {"run_id": ident, "status": "ready", "started_at": "2026-11-01",
                                          "runtime": "runtime.json"}, scene)
            runtime = next(n for n in graph.query(source, kind="RuntimeProduct") if ":run:selected:" in n["@id"])
            output = exporter / "release/web/play/index.html"
            output.parent.mkdir(parents=True)
            output.write_text('<html>Stored output</html>')
            export = graph.record_work(exporter, {"id": "export", "agent": "studio-engine-export",
                "label": "Export three", "status": "complete",
                "workspace_inputs": [{k: runtime[k] for k in ("@id", "sha256", "byteCount")}],
                "generated": [{"path": "release/web/play/index.html", "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}]})
            impostor = graph.record_work(exporter, {"id": "impostor", "agent": "other",
                "label": "Export three", "status": "complete",
                "workspace_inputs": [{k: runtime[k] for k in ("@id", "sha256", "byteCount")}],
                "generated": [{"path": "release/web/play/index.html", "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}]})
            workspace = root / "workspace.json"
            config = {"schema_version": 1, "workspace_id": str(uuid.uuid4()), "projects": ["source", "exporter"]}
            def register(activity=export, url="http://127.0.0.1:59765/play/"):
                workspace.write_text(json.dumps({**config, "playtests": [{"activity": activity, "url": url}]}))
            register()
            cache = visualize.SnapshotCache(source, workspace, True)
            tag, body, _ = cache.get(50000)
            runs = {r["run_id"]: r for r in json.loads(body)["runs"]}
            self.assertEqual(runs["selected"]["playable_url"], "http://127.0.0.1:59765/play/")
            self.assertNotIn("playable_url", runs["unrelated"])
            self.assertTrue(all("playable_url" not in r for r in visualize.state(source, None)["runs"]))
            self.assertNotEqual(cache.get(59765)[0], tag)
            self.assertTrue(all("playable_url" not in r for r in json.loads(cache.get(59765)[1])["runs"]))
            for address in ("https://127.0.0.1:59765/play/", "http://example.com:59765/play/",
                            "http://127.0.0.1/play/", "http://user@localhost:59765/play/",
                            "http://localhost:59765/play/?query", "http://localhost:59765/play/#fragment",
                            "http://localhost:59765/other/", "http://localhost:59765/play/../",
                            "http://localhost:59765/%2e%2e/", "http://localhost:0/play/"):
                with self.subTest(address=address):
                    register(url=address)
                    self.assertTrue(all("playable_url" not in r for r in json.loads(cache.get(50000)[1])["runs"]))
            for activity in (impostor, export + "-unknown", runtime["@id"]):
                register(activity=activity)
                self.assertTrue(all("playable_url" not in r for r in json.loads(cache.get(50000)[1])["runs"]))
            # The real HTTP handler must pass its actual port to the cached projection.
            server = ThreadingHTTPServer(("127.0.0.1", 0), visualize.handler(source, workspace, {}, True))
            register(url=f"http://localhost:{server.server_port}/play/")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/api/state?project=" + graph.project_id(source))
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(all("playable_url" not in r for r in json.loads(response.read())["runs"]))
                connection.close()
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_cached_authorization_still_checks_content_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder).resolve()
            pin = hashlib.sha256(b"old").hexdigest()
            (project / "asset.png").write_bytes(b"new")
            with self.assertRaises(RuntimeError):
                visualize.artifact(project, "asset.png", pin, {("asset.png", pin)})
            with self.assertRaises(FileNotFoundError):
                visualize.artifact(project, "asset.png", pin, frozenset())


if __name__ == "__main__":
    unittest.main()
