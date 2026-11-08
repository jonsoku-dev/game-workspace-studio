#!/usr/bin/env python3
"""Offline provenance graph. Atomic run shards are the only history store."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

NS = "https://game-studio.local/ns/v1#"
PROV = "http://www.w3.org/ns/prov#"
RELATIONS = {"used", "wasGeneratedBy", "wasDerivedFrom", "wasAssociatedWith", "dependsOn",
             "observed", "failedWith", "revisionOf", "partOf", "placementOf", "includesProject"}
CONTEXT = {"@version": 1.1, "@vocab": NS, "prov": PROV,
           "Entity": "prov:Entity", "Activity": "prov:Activity", "Agent": "prov:Agent"}
for _term in ("snapshot", "record", "checks", "references", "implementation"):
    CONTEXT[_term] = {"@id": NS + _term, "@type": "@json"}
for _term in RELATIONS:
    CONTEXT[_term] = {"@id": (PROV if _term in {"used", "wasGeneratedBy", "wasDerivedFrom",
                        "wasAssociatedWith"} else NS) + _term, "@type": "@id", "@container": "@set"}


LEGACY_CONTEXT = json.loads(json.dumps(CONTEXT))
RELATIONS.add("attachedTo")
CONTEXT["attachedTo"] = {"@id": NS + "attachedTo", "@type": "@id", "@container": "@set"}


def _supported_context(context):
    return context == CONTEXT or context == LEGACY_CONTEXT


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _local(project, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("expected project-relative path")
    root = Path(project).resolve()
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("path escapes project")
    return path


def _slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}", value):
        raise ValueError("invalid scoped identifier")
    return value


def _atomic(path, data, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".graph-", delete=False) as stream:
        temp = Path(stream.name)
        stream.write((_json(data) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if exclusive:
            os.link(temp, path)
        else:
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def project_id(project, create=False):
    path = _local(project, ".game-studio/project.json")
    if not path.exists() and create:
        try:
            _atomic(path, {"schema_version": 1, "project_id": str(uuid.uuid4())}, exclusive=True)
        except FileExistsError:
            pass
    data = json.loads(path.read_text())
    return "urn:game-studio:" + str(uuid.UUID(data["project_id"]))


def _node(ident, kind, **properties):
    base = "Agent" if kind in {"Plugin", "Agent"} else "Activity" if kind in {"Run", "WorkStep", "Validation", "ExternalWork"} else "Entity"
    return {"@id": ident, "@type": list(dict.fromkeys([base, kind])), **properties}


def _snapshot(project, path, content=True):
    data = _local(project, path).read_bytes()
    result = {"path": path, "sha256": _digest(data), "byteCount": len(data)}
    if content == "json":
        result["snapshot"] = json.loads(data)
        if not isinstance(result["snapshot"], dict):
            raise ValueError("motion recipe must be a JSON object")
    elif content:
        result["snapshotBase64"] = base64.b64encode(data).decode()
    return result


def _request(project, path, producer=None):
    result = _snapshot(project, path)
    data = json.loads(base64.b64decode(result["snapshotBase64"]))
    if isinstance(data, dict) and data.get("source_blend"):
        source = _local(project, str(Path(path).parent / data["source_blend"]))
        result["sources"] = [_snapshot(project, str(source.relative_to(Path(project).resolve())), False)]
    if producer == "pixel-action-set":
        if not isinstance(data, dict) or not isinstance(data.get("actions"), dict):
            raise ValueError("action-set request requires actions")
        declared = []
        for action in data["actions"].values():
            if not isinstance(action, dict) or not isinstance(action.get("frames"), list):
                raise ValueError("action-set action requires frames")
            for frame in action["frames"]:
                if not isinstance(frame, dict):
                    raise ValueError("action-set frame must be an object")
                declared.append(frame.get("path"))
        events = data.get("events", [])
        if not isinstance(events, list):
            raise ValueError("action-set events must be a list")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("action-set event must be an object")
            declared.extend(event.get(role) for role in ("sheet", "metadata", "license", "notice"))
        request_root = _local(project, path).parent
        source_paths = {_local(request_root, value) for value in declared}
        result["sources"] = [_snapshot(project, str(source.relative_to(Path(project).resolve())), False)
                             for source in sorted(source_paths)]
    return result


def _public(record):
    return {key: value for key, value in record.items() if not key.startswith("_graph_")}


def validate_graph(document):
    if not _supported_context(document.get("@context")) or document.get("schema_version") != 1:
        raise ValueError("unsupported offline graph context/version")
    nodes = document.get("@graph")
    if not isinstance(nodes, list):
        raise ValueError("graph must be a node list")
    ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("graph nodes must be objects")
        ident = node.get("@id")
        if not isinstance(ident, str) or not ident.startswith("urn:game-studio:") or ident in ids:
            raise ValueError("invalid or duplicate graph id")
        ids.add(ident)
        if (not isinstance(node.get("@type"), list) or not node["@type"]
                or any(not isinstance(kind, str) for kind in node["@type"])):
            raise ValueError("node requires types")
    for node in nodes:
        for relation in RELATIONS:
            targets = node.get(relation, [])
            if (not isinstance(targets, list) or any(not isinstance(target, str) or target not in ids for target in targets)
                    or len(targets) != len(set(targets))):
                raise ValueError(f"dangling {relation} reference")
    by_id = {node["@id"]: node for node in nodes}
    for relations in (("used", "wasGeneratedBy", "wasDerivedFrom", "dependsOn"), ("attachedTo",)):
        incoming = dict.fromkeys(by_id, 0)
        for node in nodes:
            for relation in relations:
                for target in node.get(relation, []):
                    incoming[target] += 1
        ready = [ident for ident, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            ident = ready.pop()
            visited += 1
            for relation in relations:
                for target in by_id[ident].get(relation, []):
                    incoming[target] -= 1
                    if incoming[target] == 0:
                        ready.append(target)
        if visited != len(nodes):
            raise ValueError("cyclic graph relationship")
    return document


def compile_run(project, record, scene):
    """Compile observed state, pinning inputs/artifacts in this run's memory."""
    scope = project_id(project, create=True)
    run = scope + ":run:" + _slug(record["run_id"])
    inputs = record.get("_graph_inputs")
    if inputs is None:
        try:
            inputs = {"scene": {"path": record.get("scene", "scene.json"),
                                 "sha256": _digest(_json(scene).encode()), "snapshot": json.loads(_json(scene))},
                      "requests": {a["id"]: _request(project, a["request"], a["producer"])
                                   for a in scene.get("assets", []) if "reuse" not in a}}
        except (OSError, ValueError, TypeError):
            if record.get("status") != "error":
                raise
            inputs = {"scene": {"path": record.get("scene", "scene.json"),
                                 "sha256": _digest(b"{}"), "snapshot": {}}, "requests": {}}
        record["_graph_inputs"] = inputs
    pinned_scene = inputs["scene"]["snapshot"]
    scene_id = scope + ":scene:" + inputs["scene"]["sha256"]
    game = scope + ":game:" + _slug(pinned_scene.get("id", "unadmitted"))
    nodes = {scope: _node(scope, "Project"), game: _node(game, "Game", partOf=[scope]),
             scene_id: _node(scene_id, "SceneRevision" if pinned_scene else "UnadmittedInput", partOf=[game], **inputs["scene"])}
    run_node = _node(run, "Run", status=record["status"], used=[scene_id], partOf=[scope],
                     record=_public(record))
    nodes[run] = run_node
    if record.get("implementation") is not None:
        implementation = record["implementation"]
        if not isinstance(implementation, dict):
            raise ValueError("studio implementation must be an object")
        studio = scope + ":plugin:studio:" + _digest(_json(implementation).encode())
        nodes[studio] = _node(studio, "Plugin", label="studio", implementation=implementation)
        run_node["wasAssociatedWith"] = [studio]
        run_node["implementation"] = implementation
    revisions = record.setdefault("_graph_revisions", [])
    revision = _public(record)
    if not revisions or revisions[-1] != revision:
        revisions.append(json.loads(_json(revision)))
    for index, value in enumerate(revisions):
        ident = run + ":revision:" + str(index + 1)
        nodes[ident] = _node(ident, "RunRevision", revisionOf=[run], sequence=index + 1, snapshot=value,
                             sha256=_digest(_json(value).encode()))
    pins = record.setdefault("_graph_artifacts", {})
    asset_outputs = {}
    output_ids = {}
    admitted = None
    for asset in record.get("assets", []):
        if asset["id"] not in {a["id"] for a in pinned_scene.get("assets", [])}:
            raise ValueError("artifact belongs to unknown input asset")
        asset_outputs[asset["id"]] = asset
    for index, step in enumerate(record.get("steps", []) if pinned_scene else []):
        asset = step["asset"]
        declaration = next(a for a in pinned_scene["assets"] if a["id"] == asset)
        if "reuse" in declaration:
            if step["status"] == "pending":
                continue
            if step["status"] == "error":
                continue
            if step["status"] != "reused":
                raise ValueError("reused assets cannot claim producer execution")
            if admitted is None:
                admitted = {node["@id"]: node for node in export_graph(project)["@graph"]}
            reuse = step.get("reuse", {})
            selected_run = declaration["reuse"]["run_id"]
            source_run = selected_run if selected_run.startswith(scope + ":run:") else scope + ":run:" + _slug(selected_run)
            original = admitted.get(source_run, {})
            if (source_run == run or reuse.get("run") != source_run
                    or reuse.get("run_id") != original.get("record", {}).get("run_id")
                    or reuse.get("asset") != declaration["reuse"]["asset"]
                    or "Run" not in original.get("@type", []) or original.get("status") != "ready"):
                raise ValueError("reuse requires an admitted ready source run")
            source_asset = next((a for a in original["record"].get("assets", [])
                                 if a["id"] == reuse["asset"]), None)
            output = asset_outputs.get(asset, {})
            if (source_asset is None or output.get("files") != source_asset["files"]
                    or output.get("reuse") != reuse):
                raise ValueError("reuse files must match the original asset")
            original_ids = source_asset.get("reuse", {}).get("artifacts")
            if original_ids is None:
                original_ids = [source_run + ":artifact:" + _digest(path.encode())
                                for path in source_asset["files"].values()]
            if (not isinstance(reuse.get("artifacts"), list)
                    or any(not isinstance(ident, str) for ident in reuse["artifacts"])
                    or set(reuse["artifacts"]) != set(original_ids)
                    or len(reuse["artifacts"]) != len(original_ids)):
                raise ValueError("reuse requires exact original artifact IDs")
            output_ids[asset] = {}
            for role, path in output["files"].items():
                candidates = [admitted.get(ident, {}) for ident in original_ids]
                source = next((n for n in candidates if n.get("path") == path and n.get("role") == role), {})
                snapshot = _snapshot(project, path, False)
                if ("Artifact" not in source.get("@type", [])
                        or any(source.get(k) != snapshot[k] for k in ("path", "sha256", "byteCount"))):
                    raise ValueError("reused artifact changed or is not admitted")
                output_ids[asset][role] = source["@id"]
            step_id = run + ":step:" + _slug(asset)
            nodes[step_id] = _node(step_id, "WorkStep", status="reused", sequence=index + 1,
                                   used=[source_run] + reuse["artifacts"], partOf=[run])
            if step.get("validation") is not None:
                check = step_id + ":validation"
                nodes[check] = _node(check, "Validation", used=reuse["artifacts"], partOf=[run], **step["validation"])
                nodes[check + ":evidence"] = _node(check + ":evidence", "ValidationEvidence",
                                                   wasGeneratedBy=[check], snapshot=step["validation"])
            run_node["used"].extend(i for i in [source_run] + reuse["artifacts"] if i not in run_node["used"])
            continue
        request = inputs["requests"][asset]
        request_id = scope + ":request:" + _digest(_json({"path": request["path"], "sha256": request["sha256"], "sources": request.get("sources", [])}).encode())
        sources = []
        for source in request.get("sources", []):
            source_id = scope + ":source:" + _digest(source["path"].encode()) + ":" + source["sha256"]
            nodes[source_id] = _node(source_id, "SourceArtifact", **source)
            if step["producer"] == "pixel-action-set":
                nodes[source_id]["@type"].append("Imported2DInput")
            sources.append(source_id)
        nodes[request_id] = _node(request_id, "RequestRevision", wasDerivedFrom=sources,
                                 **{k: v for k, v in request.items() if k != "sources"})
        step_id = run + ":step:" + _slug(asset)
        plugin = scope + ":plugin:" + _slug(step["producer"])
        implementation = step.get("implementation")
        if implementation is not None:
            if not isinstance(implementation, dict):
                raise ValueError("plugin implementation must be an object")
            plugin += ":" + _digest(_json(implementation).encode())
        nodes[plugin] = _node(plugin, "Plugin", label=step["producer"])
        if implementation is not None:
            nodes[plugin]["implementation"] = implementation
        if step["status"] == "pending":
            continue
        used_request = request_id
        if step.get("request"):
            request_path = step["request"]
            pin_key = "executed:" + request_path
            if pin_key not in pins:
                pins[pin_key] = _snapshot(project, request_path)
            used_request = step_id + ":request"
            nodes[used_request] = _node(used_request, "ExecutedRequest", wasDerivedFrom=[request_id] + sources,
                                        **pins[pin_key])
        nodes[step_id] = _node(step_id, "WorkStep", status=step["status"], sequence=index + 1,
                              used=[used_request] + (sources if step["producer"] == "pixel-action-set" else []),
                              wasAssociatedWith=[plugin], partOf=[run])
        artifacts = []
        output_ids[asset] = {}
        for role, path in asset_outputs.get(asset, {}).get("files", {}).items():
            if path not in pins:
                pins[path] = _snapshot(project, path, "json" if role == "effect" else False)
            value = pins[path]
            ident = run + ":artifact:" + _digest(path.encode())
            nodes[ident] = _node(ident, "Artifact", role=role, wasGeneratedBy=[step_id],
                                 wasDerivedFrom=[request_id] + (sources if step["producer"] == "pixel-action-set" else []), **value)
            if step["producer"] == "pixel-action-set":
                if role == "atlas":
                    nodes[ident]["@type"].append("ActionAtlas")
                elif role == "metadata":
                    nodes[ident]["@type"].append("ActionMetadata")
                elif re.fullmatch(r"effect_[0-9]+_(sheet|metadata|license|notice)", role):
                    nodes[ident]["@type"].append("CopiedEffectInput")
                    nodes[ident]["wasDerivedFrom"] = [request_id] + [source for source in sources
                                                       if nodes[source]["sha256"] == value["sha256"]]
            if role == "effect":
                nodes[ident]["@type"].append("MotionRecipe")
            artifacts.append(ident)
            output_ids[asset][role] = ident
        _model_phases(project, run, step_id, asset_outputs.get(asset, {}), pins, nodes)
        validation = step.get("validation")
        if validation is not None:
            check = step_id + ":validation"
            nodes[check] = _node(check, "Validation", used=artifacts, partOf=[run], **validation)
            evidence = check + ":evidence"
            nodes[evidence] = _node(evidence, "ValidationEvidence", wasGeneratedBy=[check], snapshot=validation)
        if step["status"] == "error":
            error = step_id + ":error"
            nodes[error] = _node(error, "Error", snapshot=record.get("error", {}))
            nodes[step_id]["failedWith"] = [error]
    if record.get("runtime"):
        path = record["runtime"]
        if path not in pins:
            pins[path] = _snapshot(project, path, False)
        runtime_id = run + ":runtime"
        artifacts = list(dict.fromkeys(ident for outputs in output_ids.values() for ident in outputs.values()))
        nodes[runtime_id] = _node(runtime_id, "RuntimeProduct", wasGeneratedBy=[run],
                                  wasDerivedFrom=[scene_id] + artifacts, **pins[path])
        for placement in pinned_scene.get("nodes", []):
            ident = run + ":placement:" + _slug(placement["id"])
            asset = asset_outputs.get(placement["asset"], {})
            files = asset.get("files", {})
            producer = next(a["producer"] for a in pinned_scene["assets"] if a["id"] == placement["asset"])
            if producer == "pixel-action-set":
                roles = ("atlas", "metadata") + tuple(sorted(role for role in files
                        if re.fullmatch(r"effect_[0-9]+_(sheet|metadata)", role)))
            else:
                roles = ("model", "effect") if producer == "model-assets" else ("sheet", "metadata")
            outputs = [output_ids[placement["asset"]][role] for role in roles if role in files]
            nodes[ident] = _node(ident, "ScenePlacement", partOf=[runtime_id], placementOf=outputs,
                                 wasDerivedFrom=[scene_id], snapshot=placement)
            if placement.get("parent") is not None:
                nodes[ident]["attachedTo"] = [run + ":placement:" + _slug(placement["parent"])]
    if record.get("error"):
        ident = run + ":error"
        nodes[ident] = _node(ident, "Error", snapshot=record["error"])
        run_node["failedWith"] = [ident]
    document = {"@context": CONTEXT, "schema_version": 1, "@graph": list(nodes.values())}
    combined = {**(admitted or {}), **nodes}
    validate_graph({**document, "@graph": list(combined.values())})
    return document



def _model_phases(project, run, step_id, asset, pins, nodes):
    """Report-backed substeps; reports do not constitute independent acceptance."""
    files = asset.get("files", {})
    if not {"source", "raw", "metadata", "model", "receipt", "validation"} <= files.keys():
        return
    ids = {role: run + ":artifact:" + _digest(path.encode()) for role, path in files.items()}

    def report(role):
        raw = _local(project, files[role]).read_bytes()
        if _digest(raw) != pins[files[role]]["sha256"]:
            raise ValueError("producer report changed after observation")
        return json.loads(raw)

    metadata, receipt, validation = (report(role) for role in ("metadata", "receipt", "validation"))
    if (not metadata.get("blender_version") or metadata.get("flags", {}).get("roundtrip_verified") is not True):
        return
    blender = step_id + ":blender"
    nodes[blender] = _node(blender, "WorkStep", label="Blender source/export", evidenceBasis="producer-report",
                          partOf=[step_id], observed=[ids["metadata"]], used=nodes[step_id]["used"])
    for role in ("source", "raw", "metadata"):
        nodes[ids[role]]["wasGeneratedBy"] = [blender]
    if (receipt.get("contract") != {"id": "webstage-asset", "version": "1.0"}
            or receipt.get("ok") is not True or receipt.get("kind") != "gltf"
            or receipt.get("violations") != []
            or receipt.get("output", {}).get("bytes") != pins[files["model"]]["byteCount"]
            or Path(receipt.get("input", {}).get("path", "")).name != Path(files["raw"]).name
            or Path(receipt.get("output", {}).get("path", "")).name != Path(files["model"]).name):
        return
    compile_id = step_id + ":webstage"
    nodes[compile_id] = _node(compile_id, "WorkStep", label="Webstage compilation", evidenceBasis="producer-report",
                             partOf=[step_id], used=[ids["raw"]], observed=[ids["receipt"]], dependsOn=[blender])
    for role in ("model", "receipt"):
        nodes[ids[role]]["wasGeneratedBy"] = [compile_id]
    nodes[ids["model"]]["wasDerivedFrom"] = [ids["raw"]]
    if validation.get("passed") is True and validation.get("three_version"):
        check = step_id + ":three"
        nodes[check] = _node(check, "Validation", label="Three.js model inspection", evidenceBasis="producer-report",
                             partOf=[step_id], used=[ids["model"], ids["receipt"]], dependsOn=[compile_id], passed=True)
        nodes[ids["validation"]]["wasGeneratedBy"] = [check]
        nodes[ids["validation"]]["@type"].append("ValidationEvidence")

def update_run(project, record, scene):
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    document = compile_run(project, record, scene)
    path = _local(project, ".game-studio/runs/" + _slug(record["run_id"]) + ".jsonld")
    _atomic(path, document)
    return path


def export_graph(project):
    """Read only; missing history yields an empty portable graph."""
    root = _local(project, ".game-studio/runs")
    merged = {}
    paths = sorted(root.glob("*.jsonld"))
    scope = project_id(project) if paths else None
    for path in paths:
        if path.is_symlink():
            raise ValueError("graph shards cannot be symlinks")
        document = json.loads(path.read_text())
        # External records may reference an already admitted node in another shard.
        if not _supported_context(document.get("@context")) or document.get("schema_version") != 1:
            raise ValueError("unsupported shard context/version")
        shard_ids = set()
        for node in document["@graph"]:
            ident = node["@id"]
            if ident in shard_ids:
                raise ValueError("duplicate subject in shard")
            shard_ids.add(ident)
            if ident != scope and not ident.startswith(scope + ":"):
                raise ValueError("foreign subject in project shard")
            if ident in merged and merged[ident] != node:
                raise ValueError(f"conflicting subject: {ident}")
            merged[ident] = node
    return validate_graph({"@context": CONTEXT, "schema_version": 1, "@graph": list(merged.values())})


def history(project):
    return sorted([dict(node["record"], graph_id=node["@id"]) for node in export_graph(project)["@graph"]
                   if "Run" in node["@type"]], key=lambda r: (r.get("started_at", ""), r["run_id"]))


def query(project, subject=None, kind=None):
    return [node for node in export_graph(project)["@graph"]
            if (subject is None or node["@id"] == subject) and (kind is None or kind in node["@type"])]


def record_work(project, record):
    """Admit one immutable, scoped external work record; never execute its content."""
    allowed = {"id", "label", "agent", "status", "used", "observed", "files", "generated", "verification", "references", "workspace_inputs"}
    if not isinstance(record, dict) or set(record) - allowed:
        raise ValueError("unknown external-work fields")
    key = _slug(record["id"])
    if record.get("status") not in ("complete", "error") or not isinstance(record.get("label"), str):
        raise ValueError("external work requires label and complete/error status")
    scope = project_id(project, create=True)
    ident = scope + ":work:" + key
    existing = export_graph(project)
    ids = {n["@id"] for n in existing["@graph"]}
    if ident in ids:
        raise ValueError("work id already admitted")
    nodes = {scope: _node(scope, "Project")}
    agent = scope + ":agent:" + _slug(record["agent"])
    nodes[agent] = _node(agent, "Agent", label=record["agent"])
    work = _node(ident, "ExternalWork", label=record["label"], status=record["status"],
                 recordedAt=datetime.now(timezone.utc).isoformat(), wasAssociatedWith=[agent], partOf=[scope])
    nodes[ident] = work
    for relation in ("used", "observed"):
        targets = record.get(relation, [])
        if not isinstance(targets, list) or any(not isinstance(t, str) or t not in ids for t in targets):
            raise ValueError("external work references unknown subjects")
        if len(targets) != len(set(targets)):
            raise ValueError("duplicate external work references")
        work[relation] = list(targets)
    workspace_inputs = record.get("workspace_inputs", [])
    if (not isinstance(workspace_inputs, list) or any(not isinstance(pin, dict)
            or set(pin) != {"@id", "sha256", "byteCount"}
            or not isinstance(pin["@id"], str) or not pin["@id"].startswith("urn:game-studio:")
            or pin["@id"] in ids or not isinstance(pin["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
            or type(pin["byteCount"]) is not int or pin["byteCount"] < 0 for pin in workspace_inputs)
            or len({pin["@id"] for pin in workspace_inputs}) != len(workspace_inputs)):
        raise ValueError("workspace inputs require unique foreign entity hash/size pins")
    if workspace_inputs:
        work["snapshot"] = {"workspace_inputs": json.loads(_json(workspace_inputs))}
    references = record.get("references", [])
    if not isinstance(references, list) or any(not isinstance(r, str) or not r.startswith("https://") for r in references):
        raise ValueError("references require HTTPS citations")
    work["references"] = references
    files = record.get("files", [])
    if not isinstance(files, list):
        raise ValueError("files must be a list")
    artifacts = []
    paths = set()
    for path in files:
        snapshot = _snapshot(project, path, False)
        if any(_local(project, p) == _local(project, path) for p in paths):
            raise ValueError("duplicate external file")
        paths.add(snapshot["path"])
        artifact = ident + ":artifact:" + _digest(path.encode())
        nodes[artifact] = _node(artifact, "Artifact", **snapshot)
        work["observed"].append(artifact)
        artifacts.append(artifact)
    generated = record.get("generated", [])
    if not isinstance(generated, list):
        raise ValueError("generated must be a list")
    by_id = {node["@id"]: node for node in existing["@graph"]}
    for output in generated:
        if (not isinstance(output, dict) or set(output) - {"path", "sha256", "wasDerivedFrom"}
                or not {"path", "sha256"} <= output.keys()):
            raise ValueError("generated requires path and sha256")
        snapshot = _snapshot(project, output["path"], False)
        canonical = str(_local(project, output["path"]).relative_to(Path(project).resolve()))
        if canonical in paths or any(_local(project, p) == _local(project, output["path"]) for p in paths):
            raise ValueError("duplicate external file")
        paths.add(canonical)
        if output["sha256"] != snapshot["sha256"]:
            raise ValueError("generated file hash mismatch")
        derived = output.get("wasDerivedFrom", [])
        if (not isinstance(derived, list) or any(not isinstance(target, str) or target not in work["used"]
                or "Entity" not in by_id[target]["@type"] for target in derived)
                or len(derived) != len(set(derived))):
            raise ValueError("derivation requires explicitly used existing entities")
        artifact = ident + ":artifact:" + _digest(output["path"].encode())
        nodes[artifact] = _node(artifact, "Artifact", wasGeneratedBy=[ident], wasDerivedFrom=derived, **snapshot)
        artifacts.append(artifact)
    verification = record.get("verification")
    if verification is not None:
        if (not isinstance(verification, dict) or set(verification) != {"passed", "checks"}
                or type(verification["passed"]) is not bool or not isinstance(verification["checks"], list)
                or not all(isinstance(c, str) for c in verification["checks"])):
            raise ValueError("verification requires passed boolean and check strings")
        check = ident + ":validation"
        nodes[check] = _node(check, "Validation", used=artifacts, observed=work["observed"],
                             partOf=[ident], **verification)
        evidence = check + ":evidence"
        nodes[evidence] = _node(evidence, "ValidationEvidence", wasGeneratedBy=[check], snapshot=verification)
    document = {"@context": CONTEXT, "schema_version": 1, "@graph": list(nodes.values())}
    validate_graph({**document, "@graph": existing["@graph"] + [n for k, n in nodes.items() if k not in ids]})
    path = _local(project, ".game-studio/runs/work-" + key + ".jsonld")
    _atomic(path, document, exclusive=True)
    return ident


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "history", "query", "record"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--type")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            if args.record is None:
                raise ValueError("record requires --record")
            result = {"@id": record_work(args.project, json.loads(args.record.read_text()))}
        elif args.command == "history":
            result = history(args.project)
        elif args.command == "query":
            result = query(args.project, args.id, args.type)
        else:
            result = export_graph(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
