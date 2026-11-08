#!/usr/bin/env python3
"""Validate a game scene and integrate installed local asset producers."""
import argparse
import base64
import hashlib
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import uuid

import graph
from runtime_inputs import feedback_effects


PRODUCERS = {
    "pixel-effect": ("sheet", "metadata", "preview", "effect"),
    "pixel-action-set": ("atlas", "metadata", "preview", "credits"),
    "model-assets": ("model", "metadata", "validation", "source", "raw", "preview", "receipt"),
}


class SceneError(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def resolve_reuse(project, asset):
    selection = asset.get("reuse")
    if (not isinstance(selection, dict) or set(selection) != {"run_id", "asset"}
            or any(not isinstance(selection.get(key), str) or not selection[key] for key in selection)):
        raise SceneError("invalid_reuse", "Select an exact source run_id and asset for reuse.")
    runs = [run for run in graph.history(project) if run["run_id"] == selection["run_id"]
            or run["graph_id"] == selection["run_id"]]
    if len(runs) != 1 or runs[0].get("status") != "ready":
        raise SceneError("reuse_not_ready", "Select an existing ready run in this project.")
    source = runs[0]
    assets = [item for item in source.get("assets", []) if item["id"] == selection["asset"]]
    if len(assets) != 1 or assets[0].get("producer") != asset["producer"]:
        raise SceneError("reuse_mismatch", "Select an asset with the same producer in the source run.")
    original = assets[0]
    artifacts = graph.query(project, kind="Artifact")
    allowed = original.get("reuse", {}).get("artifacts")
    pins = [node for node in artifacts if (node["@id"] in allowed if allowed is not None
            else node["@id"].startswith(source["graph_id"] + ":artifact:"))]
    references = []
    for role, name in original.get("files", {}).items():
        matches = [node for node in pins if node.get("path") == name and node.get("role") == role]
        if len(matches) != 1:
            raise SceneError("reuse_mismatch", "Source files require exact recorded artifact references.")
        pin = matches[0]
        path = local_path(project, name)
        if not path.is_file():
            raise SceneError("missing_input", "Restore the pinned source artifact before retrying.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pin.get("sha256") or path.stat().st_size != pin.get("byteCount"):
            raise SceneError("reuse_mismatch", "Source artifact bytes changed; select a verified revision.")
        references.append(pin["@id"])
    verify_bundle(project, {"schema_version": 1, "status": "ready", "files": original.get("files")}, asset["producer"])
    return {"id": asset["id"], "producer": asset["producer"], "files": dict(original["files"]),
            "reuse": {"run_id": source["run_id"], "asset": original["id"],
                      "run": source["graph_id"], "artifacts": references}}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".json-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def local_path(root, value):
    root = root.resolve()
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise SceneError("confinement", "Use a nonempty project-relative path.")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise SceneError("confinement", "Keep inputs and outputs inside their project boundary.")
    return path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ValueError(f"invalid identifier: {value}")
    return value


def vector(value, positive=False):
    if not isinstance(value, list) or len(value) != 3 or any(
        type(v) not in (int, float) or not math.isfinite(v) or (positive and v <= 0) for v in value
    ):
        raise ValueError("transform needs three finite numbers; scale must be positive")


def action_inputs(request, specification):
    actions = specification.get("actions")
    events = specification.get("events", [])
    if not isinstance(actions, dict) or not actions or not isinstance(events, list):
        raise ValueError("action-set requires actions and an optional events list")
    paths = []
    for action in actions.values():
        if not isinstance(action, dict) or not isinstance(action.get("frames"), list):
            raise ValueError("action-set actions require frames")
        for frame in action["frames"]:
            if not isinstance(frame, dict):
                raise ValueError("action-set frame must be an object")
            paths.append(frame.get("path"))
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("action-set event must be an object")
        paths.extend(event.get(key) for key in ("sheet", "metadata", "license", "notice"))
    declared = {}
    for path in paths:
        source = local_path(request.parent, path)
        if not source.is_file():
            raise SceneError("missing_input", "Restore the declared action-set input inside the request folder.")
        declared[path] = source
    return declared


def copy_pinned(source, target, pin):
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            outgoing.write(chunk)
    if digest.hexdigest() != pin["sha256"] or size != pin["byteCount"]:
        raise ValueError("declared input changed after admission; retry with a fresh output")


def stage_action_inputs(project, source_request, request, specification, pins):
    pinned = {item["path"]: item for item in pins}
    copied = {}
    for declared, source in action_inputs(source_request, specification).items():
        source_name = str(source.relative_to(project))
        if source_name not in pinned:
            raise ValueError("action-set input was not pinned at admission")
        target = local_path(request.parent, declared)
        if target == request:
            raise ValueError("action-set input collides with staged request")
        if source in copied:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target != copied[source]:
                shutil.copyfile(copied[source], target)
        else:
            copy_pinned(source, target, pinned[source_name])
            copied[source] = target


def load_scene(project, scene_name="scene.json"):
    scene = read_json(local_path(project, scene_name))
    if not isinstance(scene, dict) or scene.get("schema_version") != 1:
        raise SceneError("invalid_schema", "Use scene schema_version 1.")
    identifier(scene.get("id"))
    brief = scene.get("brief")
    if not isinstance(brief, dict) or any(not isinstance(brief.get(key), str) or not brief[key].strip()
                                          for key in ("title", "goal", "controls")):
        raise SceneError("invalid_brief", "Provide nonempty brief title, goal and controls.")
    if scene.get("coordinates") != {"units": "meters", "up": "+Y", "handedness": "right"}:
        raise ValueError("coordinates must be meters, +Y up, right handed")
    assets = scene.get("assets")
    nodes = scene.get("nodes")
    if not isinstance(assets, list) or not assets or not isinstance(nodes, list) or not nodes:
        raise ValueError("scene requires nonempty assets and nodes")
    ids = set()
    specifications = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("asset must be an object")
        key = identifier(asset.get("id"))
        if key in ids or asset.get("producer") not in PRODUCERS:
            raise ValueError("duplicate asset or unsupported producer")
        ids.add(key)
        if "reuse" in asset:
            if "request" in asset:
                raise SceneError("invalid_reuse", "Choose request or reuse for each asset.")
            reused = resolve_reuse(project, asset)
            if asset["producer"] == "pixel-action-set":
                specifications[key] = read_json(local_path(project, reused["files"]["metadata"]))
            continue
        request = local_path(project, asset.get("request"))
        if not request.is_file():
            raise SceneError("missing_input", "Restore the declared asset request JSON inside the project.")
        if not isinstance(read_json(request), dict):
            raise SceneError("invalid_schema", "Asset request JSON must contain an object.")
        specifications[key] = read_json(request)
        if asset["producer"] == "pixel-action-set":
            action_inputs(request, specifications[key])
    names = set()
    kinds = {asset["id"]: asset["producer"] for asset in assets}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("node must be an object")
        name = identifier(node.get("id"))
        if name in names or node.get("asset") not in ids:
            raise ValueError("duplicate node or unknown asset reference")
        names.add(name)
        for key in ("position", "rotation_degrees", "scale"):
            vector(node.get(key), positive=key == "scale")
        if kinds[node["asset"]] in ("pixel-effect", "pixel-action-set"):
            size = node.get("size_m")
            if type(size) not in (int, float) or not math.isfinite(size) or size <= 0:
                raise ValueError("pixel nodes require positive size_m")
        if kinds[node["asset"]] == "pixel-action-set" and "action" in node:
            action = node["action"]
            if not isinstance(action, str) or action not in specifications[node["asset"]]["actions"]:
                raise ValueError("node action must name an action in its action-set")
    parents = {}
    for node in nodes:
        if "parent" in node:
            parent = identifier(node["parent"])
            if parent not in names or parent == node["id"]:
                raise ValueError("node parent must reference another scene node")
            parents[node["id"]] = parent
    for name in names:
        visited = set()
        while name in parents:
            if name in visited:
                raise ValueError("node parent hierarchy cannot contain cycles")
            visited.add(name)
            name = parents[name]
    feedback_effects(scene)
    return scene


def run_json(command, timeout):
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          start_new_session=os.name == "posix") as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        if process.returncode:
            raise ValueError(f"producer exited {process.returncode}: {stderr[-2000:]}")
        return json.loads(stdout)


def implementation(name, root, paths):
    manifest = root / ".codex-plugin/plugin.json"
    try:
        version = read_json(manifest).get("version", "unknown")
    except (OSError, ValueError, AttributeError):
        version = "unknown"
    files = [{"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
             for path in sorted(paths) if (root / path).is_file()]
    identity = {"name": name, "version": version, "files": files}
    identity["sha256"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity


def pixel_producer():
    executable = shutil.which("pixel-asset")
    if not executable:
        raise SceneError("missing_tool", "Install the pixel-asset executable and make it available on PATH.")
    launcher = Path(executable).resolve()
    data = launcher.read_bytes()
    identity = {"name": "pixel-asset-pipeline", "version": "unknown", "launcher": launcher.name,
                "path_sha256": hashlib.sha256(os.fsencode(launcher)).hexdigest(),
                "launcher_sha256": hashlib.sha256(data).hexdigest()}
    first_line = data.split(b"\n", 1)[0]
    if first_line.startswith(b"#!"):
        interpreter = Path(os.fsdecode(first_line[2:].strip()))
        if interpreter.is_absolute() and interpreter.name.startswith("python") and interpreter.is_file():
            try:
                metadata = run_json([str(interpreter), "-c",
                    "import importlib.metadata,json; print(json.dumps({'version':importlib.metadata.version('pixel-asset-pipeline')}))"], 10)
                if isinstance(metadata, dict) and isinstance(metadata.get("version"), str):
                    identity["version"] = metadata["version"]
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    identity["sha256"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return launcher, identity


def model_implementation(root):
    paths = ["tools/build.py", "tools/blender_worker.py", "three/inspect.mjs",
             "three/loader.mjs", "three/package-lock.json"]
    for path in ("tools/lantern.py", "tools/ember.py", "tools/decode_image.py", "three/decode.mjs"):
        if (root / path).is_file():
            paths.append(path)
    return implementation("model-assets", root, paths)


def model_root():
    override = os.environ.get("MODEL_ASSETS_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
    else:
        listing = run_json(["codex", "plugin", "list", "--marketplace", "model-assets", "--json"], 30)
        enabled = [item for item in listing.get("installed", []) if item.get("name") == "model-assets"
                   and item.get("marketplaceName") == "model-assets"
                   and item.get("installed") is True and item.get("enabled") is True]
        if len(enabled) != 1:
            raise SceneError("missing_tool", "Enable one installed model-assets plugin or configure MODEL_ASSETS_ROOT.")
        version = enabled[0].get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", version) or version in (".", ".."):
            raise ValueError("invalid installed model-assets version")
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        root = (home / "plugins/cache/model-assets/model-assets" / version).resolve()
    if not (root / "tools/build.py").is_file():
        raise SceneError("missing_tool", "Restore the installed model-assets producer or correct MODEL_ASSETS_ROOT.")
    return root


def verify_effect(effect):
    if (not isinstance(effect, dict) or type(effect.get("schema_version")) is not int
            or effect["schema_version"] != 1 or effect.get("kind") != "mesh-particles"
            or effect.get("units") != "meters"):
        raise ValueError("3D effect must be a version 1 mesh-particles recipe in meters")
    duration = effect.get("duration_s")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("3D effect duration_s must be finite and positive")
    particles = effect.get("particles")
    if not isinstance(particles, list) or not 1 <= len(particles) <= 256:
        raise ValueError("3D effect requires 1 to 256 particles")
    for particle in particles:
        if not isinstance(particle, dict):
            raise ValueError("3D particle must be an object")
        for key in ("offset", "drift", "spin"):
            vector(particle.get(key))
        for key in ("start_s", "life_s", "scale"):
            value = particle.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("3D particle timing and scale must be finite")
        if not (0 <= particle["start_s"] < duration and 0 < particle["life_s"] <= duration
                and particle["scale"] > 0):
            raise ValueError("3D particle timing or scale outside recipe bounds")


def verify_bundle(bundle, result, producer, *, require_effect=False):
    if not isinstance(result, dict) or result.get("schema_version") != 1 or result.get("status") != "ready":
        raise ValueError("producer must return schema_version 1 status ready")
    files = result.get("files")
    if not isinstance(files, dict) or any(key not in files for key in PRODUCERS[producer]):
        raise ValueError(f"incomplete {producer} bundle")
    for name in files.values():
        path = local_path(bundle.resolve(), name)
        if not path.is_file():
            raise ValueError(f"missing bundle artifact: {name}")
    if producer == "model-assets":
        validation = read_json(local_path(bundle.resolve(), files["validation"]))
        if not isinstance(validation, dict) or validation.get("passed") is not True:
            raise ValueError("3D producer validation did not pass")
        if Path(files["model"]).suffix.lower() != ".glb":
            raise ValueError("3D runtime model must be compiled GLB")
        if require_effect and "effect" not in files:
            raise ValueError("embers bundle requires files.effect")
        if "effect" in files:
            verify_effect(read_json(local_path(bundle.resolve(), files["effect"])))
    return files


def build(project, output, timeout, scene_name="scene.json", source_artifact=None):
    project = project.resolve()
    output_name = output
    if not project.is_dir():
        raise ValueError("project must be an existing directory")
    record = {"schema_version": 1, "run_id": uuid.uuid4().hex, "status": "running",
              "pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
              "scene": "scene.json", "steps": [], "assets": [],
              "implementation": implementation("game-studio", Path(__file__).resolve().parents[1],
                                                ["tools/scene.py", "tools/graph.py"])}
    scene = {}
    owns_output = False
    phase = "admission"
    output_conflict = False
    try:
        output = local_path(project, output_name)
        record["output"] = str(output.relative_to(project))
        input_path = local_path(project, scene_name)
        record["scene"] = str(input_path.relative_to(project))
        scene = load_scene(project, scene_name)
        if source_artifact:
            nodes = graph.query(project, subject=source_artifact, kind="Artifact")
            raw = input_path.read_bytes()
            if (len(nodes) != 1 or not nodes[0].get("wasGeneratedBy") or nodes[0].get("path") != record["scene"]
                    or nodes[0].get("sha256") != hashlib.sha256(raw).hexdigest()
                    or nodes[0].get("byteCount") != len(raw) or json.loads(raw) != scene):
                raise SceneError("missing_input", "Restore the exact prepared scene revision before rebuilding.")
            record["scene_source"] = source_artifact
        if output.exists() or output.is_symlink():
            output_conflict = True
            raise ValueError("output exists; retry with a fresh --out path")
        record["steps"] = [{"asset": a["id"], "producer": a["producer"], "status": "pending"}
                           for a in scene["assets"]]
        graph.update_run(project, record, scene)
        output.mkdir(parents=True)
        owns_output = True
        phase = "inputs"
        inputs = output / "inputs"
        inputs.mkdir()
        write_json(inputs / "scene.json", record["_graph_inputs"]["scene"]["snapshot"])
        record["input_scene"] = str((inputs / "scene.json").relative_to(project))
        requests = {}
        for asset in scene["assets"]:
            if "reuse" in asset:
                continue
            request = inputs / f"{asset['id']}.request.json"
            pin = record["_graph_inputs"]["requests"][asset["id"]]
            request_bytes = base64.b64decode(pin["snapshotBase64"])
            specification = json.loads(request_bytes)
            if asset["producer"] == "model-assets" and "source_blend" in specification:
                sources = pin.get("sources", [])
                if len(sources) != 1:
                    raise ValueError("source_blend requires one graph-pinned source")
                source = sources[0]
                target = inputs / f"{asset['id']}.source.blend"
                copy_pinned(local_path(project, source["path"]), target, source)
                specification["source_blend"] = target.name
                write_json(request, specification)
            else:
                if asset["producer"] == "pixel-action-set":
                    request = inputs / asset["id"] / "request.json"
                    request.parent.mkdir()
                    stage_action_inputs(project, local_path(project, asset["request"]), request,
                                        specification, pin.get("sources", []))
                request.write_bytes(request_bytes)
            requests[asset["id"]] = request
        graph.update_run(project, record, scene)
        phase = "discovery"
        root = model_root() if any(a["producer"] == "model-assets" and "reuse" not in a for a in scene["assets"]) else None
        for asset, step in zip(scene["assets"], record["steps"]):
            if "reuse" in asset:
                phase = "reuse-validation"
                reused = resolve_reuse(project, asset)
                record["assets"].append(reused)
                step.update(status="reused", reuse=reused["reuse"],
                            validation={"passed": True, "checks": ["artifact-sha256", "bundle-contract"]})
                graph.update_run(project, record, scene)
                continue
            phase = "discovery"
            if asset["producer"] in ("pixel-effect", "pixel-action-set"):
                launcher, step["implementation"] = pixel_producer()
            else:
                step["implementation"] = model_implementation(root)
            phase = "producer"
            step["status"] = "running"
            step["request"] = str(requests[asset["id"]].relative_to(project))
            graph.update_run(project, record, scene)
            bundle = output / "assets" / asset["id"]
            request = requests[asset["id"]]
            if asset["producer"] in ("pixel-effect", "pixel-action-set"):
                action = "effect" if asset["producer"] == "pixel-effect" else "action-set"
                command = [str(launcher), action, "--request", str(request), "--out", str(bundle)]
            else:
                command = ["python3", str(root / "tools/build.py"), "--request", str(request), "--out", str(bundle)]
            result = run_json(command, timeout)
            phase = "bundle-validation"
            bundle = local_path(output, f"assets/{asset['id']}")
            require_effect = asset["producer"] == "model-assets" and read_json(request).get("preset") == "embers"
            files = verify_bundle(bundle, result, asset["producer"], require_effect=require_effect)
            if asset["producer"] == "pixel-action-set":
                manifest = read_json(local_path(bundle, files["metadata"]))
                if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("actions"), dict):
                    raise ValueError("action-set metadata must contain version 1 named actions")
                for node in scene["nodes"]:
                    if node["asset"] == asset["id"] and node.get("action", "idle") not in manifest["actions"]:
                        raise ValueError("node action is missing from produced action-set")
            record["assets"].append({"id": asset["id"], "producer": asset["producer"],
                                     "request": str(request.relative_to(project)),
                                     "files": {key: str((bundle / name).relative_to(project))
                                               for key, name in files.items()}})
            step["status"] = "ready"
            checks = ["bundle-contract"]
            if asset["producer"] == "model-assets" and "effect" in files:
                checks.append("mesh-particles-contract")
            step["validation"] = {"passed": True, "checks": checks}
            graph.update_run(project, record, scene)
        phase = "reuse-validation"
        for asset in scene["assets"]:
            if "reuse" in asset:
                resolve_reuse(project, asset)
        phase = "publish"
        runtime = {"schema_version": 1, "status": "ready", "id": scene["id"], "brief": scene["brief"],
                   "coordinates": scene["coordinates"], "assets": record["assets"], "nodes": scene["nodes"],
                   "input_scene": record["input_scene"]}
        if "playtest" in scene:
            runtime["playtest"] = scene["playtest"]
        if "feedback" in scene:
            runtime["feedback"] = scene["feedback"]
        write_json(output / "scene.runtime.json", runtime)
        record["status"] = "ready"
        record["runtime"] = str((output / "scene.runtime.json").relative_to(project))
        graph.update_run(project, record, scene)
        return {"schema_version": 1, "status": "ready", "run_id": record["run_id"], "files": {"scene": record["runtime"]}}
    except (OSError, ValueError, subprocess.SubprocessError, TypeError, KeyError, KeyboardInterrupt) as exc:
        record["status"] = "error"
        if isinstance(exc, SceneError):
            reason = exc.code
        elif isinstance(exc, KeyboardInterrupt):
            reason = "interrupted"
        elif isinstance(exc, subprocess.TimeoutExpired):
            reason = "timeout"
        elif phase == "admission" and (isinstance(exc, FileExistsError) or output_conflict):
            reason = "output_exists"
        elif isinstance(exc, FileNotFoundError):
            reason = "missing_input" if phase in ("admission", "inputs", "reuse-validation") else "missing_tool"
        elif isinstance(exc, json.JSONDecodeError):
            reason = "invalid_schema"
        else:
            reason = {"admission": "invalid_scene", "inputs": "input_mismatch", "discovery": "missing_tool",
                      "producer": "producer_failed", "bundle-validation": "invalid_bundle"}.get(phase, "build_failed")
        guidance = {"interrupted": "Retry with a fresh output directory.", "timeout": "Check the producer and retry with a fresh output directory.",
                    "output_exists": "Choose a fresh output directory.", "missing_tool": "Install or enable the required producer.",
                    "missing_input": "Restore the declared project input.", "invalid_schema": "Provide valid version 1 JSON input.",
                    "invalid_scene": "Correct the scene asset, node and transform declarations.",
                    "input_mismatch": "Restore pinned inputs or start a fresh run.",
                    "producer_failed": "Check producer inputs and installation, then retry with a fresh output.",
                    "invalid_bundle": "Correct the producer bundle contract before retrying."}
        record["error"] = {"code": reason, "type": type(exc).__name__, "stage": phase,
                           "reason": exc.reason if isinstance(exc, SceneError) else guidance.get(reason, "Check the declared inputs and retry with a fresh output.")}
        for step in record["steps"]:
            if step["status"] in ("running", "reused"):
                step["status"] = "error"
        if owns_output:
            (output / "scene.runtime.json").unlink(missing_ok=True)
            record.pop("runtime", None)
        graph.update_run(project, record, scene)
        if owns_output:
            write_json(output / "failure.json", {"schema_version": 1, "status": "error", "error": record["error"]})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "build"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", default="build/run-1")
    parser.add_argument("--timeout", default=300, type=int)
    parser.add_argument("--scene", default="scene.json", help="Project-relative scene input")
    parser.add_argument("--source-artifact", help="Explicit graph Artifact ID of a prepared scene revision")
    args = parser.parse_args(argv)
    try:
        project = args.project.resolve()
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        if args.command == "validate":
            load_scene(project, args.scene)
            result = {"schema_version": 1, "status": "valid"}
        else:
            result = build(project, args.out, args.timeout, args.scene, args.source_artifact)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, TypeError, KeyError) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": {"code": exc.code if isinstance(exc, SceneError) else "invalid_input",
                "reason": exc.reason if isinstance(exc, SceneError) else "Check scene inputs, producer installation and the recorded failure."}}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
