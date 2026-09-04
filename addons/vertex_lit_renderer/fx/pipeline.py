# vertex_lit_renderer/fx/pipeline.py
"""
The screen-space post pipeline.

render(): draw the scene into the G-buffer (colour+depth), run each enabled
effect as a fullscreen pass (ping-ponging colour targets), then blit the final
colour to the viewport. When nothing is enabled the engine skips the pipeline
entirely and draws straight to the viewport (zero overhead / zero risk).

Modular by design: `effects` is just an ordered list of ScreenEffect instances.
Reorder or add (SSR, compositing, DoF) without touching the engine.
"""
import gpu
from gpu_extras.presets import draw_texture_2d

from .gbuffer import GBuffer, PingPong


class Pipeline:
    def __init__(self, effects):
        self.effects = effects
        self.gbuf = GBuffer()
        self.ping = PingPong()
        self._aod = None; self._aod_dummy = None; self._aod_fb = None
        self._aod_w = self._aod_h = 0
        self._id = None; self._id_depth = None; self._id_fb = None
        self._id_w = self._id_h = 0
        self._nrm = None; self._nrm_depth = None; self._nrm_fb = None
        self._nrm_w = self._nrm_h = 0

    def _ensure_normal(self, w, h):
        if self._nrm_fb is not None and w == self._nrm_w and h == self._nrm_h:
            return
        self._nrm_w, self._nrm_h = w, h
        self._nrm = gpu.types.GPUTexture((w, h), format='RGBA16F')
        self._nrm_depth = gpu.types.GPUTexture((w, h), format='DEPTH_COMPONENT32F')
        self._nrm_fb = gpu.types.GPUFrameBuffer(color_slots=(self._nrm,), depth_slot=self._nrm_depth)

    def any_enabled(self, vls):
        if any(e.enabled(vls) for e in self.effects):
            return True
        # Supersampling runs through the pipeline too, even with no other effect on.
        return getattr(vls, 'supersampling', '1') not in ('1', '', None)

    def _ensure_ao_depth(self, w, h):
        w = max(int(w), 1); h = max(int(h), 1)
        if self._aod_fb is not None and w == self._aod_w and h == self._aod_h:
            return
        self._aod_w, self._aod_h = w, h
        self._aod = gpu.types.GPUTexture((w, h), format='DEPTH_COMPONENT32F')
        self._aod_dummy = gpu.types.GPUTexture((w, h), format='RGBA8')
        self._aod_fb = gpu.types.GPUFrameBuffer(color_slots=(self._aod_dummy,), depth_slot=self._aod)

    def _ensure_id(self, w, h):
        w = max(int(w), 1); h = max(int(h), 1)
        if self._id_fb is not None and w == self._id_w and h == self._id_h:
            return
        self._id_w, self._id_h = w, h
        self._id = gpu.types.GPUTexture((w, h), format='RGBA8')
        self._id_depth = gpu.types.GPUTexture((w, h), format='DEPTH_COMPONENT32F')
        self._id_fb = gpu.types.GPUFrameBuffer(color_slots=(self._id,), depth_slot=self._id_depth)

    def render(self, w, h, draw_scene, ctx, vls):
        # Supersampling: render the whole pipeline at ss*resolution and downscale on the
        # final blit for smooth edges (SSAA). ss=1 -> no change.
        ss = {'1': 1.0, '1.5': 1.5, '2': 2.0}.get(getattr(vls, 'supersampling', '1'), 1.0)
        sw, sh = max(int(w * ss), 1), max(int(h * ss), 1)
        self.gbuf.ensure(sw, sh)
        self.ping.ensure(sw, sh)
        ctx['texel'] = (1.0 / sw, 1.0 / sh)   # effects sample at the supersampled resolution

        # 1) scene -> gbuffer (colour + depth)
        with self.gbuf.fb.bind():
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            self.gbuf.fb.clear(color=ctx.get('clear_color', (0.08, 0.08, 0.08, 1.0)), depth=1.0)
            draw_scene()

        # 1b) AO exclusion: render only the non-excluded occluders into a separate depth
        #     buffer; AO samples that so flagged objects don't cast (or receive) AO.
        aod = ctx.get('draw_ao_occluders')
        if aod is not None:
            self._ensure_ao_depth(sw, sh)
            with self._aod_fb.bind():
                gpu.state.depth_test_set('LESS_EQUAL')
                gpu.state.depth_mask_set(True)
                self._aod_fb.clear(color=(0.0, 0.0, 0.0, 1.0), depth=1.0)
                aod()
            ctx['ao_depth_tex'] = self._aod

        # 1c) Object-ID pass for the outline effect (Workbench-style).
        idd = ctx.get('draw_object_ids')
        if idd is not None:
            self._ensure_id(sw, sh)
            with self._id_fb.bind():
                gpu.state.depth_test_set('LESS_EQUAL')
                gpu.state.depth_mask_set(True)
                self._id_fb.clear(color=(0.0, 0.0, 0.0, 1.0), depth=1.0)
                idd()
            ctx['id_tex'] = self._id

        # 1d) View-space normal pass for the Cavity (curvature) effect.
        nrm = ctx.get('draw_view_normals')
        if nrm is not None:
            self._ensure_normal(sw, sh)
            with self._nrm_fb.bind():
                gpu.state.depth_test_set('LESS_EQUAL')
                gpu.state.depth_mask_set(True)
                # clear to the "flat toward camera" normal (0,0,1) encoded -> (0.5,0.5,1)
                self._nrm_fb.clear(color=(0.5, 0.5, 1.0, 1.0), depth=1.0)
                nrm()
            ctx['normal_tex'] = self._nrm

        # 2) run enabled effects, bouncing between ping targets
        cur = self.gbuf.color
        idx = 0
        for e in self.effects:
            if not e.enabled(vls):
                continue
            with self.ping.fb[idx].bind():
                gpu.state.depth_test_set('NONE')
                gpu.state.depth_mask_set(False)
                e.run(cur, self.gbuf.depth, ctx)
            cur = self.ping.tex[idx]
            idx ^= 1

        # 3) blit final colour to the target framebuffer, downscaling sw,sh -> w,h (SSAA)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
        draw_texture_2d(cur, (0, 0), w, h)
        return True

    def free(self):
        self.gbuf.free()
        self.ping.free()
        self._aod = self._aod_dummy = self._aod_fb = None
        self._id = self._id_depth = self._id_fb = None
        for e in self.effects:
            e.free()
