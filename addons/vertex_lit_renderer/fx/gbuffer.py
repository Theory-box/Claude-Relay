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
        self.aux = False
        self.color = None
        self.depth = None
        self.normal = None      # view normals, written by the main pass (aux mode)
        self.id = None          # object id colours, written by the main pass (aux mode)
        self.fb = None
        self.normal_fb = None   # normal target alone (for the splat normal pass)

    def ensure(self, w, h, aux=False):
        w = max(int(w), 1); h = max(int(h), 1)
        if self.fb is not None and w == self.w and h == self.h and aux == self.aux:
            return
        self.w, self.h, self.aux = w, h, aux
        self.color = gpu.types.GPUTexture((w, h), format='RGBA16F')
        self.depth = gpu.types.GPUTexture((w, h), format='DEPTH_COMPONENT32F')
        if aux:
            self.normal = gpu.types.GPUTexture((w, h), format='RGBA16F')
            self.id = gpu.types.GPUTexture((w, h), format='RGBA8')
            self.fb = gpu.types.GPUFrameBuffer(color_slots=(self.color, self.normal, self.id),
                                               depth_slot=self.depth)
            self.normal_fb = gpu.types.GPUFrameBuffer(color_slots=(self.normal,), depth_slot=self.depth)
        else:
            self.normal = self.id = self.normal_fb = None
            self.fb = gpu.types.GPUFrameBuffer(color_slots=(self.color,), depth_slot=self.depth)

    def free(self):
        self.color = None
        self.depth = None
        self.normal = self.id = self.normal_fb = None
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
