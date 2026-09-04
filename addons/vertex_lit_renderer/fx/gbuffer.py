# vertex_lit_renderer/fx/gbuffer.py
"""
Off-screen render target for the post pipeline: a colour texture + a sampleable
depth texture, wrapped in a GPUFrameBuffer. The scene is drawn into this instead
of straight to the viewport, so screen-space effects (AO now; SSR/DoF later) can
read colour AND depth. Recreated on viewport resize; freed on engine teardown.
"""
import gpu


class GBuffer:
    def __init__(self):
        self.w = 0
        self.h = 0
        self.color = None
        self.depth = None
        self.fb = None

    def ensure(self, w, h):
        w = max(int(w), 1); h = max(int(h), 1)
        if self.fb is not None and w == self.w and h == self.h:
            return
        self.w, self.h = w, h
        self.color = gpu.types.GPUTexture((w, h), format='RGBA16F')
        self.depth = gpu.types.GPUTexture((w, h), format='DEPTH_COMPONENT32F')
        self.fb = gpu.types.GPUFrameBuffer(color_slots=(self.color,), depth_slot=self.depth)

    def free(self):
        self.color = None
        self.depth = None
        self.fb = None
        self.w = self.h = 0


class PingPong:
    """Two colour targets to bounce chained effects between."""
    def __init__(self):
        self.w = self.h = 0
        self.tex = [None, None]
        self.fb = [None, None]

    def ensure(self, w, h):
        w = max(int(w), 1); h = max(int(h), 1)
        if self.fb[0] is not None and w == self.w and h == self.h:
            return
        self.w, self.h = w, h
        for i in range(2):
            self.tex[i] = gpu.types.GPUTexture((w, h), format='RGBA16F')
            self.fb[i] = gpu.types.GPUFrameBuffer(color_slots=(self.tex[i],))

    def free(self):
        self.tex = [None, None]
        self.fb = [None, None]
        self.w = self.h = 0
