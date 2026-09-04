# tests/test_shading_modes.py
import bpy, sys, os, importlib.util
_here = os.path.dirname(os.path.realpath(__file__))
def _imp(n):
    p=os.path.join(os.path.dirname(_here),n+".py"); s=importlib.util.spec_from_file_location(n,p)
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))
import vertex_lit_renderer.shaders as sh
import vertex_lit_renderer.material_shader as ms
import vertex_lit_renderer.node_transpiler as nt

F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)
def bal(s,o,c):
    d=0
    for ch in s:
        d+=(ch==o)-(ch==c)
        if d<0: return False
    return d==0

def spike():
    m=bpy.data.materials.new("s"); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    out=t.nodes.new("ShaderNodeOutputMaterial"); b=t.nodes.new("ShaderNodeBsdfPrincipled")
    tc=t.nodes.new("ShaderNodeTexCoord"); mp=t.nodes.new("ShaderNodeMapping")
    im=t.nodes.new("ShaderNodeTexImage"); im.image=bpy.data.images.new("t",4,4)
    t.links.new(b.outputs["BSDF"],out.inputs["Surface"])
    t.links.new(tc.outputs["UV"],mp.inputs["Vector"])
    t.links.new(mp.outputs["Vector"],im.inputs["Vector"])
    t.links.new(im.outputs["Color"],b.inputs["Base Color"])
    return m

print("=== base shaders ===")
check("vlr_light(" in sh.MAIN_VERT, "Gouraud computes lighting in VERTEX shader")
check("vlr_light(" not in sh.MAIN_FRAG, "Gouraud frag has no lighting (uses vLight)")
check("vlr_light(" in sh.PHONG_FRAG, "Phong computes lighting in FRAGMENT shader")
check("uLPos[8]" in sh.PHONG_FRAG, "Phong frag declares light uniforms")
check("vNrm" in sh.PHONG_VERT and "vWpos" in sh.PHONG_VERT, "Phong vert passes world normal/pos")
check("vlr_light(" not in sh.PHONG_VERT, "Phong vert has no lighting")

print("=== material frag: VERTEX mode ===")
m = spike()
vertV, fragV, resV = ms.build_material_frag(m, "VERTEX")
check(vertV is sh.MAIN_VERT, "VERTEX mode pairs MAIN_VERT")
check("in vec4 vLight" in fragV and "vLight.rgb * base.rgb" in fragV, "VERTEX frag uses vLight")
check("vlr_light(" not in fragV, "VERTEX frag has no per-fragment lighting")
check("computeBaseColor" in fragV and bal(fragV,"{","}") and bal(fragV,"(",")"), "VERTEX frag valid+balanced")

print("=== material frag: PIXEL mode ===")
vertP, fragP, resP = ms.build_material_frag(m, "PIXEL")
check(vertP is sh.PHONG_VERT, "PIXEL mode pairs PHONG_VERT")
check("vlr_light(" in fragP and "vlr_shadow(" in fragP, "PIXEL frag lights per-fragment")
check("uLPos[8]" in fragP, "PIXEL frag declares light uniforms (LIGHT_CHUNK)")
check("computeBaseColor" in fragP, "PIXEL frag still computes base colour from graph")
check("lit * base.rgb" in fragP, "PIXEL frag multiplies per-fragment light by base")
check(bal(fragP,"{","}") and bal(fragP,"(",")"), "PIXEL frag balanced")
# no duplicate light uniforms across stages (phong vert must NOT declare them)
check("uLPos[8]" not in vertP, "no duplicate light uniforms across Phong stages")

print("=== mode is part of the cache key ===")
# build_material_frag differs by mode -> distinct programs
check(fragV != fragP, "VERTEX and PIXEL produce different fragments")


# --- graceful fallback: unsupported node -> material marked failed (engine uses legacy)
print("=== graceful fallback on unsupported node ===")
mm = bpy.data.materials.new("noisey"); mm.use_nodes=True; tt=mm.node_tree; tt.nodes.clear()
o=tt.nodes.new("ShaderNodeOutputMaterial"); bb=tt.nodes.new("ShaderNodeBsdfPrincipled")
noise=tt.nodes.new("ShaderNodeWireframe")
tt.links.new(bb.outputs["BSDF"], o.inputs["Surface"])
tt.links.new(noise.outputs["Fac"], bb.inputs["Base Color"])
ent = nt.transpile_material(mm)
check(ent.needs_fallback is False, "unsupported-node material transpiles (node neutralised, no wholesale fallback)")
check(any("neutralised" in str(n) for n in ent.notes), "neutralised node recorded in notes")

print("SUMMARY2: " + ("FAILED " + ", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
