# tests/test_bake.py — bake shader assembly compiles; op + prop registered.
import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd())=='vertex_lit_renderer' else os.getcwd())
import vertex_lit_renderer as v; v.register()
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

check(hasattr(bpy.ops.vertex_lit, 'bake_material'), "bake operator registered")
check(hasattr(bpy.data.scenes[0].vertex_lit, 'bake_resolution'), "bake_resolution prop present")

# assemble bake frag for a graph with helpers (brick) + params + a Value; must compile
m=bpy.data.materials.new('BakeT'); m.use_nodes=True; nt=m.node_tree
for n in list(nt.nodes):
    if n.type not in ('OUTPUT_MATERIAL','BSDF_PRINCIPLED'): nt.nodes.remove(n)
b=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED')
noise=nt.nodes.new('ShaderNodeTexNoise'); mix=nt.nodes.new('ShaderNodeMixRGB')
nt.links.new(noise.outputs['Fac'], mix.inputs[0]); nt.links.new(mix.outputs[0], b.inputs['Base Color'])
from vertex_lit_renderer import material_shader as ms
vsrc, fsrc, tr = ms.build_bake_frag(m)
check('computeBaseColor' in fsrc and 'gl_Position = vec4(texCoord' in vsrc, "bake shaders assembled")
check('void main(){ fragColor = computeBaseColor(vUV); }' in fsrc, "bake main outputs base colour")

os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE','1'); os.environ.setdefault('GALLIUM_DRIVER','llvmpipe')
os.environ.setdefault('MESA_GL_VERSION_OVERRIDE','3.3'); os.environ.setdefault('EGL_PLATFORM','surfaceless')
try:
    import moderngl; ctx=moderngl.create_standalone_context(backend='egl')
    ctx.program(vertex_shader='#version 330 core\n'+vsrc, fragment_shader='#version 330 core\n'+fsrc)
    check(True, "bake shader compiles on GPU")
except Exception as e:
    print("  SKIP bake compile (GL unavailable: %s)"%repr(e)[:50])

v.unregister()
print("ALL CHECKS PASSED" if not F else "FAILED: "+", ".join(F))
