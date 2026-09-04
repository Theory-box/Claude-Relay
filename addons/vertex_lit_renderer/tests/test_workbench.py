# tests/test_workbench.py — Workbench studio shading mode
import bpy, sys, os
_here=os.path.dirname(os.path.realpath(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))
import vertex_lit_renderer.shaders as sh
import vertex_lit_renderer.material_shader as ms
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)
def bal(s,o,c):
    d=0
    for ch in s:
        d+=(ch==o)-(ch==c)
        if d<0: return False
    return d==0

print("=== base Workbench frag ===")
check("uKeyDir" in sh.WORKBENCH_FRAG and "uAmbient" in sh.WORKBENCH_FRAG, "studio uniforms present")
check("vlr_light(" not in sh.WORKBENCH_FRAG, "no scene-light lighting")
check("uLPos" not in sh.WORKBENCH_FRAG, "no scene-light array")

print("=== material Workbench frag ===")
m=bpy.data.materials.new('w'); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled')
im=t.nodes.new('ShaderNodeTexImage'); im.image=bpy.data.images.new('t',4,4)
t.links.new(b.outputs['BSDF'],o.inputs['Surface']); t.links.new(im.outputs['Color'],b.inputs['Base Color'])
vert,frag,res=ms.build_material_frag(m,"WORKBENCH")
check(vert is sh.PHONG_VERT, "Workbench pairs PHONG_VERT (world normal)")
check("uKeyDir" in frag and "computeBaseColor" in frag, "studio light + base colour")
check("texture(uTx_0, vUV)" in frag, "samples texture at vUV")
check("uLPos" not in frag and "vlr_light(" not in frag, "no scene lights / GI in Workbench frag")
check(bal(frag,"{","}") and bal(frag,"(",")"), "balanced")

print("=== defaults ===")
import vertex_lit_renderer as vlr
vlr.register()
sc=bpy.data.scenes[0]
check(sc.vertex_lit.shading_mode=='PIXEL', "shading defaults to PIXEL")
vlr.unregister()

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
