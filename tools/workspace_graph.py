#!/usr/bin/env python3
"""Read the project graphs registered in a local workspace manifest."""
import argparse
import json
from pathlib import Path
import uuid

import graph


def registered_projects(manifest, config=None):
    manifest = Path(manifest).resolve(strict=True)
    root = manifest.parent
    if config is None:
        config = json.loads(manifest.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("unsupported workspace schema_version")
    workspace = "urn:game-studio:workspace:" + str(uuid.UUID(config["workspace_id"]))
    if not isinstance(config.get("projects"), list) or not config["projects"]:
        raise ValueError("workspace requires at least one project")
    projects = []
    for name in config["projects"]:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError("project names must be relative paths")
        project = (root / name).resolve(strict=True)
        if not project.is_dir() or not project.is_relative_to(root) or project in projects:
            raise ValueError(f"invalid registered project: {name}")
        projects.append(project)
    return workspace, projects


def export_workspace(manifest):
    config = json.loads(Path(manifest).read_text(encoding="utf-8"))
    workspace, projects = registered_projects(manifest, config)
    merged = {}
    members = []
    for project in projects:
        scope = graph.project_id(project)
        if scope in members:
            raise ValueError("two registered folders use the same graph identity")
        nodes = graph.export_graph(project)["@graph"]
        if not any(node["@id"] == scope and "Project" in node["@type"] for node in nodes):
            raise ValueError(f"project has no admitted work: {project.name}")
        members.append(scope)
        for node in nodes:
            ident = node["@id"]
            if ident in merged and node != merged[ident]:
                raise ValueError(f"conflicting graph subject: {ident}")
            merged[ident] = node
    for node in merged.values():
        if "ExternalWork" not in node["@type"]:
            continue
        pins = node.get("snapshot", {}).get("workspace_inputs", [])
        if not isinstance(pins, list):
            raise ValueError("invalid workspace input pins")
        for pin in pins:
            if not isinstance(pin, dict) or set(pin) != {"@id", "sha256", "byteCount"}:
                raise ValueError("invalid workspace input pin")
            target = merged.get(pin["@id"], {})
            if ("Entity" not in target.get("@type", []) or
                    any(target.get(key) != pin[key] for key in ("sha256", "byteCount"))):
                raise ValueError("workspace input entity missing or pin mismatch")
            used = node.setdefault("used", [])
            if pin["@id"] not in used:
                used.append(pin["@id"])
    # Workspace links resolve against the unified graph; project shards stay independently readable.
    links = config.get("links", [])
    if not isinstance(links, list):
        raise ValueError("workspace links must be a list")
    for link in links:
        if not isinstance(link, dict) or set(link) not in ({"activity", "observed"}, {"activity", "used"}):
            raise ValueError("workspace link requires an activity and exactly one observed/used target")
        relation = "used" if "used" in link else "observed"
        activity, target = link["activity"], link[relation]
        if activity not in merged or target not in merged or "ExternalWork" not in merged[activity]["@type"]:
            raise ValueError("workspace link requires an admitted external activity and target")
        if relation == "used" and "Entity" not in merged[target]["@type"]:
            raise ValueError("a used workspace input must be an entity")
        targets = merged[activity].setdefault(relation, [])
        if target not in targets:
            targets.append(target)
    merged[workspace] = {"@id": workspace, "@type": ["Entity", "Workspace"], "includesProject": members}
    result = {"schema_version": 1, "@context": graph.CONTEXT,
              "@graph": [merged[ident] for ident in sorted(merged)]}
    return graph.validate_graph(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    try:
        print(json.dumps(export_workspace(parser.parse_args().manifest), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
