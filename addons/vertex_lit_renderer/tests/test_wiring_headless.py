# tests/test_wiring_headless.py
"""
Headless validation of the live-material wiring.

Run: blender --background --factory-startup --python tests/test_wiring_headless.py

Cannot GPU-compile (no context in background) — that's confirmed on the user's
GPU. What THIS proves:
  1. The whole addon still imports + register()/unregister() cleanly with the
     new material_shader import, the props toggle, and the rewritten draw loop.
  2. build_material_frag() produces a complete, structurally-sane fragment for
     spike materials (declared samplers match usage; braces/parens balanced;
     computeBaseColor + main present).
"""
import bpy, sys, os, importlib.util

ADDONS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ADDONS)  # so `import vertex_lit_renderer` works

FAILS = []
def check(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond: FAILS.append(msg)

def balanced(s, o, c):
    d = 0
    for ch in s:
        if ch == o: d += 1
        elif ch == c:
            d -= 1
            if d < 0: return False
    return d == 0

# ---------------------------------------------------------------------------
print("\n=== 1. addon register / unregister ===")
import vertex_lit_renderer as vlr
try:
    vlr.register()
    reg_ok = True
except Exception as e:
    reg_ok = False
    print("   register() raised:", repr(e))
check(reg_ok, "addon register() succeeds")

sub = [c.__name__ for c in bpy.types.RenderEngine.__subclasses__()]
check("VertexLitEngine" in sub, "VertexLitEngine is registered as a RenderEngine")

sc = bpy.data.scenes[0] if bpy.data.scenes else bpy.data.scenes.new("t")
vls = getattr(sc, "vertex_lit", None)
check(vls is not None, "scene.vertex_lit property group present")
check(not hasattr(vls, "use_live_nodes"), "use_live_nodes toggle removed (live nodes always on)")
check(getattr(vls, "shading_mode", "") == "PIXEL", "shading_mode defaults to PIXEL")
check(getattr(vls, "use_shadows", True) is False, "shadows default OFF")

try:
    vlr.unregister(); unreg_ok = True
except Exception as e:
    unreg_ok = False
    print("   unregister() raised:", repr(e))
check(unreg_ok, "addon unregister() succeeds")

# ---------------------------------------------------------------------------
print("\n=== 2. build_material_frag structural check ===")
# import the module directly (no GPU calls in build_material_frag)
ms_path = os.path.join(ADDONS, "vertex_lit_renderer", "material_shader.py")
# material_shader imports .shaders and .node_transpiler → import as package member
import vertex_lit_renderer.material_shader as ms

def spike_mat():
    m = bpy.data.materials.new("wire"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    im = nt.nodes.new("ShaderNodeTexImage")
    im.image = bpy.data.images.new("wire_tex", 4, 4)
    mp.inputs["Scale"].default_value = (3.0, 3.0, 1.0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], im.inputs["Vector"])
    nt.links.new(im.outputs["Color"], bsdf.inputs["Base Color"])
    return m

mat = spike_mat()
_, frag, res = ms.build_material_frag(mat, "PIXEL")
print(frag)
check("void main()" in frag, "frag has main()")
check("computeBaseColor" in frag, "frag defines computeBaseColor")
check("out vec4 outColor" in frag, "frag declares outColor")
check("in vec2 vUV" in frag and "in vec3 vNrm" in frag, "frag declares per-pixel inputs")
check(balanced(frag, "{", "}"), "frag braces balanced")
check(balanced(frag, "(", ")"), "frag parens balanced")
# every declared sampler must be used, and every used uTx_ must be declared
import re
declared = set(re.findall(r"uniform sampler2D (uTx_\d+);", frag))
used = set(re.findall(r"texture\((uTx_\d+),", frag))
check(declared == used and len(declared) >= 1,
      "declared samplers exactly match used samplers ({})".format(sorted(declared)))

# fallback: unsupported node still yields a compilable-looking frag (magenta)
mat2 = bpy.data.materials.new("wire2"); mat2.use_nodes = True
nt2 = mat2.node_tree; nt2.nodes.clear()
out2 = nt2.nodes.new("ShaderNodeOutputMaterial")
bsdf2 = nt2.nodes.new("ShaderNodeBsdfPrincipled")
noise = nt2.nodes.new("ShaderNodeWireframe")  # unsupported in spike
nt2.links.new(bsdf2.outputs["BSDF"], out2.inputs["Surface"])
nt2.links.new(noise.outputs["Fac"], bsdf2.inputs["Base Color"])
_, frag2, res2 = ms.build_material_frag(mat2, "PIXEL")
check("void main()" in frag2 and balanced(frag2, "{", "}"),
      "unsupported node degrades to a structurally-valid frag")
check(any("neutralised" in n for n in res2.notes), "unsupported node neutralised + noted")

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
if FAILS:
    print("FAILED {} check(s):".format(len(FAILS)))
    for f in FAILS: print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
