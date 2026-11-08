# Phaser action-set game

This is a real Phaser 3 Scene, WebGL where available with Phaser's Canvas fallback.
It makes the admitted action-set atlas playable as **Scout · Training clearing**:
move, face the amber target, strike three times, finish, restart. Arrow keys/A/D,
Space/R and large pointer controls are available. Clicking or activating Left/Right with
the keyboard nudges the actor 32 pixels; holding a pointer moves continuously. The sample authors its own
training layout; it does not import a 3D Studio scene or claim to convert GLBs.

`ActionActor` in `game.mjs` consumes action-set v1 metadata: individual atlas
rectangles, exact frame durations, looping/non-looping actions, actor pivots,
event time, contact anchor and effect anchor. The adapter requires one actor with idle/walk/attack and a non-looping attack
with either one contact effect event or an explicit contact frame and point. It
does not synthesize missing art. Export rejects incompatible data, drift and missing
SSOT pins before publishing. The supplied scout's event is at 320ms. Like any
render loop, a threshold is displayed on the first rendered frame at or after
that timestamp; this is not a sub-frame hardware timing guarantee.

## Explicit dependency setup

Phaser **3.90.0** is deliberately pinned to its stable Phaser 3 API. Phaser 4 is
a separate version line, not silently selected by this adapter.

From this directory, explicitly install the lockfile before exporting:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

That setup downloads npm packages. Export never installs or downloads anything.
For offline export, prepare this installation in advance and copy/cache both
`phaser` and its sibling `eventemitter3` packages; `npm ci --offline
--ignore-scripts --no-audit --no-fund` works only with an already populated npm
cache. `--phaser-package /prepared/node_modules/phaser` selects an installation.
Both the version and the runtime/license bytes must match `runtime-lock.json`.
Do not commit `node_modules` or the minified runtime.

From the workspace root:

```sh
python3 studio/engines/web/phaser/export.py \
  --project examples/scout-actions \
  --runtime builds/attack-contact/scene.runtime.json \
  --output /tmp/scout-phaser
python3 -m http.server 8937 --bind 127.0.0.1 --directory /tmp/scout-phaser
```

Open `http://127.0.0.1:8937`. The exported directory is portable and self-hosted:
Phaser, actor atlas, effect PNG/metadata, credits, licenses and provenance are
local. Serve via HTTP; browser module loading does not support opening this
bundle via `file:`. No CDN, cloud API, upload or runtime install is used.

The shared `studio/tools/runtime_inputs.py` admits successful graph-pinned
runtime products, checks path containment and content hashes, copies verified
bytes, and publishes to a fresh destination atomically. `game.json` preserves
the RuntimeProduct pin; `provenance.json` preserves Artifact IDs and hashes.
Phaser and embedded EventEmitter3 notices are included in `vendor/`;
`PHASER-BUNDLED-NOTICES.txt` also preserves the original third-party copyright
and license comments from the hash-pinned official unminified distribution and
the Matter.js license source. The multi-megabyte unminified library is used only
at export time and is not shipped in the bundle; pixelfx
license and NOTICE remain beside the effect and are linked in the credits.

Official provenance:

- [Phaser 3.90.0 release](https://phaser.io/download/release/v3.90.0)
- [Phaser MIT license](https://phaser.io/download/license)
- [Official npm tarball](https://registry.npmjs.org/phaser/-/phaser-3.90.0.tgz)

Validation:

```sh
python3 -m unittest discover -s studio/engines/web/phaser -p 'test_*.py' -v
node studio/engines/web/phaser/test_timing.mjs
node --check studio/engines/web/phaser/game.mjs
```

`evidence/browser.json` records the observed Stagehand gameplay, local resource
requests and responsive inspection. This miniature demonstrates engine support;
it is not a full game-content pipeline, audio implementation or hardware/mobile
certification.

## Configured first slice and browser evidence

The immutable runtime may pin `playtest: {mode: "land_hits", hits_to_win: 5,
 target_x: 650, target_y: 300, contact_frame: 3, at_px: [46, 25]}`.
Hits are integers 1–100; target coordinates use the 960×540 game space.
`contact_frame` is zero based; its timestamp is the sum of preceding attack
frame durations. An explicit marker controls damage even when an attack FX
event exists: FX begins at its own `start_ms`, while damage happens once at the
contact marker. This allows charge → travel → impact sequences to begin before
contact. Without an explicit marker, the legacy attack FX event remains the
contact event. Without FX, an explicit marker is required. `at_px` is the actual
contact point in the actor frame, transformed by pivot, scale and facing.
The same marker fields may live on `metadata.actions.attack`. The contact point
uses `playtest.at_px`, then `metadata.actions.attack.at_px`, then the attack FX
contact point. FX retains its own timing and visual anchor. Both marker and
registered FX data are independently validated. No effect asset is required for
local authored actions. Unsupported modes fail export. Runtime `brief.title`
and `brief.goal` explain the chosen objective; these are text, never code.
Omitted rules preserve the original three-hit training game.

Use configured Stagehand against a localhost export, activate Strike while out
of range, move with the normal Left/Right controls, strike until the configured
win, and activate Restart. Observe each state from
`window.scoutGame.scene.scenes[0]`: `{hits, finished, x: actor.x, contactEvents}`.
Save these as `{miss, win, reset}` and assess with:

```
python3 studio/tools/playcheck.py --export /tmp/scout-phaser --run-id RUN_ID \
  --observations /tmp/observations.json --output /tmp/playcheck.json
```

The assessor does not launch a browser or manufacture observations. It emits
explicit pass/fail for miss, contact timing (first render within 100ms of marker),
configured win and reset, pinning every exported byte and the runtime SHA-256.
`verify(report, export)` recomputes both hashes and criteria. Record the report
through the project graph's record path for review. This is a trace of observed
browser behavior, not cryptographic attestation, artistic acceptance or proof
that arbitrary prose was converted into game logic.


For an actual fresh browser execution against a graph-registered export:

```
python3 studio/tools/playcheck.py run --project PROJECT --export play/EXPORT
```

This reads the enabled local Stagehand MCP command from Codex configuration,
snapshots and hash-verifies the exact admitted inventory (including its receipt)
before serving those immutable bytes on a temporary loopback port. The server
accepts only its loopback Host names, returns 404 for unknown paths, and never
lists directories or reads files during requests. Later disk edits, inserted
files and symlink swaps cannot change served bytes. It invokes only MCP `run`,
uses normal button controls and reads game observations. No state is injected.
Every served file is fetched and SHA-256 checked in the browser. Reports under
`checks/` use project-relative export paths and graph-linked export/browser
activities, so relocating the complete project retains the evidence. The
browser activity uses the exact RuntimeProduct and engine receipt and generates
the immutable report. Imported observations have `driver: observation-import`;
only this execution route uses `stagehand-mcp`. Review independently checks all
export inputs, inventory, graph provenance and report hashes. Facing away must
miss; for goals above one hit the penultimate hit must remain unfinished. When
FX begins before an explicit contact marker, the report also checks FX onset
with no damage and the actual renderer frame at first contact against its
frame durations. This is runtime frame evidence, not a human visual-quality
judgment.
The configured MCP browser and Python 3.11+ must be available; failures do not
imply acceptance. Configuration comes from `CODEX_HOME/config.toml`, falling back
to `~/.codex/config.toml`.
