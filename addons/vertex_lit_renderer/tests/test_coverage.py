# tests/test_coverage.py
"""Node-coverage test: each supported node emits the expected GLSL tokens."""
import bpy, sys, os, importlib.util
_here = os.path.dirname(os.path.realpath(__file__))
def _imp(name):
    p = os.path.join(os.path.dirname(_here), name + ".py")
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
nt = _imp("node_transpiler")

FAILS = []
def check(c, m): print(("  PASS " if c else "  FAIL ") + m); (FAILS.append(m) if not c else None)

def base_tree(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    t = m.node_tree; t.nodes.clear()
    out = t.nodes.new("ShaderNodeOutputMaterial")
    bsdf = t.nodes.new("ShaderNodeBsdfPrincipled")
    t.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m, t, bsdf

def emit(name, build):
    m, t, bsdf = base_tree(name)
    node, out_sock = build(t)
    t.links.new(out_sock, bsdf.inputs["Base Color"])
    r = nt.transpile_material(m)
    return r

def balanced(s, o, c):
    d = 0
    for ch in s:
        d += (ch == o) - (ch == c)
        if d < 0: return False
    return d == 0

def std(r, label):
    check(r.ok, label + " ok")
    check(balanced(r.glsl, "{", "}") and balanced(r.glsl, "(", ")"), label + " balanced")
    check(not any("unsupported" in n for n in r.notes), label + " no-unsupported")

cases = []

def C(name, builder, token):
    def run():
        r = emit(name, builder)
        std(r, name)
        check(token in r.glsl, "{} emits '{}'".format(name, token))
    cases.append(run)

# Math ADD / MULTIPLY / SINE
C("math_add", lambda t: (lambda n: (n, n.outputs[0]))(_set(t.nodes.new("ShaderNodeMath"), operation="ADD")), "+")
C("math_mul", lambda t: (lambda n: (n, n.outputs[0]))(_set(t.nodes.new("ShaderNodeMath"), operation="MULTIPLY")), "*")
C("math_sin", lambda t: (lambda n: (n, n.outputs[0]))(_set(t.nodes.new("ShaderNodeMath"), operation="SINE")), "sin(")
# Vector math cross / normalize / dot
C("vmath_cross", lambda t: (lambda n: (n, n.outputs["Vector"]))(_set(t.nodes.new("ShaderNodeVectorMath"), operation="CROSS_PRODUCT")), "cross(")
C("vmath_norm", lambda t: (lambda n: (n, n.outputs["Vector"]))(_set(t.nodes.new("ShaderNodeVectorMath"), operation="NORMALIZE")), "normalize(")
C("vmath_dot", lambda t: (lambda n: (n, n.outputs["Value"]))(_set(t.nodes.new("ShaderNodeVectorMath"), operation="DOT_PRODUCT")), "dot(")
# Map range / clamp
C("maprange", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeMapRange")), "_sdiv(")
C("clamp", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeClamp")), "clamp(")
# Hue/Sat, Gamma, Invert, Bright/Contrast
C("huesat", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeHueSaturation")), "_rgb2hsv(")
C("gamma", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeGamma")), "pow(")
C("invert", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeInvert")), "mix(")
C("brightcontrast", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeBrightContrast")), "1.0 + ")
# Separate/Combine XYZ
C("combxyz", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeCombineXYZ")), "vec4(")
# RGB / Value (uniformized)
C("rgb", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeRGB")), "uP_")
C("value", lambda t: (lambda n: (n, n.outputs[0]))(t.nodes.new("ShaderNodeValue")), "uP_")
# ColorRamp
C("colorramp", lambda t: (lambda n: (n, n.outputs["Color"]))(t.nodes.new("ShaderNodeValToRGB")), "mix(")
# Mix ADD blend
def _mix_add(t):
    n = t.nodes.new("ShaderNodeMixRGB"); n.blend_type = "ADD"; return (n, n.outputs["Color"])
C("mix_add", _mix_add, "+")

def _set(node, **kw):
    for k, v in kw.items(): setattr(node, k, v)
    return node

print("=== node coverage ===")
for run in cases:
    run()

# structure signature: changing Math operation must change signature
print("\n=== signature tracks operation change ===")
m, t, bsdf = base_tree("op")
mn = t.nodes.new("ShaderNodeMath"); mn.operation = "ADD"
t.links.new(mn.outputs[0], bsdf.inputs["Base Color"])
s1 = nt.topo_signature(m); mn.operation = "MULTIPLY"; s2 = nt.topo_signature(m)
check(s1 != s2, "operation change alters signature (forces recompile)")

print("\n================ SUMMARY ================")
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL CHECKS PASSED")
sys.exit(1 if FAILS else 0)
