# tests/test_fx.py — compile-check screen-effect shaders on software GL.
# (Offscreen pipeline + AO look are GPU-side; this only guards the GLSL.)
import os, re, sys
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE","1"); os.environ.setdefault("GALLIUM_DRIVER","llvmpipe")
os.environ.setdefault("MESA_GL_VERSION_OVERRIDE","3.3"); os.environ.setdefault("EGL_PLATFORM","surfaceless")
_here=os.path.dirname(os.path.realpath(__file__)); _fx=os.path.join(os.path.dirname(_here),"fx")
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)
def grab(path, var):
    s=open(path).read(); m=re.search(var+r'\s*=\s*"""(.*?)"""', s, re.S); return m.group(1) if m else None
FS_VERT=grab(os.path.join(_fx,"effect.py"),"FS_VERT")
SSAO=grab(os.path.join(_fx,"ssao.py"),"_SSAO_FRAG")
OUTLINE=grab(os.path.join(_fx,"outline.py"),"_OUTLINE_FRAG")
import moderngl
ctx=moderngl.create_standalone_context(backend="egl")
def compiles(frag):
    try:
        p=ctx.program(vertex_shader="#version 330 core\n"+FS_VERT, fragment_shader="#version 330 core\n"+frag)
        return True, [n for n in p]
    except Exception as e:
        return False, str(e)[:300]
ok,info=compiles(SSAO)
check(ok, "SSAO fragment compiles" + ("" if ok else " :: "+str(info)))
check(ok and 'uDepth' in info and 'uProj' in info and 'uInvProj' in info, "SSAO exposes depth + projection uniforms")
ok2,info2=compiles(OUTLINE)
check(ok2, "Outline fragment compiles" + ("" if ok2 else " :: "+str(info2)))
check(ok2 and 'uSize' in info2 and 'uLineColor' in info2 and 'uId' in info2, "Outline exposes id + size + colour uniforms")
print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
