# tests/test_instancing.py — geometry-nodes instances extract + resolve to batches.
import bpy, sys, os, time
sys.path.insert(0, os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd())=='vertex_lit_renderer' else os.getcwd())
import vertex_lit_renderer as v; v.register()
import vertex_lit_renderer.engine as EN
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

# leaf source + a GN instancer that scatters it
bpy.ops.mesh.primitive_cube_add(size=0.3); leaf=bpy.context.active_object; leaf.name='Leaf'
bpy.ops.mesh.primitive_plane_add(size=5); tree=bpy.context.active_object; tree.name='TreeGN'
ng=bpy.data.node_groups.new('Scatter','GeometryNodeTree')
ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
gin=ng.nodes.new('NodeGroupInput'); gout=ng.nodes.new('NodeGroupOutput')
dist=ng.nodes.new('GeometryNodeDistributePointsOnFaces'); dist.inputs['Density'].default_value=2.0
oinfo=ng.nodes.new('GeometryNodeObjectInfo'); oinfo.inputs['Object'].default_value=leaf
iop=ng.nodes.new('GeometryNodeInstanceOnPoints')
ng.links.new(gin.outputs['Geometry'], dist.inputs['Mesh']); ng.links.new(dist.outputs['Points'], iop.inputs['Points'])
ng.links.new(oinfo.outputs['Geometry'], iop.inputs['Instance']); ng.links.new(iop.outputs['Instances'], gout.inputs['Geometry'])
tree.modifiers.new('GN','NODES').node_group=ng
leaf.hide_set(True)

# stub the GPU builders so extraction runs without a GPU context
EN._build_object_slots = lambda data: [('BATCH', None, None)]
EN._build_shadow_batch_from_cache = lambda data: None
dg=bpy.context.evaluated_depsgraph_get()

n_inst = sum(1 for i in dg.object_instances if getattr(i,'is_instance',False) and i.object.type=='MESH')
check(n_inst > 0, "GN produced instances (%d)"%n_inst)

# instances share one mesh datablock -> one draw key
keys = {EN._draw_key(i) for i in dg.object_instances if getattr(i,'is_instance',False) and i.object.type=='MESH'}
check(len(keys)==1 and next(iter(keys)).startswith('i:'), "instances share one 'i:' key (%s)"%keys)

# run the instance-extraction path
batch_dict={}; mesh_cache={}; inst_keys=set(); done=0; be=time.time()+10
for inst in dg.object_instances:
    o=inst.object
    if o.type!='MESH' or not inst.show_self: continue
    if getattr(inst,'is_instance',False):
        k=EN._draw_key(inst)
        if k in inst_keys: continue
        inst_keys.add(k)
        sig=EN._geo_sig(o, getattr(o,'data',None))
        if k in batch_dict and EN._PERSIST_SIG.get(k)==sig: continue
        data=EN._extract_mesh_data(o, dg, attr_name='')
        if data: mesh_cache[k]=data; batch_dict[k]=EN._build_object_slots(data); done+=1

check(len(batch_dict)==1, "one geometry extracted for all instances")
tris = sum(len(s['positions'])//3 for s in mesh_cache[next(iter(mesh_cache))]['slots']) if mesh_cache else 0
check(tris==12, "leaf geometry has the cube's 12 tris (got %d)"%tris)

resolved = sum(1 for i in dg.object_instances if getattr(i,'is_instance',False)
               and i.object.type=='MESH' and EN._draw_key(i) in batch_dict)
check(resolved==n_inst, "all %d instances resolve to a batch (got %d)"%(n_inst, resolved))

v.unregister()
print("ALL CHECKS PASSED" if not F else "FAILED: "+", ".join(F))
