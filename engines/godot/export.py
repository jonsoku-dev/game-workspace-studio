"""Copy pinned Studio runtime products into a standalone offline Godot project."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from runtime_inputs import admit, copy_verified, output_stage


def export(sources, output):
    prepared, hashes = admit(sources)
    # Godot exports imported .glb files as scenes. Preserve original pinned bytes for GLTFDocument.
    paths = {name: name + '.bytes' if name.endswith('.glb') else name for name in hashes}
    for product in prepared:
        for roles in product['assets'].values():
            for role, name in roles.items():
                roles[role] = 'res://' + paths[name]
    with output_stage(output) as stage:
        provenance = copy_verified({paths[name]: pin for name, pin in hashes.items()}, stage)
        for name in ('project.godot', 'main.tscn', 'main.gd', 'studio_runtime.gd', 'probe.gd', 'export_presets.cfg'):
            shutil.copyfile(Path(__file__).parent / name, stage / name)
        (stage / 'products.json').write_text(json.dumps(prepared, indent=2))
        (stage / 'provenance.json').write_text(json.dumps(provenance, indent=2))
    return prepared


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', nargs=2, action='append', required=True, metavar=('PROJECT', 'RUNTIME'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export([(Path(p), r) for p, r in args.source], args.output)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
