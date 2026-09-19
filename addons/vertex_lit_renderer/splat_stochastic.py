"""
vertex_lit_renderer/splat_stochastic.py
---------------------------------------
Stochastic splat renderer (opt-in: Render > Splats > "Stochastic Splats"). No sorting.

Based on "Gaussian Point Splatting" (Rijsdijk et al., ACM TOG 2026; github.com/JorisAR/gaussian-point-splatting,
BSD-3). Each splat emits Poisson(lambda) pixel-sized opaque points distributed like its Gaussian, lambda chosen so
that the expected coverage equals the splat's opacity; the nearest point per sample wins. Averaged over samples and
frames this converges to the same image as sorted alpha blending. It is exact in the sense that nothing is
approximated per frame: every point is depth-tested exactly (two passes, no packed depth), and the noise is plain
Monte-Carlo noise that averages out while the view is still.

Per frame (each batch = one cloud, up to 32 instances):
  preprocess: project each splat (the addon's own EWA footprint: covariance + blur, sigma, eigen rectangle,
              alpha cut, centre depth) -> point count -> exclusive prefix sum -> total (1 readback)
  pass A:     every point: mesh depth test (LESS_EQUAL at the splat centre's depth, like the sorted draw), then
              atomicMin(view depth) per sample (skipped when the sample already holds a nearer depth)
  pass B:     regenerate the SAME points, atomicMin(splat id) where the depth matches
  resolve:    samples -> lit colour, averaged over ss x ss samples -> accumulated while the view is still
  composite:  premultiplied colour + coverage over the current framebuffer.
Measured on an RTX 4090 (1080p, ss 2), vs the sorted path with a moving camera: ~1.4x at 1M splats, ~2.3x at 4M,
~4.5x at 16M, ~6x at 32M; about even below ~0.3M.
"""
import gpu, math, time
import numpy as np
from mathutils import Matrix, Vector
from gpu_extras.batch import batch_for_shader

CW = 8192                 # row width of the 2D-tiled 1D buffers
MAX_INST = 32             # instances per batch (push-constant array size)
ACCUM_FRAMES = 32         # still-view refinement frames
_TW = 4096                # SplatCloud data texture width (4 texels / splat)

_COMMON = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
uint gid1d(){ return (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x; }
uint hash32(uint x){ x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16; return x; }
uvec2 makeSeed(uint idx, uint frame){
  uint h1 = hash32(idx ^ (frame * 0x9E3779B9u)); uint h2 = hash32((idx * 0xBB67AE85u) ^ frame);
  h1 ^= (h2 * 0x3C6EF372u); h2 ^= (h1 * 0xA54FF53Au); return uvec2(h1, h2); }
uvec2 pcg2d_u(uvec2 s){
  s = s * 1664525u + 1013904223u; s.x += s.y * 1664525u; s.y += s.x * 1664525u; s ^= s >> 16u;
  s.x += s.y * 1664525u; s.y += s.x * 1664525u; s ^= s >> 16u; return s; }
vec2 pcg2d(inout uvec2 s){ s = pcg2d_u(s); return vec2(s) * 2.3283064365387e-10; }
int stochastic_round(float x, float u){ int b = int(floor(x)); float f = x - float(b); return max(0, (u < f) ? b + 1 : b); }
float dilog(float x){
  float y = -6.09201442e-01; y = fma(y,x,1.79126616e+00); y = fma(y,x,-2.14953223e+00); y = fma(y,x,1.26304372e+00);
  y = fma(y,x,-4.59069895e-01); y = fma(y,x,-1.87417414e-01); y = fma(y,x,1.99603130e+00); y = fma(y,x,5.99669467e-05);
  float s = 1.0 - x; if (s > 0.0) y += s * log(max(s, 1e-37)); return y; }
float inv_dilog(float x){
  float t = min(x / 1.6449340668482264, 1.0);
  float y = -1.27463503e+01; y = fma(y,t,5.88993459e+01); y = fma(y,t,-1.16025780e+02); y = fma(y,t,1.26945827e+02);
  y = fma(y,t,-8.43108826e+01); y = fma(y,t,3.48799862e+01); y = fma(y,t,-8.89606235e+00); y = fma(y,t,1.38640936e+00);
  y = fma(y,t,-7.80640876e-01); y = fma(y,t,1.64841888e+00); y = fma(y,t,-2.82836687e-05); return y; }
vec2 correctedBoxMuller(float u1, float u2, float alpha){
  float a = 1.0 / max(alpha, 1e-37) * inv_dilog((1.0 - u1) * dilog(alpha));
  a = clamp(a, 1e-37, 1.0); float R = sqrt(max(-2.0 * log(a), 0.0)); float th = 6.28318530718 * u2;
  return vec2(R * cos(th), R * sin(th)); }
uint poisson(inout uvec2 st, float lam){
  if (lam <= 0.0) return 0u;
  if (lam < 12.0) {
    float u = pcg2d(st).x; float p = exp(-lam); float F = p; uint k = 0u;
    while (u > F && k < 96u) { k++; p *= lam / float(k); F += p; }
    return k; }
  vec2 uu = pcg2d(st);
  float w = sqrt(max(-2.0 * log(clamp(uu.x, 1e-37, 1.0)), 0.0)) * cos(6.28318530718 * uu.y);
  float w2 = w*w, w3 = w2*w, w4 = w2*w2, s = sqrt(lam);
  float kf = lam + s*w + (w2 - 1.0)/6.0 + (1.0/s)*(-(1.0/36.0)*w - (1.0/72.0)*w3)
           + (1.0/lam)*(-(8.0/405.0) + (7.0/810.0)*w2 + (1.0/270.0)*w4);
  return uint(max(int(round(kf)), 0)); }
// The sorted renderer's projection (splat_render._VERT), at the sample-grid resolution.
bool project(uint g, out vec2 pm, out vec3 cov, out float depth, out float ndcz, out float op,
             out vec2 e1, out float r1, out float r2){
  uint inst = g / uint(uN); uint i = g - inst * uint(uN); uint b = i * 4u;
  vec4 d0 = texelFetch(uData, at(b, 4096u), 0), d1 = texelFetch(uData, at(b+1u, 4096u), 0),
       d2 = texelFetch(uData, at(b+2u, 4096u), 0), d3 = texelFetch(uData, at(b+3u, 4096u), 0);
  vec3 icL = d0.xyz; vec3 is = vec3(d0.w, d1.x, d1.y); vec4 iq = vec4(d1.z, d1.w, d2.x, d2.y); op = d3.y;
  mat4 M = uModels[inst]; mat3 md = mat3(M);
  vec3 ic = (M * vec4(icL, 1.0)).xyz;
  vec3 dp = ic - uCam; vec3 t = vec3(dot(uR0, dp), dot(uR1, dp), dot(uR2, dp));
  vec4 clipC = uViewProj * vec4(ic, 1.0);
  if (t.z < 0.02 || clipC.w <= 0.0 || op <= 0.0) return false;
  float w = iq.x, x = iq.y, y = iq.z, z = iq.w;
  vec3 l0 = vec3(1.0-2.0*(y*y+z*z), 2.0*(x*y+w*z), 2.0*(x*z-w*y));
  vec3 l1v = vec3(2.0*(x*y-w*z), 1.0-2.0*(x*x+z*z), 2.0*(y*z+w*x));
  vec3 l2v = vec3(2.0*(x*z+w*y), 2.0*(y*z-w*x), 1.0-2.0*(x*x+y*y));
  if (uBackface == 1) {        // same rule as the sorted path: local normal . (local camera - centre) > -0.2
    vec3 nl = (is.x <= is.y && is.x <= is.z) ? l0 : ((is.y <= is.z) ? l1v : l2v);
    if (dot(nl, uCamL[inst].xyz - icL) <= -0.2) return false;
  }
  vec3 c0 = md * l0, c1 = md * l1v, c2 = md * l2v;
  float iz = 1.0 / max(t.z, 1e-6);
  mat3 J = mat3(vec3(uF.x*iz, 0, 0), vec3(0, uF.y*iz, 0), vec3(-uF.x*t.x*iz*iz, -uF.y*t.y*iz*iz, 0));
  mat3 Rv = mat3(vec3(uR0.x, uR1.x, uR2.x), vec3(uR0.y, uR1.y, uR2.y), vec3(uR0.z, uR1.z, uR2.z));
  mat3 Mm = mat3(c0*is.x, c1*is.y, c2*is.z); mat3 Sig = Mm * transpose(Mm);
  mat3 C = (J*Rv) * Sig * transpose(J*Rv);
  float ca = C[0][0] + uBlur, cb = C[0][1], cc = C[1][1] + uBlur;
  float tr = ca + cc, det = ca*cc - cb*cb, mid = 0.5*tr, disc = sqrt(max(mid*mid - det, 0.0));
  float l1 = mid + disc, l2 = max(mid - disc, 1e-9);
  r1 = uSigma * sqrt(max(l1, 0.0)); r2 = uSigma * sqrt(l2);
  e1 = vec2(cb, l1 - ca); e1 = (length(e1) < 1e-6) ? vec2(1, 0) : normalize(e1);
  float k2 = (uSigma / 3.0) * (uSigma / 3.0);
  cov = vec3(ca * k2, cb * k2, cc * k2);          // exp(-4.5|vC|^2) over the quad == this Gaussian
  pm = (clipC.xy / clipC.w * 0.5 + 0.5) * uVP;
  depth = t.z; ndcz = clipC.z / clipC.w * 0.5 + 0.5;
  vec2 e2 = vec2(-e1.y, e1.x); vec2 ext = abs(e1) * r1 + abs(e2) * r2;
  if (pm.x + ext.x < 0.0 || pm.y + ext.y < 0.0 || pm.x - ext.x > uVP.x || pm.y - ext.y > uVP.y) return false;
  return true; }
"""

_PREPROCESS = _COMMON + r"""
void main(){
  uint g = gid1d(); if (g >= uint(uG)) return;
  uint units = 0u;
  vec2 pm; vec3 cov; float depth, ndcz, op; vec2 e1; float r1, r2;
  if (project(g, pm, cov, depth, ndcz, op, e1, r1, r2)) {
    float det = cov.x*cov.z - cov.y*cov.y;
    if (det > 0.0) {
      float lam = 6.28318530718 * sqrt(det) * dilog(min(op, 1.0));   // expected points (unbiased variant)
      uvec2 st = makeSeed(g + uint(uBase), uint(uFrame) * 4u);
      uint n = poisson(st, lam);
      n = min(n, uint(uVP.x * uVP.y) / (2u * uint(uK)));
      units = uint(stochastic_round(float(n) / float(uK), pcg2d(st).x));
    }
  }
  imageStore(uCounts, at(g, uint(CW)), uvec4(units));
}"""

_SPLAT = _COMMON + r"""
void main(){
  uint u = gid1d(); if (u >= uint(uUnits)) return;
  uint lo = 0u, hi = uint(uG) - 1u;                          // owner of unit u: binary search of the prefix sum
  while (lo < hi) { uint mid = (lo + hi + 1u) >> 1; if (imageLoad(uCounts, at(mid, uint(CW))).r <= u) lo = mid; else hi = mid - 1u; }
  uint g = lo; uint j = u - imageLoad(uCounts, at(g, uint(CW))).r;
  vec2 pm; vec3 cov; float depth, ndcz, op; vec2 e1; float r1, r2;
  if (!project(g, pm, cov, depth, ndcz, op, e1, r1, r2)) return;
  uint dbits = floatBitsToUint(depth);
  float c0 = sqrt(cov.x), c1 = cov.y / c0, c2 = sqrt(max(cov.z - c1*c1, 0.0));
  float det = cov.x*cov.z - cov.y*cov.y; vec3 con = vec3(cov.z, -cov.y, cov.x) / det; vec2 e2 = vec2(-e1.y, e1.x);
  uvec2 st = makeSeed(hash32(g + uint(uBase)) ^ (j * 0x9E3779B9u), uint(uFrame) * 4u + 1u);  // same in A and B
  uint gid = g + uint(uBase);
  for (int p = 0; p < uK; p++) {
    vec2 r = pcg2d(st);
    vec2 xy = correctedBoxMuller(r.x, r.y, op);
    ivec2 pix = ivec2(floor(vec2(pm.x + c0*xy.x, pm.y + c1*xy.x + c2*xy.y)));
    if (pix.x < 0 || pix.y < 0 || pix.x >= int(uVP.x) || pix.y >= int(uVP.y)) continue;
    vec2 d = (vec2(pix) + 0.5) - pm;
    if (abs(dot(d, e1)) > r1 || abs(dot(d, e2)) > r2) continue;            // the raster quad's rectangle
    if (op * exp(-0.5*(con.x*d.x*d.x + con.z*d.y*d.y) - con.y*d.x*d.y) < uCut) continue;
    if (ndcz > texelFetch(uMeshDepth, pix / uSS, 0).r) continue;           // hidden by a mesh (LESS_EQUAL)
#if PASS == 1
    if (imageLoad(uDepth, pix).r <= dbits) continue;                        // atomicMin would be a no-op
    imageAtomicMin(uDepth, pix, dbits);
#else
    if (imageLoad(uDepth, pix).r == dbits) imageAtomicMin(uId, pix, gid);
#endif
  }
}"""

_CLEAR = r"""
void main(){ ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uSW || p.y >= uSH) return;
  imageStore(uDepth, p, uvec4(0xFFFFFFFFu)); imageStore(uId, p, uvec4(0xFFFFFFFFu)); }"""

_ZERO = r"""
void main(){ ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uW || p.y >= uH) return;
  imageStore(uOut, p, vec4(0.0)); if (uResetAcc == 1) imageStore(uAcc, p, vec4(0.0)); }"""

# per batch: add the lit colour of every sample owned by this batch's id range
_RESOLVE = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
vec3 splat_light(vec3 N){
  float hemi = dot(N, vec3(0.0,0.0,1.0))*0.5+0.5;
  vec3 L = mix(uGroundColor, uSkyColor, hemi) * uHemiIntensity;
  L += uSunColor * (max(dot(N, normalize(uSunDir)),0.0) * uSunIntensity);
  L += uKeyCol  * (max(dot(N, normalize(uKeyDir)),0.0) * uKeyIntensity);
  return L;
}
void main(){
  ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uW || p.y >= uH) return;
  vec3 c = vec3(0.0); float a = 0.0;
  for (int dy = 0; dy < uSS; dy++) for (int dx = 0; dx < uSS; dx++) {
    uint id = imageLoad(uId, p * uSS + ivec2(dx, dy)).r;
    if (id == 0xFFFFFFFFu || id < uint(uBase) || id >= uint(uBase + uG)) continue;
    uint g = id - uint(uBase); uint inst = g / uint(uN); uint i = g - inst * uint(uN); uint b = i * 4u;
    vec4 d0 = texelFetch(uData, at(b, 4096u), 0), d1 = texelFetch(uData, at(b+1u, 4096u), 0),
         d2 = texelFetch(uData, at(b+2u, 4096u), 0), d3 = texelFetch(uData, at(b+3u, 4096u), 0);
    vec3 col = vec3(d2.z, d2.w, d3.x);
    if (uLit == 1) {
      vec3 is = vec3(d0.w, d1.x, d1.y); float w = d1.z, x = d1.w, y = d2.x, z = d2.y;
      mat3 md = mat3(uModels[inst]);
      vec3 c0 = md*vec3(1.0-2.0*(y*y+z*z), 2.0*(x*y+w*z), 2.0*(x*z-w*y));
      vec3 c1 = md*vec3(2.0*(x*y-w*z), 1.0-2.0*(x*x+z*z), 2.0*(y*z+w*x));
      vec3 c2 = md*vec3(2.0*(x*z+w*y), 2.0*(y*z-w*x), 1.0-2.0*(x*x+y*y));
      vec3 nrm = (is.x <= is.y && is.x <= is.z) ? c0 : ((is.y <= is.z) ? c1 : c2);
      col *= splat_light(normalize(nrm));
    }
    c += col; a += 1.0; }
  if (a == 0.0) return;
  vec4 o = imageLoad(uOut, p) + vec4(c, a) / float(uSS * uSS);
  imageStore(uOut, p, o);
}"""

_ACCUM = r"""
void main(){ ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uW || p.y >= uH) return;
  imageStore(uAcc, p, imageLoad(uAcc, p) + imageLoad(uOut, p)); }"""

_SCAN = r"""
shared uint sh[256];
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
void main(){
  uint grp = gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x; uint lid = gl_LocalInvocationID.x;
  uint base = grp * 1024u + lid * 4u; uint v[4]; uint s = 0u;
  for (int j = 0; j < 4; j++) { uint idx = base + uint(j); uint x = (idx < uint(uN)) ? imageLoad(uA, at(idx, uint(uAW))).r : 0u; v[j] = s; s += x; }
  sh[lid] = s; barrier();
  for (uint off = 1u; off < 256u; off <<= 1u) { uint t = (lid >= off) ? sh[lid - off] : 0u; barrier(); sh[lid] += t; barrier(); }
  uint ex = (lid > 0u) ? sh[lid - 1u] : 0u;
  for (int j = 0; j < 4; j++) { uint idx = base + uint(j); if (idx < uint(uN)) imageStore(uA, at(idx, uint(uAW)), uvec4(v[j] + ex)); }
  if (lid == 255u) imageStore(uS, at(grp, uint(uSW_)), uvec4(sh[255]));
}"""

_ADD = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
void main(){
  uint idx = (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x;
  if (idx >= uint(uN)) return;
  uint add = imageLoad(uS, at(idx / 1024u, uint(uSW_))).r;
  ivec2 c = at(idx, uint(uAW)); imageStore(uA, c, uvec4(imageLoad(uA, c).r + add));
}"""

_COMP_VS = """
in vec2 pos; out vec2 uv;
void main(){ uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }"""
_COMP_FS = """
in vec2 uv; out vec4 o; uniform sampler2D uAccTex; uniform float uInvN;
void main(){ o = texture(uAccTex, uv) * uInvN; }"""


def _mk(src, local, pcs, images, samplers=(), defines=()):
    info = gpu.types.GPUShaderCreateInfo()
    info.local_group_size(*local)
    for k, v in defines:
        info.define(k, str(v))
    for typ, nm, *sz in pcs:
        if sz: info.push_constant(typ, nm, size=sz[0])
        else: info.push_constant(typ, nm)
    for slot, fmt, typ, nm, q in images:
        info.image(slot, fmt, typ, nm, qualifiers=q)
    for slot, typ, nm in samplers:
        info.sampler(slot, typ, nm)
    info.compute_source(src)
    return gpu.shader.create_from_info(info)


def _groups1d(n, local=256):
    g = max(1, (n + local - 1) // local)
    gx = min(g, 65535)
    return gx, (g + gx - 1) // gx


def _img_u32(n):
    w = max(1, min(CW, n)); h = max(1, (n + w - 1) // w)
    return gpu.types.GPUTexture((w, h), format='R32UI'), w


def _read_first_u32(tex):
    b = tex.read()
    try:
        b.dimensions = tex.width * tex.height
        return int(b[0])
    except Exception:
        v = b.to_list()
        while isinstance(v, list): v = v[0]
        return int(v)


def _scan_levels(n):
    out = []; m = n
    while True:
        groups = (m + 1023) // 1024; out.append(groups)
        if groups <= 1: return out
        m = groups


class _Batch:
    """GPU buffers for one cloud's instance group (counts + scan levels), grown on demand."""
    def __init__(self):
        self.cap = 0

    def ensure(self, G):
        if G <= self.cap:
            return
        self.cap = G
        self.counts, self.cw = _img_u32(G)
        self.levels = [_img_u32(n) for n in _scan_levels(G)]


class StochasticRenderer:
    PC = [('MAT4', 'uViewProj'), ('VEC3', 'uCam'), ('VEC3', 'uR0'), ('VEC3', 'uR1'), ('VEC3', 'uR2'),
          ('VEC2', 'uF'), ('VEC2', 'uVP'), ('FLOAT', 'uSigma'), ('FLOAT', 'uBlur'), ('FLOAT', 'uCut'),
          ('INT', 'uN'), ('INT', 'uG'), ('INT', 'uBase'), ('INT', 'uFrame'), ('INT', 'uK'), ('INT', 'uUnits'),
          ('INT', 'uSS'), ('INT', 'uBackface'), ('MAT4', 'uModels', MAX_INST), ('VEC4', 'uCamL', MAX_INST)]
    LIGHT_PC = [('INT', 'uLit'), ('VEC3', 'uSkyColor'), ('VEC3', 'uGroundColor'), ('FLOAT', 'uHemiIntensity'),
                ('VEC3', 'uSunDir'), ('VEC3', 'uSunColor'), ('FLOAT', 'uSunIntensity'),
                ('VEC3', 'uKeyDir'), ('VEC3', 'uKeyCol'), ('FLOAT', 'uKeyIntensity')]

    def __init__(self):
        PC = self.PC; RW = {'READ', 'WRITE'}
        smp = [(0, 'FLOAT_2D', 'uData'), (1, 'FLOAT_2D', 'uMeshDepth')]
        cw = [('CW', CW)]
        self.sh_pre = _mk(_PREPROCESS, (256, 1, 1), PC, [(0, 'R32UI', 'UINT_2D', 'uCounts', {'WRITE'})], smp[:1], cw)
        imgs = [(0, 'R32UI', 'UINT_2D', 'uCounts', {'READ'}), (1, 'R32UI', 'UINT_2D', 'uDepth', RW),
                (2, 'R32UI', 'UINT_2D', 'uId', RW)]
        self.sh_a = _mk(_SPLAT, (256, 1, 1), PC, imgs, smp, cw + [('PASS', 1)])
        self.sh_b = _mk(_SPLAT, (256, 1, 1), PC, imgs, smp, cw + [('PASS', 2)])
        self.sh_clear = _mk(_CLEAR, (16, 16, 1), [('INT', 'uSW'), ('INT', 'uSH')],
                            [(0, 'R32UI', 'UINT_2D', 'uDepth', {'WRITE'}), (1, 'R32UI', 'UINT_2D', 'uId', {'WRITE'})])
        self.sh_zero = _mk(_ZERO, (16, 16, 1), [('INT', 'uW'), ('INT', 'uH'), ('INT', 'uResetAcc')],
                           [(0, 'RGBA32F', 'FLOAT_2D', 'uOut', {'WRITE'}), (1, 'RGBA32F', 'FLOAT_2D', 'uAcc', {'WRITE'})])
        self.sh_res = _mk(_RESOLVE, (16, 16, 1),
                          [('INT', 'uW'), ('INT', 'uH'), ('INT', 'uN'), ('INT', 'uG'), ('INT', 'uBase'), ('INT', 'uSS'),
                           ('MAT4', 'uModels', MAX_INST)] + self.LIGHT_PC,
                          [(0, 'R32UI', 'UINT_2D', 'uId', {'READ'}), (1, 'RGBA32F', 'FLOAT_2D', 'uOut', RW)], smp[:1])
        self.sh_acc = _mk(_ACCUM, (16, 16, 1), [('INT', 'uW'), ('INT', 'uH')],
                          [(0, 'RGBA32F', 'FLOAT_2D', 'uOut', {'READ'}), (1, 'RGBA32F', 'FLOAT_2D', 'uAcc', RW)])
        scan_pc = [('INT', 'uN'), ('INT', 'uAW'), ('INT', 'uSW_')]
        self.sh_scan = _mk(_SCAN, (256, 1, 1), scan_pc,
                           [(0, 'R32UI', 'UINT_2D', 'uA', RW), (1, 'R32UI', 'UINT_2D', 'uS', {'WRITE'})])
        self.sh_add = _mk(_ADD, (256, 1, 1), scan_pc,
                          [(0, 'R32UI', 'UINT_2D', 'uA', RW), (1, 'R32UI', 'UINT_2D', 'uS', {'READ'})])
        self.sh_comp = gpu.types.GPUShader(_COMP_VS, _COMP_FS)
        self.quad = batch_for_shader(self.sh_comp, 'TRI_FAN', {'pos': [(-1, -1), (1, -1), (1, 1), (-1, 1)]})
        self.batches = {}          # (cloud id, chunk) -> _Batch
        self.size = None
        self.frame_no = 0
        self.acc_n = 0
        self.key = None

    # ── buffers ──
    def _ensure_size(self, W, H, ss):
        if self.size == (W, H, ss):
            return
        self.size = (W, H, ss)
        self.SW, self.SH = W * ss, H * ss
        self.depth = gpu.types.GPUTexture((self.SW, self.SH), format='R32UI')
        self.ids = gpu.types.GPUTexture((self.SW, self.SH), format='R32UI')
        self.out = gpu.types.GPUTexture((W, H), format='RGBA32F')
        self.acc = gpu.types.GPUTexture((W, H), format='RGBA32F')
        self.acc_n = 0; self.key = None

    # ── helpers ──
    def _uniforms(self, s, st, cloud, models, camls, G, base, units=0):
        def f(n, v):
            try: s.uniform_float(n, v)
            except ValueError: pass

        def i(n, v):
            try: s.uniform_int(n, v)
            except ValueError: pass
        f('uViewProj', st['vp']); f('uCam', st['cam']); f('uR0', st['r0']); f('uR1', st['r1']); f('uR2', st['r2'])
        f('uF', st['f']); f('uVP', (float(self.SW), float(self.SH)))
        f('uSigma', float(getattr(cloud, 'sigma', 2.2))); f('uBlur', st['blur']); f('uCut', 0.004)
        i('uN', int(cloud.d['count'])); i('uG', G); i('uBase', base); i('uFrame', self.frame_no); i('uK', st['K'])
        i('uUnits', units); i('uSS', st['ss']); i('uBackface', 1 if st['backface'] else 0)
        flat = [v for M in models for col in zip(*[tuple(r) for r in M]) for v in col]
        flat += [0.0] * (16 * MAX_INST - len(flat))
        try: s.uniform_vector_float(s.uniform_from_name('uModels'), gpu.types.Buffer('FLOAT', len(flat), flat), 16, MAX_INST)
        except ValueError: pass
        cl = [v for c in camls for v in (c[0], c[1], c[2], 1.0)] + [0.0] * (4 * (MAX_INST - len(camls)))
        try: s.uniform_vector_float(s.uniform_from_name('uCamL'), gpu.types.Buffer('FLOAT', len(cl), cl), 4, MAX_INST)
        except ValueError: pass
        try: s.uniform_sampler('uData', cloud.datatex)
        except ValueError: pass
        try: s.uniform_sampler('uMeshDepth', st['mesh_depth'])
        except ValueError: pass

    def _scan(self, bt, n):
        levels = [(bt.counts, bt.cw, n)] + [(t, w, m) for (t, w), m in zip(bt.levels, _scan_levels(n))]
        for li in range(len(levels) - 1):
            a, aw, m = levels[li]; s, sw, _ = levels[li + 1]
            sh = self.sh_scan; sh.bind(); sh.image('uA', a); sh.image('uS', s)
            sh.uniform_int('uN', m); sh.uniform_int('uAW', aw); sh.uniform_int('uSW_', sw)
            gx, gy = _groups1d((m + 1023) // 1024 * 256); gpu.compute.dispatch(sh, gx, gy, 1)
        for li in range(len(levels) - 3, -1, -1):
            a, aw, m = levels[li]; s, sw, _ = levels[li + 1]
            sh = self.sh_add; sh.bind(); sh.image('uA', a); sh.image('uS', s)
            sh.uniform_int('uN', m); sh.uniform_int('uAW', aw); sh.uniform_int('uSW_', sw)
            gx, gy = _groups1d(m); gpu.compute.dispatch(sh, gx, gy, 1)
        return levels[-1][0]

    # ── main entry ──
    def render(self, entries, vm, pm, W, H, region_w, mesh_depth, light=None, backface=False, epoch=0):
        """Draw `entries` [(cloud, world matrix, name)] into the bound framebuffer (W x H, whose depth
        texture is `mesh_depth`). Returns True when more refinement frames are wanted (caller redraws)."""
        if not entries:
            return False
        # sample grid: 2x2 per framebuffer pixel, unless the framebuffer is already supersampled
        ss = 2 if W <= region_w * 1.01 else 1
        self._ensure_size(W, H, ss)
        # group instances by cloud (one data texture per batch), MAX_INST per batch
        groups = {}
        for cloud, M, name in entries:
            cloud.ensure_gpu()
            groups.setdefault(id(cloud), (cloud, []))[1].append(M)
        batches = []
        for cid, (cloud, ms) in groups.items():
            for c0 in range(0, len(ms), MAX_INST):
                batches.append((cid, c0, cloud, ms[c0:c0 + MAX_INST]))
        # still-view accumulation key
        lk = None if light is None else tuple(round(float(x), 5) for k in sorted(light) for x in
                                              (light[k] if hasattr(light[k], '__len__') else (light[k],)))
        key = (tuple(round(v, 6) for r in vm for v in r), tuple(round(v, 6) for r in pm for v in r), W, H, ss,
               tuple((b[0], b[1], tuple(round(v, 6) for M in b[3] for r in M for v in r)) for b in batches),
               tuple(float(getattr(b[2], 'sigma', 2.2)) for b in batches), lk, bool(backface), epoch)
        reset = key != self.key
        self.key = key
        if reset:
            self.acc_n = 0
        if self.acc_n >= ACCUM_FRAMES:
            self._composite()                  # converged: just redraw the accumulated image
            return False
        self.frame_no = (self.frame_no + 1) & 0x3FFFFFFF
        # per-frame constants
        cam = vm.inverted().translation
        st = {'vp': pm @ vm, 'cam': cam, 'r0': Vector(vm[0][:3]), 'r1': Vector(vm[1][:3]), 'r2': -Vector(vm[2][:3]),
              'f': (0.5 * self.SW * pm[0][0], 0.5 * self.SH * pm[1][1]),
              'blur': 0.3 * (self.SW / float(max(region_w, 1))) ** 2,   # the sorted path's 0.3 px^2 (region px)
              'K': ss * ss, 'ss': ss, 'backface': backface, 'mesh_depth': mesh_depth}
        s = self.sh_clear; s.bind(); s.image('uDepth', self.depth); s.image('uId', self.ids)
        s.uniform_int('uSW', self.SW); s.uniform_int('uSH', self.SH)
        gpu.compute.dispatch(s, (self.SW + 15) // 16, (self.SH + 15) // 16, 1)
        # preprocess + pass A for every batch (global nearest depth), then pass B (ids)
        work = []; base = 0
        for cid, c0, cloud, ms in batches:
            N = int(cloud.d['count']); G = N * len(ms)
            bt = self.batches.get((cid, c0))
            if bt is None:
                bt = self.batches[(cid, c0)] = _Batch()
            bt.ensure(G)
            camls = [M.inverted() @ cam for M in ms]
            s = self.sh_pre; s.bind(); self._uniforms(s, st, cloud, ms, camls, G, base); s.image('uCounts', bt.counts)
            gx, gy = _groups1d(G); gpu.compute.dispatch(s, gx, gy, 1)
            units = _read_first_u32(self._scan(bt, G))
            if units > 0:
                self._pass(self.sh_a, st, cloud, ms, camls, G, base, units, bt)
            work.append((cloud, ms, camls, G, base, units, bt))
            base += G
        for cloud, ms, camls, G, b0, units, bt in work:
            if units > 0:
                self._pass(self.sh_b, st, cloud, ms, camls, G, b0, units, bt)
        # resolve -> out (per batch), accumulate
        s = self.sh_zero; s.bind(); s.image('uOut', self.out); s.image('uAcc', self.acc)
        s.uniform_int('uW', W); s.uniform_int('uH', H); s.uniform_int('uResetAcc', 1 if self.acc_n == 0 else 0)
        gpu.compute.dispatch(s, (W + 15) // 16, (H + 15) // 16, 1)
        for cloud, ms, camls, G, b0, units, bt in work:
            if units == 0:
                continue
            s = self.sh_res; s.bind(); s.image('uId', self.ids); s.image('uOut', self.out)
            s.uniform_int('uW', W); s.uniform_int('uH', H); s.uniform_int('uN', int(cloud.d['count']))
            s.uniform_int('uG', G); s.uniform_int('uBase', b0); s.uniform_int('uSS', ss)
            s.uniform_sampler('uData', cloud.datatex)
            flat = [v for M in ms for col in zip(*[tuple(r) for r in M]) for v in col] + [0.0] * (16 * (MAX_INST - len(ms)))
            try: s.uniform_vector_float(s.uniform_from_name('uModels'), gpu.types.Buffer('FLOAT', len(flat), flat), 16, MAX_INST)
            except ValueError: pass
            self._light_uniforms(s, light)
            gpu.compute.dispatch(s, (W + 15) // 16, (H + 15) // 16, 1)
        s = self.sh_acc; s.bind(); s.image('uOut', self.out); s.image('uAcc', self.acc)
        s.uniform_int('uW', W); s.uniform_int('uH', H)
        gpu.compute.dispatch(s, (W + 15) // 16, (H + 15) // 16, 1)
        self.acc_n += 1
        self._composite()
        return self.acc_n < ACCUM_FRAMES

    def _pass(self, sh, st, cloud, ms, camls, G, base, units, bt):
        sh.bind(); self._uniforms(sh, st, cloud, ms, camls, G, base, units)
        sh.image('uCounts', bt.counts); sh.image('uDepth', self.depth); sh.image('uId', self.ids)
        gx, gy = _groups1d(units); gpu.compute.dispatch(sh, gx, gy, 1)

    @staticmethod
    def _light_uniforms(s, light):
        def f(n, v):
            try: s.uniform_float(n, v)
            except ValueError: pass
        try: s.uniform_int('uLit', 1 if light is not None else 0)
        except ValueError: pass
        if light is None:
            return
        f('uSkyColor', light['sky']); f('uGroundColor', light['ground']); f('uHemiIntensity', float(light['hemi']))
        f('uSunDir', light['sun_dir']); f('uSunColor', light['sun_col']); f('uSunIntensity', float(light['sun_int']))
        f('uKeyDir', light['key_dir']); f('uKeyCol', light['key_col']); f('uKeyIntensity', float(light['key_int']))

    def _composite(self):
        if self.acc_n <= 0:
            return
        gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(False)
        gpu.state.blend_set('ALPHA_PREMULT')
        sh = self.sh_comp; sh.bind()
        sh.uniform_sampler('uAccTex', self.acc); sh.uniform_float('uInvN', 1.0 / self.acc_n)
        self.quad.draw(sh)
        gpu.state.blend_set('NONE'); gpu.state.depth_mask_set(True)


_RENDERER = [None]
_FAILED = [False]


def get():
    """The shared renderer, or None if it can't be built on this GPU (callers fall back to sorting)."""
    if _RENDERER[0] is None and not _FAILED[0]:
        try:
            _RENDERER[0] = StochasticRenderer()
        except Exception as e:
            _FAILED[0] = True
            print("[VertexLit] stochastic splats unavailable on this GPU -> sorted path:", e)
    return _RENDERER[0]
