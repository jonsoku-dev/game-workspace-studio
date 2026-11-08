extends Node3D

var particles: Array = []
var models: Dictionary = {}
var import_report: Array = []
var clock := 0.0

func json_file(path: String):
	return JSON.parse_string(FileAccess.get_file_as_string(path))

func vec(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])

func load_glb(path: String) -> Node3D:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var bytes := FileAccess.get_file_as_bytes(path)
	if bytes.is_empty():
		return null
	var error := doc.append_from_buffer(bytes, path.get_base_dir(), state)
	if error != OK:
		return null
	var node := doc.generate_scene(state)
	if node == null:
		return null
	if geometry(node).triangles <= 0:
		node.free()
		return null
	return node

func geometry(node: Node) -> Dictionary:
	var result := {"meshes": 0, "triangles": 0}
	if node is MeshInstance3D and node.mesh:
		result.meshes = 1
		for i in node.mesh.get_surface_count():
			var arrays: Array = node.mesh.surface_get_arrays(i)
			result.triangles += (arrays[Mesh.ARRAY_INDEX].size() if arrays[Mesh.ARRAY_INDEX] != null and arrays[Mesh.ARRAY_INDEX].size() > 0 else arrays[Mesh.ARRAY_VERTEX].size()) / 3
	for child in node.get_children():
		var child_stats := geometry(child)
		result.meshes += child_stats.meshes
		result.triangles += child_stats.triangles
	return result

func import_product(product: Dictionary) -> Dictionary:
	var nodes := {}
	for asset_id in product.assets:
		var files: Dictionary = product.assets[asset_id]
		if not files.has("model"):
			continue
		# Webstage targets browsers; probe its compiled GLB separately from the raw fallback.
		var compiled := load_glb(files.model)
		var raw := load_glb(files.raw) if files.has("raw") else null
		import_report.append({"asset": asset_id, "compiled": compiled != null, "raw": raw != null, "compiled_geometry": geometry(compiled) if compiled else {}, "raw_geometry": geometry(raw) if raw else {}})
		if compiled:
			models[files.model] = compiled
			if raw:
				raw.free()
		elif raw:
			models[files.model] = raw
		else:
			push_error("No decodable model: " + asset_id)
			get_tree().quit(2)
	for spec in product.scene.nodes:
		var anchor := Node3D.new()
		anchor.name = spec.id
		anchor.position = vec(spec.position)
		anchor.rotation_degrees = vec(spec.rotation_degrees)
		anchor.scale = vec(spec.scale)
		nodes[spec.id] = anchor
		var files: Dictionary = product.assets[spec.asset]
		if files.has("model"):
			if files.has("effect"):
				var recipe: Dictionary = json_file(files.effect)
				assert(recipe.kind == "mesh-particles")
				for p in recipe.particles:
					var mesh: Node3D = models[files.model].duplicate()
					anchor.add_child(mesh)
					particles.append({"node": mesh, "recipe": p, "duration": recipe.duration_s})
			else:
				anchor.add_child(models[files.model].duplicate())
	for spec in product.scene.nodes:
		if spec.has("parent"):
			nodes[spec.parent].add_child(nodes[spec.id])
		else:
			add_child(nodes[spec.id])
	return nodes

func _process(delta: float) -> void:
	clock += delta
	for entry in particles:
		var p: Dictionary = entry.recipe
		var age := fposmod(clock - float(p.start_s), float(entry.duration))
		var mesh: Node3D = entry.node
		mesh.visible = age < float(p.life_s)
		mesh.position = vec(p.offset) + vec(p.drift) * age
		mesh.rotation = vec(p.spin) * age
		var fade := sin(PI * clampf(age / float(p.life_s), 0, 1))
		mesh.scale = Vector3.ONE * maxf(0.001, float(p.scale) * fade)

func _exit_tree() -> void:
	for model in models.values():
		model.free()
