#!/usr/bin/env python3
"""Read-only loopback viewer for a Studio project and its registered workspace."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import runpy
import threading
from urllib.parse import parse_qs, urlsplit

import graph
from scene import model_root
from workspace_graph import export_workspace, registered_projects


UI = Path(__file__).resolve().parents[1] / "visualizer"
PAGES = {"/": "index.html", "/app.mjs": "app.mjs", "/style.css": "style.css",
         "/scene-view.mjs": "scene-view.mjs", "/i18n.mjs": "i18n.mjs",
         "/shell-i18n.mjs": "shell-i18n.mjs", "/app-messages.mjs": "app-messages.mjs",
         "/view-messages.mjs": "view-messages.mjs"}
MIME = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript",
        ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
        ".glb": "model/gltf-binary", ".png": "image/png", ".gif": "image/gif"}
POLICY = ("default-src 'none'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
          "connect-src 'self' blob:; img-src 'self' blob: data:; font-src 'self'; "
          "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


def static_routes():
    routes = {url: UI / filename for url, filename in PAGES.items()}
    try:
        producer = model_root()
    except (ValueError, OSError):
        return routes
    modules = runpy.run_path(str(producer / "tools/serve.py"))["MODULES"]
    routes["/model/loader.mjs"] = producer / "three/loader.mjs"
    for url, name in modules.items():
        routes["/three/" + url] = producer / "three/node_modules/three" / name
    return routes


def live_process(pid):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def state(project, workspace, browse=False, viewer_port=None):
    doc = export_workspace(workspace) if workspace else graph.export_graph(project)
    scope = graph.project_id(project) if (project / ".game-studio/project.json").exists() else None
    runs = []
    activities = []
    for node in doc["@graph"]:
        if scope not in node.get("partOf", []):
            continue
        if "Run" in node["@type"]:
            run = {**node["record"], "graph_id": node["@id"], "live": None}
            if run["status"] == "running":
                run["live"] = live_process(run.get("pid"))
            runs.append(run)
        elif "ExternalWork" in node["@type"]:
            activities.append({"graph_id": node["@id"], "label": node.get("label"),
                               "status": node.get("status"), "recorded_at": node.get("recordedAt")})
    if workspace:
        attach_playtests(runs, doc, json.loads(workspace.read_text(encoding="utf-8")).get("playtests", []), viewer_port)
    choices = []
    if browse:
        _, projects = registered_projects(workspace)
        choices = project_choices(doc, projects)
    return {"project_id": scope, "project_name": project.name, "projects": choices, "graph": doc,
            "runs": sorted(runs, key=lambda r: (r["started_at"], r["run_id"]), reverse=True),
            "activities": sorted(activities, key=lambda a: a["recorded_at"] or "", reverse=True)}


def attach_playtests(runs, document, registrations, viewer_port=None):
    """Expose operator addresses backed by exact completed engine-export inputs."""
    if not isinstance(registrations, list):
        return
    nodes = {node["@id"]: node for node in document["@graph"]}
    exported_indexes = {}
    for node in nodes.values():
        if "Artifact" in node["@type"] and Path(node.get("path", "")).name == "index.html":
            for activity in node.get("wasGeneratedBy", []):
                if node["@id"].startswith(activity + ":artifact:"):
                    exported_indexes.setdefault(activity, []).append(Path(node["path"]).parent)
    for link in registrations:
        if not isinstance(link, dict) or set(link) != {"activity", "url"}:
            continue
        address = link["url"]
        if not isinstance(address, str):
            continue
        match = re.fullmatch(r"http://(127\.0\.0\.1|localhost):([0-9]{1,5})(/[A-Za-z0-9_./~-]*)?", address)
        if not match or not 1 <= int(match[2]) <= 65535 or int(match[2]) == viewer_port:
            continue
        path = match[3] or "/"
        if any(part in {".", ".."} for part in path.split("/")) or "//" in path:
            continue
        work = nodes.get(link["activity"], {}) if isinstance(link["activity"], str) else {}
        if ("ExternalWork" not in work.get("@type", []) or work.get("status") != "complete" or
                work.get("label") not in {"Export three", "Export phaser"}):
            continue
        agent = work["@id"].split(":work:")[0] + ":agent:studio-engine-export"
        if (agent not in work.get("wasAssociatedWith", []) or
                "Agent" not in nodes.get(agent, {}).get("@type", []) or
                nodes[agent].get("label") != "studio-engine-export"):
            continue
        directories = exported_indexes.get(work["@id"], [])
        url_directory = path.removesuffix("index.html").strip("/")
        if not directories or (url_directory and not any(
                str(directory).endswith("/" + url_directory) or str(directory) == url_directory
                for directory in directories)):
            continue
        for run in runs:
            runtime = nodes.get(run["graph_id"] + ":runtime", {})
            if (run.get("status") == "ready" and "RuntimeProduct" in runtime.get("@type", []) and
                    runtime.get("wasGeneratedBy") == [run["graph_id"]] and
                    runtime.get("path") == run.get("runtime") and runtime["@id"] in work.get("used", [])):
                run.setdefault("playable_url", address)


def project_choices(document, projects):
    """Project cards use only pinned scenes and their actual runtime dependencies."""
    nodes = {node["@id"]: node for node in document["@graph"]}
    runs = {}
    for node in nodes.values():
        if "Run" in node["@type"]:
            for scope in node.get("partOf", []):
                runs.setdefault(scope, []).append(node)
    choices = []
    for member in projects:
        scope = graph.project_id(member)
        history = runs.get(scope, [])
        choice = {"id": scope, "name": member.name, "title": member.name,
                  "kind": None, "preview": None, "run_count": len(history)}
        for run in sorted(history, key=lambda n: (n["record"].get("started_at", ""),
                                                  n["record"].get("run_id", "")), reverse=True):
            record = run["record"]
            runtime = nodes.get(run["@id"] + ":runtime", {})
            scene = next((nodes[ident].get("snapshot", {}) for ident in run.get("used", [])
                          if ident.startswith(scope + ":") and "SceneRevision" in nodes[ident]["@type"]), {})
            if (record.get("status") != "ready" or not scene or
                    "RuntimeProduct" not in runtime.get("@type", []) or
                    runtime.get("path") != record.get("runtime") or
                    runtime.get("wasGeneratedBy") != [run["@id"]]):
                continue
            dependencies = {ident: nodes[ident] for ident in runtime.get("wasDerivedFrom", [])
                            if ident.startswith(scope + ":") and "Artifact" in nodes[ident]["@type"]}
            outputs = {asset["id"]: asset for asset in record.get("assets", [])}
            declarations = {asset["id"]: asset for asset in scene.get("assets", [])}
            kinds = set()
            for placement in scene.get("nodes", []):
                asset_id = placement.get("asset")
                declaration = declarations.get(asset_id, {})
                output = outputs.get(asset_id, {})
                placed = nodes.get(run["@id"] + ":placement:" + placement["id"], {})
                actual = [ident for ident in placed.get("placementOf", []) if ident in dependencies]
                if runtime["@id"] not in placed.get("partOf", []) or not actual:
                    continue
                producer = declaration.get("producer")
                if producer == "pixel-action-set":
                    kinds.add("2d")
                elif producer == "model-assets" and "effect" not in output.get("files", {}):
                    kinds.add("3d")
                else:
                    continue
                if choice["preview"] is not None:
                    continue
                files = output.get("files", {})
                source_ids = output.get("reuse", {}).get("artifacts")
                asset_pins = [node for ident, node in dependencies.items()
                              if (ident in source_ids if source_ids is not None else
                                  ident.startswith(run["@id"] + ":artifact:"))]
                if not any(nodes[ident] in asset_pins for ident in actual):
                    continue
                for role in ("preview", "sheet", "atlas"):
                    pin = next((node for node in asset_pins
                                if node.get("role") == role and node.get("path") == files.get(role)), None)
                    if pin and Path(pin["path"]).suffix.lower() in {".png", ".gif"}:
                        choice["preview"] = {"path": pin["path"], "sha256": pin["sha256"]}
                        break
            choice["title"] = scene.get("brief", {}).get("title") or scene.get("id") or member.name
            choice["kind"] = "mixed" if len(kinds) > 1 else next(iter(kinds), None)
            break
        choices.append(choice)
    return choices


def graph_signature(project, workspace):
    paths = []
    if workspace:
        paths.append(workspace)
        _, projects = registered_projects(workspace)
    else:
        projects = [project]
    for member in projects:
        root = member / ".game-studio"
        paths.append(root / "project.json")
        paths.extend(sorted((root / "runs").glob("*.jsonld")))
    signature = []
    for path in paths:
        try:
            info = path.lstat()
            signature.append((str(path), info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        except FileNotFoundError:
            signature.append((str(path), None))
    return signature


VIEW_ROLES = {"model", "preview", "review", "sheet", "atlas", "metadata", "receipt", "validation", "effect", "credits"}


class SnapshotCache:
    """One immutable HTTP projection per graph revision and process-liveness state."""
    def __init__(self, project, workspace, browse=False):
        self.project = project
        self.workspace = workspace
        self.browse = browse
        self.lock = threading.Lock()
        self.signature = None
        self.running = {}
        self.snapshot = None

    def get(self, viewer_port=None):
        with self.lock:
            signature = graph_signature(self.project, self.workspace) + [("viewer_port", viewer_port)]
            if self.signature == signature and all(live_process(pid) == live for pid, live in self.running.items()):
                return self.snapshot
            data = state(self.project, self.workspace, self.browse, viewer_port)
            scope = data["project_id"]
            allowed = set()
            for node in data["graph"]["@graph"]:
                if not scope or not node["@id"].startswith(scope + ":"):
                    continue
                role = node.get("role", "")
                if ("RuntimeProduct" in node["@type"] or ("Artifact" in node["@type"] and
                    (role in VIEW_ROLES or re.fullmatch(r"effect_\d+_(sheet|metadata)", role)))):
                    allowed.add((node.get("path"), node.get("sha256")))
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
            tag = '"' + hashlib.sha256(body).hexdigest() + '"'
            self.snapshot = (tag, body, frozenset(allowed))
            self.signature = signature
            self.running = {r.get("pid"): r["live"] for r in data["runs"] if r["status"] == "running"}
            return self.snapshot


def artifact(project, path, digest, allowed):
    if not path or not digest:
        raise ValueError("a graph artifact path and SHA-256 are required")
    if (path, digest) not in allowed:
        raise FileNotFoundError("unknown graph artifact")
    target = (project / path).resolve(strict=True)
    if not target.is_relative_to(project) or target.suffix not in {".json", ".glb", ".png", ".gif"}:
        raise FileNotFoundError("file is outside the viewer scope")
    body = target.read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise RuntimeError("파일이 기록된 리비전과 다릅니다.")
    return MIME[target.suffix], body


def handler(project, workspace, routes, browse=False):
    caches = {project: SnapshotCache(project, workspace, browse)}
    lock = threading.Lock()

    def select(query):
        selected = project
        ident = query.get("project", [None])[0]
        if ident:
            if not browse:
                raise FileNotFoundError("workspace browsing is disabled")
            _, projects = registered_projects(workspace)
            selected = next((p for p in projects if graph.project_id(p) == ident), None)
            if selected is None:
                raise FileNotFoundError("unknown workspace project")
        with lock:
            if selected not in caches:
                caches[selected] = SnapshotCache(selected, workspace, browse)
            return selected, caches[selected]

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, status, mime, body, tag=None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", POLICY)
            self.send_header("Cache-Control", "private, no-cache" if tag else "no-store")
            if tag:
                self.send_header("ETag", tag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") not in {f"{name}:{self.server.server_port}" for name in ("localhost", "127.0.0.1")}:
                self.send_error(403)
                return
            url = urlsplit(self.path)
            try:
                if url.path == "/api/state":
                    _, cache = select(parse_qs(url.query))
                    tag, body, _ = cache.get(self.server.server_port)
                    tags = {value.strip().removeprefix("W/") for value in self.headers.get("If-None-Match", "").split(",")}
                    if tag in tags or "*" in tags:
                        self.send_response(304)
                        self.send_header("ETag", tag)
                        self.send_header("Cache-Control", "private, no-cache")
                        self.end_headers()
                    else:
                        self.send_bytes(200, MIME[".json"], body, tag)
                    return
                elif url.path == "/artifact":
                    query = parse_qs(url.query)
                    selected, cache = select(query)
                    mime, body = artifact(selected, query.get("path", [""])[0], query.get("sha256", [""])[0], cache.get(self.server.server_port)[2])
                elif url.path in routes:
                    file = routes[url.path]
                    mime, body = MIME[file.suffix], file.read_bytes()
                elif url.path == "/favicon.ico":
                    self.send_bytes(204, "image/x-icon", b"")
                    return
                else:
                    raise FileNotFoundError("unknown route")
                self.send_bytes(200, mime, body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except FileNotFoundError:
                self.send_error(404)
            except (KeyError, TypeError, OSError, ValueError, RuntimeError) as exc:
                self.send_bytes(409, MIME[".json"], json.dumps({"error": str(exc)}).encode())
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, help="Optional workspace.json for the relation view")
    parser.add_argument("--browse-workspace", action="store_true",
                        help="Allow inspecting artifacts from all explicitly registered projects")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    if not project.is_dir():
        parser.error("project must be a directory")
    if args.browse_workspace and not args.workspace:
        parser.error("--browse-workspace requires --workspace")
    if args.workspace and project not in registered_projects(args.workspace)[1]:
        parser.error("project must be registered in this workspace")
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler(project, args.workspace, static_routes(), args.browse_workspace)) as server:
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
