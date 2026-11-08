# Offline Unity adapter

Unity is the third integration target after web and Godot. This adapter exports a standalone **source project** for Unity **6000.0.60f1**, built-in render pipeline. It uses only Unity's native Mesh, Material, Sprite, SpriteRenderer and Transform APIs. No remote Unity package, glTF decoder, paid plugin, CDN, API key or upload is needed. The manifest lists only editor-bundled imageconversion/jsonserialize/imgui modules. The Unity Editor and its valid licence remain prerequisites.

Local checks on 2026-11-08 found no Unity Editor or Hub in `/Applications`, no Spotlight `Unity.app` result, and no local Unity support directory. No Unity install or licence activation was attempted. **Unity C# compilation, native import, Editor playback, batch verification and visual/material acceptance have not run.** Python and Blender results below are separate evidence.

From the workspace root, with Python 3.10+ and local Blender **5.2.1 LTS**:

```sh
python3 studio/engines/unity/export.py \
  --source examples/forest-camp builds/lantern-embers-final/scene.runtime.json \
  --source examples/scout-actions builds/attack-contact/scene.runtime.json \
  --output /tmp/studio-unity-offline
python3 -m unittest discover -s studio/engines/unity -p 'test_*.py' -v
```

The normal exporter entry reads `studio/tools/runtime_inputs.py` admission. It requires successful SSOT runtime pins and verifies every selected file's SHA-256. It follows linked reused artifacts, copies only admitted files, preserves original GLBs and licence/NOTICE/credits, refuses existing output and publishes atomically. Export does not mutate producer inputs. Parent orchestration records this code work and actual validation in the project graph.

Open the exported folder as a Unity project using an already installed, licensed matching Editor. Choose **Studio > Create Offline Scene**, then Play. The menu creates an observation scene containing the original local placements, models, scout attack and attached native mesh particles. This menu remains a read-only integration preview. `StudioRuntime.Load()` is the reusable component entry. `StudioSprite.Play(name)` selects any of the six supplied clips. Play rebuilds native objects from the local payload, so no serialized generated mesh dependency is required. The created scene is intentionally transient. Run the menu again after reopening the project.

For the opt-in playable vertical slice, choose **Studio > Create Playable Sample**, then Play and focus the Game view. WASD moves on the XZ arena, Space starts the authored attack, and R resets. Collect three native mesh crystals to win. Movement pauses while attacking; a crystal within 0.85m is collected only when the attack reaches the original event time, 320ms for this scout. Distant attacks miss. Targets and goal rules are sample code, not producer output. The menu adjusts the preview camera only for this sample.

`StudioGame.Step` drives both keyboard and batch acceptance through the same state transitions. `StudioGameState` keeps movement, contact gating, collection, win and reset logic independent of Unity objects. A local regression test compiles that exact class with `DOTNET` (or installed dotnet/Mono) when available; the test installs nothing. A separately downloaded official Microsoft .NET SDK **10.0.403** for macOS arm64 ran the exact C# state regression successfully in `/tmp`, with official SHA-512 verification, telemetry/certificate creation disabled, temporary CLI/cache paths and cleared NuGet sources. This proves the standalone state transitions; it does not compile Unity API code or prove keyboard input/rendering. The new source project retains Unity's default legacy Input Manager; no separate `com.unity.modules.inputlegacy` UPM dependency exists in this manifest. If importing into an existing project, use **Player > Active Input Handling > Input Manager (Old)** or **Both**. Unity's future licensed batch run also exercises the real native objects and sprite/event presentation through the same Step calls.

Run the included sample-specific harness only with an existing licensed Editor:

```sh
"/Applications/Unity/Hub/Editor/6000.0.60f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -nographics -projectPath /tmp/studio-unity-offline \
  -executeMethod StudioBatch.Verify -logFile /tmp/studio-unity.log
```

The harness exits 0 only after payload hashing, native mesh construction, all six action frame boundaries, absent FX at 319ms, visible FX at 320ms, 24 particles, local parent attachment particle motion, movement, distant miss, no immediate/early collection, authored contact, target visibility, win and reset pass. It writes `Assets/StreamingAssets/Studio/unity-verification.json` on success or failure, recording only checks that actually passed plus any exception. This command and harness are supplied for future engine verification; no passing Unity result is claimed.

The standalone C# smoke can also run without Unity using an already available .NET SDK:

```sh
DOTNET=/tmp/studio-unity-dotnet-10.0.403/dotnet \
  python3 -m unittest discover -s studio/engines/unity -p 'test_*.py' -v
```

SDK acquisition was a one-time local validation action, not an exporter dependency. The SDK/archive remain under `/tmp`; no SDK, compiler, package source, credentials or binaries are shipped. [Official Microsoft 10.0 release metadata](https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/10.0/releases.json) supplied the archive URL and SHA-512 recorded in `evidence.json`.

## Conversion and coordinates

Raw GLB is the explicitly selected pinned conversion source. Compiled GLB remains copied byte-for-byte for provenance, but is not decoded by Unity. Blender imports the self-contained raw GLB and emits deterministic native mesh JSON. Static internal node transforms are baked into **asset-local** vertex/normal coordinates without recentering. The source asset pivot remains the placement origin. UVs and embedded Base Color texture bytes are retained. Base color, metallic, roughness and emissive values map to built-in Standard materials. No external Blender add-on is required.

Blender's Z-up representation becomes Unity `(x,z,y)` during conversion. Studio placement `(x,y,z)` becomes Unity `(x,y,-z)`, once. Studio XYZ rotation becomes `Rx(-x) * Ry(-y) * Rz(z)`. Positive placement scale and parent-local attachment remain local. Mesh winding changes with the reflection; normals use inverse transpose. Original transforms and source hashes remain in `products.json` and `provenance.json`; converted hashes/counts are in `conversion.json`. `integrity.json` hashes every exported media payload, including converted meshes/textures, and Unity checks it before loading.

Sprite atlas rectangles use authored top-left coordinates, converted to Unity bottom-left rectangles. Pivots use the authored pixel origin; pixels per unit derive from cell height / placement size. Exact per-frame milliseconds and loop flags are retained. Contact FX uses the authored `effect_anchor_px` at `at_px`, starts at 320ms, and uses the original sheet and durations. Non-loop actions hold their last frame. This adapter does not invent replay loops.

Observed Blender conversion of the two actual model assets produced 54 lantern material parts / 23,160 triangles and 1 ember part / 8 triangles. Two separate exports produced identical converted mesh hashes. Five passing Python/Blender checks cover real pins/copies/counts, repeated conversion, six action metadata/contact/pivot/attachment retention, overwrite and drift/escape rejection, malformed GLB/timing, failed-converter atomic cleanup, and a generated textured off-origin fixture whose embedded Base Color PNG bytes and transformed vertex coordinates match expectations. The sixth test compiles and executes the actual standalone C# game state, covering movement, distant miss, no immediate/early hit, contact, collection, win and reset. None of these checks is Unity Editor execution evidence.

## Limits and licences

Static meshes only. Skins, animation tracks, morph targets, external resource URIs and required GLB extensions are rejected. Internal model articulation becomes baked static geometry; Studio parent attachment and particle motion remain articulated runtime Transforms. Material parity is not certified. Transmission/glass, clearcoat, alpha modes, normal maps, packed metallic/roughness textures and emissive textures are not translated. Original embedded PBR media remains preserved inside the copied raw GLB. Only a directly connected embedded Base Color image is extracted for rendering; unsupported connected Base Color node graphs do not reproduce procedurally authored colors. No skinned animation, collision, audio, build, mobile/WebGL filesystem support or production acceptance is claimed. StreamingAssets filesystem loading targets desktop Editor/player.

Unity is proprietary and requires the user's existing valid licence. No engine binary is redistributed. Blender is GPL-licensed and invoked as the user's external local tool; no Blender code or binary is bundled. Local imported asset licence/NOTICE/credit files retain their own terms.

Official sources consulted: [Unity 6000.0.60f1 release](https://unity.com/releases/editor/whats-new/6000.0.60f1), [Mesh API](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityengine/mesh), [Sprite.Create](https://docs.unity.com/zh-cn/engine/6000.0/script-reference/unityengine/sprite/create), [ImageConversion.LoadImage](https://docs.unity.cn/6000.0/Documentation/ScriptReference/ImageConversion.LoadImage.html), [Editor command line](https://docs.unity3d.com/6000.0/Documentation/Manual/EditorCommandLineArguments.html), [native model formats](https://docs.unity3d.com/6000.0/Documentation/Manual/ImportingModelFiles.html). Unity's [glTFast runtime route](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/Documentation~/ImportRuntime.md) was considered; native static conversion keeps this deliverable independent of a remote package resolution step.

Manifest/input references: [official Unity sample manifest](https://raw.githubusercontent.com/Unity-Technologies/EntityComponentSystemSamples/master/EntitiesSamples/Packages/manifest.json), [Unity 6000.0 legacy/new input handling](https://docs.unity3d.com/cn/6000.0/Manual/UIE-Runtime-Event-System.html).
