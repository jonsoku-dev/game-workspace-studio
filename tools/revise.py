#!/usr/bin/env python3
"""Create a local candidate in the source Studio project without editing its ready run."""
import argparse
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import uuid

import graph
import scene


def digest(data):
    return hashlib.sha256(data).hexdigest()


def point(value):
    if not isinstance(value, list) or len(value) != 2 or any(type(x) is not int for x in value):
        raise ValueError("anchor points require two integer pixels")
    return value


def png(data, size):
    from PIL import Image
    if len(data) > 16_777_216:
        raise ValueError("PNG exceeds 16 MiB")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != tuple(size):
            raise ValueError("replacement and source PNG dimensions must match cell_size")
        image.load()
        return image.convert("RGBA")


def pinned_request(project, nodes, run, asset_id, seen=None):
    seen = set() if seen is None else seen
    key = (run["@id"], asset_id)
    if key in seen:
        raise ValueError("cyclic reuse")
    seen.add(key)
    original_scene = next(nodes[x]["snapshot"] for x in run["used"] if "SceneRevision" in nodes[x]["@type"])
    asset = next(a for a in original_scene["assets"] if a["id"] == asset_id)
    if "reuse" in asset:
        reused = next(a for a in run["record"]["assets"] if a["id"] == asset_id)["reuse"]
        return pinned_request(project, nodes, nodes[reused["run"]], reused["asset"], seen)
    executed = nodes[run["@id"] + ":step:" + asset_id + ":request"]
    request = next(nodes[x] for x in executed["wasDerivedFrom"] if "RequestRevision" in nodes[x]["@type"])
    raw = base64.b64decode(request["snapshotBase64"], validate=True)
    if digest(raw) != request["sha256"]:
        raise ValueError("request snapshot hash mismatch")
    sources = {}
    specification = json.loads(raw)
    executed_specification = json.loads(base64.b64decode(executed["snapshotBase64"], validate=True))
    for ident in request.get("wasDerivedFrom", []):
        pin = nodes[ident]
        if asset["producer"] == "model-assets" and "source_blend" in specification:
            relative = Path("_sources") / (pin["sha256"] + ".blend")
            staged = scene.local_path(project, str(Path(executed["path"]).parent / executed_specification["source_blend"]))
            specification["source_blend"] = str(relative)
        else:
            relative = Path(pin["path"]).relative_to(Path(request["path"]).parent)
            staged = scene.local_path(project, str(Path(executed["path"]).parent / relative))
        candidates = [staged, scene.local_path(project, pin["path"])]
        data = None
        for path in candidates:
            if path.is_file():
                observed = path.read_bytes()
                if len(observed) == pin["byteCount"] and digest(observed) == pin["sha256"]:
                    data = observed
                    break
        if data is None:
            raise ValueError("pinned source bytes unavailable or changed: " + pin["path"])
        sources[str(relative)] = data
    if asset["producer"] == "model-assets" and "source_blend" in specification:
        raw = (json.dumps(specification, ensure_ascii=False, indent=2) + "\n").encode()
    return asset, request, raw, sources


def change_request(original, patch, patch_path, sources):
    if (not isinstance(patch, dict) or set(patch) != {"schema_version", "actions"}
            or type(patch["schema_version"]) is not int or patch["schema_version"] != 1
            or not isinstance(patch["actions"], dict) or not patch["actions"]):
        raise ValueError("patch requires schema_version 1 and nonempty actions")
    result = copy.deepcopy(original)
    replacements = {}
    mapping = {}
    for name, edit in patch["actions"].items():
        if name not in original["actions"] or not isinstance(edit, dict) or set(edit) - {"frames", "event_frames", "contact_frame"}:
            raise ValueError("patch names an unknown action or field")
        if "contact_frame" in edit and name != "attack":
            raise ValueError("contact_frame selects the attack playtest marker only")
        entries = edit.get("frames")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError("selected action needs a full list of 1..64 frames")
        frames = []
        mapping[name] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or set(entry) - {"source", "duration_ms", "replacement", "sha256", "anchor"}:
                raise ValueError("unknown frame patch field")
            old = entry.get("source")
            if type(old) is not int or not 0 <= old < len(original["actions"][name]["frames"]):
                raise ValueError("source must be an existing zero-based frame index")
            frame = copy.deepcopy(original["actions"][name]["frames"][old])
            value = entry.get("duration_ms", frame["duration_ms"])
            if type(value) is not int or not 1 <= value <= 60000:
                raise ValueError("duration_ms must be in 1..60000")
            frame["duration_ms"] = value
            data = sources[frame["path"]]
            if "replacement" in entry:
                path = scene.local_path(patch_path.parent, entry["replacement"])
                data = path.read_bytes()
                if not isinstance(entry.get("sha256"), str) or digest(data) != entry["sha256"]:
                    raise ValueError("replacement requires its exact sha256")
            elif "sha256" in entry:
                raise ValueError("sha256 requires a replacement")
            image = png(data, original["cell_size"])
            if "anchor" in entry:
                from PIL import Image
                anchor = entry["anchor"]
                if not isinstance(anchor, dict) or set(anchor) != {"from_px", "to_px"}:
                    raise ValueError("anchor requires from_px and to_px")
                start, stop = point(anchor["from_px"]), point(anchor["to_px"])
                if any(not 0 <= p <= bound for pnt in (start, stop) for p, bound in zip(pnt, image.size)):
                    raise ValueError("anchor must be within the cell edges")
                dx, dy = stop[0] - start[0], stop[1] - start[1]
                bbox = image.getchannel("A").getbbox()
                if bbox and (bbox[0] + dx < 0 or bbox[1] + dy < 0 or bbox[2] + dx > image.width or bbox[3] + dy > image.height):
                    raise ValueError("anchor translation would clip opaque pixels")
                shifted = Image.new("RGBA", image.size)
                shifted.paste(image, (dx, dy))
                stream = io.BytesIO()
                shifted.save(stream, format="PNG")
                data = stream.getvalue()
            if "replacement" in entry or "anchor" in entry:
                filename = f"revisions/{name}-{index}-{digest(data)}.png"
                replacements[filename] = data
                frame["path"] = filename
            frames.append(frame)
            mapping[name].append(copy.deepcopy(entry))
        if sum(f["duration_ms"] for f in frames) > 120000:
            raise ValueError("action duration exceeds 120000ms")
        result["actions"][name]["frames"] = frames
        expected = {str(i) for i, e in enumerate(original.get("events", [])) if e["action"] == name}
        event_frames = edit.get("event_frames", {})
        if not isinstance(event_frames, dict) or set(event_frames) != expected:
            raise ValueError("event_frames must explicitly map every selected-action event index, or null to remove")
        for ident, target in event_frames.items():
            if target is not None and (type(target) is not int or not 0 <= target < len(frames)):
                raise ValueError("event target must be a new frame index or null")
            result["events"][int(ident)]["frame"] = target
    if max(len(a["frames"]) for a in result["actions"].values()) * original["cell_size"][0] * original["cell_size"][1] * 6 > 16_777_216:
        raise ValueError("candidate atlas exceeds pixel budget")
    result["events"] = [e for e in result.get("events", []) if e["frame"] is not None]
    return result, replacements, mapping


def evidence(original, candidate, sources, folder, mapping):
    from PIL import Image, ImageDraw
    report = {"schema_version": 1, "visual_acceptance": "unreviewed", "actions": {},
              "measurement_limits": "Alpha bounds and bottommost opaque pixels are silhouette measures, not anatomical feet. GIF timing rounds to 10ms; JSON durations are authoritative. GIFs show actor poses, not composite effects. Native 1x PNGs retain source colors; GIF uses a palette."}
    for name in original["actions"]:
        rows = []
        values = {}
        for label, request in (("before", original), ("after", candidate)):
            action = request["actions"][name]
            images = [png(sources[f["path"]], request["cell_size"]) for f in action["frames"]]
            metrics = []
            for image in images:
                alpha = image.getchannel("A")
                bounds = alpha.getbbox()
                bottom = None
                if bounds:
                    xs = [x for x in range(image.width) if alpha.getpixel((x, bounds[3] - 1))]
                    bottom = [min(xs), max(xs), bounds[3] - 1]
                metrics.append({"alpha_bounds": bounds, "bottom_opaque_span": bottom})
            values[label] = {"durations_ms": [f["duration_ms"] for f in action["frames"]],
                             "total_ms": sum(f["duration_ms"] for f in action["frames"]),
                             "sha256": [digest(sources[f["path"]]) for f in action["frames"]], "frames": metrics,
                             "contacts": [{"event": i, "frame": e["frame"], "start_ms": sum(f["duration_ms"] for f in action["frames"][:e["frame"]]), "at_px": e.get("at_px", request["pivot_px_from_top_left"])} for i, e in enumerate(request.get("events", [])) if e["action"] == name]}
            bottoms = [m["bottom_opaque_span"] for m in metrics]
            values[label]["bottom_span_steps_px"] = [
                [b[0] - a[0], b[1] - a[1], b[2] - a[2]] if a and b else None
                for a, b in zip(bottoms, bottoms[1:])]
            values[label]["loop_bottom_span_step_px"] = (
                [bottoms[0][i] - bottoms[-1][i] for i in range(3)]
                if action["loop"] and bottoms[0] and bottoms[-1] else None)
            rows.append(images)
            if name in mapping:
                canvases = []
                for image in images:
                    canvas = Image.new("RGBA", image.size, "#525c59")
                    canvas.alpha_composite(image)
                    canvases.append(canvas.convert("RGB"))
                canvases[0].save(folder / f"{name}-{label}-1x.gif", save_all=True, append_images=canvases[1:],
                                 duration=[max(10, round(f["duration_ms"] / 10) * 10) for f in action["frames"]],
                                 loop=0, disposal=2, optimize=False)
        values["changed"] = values["before"] != values["after"]
        values["mapping"] = mapping.get(name)
        report["actions"][name] = values
        if name in mapping:
            w, h = original["cell_size"]
            sheet = Image.new("RGBA", (max(map(len, rows)) * w, 2 * (h + 18)), "#525c59")
            draw = ImageDraw.Draw(sheet)
            for row, images in enumerate(rows):
                for i, image in enumerate(images):
                    sheet.alpha_composite(image, (i * w, row * (h + 18) + 18))
                    draw.text((i * w, row * (h + 18)), f"{i}:{values['before' if row == 0 else 'after']['durations_ms'][i]}", fill="white")
            sheet.save(folder / f"{name}-contact.png")
    return report


def revise(project, base, asset_id, patch_path, output, *, build=False, timeout=300):
    project, patch_path = project.resolve(), patch_path.resolve()
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("timeout must be positive")
    folder = scene.local_path(project, output)
    if folder.exists() or folder.is_symlink():
        raise ValueError("output exists; retry with a fresh --out path")
    relative_folder = str(folder.relative_to(project))
    scene_name = relative_folder + "/scene.json"
    build_output = relative_folder + "/build/candidate"
    nodes = {n["@id"]: n for n in graph.export_graph(project)["@graph"]}
    runs = [n for n in nodes.values() if "Run" in n["@type"] and (n["@id"] == base or n.get("record", {}).get("run_id") == base)]
    if len(runs) != 1 or runs[0].get("status") != "ready":
        raise ValueError("base must be an exact ready run in this project")
    run = runs[0]
    original_scene = next(nodes[x]["snapshot"] for x in run["used"] if "SceneRevision" in nodes[x]["@type"])
    candidate_scene = copy.deepcopy(original_scene)
    if not any(a["id"] == asset_id and a["producer"] == "pixel-action-set" for a in candidate_scene["assets"]):
        raise ValueError("asset must select a pixel-action-set in the base scene")
    patch_bytes = patch_path.read_bytes()
    patch = json.loads(patch_bytes)
    files = {"patch.json": patch_bytes}
    used = [run["@id"]]
    scene_id = next(x for x in run["used"] if "SceneRevision" in nodes[x]["@type"])
    used.append(scene_id)
    derivations = {"scene.json": [scene_id]}
    report = None
    for asset in candidate_scene["assets"]:
        declaration, request_pin, raw, sources = pinned_request(project, nodes, run, asset["id"])
        used.extend([request_pin["@id"]] + request_pin.get("wasDerivedFrom", []))
        request = json.loads(raw)
        if asset["id"] == asset_id:
            original = copy.deepcopy(request)
            request, replacements, mapping = change_request(request, patch, patch_path, sources)
            sources.update(replacements)
            raw = (json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
            report = (original, request, sources, mapping)
        prefix = f"inputs/{asset['id']}/"
        files[prefix + "request.json"] = raw
        derivations[prefix + "request.json"] = [request_pin["@id"]]
        for path, data in sources.items():
            files[prefix + path] = data
            derivations[prefix + path] = [ident for ident in request_pin.get("wasDerivedFrom", [])
                if nodes[ident]["sha256"] == digest(data)]
        asset.pop("reuse", None)
        asset["request"] = relative_folder + "/" + prefix + "request.json"
    playtest = candidate_scene.get("playtest", {})
    attack_edit = patch["actions"].get("attack")
    if attack_edit and ("contact_frame" in playtest or "contact_frame" in attack_edit):
        old_marker = playtest.get("contact_frame")
        matches = [i for i, f in enumerate(attack_edit["frames"]) if f["source"] == old_marker]
        marker = attack_edit.get("contact_frame", matches[0] if len(matches) == 1 else None)
        if type(marker) is not int or not 0 <= marker < len(attack_edit["frames"]):
            raise ValueError("removed or duplicated playtest contact requires explicit attack.contact_frame")
        candidate_scene.setdefault("playtest", {})["contact_frame"] = marker
    files["scene.json"] = (json.dumps(candidate_scene, ensure_ascii=False, indent=2) + "\n").encode()
    folder.mkdir(parents=True, exist_ok=False)
    key = "revise-" + uuid.uuid4().hex
    try:
        for name, data in files.items():
            target = scene.local_path(folder, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        review = evidence(report[0], report[1], report[2], folder, report[3])
        review.update(base_run=run["@id"], asset=asset_id, patch_sha256=digest(patch_bytes),
                      playtest_before=original_scene.get("playtest"), playtest_after=candidate_scene.get("playtest"))
        scene.write_json(folder / "review.json", review)
        scene.load_scene(project, scene_name)
        scene_artifact = graph.project_id(project) + ":work:" + key + ":artifact:" + graph._digest(scene_name.encode())
        next_step = [sys.executable, str(Path(scene.__file__).resolve()), "build", "--project", str(project),
                     "--scene", scene_name, "--source-artifact", scene_artifact, "--out", build_output]
        result = {"schema_version": 1, "status": "prepared", "candidate_project": str(project), "candidate_folder": str(folder),
                  "scene": str(folder / "scene.json"), "review": str(folder / "review.json"),
                  "next_command": shlex.join(next_step), "visual_acceptance": "unreviewed"}
        scene.write_json(folder / "result.json", result)
        generated = [{"path": str(p.relative_to(project)), "sha256": digest(p.read_bytes()), "wasDerivedFrom": derivations.get(str(p.relative_to(folder)), [])}
                     for p in sorted(folder.rglob("*")) if p.is_file()]
        result["graph_id"] = graph.record_work(project, {"id": key, "label": "Prepare local action candidate", "agent": "studio-revise",
            "status": "complete", "used": list(dict.fromkeys(used)), "generated": generated,
            "verification": {"passed": True, "checks": ["Pinned source hashes and sizes", "Explicit event frame mapping", "Same-project candidate scene input validation", "PNG dimensions and silhouette measurements; visual acceptance unreviewed"]}})
        if build:
            try:
                built = scene.build(project, build_output, timeout, scene_name, scene_artifact)
                result.update(status=built["status"], run_id=built["run_id"], files=built["files"])
                result["run"] = graph.project_id(project) + ":run:" + built["run_id"]
            except Exception as exc:
                raise ValueError("candidate build failed; A is preserved; inspect recorded failure and retry with a fresh --out") from exc
        return result
    except Exception:
        graph.record_work(project, {"id": key + "-error", "label": "Local candidate revision failed; retry with a fresh output", "agent": "studio-revise",
                                   "status": "error", "used": list(dict.fromkeys(used))})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--patch", required=True, type=Path)
    parser.add_argument("--out", required=True)
    parser.add_argument("--build", action="store_true", help="Build candidate B as a new run in the original project")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(revise(args.project, args.base, args.asset, args.patch, args.out, build=args.build, timeout=args.timeout)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print(json.dumps({"status": "error", "reason": str(exc) or "Pinned base inputs are unavailable"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
