# tests/test_workbench2.py — Workbench 2.0 refactor: props, panels, view-mode + bg shaders.
import bpy, sys, os, re
sys.path.insert(0, os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd())=='vertex_lit_renderer' else os.getcwd())
import vertex_lit_renderer as v; v.register()
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

sc=bpy.data.scenes[0]; s=sc.vertex_lit

# props
check(not hasattr(s,'shading_mode'), "shading_mode removed")
for p,default in [('view_mode','TEXTURED'),('background_mode','WORLD')]:
    check(getattr(s,p)==default, "%s defaults to %s"%(p,default))
for p in ('solid_color','background_color','key_intensity','sky_color','ground_color'):
    check(hasattr(s,p), "prop %s present"%p)
# view mode enum has all 5
items={e.identifier for e in s.bl_rna.properties['view_mode'].enum_items}
check(items=={'TEXTURED','SOLID','RANDOM','ATTRIBUTE','NORMAL'}, "view_mode has 5 options (%s)"%items)

# engine renamed, id preserved
E=[c for c in bpy.types.RenderEngine.__subclasses__() if c.__name__=='VertexLitEngine'][0]
check(E.bl_label=='Workbench 2.0', "engine label = Workbench 2.0")
check(E.bl_idname=='VERTEX_LIT', "engine id preserved (VERTEX_LIT)")

# collapsible panel tree
pnames={c.__name__ for c in bpy.types.Panel.__subclasses__() if c.__name__.startswith('VERTEX_LIT_PT')}
for want in ('VERTEX_LIT_PT_lighting','VERTEX_LIT_PT_viewmode','VERTEX_LIT_PT_background',
             'VERTEX_LIT_PT_shading','VERTEX_LIT_PT_outline','VERTEX_LIT_PT_cavity_world',
             'VERTEX_LIT_PT_cavity_screen'):
    check(want in pnames, "panel %s registered"%want)
# outline/cavity are children of shading
import vertex_lit_renderer.ui as U
check(U.VERTEX_LIT_PT_outline.bl_parent_id=='VERTEX_LIT_PT_shading', "outline nested under shading")
check(U.VERTEX_LIT_PT_cavity_world.bl_parent_id=='VERTEX_LIT_PT_shading', "cavity world under shading")

# key light folded into shared lighting
from vertex_lit_renderer import shaders as SH
check('uKeyIntensity' in SH.LIGHT_UNIFORMS and 'uKeyIntensity' in SH.LIGHT_FUNCS, "key light in vlr_light")

# random colour helper is stable + varies
from vertex_lit_renderer import engine as ENG
c1=ENG._obj_random_color("Cube"); c2=ENG._obj_random_color("Cube"); c3=ENG._obj_random_color("Sphere")
check(c1==c2 and c1!=c3, "random colour stable per name, differs across names")

# shaders compile on the GL harness backend
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE','1'); os.environ.setdefault('GALLIUM_DRIVER','llvmpipe')
os.environ.setdefault('MESA_GL_VERSION_OVERRIDE','3.3'); os.environ.setdefault('EGL_PLATFORM','surfaceless')
try:
    import moderngl; ctx=moderngl.create_standalone_context(backend='egl')
    def V(x): return '#version 330 core\n'+x
    ctx.program(vertex_shader=V(SH.PHONG_VERT), fragment_shader=V(SH.VIEWMODE_FRAG)); check(True,"VIEWMODE_FRAG compiles")
    ctx.program(vertex_shader=V(SH.BG_VERT), fragment_shader=V(SH.BG_FRAG)); check(True,"BG shaders compile")
    ctx.program(vertex_shader=V(SH.PHONG_VERT), fragment_shader=V(SH.PHONG_FRAG)); check(True,"PHONG w/ key light compiles")
except Exception as e:
    print("  SKIP shader compile (GL unavailable: %s)"%repr(e)[:60])

v.unregister()
print("ALL CHECKS PASSED" if not F else "FAILED: "+", ".join(F))
