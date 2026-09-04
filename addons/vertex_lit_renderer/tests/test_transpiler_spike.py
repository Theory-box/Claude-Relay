# tests/test_transpiler_spike.py
"""
Spike + uniformization test.  blender -b --factory-startup --python <this>
Validates node-walking + GLSL emission and the recompile-kill (constants are
uniforms; value edits leave the shader source identical).
"""
import bpy, sys, os, importlib.util
_here = os.path.dirname(os.path.realpath(__file__))
def _imp(name):
    p = os.path.join(os.path.dirname(_here), name + ".py")
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
nt = _imp("node_transpiler")

FAILS = []
def check(c, m): print(("  PASS " if c else "  FAIL ") + m); (FAILS.append(m) if not c else None)

def new_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    bsdf = t.nodes.new("ShaderNodeBsdfPrincipled")
    t.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m, t, bsdf

print("\n=== A: TexCoord.UV -> Mapping -> Image -> Base Color (mapping uniformized) ===")
mA, tA, bA = new_mat("A")
tc = tA.nodes.new("ShaderNodeTexCoord"); mp = tA.nodes.new("ShaderNodeMapping")
im = tA.nodes.new("ShaderNodeTexImage"); im.image = bpy.data.images.new("t", 4, 4)
mp.inputs["Scale"].default_value = (2.0, 2.0, 1.0)
tA.links.new(tc.outputs["UV"], mp.inputs["Vector"])
tA.links.new(mp.outputs["Vector"], im.inputs["Vector"])
tA.links.new(im.outputs["Color"], bA.inputs["Base Color"])
rA = nt.transpile_material(mA)
print(rA.glsl)
import re
check("texture(" in rA.glsl, "A samples image")
check(len(rA.samplers) == 1, "A one sampler")
check(len(rA.params) >= 3, "A promotes Mapping loc/rot/scale to uniforms ({})".format(len(rA.params)))
check(any(p.want == "vec3" for p in rA.params), "A has vec3 uniform params")
m = re.search(r"texture\(uTx_0,\s*(.+?)\);", rA.glsl)
check(bool(m) and "n_map" in m.group(1), "A samples with MAPPED coords (UV distortion live)")
check("2.0, 2.0, 1.0" not in rA.glsl, "A does NOT bake scale as a literal (it's a uniform)")

print("\n=== A2: change scale 2->4  => shader source UNCHANGED (no recompile) ===")
sigA = nt.topo_signature(mA)
mp.inputs["Scale"].default_value = (4.0, 4.0, 1.0)
rA2 = nt.transpile_material(mA)
check(rA2.glsl == rA.glsl, "A2 GLSL identical after value edit (recompile killed)")
check(nt.topo_signature(mA) == sigA, "A2 topo_signature identical after value edit")

print("\n=== A3: change Mapping vector_type (structure) => signature CHANGES ===")
mp.vector_type = 'TEXTURE'
check(nt.topo_signature(mA) != sigA, "A3 signature changes on structural edit")

print("\n=== B: Mix (image, red) default MIX blend ===")
mB, tB, bB = new_mat("B")
imB = tB.nodes.new("ShaderNodeTexImage"); imB.image = bpy.data.images["t"]
mix = tB.nodes.new("ShaderNodeMixRGB")  # legacy, stable sockets
mix.inputs["Color2"].default_value = (1, 0, 0, 1)
tB.links.new(imB.outputs["Color"], mix.inputs["Color1"])
tB.links.new(mix.outputs["Color"], bB.inputs["Base Color"])
rB = nt.transpile_material(mB)
check("mix(" in rB.glsl, "B emits mix()")
check("texture(" in rB.glsl, "B samples inside mix")

print("\n=== D: no-nodes material -> flat diffuse ===")
mD = bpy.data.materials.new("D"); mD.use_nodes = False
mD.diffuse_color = (0.2, 0.4, 0.6, 1.0)
rD = nt.transpile_material(mD)
check("0.2" in rD.glsl and "0.4" in rD.glsl, "D flat diffuse")



# --- regression: bare Image -> Base Color (no Tex Coord) must sample at vUV
print("=== E: bare Image -> Base Color samples at vUV (not a constant) ===")
mE, tE, bE = new_mat("E")
imE = tE.nodes.new("ShaderNodeTexImage"); imE.image = bpy.data.images.new("e",4,4)
tE.links.new(imE.outputs["Color"], bE.inputs["Base Color"])
rE = nt.transpile_material(mE)
import re as _re2
mm = _re2.search(r"texture\(uTx_0,\s*(.+?)\);", rE.glsl)
check(bool(mm), "E emits a texture() call")
check(bool(mm) and mm.group(1).strip()=="vUV", "E samples at vUV (fixes solid-colour bug)")
print("SUMMARY_E: " + ("FAILED" if FAILS else "ALL CHECKS PASSED"))
sys.exit(1 if FAILS else 0)
