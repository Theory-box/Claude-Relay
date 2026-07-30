# make_test_file.py - build a deliberately-broken .blend in a NEWER Blender
# (uses nodes absent in the target) to exercise the scanner. Run: blender -b --python make_test_file.py
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
# --- material with 4.3+ shader nodes ---
mat=bpy.data.materials.new("BreakMat"); mat.use_nodes=True; nt=mat.node_tree
met=nt.nodes.new("ShaderNodeBsdfMetallic")      # missing in 4.2
gab=nt.nodes.new("ShaderNodeTexGabor")          # missing in 4.2
prin=[n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'][0]
# --- object with geo-nodes modifier using 4.3/4.4 nodes ---
bpy.ops.mesh.primitive_cube_add(); obj=bpy.context.active_object
obj.data.materials.append(mat)
mod=obj.modifiers.new("GN",'NODES')
ng=bpy.data.node_groups.new("BreakGN",'GeometryNodeTree'); mod.node_group=ng
ng.interface.new_socket("Geometry",in_out='INPUT',socket_type='NodeSocketGeometry')
ng.interface.new_socket("Geometry",in_out='OUTPUT',socket_type='NodeSocketGeometry')
gin=ng.nodes.new("NodeGroupInput"); gout=ng.nodes.new("NodeGroupOutput")
imath=ng.nodes.new("FunctionNodeIntegerMath")   # missing in 4.2
imp=ng.nodes.new("GeometryNodeImportSTL")        # missing in 4.2
giz=ng.nodes.new("GeometryNodeGizmoDial")        # missing in 4.2
warn=ng.nodes.new("GeometryNodeWarning")         # missing in 4.2
ng.links.new(gin.outputs[0],gout.inputs[0])
bpy.ops.wm.save_as_mainfile(filepath="/home/claude/broken.blend")
print("built broken.blend in", bpy.app.version_string)
