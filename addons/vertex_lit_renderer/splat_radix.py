# vertex_lit_renderer/splat_radix.py
"""
GPU radix sort for the splat depth order — replaces the bitonic sort's O(N log^2 N) + power-of-two
padding with O(N) passes and no padding.

Measured motivation (tree scene, RTX 4090): the bitonic GPU sort cost ~0.7/1.3/2.5 ms per cloud per
frame at 250k/500k/1M splats, i.e. ~15 ms of a 17.8 ms frame with six 1M trees. At 1.1M it pads to
2.1M, so ~48% of the work sorts padding. The algorithm below was validated in numpy first
(apps/splat-viewer/radix_prototype.py): correct, stable, 13-27x fewer element-ops, 24 dispatches
instead of 171-276.

Design: LSD radix, 4-bit digits (16 buckets), 8 passes over a 32-bit key.
  pass p:  histogram (per workgroup) -> scan (digit-major exclusive prefix sum) -> stable scatter
Storage is image-backed (Blender has no SSBOs): linear index -> ivec2(i % IW, i / IW).
Ping-pongs between two key/value buffers. Falls back to the caller's bitonic path on any failure.
"""
import numpy as np
import gpu
from mathutils import Vector

_IW = 4096          # buffer image width
_BITS = 4
_RADIX = 1 << _BITS
_PASSES = 32 // _BITS
_GROUP = 256
_DBG = True

_AT = "ivec2 at(int i){ return ivec2(i %% IW, i / IW); }\n".replace('%%', '%')

# ── keygen: depth -> monotonic uint32 key (+ cull to a sentinel), value = splat id ──
_KEYGEN = _AT + """
ivec2 atD(int i){ return ivec2(i % uTW, i / uTW); }
uint f2key(float f){                       // IEEE monotonic map: ascending uint == ascending float
  uint b = floatBitsToUint(f);
  return ((b >> 31) != 0u) ? ~b : (b | 0x80000000u);
}
void main(){
  int id=int(gl_GlobalInvocationID.x); if(id>=uN) return;
  vec4 t0=texelFetch(uData,atD(id*4),0), t1=texelFetch(uData,atD(id*4+1),0), t2=texelFetch(uData,atD(id*4+2),0);
  vec3 c=t0.xyz; float depth=dot(c-uCam,uFwd);
  bool vis = depth > 0.0;
  if(vis){ vec4 cl=uViewProj*vec4(c,1.0); vis = cl.w>1e-4;
           if(vis){ vec2 n=cl.xy/cl.w; vis = abs(n.x)<1.3 && abs(n.y)<1.3; } }
  if(vis && uBackface==1){
    vec3 s=vec3(t0.w,t1.x,t1.y); vec4 q=vec4(t1.z,t1.w,t2.x,t2.y);
    float w=q.x,x=q.y,y=q.z,z=q.w;
    vec3 a0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
    vec3 a1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
    vec3 a2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
    vec3 nrm=(s.x<=s.y&&s.x<=s.z)?a0:((s.y<=s.z)?a1:a2);
    vis = dot(normalize(nrm), normalize(uCam-c)) > -0.2;
  }
  // far -> near == ascending key on -depth; culled splats get the max key so they land at the end
  uint k = vis ? f2key(-depth) : 0xFFFFFFFFu;
  imageStore(uKeyA, at(id), uvec4(k));
  imageStore(uValA, at(id), uvec4(uint(vis ? id : uN)));   // sentinel id == uN -> shader skips it
}"""

# ── stage 1: per-workgroup histogram of the current 4-bit digit ──
_HIST = _AT + """
shared uint lh[RADIX];
void main(){
  int g=int(gl_WorkGroupID.x); int lid=int(gl_LocalInvocationID.x);
  if(lid<RADIX) lh[lid]=0u;
  barrier();
  int i=g*GROUP+lid;
  if(i<uN){
    uint k = (uSrc==0) ? imageLoad(uKeyA,at(i)).r : imageLoad(uKeyB,at(i)).r;
    atomicAdd(lh[(k>>uShift)&(RADIXu-1u)], 1u);
  }
  barrier();
  // counts laid out DIGIT-MAJOR: counts[digit*uGroups + group] -> a plain scan gives stable offsets
  if(lid<RADIX) imageStore(uCounts, at(lid*uGroups+g), uvec4(lh[lid]));
}"""

# ── stage 2: exclusive prefix sum over the (small) digit-major counts buffer ──
# single workgroup, serial-in-shared scan: RADIX*uGroups is small (16 * N/256)
_SCAN = _AT + """
void main(){
  if(gl_GlobalInvocationID.x!=0u) return;       // one thread: the counts buffer is small
  uint total=0u; int n=RADIX*uGroups;
  for(int i=0;i<n;i++){
    uint c=imageLoad(uCounts,at(i)).r;
    imageStore(uOffsets,at(i),uvec4(total));
    total+=c;
  }
}"""

# ── stage 3: stable scatter to the destination buffer ──
_SCATTER = _AT + """
void main(){
  int g=int(gl_WorkGroupID.x); int lid=int(gl_LocalInvocationID.x);
  int base=g*GROUP;
  if(lid!=0) return;                            // serial within the group preserves stability
  uint cur[RADIX];
  for(int d=0; d<RADIX; d++) cur[d]=imageLoad(uOffsets,at(d*uGroups+g)).r;
  for(int j=0; j<GROUP; j++){
    int i=base+j; if(i>=uN) break;
    uint k = (uSrc==0) ? imageLoad(uKeyA,at(i)).r : imageLoad(uKeyB,at(i)).r;
    uint v = (uSrc==0) ? imageLoad(uValA,at(i)).r : imageLoad(uValB,at(i)).r;
    uint d = (k>>uShift)&(RADIXu-1u);
    int dst=int(cur[d]); cur[d]+=1u;
    if(uSrc==0){ imageStore(uKeyB,at(dst),uvec4(k)); imageStore(uValB,at(dst),uvec4(v)); }
    else       { imageStore(uKeyA,at(dst),uvec4(k)); imageStore(uValA,at(dst),uvec4(v)); }
  }
}"""

# ── final: uint ids -> the R32F index texture the billboard shaders already sample ──
_TOF = _AT + """
void main(){
  int i=int(gl_GlobalInvocationID.x); if(i>=uCap) return;
  uint v = (uSrc==0) ? imageLoad(uValA,at(i)).r : imageLoad(uValB,at(i)).r;
  imageStore(uOut, at(i), vec4(float(i<uN ? v : uint(uN))));
}"""


def _img(w, h, fmt):
    return gpu.types.GPUTexture((w, h), format=fmt)

def _dims(n):
    return _IW, max(1, (n + _IW - 1)//_IW)


class RadixSorter:
    """Drop-in replacement for GPUSorter.run(): returns an R32F index texture of splat ids far->near."""

    def __init__(self):
        self.ok = False; self._tried = False

    def build(self, N):
        if self._tried:
            return self.ok
        self._tried = True
        try:
            self.N = N
            self.groups = (N + _GROUP - 1)//_GROUP
            bw, bh = _dims(N)
            self.uKeyA = _img(bw, bh, 'R32UI'); self.uKeyB = _img(bw, bh, 'R32UI')
            self.uValA = _img(bw, bh, 'R32UI'); self.uValB = _img(bw, bh, 'R32UI')
            cw, ch = _dims(_RADIX * self.groups)
            self.uCounts = _img(cw, ch, 'R32UI'); self.uOffsets = _img(cw, ch, 'R32UI')
            ow, oh = _dims(N)
            self.uOut = _img(ow, oh, 'R32F')
            self.cap = ow * oh

            def mk(src, local, names_i, images, extra_defs=()):
                info = gpu.types.GPUShaderCreateInfo()
                info.local_group_size(local, 1, 1)
                info.define("IW", str(_IW)); info.define("RADIX", str(_RADIX))
                info.define("RADIXu", str(_RADIX) + "u"); info.define("GROUP", str(_GROUP))
                for d, val in extra_defs: info.define(d, val)
                for nm in names_i: info.push_constant('INT', nm)
                for slot, (fmt, ityp, nm, q) in enumerate(images):
                    info.image(slot, fmt, ityp, nm, qualifiers=q)
                info.compute_source(src)
                return gpu.shader.create_from_info(info)

            self.sh_key = mk(_KEYGEN, 64, ('uN','uTW','uBackface'),
                             [('R32UI','UINT_2D','uKeyA',{'WRITE'}), ('R32UI','UINT_2D','uValA',{'WRITE'})])
            # keygen also needs the camera + data sampler -> rebuild with those
            ik = gpu.types.GPUShaderCreateInfo(); ik.local_group_size(64,1,1)
            ik.define("IW", str(_IW))
            ik.push_constant('VEC3','uCam'); ik.push_constant('VEC3','uFwd'); ik.push_constant('MAT4','uViewProj')
            for nm in ('uN','uTW','uBackface'): ik.push_constant('INT', nm)
            ik.sampler(0,'FLOAT_2D','uData')
            ik.image(0,'R32UI','UINT_2D','uKeyA',qualifiers={'WRITE'})
            ik.image(1,'R32UI','UINT_2D','uValA',qualifiers={'WRITE'})
            ik.compute_source(_KEYGEN)
            self.sh_key = gpu.shader.create_from_info(ik)

            self.sh_hist = mk(_HIST, _GROUP, ('uN','uShift','uSrc','uGroups'),
                              [('R32UI','UINT_2D','uKeyA',{'READ'}), ('R32UI','UINT_2D','uKeyB',{'READ'}),
                               ('R32UI','UINT_2D','uCounts',{'WRITE'})])
            self.sh_scan = mk(_SCAN, 1, ('uGroups',),
                              [('R32UI','UINT_2D','uCounts',{'READ'}), ('R32UI','UINT_2D','uOffsets',{'WRITE'})])
            self.sh_scat = mk(_SCATTER, _GROUP, ('uN','uShift','uSrc','uGroups'),
                              [('R32UI','UINT_2D','uKeyA',{'READ','WRITE'}), ('R32UI','UINT_2D','uKeyB',{'READ','WRITE'}),
                               ('R32UI','UINT_2D','uValA',{'READ','WRITE'}), ('R32UI','UINT_2D','uValB',{'READ','WRITE'}),
                               ('R32UI','UINT_2D','uOffsets',{'READ'})])
            self.sh_tof = mk(_TOF, 64, ('uN','uSrc','uCap'),
                             [('R32UI','UINT_2D','uValA',{'READ'}), ('R32UI','UINT_2D','uValB',{'READ'}),
                              ('R32F','FLOAT_2D','uOut',{'WRITE'})])
            self.ok = True
            if _DBG: print("[VertexLit radix] built: N=%d groups=%d passes=%d" % (N, self.groups, _PASSES))
        except Exception as e:
            if _DBG: print("[VertexLit radix] build failed -> bitonic:", e)
            self.ok = False
        return self.ok

    def run(self, datatex, data_w, cam, fwd, N, view_proj=None, backface=False):
        if not self.build(N):
            return None
        try:
            s = self.sh_key; s.bind()
            s.image('uKeyA', self.uKeyA); s.image('uValA', self.uValA)
            s.uniform_sampler('uData', datatex)
            s.uniform_float('uCam', Vector(cam)); s.uniform_float('uFwd', Vector(fwd))
            if view_proj is not None: s.uniform_float('uViewProj', view_proj)
            s.uniform_int('uN', N); s.uniform_int('uTW', data_w)
            s.uniform_int('uBackface', 1 if backface else 0)
            gpu.compute.dispatch(s, (N + 63)//64, 1, 1)

            src = 0
            for p in range(_PASSES):
                shift = p * _BITS
                s = self.sh_hist; s.bind()
                s.image('uKeyA', self.uKeyA); s.image('uKeyB', self.uKeyB); s.image('uCounts', self.uCounts)
                s.uniform_int('uN', N); s.uniform_int('uShift', shift)
                s.uniform_int('uSrc', src); s.uniform_int('uGroups', self.groups)
                gpu.compute.dispatch(s, self.groups, 1, 1)

                s = self.sh_scan; s.bind()
                s.image('uCounts', self.uCounts); s.image('uOffsets', self.uOffsets)
                s.uniform_int('uGroups', self.groups)
                gpu.compute.dispatch(s, 1, 1, 1)

                s = self.sh_scat; s.bind()
                s.image('uKeyA', self.uKeyA); s.image('uKeyB', self.uKeyB)
                s.image('uValA', self.uValA); s.image('uValB', self.uValB); s.image('uOffsets', self.uOffsets)
                s.uniform_int('uN', N); s.uniform_int('uShift', shift)
                s.uniform_int('uSrc', src); s.uniform_int('uGroups', self.groups)
                gpu.compute.dispatch(s, self.groups, 1, 1)
                src = 1 - src

            s = self.sh_tof; s.bind()
            s.image('uValA', self.uValA); s.image('uValB', self.uValB); s.image('uOut', self.uOut)
            s.uniform_int('uN', N); s.uniform_int('uSrc', src); s.uniform_int('uCap', self.cap)
            gpu.compute.dispatch(s, (self.cap + 63)//64, 1, 1)
            return self.uOut
        except Exception as e:
            if _DBG: print("[VertexLit radix] run failed -> bitonic:", e)
            self.ok = False
            return None
