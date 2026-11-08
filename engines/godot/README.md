# Godot 4 offline adapter and Ember Run sample

`export.py` copies admitted Studio v1 runtime products and their selected files into a new local Godot project. It reads the canonical Studio graph, requires a matching successful runtime pin, follows runtime derivation and placement links (including reused artifacts), checks SHA-256/byte counts, validates containment, and publishes through a temporary sibling directory. It refuses existing destinations. The source producer packages and build outputs stay untouched.

`studio_runtime.gd` imports self-contained GLBs with `GLTFDocument`, retains Studio meter/Y-up transforms and parent attachment, and animates the mesh-particle recipe with native `Node3D`/`MeshInstance3D` instances. GLBs retain their exact pinned bytes under a `.glb.bytes` transport suffix and load through `append_from_buffer`; Godot export cannot replace them with imported `.scn` resources. It probes compiled and raw GLBs independently, checks drawable triangles, and falls back to raw when compiled decoding fails. These 3D effects do not use billboards. The authored **2D** scout and hit effect use `Sprite3D` atlas regions with exact frame durations and authored 320ms contact trigger.

Ember Run is a small integration sample: WASD movement within the arena, Space to strike crystals within 0.85m, three crystals to complete, R to reset. It binds `camp-lantern`, `camp-embers`, `scout`, the `idle`/`walk`/`attack` actions, and the first attack effect. Its three target meshes and game rules are sample code, not generated producer output. The reusable importer is separate from those fixed sample bindings. Only the first forest-camp product and second scout-actions product drive this sample.

## Native interaction feedback

The sample keeps WASD / Space / R controls and adds **P** pause, **F** optional accents A/B, **M** sound (muted until explicitly enabled), and **V** reduced motion. `--no-accents` and `--reduced-motion` after `--` set the initial accessibility/comparison state. Sound also follows the F accents switch; muting either switch stops the current cue.

The HUD always reports strike acceptance, out-of-reach misses, attempts during a swing or after completion, crystal collection, completion, restart, and pause/resume. Optional accents add a small scout pulse on collection/completion/restart, walking bob only during actual movement, and quiet native synthesized tones for footsteps and those events. Reduced motion removes the added bob/pulse; the original authored sprite/attack animation and imported ember particles remain. There are no screen flashes, added assets, dependencies, or invented restore mechanics. Pause freezes gameplay, attack timing and imported particles; press P to resume before restarting.

Headless `--verify` also checks actual event dispatch, pause, A/B, reduced motion, default mute, native audio dispatch and stopping audio on mute. These checks prove engine state and routing; listening quality, visual comfort and physical keyboard acceptance require a windowed playtest.

## Run locally

From the workspace root, using Python 3.10+ and Godot **4.5.1**:

```sh
python3 studio/engines/godot/export.py \
  --source examples/forest-camp builds/lantern-embers-final/scene.runtime.json \
  --source examples/scout-actions builds/attack-contact/scene.runtime.json \
  --output /tmp/ember-run
GODOT=/tmp/studio-godot-4.5.1/Godot.app/Contents/MacOS/Godot
"$GODOT" --headless --path /tmp/ember-run --editor --import --quit
"$GODOT" --path /tmp/ember-run
```

The resulting project is offline and portable: `products.json` uses namespaced `res://` paths, `provenance.json` retains project-relative source paths and original graph artifact IDs/hashes, and pixelfx LICENSE/NOTICE and scout credits are copied with the selected files. Copy the whole output folder, not only `project.godot`. The included export preset also produces a PCK, tested below. A PCK needs a compatible Godot binary; it is not a self-contained executable.

## Focused checks

```sh
python3 -m unittest discover -s studio/engines/godot -p 'test_*.py' -v
"$GODOT" --headless --path /tmp/ember-run -- --verify
"$GODOT" --path /tmp/ember-run -- --verify
```

`--verify` sends Godot `Input.action_press/release` events through the same physics/input loop used by keyboard controls. It checks movement, a distant miss, no early collection, contact at the authored trigger, visible hit FX, moving native particles, original parent attachment, goal completion and reset. Visible mode also saves actual viewport `start.png`, `contact.png`, `completed.png`; both write `verification.json` to `user://` by default. Add `--evidence-dir=/tmp/ember-proof` after `--` for a chosen local output directory. This is engine input automation, not physical keyboard or human playtesting. Gameplay verification uses explicit checks that also run in exported packs. It hashes packaged GLB/JSON/license/credit bytes against the source pins; PNGs are Godot-imported texture resources and are checked for successful texture loading rather than original PNG byte equality.

`probe.gd` independently reports GLB decoding and actual mesh/triangle counts:

```sh
"$GODOT" --headless --path /tmp/ember-run --script res://probe.gd -- \
  /tmp/ember-run/products/0/lantern/model.glb.bytes \
  /tmp/ember-run/products/0/lantern/model.web.glb.bytes
```

The existing example compiled GLBs contain no `EXT_meshopt_compression`; they cannot prove meshopt decoding. To reproduce the separate required-extension probe without changing producers, install test-only packages in `/tmp`:

```sh
npm install --prefix /tmp/studio-meshopt-probe --ignore-scripts --no-audit --no-fund \
  @gltf-transform/core@4.5.0 @gltf-transform/extensions@4.5.0 meshoptimizer@0.25.0
node studio/engines/godot/compress_probe.cjs /tmp/studio-meshopt-probe \
  /tmp/ember-run/products/0/lantern/model.glb.bytes /tmp/studio-meshopt-probe/lantern.meshopt.glb
"$GODOT" --headless --path /tmp/ember-run --script res://probe.gd -- \
  /tmp/studio-meshopt-probe/lantern.meshopt.glb
"$GODOT" --headless --path /tmp/ember-run --script res://probe.gd -- --fallback \
  /tmp/studio-meshopt-probe/lantern.meshopt.glb /tmp/ember-run/products/0/lantern/model.glb.bytes
```

The tested official Godot 4.5.1 loader **rejects required meshopt compression**. Its engine error is expected in those negative probes. A decoder extension would be needed to load it directly; this adapter uses the pinned raw GLB instead. No decoder dependency is silently installed.

## Export and run a PCK

The `Offline PCK` preset includes original GLB byte payloads, JSON metadata, source pins, credits and LICENSE/NOTICE, along with Godot-imported PNG textures. No export template download is needed to produce this data pack:

```sh
mkdir -p /tmp/ember-dist
"$GODOT" --headless --path /tmp/ember-run --export-pack 'Offline PCK' /tmp/ember-dist/ember-run.pck
cd /tmp/ember-dist
"$GODOT" --main-pack /tmp/ember-dist/ember-run.pck
"$GODOT" --headless --main-pack /tmp/ember-dist/ember-run.pck -- --verify --evidence-dir=/tmp/ember-pck-proof
```

The argument order is deliberate: Godot options (`--headless`, `--main-pack PATH`) precede the separator **`--`**; sample arguments (`--verify`, `--evidence-dir=PATH`) follow it. Use the visible variant without `--headless` to capture the three viewport screenshots. Running from the distribution directory needs only the PCK plus a compatible engine binary, not the source project.

Actual distributable test: `/tmp/studio-ember-pck/ember-run.pck` launched with `--main-pack` from a directory containing no `project.godot` or source assets, while the export source project directory was temporarily renamed out of the way. The visible loop passed movement, contact timing, completion/reset, 24 native mesh particles and packaged source-byte checks. See `evidence/pck.json` and `evidence/pck-visible.log` for its checksum, size, commands and report. The engine remains the separately downloaded official Godot app in `/tmp`; no signed or self-contained `.app` export is claimed.

## Observed evidence (2026-11-08)

[evidence/verification.json](evidence/verification.json) and the adjacent concise engine logs record the actual results:

- macOS arm64, Apple M4 Pro, Godot `4.5.1.stable.official.f62fdbde1`; visible OpenGL Compatibility through Metal 90.5.
- Official macOS universal zip SHA-256: `65c27959d02aaacfc131ec7ecb90179ba8045200cb02982bf2be96d117010b8a`, matched the official GitHub release API asset digest before execution. Engine downloaded/extracted under `/tmp`; no user-wide install.
- Raw lantern: 54 mesh instances / 23,160 triangles; compiled lantern: 9 / 23,160. Raw and compiled ember seed: 1 / 8. Runtime: 24 native mesh-particle instances attached to lantern.
- Headless and visible input loops passed. A separate actual Studio `builds/reuse-smoke/scene.runtime.json` referencing original forest-camp artifacts exported and passed both loops. Five Python checks cover copies/pins/licenses, drift rejection with no output, escaping paths/cycles, and a linked-artifact reuse fixture.
- The source scene transforms and authored textures/GLBs are imported. This is not material-equivalence certification: Godot/glTF transmission/emissive appearance can differ from Three/Blender.

This is a useful engine integration sample, not a production game or a 5/5 art/gameplay acceptance result. It has no authored soundtrack, enemy AI, physics collisions, controller/touch support, save system, self-contained executable export, cross-platform or physical-input certification.

Engine sources: [Godot 4.5.1 official release](https://github.com/godotengine/godot/releases/tag/4.5.1-stable), [official build assets and digest](https://api.github.com/repos/godotengine/godot-builds/releases/tags/4.5.1-stable), [Godot GLTFDocument API](https://docs.godotengine.org/en/4.5/classes/class_gltfdocument.html). Compression probe follows [glTF Transform EXTMeshoptCompression](https://gltf-transform.dev/modules/extensions/classes/EXTMeshoptCompression). Godot is MIT licensed; no engine binary is vendored. Imported local pixelfx material retains its own copied attribution/license files.

## Feedback validation (2026-11-09)

The updated adapter passed the five Python export regressions and Godot 4.5.1 headless gameplay/feedback verification, including imported geometry and 14 packaged byte pins. The normal exported project's independent `probe.gd` and exported PCK were also exercised headlessly. Current-run artifacts live under `/tmp/ember-feedback-proof`, `/tmp/ember-feedback-native`, and `/tmp/ember-feedback-dist`; they are local evidence, not checked-in release artifacts. No new windowed visual/listening acceptance is claimed.
