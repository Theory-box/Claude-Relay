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

    def any_enabled(self, vls):
        return any(e.enabled(vls) for e in self.effects)

    def render(self, w, h, draw_scene, ctx, vls):
        """draw_scene: a zero-arg callable that draws the lit scene (opaque) with
        depth into the currently-bound framebuffer."""
        self.gbuf.ensure(w, h)
        self.ping.ensure(w, h)

        # 1) scene -> gbuffer (colour + depth)
        with self.gbuf.fb.bind():
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(True)
            self.gbuf.fb.clear(color=(0.0, 0.0, 0.0, 1.0), depth=1.0)
            draw_scene()

        # 2) run enabled effects, bouncing between ping targets
        cur = self.gbuf.color
        idx = 0
        ran_any = False
        for e in self.effects:
            if not e.enabled(vls):
                continue
            with self.ping.fb[idx].bind():
                gpu.state.depth_test_set('NONE')
                gpu.state.depth_mask_set(False)
                e.run(cur, self.gbuf.depth, ctx)
            cur = self.ping.tex[idx]
            idx ^= 1
            ran_any = True

        # 3) blit final colour to the viewport (already-bound default framebuffer)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
        draw_texture_2d(cur, (0, 0), w, h)
        return ran_any

    def free(self):
        self.gbuf.free()
        self.ping.free()
        for e in self.effects:
            e.free()
