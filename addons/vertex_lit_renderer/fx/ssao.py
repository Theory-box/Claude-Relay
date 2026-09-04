# vertex_lit_renderer/fx/ssao.py
"""
Screen-space ambient occlusion. Reconstructs view-space position from the depth
buffer, reconstructs a normal from depth derivatives, samples a hemisphere
kernel, and darkens creases. Output = colour * ao.

This is the classic depth-only SSAO (no normal G-buffer yet). Sign conventions,
bias and radius scale are the things most likely to need tuning on real hardware
— the harness can compile this shader but not judge the look.
"""
from .effect import ScreenEffect

_SSAO_FRAG = """
uniform sampler2D uColor;
uniform sampler2D uDepth;
uniform mat4 uProj;
uniform mat4 uInvProj;
uniform vec2 uTexel;
uniform float uRadius;
uniform float uStrength;
uniform float uBias;
in vec2 vUV;
out vec4 fragColor;

const vec3 KERNEL[16] = vec3[](
    vec3(-0.0335,-0.0664,0.0669),
    vec3(-0.0909,0.0076,0.0490),
    vec3(-0.1117,0.0019,0.0230),
    vec3(-0.0194,-0.1259,0.0332),
    vec3(-0.0329,0.1423,0.0556),
    vec3(-0.0918,0.0423,0.1584),
    vec3(0.0345,-0.0462,0.2191),
    vec3(-0.2020,0.1597,0.0883),
    vec3(-0.2060,-0.2213,0.1193),
    vec3(0.2200,-0.2222,0.2242),
    vec3(0.1738,-0.1596,0.3850),
    vec3(-0.3581,-0.3607,0.1331),
    vec3(0.3837,-0.1540,0.4434),
    vec3(0.2643,-0.1446,0.6253),
    vec3(0.5840,0.3948,0.3546),
    vec3(0.1461,0.0495,0.8776));

vec3 view_pos(vec2 uv){
    float z = texture(uDepth, uv).r;
    vec4 clip = vec4(uv * 2.0 - 1.0, z * 2.0 - 1.0, 1.0);
    vec4 v = uInvProj * clip;
    return v.xyz / v.w;
}
float rand(vec2 co){ return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453); }

void main(){
    float z = texture(uDepth, vUV).r;
    vec4 col = texture(uColor, vUV);
    if(any(isnan(col)) || any(isinf(col))) col = vec4(0.0, 0.0, 0.0, 1.0);
    if(z >= 1.0){ fragColor = col; return; }        /* background: no AO */

    vec3 P = view_pos(vUV);
    vec3 N = normalize(cross(dFdx(P), dFdy(P)));

    float ang = rand(vUV) * 6.2831853;
    float ca = cos(ang), sa = sin(ang);
    mat2 rot = mat2(ca, -sa, sa, ca);

    float occ = 0.0;
    for(int i = 0; i < 16; i++){
        vec3 s = KERNEL[i];
        s.xy = rot * s.xy;
        if(dot(s, N) < 0.0) s = -s;               /* flip into the normal hemisphere */
        vec3 sp = P + s * uRadius;

        vec4 off = uProj * vec4(sp, 1.0);
        off.xyz /= off.w;
        vec2 suv = off.xy * 0.5 + 0.5;
        if(suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) continue;

        float sd = view_pos(suv).z;               /* sampled surface depth (view Z) */
        float rangeCheck = smoothstep(0.0, 1.0, uRadius / max(abs(P.z - sd), 1e-4));
        occ += ((sd >= sp.z + uBias) ? 1.0 : 0.0) * rangeCheck;
    }
    float ao = 1.0 - (occ / 16.0) * uStrength;
    ao = clamp(ao, 0.0, 1.0);
    fragColor = vec4(col.rgb * ao, col.a);
}
"""


class SSAO(ScreenEffect):
    name = "ssao"
    uses_depth = True
    frag = _SSAO_FRAG

    def enabled(self, vls):
        return bool(getattr(vls, "use_ao", False))

    def set_uniforms(self, sh, ctx):
        def sf(n, v):
            try: sh.uniform_float(n, v)
            except Exception: pass
        sf('uProj', ctx['proj'])
        sf('uInvProj', ctx['inv_proj'])
        sf('uTexel', ctx['texel'])
        sf('uRadius', ctx.get('ao_radius', 0.5))
        sf('uStrength', ctx.get('ao_strength', 1.0))
        sf('uBias', ctx.get('ao_bias', 0.02))
        # AO object exclusion: sample the occluder-only depth (flagged objects omitted)
        aod = ctx.get('ao_depth_tex')
        if aod is not None:
            try: sh.uniform_sampler('uDepth', aod)
            except Exception: pass
