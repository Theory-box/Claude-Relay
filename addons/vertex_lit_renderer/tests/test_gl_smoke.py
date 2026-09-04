# tests/test_gl_smoke.py — prove the CPU GL harness compiles + renders real node output
import bpy, sys, os, importlib.util
_here=os.path.dirname(os.path.realpath(__file__))
spec=importlib.util.spec_from_file_location("gl_harness", os.path.join(_here,"gl_harness.py"))
H=importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
import numpy as np
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

def mat(name, wire):
    m=bpy.data.materials.new(name); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled')
    t.links.new(b.outputs['BSDF'],o.inputs['Surface']); wire(t,b); return m

img=bpy.data.images.new('t',16,16)

# 1) image -> base color : output should equal the gradient texture (R=u, G=v)
def w_img(t,b):
    im=t.nodes.new('ShaderNodeTexImage'); im.image=img
    t.links.new(im.outputs['Color'], b.inputs['Base Color'])
px,res=H.render_material(mat('img', w_img), size=16)
# bottom-left ~ (0,0), top-right ~ (1,1) in R,G
check(px[0,0,0] < 0.15 and px[-1,-1,0] > 0.85, "texture samples across U (varies left->right)")
check(px[0,0,1] < 0.15 and px[-1,-1,1] > 0.85, "texture samples across V (varies bottom->top)")

# 2) brightness (BrightContrast Bright=+0.4) must RAISE output vs passthrough
def w_flat(t,b): b.inputs['Base Color'].default_value=(0.3,0.3,0.3,1.0)
base_px,_=H.render_material(mat('flat', w_flat), size=8, param_values={})
def w_bright(t,b):
    v=t.nodes.new('ShaderNodeRGB'); v.outputs[0].default_value=(0.3,0.3,0.3,1.0)
    bc=t.nodes.new('ShaderNodeBrightContrast'); bc.inputs['Bright'].default_value=0.4
    t.links.new(v.outputs[0], bc.inputs['Color']); t.links.new(bc.outputs['Color'], b.inputs['Base Color'])
bp,_=H.render_material(mat('bright', w_bright), size=8)
check(bp.mean() > base_px.mean()+0.2, "brightness node raises output ({:.2f} -> {:.2f})".format(base_px.mean(), bp.mean()))

# 3) mix ADD of grey(0.3) + grey(0.4) ~ 0.7
def w_mix(t,b):
    a=t.nodes.new('ShaderNodeRGB'); a.outputs[0].default_value=(0.3,0.3,0.3,1)
    c=t.nodes.new('ShaderNodeRGB'); c.outputs[0].default_value=(0.4,0.4,0.4,1)
    mx=t.nodes.new('ShaderNodeMixRGB'); mx.blend_type='ADD'; mx.inputs['Fac'].default_value=1.0
    t.links.new(a.outputs[0], mx.inputs['Color1']); t.links.new(c.outputs[0], mx.inputs['Color2'])
    t.links.new(mx.outputs['Color'], b.inputs['Base Color'])
mp,_=H.render_material(mat('mixadd', w_mix), size=4)
check(abs(mp[...,0].mean()-0.7) < 0.05, "mix ADD 0.3+0.4 ~= 0.7 (got {:.3f})".format(mp[...,0].mean()))

# 4) all 19 blend modes COMPILE on the software context
ok_all=True
for bt in ['MIX','DARKEN','MULTIPLY','BURN','LIGHTEN','SCREEN','DODGE','ADD','OVERLAY','SOFT_LIGHT','LINEAR_LIGHT','DIFFERENCE','EXCLUSION','SUBTRACT','DIVIDE','HUE','SATURATION','COLOR','VALUE']:
    def w(t,b,bt=bt):
        im=t.nodes.new('ShaderNodeTexImage'); im.image=img
        mx=t.nodes.new('ShaderNodeMixRGB'); mx.blend_type=bt; mx.inputs['Color2'].default_value=(1,0.5,0,1)
        t.links.new(im.outputs['Color'], mx.inputs['Color1']); t.links.new(mx.outputs['Color'], b.inputs['Base Color'])
    good,err=H.compiles(mat('bl_'+bt, w))
    if not good: ok_all=False; print("   COMPILE FAIL", bt, err[:120])
check(ok_all, "all 19 blend modes compile on real GLSL")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
