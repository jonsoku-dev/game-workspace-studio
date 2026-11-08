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
