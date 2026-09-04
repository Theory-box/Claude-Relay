# vertex_lit_renderer/fx/fxaa.py
"""
FXAA — fast approximate anti-aliasing. A single fullscreen pass that softens
high-contrast edges from the luma of the neighbouring pixels. Runs last in the
pipeline so it smooths the final composited image (including outlines).
"""
from .effect import ScreenEffect

_FXAA_FRAG = """
uniform sampler2D uColor;
uniform vec2 uTexel;
in vec2 vUV;
out vec4 fragColor;

float luma(vec3 c){ return dot(c, vec3(0.299, 0.587, 0.114)); }

void main(){
    vec3 rgbM = texture(uColor, vUV).rgb;
    float lM  = luma(rgbM);
    float lNW = luma(texture(uColor, vUV + vec2(-uTexel.x, -uTexel.y)).rgb);
    float lNE = luma(texture(uColor, vUV + vec2( uTexel.x, -uTexel.y)).rgb);
    float lSW = luma(texture(uColor, vUV + vec2(-uTexel.x,  uTexel.y)).rgb);
    float lSE = luma(texture(uColor, vUV + vec2( uTexel.x,  uTexel.y)).rgb);

    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    if(lMax - lMin < 0.05){ fragColor = vec4(rgbM, texture(uColor, vUV).a); return; }

    vec2 dir;
    dir.x = -((lNW + lNE) - (lSW + lSE));
    dir.y =  ((lNW + lSW) - (lNE + lSE));
    float reduce = max((lNW + lNE + lSW + lSE) * 0.25 * 0.125, 1.0/128.0);
    float rcp = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
    dir = clamp(dir * rcp, vec2(-8.0), vec2(8.0)) * uTexel;

    vec3 rgbA = 0.5 * (texture(uColor, vUV + dir * (1.0/3.0 - 0.5)).rgb +
                       texture(uColor, vUV + dir * (2.0/3.0 - 0.5)).rgb);
    vec3 rgbB = rgbA * 0.5 + 0.25 * (texture(uColor, vUV + dir * -0.5).rgb +
                                     texture(uColor, vUV + dir *  0.5).rgb);
    float lB = luma(rgbB);
    vec3 outc = (lB < lMin || lB > lMax) ? rgbA : rgbB;
    fragColor = vec4(outc, texture(uColor, vUV).a);
}
"""


class FXAA(ScreenEffect):
    name = "fxaa"
    uses_depth = False
    frag = _FXAA_FRAG

    def enabled(self, vls):
        return getattr(vls, "aa_method", "OFF") == 'FXAA'

    def set_uniforms(self, sh, ctx):
        try: sh.uniform_float('uTexel', ctx['texel'])
        except Exception: pass
