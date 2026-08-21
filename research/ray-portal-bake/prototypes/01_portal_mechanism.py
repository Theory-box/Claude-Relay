# TEST 1: proves Ray Portal redirects camera rays to sample a DIFFERENT surface.
# Run: blender -b --python 01_portal_mechanism.py   (Cycles CPU, Blender 4.2+)
# Part of the Ray Portal UV baking research — see ../FINDINGS.md

import bpy, numpy as np
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
def emission_plane(name, loc, size, color):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
    o=bpy.context.object; o.name=name
    m=bpy.data.materials.new(name+"_m"); m.use_nodes=True; nt=m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    e=nt.nodes.new("ShaderNodeEmission"); e.inputs["Color"].default_value=(*color,1)
    out=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0], out.inputs["Surface"])
    o.data.materials.append(m); return o
# TARGET off to the side at x=10 (NOT behind the portal)
B=emission_plane("Target",(10,0,0),4,(1,0,0))
# PORTAL at origin z=3, redirect ray to hit B
bpy.ops.mesh.primitive_plane_add(size=2, location=(0,0,3))
A=bpy.context.object
pm=bpy.data.materials.new("portal"); pm.use_nodes=True; nt=pm.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
geo=nt.nodes.new("ShaderNodeNewGeometry"); rp=nt.nodes.new("ShaderNodeBsdfRayPortal"); out=nt.nodes.new("ShaderNodeOutputMaterial")
add=nt.nodes.new("ShaderNodeVectorMath"); add.operation="ADD"; add.inputs[1].default_value=(10,0,-2.5)
nt.links.new(geo.outputs["Position"], add.inputs[0]); nt.links.new(add.outputs[0], rp.inputs["Position"])
dirv=nt.nodes.new("ShaderNodeCombineXYZ"); dirv.inputs[0].default_value=0; dirv.inputs[1].default_value=0; dirv.inputs[2].default_value=-1
nt.links.new(dirv.outputs[0], rp.inputs["Direction"])
nt.links.new(rp.outputs["BSDF"], out.inputs["Surface"])
A.data.materials.append(pm)
cd=bpy.data.cameras.new("c"); cd.type="ORTHO"; cd.ortho_scale=4
cam=bpy.data.objects.new("cam",cd); cam.location=(0,0,8); bpy.context.scene.collection.objects.link(cam); bpy.context.scene.camera=cam
sc=bpy.context.scene; sc.render.engine="CYCLES"; sc.cycles.device="CPU"; sc.cycles.samples=8
sc.world.use_nodes=True
for n in sc.world.node_tree.nodes:
    if n.type=="BACKGROUND": n.inputs["Color"].default_value=(0,0,0,1)
sc.render.resolution_x=sc.render.resolution_y=128
sc.render.filepath="/tmp/p1b.png"; sc.render.image_settings.file_format="PNG"; sc.render.use_file_extension=False
sc.view_settings.view_transform="Standard"
bpy.ops.render.render(write_still=True)
im=bpy.data.images.load("/tmp/p1b.png"); b=np.empty(128*128*4,np.float32); im.pixels.foreach_get(b); a=b.reshape(128,128,4)
center=a[54:74,54:74,:3].mean(axis=(0,1)); corner=a[0:10,0:10,:3].mean(axis=(0,1))
print("STAGE1b center(portal)=%s corner(empty)=%s"%([round(float(x),2) for x in center],[round(float(x),2) for x in corner]))
print("PORTAL WORKS:", center[0]>0.5 and corner[0]<0.2)
