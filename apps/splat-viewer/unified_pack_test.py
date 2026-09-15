"""Invariant test for the unified texture array: the number of packed planes MUST equal the number
of declared layers, for any mix of duplicate and distinct clouds. Shipping a mismatch makes the
array build fail, which silently falls back to per-tree sorting -- and per-tree sorting is ANGLE
DEPENDENT (correct from some yaws, ~5% wrong pixels from others), which is what the user saw.
Run inside Blender: blender --background --python unified_pack_test.py"""
import bpy, sys, numpy as np
sys.path.insert(0, '/path/to/addons')
import vertex_lit_renderer as v; v.register()
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3)
o = bpy.context.active_object
m = bpy.data.materials.new('m'); m.use_nodes = True; o.data.materials.append(m)
s = bpy.context.scene.vertex_lit
s.splat_method = 'SURFEL'; s.splat_count = 3000; s.splat_color = 'BASECOLOR'
bpy.ops.vertex_lit.generate_splats()
bpy.ops.mesh.primitive_cube_add(); bpy.context.active_object.data.materials.append(m)
bpy.ops.vertex_lit.generate_splats()
from vertex_lit_renderer import splat_render
cl = list(splat_render.SPLAT_CLOUDS.values()); a, b = cl[0], cl[1]
W = 4096

def check(entries, label):
    uniq = []
    for c in entries:
        if not any(c is u for u in uniq): uniq.append(c)
    h = max(u.layer_height() for u in uniq); layers = len(uniq)
    data = np.concatenate([u._packed_data(W, h) for u in uniq], axis=0)
    ok = data.size == W*h*4*layers
    print("%-28s entries=%d unique=%d layers=%d MATCH=%s" % (label, len(entries), len(uniq), layers, ok))
    return ok

res = [check([a]*6, '6 copies of one cloud'), check([a, b], '2 different clouds'),
       check([a, a, b, b, b], 'mixed duplicates'), check([a], 'single cloud')]
print("ALL PASS:", all(res))
v.unregister()
