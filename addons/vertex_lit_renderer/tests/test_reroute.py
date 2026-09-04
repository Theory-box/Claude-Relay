# tests/test_reroute.py — reroute passthrough + values reaching a brick through chains.
import bpy, sys, os, importlib.util
_here=os.path.dirname(os.path.realpath(__file__))
spec=importlib.util.spec_from_file_location("gl_harness", os.path.join(_here,"gl_harness.py"))
H=importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
sys.path.insert(0, os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd())=='vertex_lit_renderer' else os.getcwd())
import vertex_lit_renderer as v; v.register()
from vertex_lit_renderer import node_transpiler as T
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

def make_plankish():
    g=bpy.data.node_groups.new("Plankish",'ShaderNodeTree')
    g.interface.new_socket("Color",in_out='OUTPUT',socket_type='NodeSocketColor')
    g.interface.new_socket("Length",in_out='INPUT',socket_type='NodeSocketFloat')
    g.interface.new_socket("Width",in_out='INPUT',socket_type='NodeSocketFloat')
    gi=g.nodes.new('NodeGroupInput'); go=g.nodes.new('NodeGroupOutput'); br=g.nodes.new('ShaderNodeTexBrick')
    r1=g.nodes.new('NodeReroute'); r2=g.nodes.new('NodeReroute')
    g.links.new(gi.outputs['Length'],r1.inputs[0]); g.links.new(r1.outputs[0],r2.inputs[0]); g.links.new(r2.outputs[0],br.inputs[8])
    r3=g.nodes.new('NodeReroute'); r4=g.nodes.new('NodeReroute')
    g.links.new(gi.outputs['Width'],r3.inputs[0]); g.links.new(r3.outputs[0],r4.inputs[0]); g.links.new(r4.outputs[0],br.inputs[9])
    br.inputs[4].default_value=5.0
    g.links.new(br.outputs[0],go.inputs['Color']); return g

m=bpy.data.materials.new("pk"); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled'); t.links.new(b.outputs['BSDF'],o.inputs['Surface'])
gn=t.nodes.new('ShaderNodeGroup'); gn.node_tree=make_plankish()
gn.inputs['Length'].default_value=0.5; gn.inputs['Width'].default_value=0.25
t.links.new(gn.outputs['Color'], b.inputs['Base Color'])
res=T.transpile_material(m)

check(res.ok and not res.notes, "no neutralised nodes; notes=%s"%res.notes)

# Length param = kind 'input' on the group node, index 0; Width = index 1
def find_param(idx):
    for p in res.params:
        if p.kind=='input' and p.node_name==gn.name and p.index==idx: return p
    return None
pl=find_param(0); pw=find_param(1)
check(pl is not None and pw is not None, "Length & Width each became a uniform")
check(pl and pw and pl.uniform!=pw.uniform, "Length and Width are DISTINCT uniforms (%s vs %s)"%(getattr(pl,'uniform','?'),getattr(pw,'uniform','?')))
check(pl and pl.want=='float', "Length uniform is float, not vec4 (got %s)"%getattr(pl,'want','?'))

# both uniforms must appear in the brick call (i.e. actually feed Brick Width / Row Height)
glsl=res.glsl
check(pl and pl.uniform in glsl, "Length uniform used in generated GLSL")
check(pw and pw.uniform in glsl, "Width uniform used in generated GLSL")
# no stacked coercion artifact
check('.x).x).x' not in glsl, "no stacked-coercion artifact ((x).x).x")

# live binding: changing the group input default changes the bound uniform value
before=pl.value(m.node_tree)
gn.inputs['Length'].default_value=0.123
after=pl.value(m.node_tree)
check(abs(before-0.5)<1e-4 and abs(after-0.123)<1e-4, "Length binds live (%.3f -> %.3f)"%(before,after))

# it also compiles+renders without error
try:
    px,_=H.render_material(m,size=16); ok=(px is not None)
except Exception as e:
    ok=False; print("   render err:", repr(e)[:120])
check(ok, "brick-through-reroute material compiles & renders")

v.unregister()
print("ALL CHECKS PASSED" if not F else "FAILED: "+", ".join(F))
