# vertex_lit_renderer/fx/effect.py
"""
Base class for a screen-space post effect (a single fullscreen fragment pass).

Every effect subclasses ScreenEffect, provides a `frag` shader that reads
`uColor` (+ optionally `uDepth`) and writes the new colour, and implements
`enabled()` and `set_uniforms()`. The pipeline (fx/pipeline.py) chains enabled
effects, ping-ponging colour buffers between them. Add a new effect (SSR,
compositing, DoF...) by dropping a new module here and registering it in
fx/__init__.py — no engine changes needed.
"""
import gpu
from gpu_extras.batch import batch_for_shader

# Fullscreen-triangle vertex shader shared by all effects.
FS_VERT = """
in vec2 pos;
out vec2 vUV;
void main(){ vUV = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""


class ScreenEffect:
    name = "effect"
    frag = ""          # subclass provides the fragment shader body (with #version-less GLSL)
    uses_depth = False

    def __init__(self):
        self._shader = None
        self._batch = None

    def enabled(self, vls):
        """Return True if this effect should run given the scene settings."""
        return False

    def set_uniforms(self, shader, ctx):
        """Push effect-specific uniforms (matrices, params). Base sets none."""
        pass

    # -- internals -----------------------------------------------------------
    def shader(self):
        if self._shader is None:
            self._shader = gpu.types.GPUShader(FS_VERT, self.frag)
            self._batch = batch_for_shader(
                self._shader, 'TRIS', {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]})
        return self._shader

    def run(self, color_tex, depth_tex, ctx):
        sh = self.shader()
        sh.bind()
        try: sh.uniform_sampler('uColor', color_tex)
        except Exception: pass
        if self.uses_depth and depth_tex is not None:
            try: sh.uniform_sampler('uDepth', depth_tex)
            except Exception: pass
        self.set_uniforms(sh, ctx)
        self._batch.draw(sh)

    def free(self):
        self._shader = None
        self._batch = None
