#!/usr/bin/env python3
"""Copy the runtime, skill and executable example into a fresh plugin folder."""
import argparse
from pathlib import Path
import shutil


FILES = (
    ".codex-plugin/plugin.json", ".agents/plugins/marketplace.json",
    ".agents/skills/game-studio/SKILL.md", "README.md", "GRAPH.md", "FEEDBACK.md",
    "INSTALL.md", "tools/install_workspace.py",
    "tools/character.py", "tools/start.py", "tools/revise.py", "tools/review.py", "tools/playcheck.py", "tools/playcheck_browser.py", "tools/courier_playcheck.py",
    "starter/2d/master.png", "starter/2d/motion.json", "starter/2d/LICENSE.txt", "starter/2d/NOTICE.md",
    "starter/3d/scene.json", "starter/3d/requests/lantern.json", "starter/3d/requests/embers.json",
    "starter/identity/LOGO.md", "starter/identity/a-moon-strike.svg",
    "starter/identity/b-target-cut.svg", "starter/identity/c-robot-guard.svg",
    "visualizer/compare.mjs", "visualizer/compare-messages.mjs",
    "tools/runtime_inputs.py", "tools/export_game.py", "engines/HTML-ENGINES.md",
    "engines/web/README.md", "engines/web/export.py", "engines/web/index.html",
    "engines/web/feedback.mjs", "engines/web/game-state.mjs", "engines/web/game.mjs", "engines/web/style.css",
    "engines/web/three-lock.json", "engines/web/MESHOPT-LICENSE.txt", "engines/web/evidence/meshopt.json", "engines/web/evidence/browser.json", "engines/web/evidence/mobile-win.jpg",
    "engines/web/phaser/README.md", "engines/web/phaser/export.py", "engines/web/phaser/index.html",
    "engines/web/phaser/game.mjs", "engines/web/phaser/timing.mjs", "engines/web/phaser/trial.mjs", "engines/web/phaser/cue-sheets.mjs", "engines/web/phaser/style.css",
    "engines/web/phaser/package.json", "engines/web/phaser/package-lock.json", "engines/web/phaser/runtime-lock.json",
    "engines/web/phaser/evidence/browser.json", "engines/web/phaser/evidence/notice-nudge-browser.json",
    "engines/unity/evidence.json", "engines/unity/README.md", "engines/unity/export.py", "engines/unity/convert.py",
    "engines/unity/Assets/StudioGame.cs", "engines/unity/Assets/StudioRuntime.cs", "engines/unity/Assets/Editor/StudioBatch.cs",
    "engines/godot/README.md", "engines/godot/export.py", "engines/godot/project.godot",
    "engines/godot/main.tscn", "engines/godot/main.gd", "engines/godot/studio_runtime.gd",
    "engines/godot/probe.gd", "engines/godot/export_presets.cfg", "engines/godot/compress_probe.cjs",
    "engines/godot/evidence/verification.json", "engines/godot/evidence/pck.json",
    "tools/scene.py", "tools/graph.py", "tools/workspace_graph.py", "tools/visualize.py",
    "visualizer/index.html", "visualizer/app.mjs", "visualizer/scene-view.mjs", "visualizer/style.css",
    "visualizer/i18n.mjs", "visualizer/shell-i18n.mjs", "visualizer/app-messages.mjs", "visualizer/view-messages.mjs",
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
