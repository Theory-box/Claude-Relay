# vertex_lit_renderer/splat_gpusort.py
"""
GPU depth-sort for the billboard splat path — moves the per-frame sort off the CPU while keeping the
GPU's fast hardware alpha blending (the actual top-tier viewing architecture). Two compute passes:

  keygen : per splat, depth = dot(centre-cam, fwd); key = -depth (far first), value = splat id.
  sort   : bitonic sort (validated headless) -> value image = splat ids in draw order.

The value image is an R32F texture with the SAME width the billboard's uIndex sampler expects, so it is
a drop-in for the CPU-built index texture. No atomics, no readback. Opt-in + falls back to the CPU sort.
"""
import numpy as np
import gpu
from mathutils import Vector

_IW = 4096      # index/key/value width (matches SplatCloud.itw)
_DBG = True

_KEYGEN = """
ivec2 atD(int i){ return ivec2(i % uTW, i / uTW); }
ivec2 atK(int i){ return ivec2(i % IW, i / IW); }
void main(){
  int id=int(gl_GlobalInvocationID.x); if(id>=uMax) return;
  if(id>=uN){ imageStore(uKey,atK(id),vec4(1e30)); imageStore(uVal,atK(id),vec4(0.0)); return; }
  vec3 c=texelFetch(uData, atD(id*4), 0).xyz;
  float depth=dot(c-uCam, uFwd);
  imageStore(uKey, atK(id), vec4(-depth));   // ascending sort on -depth => far first
  imageStore(uVal, atK(id), vec4(float(id)));
}"""

_SORT = """
ivec2 atK(int i){ return ivec2(i % IW, i / IW); }
void main(){
  int i=int(gl_GlobalInvocationID.x); if(i>=uN) return; int ixj=i^uJ;
  if(ixj>i){
    bool asc=((i&uK)==0);
    float ki=imageLoad(uKey,atK(i)).r, kj=imageLoad(uKey,atK(ixj)).r;
    if((ki>kj)==asc){
      imageStore(uKey,atK(i),vec4(kj)); imageStore(uKey,atK(ixj),vec4(ki));
      float vi=imageLoad(uVal,atK(i)).r, vj=imageLoad(uVal,atK(ixj)).r;
      imageStore(uVal,atK(i),vec4(vj)); imageStore(uVal,atK(ixj),vec4(vi));
    }
  }
}"""


class GPUSorter:
    def __init__(self):
        self.ok = False; self._tried = False; self.MAXN = 0
        self.keygen = None; self.sort = None; self.uKey = None; self.uVal = None

    def build(self, N):
        if self._tried:
            return self.ok
        self._tried = True
        try:
            mp = 1
            while mp < N: mp <<= 1
            self.MAXN = mp; self.N = N
            h = (mp + _IW - 1)//_IW
            self.uKey = gpu.types.GPUTexture((_IW, h), format='R32F')
            self.uVal = gpu.types.GPUTexture((_IW, h), format='R32F')
            # keygen shader
            ik = gpu.types.GPUShaderCreateInfo(); ik.local_group_size(64,1,1); ik.define("IW", str(_IW))
            ik.push_constant('VEC3','uCam'); ik.push_constant('VEC3','uFwd')
            for nm in ('uN','uMax','uTW'): ik.push_constant('INT', nm)
            ik.sampler(0,'FLOAT_2D','uData')
            ik.image(0,'R32F','FLOAT_2D','uKey',qualifiers={'WRITE'})
            ik.image(1,'R32F','FLOAT_2D','uVal',qualifiers={'WRITE'})
            ik.compute_source(_KEYGEN)
            self.keygen = gpu.shader.create_from_info(ik)
            # sort shader
            iso = gpu.types.GPUShaderCreateInfo(); iso.local_group_size(256,1,1); iso.define("IW", str(_IW))
            for nm in ('uJ','uK','uN'): iso.push_constant('INT', nm)
            iso.image(0,'R32F','FLOAT_2D','uKey',qualifiers={'READ','WRITE'})
            iso.image(1,'R32F','FLOAT_2D','uVal',qualifiers={'READ','WRITE'})
            iso.compute_source(_SORT)
            self.sort = gpu.shader.create_from_info(iso)
            self.ok = True
            if _DBG: print("[VertexLit gpusort] built: N=%d MAXN=%d" % (N, mp))
        except Exception as e:
            if _DBG: print("[VertexLit gpusort] build failed -> CPU sort:", e); self.ok = False
        return self.ok

    def run(self, datatex, data_w, cam, fwd, N):
        """Return an R32F index texture (width _IW) of splat ids sorted far->near, or None on failure."""
        if not self.build(N):
            return None
        try:
            s=self.keygen; s.bind()
            s.image('uKey',self.uKey); s.image('uVal',self.uVal); s.uniform_sampler('uData',datatex)
            s.uniform_float('uCam',Vector(cam)); s.uniform_float('uFwd',Vector(fwd))
            s.uniform_int('uN',N); s.uniform_int('uMax',self.MAXN); s.uniform_int('uTW',data_w)
            gpu.compute.dispatch(s,(self.MAXN+63)//64,1,1)
            s=self.sort; s.bind(); s.image('uKey',self.uKey); s.image('uVal',self.uVal); s.uniform_int('uN',self.MAXN)
            g=(self.MAXN+255)//256; k=2
            while k<=self.MAXN:
                j=k>>1
                while j>=1:
                    s.uniform_int('uK',k); s.uniform_int('uJ',j); gpu.compute.dispatch(s,g,1,1); j>>=1
                k<<=1
            return self.uVal
        except Exception as e:
            if _DBG: print("[VertexLit gpusort] run failed -> CPU sort:", e); self.ok=False
            return None
