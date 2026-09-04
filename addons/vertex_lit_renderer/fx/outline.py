# vertex_lit_renderer/fx/outline.py
"""
Object outline, matching Blender Workbench's approach: sample a per-object ID buffer
and draw the outline where a pixel's object ID differs from its neighbours. Opacity is
proportional to how many of the 4 neighbours differ (softer at corners), exactly like
Workbench's workbench_effect_outline_frag. Every object gets outlined — including
touching same-depth ones — unlike a depth-only silhouette.
"""
from .effect import ScreenEffect

_OUTLINE_FRAG = """
uniform sampler2D uColor;
uniform sampler2D uId;      /* per-object flat colour; background = (0,0,0) */
uniform vec2 uTexel;
uniform float uSize;        /* outline width in pixels */
uniform vec3 uLineColor;
in vec2 vUV;
out vec4 fragColor;

void main(){
    vec4 col = texture(uColor, vUV);
    vec2 o = uTexel * max(uSize, 1.0);
    vec3 c  = texture(uId, vUV).rgb;
    vec3 a0 = texture(uId, vUV + vec2(0.0, o.y)).rgb;
    vec3 a1 = texture(uId, vUV - vec2(0.0, o.y)).rgb;
    vec3 a2 = texture(uId, vUV + vec2(o.x, 0.0)).rgb;
    vec3 a3 = texture(uId, vUV - vec2(o.x, 0.0)).rgb;
    /* Workbench: opacity = 1 - fraction of neighbours whose id == centre id */
    float same = 0.0;
    same += (a0 == c) ? 0.25 : 0.0;
    same += (a1 == c) ? 0.25 : 0.0;
    same += (a2 == c) ? 0.25 : 0.0;
    same += (a3 == c) ? 0.25 : 0.0;
    float op = 1.0 - same;
    fragColor = vec4(mix(col.rgb, uLineColor, op), col.a);
}
"""


class Outline(ScreenEffect):
    name = "outline"
    uses_depth = False
    frag = _OUTLINE_FRAG

    def enabled(self, vls):
        return bool(getattr(vls, "use_outline", False))

    def run(self, color_tex, depth_tex, ctx):
        # bind the object-id buffer instead of depth
        sh = self.shader()
        sh.bind()
        try: sh.uniform_sampler('uColor', color_tex)
        except Exception: pass
        idt = ctx.get('id_tex')
        if idt is not None:
            try: sh.uniform_sampler('uId', idt)
            except Exception: pass
        self.set_uniforms(sh, ctx)
        self._batch.draw(sh)

    def set_uniforms(self, sh, ctx):
        def sf(n, v):
            try: sh.uniform_float(n, v)
            except Exception: pass
        sf('uTexel', ctx['texel'])
        sf('uSize', ctx.get('outline_size', 1.5))
        sf('uLineColor', ctx.get('outline_color', (0.0, 0.0, 0.0)))
