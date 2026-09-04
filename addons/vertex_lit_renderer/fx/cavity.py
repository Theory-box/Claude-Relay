# vertex_lit_renderer/fx/cavity.py
"""
Cavity (curvature) effect — Blender Workbench-style screen-space curvature.

Reads a view-space normal buffer and, from the screen-space derivative of the
normal, decides whether each pixel sits on a convex edge (a ridge) or in a
concave crevice (a valley):

    curvature = (normal_up.y - normal_down.y) + (normal_right.x - normal_left.x)

    curvature > 0  -> convex  -> ridge  -> brighten  (the "reverse AO")
    curvature < 0  -> concave -> valley -> darken

The object-id buffer (already produced for the outline) is used to skip the
boundary between two different objects so curvature doesn't bleed across
silhouettes. If no id buffer is present the guard is simply skipped.
"""
from .effect import ScreenEffect

_CAVITY_FRAG = """
uniform sampler2D uColor;
uniform sampler2D uNormal;   /* view normals, encoded *0.5+0.5 */
uniform sampler2D uId;
uniform vec2 uTexel;
uniform float uRidge;
uniform float uValley;
uniform int uHasId;
in vec2 vUV;
out vec4 fragColor;

vec3 decodeN(vec2 uv){ return texture(uNormal, uv).xyz * 2.0 - 1.0; }

void main(){
    vec4 col = texture(uColor, vUV);
    vec2 t = uTexel;

    /* skip curvature across an object boundary (like Workbench) */
    if(uHasId == 1){
        vec3 iu = texture(uId, vUV + vec2(0.0, t.y)).rgb;
        vec3 id = texture(uId, vUV - vec2(0.0, t.y)).rgb;
        vec3 ir = texture(uId, vUV + vec2(t.x, 0.0)).rgb;
        vec3 il = texture(uId, vUV - vec2(t.x, 0.0)).rgb;
        if(iu != id || ir != il){ fragColor = col; return; }
    }

    vec3 nu = decodeN(vUV + vec2(0.0, t.y));
    vec3 nd = decodeN(vUV - vec2(0.0, t.y));
    vec3 nr = decodeN(vUV + vec2(t.x, 0.0));
    vec3 nl = decodeN(vUV - vec2(t.x, 0.0));

    float curv = (nu.y - nd.y) + (nr.x - nl.x);
    float factor = (curv < 0.0) ? (1.0 + curv * uValley)   /* valley: darken */
                                : (1.0 + curv * uRidge);   /* ridge:  brighten */
    factor = clamp(factor, 0.0, 4.0);
    fragColor = vec4(col.rgb * factor, col.a);
}
"""


class Cavity(ScreenEffect):
    name = "cavity"
    uses_depth = False
    frag = _CAVITY_FRAG

    def enabled(self, vls):
        # Needs the view-normal buffer; if it wasn't produced this frame, do nothing.
        return bool(getattr(vls, "use_cavity", False))

    def run(self, color_tex, depth_tex, ctx):
        sh = self.shader()
        sh.bind()
        nrm = ctx.get('normal_tex')
        passthrough = nrm is None   # no normal buffer -> pass colour through unchanged
        idt = ctx.get('id_tex')
        try: sh.uniform_sampler('uColor', color_tex)
        except Exception: pass
        try: sh.uniform_sampler('uNormal', nrm if nrm is not None else color_tex)
        except Exception: pass
        try: sh.uniform_sampler('uId', idt if idt is not None else color_tex)
        except Exception: pass
        try: sh.uniform_int('uHasId', 0 if (passthrough or idt is None) else 1)
        except Exception: pass
        def sf(n, val):
            try: sh.uniform_float(n, val)
            except Exception: pass
        sf('uTexel', ctx['texel'])
        # ridge/valley 0 when passing through -> factor 1.0 -> colour unchanged (never black)
        sf('uRidge', 0.0 if passthrough else ctx.get('cavity_ridge', 1.0))
        sf('uValley', 0.0 if passthrough else ctx.get('cavity_valley', 1.0))
        self._batch.draw(sh)

    def set_uniforms(self, sh, ctx):
        pass
