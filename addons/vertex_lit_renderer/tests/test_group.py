# tests/test_group.py — node group tracing verified on the GL harness.
import bpy, sys, os, importlib.util
_here=os.path.dirname(os.path.realpath(__file__))
spec=importlib.util.spec_from_file_location("gl_harness", os.path.join(_here,"gl_harness.py"))
H=importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

def base(name):
    m=bpy.data.materials.new(name); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled')
    t.links.new(b.outputs['BSDF'],o.inputs['Surface']); return m,t,b

# --- group 1: pure passthrough Color in -> Color out ---
def make_passthrough():
    g=bpy.data.node_groups.new("PT",'ShaderNodeTree')
    g.interface.new_socket("Color",in_out='INPUT',socket_type='NodeSocketColor')
    g.interface.new_socket("Color",in_out='OUTPUT',socket_type='NodeSocketColor')
    gi=g.nodes.new('NodeGroupInput'); go=g.nodes.new('NodeGroupOutput')
    g.links.new(gi.outputs['Color'], go.inputs['Color']); return g

# --- group 2: Color in -> Invert -> Color out ---
def make_invert():
    g=bpy.data.node_groups.new("INV",'ShaderNodeTree')
    g.interface.new_socket("Color",in_out='INPUT',socket_type='NodeSocketColor')
    g.interface.new_socket("Color",in_out='OUTPUT',socket_type='NodeSocketColor')
    gi=g.nodes.new('NodeGroupInput'); go=g.nodes.new('NodeGroupOutput')
    inv=g.nodes.new('ShaderNodeInvert')
    g.links.new(gi.outputs['Color'], inv.inputs['Color'])
    g.links.new(inv.outputs['Color'], go.inputs['Color']); return g

C=(0.2,0.4,0.6,1.0)
# passthrough: albedo should equal input color
m,t,b=base('g_pt'); rgb=t.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value=C
gn=t.nodes.new('ShaderNodeGroup'); gn.node_tree=make_passthrough()
t.links.new(rgb.outputs[0], gn.inputs['Color']); t.links.new(gn.outputs['Color'], b.inputs['Base Color'])
px,_=H.render_material(m,size=4); r,gc,bl=px[...,0].mean(),px[...,1].mean(),px[...,2].mean()
check(abs(r-0.2)<0.03 and abs(gc-0.4)<0.03 and abs(bl-0.6)<0.03, "group passthrough albedo = input (%.2f,%.2f,%.2f)"%(r,gc,bl))

# invert: albedo should be 1-input
m,t,b=base('g_inv'); rgb=t.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value=C
gn=t.nodes.new('ShaderNodeGroup'); gn.node_tree=make_invert()
t.links.new(rgb.outputs[0], gn.inputs['Color']); t.links.new(gn.outputs['Color'], b.inputs['Base Color'])
px,_=H.render_material(m,size=4); r,gc,bl=px[...,0].mean(),px[...,1].mean(),px[...,2].mean()
check(abs(r-0.8)<0.03 and abs(gc-0.6)<0.03 and abs(bl-0.4)<0.03, "group invert albedo = 1-input (%.2f,%.2f,%.2f)"%(r,gc,bl))

# nested group: invert group used INSIDE another passthrough-ish group
def make_nested():
    inner=make_invert()
    g=bpy.data.node_groups.new("OUTER",'ShaderNodeTree')
    g.interface.new_socket("Color",in_out='INPUT',socket_type='NodeSocketColor')
    g.interface.new_socket("Color",in_out='OUTPUT',socket_type='NodeSocketColor')
    gi=g.nodes.new('NodeGroupInput'); go=g.nodes.new('NodeGroupOutput')
    sub=g.nodes.new('ShaderNodeGroup'); sub.node_tree=inner
    g.links.new(gi.outputs['Color'], sub.inputs['Color'])
    g.links.new(sub.outputs['Color'], go.inputs['Color']); return g
m,t,b=base('g_nest'); rgb=t.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value=C
gn=t.nodes.new('ShaderNodeGroup'); gn.node_tree=make_nested()
t.links.new(rgb.outputs[0], gn.inputs['Color']); t.links.new(gn.outputs['Color'], b.inputs['Base Color'])
px,_=H.render_material(m,size=4); r=px[...,0].mean()
check(abs(r-0.8)<0.03, "nested group (invert inside) albedo.r = 0.8 (got %.2f)"%r)

print("ALL CHECKS PASSED" if not F else ("FAILED: "+", ".join(F)))
