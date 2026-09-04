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
uniform int uSamples;
in vec2 vUV;
out vec4 fragColor;

const vec3 KERNEL[64] = vec3[](
    vec3(-0.0100,0.0126,0.0987),vec3(-0.0105,0.0024,0.0996),
    vec3(-0.0683,0.0026,0.0742),vec3(0.0553,-0.0766,0.0385),
    vec3(-0.0670,0.0507,0.0605),vec3(-0.0587,0.0618,0.0622),
    vec3(0.0695,0.0521,0.0640),vec3(-0.1083,0.0063,0.0224),
    vec3(-0.0856,-0.0713,0.0243),vec3(-0.0097,-0.0160,0.1163),
    vec3(0.0073,0.0534,0.1094),vec3(0.0803,-0.0211,0.0955),
    vec3(0.0794,0.0791,0.0690),vec3(0.0871,-0.0774,0.0723),
    vec3(-0.0483,-0.0985,0.0918),vec3(-0.0344,0.1197,0.0826),
    vec3(0.1235,0.0936,0.0203),vec3(-0.0829,0.1171,0.0784),
    vec3(0.1636,-0.0349,0.0361),vec3(0.0643,0.1384,0.0942),
    vec3(-0.1178,-0.0478,0.1383),vec3(0.1027,-0.1520,0.0715),
    vec3(-0.1137,-0.1255,0.1179),vec3(-0.1653,0.0304,0.1360),
    vec3(-0.1717,0.1287,0.0725),vec3(0.0708,-0.1889,0.1250),
    vec3(-0.1168,-0.0937,0.1984),vec3(0.1366,-0.0882,0.2031),
    vec3(-0.1471,-0.0537,0.2227),vec3(0.0619,-0.1745,0.2164),
    vec3(-0.1550,-0.1307,0.2181),vec3(-0.1858,-0.2213,0.1154),
    vec3(-0.2931,0.0592,0.1275),vec3(0.1096,-0.1388,0.2895),
    vec3(0.2905,-0.0103,0.2020),vec3(0.2681,-0.2320,0.1028),
    vec3(0.2866,0.2230,0.1271),vec3(-0.2020,0.1559,0.3091),
    vec3(-0.1796,0.2664,0.2663),vec3(0.2550,-0.1934,0.2934),
    vec3(-0.3078,0.3087,0.1177),vec3(0.1809,-0.2149,0.3760),
    vec3(0.1725,-0.3694,0.2675),vec3(0.2171,-0.4248,0.1695),
    vec3(0.0636,0.3774,0.3599),vec3(-0.2402,0.4561,0.1767),
    vec3(-0.4572,-0.2183,0.2501),vec3(-0.4339,-0.3196,0.2287),
    vec3(0.0995,-0.5080,0.3156),vec3(0.3438,0.4226,0.3115),
    vec3(0.4994,0.2205,0.3516),vec3(-0.3837,-0.3979,0.3812),
    vec3(0.2727,0.6280,0.1140),vec3(0.2387,-0.0311,0.6756),
    vec3(-0.2476,0.6826,0.1463),vec3(0.0681,0.3503,0.6763),
    vec3(0.3617,0.3107,0.6287),vec3(0.5895,-0.2105,0.5202),
    vec3(0.5590,0.5176,0.3519),vec3(0.4456,0.5575,0.4884),
    vec3(0.3047,-0.2869,0.7866),vec3(0.1799,-0.6937,0.5730),
    vec3(0.6368,0.4903,0.4964),vec3(-0.2620,0.5520,0.7560));

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
    int NS = uSamples;
    for(int i = 0; i < NS; i++){
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
    float ao = 1.0 - (occ / float(NS)) * uStrength;
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
        try: sh.uniform_int('uSamples', int(ctx.get('ao_samples', 16)))
        except Exception: pass
        # AO object exclusion: sample the occluder-only depth (flagged objects omitted)
        aod = ctx.get('ao_depth_tex')
        if aod is not None:
            try: sh.uniform_sampler('uDepth', aod)
            except Exception: pass
