"""
proto_stochastic.py: PROTOTYPE benchmark of stochastic Gaussian point splatting (Rijsdijk et al.,
"Gaussian Point Splatting", ACM TOG 2026; https://github.com/JorisAR/gaussian-point-splatting, BSD-3)
against the addon's current sorted splat renderer (GPU radix sort + alpha blending). Installed addon untouched.

  blender.exe <scratch copy of a tree .blend> --python proto_stochastic.py -- <out_dir> <benchmark_splats.py>
  env VLR_SCENES  e.g. "200000x1,1000000x1,1000000x4,1000000x16,1000000x32"  (per-tree splats x trees)
  env VLR_MODES   comma list of: bsearch, early, occl, cull, tile64, tile32   (default: bsearch,early,occl)
  env VLR_RES     e.g. "1920x1080"     env VLR_SS  supersampling factor (default 2, the paper's default)
  env VLR_K       points per thread (default ss^2, the paper's default)

Every mode is EXACT: the same frame gives bit-identical ids in every mode (checked per scene). Per frame:
  preprocess (project each Gaussian, importance = 2*pi*sqrt(det)*Li2(opacity), Poisson point count)
  -> exclusive prefix sum -> read back the total -> pass A: points atomicMin(depth) -> pass B: regenerate the
  SAME points, atomicMin(id) where depth matches -> resolve id -> colour (ss x ss box) -> accumulate.
  bsearch : as above (option 1). Each point finds its Gaussian by binary search over the prefix sum.
  early   : pass A skips the atomic when the pixel already holds a nearer depth (the atomic would be a no-op).
  occl    : + two-phase occlusion culling (as in the paper): draw last frame's winning Gaussians' depths first,
            build a max-depth Hi-Z, then drop every Gaussian whose depth is behind all of the pixels it can touch.
            All points of a Gaussian share its centre depth, so a dropped Gaussian could never have won a pixel.
  cull    : early + skip whole instances that provably cannot reach the screen (bound on the EWA footprint).
  tile64  : option 2. Gaussians binned to 32x32 tiles; one workgroup per tile regenerates the same points and keeps
            the nearest with 64-bit SHARED-memory atomicMin(depth<<32 | id) (NVIDIA GL_NV_shader_atomic_int64).
  tile32  : option 2 without 64-bit atomics (the two-pass trick inside shared memory; any GPU).
Measured (RTX 4090, 1080p, ss 2): early is the winner, ~4.2-4.8x the sorted renderer at 16M, 6x at 32M. Tiles are
correct but slower (binning atomics on 8k tile counters dominate). Occlusion culling barely culls: stochastic points
leave holes, so the exact "all pixels nearer" test rarely holds. Also tried, same image but slower: owner lookup
via max-scan, caching the projection per Gaussian, and 1-px GL points with the hardware depth test.
  env VLR_DIST    camera distance scale (default 1; e.g. 0.18 = close-up with part of the scene off-screen)
The Gaussian footprint is EXACTLY the addon's: EWA covariance + 0.3 px^2, scaled by (sigma/3)^2, truncated to
the same eigen-aligned rectangle the raster quad covers, alpha cut 0.004, depth = view depth of the centre.
"""
import bpy, sys, os, json, time, math, statistics, traceback, importlib, importlib.util
import numpy as np
import gpu
from mathutils import Matrix, Vector, Euler

ARGS = sys.argv[sys.argv.index('--') + 1:]
OUT_DIR, BENCH = ARGS[0], ARGS[1]
os.makedirs(OUT_DIR, exist_ok=True)
SCENES = [tuple(int(v) for v in s.split('x')) for s in
          os.environ.get('VLR_SCENES', '200000x1,1000000x1,1000000x4,1000000x16,1000000x32').split(',')]
MODES = os.environ.get('VLR_MODES', 'bsearch,early,occl').split(',')
W, H = (int(v) for v in os.environ.get('VLR_RES', '1920x1080').split('x'))
SS = int(os.environ.get('VLR_SS', '2'))
K = int(os.environ.get('VLR_K', str(SS * SS)))    # points per thread. Paper default K = ss^2; K = 1 is its
                                                  # "mathematically correct" mode (no measurable difference here)
SIGMA = 2.2
ORBIT_FRAMES = int(os.environ.get('VLR_ORBIT', '16'))
CONV = [1, 16]
RESULTS = os.path.join(OUT_DIR, 'stochastic_results.txt')
STATUS = os.path.join(OUT_DIR, 'auto_status.json')
L = []; status = {'ok': False, 'scenes': []}
bench = None
CW = 8192                        # row width of the 2D-tiled 1D buffers
DIST = float(os.environ.get('VLR_DIST', '1'))   # camera distance scale (<1: close-up, much of the scene off-screen)
TS = int(os.environ.get('VLR_TS', '32'))   # tile size (supersampled px) for the tile modes


def log(s=''):
    print('[stoch]', s); L.append(str(s))
    with open(RESULTS, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


for _scr in bpy.data.screens:
    for _a in _scr.areas:
        if _a.type == 'VIEW_3D':
            for _s in _a.spaces:
                if _s.type == 'VIEW_3D':
                    _s.shading.type = 'SOLID'

# ─────────────────────────────── GLSL ───────────────────────────────
COMMON = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
// --- RNG (ported from the paper's random.cuh) ---
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
  if (lam < 12.0) {                              // exact inversion for small means
    float u = pcg2d(st).x; float p = exp(-lam); float F = p; uint k = 0u;
    while (u > F && k < 96u) { k++; p *= lam / float(k); F += p; }
    return k; }
  vec2 uu = pcg2d(st);                           // Giles QN3 (as the paper) for large means
  float w = sqrt(max(-2.0 * log(clamp(uu.x, 1e-37, 1.0)), 0.0)) * cos(6.28318530718 * uu.y);
  float w2 = w*w, w3 = w2*w, w4 = w2*w2, s = sqrt(lam);
  float kf = lam + s*w + (w2 - 1.0)/6.0 + (1.0/s)*(-(1.0/36.0)*w - (1.0/72.0)*w3)
           + (1.0/lam)*(-(8.0/405.0) + (7.0/810.0)*w2 + (1.0/270.0)*w4);
  return uint(max(int(round(kf)), 0)); }
// --- the addon's exact projection (splat_render._COMPUTE_SRC), at supersampled resolution ---
bool project(uint g, out vec2 pm, out vec3 cov, out float depth, out float op, out vec2 e1, out float r1, out float r2){
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
  vec3 c0 = md * vec3(1.0-2.0*(y*y+z*z), 2.0*(x*y+w*z), 2.0*(x*z-w*y));
  vec3 c1 = md * vec3(2.0*(x*y-w*z), 1.0-2.0*(x*x+z*z), 2.0*(y*z+w*x));
  vec3 c2 = md * vec3(2.0*(x*z+w*y), 2.0*(y*z-w*x), 1.0-2.0*(x*x+y*y));
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
  cov = vec3(ca * k2, cb * k2, cc * k2);          // exp(-4.5|vC|^2) == Gaussian with this covariance
  pm = (clipC.xy / clipC.w * 0.5 + 0.5) * uVP;
  depth = t.z;
  vec2 e2 = vec2(-e1.y, e1.x); vec2 ext = abs(e1) * r1 + abs(e2) * r2;
  if (pm.x + ext.x < 0.0 || pm.y + ext.y < 0.0 || pm.x - ext.x > uVP.x || pm.y - ext.y > uVP.y) return false;
  return true; }
uint remap(uint v){ uint k = v / uint(uN); return uint(uInstMap[k]) * uint(uN) + (v - k * uint(uN)); }
// number of K-point units of Gaussian g this frame (depends only on g, frame and its projection)
uint unit_count(uint g, vec3 cov, float op){
  float det = cov.x*cov.z - cov.y*cov.y;
  if (det <= 0.0) return 0u;
  float lam = 6.28318530718 * sqrt(det) * dilog(min(op, 1.0));     // expected points (unbiased variant)
  uvec2 st = makeSeed(g, uint(uFrame) * 4u);
  uint n = poisson(st, lam);
  n = min(n, uint(uVP.x * uVP.y) / (2u * uint(uK)));
  return uint(stochastic_round(float(n) / float(uK), pcg2d(st).x));
}
// Hi-Z occlusion test. Every point of a Gaussian carries the SAME depth (its centre's view depth) and lies
// inside the axis-aligned bound of its rectangle, so if every pixel of that bound already holds a strictly
// nearer depth, none of its points can ever win: skipping it cannot change the image (exact, not a heuristic).
#if defined(PHASE) && PHASE == 2
bool occluded(vec2 pm, vec2 e1, float r1, float r2, uint dbits){
  vec2 e2 = vec2(-e1.y, e1.x); vec2 ext = abs(e1) * r1 + abs(e2) * r2;
  ivec2 lo = max(ivec2(floor(pm - ext)), ivec2(0)); ivec2 hi = min(ivec2(floor(pm + ext)), ivec2(uVP) - 1);
  if (hi.x < lo.x || hi.y < lo.y) return false;
  uint m = 0u;
  ivec2 a = lo >> 3, b = hi >> 3;
  if (b.x - a.x < 4 && b.y - a.y < 4) {
    for (int y = a.y; y <= b.y; y++) for (int x = a.x; x <= b.x; x++) m = max(m, imageLoad(uHZ8, ivec2(x, y)).r);
  } else {
    a = lo >> 6; b = hi >> 6;
    if (b.x - a.x >= 4 || b.y - a.y >= 4) return false;
    for (int y = a.y; y <= b.y; y++) for (int x = a.x; x <= b.x; x++) m = max(m, imageLoad(uHZ64, ivec2(x, y)).r);
  }
  return dbits > m;
}
#endif
"""
CS = r"""
uint gid1d(){ return (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x; }
"""

# PHASE 0: plain.  PHASE 1: only Gaussians that won a pixel last frame.  PHASE 2: all, minus Hi-Z-occluded ones.
# The point count of a Gaussian depends only on (g, frame), so phases 1 and 2 agree on every Gaussian they share.
PREPROCESS = COMMON + CS + r"""
void main(){
  uint v = gid1d(); if (v >= uint(uG)) return; uint g = remap(v);
  uint units = 0u;
#if PHASE == 1
  if (imageLoad(uFlag, at(g, uint(CW))).r != uint(uFrame - 1)) { imageStore(uCounts, at(v, uint(CW)), uvec4(0u)); return; }
#endif
  vec2 pm; vec3 cov; float depth, op; vec2 e1; float r1, r2;
  if (project(g, pm, cov, depth, op, e1, r1, r2)) {
    units = unit_count(g, cov, op);
#if PHASE == 2
    if (units > 0u && occluded(pm, e1, r1, r2, floatBitsToUint(depth))) units = 0u;
#endif
#if PHASE == 3
    if (units > 0u) {                         // tiles: count this Gaussian into every tile its bound touches
      vec2 e2 = vec2(-e1.y, e1.x); vec2 ext = abs(e1) * r1 + abs(e2) * r2;
      ivec2 lo = max(ivec2(floor(pm - ext)), ivec2(0)) / TS, hi = min(ivec2(floor(pm + ext)), ivec2(uVP) - 1) / TS;
      if (hi.x >= lo.x && hi.y >= lo.y) {
        for (int y = lo.y; y <= hi.y; y++) for (int x = lo.x; x <= hi.x; x++) imageAtomicAdd(uTileOff, ivec2(x, y), 1u);
        imageStore(uCounts, at(v, uint(CW)), uvec4(uint(lo.x) | (uint(lo.y) << 8) | (uint(hi.x) << 16) | (uint(hi.y) << 24)));
        return; }
    }
#endif
  }
#if PHASE == 3
  imageStore(uCounts, at(v, uint(CW)), uvec4(0xFFFFFFFFu)); return;
#endif
  imageStore(uCounts, at(v, uint(CW)), uvec4(units));
}"""

SPLAT = COMMON + CS + r"""
void main(){
  uint u = gid1d(); if (u >= uint(uUnits)) return;
  uint lo = 0u, hi = uint(uG) - 1u;                                       // binary search over the prefix sum
  while (lo < hi) { uint mid = (lo + hi + 1u) >> 1; if (imageLoad(uCounts, at(mid, uint(CW))).r <= u) lo = mid; else hi = mid - 1u; }
  uint j = u - imageLoad(uCounts, at(lo, uint(CW))).r; uint g = remap(lo);  // j-th unit of Gaussian g
#if SKIPFLAG == 1
  if (imageLoad(uFlag, at(g, uint(CW))).r == uint(uFrame - 1)) return;    // its depths are already in (phase 1)
#endif
  vec2 pm; vec3 cov; float depth, op; vec2 e1; float r1, r2;
  if (!project(g, pm, cov, depth, op, e1, r1, r2)) return;
  uint dbits = floatBitsToUint(depth);
  float c0 = sqrt(cov.x), c1 = cov.y / c0, c2 = sqrt(max(cov.z - c1*c1, 0.0));
  float det = cov.x*cov.z - cov.y*cov.y; vec3 con = vec3(cov.z, -cov.y, cov.x) / det; vec2 e2 = vec2(-e1.y, e1.x);
  uvec2 st = makeSeed(hash32(g) ^ (j * 0x9E3779B9u), uint(uFrame) * 4u + 1u);   // depends on (g, j, frame) only
  for (int p = 0; p < uK; p++) {
    vec2 r = pcg2d(st);
    vec2 xy = correctedBoxMuller(r.x, r.y, op);
    ivec2 pix = ivec2(floor(vec2(pm.x + c0*xy.x, pm.y + c1*xy.x + c2*xy.y)));
    if (pix.x < 0 || pix.y < 0 || pix.x >= int(uVP.x) || pix.y >= int(uVP.y)) continue;
    vec2 d = (vec2(pix) + 0.5) - pm;
    if (abs(dot(d, e1)) > r1 || abs(dot(d, e2)) > r2) continue;
    if (op * exp(-0.5*(con.x*d.x*d.x + con.z*d.y*d.y) - con.y*d.x*d.y) < uCut) continue;
#if PASS == 1
#if EARLY == 1
    if (imageLoad(uDepth, pix).r <= dbits) continue;                      // atomicMin would be a no-op
#endif
    imageAtomicMin(uDepth, pix, dbits);
#else
    if (imageLoad(uDepth, pix).r == dbits) imageAtomicMin(uId, pix, g);
#endif
  }
}"""

TSCATTER = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
uint gid1d(){ return (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x; }
void main(){
  uint g = gid1d(); if (g >= uint(uG)) return;
  uint r = imageLoad(uCounts, at(g, uint(CW))).r; if (r == 0xFFFFFFFFu) return;
  ivec2 lo = ivec2(int(r & 255u), int((r >> 8) & 255u)), hi = ivec2(int((r >> 16) & 255u), int(r >> 24));
  for (int y = lo.y; y <= hi.y; y++) for (int x = lo.x; x <= hi.x; x++) {
    uint slot = imageAtomicAdd(uTileOff, ivec2(x, y), 1u);          // exclusive offset -> ends as the tile's end
    if (slot < uint(uCap)) imageStore(uPairs, at(slot, uint(CW)), uvec4(g)); }
}"""

# one workgroup per TS x TS tile: regenerate the points of every Gaussian listed for the tile, keep those inside,
# nearest-wins in SHARED memory. I64: one pass, atomicMin(depth << 32 | id) (NVIDIA extension). Else two passes.
TILE = r"""
#if I64 == 1
#extension GL_NV_shader_atomic_int64 : require
#extension GL_ARB_gpu_shader_int64 : require
shared uint64_t sb[TS * TS];
#else
shared uint sd[TS * TS]; shared uint si[TS * TS];
#endif
""" + COMMON + r"""
void splat_tile(uint g, ivec2 org, int pass){
  vec2 pm; vec3 cov; float depth, op; vec2 e1; float r1, r2;
  if (!project(g, pm, cov, depth, op, e1, r1, r2)) return;
  uint units = unit_count(g, cov, op);
  uint dbits = floatBitsToUint(depth);
  float c0 = sqrt(cov.x), c1 = cov.y / c0, c2 = sqrt(max(cov.z - c1*c1, 0.0));
  float det = cov.x*cov.z - cov.y*cov.y; vec3 con = vec3(cov.z, -cov.y, cov.x) / det; vec2 e2 = vec2(-e1.y, e1.x);
  for (uint j = 0u; j < units; j++) {
    uvec2 st = makeSeed(hash32(g) ^ (j * 0x9E3779B9u), uint(uFrame) * 4u + 1u);  // the SAME points as option 1
    for (int p = 0; p < uK; p++) {
      vec2 r = pcg2d(st);
      vec2 xy = correctedBoxMuller(r.x, r.y, op);
      ivec2 pix = ivec2(floor(vec2(pm.x + c0*xy.x, pm.y + c1*xy.x + c2*xy.y)));
      ivec2 l = pix - org;
      if (l.x < 0 || l.y < 0 || l.x >= TS || l.y >= TS) continue;            // another tile's point
      if (pix.x >= int(uVP.x) || pix.y >= int(uVP.y)) continue;
      vec2 d = (vec2(pix) + 0.5) - pm;
      if (abs(dot(d, e1)) > r1 || abs(dot(d, e2)) > r2) continue;
      if (op * exp(-0.5*(con.x*d.x*d.x + con.z*d.y*d.y) - con.y*d.x*d.y) < uCut) continue;
      int k = l.y * TS + l.x;
#if I64 == 1
      atomicMin(sb[k], (uint64_t(dbits) << 32) | uint64_t(g));
#else
      if (pass == 0) atomicMin(sd[k], dbits); else if (sd[k] == dbits) atomicMin(si[k], g);
#endif
    }
  }
}
void main(){
  ivec2 tc = ivec2(gl_WorkGroupID.xy); uint lid = gl_LocalInvocationID.x;
  int TW = int(gl_NumWorkGroups.x); int t = tc.y * TW + tc.x;
  for (uint k = lid; k < uint(TS * TS); k += 256u) {
#if I64 == 1
    sb[k] = 0xFFFFFFFFFFFFFFFFul;
#else
    sd[k] = 0xFFFFFFFFu; si[k] = 0xFFFFFFFFu;
#endif
  }
  barrier();
  uint end = imageLoad(uTileOff, tc).r;
  uint start = (t == 0) ? 0u : imageLoad(uTileOff, ivec2((t - 1) % TW, (t - 1) / TW)).r;
  end = min(end, uint(uCap));
  ivec2 org = tc * TS;
  for (uint i = start + lid; i < end; i += 256u) splat_tile(imageLoad(uPairs, at(i, uint(CW))).r, org, 0);
#if I64 == 0
  barrier();
  for (uint i = start + lid; i < end; i += 256u) splat_tile(imageLoad(uPairs, at(i, uint(CW))).r, org, 1);
#endif
  barrier();
  for (uint k = lid; k < uint(TS * TS); k += 256u) {
    ivec2 pix = org + ivec2(int(k) % TS, int(k) / TS);
    if (pix.x >= int(uVP.x) || pix.y >= int(uVP.y)) continue;
#if I64 == 1
    imageStore(uId, pix, uvec4(uint(sb[k] & 0xFFFFFFFFul)));
#else
    imageStore(uId, pix, uvec4(si[k]));
#endif
  }
}"""

TCLEAR = r"""
void main(){ ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uTW || p.y >= uTH) return; imageStore(uA, p, uvec4(0u)); }"""

HIZ = r"""
void main(){
  ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uDW || p.y >= uDH) return;
  uint m = 0u; ivec2 b = p * 8;
  for (int y = 0; y < 8; y++) for (int x = 0; x < 8; x++) {
    ivec2 q = b + ivec2(x, y); if (q.x < uSW && q.y < uSH) m = max(m, imageLoad(uSrc, q).r); }
  imageStore(uDst, p, uvec4(m));
}"""

FILL = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
uint gid1d(){ return (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x; }
void main(){ uint u = gid1d(); if (u >= uint(uN)) return; imageStore(uA, at(u, uint(CW)), uvec4(uint(uVal))); }"""

CLEAR = r"""
void main(){ ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uSW || p.y >= uSH) return;
  imageStore(uDepth, p, uvec4(0xFFFFFFFFu)); imageStore(uId, p, uvec4(0xFFFFFFFFu)); }"""

RESOLVE = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
void main(){
  ivec2 p = ivec2(gl_GlobalInvocationID.xy); if (p.x >= uW || p.y >= uH) return;
  vec3 c = vec3(0.0); float a = 0.0;
  for (int dy = 0; dy < SS; dy++) for (int dx = 0; dx < SS; dx++) {
    uint id = imageLoad(uId, p * SS + ivec2(dx, dy)).r;
    if (id != 0xFFFFFFFFu) {
#if MARK == 1
      imageStore(uFlag, at(id, uint(CW)), uvec4(uint(uFrame)));          // "won a pixel in frame uFrame"
#endif
      uint inst = id / uint(uN); uint i = id - inst * uint(uN); uint b = i * 4u;
      vec4 d2 = texelFetch(uData, at(b+2u, 4096u), 0), d3 = texelFetch(uData, at(b+3u, 4096u), 0);
      c += vec3(d2.z, d2.w, d3.x); a += 1.0; } }
  vec4 o = vec4(c, a) / float(SS * SS);
  imageStore(uOut, p, o);
  imageStore(uAcc, p, imageLoad(uAcc, p) + o);
}"""

# in-place exclusive prefix sum, 1024 elements per 256-thread group (Hillis-Steele), block totals to uS
SCAN = r"""
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

ADD = r"""
ivec2 at(uint lin, uint w){ return ivec2(int(lin % w), int(lin / w)); }
void main(){
  uint idx = (gl_WorkGroupID.y * gl_NumWorkGroups.x + gl_WorkGroupID.x) * 256u + gl_LocalInvocationID.x;
  if (idx >= uint(uN)) return;
  uint add = imageLoad(uS, at(idx / 1024u, uint(uSW_))).r;
  ivec2 c = at(idx, uint(uAW)); imageStore(uA, c, uvec4(imageLoad(uA, c).r + add));
}"""


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


def groups1d(n, local=256):
    g = max(1, (n + local - 1) // local)
    gx = min(g, 65535)
    return gx, (g + gx - 1) // gx


def img_u32(n, width):
    w = max(1, min(width, n)); h = max(1, (n + w - 1) // w)
    return gpu.types.GPUTexture((w, h), format='R32UI'), w


def read_u32(tex):
    b = tex.read()
    try:
        b.dimensions = tex.width * tex.height
        return np.array(b, dtype=np.uint32)
    except Exception:
        return np.array(b.to_list(), dtype=np.uint64).ravel().astype(np.uint32)


def read_f32(tex, ch=4):
    b = tex.read()
    b.dimensions = tex.width * tex.height * ch
    return np.array(b, dtype=np.float32).reshape(tex.height, tex.width, ch)


def scan_levels(n):
    """Block-total level sizes for an n-element scan (last level has 1 element = grand total)."""
    out = []; m = n
    while True:
        groups = (m + 1023) // 1024; out.append(groups)
        if groups <= 1: return out
        m = groups


class Stochastic:
    PC = [('MAT4', 'uViewProj'), ('VEC3', 'uCam'), ('VEC3', 'uR0'), ('VEC3', 'uR1'), ('VEC3', 'uR2'),
          ('VEC2', 'uF'), ('VEC2', 'uVP'), ('FLOAT', 'uSigma'), ('FLOAT', 'uBlur'), ('FLOAT', 'uCut'),
          ('INT', 'uN'), ('INT', 'uG'), ('INT', 'uFrame'), ('INT', 'uK'), ('INT', 'uUnits'), ('INT', 'uInstMap', 32),
          ('MAT4', 'uModels', 32)]

    def __init__(self, cloud, sigma):
        self.cloud = cloud; self.N = int(cloud.d['count']); self.sigma = sigma
        self.SW, self.SH = W * SS, H * SS
        PC = self.PC; smp = [(0, 'FLOAT_2D', 'uData')]; RW = {'READ', 'WRITE'}
        cw = [('CW', CW)]
        flag_r = (5, 'R32UI', 'UINT_2D', 'uFlag', {'READ'})
        hz = [(6, 'R32UI', 'UINT_2D', 'uHZ8', {'READ'}), (7, 'R32UI', 'UINT_2D', 'uHZ64', {'READ'})]
        counts_w = (0, 'R32UI', 'UINT_2D', 'uCounts', {'WRITE'})
        self.sh_pre = {0: _mk(PREPROCESS, (256, 1, 1), PC, [counts_w], smp, cw + [('PHASE', 0)]),
                       1: _mk(PREPROCESS, (256, 1, 1), PC, [counts_w, flag_r], smp, cw + [('PHASE', 1)]),
                       2: _mk(PREPROCESS, (256, 1, 1), PC, [counts_w] + hz, smp, cw + [('PHASE', 2)])}
        TSd = [('TS', TS)]
        toff = (4, 'R32UI', 'UINT_2D', 'uTileOff', {'READ', 'WRITE'})
        self.sh_pre[3] = _mk(PREPROCESS, (256, 1, 1), PC, [counts_w, toff], smp, cw + TSd + [('PHASE', 3)])
        self.sh_tscatter = _mk(TSCATTER, (256, 1, 1), [('INT', 'uG'), ('INT', 'uCap')],
                               [(0, 'R32UI', 'UINT_2D', 'uCounts', {'READ'}), toff,
                                (3, 'R32UI', 'UINT_2D', 'uPairs', {'WRITE'})], defines=cw)
        self.sh_tile = {}
        for i64 in (1, 0):
            try:
                self.sh_tile[i64] = _mk(TILE, (256, 1, 1), PC + [('INT', 'uCap')],
                                        [(3, 'R32UI', 'UINT_2D', 'uPairs', {'READ'}), (4, 'R32UI', 'UINT_2D', 'uTileOff', {'READ'}),
                                         (2, 'R32UI', 'UINT_2D', 'uId', {'WRITE'})], smp, cw + TSd + [('I64', i64)])
            except Exception as e:
                print('[stoch] tile shader I64=%d failed: %s' % (i64, e))
        self.sh_tclear = _mk(TCLEAR, (16, 16, 1), [('INT', 'uTW'), ('INT', 'uTH')], [(0, 'R32UI', 'UINT_2D', 'uA', {'WRITE'})])
        self.TW, self.TH = (self.SW + TS - 1) // TS, (self.SH + TS - 1) // TS
        self.tileoff = gpu.types.GPUTexture((self.TW, self.TH), format='R32UI')
        self.tlevels = [img_u32(n, CW) for n in scan_levels(self.TW * self.TH)]
        self.pair_cap = 0; self.last_pairs = 0
        self.sh_pass = {}
        for p, early, skip in ((1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0)):
            imgs = [(0, 'R32UI', 'UINT_2D', 'uCounts', {'READ'}), (1, 'R32UI', 'UINT_2D', 'uDepth', RW),
                    (2, 'R32UI', 'UINT_2D', 'uId', RW)] + ([flag_r] if skip else [])
            self.sh_pass[(p, early, skip)] = _mk(SPLAT, (256, 1, 1), PC, imgs, smp,
                                                 cw + [('PASS', p), ('EARLY', early), ('SKIPFLAG', skip)])
        self.sh_hiz = _mk(HIZ, (8, 8, 1), [('INT', 'uSW'), ('INT', 'uSH'), ('INT', 'uDW'), ('INT', 'uDH')],
                          [(0, 'R32UI', 'UINT_2D', 'uSrc', {'READ'}), (1, 'R32UI', 'UINT_2D', 'uDst', {'WRITE'})])
        self.sh_fill = _mk(FILL, (256, 1, 1), [('INT', 'uN'), ('INT', 'uVal')],
                           [(0, 'R32UI', 'UINT_2D', 'uA', {'WRITE'})], defines=cw)
        self.sh_clear = _mk(CLEAR, (16, 16, 1), [('INT', 'uSW'), ('INT', 'uSH')],
                            [(0, 'R32UI', 'UINT_2D', 'uDepth', {'WRITE'}), (1, 'R32UI', 'UINT_2D', 'uId', {'WRITE'})])
        res_imgs = [(0, 'R32UI', 'UINT_2D', 'uId', {'READ'}), (1, 'RGBA32F', 'FLOAT_2D', 'uOut', {'WRITE'}),
                    (2, 'RGBA32F', 'FLOAT_2D', 'uAcc', RW)]
        res_pc = [('INT', 'uW'), ('INT', 'uH'), ('INT', 'uN'), ('INT', 'uFrame')]
        self.sh_res = {0: _mk(RESOLVE, (16, 16, 1), res_pc, res_imgs, smp, cw + [('SS', SS), ('MARK', 0)]),
                       1: _mk(RESOLVE, (16, 16, 1), res_pc, res_imgs + [(5, 'R32UI', 'UINT_2D', 'uFlag', {'WRITE'})],
                              smp, cw + [('SS', SS), ('MARK', 1)])}
        scan_pc = [('INT', 'uN'), ('INT', 'uAW'), ('INT', 'uSW_')]
        self.sh_scan = _mk(SCAN, (256, 1, 1), scan_pc,
                           [(0, 'R32UI', 'UINT_2D', 'uA', RW), (1, 'R32UI', 'UINT_2D', 'uS', {'WRITE'})])
        self.sh_add = _mk(ADD, (256, 1, 1), scan_pc,
                          [(0, 'R32UI', 'UINT_2D', 'uA', RW), (1, 'R32UI', 'UINT_2D', 'uS', {'READ'})])
        # EWA low-pass blur in SUPERSAMPLED px^2: 0.3*ss^2 == the viewport's 0.3 px^2 at display resolution. The
        # quality check compares against the sorted renderer drawn AT the supersampled size (0.3 px^2 of THOSE
        # pixels), so the caller sets 0.3 for that comparison.
        self.blur = 0.3 * SS * SS
        self.depth = gpu.types.GPUTexture((self.SW, self.SH), format='R32UI')
        self.ids = gpu.types.GPUTexture((self.SW, self.SH), format='R32UI')
        self.hz8 = gpu.types.GPUTexture(((self.SW + 7) // 8, (self.SH + 7) // 8), format='R32UI')
        self.hz64 = gpu.types.GPUTexture(((self.hz8.width + 7) // 8, (self.hz8.height + 7) // 8), format='R32UI')
        self.out = gpu.types.GPUTexture((W, H), format='RGBA32F')
        self.acc = gpu.types.GPUTexture((W, H), format='RGBA32F')
        self.G = None

    def ensure(self, G):
        if self.G == G:
            return
        self.G = G
        self.counts, self.cw = img_u32(G, CW)
        self.levels = [img_u32(n, CW) for n in scan_levels(G)]
        self.flags, _ = img_u32(G, CW)
        self.reset_flags()

    def visible(self, models, vm, pm):
        """Instances that can put a point on screen. EXACT (conservative) against the shader's own rejection: for
        every splat centre in the instance's box, the shader's screen rectangle is bounded using the EWA Jacobian
        norm, ||J|| <= f/tz * sqrt(1 + (tx/tz)^2 + (ty/tz)^2), and the rectangle half-extent <= sqrt(2) * r1 with
        r1 <= sigma * (||J|| * s_max + sqrt(blur)). tx/tz is linear-fractional, so its extremes are at box corners."""
        if not hasattr(self, '_box'):
            xyz = self.cloud.d['xyz']; sc = self.cloud.d.get('scale')
            self._smax = float(np.abs(sc).max()) if sc is not None else 1.0
            mn = xyz.min(0); mx = xyz.max(0)
            self._box = np.array([(x, y, z, 1.0) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])])
        R = np.array([list(vm[0][:3]), list(vm[1][:3]), [-v for v in vm[2][:3]]])        # right, up, forward
        cam = np.array(vm.inverted().translation)
        fx = 0.5 * self.SW * pm[0][0]; fy = 0.5 * self.SH * pm[1][1]; fm = max(fx, fy)
        out = []
        for k, M in enumerate(models):
            Mn = np.array(M)
            t = (R @ ((Mn @ self._box.T)[:3].T - cam).T).T                                # view-space corners
            tz = t[:, 2]
            if tz.max() < 0.02: continue                                                  # all behind: shader rejects
            if tz.min() <= 0.02: out.append(k); continue                                  # straddles near plane: keep
            a = t[:, 0] / tz; b = t[:, 1] / tz
            s = self._smax * float(np.linalg.norm(Mn[:3, :3], 2))
            jn = fm / tz.min() * math.sqrt(1.0 + max(a.max() ** 2, a.min() ** 2) + max(b.max() ** 2, b.min() ** 2))
            ext = math.sqrt(2.0) * self.sigma * (jn * s + math.sqrt(self.blur)) + 2.0
            if (fx * a.min() - ext > 0.5 * self.SW or fx * a.max() + ext < -0.5 * self.SW or
                    fy * b.min() - ext > 0.5 * self.SH or fy * b.max() + ext < -0.5 * self.SH):
                continue
            out.append(k)
        return out

    def reset_flags(self):
        s = self.sh_fill; s.bind(); s.image('uA', self.flags); s.uniform_int('uN', self.G); s.uniform_int('uVal', -1)
        gx, gy = groups1d(self.G); gpu.compute.dispatch(s, gx, gy, 1)

    def clear_acc(self):
        z = gpu.types.Buffer('FLOAT', W * H * 4, np.zeros(W * H * 4, np.float32))
        self.acc = gpu.types.GPUTexture((W, H), format='RGBA32F', data=z)

    def _uniforms(self, s, vm, pm, models, frame, units=0):
        """Set every uniform the shader kept (the compiler strips unused ones; setting those raises)."""
        right = Vector(vm[0][:3]); up = Vector(vm[1][:3]); fwd = -Vector(vm[2][:3])
        cam = vm.inverted().translation

        def f(n, v):
            try: s.uniform_float(n, v)
            except ValueError: pass

        def i(n, v):
            try: s.uniform_int(n, v)
            except ValueError: pass
        f('uViewProj', pm @ vm)
        f('uCam', cam); f('uR0', right); f('uR1', up); f('uR2', fwd)
        f('uF', (0.5 * self.SW * pm[0][0], 0.5 * self.SH * pm[1][1]))
        f('uVP', (float(self.SW), float(self.SH)))
        f('uSigma', self.sigma); f('uBlur', self.blur); f('uCut', 0.004)
        i('uN', self.N); i('uG', self.Gd); i('uFrame', frame)
        try:
            vis = list(self.vis) + [0] * (32 - len(self.vis))
            s.uniform_vector_int(s.uniform_from_name('uInstMap'), gpu.types.Buffer('INT', 32, vis), 1, 32)
        except ValueError: pass
        i('uK', K); i('uUnits', units)
        try: SU._set_mat4_array(s, 'uModels', models)
        except ValueError: pass
        try: s.uniform_sampler('uData', self.cloud.datatex)
        except ValueError: pass

    def _scan(self, base=None, bw=None, n=None, lv=None):
        """In-place exclusive prefix sum (default: of counts); returns the 1x1 grand-total texture."""
        if base is None: base, bw, n, lv = self.counts, self.cw, self.Gd, self.levels
        levels = [(base, bw, n)] + [(t, w, m) for (t, w), m in zip(lv, scan_levels(n))]
        for li in range(len(levels) - 1):
            a, aw, m = levels[li]; s, sw, _ = levels[li + 1]
            sh = self.sh_scan; sh.bind(); sh.image('uA', a); sh.image('uS', s)
            sh.uniform_int('uN', m); sh.uniform_int('uAW', aw); sh.uniform_int('uSW_', sw)
            gx, gy = groups1d((m + 1023) // 1024 * 256); gpu.compute.dispatch(sh, gx, gy, 1)
        for li in range(len(levels) - 3, -1, -1):
            a, aw, m = levels[li]; s, sw, _ = levels[li + 1]
            sh = self.sh_add; sh.bind(); sh.image('uA', a); sh.image('uS', s)
            sh.uniform_int('uN', m); sh.uniform_int('uAW', aw); sh.uniform_int('uSW_', sw)
            gx, gy = groups1d(m); gpu.compute.dispatch(sh, gx, gy, 1)
        return levels[-1][0]

    def _pre(self, phase, vm, pm, models, frame):
        s = self.sh_pre[phase]; s.bind(); self._uniforms(s, vm, pm, models, frame); s.image('uCounts', self.counts)
        if phase == 1: s.image('uFlag', self.flags)
        if phase == 2: s.image('uHZ8', self.hz8); s.image('uHZ64', self.hz64)
        gx, gy = groups1d(self.Gd); gpu.compute.dispatch(s, gx, gy, 1)
        return int(read_u32(self._scan())[0])

    def _pass(self, key, vm, pm, models, frame, units):
        sh = self.sh_pass[key]; sh.bind(); self._uniforms(sh, vm, pm, models, frame, units)
        sh.image('uCounts', self.counts); sh.image('uDepth', self.depth); sh.image('uId', self.ids)
        if key[2]: sh.image('uFlag', self.flags)
        gx, gy = groups1d(units); gpu.compute.dispatch(sh, gx, gy, 1)

    def _hiz(self):
        for src, dst, sw, sh_ in ((self.depth, self.hz8, self.SW, self.SH), (self.hz8, self.hz64, self.hz8.width, self.hz8.height)):
            s = self.sh_hiz; s.bind(); s.image('uSrc', src); s.image('uDst', dst)
            s.uniform_int('uSW', sw); s.uniform_int('uSH', sh_); s.uniform_int('uDW', dst.width); s.uniform_int('uDH', dst.height)
            gpu.compute.dispatch(s, (dst.width + 7) // 8, (dst.height + 7) // 8, 1)

    def frame(self, vm, pm, models, frame, mode='bsearch', T=None):
        """One stochastic frame into self.out (+ accumulated into self.acc). Returns point units drawn."""
        def mark(k):
            if T is not None:
                bench._gpu_sync(); t = time.perf_counter(); T[k] = T.get(k, 0.0) + (t - mark.t) * 1000.0; mark.t = t
        mark.t = time.perf_counter()
        self.ensure(self.N * len(models))
        self.vis = self.visible(models, vm, pm) if mode == 'cull' else list(range(len(models)))
        self.Gd = self.N * len(self.vis)
        if not self.vis:
            mode = 'none'
        early = 1 if mode in ('early', 'occl', 'cull') else 0
        s = self.sh_clear; s.bind(); s.image('uDepth', self.depth); s.image('uId', self.ids)
        s.uniform_int('uSW', self.SW); s.uniform_int('uSH', self.SH)
        gpu.compute.dispatch(s, (self.SW + 15) // 16, (self.SH + 15) // 16, 1); mark('clear')
        drawn = 0
        if mode in ('tile64', 'tile32'):
            s = self.sh_tclear; s.bind(); s.image('uA', self.tileoff); s.uniform_int('uTW', self.TW); s.uniform_int('uTH', self.TH)
            gpu.compute.dispatch(s, (self.TW + 15) // 16, (self.TH + 15) // 16, 1)
            s = self.sh_pre[3]; s.bind(); self._uniforms(s, vm, pm, models, frame); s.image('uCounts', self.counts)
            s.image('uTileOff', self.tileoff)
            gx, gy = groups1d(self.G); gpu.compute.dispatch(s, gx, gy, 1); mark('preprocess')
            pairs = int(read_u32(self._scan(self.tileoff, self.TW, self.TW * self.TH, self.tlevels))[0]); mark('tilescan')
            if pairs > self.pair_cap:
                self.pair_cap = int(pairs * 1.3) + 4096
                self.pairs, _ = img_u32(self.pair_cap, CW)
            s = self.sh_tscatter; s.bind(); s.image('uCounts', self.counts); s.image('uTileOff', self.tileoff)
            s.image('uPairs', self.pairs); s.uniform_int('uG', self.G); s.uniform_int('uCap', self.pair_cap)
            gx, gy = groups1d(self.G); gpu.compute.dispatch(s, gx, gy, 1); mark('scatter')
            s = self.sh_tile[1 if mode == 'tile64' else 0]; s.bind(); self._uniforms(s, vm, pm, models, frame)
            try: s.uniform_int('uCap', self.pair_cap)
            except ValueError: pass
            s.image('uPairs', self.pairs); s.image('uTileOff', self.tileoff); s.image('uId', self.ids)
            gpu.compute.dispatch(s, self.TW, self.TH, 1); mark('tiles')
            self.last_pairs = pairs; units = 0
        elif mode == 'occl':
            u1 = self._pre(1, vm, pm, models, frame); mark('pre1')        # last frame's winners, depth only
            if u1 > 0: self._pass((1, 1, 0), vm, pm, models, frame, u1)
            drawn += u1; mark('passA1')
            self._hiz(); mark('hiz')
            units = self._pre(2, vm, pm, models, frame); mark('pre2')     # everything not provably hidden
            if units > 0: self._pass((1, 1, 1), vm, pm, models, frame, units)
            mark('passA2')
        elif mode == 'none':
            units = 0
        else:
            units = self._pre(0, vm, pm, models, frame); mark('preprocess')
            if units > 0: self._pass((1, early, 0), vm, pm, models, frame, units)
            mark('passA')
        if units > 0: self._pass((2, 0, 0), vm, pm, models, frame, units)
        if mode not in ('tile64', 'tile32'): mark('passB')
        drawn += units
        mk = 1 if mode == 'occl' else 0
        s = self.sh_res[mk]; s.bind(); s.image('uId', self.ids); s.image('uOut', self.out); s.image('uAcc', self.acc)
        if mk: s.image('uFlag', self.flags)
        s.uniform_int('uW', W); s.uniform_int('uH', H); s.uniform_int('uN', self.N)
        if mk: s.uniform_int('uFrame', frame)
        s.uniform_sampler('uData', self.cloud.datatex)
        gpu.compute.dispatch(s, (W + 15) // 16, (H + 15) // 16, 1); mark('resolve')
        return drawn


# ─────────────────────────────── scene / camera ───────────────────────────────
# ─────────────────────────────── scene / camera ───────────────────────────────
SU = None


def _mod(suffix):
    return importlib.import_module('vertex_lit_renderer.' + suffix)


def convert(tree, count):
    vls = bpy.context.scene.vertex_lit
    win, area, region, rv3d = bench._find_view3d()
    vls.splat_method = 'SURFEL'; vls.splat_count = int(count); vls.splat_color = 'TEXTURE'
    vls.splat_hide_src = True; vls.splat_sigma = SIGMA
    tree.hide_set(False)
    for o in bpy.context.view_layer.objects:
        if o.select_get(): o.select_set(False)
    tree.select_set(True); bpy.context.view_layer.objects.active = tree
    with bpy.context.temp_override(window=win, area=area, region=region, active_object=tree, object=tree,
                                   selected_objects=[tree]):
        bpy.ops.vertex_lit.generate_splats()
    anchor = bpy.context.view_layer.objects.active
    cloud = _mod('splat_render').SPLAT_CLOUDS[int(anchor['vlr_splat_id'])]
    anchor.hide_set(True)                         # nothing draws in the viewport; all rendering is offscreen here
    return anchor, cloud


def grid_models(anchor, n, spacing=5.0):
    cols = int(math.ceil(math.sqrt(n)))
    return [Matrix.Translation(Vector(((i % cols) * spacing, (i // cols) * spacing, 0.0))) @ anchor.matrix_world
            for i in range(n)]


def bounds(cloud, models):
    mn = cloud.d['xyz'].min(0); mx = cloud.d['xyz'].max(0)
    lo = Vector((1e30,) * 3); hi = Vector((-1e30,) * 3)
    for M in models:
        for x in (mn[0], mx[0]):
            for y in (mn[1], mx[1]):
                for z in (mn[2], mx[2]):
                    p = M @ Vector((float(x), float(y), float(z)))
                    for k in range(3): lo[k] = min(lo[k], p[k]); hi[k] = max(hi[k], p[k])
    return lo, hi


def camera(lo, hi, yaw_deg, w, h, fov=50.0):
    c = (lo + hi) * 0.5; r = (hi - lo).length * 0.5
    d = r / math.sin(math.radians(fov) * 0.5) * 0.85 * DIST
    R = Euler((math.radians(72.0), 0.0, math.radians(20.0 + yaw_deg))).to_matrix().to_4x4()
    pos = c + (R @ Vector((0.0, 0.0, d, 0.0))).to_3d()
    vm = (Matrix.Translation(pos) @ R).inverted()
    f = 1.0 / math.tan(math.radians(fov) * 0.5); a = w / h; n_, f_ = 0.1, d + 3.0 * r
    pm = Matrix(((f / a, 0, 0, 0), (0, f, 0, 0), (0, 0, (f_ + n_) / (n_ - f_), 2 * f_ * n_ / (n_ - f_)), (0, 0, -1, 0)))
    return vm, pm


def sorted_draw(cloud, models, vm, pm, w, h):
    if len(models) == 1:
        cloud._gpu_sort = True; cloud._radix_pref = True
        cloud.draw(vm, pm, w, h, write_depth=False, light=None, model=models[0], obj_key='__proto_%dx%d' % (w, h))
        return True
    ents = [(cloud, M, 'p%d' % i) for i, M in enumerate(models)]
    return bool(SU.SORTER.draw(ents, vm, pm, w, h, light=None, sigma=cloud.sigma, write_depth=False))


def render_sorted(cloud, models, vm, pm, w, h, off=None, read=False):
    own = off is None
    if own: off = gpu.types.GPUOffScreen(w, h, format='RGBA16F')
    img = None
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get(); fb.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(True)
            ok = sorted_draw(cloud, models, vm, pm, w, h)
            if read:
                buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT'); buf.dimensions = w * h * 4
                img = np.array(buf, dtype=np.float32).reshape(h, w, 4)
    finally:
        gpu.state.blend_set('NONE'); gpu.state.depth_test_set('NONE'); gpu.state.depth_mask_set(True)
        if own: off.free()
    return img, ok


def downsample(img, s):
    h, w, c = img.shape
    return img.reshape(h // s, s, w // s, s, c).mean(axis=(1, 3))


def err(a, b):
    d = a - b; mse = float(np.mean(d * d)); rmse = math.sqrt(mse)
    return rmse, (99.0 if mse <= 0 else 10.0 * math.log10(1.0 / mse))


def save_png(img, name):
    rgb = img[..., :3] + (1.0 - img[..., 3:4]) * 0.12                 # over a dark grey background
    rgba = np.concatenate([np.clip(rgb, 0, 1), np.ones_like(img[..., :1])], axis=-1)
    im = bpy.data.images.new(name, img.shape[1], img.shape[0], alpha=True, float_buffer=False)
    im.pixels.foreach_set(rgba.ravel()); p = os.path.join(OUT_DIR, name + '.png')
    im.filepath_raw = p; im.file_format = 'PNG'; im.save()
    return p


def median_ms(fn, frames):
    ts = []
    for i in range(frames):
        bench._gpu_sync(); t = time.perf_counter(); fn(i); bench._gpu_sync(); ts.append((time.perf_counter() - t) * 1000.0)
    return statistics.median(ts), ts




def run_scene(tree, per_tree, n_trees, clouds):
    if per_tree not in clouds:
        a, c = convert(tree, per_tree); c.ensure_gpu(); clouds[per_tree] = (a, c)
    anchor, cloud = clouds[per_tree]
    models = grid_models(anchor, n_trees)
    lo, hi = bounds(cloud, models)
    total = int(cloud.d['count']) * n_trees
    tag = '%dx%dk' % (n_trees, int(cloud.d['count']) // 1000)
    log(""); log("=" * 100)
    log("SCENE %d trees x %d = %.2fM splats | %dx%d | stochastic ss=%d (K=%d)" % (n_trees, int(cloud.d['count']), total / 1e6, W, H, SS, K))
    log("=" * 100)
    rec = {'trees': n_trees, 'per_tree': int(cloud.d['count']), 'total': total, 'modes': {}}
    # ── current sorted renderer, orbiting (every frame re-sorts) ──
    off = gpu.types.GPUOffScreen(W, H, format='RGBA16F')
    try:
        render_sorted(cloud, models, *camera(lo, hi, 0.0, W, H), W, H, off)                # warm-up
        med, _ = median_ms(lambda i: render_sorted(cloud, models, *camera(lo, hi, 3.0 * (i + 1), W, H), W, H, off), ORBIT_FRAMES)
        still, _ = median_ms(lambda i: render_sorted(cloud, models, *camera(lo, hi, 3.0 * ORBIT_FRAMES, W, H), W, H, off), 8)
    finally:
        off.free()
    rec['sorted_move_ms'] = med; rec['sorted_still_ms'] = still
    log("  SORTED (current: GPU radix sort + blend)   moving %.2f ms/frame | still (sort skipped) %.2f ms" % (med, still))
    ref_hi, ok = render_sorted(cloud, models, *camera(lo, hi, 0.0, W * SS, H * SS), W * SS, H * SS, read=True)
    ref = downsample(ref_hi, SS)
    save_png(ref, 'ref_sorted_' + tag)
    st = Stochastic(cloud, cloud.sigma)
    vm0, pm0 = camera(lo, hi, 0.0, W, H)
    ids_ref = None
    for mode in MODES:
        try:
            # exactness: the same frame (after the same previous frame, for occl's reuse) must give the SAME ids
            st.blur = 0.3 * SS * SS; st.ensure(st.N * len(models)); st.reset_flags()
            st.frame(*camera(lo, hi, -3.0, W, H), models, 49, mode); st.frame(vm0, pm0, models, 50, mode)
            ids = read_u32(st.ids)
            if ids_ref is None: ids_ref = ids; same = 'reference'
            else:
                nd = int(np.count_nonzero(ids != ids_ref))
                same = 'BIT-IDENTICAL to %s' % MODES[0] if nd == 0 else 'DIFFERS in %d of %d px' % (nd, ids.size)
            # speed: orbit, consecutive frames (occl reuses the previous frame's winners)
            st.frame(*camera(lo, hi, 0.0, W, H), models, 99, mode)
            units = []
            med_s, _ = median_ms(lambda i: units.append(st.frame(*camera(lo, hi, 3.0 * (i + 1), W, H), models, 100 + i, mode)), ORBIT_FRAMES)
            T = {}; f0 = 100 + ORBIT_FRAMES
            for i in range(4):
                st.frame(*camera(lo, hi, 3.0 * (ORBIT_FRAMES + i + 1), W, H), models, f0 + i, mode, T=T)
            T = {k: v / 4.0 for k, v in T.items()}
            pts = statistics.median(units) * K
            if mode in ('tile64', 'tile32'): T['pairs(M)'] = st.last_pairs / 1e6
            if mode == 'cull': T['visible trees'] = len(st.vis)
            st.blur = 0.3; st.clear_acc(); q = {}; n_done = 0; one = None
            for target in CONV:
                while n_done < target:
                    st.frame(vm0, pm0, models, 1000 + n_done, mode); n_done += 1
                    if n_done == 1: one = read_f32(st.out)
                q[target] = err(read_f32(st.acc) / float(n_done), ref)
            rec['modes'][mode] = dict(ms=med_s, stages=T, points=pts, q=q, same=same)
            log("  STOCHASTIC %-7s moving %6.2f ms/frame = %.2fx sorted  (%.1fM points) | %d frames %.1f dB | ids %s"
                % (mode, med_s, med / med_s, pts / 1e6, CONV[-1], q[CONV[-1]][1], same))
            log("       stages (ms, synced): " + " | ".join("%s %.2f" % (k, v) for k, v in T.items()))
            if mode == MODES[-1]:
                save_png(one, 'stoch_1frame_%s_%s' % (mode, tag))
        except Exception:
            log("  STOCHASTIC %s FAILED:\n%s" % (mode, traceback.format_exc()))
    status['scenes'].append(rec)
    return rec


def run():
    global bench, SU
    try:
        if bpy.app.background:
            raise RuntimeError('needs a live GPU session')
        if not bpy.data.filepath or 'claude' not in bpy.data.filepath.lower():
            raise RuntimeError('refusing to run on a non-scratch file')
        spec = importlib.util.spec_from_file_location('benchmark_splats', BENCH)
        bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
        SU = _mod('splat_unified')
        scene = bpy.context.scene; scene.render.engine = 'VERTEX_LIT'
        vls = scene.vertex_lit; vls.splat_gpu_sort = True; vls.splat_radix = True; vls.splat_unified = True
        import addon_utils
        ver = next((m.bl_info.get('version') for m in addon_utils.modules() if m.__name__ == 'vertex_lit_renderer'), None)
        log("STOCHASTIC POINT SPLATTING PROTOTYPE vs SORTED | addon %s | Blender %s | %s" % (ver, bpy.app.version_string, bench.detect_caps()['gpu']))
        log("scenes %s | modes %s | %dx%d | ss %d | K %d | orbit %d frames x 3 deg" % (SCENES, MODES, W, H, SS, K, ORBIT_FRAMES))
        for o in [o for o in scene.objects if o.get('vlr_splat_id') is not None]:
            bpy.data.objects.remove(o, do_unlink=True)
        tree = max((o for o in scene.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
        clouds = {}
        for per_tree, n in SCENES:
            try:
                run_scene(tree, per_tree, n, clouds)
            except Exception:
                log("  SCENE FAILED:\n" + traceback.format_exc())
        log(""); log("SUMMARY: moving camera, ms/frame (speed-up vs sorted) [quality after %d frames, dB]" % CONV[-1])
        log("  splats   sorted   " + "   ".join("%-24s" % m for m in MODES))
        for r in status['scenes']:
            cells = []
            for m in MODES:
                d = r['modes'].get(m)
                cells.append("%-24s" % ("%.2f (%.2fx) [%.1f]" % (d['ms'], r['sorted_move_ms'] / d['ms'], d['q'][CONV[-1]][1]) if d else 'failed'))
            log("  %5.1fM  %7.2f   %s" % (r['total'] / 1e6, r['sorted_move_ms'], "   ".join(cells)))
        status['ok'] = True
    except Exception:
        status['error'] = traceback.format_exc()
        log("!! FAILED:\n" + status['error'])
    with open(STATUS, 'w') as f:
        json.dump(status, f, indent=2, default=str)
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(run, first_interval=4.0)
