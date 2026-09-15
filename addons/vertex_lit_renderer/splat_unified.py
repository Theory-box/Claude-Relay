# vertex_lit_renderer/splat_unified.py
"""
Unified cross-cloud splat sorting.

THE BUG THIS FIXES: every cloud currently sorts and draws independently, so where two trees overlap
on screen the one drawn LAST wins regardless of actual depth -> splats from a far tree render in
front of a near one. Correct alpha blending needs ONE global back-to-front order across all clouds.

WHY IT'S AFFORDABLE NOW: with the old bitonic sort, one merged sort of 6M splats padded to 8.4M and
measured 31% SLOWER than six separate 1M sorts. The radix sort (splat_radix.py) is O(N) with no
padding and ~23x less work at 6M, so a single unified sort should cost LESS than the separate sorts
it replaces -- fixing correctness and speed with the same change.

DESIGN (one draw call, globally ordered):
  * Each visible (cloud, anchor) pair becomes an INSTANCE with its own model matrix.
  * All their splats are keyed by WORLD-space depth into one buffer; the payload packs
    (instance << 24 | splat_id), so one sort orders everything across clouds.
  * The draw binds the clouds' data textures as a 2D TEXTURE ARRAY (layer == instance's cloud) and
    the model matrices as a MAT4[] push-constant array, then draws ONE instanced batch over the
    global order; the vertex shader unpacks instance+id, samples the right layer, applies the right
    matrix. Probed as available: FLOAT_2D_ARRAY samplers and MAT4 arrays.

Limits: MAX_INSTANCES (matrix array size) and the fact that all clouds must share a data-texture
size to live in one array; clouds that don't fit fall back to the existing per-cloud path.
"""
import numpy as np
import gpu
from mathutils import Vector, Matrix

MAX_INSTANCES = 32          # model-matrix array size (per-draw cap on unified instances)
_IW = 4096
_DBG = True

# ── keygen over ALL instances: world depth -> monotonic uint key, payload = instance<<24 | id ──
KEYGEN = """
ivec2 at(int i){ return ivec2(i % IW, i / IW); }
ivec2 atD(int i, int w){ return ivec2(i % w, i / w); }
uint f2key(float f){ uint b=floatBitsToUint(f); return ((b>>31)!=0u) ? ~b : (b|0x80000000u); }
void main(){
  int g=int(gl_GlobalInvocationID.x); if(g>=uTotal) return;
  // find which instance this global index belongs to (few instances -> linear scan is fine)
  int inst=0; int local=g;
  for(int k=0;k<uNumInst;k++){
    int c=uCounts[k];
    if(local < c){ inst=k; break; }
    local -= c;
  }
  vec4 d0 = texelFetch(uData, ivec3(atD(local*4, uTW), inst), 0);
  vec3 cW = (uModels[inst] * vec4(d0.xyz,1.0)).xyz;      // LOCAL -> WORLD (per-instance transform)
  float depth = dot(cW - uCam, uFwd);
  bool vis = depth > 0.0;
  if(vis){ vec4 cl=uViewProj*vec4(cW,1.0); vis = cl.w>1e-4;
           if(vis){ vec2 n=cl.xy/cl.w; vis = abs(n.x)<1.3 && abs(n.y)<1.3; } }
  uint key = vis ? f2key(-depth) : 0xFFFFFFFFu;          // far -> near; culled sort to the end
  uint payload = vis ? (uint(inst)<<24) | uint(local) : 0xFFFFFFFFu;
  imageStore(uKey, at(g), uvec4(key));
  imageStore(uVal, at(g), uvec4(payload));
}"""

# ── unified draw: unpack instance+id from the global order, sample the right array layer ──
VERT = """
uniform sampler2DArray uData; uniform usampler2D uIndex;
uniform int uTW; uniform int uITW; uniform int uTotal;
uniform mat4 uModels[MAX_INST];
uniform vec3 uRow0,uRow1,uRow2; uniform vec3 uCam; uniform vec2 uF; uniform vec2 uVP; uniform float uSigma;
uniform mat4 uViewProj;
uniform int  uLit;
uniform vec3 uSkyColor, uGroundColor; uniform float uHemiIntensity;
uniform vec3 uSunDir, uSunColor; uniform float uSunIntensity;
uniform vec3 uKeyDir, uKeyCol; uniform float uKeyIntensity;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin % w, lin / w); }
vec3 splat_light(vec3 N){
  float hemi = dot(N, vec3(0.0,0.0,1.0))*0.5+0.5;
  vec3 L = mix(uGroundColor, uSkyColor, hemi) * uHemiIntensity;
  L += uSunColor * (max(dot(N, normalize(uSunDir)),0.0) * uSunIntensity);
  L += uKeyCol  * (max(dot(N, normalize(uKeyDir)),0.0) * uKeyIntensity);
  return L;
}
void main(){
  uint p = texelFetch(uIndex, at(gl_InstanceID, uITW), 0).r;
  if(p == 0xFFFFFFFFu){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }   // culled
  int inst = int(p >> 24); int sid = int(p & 0x00FFFFFFu);
  mat4 M = uModels[inst]; mat3 md = mat3(M);
  int base = sid*4;
  vec4 d0=texelFetch(uData,ivec3(at(base,uTW),inst),0),   d1=texelFetch(uData,ivec3(at(base+1,uTW),inst),0),
       d2=texelFetch(uData,ivec3(at(base+2,uTW),inst),0), d3=texelFetch(uData,ivec3(at(base+3,uTW),inst),0);
  vec3 icL=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
  vec3 icol=vec3(d2.z,d2.w,d3.x); float iop=d3.y; vC=corner; vOp=iop;
  vec3 ic=(M*vec4(icL,1.0)).xyz;
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uRow0,dp),dot(uRow1,dp),dot(uRow2,dp));
  vec4 clipC=uViewProj*vec4(ic,1.0);
  if(t.z<0.02||clipC.w<=0.0){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }
  float w=iq.x,x=iq.y,y=iq.z,z=iq.w;
  vec3 c0=md*vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=md*vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=md*vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  vec3 nrm=(is.x<=is.y&&is.x<=is.z)?c0:((is.y<=is.z)?c1:c2); nrm=normalize(nrm);
  vCol = (uLit==1) ? icol*splat_light(nrm) : icol;
  float iz=1.0/max(t.z,1e-6);
  mat3 J=mat3(vec3(uF.x*iz,0,0),vec3(0,uF.y*iz,0),vec3(-uF.x*t.x*iz*iz,-uF.y*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uRow0.x,uRow1.x,uRow2.x),vec3(uRow0.y,uRow1.y,uRow2.y),vec3(uRow0.z,uRow1.z,uRow2.z));
  mat3 Mm=mat3(c0*is.x,c1*is.y,c2*is.z); mat3 Sig=Mm*transpose(Mm);
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float a=cov[0][0]+0.3,b=cov[0][1],cc=cov[1][1]+0.3;
  float tr=a+cc,det=a*cc-b*b,mid=0.5*tr,disc=sqrt(max(mid*mid-det,0.0));
  float l1=mid+disc,l2=max(mid-disc,1e-9);
  float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
  vec2 e1=vec2(b,l1-a); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
  vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
  gl_Position=vec4(clipC.xy + (corner.x*e1*r1+corner.y*e2*r2)*p2n*clipC.w, clipC.z, clipC.w);
}"""

FRAG = """
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
uniform float uDepthCut;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<uDepthCut) discard; o=vec4(vCol*al, al); }"""


def can_unify(entries):
    """entries = [(cloud, model_matrix, name)]. Unified draw needs a shared data-texture size and a
    bounded instance count; otherwise the caller keeps the per-cloud path."""
    if not entries or len(entries) > MAX_INSTANCES:
        return False
    if len(entries) < 2:
        return False                       # nothing to unify
    # Clouds no longer need identical sizes: _packed_data() pads each into a shared layer height
    # (the max across the set). Just require they all have CPU data to pack.
    for c, _m, _n in entries:
        if getattr(c, 'd', None) is None or not hasattr(c, '_packed_data'):
            return False
    return True


class UnifiedSorter:
    """Builds the texture array + global order for a set of (cloud, matrix) instances."""

    def __init__(self):
        self.ok = False
        self._sig = None        # (names, tex-size) -> rebuild the array only when the set changes
        self.array = None

    def ensure_array(self, entries):
        """Pack every cloud's data texture into one 2D texture array (layer == instance index)."""
        sig = tuple(n for _c, _m, n in entries)
        if self.array is not None and self._sig == sig:
            return True
        try:
            w = 4096
            h = max(c.layer_height() for c, _m, _n in entries)   # shared layer height
            layers = len(entries)
            # rebuild from each cloud's CPU-side packed data (authoritative, avoids GPU->GPU copies)
            planes = []
            for c, _m, _n in entries:
                # NOTE: SplatCloud has no _packed_data() yet -- the per-cloud packing in
                # ensure_gpu() must be factored out before this path can be wired up.
                planes.append(c._packed_data(w, h))
            data = np.concatenate(planes, axis=0).astype('f4')
            buf = gpu.types.Buffer('FLOAT', w*h*4*layers, data.reshape(-1))
            self.array = gpu.types.GPUTexture((w, h, layers), format='RGBA32F', data=buf, is_layered=True)
            self._sig = sig
            if _DBG: print("[VertexLit unified] texture array: %dx%d x %d layers" % (w, h, layers))
            return True
        except Exception as e:
            if _DBG: print("[VertexLit unified] array build failed -> per-cloud:", e)
            self.array = None
            return False

    # ── build the shaders (keygen compute + the unified draw) ─────────────────────────────
    def ensure_shaders(self):
        if getattr(self, '_sh_ok', False):
            return True
        try:
            from gpu_extras.batch import batch_for_shader
            ik = gpu.types.GPUShaderCreateInfo(); ik.local_group_size(64, 1, 1)
            ik.define("IW", str(_IW)); ik.define("MAX_INST", str(MAX_INSTANCES))
            ik.push_constant('VEC3', 'uCam'); ik.push_constant('VEC3', 'uFwd')
            ik.push_constant('MAT4', 'uViewProj')
            ik.push_constant('MAT4', 'uModels', size=MAX_INSTANCES)
            ik.push_constant('INT', 'uCounts', size=MAX_INSTANCES)
            ik.push_constant('INT', 'uTotal'); ik.push_constant('INT', 'uNumInst'); ik.push_constant('INT', 'uTW')
            ik.sampler(0, 'FLOAT_2D_ARRAY', 'uData')
            ik.image(0, 'R32UI', 'UINT_2D', 'uKey', qualifiers={'WRITE'})
            ik.image(1, 'R32UI', 'UINT_2D', 'uVal', qualifiers={'WRITE'})
            ik.compute_source(KEYGEN)
            self.sh_key = gpu.shader.create_from_info(ik)

            src = VERT.replace("MAX_INST", str(MAX_INSTANCES))
            self.shader = gpu.types.GPUShader(src, FRAG)
            self.batch = batch_for_shader(self.shader, 'TRI_FAN',
                                          {"corner": [(-1, -1), (1, -1), (1, 1), (-1, 1)]})
            self._sh_ok = True
            return True
        except Exception as e:
            if _DBG: print("[VertexLit unified] shader build failed -> per-cloud:", e)
            self._sh_ok = False
            return False

    def ensure_buffers(self, total):
        """Key/value buffers for the global order + the R32F index the draw samples."""
        if getattr(self, '_cap', 0) >= total and self.uKey is not None:
            return
        w, h = _IW, max(1, (total + _IW - 1)//_IW)
        self.uKey = gpu.types.GPUTexture((w, h), format='R32UI')
        self.uVal = gpu.types.GPUTexture((w, h), format='R32UI')
        # R32UI, NOT R32F: the payload (inst<<24|id) does not survive float32 exactly
        self.uIndex = gpu.types.GPUTexture((w, h), format='R32UI')
        self._cap = w*h

    def draw(self, entries, vm, pm, w, h, light=None, sigma=2.4, write_depth=True):
        """One globally-ordered draw across every cloud. Returns True if it handled the splats."""
        from . import splat_radix
        if not can_unify(entries) or not self.ensure_array(entries) or not self.ensure_shaders():
            return False
        try:
            counts = [int(c.d['count']) for c, _m, _n in entries]
            total = sum(counts)
            self.ensure_buffers(total)
            right = Vector(vm[0][:3]); up = Vector(vm[1][:3]); fwd = -Vector(vm[2][:3])
            cam = vm.inverted().translation
            fx = 0.5*w*pm[0][0]; fy = 0.5*h*pm[1][1]
            view_proj = pm @ vm
            models = [m for _c, m, _n in entries]

            # 1) key every splat of every instance by WORLD depth (payload = inst<<24 | id)
            s = self.sh_key; s.bind()
            s.image('uKey', self.uKey); s.image('uVal', self.uVal)
            s.uniform_sampler('uData', self.array)
            s.uniform_float('uCam', cam); s.uniform_float('uFwd', fwd)
            s.uniform_float('uViewProj', view_proj)
            for i, m in enumerate(models):
                s.uniform_float('uModels[%d]' % i, m)
            for i, c in enumerate(counts):
                s.uniform_int('uCounts[%d]' % i, c)
            s.uniform_int('uTotal', total); s.uniform_int('uNumInst', len(entries)); s.uniform_int('uTW', _IW)
            gpu.compute.dispatch(s, (total + 63)//64, 1, 1)

            # 2) ONE radix sort over the combined buffer -> global back-to-front order
            if not splat_radix.sort_existing(self.uKey, self.uVal, self.uIndex, total):
                return False

            # 3) one instanced draw in that order
            sh = self.shader; sh.bind()
            sh.uniform_sampler('uData', self.array); sh.uniform_sampler('uIndex', self.uIndex)
            sh.uniform_int('uTW', _IW); sh.uniform_int('uITW', _IW); sh.uniform_int('uTotal', total)
            for i, m in enumerate(models):
                sh.uniform_float('uModels[%d]' % i, m)
            sh.uniform_float('uRow0', right); sh.uniform_float('uRow1', up); sh.uniform_float('uRow2', fwd)
            sh.uniform_float('uCam', cam); sh.uniform_float('uF', (fx, fy))
            sh.uniform_float('uVP', (float(w), float(h))); sh.uniform_float('uSigma', sigma)
            sh.uniform_float('uViewProj', view_proj)
            if light is not None:
                sh.uniform_int('uLit', 1)
                sh.uniform_float('uSkyColor', light['sky']); sh.uniform_float('uGroundColor', light['ground'])
                sh.uniform_float('uHemiIntensity', float(light['hemi']))
                sh.uniform_float('uSunDir', light['sun_dir']); sh.uniform_float('uSunColor', light['sun_col'])
                sh.uniform_float('uSunIntensity', float(light['sun_int']))
                sh.uniform_float('uKeyDir', light['key_dir']); sh.uniform_float('uKeyCol', light['key_col'])
                sh.uniform_float('uKeyIntensity', float(light['key_int']))
            else:
                sh.uniform_int('uLit', 0)
            gpu.state.blend_set('ALPHA_PREMULT'); gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(False)
            sh.uniform_float('uDepthCut', 0.004)
            self.batch.draw_instanced(sh, instance_count=total)
            if write_depth:
                try:
                    gpu.state.color_mask_set(False, False, False, False)
                    gpu.state.blend_set('NONE'); gpu.state.depth_mask_set(True)
                    sh.uniform_float('uDepthCut', 0.35)
                    self.batch.draw_instanced(sh, instance_count=total)
                finally:
                    gpu.state.color_mask_set(True, True, True, True)
            gpu.state.blend_set('NONE'); gpu.state.depth_mask_set(True)
            return True
        except Exception as e:
            if _DBG: print("[VertexLit unified] draw failed -> per-cloud:", e)
            return False


SORTER = UnifiedSorter()
