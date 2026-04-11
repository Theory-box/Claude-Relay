#!/usr/bin/env python3
"""
inspect_glb_tod.py — Diagnose ToD vertex color attributes in an exported level GLB.

USAGE:
    python3 inspect_glb_tod.py path/to/your-level.glb

WHAT IT DOES:
    Walks every mesh primitive in the GLB and lists every vertex attribute it
    finds. We're looking specifically for the 8 ToD slots:
        _SUNRISE _MORNING _NOON _AFTERNOON _SUNSET _TWILIGHT _EVENING _GREENSUN
    plus the standard COLOR_0 (which is whatever attribute was 'active' in
    Blender at export time).

INTERPRETATION:
    - Sees all 8 _NAME attributes ........... addon-side export is FINE.
                                              Bug is downstream (importer / mood / collection setup).
    - Sees only COLOR_0, no _NAME attrs ..... export is silently dropping them.
                                              Need to fix the gltf export call (likely export_attributes
                                              isn't actually catching color-typed attributes in B4.4).
    - Sees some but not all _NAME attrs ..... per-mesh problem (some meshes never got baked into).
    - Sees no COLOR_0 either ................ no vertex colors at all reaching export.

NO BLENDER REQUIRED. Pure-Python GLB parser, stdlib only.
"""
import json
import struct
import sys
from pathlib import Path

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
TOD_SLOTS = ["_SUNRISE", "_MORNING", "_NOON", "_AFTERNOON",
             "_SUNSET", "_TWILIGHT", "_EVENING", "_GREENSUN"]


def parse_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"Not a GLB file: {path}")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != JSON_CHUNK:
        raise ValueError("First chunk is not JSON")
    return json.loads(data[20:20 + chunk_len].decode("utf-8"))


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    glb_path = Path(sys.argv[1])
    if not glb_path.exists():
        print(f"ERROR: file not found: {glb_path}")
        sys.exit(1)

    gltf = parse_glb_json(glb_path)
    meshes = gltf.get("meshes", [])
    print(f"GLB: {glb_path.name}  ({len(meshes)} meshes)\n")

    all_attr_names: set[str] = set()
    slot_presence = {slot: 0 for slot in TOD_SLOTS}
    color0_count = 0
    prim_count = 0
    meshes_with_no_tod = []

    for mesh in meshes:
        mesh_name = mesh.get("name", "<unnamed>")
        mesh_has_any_tod = False
        for prim in mesh.get("primitives", []):
            prim_count += 1
            attrs = prim.get("attributes", {})
            all_attr_names.update(attrs.keys())
            if "COLOR_0" in attrs:
                color0_count += 1
            for slot in TOD_SLOTS:
                if slot in attrs:
                    slot_presence[slot] += 1
                    mesh_has_any_tod = True
        if not mesh_has_any_tod:
            meshes_with_no_tod.append(mesh_name)

    print(f"Total primitives: {prim_count}")
    print(f"Primitives with COLOR_0: {color0_count}\n")

    print("ToD slot presence (primitives carrying each slot):")
    for slot in TOD_SLOTS:
        marker = "OK " if slot_presence[slot] == prim_count else "!! "
        print(f"  {marker}{slot:12s} {slot_presence[slot]:4d} / {prim_count}")

    print("\nAll unique vertex attribute names found across all primitives:")
    for name in sorted(all_attr_names):
        print(f"  {name}")

    if meshes_with_no_tod:
        print(f"\nMeshes with ZERO ToD slots ({len(meshes_with_no_tod)}):")
        for name in meshes_with_no_tod[:20]:
            print(f"  - {name}")
        if len(meshes_with_no_tod) > 20:
            print(f"  ... and {len(meshes_with_no_tod) - 20} more")

    # Verdict
    print("\n" + "=" * 60)
    full = sum(1 for s in TOD_SLOTS if slot_presence[s] == prim_count)
    partial = sum(1 for s in TOD_SLOTS if 0 < slot_presence[s] < prim_count)
    none = sum(1 for s in TOD_SLOTS if slot_presence[s] == 0)
    if full == 8:
        print("VERDICT: All 8 ToD slots present on every primitive.")
        print("         Export side is FINE. Bug is downstream.")
    elif full == 0 and partial == 0:
        print("VERDICT: ZERO ToD slots in this GLB.")
        print("         export_attributes is not catching the color attributes.")
        print("         (Or: meshes were never baked, or wrong collection exported.)")
    else:
        print(f"VERDICT: Mixed — {full} slots full, {partial} partial, {none} missing.")
        print("         Per-mesh baking gaps OR partial export failure.")
    print("=" * 60)


if __name__ == "__main__":
    main()
