#!/usr/bin/env python3
"""make_test_scene.py — build a synthetic Revit-style test scene INSIDE Blender.

Creates N objects whose names are sampled from a corpus of real Revit-export names
(with [element IDs], .001 dup tags, etc. intact so noise-stripping gets exercised),
and deliberately shares mesh datablocks across many objects so the "instances"
(linked duplicates) path — make_single_user before join — gets tested too.

    blender -b --python make_test_scene.py -- --count 1000 --out test.blend [--seed 7]

Self-contained: the name corpus is embedded, so it runs anywhere with Blender.
"""
import bpy, sys, os, random, argparse

def _args():
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=1000)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--shared-meshes", type=int, default=40,
                   help="size of the shared-mesh pool; smaller => heavier instancing")
    return p.parse_args(argv)

# --- corpus: real cleaned Revit name stems (no trailing IDs); IDs are added below ---
STEMS = [
    "Railing Patio Railing", "Railing Railing - Stair Interior", "Railing Townhome Railing",
    "Railing Railing - Stair - Guardrail", "Basic Wall INT_WD-AW16", "Basic Wall INT_WD-AW17",
    "Basic Wall INT_WD-AW20", "Basic Wall INT_WD-DW10", "Basic Wall INT_WD-GW31",
    "Basic Wall EXT_WD-2X6", "Basic Wall EXT_Stone (Full Bed) w/ OSB",
    "Basic Wall EXT_Siding - Panel Siding w/ OSB", "Basic Wall EXT_Siding - Board & Batten w/ OSB",
    "Basic Wall INT_KITCHEN TILE", "Basic Wall INT_BATH TILE", "Assembled Stair Stair",
    "CW_Closet Shelf and Rod 12\" Deep", "CW_Countertop 21\" Depth", "CW_Countertop 25 1/2\" Depth",
    "CW_Countertop 42\" Depth", "CW_CAB_Base-Filler Panel 36 H x 24 D",
    "CW_CAB_Wall-2 Door Shaker-27 W x 42 H x 12 D", "CW_CAB_Wall-Filler Panel 42 H x 12 D",
    "CW_CAB_Base-2 Door Shaker-30 W x 36 H x 21 D", "CW_CAB_Base-3 Drawer 15 W x 36 H x 21 D",
    "Floor Concrete Slab", "Floor Wood Joist Balcony", "Floor Wood Truss - Townhomes",
    "ME_4 in Exhaust Vent 4\"", "ME_6 in Exhaust Vent 6\"", "Carriage Carriage - 2\" Width",
    "SE_TA-2C/D_Soap Dish", "SE_TA-3A-B_Toilet Paper Holder", "SE_TA-4A_Towel Ring",
    "SE_AP-2A-B_Range1 AP-2A - 30\" W", "SE_AP-3A-C_Microwave AP-3A - Over the Range",
    "SE_FP-Fire Extinguisher Cabinet-FB Semi-Recessed", "SE_FP-Fire Extinguisher Wall Mount",
    "WN_Single Hung-2Unit2 72\" W x 72 H", "WN_Single Hung-3Unit 96\" W x 72 H",
    "WN_1Unit Fixed - 36\" W x 36\" H - White", "GEN_Window Surrounds 72\" x 72\" - SIDING 02",
    "GEN_Window Surrounds 39\" x 96\" - SIDING 02", "GEN_Downspout Downspout",
    "PF_LV-1_Sink-Undermount-Rect 13\" W x 15\" L", "PF_Toilet WC-1 - Tank Type - ANSI Type B",
    "PF_Tub-Rectangular1 36\" D x 60\" L x 18\" H", "PF_Shower-Aquatic - Swing Door 60\" x 35\"",
    "LF_Surface Mounted Puck Fixture 8\"", "LF_Surface Mounted Puck Fixture 6\"",
    "LF_Wall Sconce-Exterior Wall Sconce", "COL_WD Post-Resident Balcony 6\" PT-02",
    "COL_WD Post-Resident Balcony 6\" PT-03", "Wall Sweep Trim - 5/4 x 5.5 - PT-01",
    "Wall Sweep Trim - 5/4 x 5.5 - PT-02", "Fascia Fascia - 4/4 X 7.25\" - PT-02",
    "LEAF_F/G/H F_WD", "LEAF_M 2X5_AL", "LEAF_E WD", "LEAF_N 2X3_AL",
    "UNITS_DR_WD_F1-Swing-Single A-3 - F_HC - 2-10 W x 6-8 H",
    "UNITS_DR_WD_F1-Swing-Single A-4 - F_HC - 2-10 W x 6-8 H",
    "VP_HP_Goodman-GSZ16 Size 24 & 30 (2.0 & 2.5 Ton)", "Gutter Gutter-K Style",
    "Basic Roof Wood Truss - Asphalt Shingle", "Compound Ceiling (Wood Structure)",
    "Water Heater1 Water Heater - Townhomes", "Support - Metal - Circular",
    "Stringer Stringer - 2.125\" Width", "Non-Monolithic Landing",
]

def raw_name(stem, rng):
    """Reattach Revit-style noise so extraction/cleaning gets a realistic target."""
    a = rng.randint(4000000, 9999999)
    n = stem + f" [{a}]"
    if rng.random() < 0.4:                      # sometimes a second host id
        n += f"_[{rng.randint(4000000,9999999)}]"
    if rng.random() < 0.5:                       # sometimes a Blender dup suffix
        n += f".{rng.randint(1,300):03d}"
    return n

def main():
    a = _args()
    rng = random.Random(a.seed)

    # fresh scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # a pool of shared meshes (cubes of varying sizes) -> instancing
    pool = []
    for i in range(a.shared_meshes):
        m = bpy.data.meshes.new(f"shared_mesh_{i:03d}")
        # simple box geometry via bmesh
        import bmesh
        bm = bmesh.new()
        s = 0.5 + (i % 5) * 0.15
        bmesh.ops.create_cube(bm, size=s)
        bm.to_mesh(m); bm.free()
        pool.append(m)

    coll = bpy.context.scene.collection
    used_names = set()
    for k in range(a.count):
        stem = rng.choice(STEMS)
        name = raw_name(stem, rng)
        while name in used_names:               # Blender would auto-suffix; keep unique in our set
            name = raw_name(stem, rng)
        used_names.add(name)
        mesh = rng.choice(pool)                  # SHARED datablock => linked duplicate / "instance"
        obj = bpy.data.objects.new(name, mesh)
        obj.location = (rng.uniform(-20,20), rng.uniform(-20,20), rng.uniform(0,10))
        coll.objects.link(obj)

    # report instancing stats
    shared = sum(1 for m in bpy.data.meshes if m.users > 1)
    multi_user_objs = sum(1 for o in bpy.data.objects if o.type=='MESH' and o.data and o.data.users>1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.out))
    print(f"SCENE_OK objects={len([o for o in bpy.data.objects if o.type=='MESH'])} "
          f"meshes={len(bpy.data.meshes)} shared_meshes={shared} "
          f"objs_on_shared_mesh={multi_user_objs} out={a.out}")

if __name__ == "__main__":
    main()
