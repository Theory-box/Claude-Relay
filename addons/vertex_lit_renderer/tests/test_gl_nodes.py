# tests/test_gl_nodes.py — per-node OUTPUT verification on the CPU GL harness.
# Grows as nodes are ported. Each check renders real GLSL and asserts pixel values.
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
def rgb(t, col):
    n=t.nodes.new('ShaderNodeRGB'); n.outputs[0].default_value=col; return n

# --- RGB to BW (Rec.709 luminance) ---
def bw(col):
    m,t,b=base('bw'); src=rgb(t,col); n=t.nodes.new('ShaderNodeRGBToBW')
    t.links.new(src.outputs[0], n.inputs['Color']); t.links.new(n.outputs[0], b.inputs['Base Color'])
    px,_=H.render_material(m,size=4); return px[...,0].mean()
check(abs(bw((1,1,1,1))-1.0)<0.02, "RGBtoBW white = 1.0")
check(abs(bw((1,0,0,1))-0.2127)<0.02, "RGBtoBW red = 0.213")
check(abs(bw((0,1,0,1))-0.7152)<0.02, "RGBtoBW green = 0.715")
check(abs(bw((0,0,1,1))-0.0722)<0.02, "RGBtoBW blue = 0.072")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
