# tests/gl_harness.py
"""
CPU GL test harness.

Compiles the transpiler's computeBaseColor() GLSL on a *software* OpenGL 3.3
context (Mesa llvmpipe via EGL) and renders it over a UV grid, so node ports can
be validated on-machine WITHOUT a GPU:
  - catches GLSL COMPILE errors (the class of bug we otherwise ship blind), and
  - reads back pixels so we can assert on actual node output values.

Run inside Blender's Python (needs bpy for the node tree + moderngl for GL):
    blender --background --factory-startup --python tests/test_gl_*.py

Requires moderngl installed into Blender's Python and Mesa software GL. The env
vars below force the software path.
"""
import os
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
os.environ.setdefault("MESA_GL_VERSION_OVERRIDE", "3.3")
os.environ.setdefault("EGL_PLATFORM", "surfaceless")

import numpy as np
import importlib.util

_here = os.path.dirname(os.path.realpath(__file__))

def _imp(name):
    p = os.path.join(os.path.dirname(_here), name + ".py")
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

_nt = _imp("node_transpiler")

_ctx = None
def _context():
    global _ctx
    if _ctx is None:
        import moderngl
        _ctx = moderngl.create_standalone_context(backend="egl")
    return _ctx


class CompileError(Exception):
    pass


def _default_texture(ctx, size=16):
    # Gradient: R=u, G=v, B=0.5 — lets tests verify UV-space sampling.
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32) / (size - 1)
    img = np.zeros((size, size, 4), dtype=np.float32)
    img[..., 0] = xs; img[..., 1] = ys; img[..., 2] = 0.5; img[..., 3] = 1.0
    data = (img * 255).astype(np.uint8).tobytes()
    return ctx.texture((size, size), 4, data)


def render_material(mat, size=16, param_values=None, textures=None):
    """
    Transpile `mat`, compile computeBaseColor(), render it over a size×size UV
    grid, return (pixels[H,W,4] float 0..1, transpile_result).
    Raises CompileError on a GLSL compile failure.

    param_values: {uniform_name: value} overrides for uP_* params (else 0.5 / grey).
    textures:     {uniform_name: (size, rgba_float_array)} for uTx_* (else gradient).
    """
    import moderngl
    ctx = _context()
    res = _nt.transpile_material(mat)

    sampler_decls = "".join("uniform sampler2D {};\n".format(s.uniform) for s in res.samplers)
    param_decls = "".join(d + "\n" for d in res.param_decls)
    frag = ("#version 330 core\n"
            "in vec2 vUV;\nout vec4 fragColor;\n"
            + sampler_decls + param_decls + _nt.HELPERS + "\n"
            + res.glsl + "\n"
            + "void main(){ fragColor = computeBaseColor(vUV); }\n")
    vert = ("#version 330 core\n"
            "in vec2 p; out vec2 vUV;\n"
            "void main(){ vUV = p*0.5+0.5; gl_Position = vec4(p,0.0,1.0); }\n")
    try:
        prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
    except Exception as e:
        raise CompileError("{}\n---FRAG---\n{}".format(e, frag))

    # bind samplers
    tex_objs = []
    for i, s in enumerate(res.samplers):
        if textures and s.uniform in textures:
            sz, arr = textures[s.uniform]
            t = ctx.texture((sz, sz), 4, (np.clip(arr, 0, 1) * 255).astype(np.uint8).tobytes())
        else:
            t = _default_texture(ctx)
        t.use(location=i); tex_objs.append(t)
        if s.uniform in prog:
            prog[s.uniform] = i

    # set params
    for p in res.params:
        val = (param_values or {}).get(p.uniform)
        if val is None:
            val = {"float": 0.5, "vec2": (0.5, 0.5),
                   "vec3": (0.5, 0.5, 0.5), "vec4": (0.5, 0.5, 0.5, 1.0)}[p.want]
        if p.uniform in prog:
            try: prog[p.uniform] = val
            except Exception: pass

    fbo = ctx.framebuffer(color_attachments=[ctx.texture((size, size), 4, dtype="f1")])
    fbo.use()
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
    vao = ctx.vertex_array(prog, [(quad, "2f", "p")])
    vao.render(moderngl.TRIANGLE_STRIP)
    px = np.frombuffer(fbo.read(components=4), dtype=np.uint8).reshape(size, size, 4).astype(np.float32) / 255.0

    for t in tex_objs: t.release()
    fbo.release(); vao.release(); quad.release()
    return px, res


def compiles(mat):
    """True if the material's computeBaseColor compiles on the software context."""
    try:
        render_material(mat, size=4)
        return True, ""
    except CompileError as e:
        return False, str(e)[:400]
