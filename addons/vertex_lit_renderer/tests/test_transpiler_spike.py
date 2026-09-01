# tests/test_transpiler_spike.py
"""
Headless spike test for node_transpiler.

Run:  blender --background --factory-startup --python test_transpiler_spike.py

Builds real Blender materials and runs the transpiler on them. Validates the
node-walking + GLSL emission (the risky part). Does NOT need a GPU: shader
COMPILE + visual output is the engine's job on the user's machine.
"""
import bpy, sys, os, importlib.util

# import node_transpiler.py directly (sibling of the tests/ dir)
_here = os.path.dirname(os.path.realpath(__file__))
_mod_path = os.path.join(os.path.dirname(_here), "node_transpiler.py")
spec = importlib.util.spec_from_file_location("node_transpiler", _mod_path)
nt = importlib.util.module_from_spec(spec); spec.loader.exec_module(nt)

FAILS = []
def check(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond: FAILS.append(msg)

def new_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt_ = m.node_tree
    nt_.nodes.clear()
    out = nt_.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt_.nodes.new("ShaderNodeBsdfPrincipled")
    nt_.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m, nt_, bsdf

def make_image():
    img = bpy.data.images.get("spike_tex") or bpy.data.images.new("spike_tex", 4, 4)
    return img

# ---------------------------------------------------------------------------
print("\n=== Case A: TexCoord.UV -> Mapping -> Image -> Base Color ===")
matA, tA, bsdfA = new_mat("A")
tc  = tA.nodes.new("ShaderNodeTexCoord")
mp  = tA.nodes.new("ShaderNodeMapping")
im  = tA.nodes.new("ShaderNodeTexImage")
im.image = make_image()
mp.inputs["Scale"].default_value    = (2.0, 2.0, 1.0)
mp.inputs["Location"].default_value = (0.1, 0.0, 0.0)
tA.links.new(tc.outputs["UV"],   mp.inputs["Vector"])
tA.links.new(mp.outputs["Vector"], im.inputs["Vector"])
tA.links.new(im.outputs["Color"],  bsdfA.inputs["Base Color"])

rA = nt.transpile_material(matA)
print(rA.glsl)
print("  samplers:", [(s.uniform, s.image.name) for s in rA.samplers])
print("  notes:", rA.notes)
check(rA.ok, "A transpiles ok")
check("texture(" in rA.glsl, "A samples the image")
check(len(rA.samplers) == 1, "A registers exactly one sampler")
check("computeBaseColor" in rA.glsl, "A emits computeBaseColor entry")
check("2.0" in rA.glsl and "0.1" in rA.glsl, "A bakes mapping scale(2.0)+loc(0.1)")
# the image must be sampled with the MAPPED coords, not raw vUV:
import re as _re
m = _re.search(r"texture\(uTx_0,\s*(.+?)\);", rA.glsl)
sampled_with_map = bool(m) and "n_map" in m.group(1)
check(sampled_with_map, "A samples with MAPPED coords (UV distortion is live)")

# ---------------------------------------------------------------------------
print("\n=== Case C: change Mapping scale 2 -> 4 changes the GLSL ===")
mp.inputs["Scale"].default_value = (4.0, 4.0, 1.0)
rC = nt.transpile_material(matA)
check("4.0" in rC.glsl, "C reflects new scale 4.0 in GLSL")
check(rC.glsl != rA.glsl, "C output differs from A (distortion tracked)")

# ---------------------------------------------------------------------------
print("\n=== Case B: add a Mix node (Image mixed with red) -> Base Color ===")
matB, tB, bsdfB = new_mat("B")
tc2 = tB.nodes.new("ShaderNodeTexCoord")
im2 = tB.nodes.new("ShaderNodeTexImage"); im2.image = make_image()
try:
    mix = tB.nodes.new("ShaderNodeMix"); mix.data_type = 'RGBA'
    a_in, b_in, fac_in = "A", "B", "Factor"
    # RGBA Mix exposes duplicate-named sockets; pick the color ones by index
    col_inputs = [s for s in mix.inputs if s.type == 'RGBA']
    fac_sock = mix.inputs[fac_in]
    red_sock = col_inputs[1]
    tex_sock = col_inputs[0]
    out_sock = [s for s in mix.outputs if s.type == 'RGBA'][0]
except Exception:
    mix = tB.nodes.new("ShaderNodeMixRGB")
    fac_sock = mix.inputs["Fac"]; tex_sock = mix.inputs["Color1"]; red_sock = mix.inputs["Color2"]
    out_sock = mix.outputs["Color"]
fac_sock.default_value = 0.5
red_sock.default_value = (1.0, 0.0, 0.0, 1.0)
tB.links.new(tc2.outputs["UV"], im2.inputs["Vector"])
tB.links.new(im2.outputs["Color"], tex_sock)
tB.links.new(out_sock, bsdfB.inputs["Base Color"])

rB = nt.transpile_material(matB)
print(rB.glsl)
print("  notes:", rB.notes)
check(rB.ok, "B transpiles ok")
check("mix(" in rB.glsl, "B emits a mix() (the mix node shows live)")
check("texture(" in rB.glsl, "B still samples the image inside the mix")

# ---------------------------------------------------------------------------
print("\n=== Case D: material with no nodes -> flat diffuse ===")
matD = bpy.data.materials.new("D"); matD.use_nodes = False
matD.diffuse_color = (0.2, 0.4, 0.6, 1.0)
rD = nt.transpile_material(matD)
check(rD.ok, "D transpiles ok")
check("0.2" in rD.glsl and "0.4" in rD.glsl, "D uses flat diffuse_color")

# ---------------------------------------------------------------------------
print("\n=== Optional: try GPU compile (expected to be unavailable headless) ===")
try:
    import gpu
    full = ("in vec2 vUV;\nout vec4 outColor;\n" + rA.glsl
            + "\nvoid main(){ outColor = computeBaseColor(vUV); }")
    sh = gpu.types.GPUShader(
        "in vec2 pos; void main(){ gl_Position = vec4(pos,0.0,1.0); }", full)
    print("  GPU compile: SUCCESS (unexpected but great)")
except Exception as e:
    print("  GPU compile: not available headless ->", repr(e)[:90])
    print("  (expected — shader compile + visual is validated on the user's GPU)")

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
if FAILS:
    print("FAILED {} check(s):".format(len(FAILS)))
    for f in FAILS: print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
