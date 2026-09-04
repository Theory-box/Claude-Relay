# vertex_lit_renderer/fx/outline.py
"""
Freestyle-ish object outline (like Workbench's). Detects silhouette edges from the
depth buffer — where a pixel's view-space depth jumps relative to its neighbours, or
an object meets the background — and paints the outline colour there. The sample
offset is the outline WIDTH in pixels (uSize).
"""
from .effect import ScreenEffect

_OUTLINE_FRAG = """
uniform sampler2D uColor;
uniform sampler2D uDepth;
uniform mat4 uInvProj;
uniform vec2 uTexel;
uniform float uSize;        /* outline width in pixels */
uniform float uThreshold;   /* depth-edge sensitivity (view-space, relative) */
uniform vec3 uLineColor;
in vec2 vUV;
out vec4 fragColor;

float view_z(vec2 uv){
    float z = texture(uDepth, uv).r;
    vec4 clip = vec4(uv * 2.0 - 1.0, z * 2.0 - 1.0, 1.0);
    vec4 v = uInvProj * clip;
    return v.z / v.w;   /* view-space z (negative in front of camera) */
}

void main(){
    vec4 col = texture(uColor, vUV);
    float zc = texture(uDepth, vUV).r;
    vec2 o = uTexel * max(uSize, 1.0);

    /* object -> background silhouette (a neighbour is at the far plane) */
    float zl = texture(uDepth, vUV - vec2(o.x, 0.0)).r;
    float zr = texture(uDepth, vUV + vec2(o.x, 0.0)).r;
    float zd = texture(uDepth, vUV - vec2(0.0, o.y)).r;
    float zu = texture(uDepth, vUV + vec2(0.0, o.y)).r;
    float bg = (zc < 1.0 && (zl >= 1.0 || zr >= 1.0 || zd >= 1.0 || zu >= 1.0)) ? 1.0 : 0.0;

    /* depth discontinuity between objects, measured in view space (scale-tolerant) */
    float vz = view_z(vUV);
    float md = 0.0;
    md = max(md, abs(vz - view_z(vUV - vec2(o.x, 0.0))));
    md = max(md, abs(vz - view_z(vUV + vec2(o.x, 0.0))));
    md = max(md, abs(vz - view_z(vUV - vec2(0.0, o.y))));
    md = max(md, abs(vz - view_z(vUV + vec2(0.0, o.y))));
    float rel = md / max(abs(vz), 1e-3);
    float disc = (zc < 1.0) ? smoothstep(uThreshold, uThreshold * 3.0, rel) : 0.0;

    float edge = max(bg, disc);
    fragColor = vec4(mix(col.rgb, uLineColor, edge), col.a);
}
"""


class Outline(ScreenEffect):
    name = "outline"
    uses_depth = True
    frag = _OUTLINE_FRAG

    def enabled(self, vls):
        return bool(getattr(vls, "use_outline", False))

    def set_uniforms(self, sh, ctx):
        def sf(n, v):
            try: sh.uniform_float(n, v)
            except Exception: pass
        sf('uInvProj', ctx['inv_proj'])
        sf('uTexel', ctx['texel'])
        sf('uSize', ctx.get('outline_size', 1.5))
        sf('uThreshold', ctx.get('outline_threshold', 0.15))
        sf('uLineColor', ctx.get('outline_color', (0.0, 0.0, 0.0)))
