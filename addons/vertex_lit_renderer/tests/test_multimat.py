# tests/test_multimat.py — multi-material objects split into per-slot batches.
import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
import vertex_lit_renderer.engine as E
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

bpy.ops.mesh.primitive_cube_add(); obj=bpy.context.active_object
m1=bpy.data.materials.new('MM1'); m2=bpy.data.materials.new('MM2'); m3=bpy.data.materials.new('MM3')
for m in (m1,m2,m3): obj.data.materials.append(m)
obj.data.calc_loop_triangles()
for i,p in enumerate(obj.data.polygons): p.material_index = i % 3
dg=bpy.context.evaluated_depsgraph_get()
data=E._extract_mesh_data(obj, dg)
check(len(data['slots'])==3, "3 materials -> 3 slots")
names=sorted(s['material_name'] for s in data['slots'])
check(names==['MM1','MM2','MM3'], "each slot carries its own material")
tot=sum(len(s['positions'])//3 for s in data['slots'])
check(tot==len(obj.data.loop_triangles), "slot triangles sum to the whole mesh")

# single-material object -> one slot
bpy.ops.mesh.primitive_cube_add(); o2=bpy.context.active_object
o2.data.materials.append(bpy.data.materials.new('Solo'))
data2=E._extract_mesh_data(o2, bpy.context.evaluated_depsgraph_get())
check(len(data2['slots'])==1, "single material -> one slot")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
