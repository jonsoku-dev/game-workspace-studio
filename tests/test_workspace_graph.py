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


if __name__ == "__main__":
    unittest.main()
