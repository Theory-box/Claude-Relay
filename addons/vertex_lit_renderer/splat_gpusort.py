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
  if(id>=uN){ imageStore(uKey,atK(id),vec4(1e30)); imageStore(uVal,atK(id),vec4(float(uN))); return; }
  vec4 t0=texelFetch(uData,atD(id*4),0), t1=texelFetch(uData,atD(id*4+1),0), t2=texelFetch(uData,atD(id*4+2),0);
  vec3 c=t0.xyz; float depth=dot(c-uCam, uFwd);
  bool vis = depth > 0.0;                                   // in front
  if(vis){ vec4 cl=uViewProj*vec4(c,1.0); vis = cl.w>1e-4;  // frustum
           if(vis){ vec2 n=cl.xy/cl.w; vis = abs(n.x)<1.3 && abs(n.y)<1.3; } }
  if(vis && uBackface==1){                                  // backface (keep silhouette)
    vec3 s=vec3(t0.w,t1.x,t1.y); vec4 q=vec4(t1.z,t1.w,t2.x,t2.y);
    float w=q.x,x=q.y,y=q.z,z=q.w;
    vec3 a0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
    vec3 a1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
    vec3 a2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
    vec3 nrm=(s.x<=s.y&&s.x<=s.z)?a0:((s.y<=s.z)?a1:a2);
    vis = dot(normalize(nrm), normalize(uCam-c)) > -0.2;
  }
  if(!vis){ imageStore(uKey,atK(id),vec4(1e30)); imageStore(uVal,atK(id),vec4(float(uN))); return; }
  imageStore(uKey, atK(id), vec4(-depth));                  // ascending on -depth => far first
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
            ik.push_constant('VEC3','uCam'); ik.push_constant('VEC3','uFwd'); ik.push_constant('MAT4','uViewProj')
            for nm in ('uN','uMax','uTW','uBackface'): ik.push_constant('INT', nm)
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

    def run(self, datatex, data_w, cam, fwd, N, view_proj=None, backface=False):
        """Return an R32F index texture (width _IW) of splat ids sorted far->near, culled ids -> sentinel N."""
        if not self.build(N):
            return None
        try:
            s=self.keygen; s.bind()
            s.image('uKey',self.uKey); s.image('uVal',self.uVal); s.uniform_sampler('uData',datatex)
            s.uniform_float('uCam',Vector(cam)); s.uniform_float('uFwd',Vector(fwd))
            if view_proj is not None:
                s.uniform_float('uViewProj', view_proj)
            s.uniform_int('uN',N); s.uniform_int('uMax',self.MAXN); s.uniform_int('uTW',data_w)
            s.uniform_int('uBackface', 1 if backface else 0)
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
