#!/usr/bin/env python3
"""Install the three workspace plugins into a new, isolated offline environment."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


PYTHON_PACKAGES = ("Pillow==12.0.0", "setuptools==80.9.0", "wheel==0.45.1")
PLUGINS = (
    ("game-studio", "studio", "tools/stage.py"),
    ("pixel-asset-pipeline", "assets", "scripts/package-plugin.py"),
    ("model-assets", "assets/plugins/model-assets", "package.py"),
)


def run(command, env, cwd=None):
    result = subprocess.run([str(part) for part in command], env=env, cwd=cwd,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(f"{shlex.join([str(p) for p in command])} failed:\n"
                         f"{result.stdout}{result.stderr}\n"
                         "Restore the prerequisite/input and rerun the same install command.")
    return result.stdout


def digest_tree(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def write_atomic(path, text):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def install(workspace, destination, wheelhouse, npm_cache):
    if sys.version_info < (3, 10):
        raise ValueError("Use Python 3.10+ with venv and ensurepip support.")
    workspace, destination, wheelhouse, npm_cache = (
        path.expanduser().resolve() for path in (workspace, destination, wheelhouse, npm_cache))
    if destination == workspace or destination.is_relative_to(workspace) or workspace.is_relative_to(destination):
        raise ValueError("Choose a destination outside the source workspace and its parents.")
    if destination.exists() and (not destination.is_dir() or (
            any(path.name != ".install.lock" for path in destination.iterdir())
            and not (destination / "install-source.json").is_file())):
        raise ValueError("Destination is not empty or installer-owned. Choose a new destination.")
    for name in ("codex-home", "venv", "plugins", "install-source.json", ".install.lock", "env.sh", "install-result.json"):
        if (destination / name).is_symlink():
            raise ValueError(f"Installer-owned path must not be a symlink: {destination / name}")
    for path, label in ((wheelhouse, "wheelhouse"), (npm_cache, "npm cache")):
        if not path.is_dir() or not any(path.iterdir()):
            raise ValueError(f"Missing prepared {label}: {path}. See INSTALL.md acquisition commands.")
        if path == destination or path.is_relative_to(destination):
            raise ValueError(f"Keep the prepared {label} outside the destination.")
    executables = {}
    for name in ("codex", "node", "npm", "blender", "webstage"):
        executables[name] = shutil.which(name)
        if not executables[name]:
            raise ValueError(f"Missing host executable: {name}. Provision it on PATH before installing; see INSTALL.md.")
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               PIP_CONFIG_FILE=os.devnull, npm_config_offline="true",
               npm_config_cache=str(npm_cache), npm_config_audit="false",
               npm_config_fund="false", npm_config_update_notifier="false")
    # Prepare and verify inputs before touching the destination or any registrations.
    with tempfile.TemporaryDirectory(prefix="game-install-") as temporary:
        prepared = Path(temporary)
        for name, relative, script in PLUGINS:
            source = workspace / relative
            command = [sys.executable, source / script]
            if name == "game-studio":
                command.append("--out")
            run([*command, prepared / name], env)
        identity = {"schema_version": 1, "workspace": str(workspace),
                    "files": digest_tree(prepared), "python_packages": list(PYTHON_PACKAGES)}
        probe = prepared / "probe"
        run([sys.executable, "-m", "venv", probe], env)
        probe_python = probe / "bin/python"
        run([probe_python, "-m", "pip", "install", "--no-index", "--only-binary=:all:",
             "--find-links", wheelhouse, *PYTHON_PACKAGES], env)
        run([executables["npm"], "ci", "--cache", npm_cache, "--offline",
             "--ignore-scripts", "--no-audit", "--no-fund"], env, prepared / "model-assets/three")
        destination.mkdir(parents=True, exist_ok=True)
        marker = destination / "install-source.json"
        lock_fd = os.open(destination / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if marker.is_symlink():
                raise ValueError(f"Install marker must not be a symlink: {marker}")
            if marker.is_file():
                if json.loads(marker.read_text()) != identity:
                    raise ValueError("Destination belongs to different source bytes. Choose a new destination.")
            elif any(path.name != ".install.lock" for path in destination.iterdir()):
                raise ValueError("Destination is not empty or installer-owned. Choose a new destination.")
            else:
                write_atomic(marker, json.dumps(identity, indent=2) + "\n")
            home = destination / "codex-home"
            home.mkdir(exist_ok=True)
            env["CODEX_HOME"] = str(home)
            venv = destination / "venv"
            run([sys.executable, "-m", "venv", venv], env)
            python = venv / "bin/python"
            run([python, "-m", "pip", "install", "--no-index", "--only-binary=:all:",
                 "--find-links", wheelhouse, *PYTHON_PACKAGES], env)
            stages = destination / "plugins"
            stages.mkdir(exist_ok=True)
            installed = {}
            for name, _, _ in PLUGINS:
                stage = stages / name
                if not stage.exists():
                    with tempfile.TemporaryDirectory(prefix=".stage-", dir=stages) as stage_temp:
                        staged = Path(stage_temp) / name
                        shutil.copytree(prepared / name, staged, ignore=shutil.ignore_patterns("node_modules"))
                        staged.rename(stage)
                for relative, digest in identity["files"].items():
                    if relative.startswith(name + "/"):
                        path = stages / relative
                        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                            raise ValueError(f"Staged source changed: {path}. Choose a new destination.")
                manifest = json.loads((stage / ".codex-plugin/plugin.json").read_text())
                run([executables["codex"], "plugin", "marketplace", "add", stage], env)
                run([executables["codex"], "plugin", "add", f"{name}@{name}"], env)
                listing = json.loads(run([executables["codex"], "plugin", "list", "--marketplace", name, "--json"], env))
                matches = [item for item in listing.get("installed", [])
                           if item.get("name") == name and item.get("installed") is True
                           and item.get("enabled") is True and item.get("version") == manifest["version"]]
                if len(matches) != 1:
                    raise ValueError(f"Codex did not enable the expected local {name} version.")
                installed[name] = home / "plugins/cache" / name / name / manifest["version"]
                if not (installed[name] / ".codex-plugin/plugin.json").is_file():
                    raise ValueError(f"Codex plugin cache missing: {installed[name]}")
            run([python, "-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation",
                 prepared / "pixel-asset-pipeline"], env)
            model = installed["model-assets"]
            run([executables["npm"], "ci", "--cache", npm_cache, "--offline",
                 "--ignore-scripts", "--no-audit", "--no-fund"], env, model / "three")
            env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
            run([venv / "bin/pixel-asset", "--help"], env)
            three = json.loads((model / "three/package.json").read_text())["dependencies"]["three"]
            run([executables["node"], "--input-type=module", "-e",
                 "import fs from 'node:fs'; import * as THREE from 'three'; "
                 "const p=JSON.parse(fs.readFileSync('node_modules/three/package.json')); "
                 f"if(p.version!=={json.dumps(three)} || !THREE.Scene) process.exit(1)"], env, model / "three")
            exports = {"CODEX_HOME": str(home), "PATH": str(venv / "bin"),
                       "STUDIO_ROOT": str(installed["game-studio"]),
                       "MODEL_ASSETS_ROOT": str(model)}
            write_atomic(destination / "env.sh", "\n".join(
                f"export {key}={shlex.quote(value)}" + (':"$PATH"' if key == "PATH" else "")
                for key, value in exports.items()) + "\n")
            result = {"status": "ready", "destination": str(destination), "plugins":
                      {name: str(path) for name, path in installed.items()}, "three": three}
            write_atomic(destination / "install-result.json", json.dumps(result, indent=2) + "\n")
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "destination", "wheelhouse", "npm-cache"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.workspace, args.destination, args.wheelhouse, args.npm_cache)))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Install failed: {exc}\n")


if __name__ == "__main__":
    main()
