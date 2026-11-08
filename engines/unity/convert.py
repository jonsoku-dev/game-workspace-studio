"""Blender-only static GLB conversion to Unity native mesh payloads."""
import json
from pathlib import Path
import sys
import bpy

source, target = map(Path, sys.argv[sys.argv.index('--') + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
parts = []
for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
    if obj.type != 'MESH':
        continue
    mesh = obj.data
    mesh.calc_loop_triangles()
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    for slot in sorted({t.material_index for t in mesh.loop_triangles}):
        material = obj.material_slots[slot].material if obj.material_slots else None
        color, metallic, roughness, emission = [1, 1, 1, 1], 0, 0.5, [0, 0, 0, 1]
        texture = ''
        if material and material.use_nodes:
            bsdf = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                color = list(bsdf.inputs['Base Color'].default_value)
                metallic = bsdf.inputs['Metallic'].default_value
                roughness = bsdf.inputs['Roughness'].default_value
                emission = list(bsdf.inputs['Emission Color'].default_value)
                strength = bsdf.inputs['Emission Strength'].default_value
                emission[:3] = [v * strength for v in emission[:3]]
                links = bsdf.inputs['Base Color'].links
                if links and links[0].from_node.type == 'TEX_IMAGE':
                    image = links[0].from_node.image
                    if not image or not image.packed_file:
                        raise ValueError('Base Color texture is not embedded')
                    texture = f'{target.stem}-texture-{len(parts)}.png'
                    # Keep embedded media bytes instead of re-encoding image colors.
                    (target.parent / texture).write_bytes(bytes(image.packed_file.data))
        vertices, normals, uv, triangles = [], [], [], []
        for tri in mesh.loop_triangles:
            if tri.material_index != slot:
                continue
            start = len(vertices)
            for loop_index in tri.loops:
                loop = mesh.loops[loop_index]
                v = obj.matrix_world @ mesh.vertices[loop.vertex_index].co
                n = (normal_matrix @ mesh.corner_normals[loop_index].vector).normalized()
                # Blender Z-up to Studio Y-up, then reflect Z for Unity left-handed space.
                vertices.append({'x': v.x, 'y': v.z, 'z': v.y})
                normals.append({'x': n.x, 'y': n.z, 'z': n.y})
                p = mesh.uv_layers.active.data[loop_index].uv if mesh.uv_layers.active else (0, 0)
                uv.append({'x': p[0], 'y': p[1]})
            triangles.extend([start, start + 1, start + 2] if obj.matrix_world.determinant() < 0 else [start, start + 2, start + 1])
        parts.append(dict(name=obj.name, vertices=vertices, normals=normals, uv=uv,
                          triangles=triangles, color=color, metallic=metallic,
                          roughness=roughness, emission=emission, texture=texture))
if not parts or not any(p['triangles'] for p in parts):
    raise ValueError('No drawable triangles')
target.write_text(json.dumps({'parts': parts}, sort_keys=True, separators=(',', ':'), allow_nan=False))
