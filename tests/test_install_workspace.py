"""Boundary checks; opt-in real installation uses prepared offline dependencies."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools/install_workspace.py"
spec = importlib.util.spec_from_file_location("install_workspace", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallBoundaries(unittest.TestCase):
    def test_retry_symlinks_never_overwrite_foreign_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "install"
            destination.mkdir()
            (destination / "install-source.json").write_text("{}")
            sentinel = root / "foreign"
            sentinel.write_text("preserve")
            for name in ("env.sh", "install-result.json", ".install.lock", "codex-home", "venv", "plugins"):
                link = destination / name
                link.symlink_to(sentinel)
                with self.subTest(path=name), self.assertRaisesRegex(ValueError, "must not be a symlink"):
                    installer.install(root / "source", destination, root / "wheels", root / "npm")
                self.assertEqual(sentinel.read_text(), "preserve")
                link.unlink()

    def test_atomic_publication_replaces_link_without_following_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "foreign"
            sentinel.write_text("preserve")
            link = root / "env.sh"
            link.symlink_to(sentinel)
            installer.write_atomic(link, "owned")
            self.assertFalse(link.is_symlink())
            self.assertEqual(link.read_text(), "owned")
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_source_destination_overlap_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "outside the source"):
                installer.install(root, root / "install", root / "wheels", root / "npm")
            self.assertEqual(list(root.iterdir()), [])

    def test_missing_offline_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Missing prepared wheelhouse"):
                installer.install(root / "source", root / "install", root / "wheels", root / "npm")
            self.assertFalse((root / "install").exists())

    def test_unrelated_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "install"
            destination.mkdir()
            sentinel = destination / "config.toml"
            sentinel.write_text("preserve")
            with self.assertRaisesRegex(ValueError, "not empty or installer-owned"):
                installer.install(root / "source", destination, root / "wheels", root / "npm")
            self.assertEqual(list(destination.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_missing_host_tool_names_remedy_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("wheels", "npm"):
                (root / name).mkdir()
                (root / name / "input").touch()
            with patch.object(installer.shutil, "which", return_value=None):
                with self.assertRaisesRegex(ValueError, "Missing host executable: codex"):
                    installer.install(root / "source", root / "install", root / "wheels", root / "npm")
            self.assertFalse((root / "install").exists())

    @unittest.skipUnless(os.environ.get("INSTALL_TEST_WHEELHOUSE") and os.environ.get("INSTALL_TEST_NPM_CACHE"),
                         "Set INSTALL_TEST_WHEELHOUSE and INSTALL_TEST_NPM_CACHE for real isolated CLI installation")
    def test_real_offline_install_retry_and_unrelated_home(self):
        with tempfile.TemporaryDirectory(prefix="install-test-") as temporary:
            root = Path(temporary)
            unrelated = root / "unrelated-home"
            unrelated.mkdir()
            sentinel = unrelated / "config.toml"
            sentinel.write_text('# preserve this unrelated home\n')
            destination = root / "environment"
            env = dict(os.environ, CODEX_HOME=str(unrelated))
            workspace = root / "source"
            for name, relative, script in installer.PLUGINS:
                source = SCRIPT.parents[2] / relative
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                stage = [sys.executable, str(source / script)]
                if name == "game-studio":
                    stage.append("--out")
                result = subprocess.run([*stage, str(target)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                (target / script).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / script, target / script)
            command = [sys.executable, str(SCRIPT), "--workspace", str(workspace),
                       "--destination", str(destination), "--wheelhouse", os.environ["INSTALL_TEST_WHEELHOUSE"],
                       "--npm-cache", os.environ["INSTALL_TEST_NPM_CACHE"]]
            real_run = installer.run

            def interrupt_after_first_plugin(command, env, cwd=None):
                if [str(part) for part in command[1:4]] == ["plugin", "marketplace", "add"] and str(command[-1]).endswith("pixel-asset-pipeline"):
                    raise ValueError("simulated interrupted second plugin registration")
                return real_run(command, env, cwd)

            with patch.dict(os.environ, CODEX_HOME=str(unrelated)):
                with patch.object(installer, "run", side_effect=interrupt_after_first_plugin):
                    with self.assertRaisesRegex(ValueError, "simulated interrupted"):
                        installer.install(workspace, destination,
                                          Path(os.environ["INSTALL_TEST_WHEELHOUSE"]),
                                          Path(os.environ["INSTALL_TEST_NPM_CACHE"]))
            self.assertFalse((destination / "install-result.json").exists())
            for _ in range(2):
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "ready")
            self.assertEqual(list(unrelated.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), '# preserve this unrelated home\n')
            cli = subprocess.run([str(destination / "venv/bin/pixel-asset"), "--help"],
                                 capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertIn("action-set", cli.stdout)
            request = root / "pickup.json"
            request.write_text(json.dumps({"schema_version": 1, "preset": "pickup", "size": 32,
                                           "palette": ["#64754b", "#e5ad57", "#fff1d0"], "seed": 17}))
            effect = subprocess.run([str(destination / "venv/bin/pixel-asset"), "effect", "--request",
                                     str(request), "--out", str(root / "effect")],
                                    capture_output=True, text=True)
            self.assertEqual(effect.returncode, 0, effect.stdout + effect.stderr)
            self.assertGreater((root / "effect/sheet.png").stat().st_size, 0)
            self.assertTrue((destination / "install-result.json").is_file())
            pixel_cache = Path(json.loads((destination / "install-result.json").read_text())
                               ["plugins"]["pixel-asset-pipeline"])
            self.assertFalse((pixel_cache / "build").exists())
            self.assertEqual(list(pixel_cache.rglob("*.egg-info")), [])
            marker = (destination / "install-source.json").read_bytes()
            (workspace / "studio/README.md").write_text("changed source\n")
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("different source bytes", result.stderr)
            self.assertEqual((destination / "install-source.json").read_bytes(), marker)


if __name__ == "__main__":
    unittest.main()
