#!/usr/bin/env python3
"""Read the project graphs registered in a local workspace manifest."""
import argparse
import json
from pathlib import Path
import uuid

import graph


def registered_projects(manifest):
    manifest = Path(manifest).resolve(strict=True)
    root = manifest.parent
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
    workspace, projects = registered_projects(manifest)
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
    # Cross-project observations belong to the workspace, with both endpoints checked.
    for link in json.loads(Path(manifest).read_text(encoding="utf-8")).get("links", []):
        activity, subject = link["activity"], link["observed"]
        if activity not in merged or subject not in merged or "ExternalWork" not in merged[activity]["@type"]:
            raise ValueError("workspace observation requires an admitted activity and subject")
        observed = merged[activity].setdefault("observed", [])
        if subject not in observed:
            observed.append(subject)
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
