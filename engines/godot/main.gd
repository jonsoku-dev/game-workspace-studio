extends Node3D

const Runtime = preload("res://studio_runtime.gd")
var runtime = Runtime.new()
var player := Node3D.new()
var sprite := Sprite3D.new()
var spark := Sprite3D.new()
var hud := Label.new()
var metadata: Dictionary
var action := "idle"
var action_ms := 0.0
var effect_ms := -1.0
var attacked := false
var collected := 0
var targets: Array[Node3D] = []
var completed := false
var imported: Dictionary
var test_mode := false
var evidence: Dictionary = {}
var evidence_root := "user://"
var verification_failed := false
var accents := true
var reduced_motion := false
var sound_enabled := false
var paused := false
var status := "Gather three ember crystals for the camp lantern."
var cue_counts: Dictionary = {}
var sound := AudioStreamPlayer.new()
var tones: Dictionary = {}
var accent_seconds := 0.0
var step_seconds := 0.0

func _ready() -> void:
	test_mode = "--verify" in OS.get_cmdline_user_args()
	reduced_motion = "--reduced-motion" in OS.get_cmdline_user_args()
	accents = not "--no-accents" in OS.get_cmdline_user_args()
	add_child(sound)
	sound.volume_db = -18
	for pair in [["step", 180.0], ["attack", 330.0], ["denied", 130.0], ["pickup", 660.0], ["win", 880.0], ["reset", 440.0], ["pause", 220.0]]:
		var wave := AudioStreamWAV.new()
		wave.format = AudioStreamWAV.FORMAT_16_BITS
		wave.mix_rate = 22050
		var samples := PackedByteArray()
		samples.resize(2205 * 2)
		for i in 2205:
			var envelope := sin(PI * float(i) / 2205.0)
			samples.encode_s16(i * 2, int(sin(TAU * float(pair[1]) * float(i) / 22050.0) * envelope * 8000))
		wave.data = samples
		tones[pair[0]] = wave
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--evidence-dir="):
			evidence_root = arg.trim_prefix("--evidence-dir=").trim_suffix("/") + "/"
	DirAccess.make_dir_recursive_absolute(evidence_root)
	add_child(runtime)
	var products: Array = runtime.json_file("res://products.json")
	assert(products.size() >= 2, "Ember Run needs forest-camp and scout-actions products")
	var placement: Dictionary = runtime.import_product(products[0])
	imported = placement
	var lantern: Node3D = placement["camp-lantern"]
	# Game placement wraps the imported hierarchy; source transforms remain intact.
	var stage := Node3D.new()
	add_child(stage)
	lantern.reparent(stage, false)
	stage.position = Vector3(-7, 0, 8)
	stage.scale = Vector3.ONE * 5
	var files: Dictionary = products[1].assets["scout"]
	metadata = runtime.json_file(files.metadata)
	sprite.texture = load(files.atlas)
	sprite.pixel_size = 0.025
	sprite.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	sprite.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	sprite.region_enabled = true
	var pivot: Array = metadata.pivot_px_from_top_left
	sprite.offset = Vector2(24 - pivot[0], pivot[1] - 24)
	player.add_child(sprite)
	spark.texture = load(files.effect_0_sheet)
	spark.pixel_size = sprite.pixel_size
	spark.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	spark.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	spark.region_enabled = true
	spark.visible = false
	player.add_child(spark)
	add_child(player)
	player.position = Vector3(-2, 0.1, 0)
	var floor_mesh := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(10, 8)
	floor_mesh.mesh = plane
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color("203e48")
	floor_mesh.material_override = mat
	add_child(floor_mesh)
	for pos in [Vector3(0, 0.3, 0), Vector3(2, 0.3, 0), Vector3(2, 0.3, -2)]:
		var target := MeshInstance3D.new()
		var mesh := PrismMesh.new()
		mesh.size = Vector3(0.35, 0.6, 0.35)
		target.mesh = mesh
		var gold := StandardMaterial3D.new()
		gold.albedo_color = Color("f5b95b")
		gold.emission_enabled = true
		gold.emission = Color("b07520")
		target.material_override = gold
		target.position = pos
		add_child(target)
		targets.append(target)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-55, -30, 0)
	light.light_energy = 1.8
	add_child(light)
	var world := WorldEnvironment.new()
	world.environment = Environment.new()
	world.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	world.environment.ambient_light_color = Color("94abb8")
	world.environment.ambient_light_energy = 0.7
	add_child(world)
	var camera := Camera3D.new()
	camera.position = Vector3(0, 6.5, 7)
	camera.rotation_degrees = Vector3(-45, 0, 0)
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 9
	add_child(camera)
	var canvas := CanvasLayer.new()
	add_child(canvas)
	hud.position = Vector2(28, 24)
	hud.add_theme_font_size_override("font_size", 22)
	canvas.add_child(hud)
	for pair in [["left", KEY_A], ["right", KEY_D], ["up", KEY_W], ["down", KEY_S], ["attack", KEY_SPACE], ["reset", KEY_R], ["pause", KEY_P], ["accents", KEY_F], ["sound", KEY_M], ["motion", KEY_V]]:
		InputMap.add_action(pair[0])
		var key := InputEventKey.new()
		key.physical_keycode = pair[1]
		InputMap.action_add_event(pair[0], key)
	print("STUDIO_IMPORT ", JSON.stringify(runtime.import_report))
	if test_mode:
		verify.call_deferred()

func set_action(value: String) -> void:
	if action != value:
		action = value
		action_ms = 0

func frame_at(frames: Array, ms: float) -> Dictionary:
	for frame in frames:
		ms -= float(frame.duration_ms)
		if ms < 0:
			return frame.rect
	return frames[-1].rect

func region(rect: Dictionary) -> Rect2:
	return Rect2(rect.x, rect.y, rect.w, rect.h)

func cue(kind: String, message: String) -> void:
	cue_counts[kind] = int(cue_counts.get(kind, 0)) + 1
	if not message.is_empty():
		status = message
	if accents and kind in ["pickup", "win", "reset"]:
		accent_seconds = 0.18
	if sound_enabled and accents:
		sound.stream = tones[kind]
		sound.play()

func update_hud() -> void:
	hud.text = "EMBER RUN   %d / 3%s\nWASD move · SPACE strike · R restart · P pause\nF accents: %s · M sound: %s · V reduced motion: %s\n%s" % [collected, "   PAUSED" if paused else "", "on" if accents else "off", "on" if sound_enabled else "off", "on" if reduced_motion else "off", status]

func _physics_process(delta: float) -> void:
	if Input.is_action_just_pressed("accents"):
		accents = not accents
		if not accents:
			sound.stop()
			sound.stream = null
	if Input.is_action_just_pressed("sound"):
		sound_enabled = not sound_enabled
		if not sound_enabled:
			sound.stop()
			sound.stream = null
	if Input.is_action_just_pressed("motion"):
		reduced_motion = not reduced_motion
	if not accents or reduced_motion:
		sprite.scale = Vector3.ONE
		sprite.position.y = 0
	if Input.is_action_just_pressed("pause"):
		paused = not paused
		runtime.process_mode = Node.PROCESS_MODE_DISABLED if paused else Node.PROCESS_MODE_INHERIT
		cue("pause", "Paused — press P to resume." if paused else ("Camp supplied — press R to play again." if completed else "Resumed — gather the remaining crystals."))
	if paused:
		update_hud()
		return
	if Input.is_action_just_pressed("reset"):
		reset_game()
	if Input.is_action_just_pressed("attack"):
		if action == "attack" or completed:
			cue("denied", "Strike already in progress." if not completed else "Camp supplied — press R to play again.")
		else:
			set_action("attack")
			attacked = false
			cue("attack", "Strike — contact follows the scout's swing.")
	var direction := Input.get_vector("left", "right", "up", "down")
	if action != "attack" and not completed:
		var previous := player.position
		player.position += Vector3(direction.x, 0, direction.y) * delta * 2.5
		player.position.x = clampf(player.position.x, -4.3, 4.3)
		player.position.z = clampf(player.position.z, -3.3, 3.3)
		var moving := player.position.distance_to(previous) > 0.0001
		set_action("walk" if moving else "idle")
		if moving:
			step_seconds -= delta
			if step_seconds <= 0:
				cue("step", "")
				step_seconds = 0.32
		else:
			step_seconds = 0
		if direction.x != 0:
			sprite.flip_h = direction.x < 0
	action_ms += delta * 1000
	var info: Dictionary = metadata.actions[action]
	if action == "attack":
		var event: Dictionary = metadata.events[0]
		if not attacked and action_ms >= float(event.start_ms):
			attacked = true
			effect_ms = 0
			var before := collected
			for target in targets:
				if target.visible and player.position.distance_to(target.position) < 0.85:
					target.visible = false
					collected += 1
			completed = collected == targets.size()
			if completed:
				cue("win", "Camp supplied — complete! Press R to play again.")
			elif collected > before:
				cue("pickup", "Crystal gathered — %d remaining." % (targets.size() - collected))
			else:
				cue("denied", "No crystal in reach — move closer, then strike.")
		if action_ms >= float(info.duration_ms):
			set_action("idle")
			info = metadata.actions.idle
	var time := fposmod(action_ms, float(info.duration_ms)) if info.loop else minf(action_ms, float(info.duration_ms) - 1)
	sprite.region_rect = region(frame_at(info.frames, time))
	if effect_ms >= 0:
		var event: Dictionary = metadata.events[0]
		effect_ms += delta * 1000
		spark.visible = effect_ms < float(event.duration_ms)
		if spark.visible:
			spark.region_rect = region(frame_at(event.frames, effect_ms))
			var at: Array = event.at_px
			var anchor: Array = event.effect_anchor_px
			var rect: Rect2 = spark.region_rect
			var sign_x := -1 if sprite.flip_h else 1
			spark.flip_h = sprite.flip_h
			spark.position = Vector3((at[0] - 24) * sprite.pixel_size * sign_x, (46 - at[1]) * sprite.pixel_size, 0.02)
			spark.offset = Vector2((rect.size.x / 2 - anchor[0]) * sign_x, anchor[1] - rect.size.y / 2)
	accent_seconds = maxf(0, accent_seconds - delta)
	sprite.scale = Vector3.ONE * (1.0 + accent_seconds * 0.5 if accents and not reduced_motion else 1.0)
	sprite.position.y = sin(action_ms * 0.018) * 0.025 if action == "walk" and accents and not reduced_motion else 0.0
	update_hud()

func reset_game() -> void:
	cue("reset", "Camp reset — gather three ember crystals.")
	step_seconds = 0
	sprite.position.y = 0
	player.position = Vector3(-2, 0.1, 0)
	collected = 0
	completed = false
	set_action("idle")
	effect_ms = -1
	spark.visible = false
	for target in targets:
		target.visible = true

func hold(action_name: String, seconds: float) -> void:
	Input.action_press(action_name)
	await get_tree().create_timer(seconds).timeout
	Input.action_release(action_name)
	await get_tree().physics_frame

func screenshot(filename: String) -> void:
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(evidence_root + filename)

func ensure(condition: bool, message := "Gameplay check failed") -> void:
	if not condition:
		verification_failed = true
		push_error(message)
		get_tree().quit(1)

func verify() -> void:
	await get_tree().physics_frame
	var verified_pins := 0
	var pins: Dictionary = runtime.json_file("res://provenance.json")
	for path in pins:
		if path.ends_with(".png"):
			continue
		var context := HashingContext.new()
		context.start(HashingContext.HASH_SHA256)
		context.update(FileAccess.get_file_as_bytes("res://" + path))
		ensure(context.finish().hex_encode() == pins[path].sha256, "Packaged artifact pin: " + path)
		verified_pins += 1
	ensure(sprite.texture.get_width() > 0 and spark.texture.get_width() > 0, "Imported atlas textures")
	ensure(imported["camp-embers"].get_parent() == imported["camp-lantern"], "Native parent attachment")
	var initial_particle: Vector3 = runtime.particles[0].node.position
	await screenshot("start.png")
	var start := player.position
	await hold("attack", 0.15)
	ensure(collected == 0, "Distant attack must miss")
	await hold("attack", 0.05)
	ensure(status == "Strike already in progress.", "Busy strike denial")
	await get_tree().create_timer(0.8).timeout
	await hold("right", 0.8)
	ensure(player.position.x > start.x + 1.8, "Input movement")
	await hold("attack", 0.15)
	ensure(collected == 0, "Contact must wait for authored 320ms trigger")
	await get_tree().create_timer(0.25).timeout
	ensure(collected == 1 and spark.visible, "Timed contact collection + atlas FX")
	ensure(runtime.particles[0].node.position != initial_particle, "Mesh particle movement")
	await screenshot("contact.png")
	await get_tree().create_timer(0.6).timeout
	await hold("right", 0.8)
	await hold("attack", 0.9)
	ensure(collected == 2)
	await hold("up", 0.8)
	await hold("attack", 0.9)
	ensure(completed and collected == 3, "Playable goal")
	await hold("attack", 0.05)
	ensure(action == "idle" and status.contains("Camp supplied"), "Completed game denies another strike")
	evidence = {"engine": Engine.get_version_info(), "packaged_byte_pins": verified_pins, "movement": true, "distant_miss": true, "trigger_320ms": true, "collected": collected, "completed": completed, "native_mesh_particles": runtime.particles.size(), "imports": runtime.import_report}
	await screenshot("completed.png")
	await hold("reset", 0.1)
	ensure(collected == 0 and not completed and targets.all(func(t): return t.visible), "Replay reset")
	evidence.reset = true
	ensure(cue_counts.get("step", 0) > 0 and cue_counts.get("pickup", 0) == 2 and cue_counts.get("win", 0) == 1 and cue_counts.get("denied", 0) > 0 and cue_counts.get("reset", 0) == 1, "Event feedback follows real gameplay")
	await hold("pause", 0.1)
	var paused_position := player.position
	var paused_particle: Vector3 = runtime.particles[0].node.position
	await hold("right", 0.2)
	ensure(paused and player.position == paused_position and runtime.particles[0].node.position == paused_particle, "Pause freezes gameplay and imported particles")
	await hold("pause", 0.1)
	if accents:
		await hold("accents", 0.1)
	if not reduced_motion:
		await hold("motion", 0.1)
	ensure(not accents and reduced_motion and sprite.scale == Vector3.ONE and sprite.position.y == 0, "A/B and reduced motion retain informational state")
	ensure(not sound_enabled and not sound.playing, "Audio is opt in")
	await hold("sound", 0.1)
	ensure(sound_enabled and not sound.playing, "A/B disables optional sound")
	await hold("accents", 0.1)
	await hold("attack", 0.05)
	ensure(sound.playing and sound.stream == tones.attack, "Opt-in native audio dispatch")
	await hold("sound", 0.05)
	ensure(not sound_enabled and not sound.playing, "Mute stops current audio")
	await get_tree().create_timer(0.2).timeout
	evidence.feedback = {"events": cue_counts, "pause_freezes_gameplay": true, "accents_ab": true, "reduced_motion": true, "audio_default_muted": true, "native_audio_dispatch": true}
	if verification_failed:
		return
	print("STUDIO_EVIDENCE_DIR ", ProjectSettings.globalize_path(evidence_root))
	FileAccess.open(evidence_root + "verification.json", FileAccess.WRITE).store_string(JSON.stringify(evidence, "  "))
	print("STUDIO_PLAYABLE_PASS ", JSON.stringify(evidence))
	get_tree().quit()
