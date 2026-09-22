# vertex_lit_renderer/fx/ssao.py
"""
Screen-space ambient occlusion (Cavity World), computed over TIME instead of all at once.

The AO maths is unchanged: reconstruct view-space position from depth, reconstruct a normal from
depth derivatives, sample a hemisphere kernel, darken creases (and optionally brighten ridges).
What changed is how many samples a single frame pays for:

  * each frame takes a SMALL slice of the kernel (8 by default) with a per-frame rotation;
  * the result is blended into a history buffer, reprojected with the camera movement (world
    position from this frame's depth -> previous frame's screen position). History is rejected
    where the reprojected depth disagrees (disocclusion, moved objects), so those pixels simply
    use this frame's samples;
  * while the view sits still the history keeps refining and the image converges to MORE samples
    than the old one-shot pass used, then stops (the pass is skipped once converged).

Quality ("ao_samples") is the converged sample count, as before. The visible result after the
view settles matches -- or beats -- the old shader; the per-frame cost is a fraction of it.
"""
import gpu
from .effect import ScreenEffect, FS_VERT

_KERNEL = """
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
"""

# ── pass 1: this frame's slice of AO, blended into the reprojected history ──
# out: (occlusion mean, ridge mean, view depth, history weight)
_AO_FRAG = """
uniform sampler2D uDepth;    /* main (visible surface) depth */
uniform sampler2D uAoDepth;  /* occluder depth: excluded objects omitted (== uDepth if none) */
uniform sampler2D uHist;     /* previous frame's accumulated AO */
uniform mat4 uProj;
uniform mat4 uInvProj;
uniform mat4 uInvViewProj;
uniform mat4 uPrevViewProj;
uniform float uRadius;
uniform float uBias;
uniform float uRidge;
uniform int uSamples;        /* samples THIS frame */
uniform int uTarget;         /* Quality: the full kernel size being covered */
uniform int uSliceBase;      /* first kernel tap of this frame's slice */
uniform int uFirst;          /* 1 = history invalid (view/scene changed) */
uniform float uMaxN;         /* history length in frames */
uniform float uSeed;         /* per-frame kernel rotation */
in vec2 vUV;
out vec4 fragColor;
""" + _KERNEL + """
vec3 view_pos(sampler2D dtex, vec2 uv){
    float z = texture(dtex, uv).r;
    vec4 clip = vec4(uv * 2.0 - 1.0, z * 2.0 - 1.0, 1.0);
    vec4 v = uInvProj * clip;
    return v.xyz / v.w;
}
float rand(vec2 co){ return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453); }

void main(){
    float z = texture(uDepth, vUV).r;
    if(z >= 1.0){ fragColor = vec4(0.0, 0.0, 1e6, 1.0); return; }      /* background: no AO */
    float aoZ = texture(uAoDepth, vUV).r;
    if(z < aoZ - 0.0008){ fragColor = vec4(0.0, 0.0, 1e6, 1.0); return; }   /* AO-excluded object */

    vec3 P = view_pos(uDepth, vUV);
    vec3 N = normalize(cross(dFdx(P), dFdy(P)));

    float ang = rand(vUV) * 6.2831853;
    float ca = cos(ang), sa = sin(ang);
    mat2 rot = mat2(ca, -sa, sa, ca);

    /* this frame's slice of the kernel the old one-shot pass averaged */
    int NS = uSamples;
    int base = uSliceBase;
    float occ = 0.0;
    float edg = 0.0;
    for(int i = 0; i < NS; i++){
        vec3 s = KERNEL[(base + i) % uTarget];
        s.xy = rot * s.xy;
        if(dot(s, N) < 0.0) s = -s;               /* flip into the normal hemisphere */
        vec3 sp = P + s * uRadius;

        vec4 off = uProj * vec4(sp, 1.0);
        off.xyz /= off.w;
        vec2 suv = off.xy * 0.5 + 0.5;
        if(suv.x < 0.0 || suv.x > 1.0 || suv.y < 0.0 || suv.y > 1.0) continue;

        float sz = texture(uAoDepth, suv).r;
        vec3 gp = view_pos(uAoDepth, suv);
        float sd = gp.z;
        float rangeCheck = smoothstep(0.0, 1.0, uRadius / max(abs(P.z - sd), 1e-4));
        occ += ((sd >= sp.z + uBias) ? 1.0 : 0.0) * rangeCheck;

        if(uRidge > 0.0 && sz < 1.0){
            vec3 dir = gp - P;
            float len = length(dir);
            if(len > 1e-4){
                float d = dot(dir / len, N);
                edg += max(-d - uBias, 0.0) * rangeCheck;
            }
        }
    }
    occ /= float(NS);
    edg /= float(NS);

    /* reproject the history with the camera motion and reject it where the surface changed */
    float w = 1.0;
    if(uFirst == 0){
        vec4 wp = uInvViewProj * vec4(vUV * 2.0 - 1.0, z * 2.0 - 1.0, 1.0);
        vec3 world = wp.xyz / wp.w;
        vec4 pc = uPrevViewProj * vec4(world, 1.0);
        if(pc.w > 1e-6){
            vec2 puv = pc.xy / pc.w * 0.5 + 0.5;
            if(puv.x >= 0.0 && puv.x <= 1.0 && puv.y >= 0.0 && puv.y <= 1.0){
                /* nearest texel: repeated bilinear resampling would smear the history */
                vec4 h = texelFetch(uHist, ivec2(puv * vec2(textureSize(uHist, 0))), 0);
                float tol = max(0.02 * abs(P.z), uRadius * 0.5);
                if(abs(h.z - P.z) < tol){
                    w = min(h.w + 1.0, uMaxN);
                    float a = 1.0 / w;                       /* running mean */
                    occ = mix(h.x, occ, a);
                    edg = mix(h.y, edg, a);
                }
            }
        }
    }
    fragColor = vec4(occ, edg, P.z, w);
}
"""

# ── pass 2: apply the accumulated AO to the colour ──
_APPLY_FRAG = """
uniform sampler2D uColor;
uniform sampler2D uAO;
uniform float uStrength;
uniform float uRidge;
in vec2 vUV;
out vec4 fragColor;
void main(){
    vec4 col = texture(uColor, vUV);
    if(any(isnan(col)) || any(isinf(col))) col = vec4(0.0, 0.0, 0.0, 1.0);
    vec4 a = texture(uAO, vUV);
    float ao = clamp(1.0 - a.x * uStrength, 0.0, 1.0);
    float ridge = a.y * uRidge;
    fragColor = vec4(col.rgb * ao * (1.0 + ridge), col.a);
}
"""

SPF = 8               # samples per frame while accumulating (the rest arrive over the next frames)


class SSAO(ScreenEffect):
    name = "ssao"
    uses_depth = True
    frag = _APPLY_FRAG          # the base class' shader() builds the apply pass

    def __init__(self):
        super().__init__()
        self._ao_sh = None
        self._ao_batch = None
        self._n = 0
        self._hist = [None, None]
        self._hist_fb = [None, None]
        self._w = self._h = 0
        self._cur = 0
        self._key = None

    def enabled(self, vls):
        return bool(getattr(vls, "use_ao", False))

    def free(self):
        super().free()
        self._ao_sh = None; self._ao_batch = None
        self._hist = [None, None]; self._hist_fb = [None, None]
        self._w = self._h = 0; self._key = None

    # -- internals --
    def _ensure(self, w, h):
        if self._hist_fb[0] is not None and (w, h) == (self._w, self._h):
            return
        self._w, self._h = w, h
        for i in range(2):
            self._hist[i] = gpu.types.GPUTexture((w, h), format='RGBA16F')
            self._hist_fb[i] = gpu.types.GPUFrameBuffer(color_slots=(self._hist[i],))
        self._key = None

    def _ao_shader(self):
        if self._ao_sh is None:
            from gpu_extras.batch import batch_for_shader
            self._ao_sh = gpu.types.GPUShader(FS_VERT, _AO_FRAG)
            self._ao_batch = batch_for_shader(
                self._ao_sh, 'TRIS', {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]})
        return self._ao_sh

    def run(self, color_tex, depth_tex, ctx):
        w, h = int(color_tex.width), int(color_tex.height)
        self._ensure(w, h)
        target = int(ctx.get('ao_samples', 16))
        if ctx.get('ao_full'):                              # F12: one shot, full budget (no next frame)
            spf, max_n = target, 1.0
        else:
            spf = min(SPF, target)
            max_n = max(1.0, float(target) / float(spf))    # converge to at least the set quality
        # The history survives camera movement -- reprojection handles that. Only a scene change or a
        # settings change throws it away.
        key = (ctx.get('scene_key'), target, round(float(ctx.get('ao_radius', 0.5)), 5),
               round(float(ctx.get('ao_bias', 0.02)), 5), round(float(ctx.get('ao_ridge', 0.0)), 5), w, h)
        first = 1 if key != self._key else 0
        self._key = key
        if first:
            self._n = 0
        still = bool(ctx.get('view_still')) and not first
        # The moment the view settles, start the history again from scratch: the frames that follow
        # then average exactly the taps the one-shot pass used, from THIS viewpoint, so the settled
        # image is the old image (reprojected samples from older viewpoints would only approximate it).
        if still and not getattr(self, '_was_still', False):
            first = 1; self._n = 0
        self._was_still = still
        # A still, fully accumulated view is already the average the one-shot pass computed: freeze it
        # (the AO pass then costs nothing at all until something moves).
        if still and self._n >= max_n:
            self._apply(color_tex, ctx, self._hist[self._cur])
            return
        self._frame = (getattr(self, '_frame', 0) + 1) % 64
        src, dst = self._cur, 1 - self._cur

        sh = self._ao_shader(); sh.bind()

        def s(fn, n, v):
            try: fn(n, v)
            except Exception: pass
        s(sh.uniform_sampler, 'uDepth', depth_tex)
        aod = ctx.get('ao_depth_tex')
        s(sh.uniform_sampler, 'uAoDepth', aod if aod is not None else depth_tex)
        s(sh.uniform_sampler, 'uHist', self._hist[src])
        s(sh.uniform_float, 'uProj', ctx['proj'])
        s(sh.uniform_float, 'uInvProj', ctx['inv_proj'])
        s(sh.uniform_float, 'uInvViewProj', ctx.get('inv_view_proj', ctx['inv_proj']))
        s(sh.uniform_float, 'uPrevViewProj', ctx.get('prev_view_proj', ctx.get('view_proj')))
        s(sh.uniform_float, 'uRadius', ctx.get('ao_radius', 0.5))
        s(sh.uniform_float, 'uBias', ctx.get('ao_bias', 0.02))
        s(sh.uniform_float, 'uRidge', ctx.get('ao_ridge', 0.0))
        s(sh.uniform_float, 'uMaxN', max_n)
        s(sh.uniform_float, 'uSeed', self._frame / 64.0)
        s(sh.uniform_int, 'uSamples', spf)
        s(sh.uniform_int, 'uTarget', target)
        slices = max(1, int(round(max_n)))
        s(sh.uniform_int, 'uSliceBase', (self._frame % slices) * spf)
        s(sh.uniform_int, 'uFirst', first)
        with self._hist_fb[dst].bind():
            gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False); gpu.state.blend_set('NONE')
            self._ao_batch.draw(sh)
        self._cur = dst
        # keep refining until the history holds the full sample budget (the engine redraws for us)
        self._n = 1 if first else min(self._n + 1, max_n)
        if self._n < max_n:
            ctx['ao_more'] = True

        self._apply(color_tex, ctx, self._hist[dst])

    def _apply(self, color_tex, ctx, ao_tex):
        ap = self.shader(); ap.bind()

        def s(fn, n, v):
            try: fn(n, v)
            except Exception: pass
        s(ap.uniform_sampler, 'uColor', color_tex)
        s(ap.uniform_sampler, 'uAO', ao_tex)
        s(ap.uniform_float, 'uStrength', ctx.get('ao_strength', 1.0))
        s(ap.uniform_float, 'uRidge', ctx.get('ao_ridge', 0.0))
        self._batch.draw(ap)

    def set_uniforms(self, sh, ctx):
        pass
