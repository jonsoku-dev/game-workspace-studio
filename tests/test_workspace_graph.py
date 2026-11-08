import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import graph
import workspace_graph


class WorkspaceTest(unittest.TestCase):
    def test_export_merges_distinct_projects_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "game").mkdir()
            config = {"schema_version": 1, "workspace_id": str(uuid.uuid4()), "projects": [".", "game"]}
            manifest = root / "workspace.json"
            manifest.write_text(json.dumps(config))
            for project in (root, root / "game"):
                graph.record_work(project, {"id": "plan", "agent": "studio", "status": "complete", "label": "Plan"})
            exported = workspace_graph.export_workspace(manifest)
            workspace = next(n for n in exported["@graph"] if "Workspace" in n["@type"])
            self.assertEqual(len(set(workspace["includesProject"])), 2)
            config["projects"] = [".."]
            manifest.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                workspace_graph.export_workspace(manifest)

    def test_cross_project_input_is_explicit_and_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / "game"
            game.mkdir()
            (game / "scene.txt").write_bytes(b"scene")
            graph.record_work(game, {"id": "scene", "agent": "studio", "status": "complete",
                "label": "Published scene", "generated": [{"path": "scene.txt",
                    "sha256": hashlib.sha256(b"scene").hexdigest()}]})
            source = graph.query(game, kind="Artifact")[0]["@id"]
            work = graph.record_work(root, {"id": "pack", "agent": "studio", "status": "complete", "label": "Pack"})
            config = {"schema_version": 1, "workspace_id": str(uuid.uuid4()), "projects": [".", "game"],
                      "links": [{"activity": work, "used": source}]}
            manifest = root / "workspace.json"
            manifest.write_text(json.dumps(config))
            nodes = workspace_graph.export_workspace(manifest)["@graph"]
            self.assertEqual(next(n for n in nodes if n["@id"] == work)["used"], [source])
            self.assertNotIn(source, graph.query(root, subject=work)[0]["used"])
            config["links"] = [{"activity": work, "used": work}]
            manifest.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                workspace_graph.export_workspace(manifest)


if __name__ == "__main__":
    unittest.main()
