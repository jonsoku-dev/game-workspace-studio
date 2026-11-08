#!/usr/bin/env python3
"""Copy the runtime, skill and executable example into a fresh plugin folder."""
import argparse
from pathlib import Path
import shutil


FILES = (
    ".codex-plugin/plugin.json", ".agents/plugins/marketplace.json",
    ".agents/skills/game-studio/SKILL.md", "README.md", "GRAPH.md",
    "INSTALL.md", "tools/install_workspace.py",
    "engines/godot/README.md", "engines/godot/export.py", "engines/godot/project.godot",
    "engines/godot/main.tscn", "engines/godot/main.gd", "engines/godot/studio_runtime.gd",
    "engines/godot/probe.gd", "engines/godot/export_presets.cfg", "engines/godot/compress_probe.cjs",
    "engines/godot/evidence/verification.json", "engines/godot/evidence/pck.json",
    "tools/scene.py", "tools/graph.py", "tools/workspace_graph.py", "tools/visualize.py",
    "visualizer/index.html", "visualizer/app.mjs", "visualizer/scene-view.mjs", "visualizer/style.css",
    "examples/forest-camp/scene.json",
    "examples/forest-camp/requests/lantern.json", "examples/forest-camp/requests/embers.json",
)


def stage(output):
    source = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("stage outside the source plugin")
    for name in FILES:
        path = source / name
        if not path.is_file() or path.resolve() != path:
            raise ValueError(f"missing regular plugin file: {name}")
    output.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(stage(args.out))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
