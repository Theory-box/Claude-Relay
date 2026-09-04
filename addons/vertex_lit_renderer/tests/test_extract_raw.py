# tests/test_extract_raw.py — the raw-memory extraction must match a foreach reference.
import bpy, sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
import vertex_lit_renderer.engine as E
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=32)
obj=bpy.context.active_object
dg=bpy.context.evaluated_depsgraph_get()
m=obj.evaluated_get(dg).data; m.calc_loop_triangles()
nt=len(m.loop_triangles); nflat=nt*3

# independent foreach reference
vi=np.empty(nflat,np.int32); m.loop_triangles.foreach_get('vertices',vi)
vc=np.empty(len(m.vertices)*3,np.float32); m.vertices.foreach_get('co',vc); vc=vc.reshape(-1,3)
ref_pos=vc[vi]

data=E._extract_mesh_data(obj, dg)
got_pos=data['slots'][0]['positions']
check(got_pos.shape==ref_pos.shape, "extracted position count matches foreach")
check(np.allclose(got_pos, ref_pos, atol=1e-5), "raw-memory positions == foreach positions")

# raw helpers return None gracefully on a bogus attribute (fallback safety)
check(E._raw_attr(m, 'NONEXISTENT_ATTR', __import__('ctypes').c_float, 3, len(m.vertices)) is None,
      "raw reader returns None for a missing attribute (falls back safely)")

# UVs present and finite
uvs=data['slots'][0]['uvs']
check(uvs.shape==(nflat,2) and np.isfinite(uvs).all(), "UVs extracted, correct shape, finite")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
