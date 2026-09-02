# tests/test_fallback.py — materials the transpiler can't fully handle must FALL BACK
import bpy, sys, os, importlib.util
_here=os.path.dirname(os.path.realpath(__file__))
def _imp(n):
    p=os.path.join(os.path.dirname(_here),n+".py"); s=importlib.util.spec_from_file_location(n,p)
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
nt=_imp("node_transpiler")
sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))
import vertex_lit_renderer.material_shader as ms
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)
img=bpy.data.images.new('t',8,8)
def mk(name, wire):
    m=bpy.data.materials.new(name); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    o=t.nodes.new('ShaderNodeOutputMaterial'); wire(t,o); return m

# Mix Shader surface -> can't trace base colour -> fallback
def w_mix(t,o):
    a=t.nodes.new('ShaderNodeBsdfPrincipled'); b=t.nodes.new('ShaderNodeBsdfDiffuse')
    im=t.nodes.new('ShaderNodeTexImage'); im.image=img
    t.links.new(im.outputs['Color'], a.inputs['Base Color'])
    mix=t.nodes.new('ShaderNodeMixShader')
    t.links.new(a.outputs['BSDF'], mix.inputs[1]); t.links.new(b.outputs['BSDF'], mix.inputs[2])
    t.links.new(mix.outputs['Shader'], o.inputs['Surface'])
r=nt.transpile_material(mk('MixShader', w_mix))
check(r.needs_fallback is True, "Mix Shader surface flags needs_fallback")
ent=ms._compile(mk('MixShader2', w_mix), "VERTEX")
check(ent["failed"] is True, "Mix Shader material marked failed -> engine uses legacy texture")

# Empty surface (nothing linked) -> fallback, not black
def w_empty(t,o): pass
r2=nt.transpile_material(mk('Empty', w_empty))
check(r2.needs_fallback is True, "empty surface flags needs_fallback")

# Diffuse BSDF with image in Color -> should WORK (not fallback), samples vUV
def w_diff(t,o):
    d=t.nodes.new('ShaderNodeBsdfDiffuse'); im=t.nodes.new('ShaderNodeTexImage'); im.image=img
    t.links.new(im.outputs['Color'], d.inputs['Color'])
    t.links.new(d.outputs['BSDF'], o.inputs['Surface'])
r3=nt.transpile_material(mk('Diffuse', w_diff))
check(r3.needs_fallback is False and len(r3.samplers)==1, "Diffuse BSDF with texture works (no fallback)")
check("texture(uTx_0, vUV)" in r3.glsl, "Diffuse texture samples at vUV")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
