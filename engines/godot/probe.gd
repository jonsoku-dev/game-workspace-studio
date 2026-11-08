extends SceneTree

func _initialize() -> void:
	var loader = load("res://studio_runtime.gd").new()
	var results := []
	var args := OS.get_cmdline_user_args()
	if args.size() == 3 and args[0] == "--fallback":
		loader.import_product({"scene": {"nodes": []}, "assets": {"probe": {"model": args[1], "raw": args[2]}}})
		assert(loader.models.has(args[1]))
		var stats: Dictionary = loader.geometry(loader.models[args[1]])
		assert(stats.triangles > 0)
		print("STUDIO_RAW_FALLBACK_PASS ", JSON.stringify(stats))
		for model in loader.models.values():
			model.free()
		loader.models.clear()
		loader.free()
		quit()
		return
	for path in args:
		var node = loader.load_glb(path)
		results.append({"path": path, "decoded": node != null, "geometry": loader.geometry(node) if node else {}})
		if node:
			node.free()
	print("STUDIO_GLB_PROBE ", JSON.stringify(results))
	loader.free()
	quit()
