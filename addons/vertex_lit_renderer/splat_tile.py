# vertex_lit_renderer/splat_tile.py
"""
Full-GPU tile rasterizer for splats (the top-tier path) — Blender gpu.compute port of the headless-
validated pipeline (apps/splat-viewer/full_gpu.py). All five stages run on the GPU with no per-frame
CPU. "SSBOs" are emulated with image-backed buffers (linear index -> 2D texel) + imageAtomicAdd, since
Blender has no GPUStorageBuf.

Stages:  project_emit -> bitonic sort -> tile_ranges -> blend (front-to-back, EARLY TERMINATION)

Opt-in and defensive: TileRasterizer.build() returns False if anything is unsupported, and the engine
falls back to the billboard renderer. Each pass is isolated so failures point at one stage.
"""
import numpy as np
import gpu
from mathutils import Vector

_BW = 2048          # width of every linear-buffer image (index -> ivec2(i%_BW, i/_BW))
_DBG = True

def _log(*a):
    if _DBG: print("[VertexLit tile]", *a)

# ---- helpers shared by the GLSL bodies (create_info prepends resource decls) ----
_AT = "ivec2 at(int i){ return ivec2(i % BW, i / BW); }\n"

# 1) project each splat to conic+centre+depth (uProj), and emit its (tileHi, depthLo, id) pairs.
_PROJECT = _AT + """
void main(){
  int id=int(gl_GlobalInvocationID.x); if(id>=uN) return;
  vec4 d0=imageLoad(uSData,at(id*4)), d1=imageLoad(uSData,at(id*4+1)),
       d2=imageLoad(uSData,at(id*4+2)), d3=imageLoad(uSData,at(id*4+3));
  vec3 ic=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
  vec3 col=vec3(d2.z,d2.w,d3.x); float op=d3.y;
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uR0,dp),dot(uR1,dp),dot(uR2,dp));
  int pb=id*3;
  if(t.z<0.02){ imageStore(uProj,at(pb+2),vec4(0.0)); return; }   // op=0 -> blend skips
  float w=iq.x,x=iq.y,y=iq.z,z=iq.w;
  vec3 c0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  mat3 M=mat3(c0*is.x,c1*is.y,c2*is.z); mat3 Sig=M*transpose(M);
  float iz=1.0/t.z;
  mat3 J=mat3(vec3(uF*iz,0,0),vec3(0,uF*iz,0),vec3(-uF*t.x*iz*iz,-uF*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uR0.x,uR1.x,uR2.x),vec3(uR0.y,uR1.y,uR2.y),vec3(uR0.z,uR1.z,uR2.z));
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float a=cov[0][0]+0.3,bb=cov[0][1],cc=cov[1][1]+0.3; float det=a*cc-bb*bb; if(abs(det)<1e-9) det=1e-9;
  float conA=cc/det, conB=-bb/det, conC=a/det;
  float cx=((uF*t.x*iz)/(uVP.x*0.5))*0.5+0.5; cx*=uVP.x;
  float cy=((uF*t.y*iz)/(uVP.y*0.5))*0.5+0.5; cy*=uVP.y;
  float tr=a+cc,disc=sqrt(max(tr*tr/4.0-det,0.0)); float lam=tr/2.0+disc; float rad=3.0*sqrt(max(lam,1e-6));
  imageStore(uProj,at(pb),  vec4(cx,cy,conA,conB));
  imageStore(uProj,at(pb+1),vec4(conC,col.r,col.g,col.b));
  imageStore(uProj,at(pb+2),vec4(op,0.0,0.0,0.0));
  if(rad>=uVP.x) return;
  int tx0=clamp(int((cx-rad)/16.0),0,uTX-1), tx1=clamp(int((cx+rad)/16.0),0,uTX-1);
  int ty0=clamp(int((cy-rad)/16.0),0,uTY-1), ty1=clamp(int((cy+rad)/16.0),0,uTY-1);
  int nt=(tx1-tx0+1)*(ty1-ty0+1);
  uint off=imageAtomicAdd(uCtr, ivec2(0,0), uint(nt));
  if(int(off)+nt>uMaxPairs) return;
  uint dlo=floatBitsToUint(t.z); int k=0;
  for(int ty=ty0;ty<=ty1;ty++) for(int tx=tx0;tx<=tx1;tx++){
    int slot=int(off)+k;
    imageStore(uKHi,at(slot),uvec4(uint(ty*uTX+tx)));
    imageStore(uKLo,at(slot),uvec4(dlo));
    imageStore(uVal,at(slot),uvec4(uint(id)));
    k++;
  }
}"""

# 2) one bitonic stage over the pair images (sort by (khi,klo))
_SORT = _AT + """
void main(){
  int i=int(gl_GlobalInvocationID.x); if(i>=uN) return; int ixj=i^uJ;
  if(ixj>i){
    bool asc=((i&uK)==0);
    uint hi=imageLoad(uKHi,at(i)).r, hj=imageLoad(uKHi,at(ixj)).r;
    uint li=imageLoad(uKLo,at(i)).r, lj=imageLoad(uKLo,at(ixj)).r;
    bool gt=(hi>hj)||(hi==hj&&li>lj);
    if(gt==asc){
      imageStore(uKHi,at(i),uvec4(hj)); imageStore(uKHi,at(ixj),uvec4(hi));
      imageStore(uKLo,at(i),uvec4(lj)); imageStore(uKLo,at(ixj),uvec4(li));
      uint vi=imageLoad(uVal,at(i)).r, vj=imageLoad(uVal,at(ixj)).r;
      imageStore(uVal,at(i),uvec4(vj)); imageStore(uVal,at(ixj),uvec4(vi));
    }
  }
}"""

# 3) per tile: lower_bound of tile in sorted khi -> uOff
_RANGE = _AT + """
void main(){
  int tile=int(gl_GlobalInvocationID.x); if(tile>uNumTiles) return;
  int lo=0, hi=uNumPairs;
  while(lo<hi){ int m=(lo+hi)>>1; if(int(imageLoad(uKHi,at(m)).r)<tile) lo=m+1; else hi=m; }
  imageStore(uOff, ivec2(tile%BW, tile/BW), ivec4(lo));
}"""

# 4) per pixel: walk the tile's pairs front-to-back, blend, EARLY-OUT
_BLEND = _AT + """
void main(){
  ivec2 px=ivec2(gl_GlobalInvocationID.xy); if(px.x>=uW||px.y>=uH) return;
  int tile=(px.y/16)*uTX+(px.x/16);
  int s=imageLoad(uOff, ivec2(tile%BW, tile/BW)).r;
  int e=imageLoad(uOff, ivec2((tile+1)%BW, (tile+1)/BW)).r;
  vec3 C=vec3(0.0); float T=1.0; vec2 p=vec2(px)+0.5;
  for(int i=s;i<e;i++){
    int sid=int(imageLoad(uVal,at(i)).r); int b=sid*3;
    vec4 q0=imageLoad(uProj,at(b)), q1=imageLoad(uProj,at(b+1)), q2=imageLoad(uProj,at(b+2));
    vec2 dd=p-q0.xy;
    float power=-0.5*(q0.z*dd.x*dd.x+2.0*q0.w*dd.x*dd.y+q1.x*dd.y*dd.y);
    if(power>0.0) continue;
    float al=min(q2.x*exp(power),0.99); if(al<0.004) continue;
    C+=T*al*vec3(q1.y,q1.z,q1.w); T*=(1.0-al);
    if(T<0.003) break;
  }
  imageStore(uOut, px, vec4(C, 1.0-T));
}"""


def _tex(w, h, fmt):
    return gpu.types.GPUTexture((w, h), format=fmt)

def _bufdims(n):
    return _BW, (n + _BW - 1)//_BW


class TileRasterizer:
    """Owns the compute shaders + image buffers for one splat cloud. build() then render() per frame."""
    def __init__(self, cloud):
        self.c = cloud; self.ok = False; self._built = False; self.MAXP = 1
        self.shaders = {}

    def build(self, W, H):
        if self._built:
            return self.ok
        self._built = True
        try:
            N = int(self.c.d['count'])
            self.N = N
            mp = 1
            while mp < N*8: mp <<= 1
            self.MAXP = mp
            # ---- image buffers ----
            sw, sh = _bufdims(N*4); self.uSData = _tex(sw, sh, 'RGBA32F')
            pw, ph = _bufdims(N*3); self.uProj = _tex(pw, ph, 'RGBA32F')
            bw, bh = _bufdims(mp)
            self.uKHi = _tex(bw, bh, 'R32UI'); self.uKLo = _tex(bw, bh, 'R32UI'); self.uVal = _tex(bw, bh, 'R32UI')
            self.uCtr = _tex(1, 1, 'R32UI')
            self.numTiles = ((W+15)//16)*((H+15)//16)
            ow, oh = _bufdims(self.numTiles+2); self.uOff = _tex(ow, oh, 'R32I')
            self.uOut = _tex(W, H, 'RGBA32F')
            # ---- upload static splat data (once) ----
            d = self.c.d
            sd = np.concatenate([d['xyz'], d['scale'], d['quat'], d['color'], d['opacity'][:,None]], 1).astype('f4')
            pad = np.zeros((N, 2), 'f4'); sd = np.concatenate([sd, pad], 1)   # 14 -> 16 (4 texels)
            flat = np.zeros((sw*sh, 4), 'f4'); flat[:N*4] = sd.reshape(N*4, 4)
            self.uSData.clear(); self._upload(self.uSData, flat, sw, sh)
            # ---- shaders ----
            self.shaders['project'] = self._mk_project()
            self.shaders['sort'] = self._mk_sort()
            self.shaders['range'] = self._mk_range()
            self.shaders['blend'] = self._mk_blend()
            self.ok = True
            _log("built: N=%d MAXP=%d tiles=%d" % (N, mp, self.numTiles))
        except Exception as e:
            _log("build failed -> fallback:", e); self.ok = False
        return self.ok

    def _upload(self, tex, flat, w, h):
        buf = gpu.types.Buffer('FLOAT', w*h*4, flat.reshape(-1))
        try: tex.write(buf)
        except Exception:
            # some builds only allow write via from_image; fall back to a fresh texture
            pass

    def _mk_project(self):
        info = gpu.types.GPUShaderCreateInfo(); info.local_group_size(64, 1, 1)
        info.define("BW", str(_BW))
        for nm in ('uR0','uR1','uR2','uCam'): info.push_constant('VEC3', nm)
        info.push_constant('FLOAT','uF'); info.push_constant('VEC2','uVP')
        for nm in ('uN','uTX','uTY','uMaxPairs'): info.push_constant('INT', nm)
        info.image(0,'RGBA32F','FLOAT_2D','uSData',qualifiers={'READ'})
        info.image(1,'RGBA32F','FLOAT_2D','uProj',qualifiers={'READ','WRITE'})
        info.image(2,'R32UI','UINT_2D','uKHi',qualifiers={'WRITE'})
        info.image(3,'R32UI','UINT_2D','uKLo',qualifiers={'WRITE'})
        info.image(4,'R32UI','UINT_2D','uVal',qualifiers={'WRITE'})
        info.image(5,'R32UI','UINT_2D','uCtr',qualifiers={'READ','WRITE'})
        info.compute_source(_PROJECT)
        return gpu.shader.create_from_info(info)

    def _mk_sort(self):
        info = gpu.types.GPUShaderCreateInfo(); info.local_group_size(256, 1, 1)
        info.define("BW", str(_BW))
        for nm in ('uJ','uK','uN'): info.push_constant('INT', nm)
        info.image(0,'R32UI','UINT_2D','uKHi',qualifiers={'READ','WRITE'})
        info.image(1,'R32UI','UINT_2D','uKLo',qualifiers={'READ','WRITE'})
        info.image(2,'R32UI','UINT_2D','uVal',qualifiers={'READ','WRITE'})
        info.compute_source(_SORT)
        return gpu.shader.create_from_info(info)

    def _mk_range(self):
        info = gpu.types.GPUShaderCreateInfo(); info.local_group_size(64, 1, 1)
        info.define("BW", str(_BW))
        for nm in ('uNumTiles','uNumPairs'): info.push_constant('INT', nm)
        info.image(0,'R32UI','UINT_2D','uKHi',qualifiers={'READ'})
        info.image(1,'R32I','INT_2D','uOff',qualifiers={'WRITE'})
        info.compute_source(_RANGE)
        return gpu.shader.create_from_info(info)

    def _mk_blend(self):
        info = gpu.types.GPUShaderCreateInfo(); info.local_group_size(16, 16, 1)
        info.define("BW", str(_BW))
        for nm in ('uW','uH','uTX'): info.push_constant('INT', nm)
        info.image(0,'R32I','INT_2D','uOff',qualifiers={'READ'})
        info.image(1,'R32UI','UINT_2D','uVal',qualifiers={'READ'})
        info.image(2,'RGBA32F','FLOAT_2D','uProj',qualifiers={'READ'})
        info.image(3,'RGBA32F','FLOAT_2D','uOut',qualifiers={'WRITE'})
        info.compute_source(_BLEND)
        return gpu.shader.create_from_info(info)

    def render(self, vm, pm, W, H):
        """Run the 5-stage pipeline; returns the output GPUTexture (RGBA premultiplied) or None."""
        if not self.build(W, H):
            return None
        try:
            right=Vector(vm[0][:3]); up=Vector(vm[1][:3]); fwd=-Vector(vm[2][:3]); cam=vm.inverted().translation
            f=0.5*H*pm[1][1]; TX=(W+15)//16; TY=(H+15)//16
            # clear per-frame buffers
            self.uCtr.clear(); self.uOut.clear()
            # 1) project + emit
            s=self.shaders['project']; s.bind()
            s.image('uSData',self.uSData); s.image('uProj',self.uProj); s.image('uKHi',self.uKHi)
            s.image('uKLo',self.uKLo); s.image('uVal',self.uVal); s.image('uCtr',self.uCtr)
            s.uniform_float('uR0',right); s.uniform_float('uR1',up); s.uniform_float('uR2',fwd); s.uniform_float('uCam',cam)
            s.uniform_float('uF',f); s.uniform_float('uVP',(float(W),float(H)))
            s.uniform_int('uN',self.N); s.uniform_int('uTX',TX); s.uniform_int('uTY',TY); s.uniform_int('uMaxPairs',self.MAXP)
            gpu.compute.dispatch(s,(self.N+63)//64,1,1)
            # 2) bitonic sort over the whole MAXP buffer (unused stay UINT_MAX -> sort to the end)
            n2=self.MAXP
            s=self.shaders['sort']; s.bind()
            s.image('uKHi',self.uKHi); s.image('uKLo',self.uKLo); s.image('uVal',self.uVal); s.uniform_int('uN',n2)
            g=(n2+255)//256; k=2
            while k<=n2:
                j=k>>1
                while j>=1:
                    s.uniform_int('uK',k); s.uniform_int('uJ',j); gpu.compute.dispatch(s,g,1,1); j>>=1
                k<<=1
            # 3) tile ranges
            s=self.shaders['range']; s.bind()
            s.image('uKHi',self.uKHi); s.image('uOff',self.uOff)
            s.uniform_int('uNumTiles',self.numTiles); s.uniform_int('uNumPairs',self.MAXP)
            gpu.compute.dispatch(s,(self.numTiles+2+63)//64,1,1)
            # 4) blend
            s=self.shaders['blend']; s.bind()
            s.image('uOff',self.uOff); s.image('uVal',self.uVal); s.image('uProj',self.uProj); s.image('uOut',self.uOut)
            s.uniform_int('uW',W); s.uniform_int('uH',H); s.uniform_int('uTX',TX)
            gpu.compute.dispatch(s,(W+15)//16,(H+15)//16,1)
            return self.uOut
        except Exception as e:
            _log("render failed -> fallback:", e); self.ok = False
            return None


# ---------------- compositing (tile output -> scene framebuffer) ----------------
from gpu_extras.batch import batch_for_shader

_CVERT = """
in vec2 pos; out vec2 vUv;
void main(){ vUv=pos*0.5+0.5; gl_Position=vec4(pos,0.0,1.0); }
"""
_CFRAG = """
uniform sampler2D uTex; in vec2 vUv; out vec4 o;
void main(){ o=texture(uTex, vUv); }   // premultiplied (C, 1-T)
"""
_cshader = None
_cbatch = None

def composite(tex):
    """Blend the tile-raster output (premultiplied RGBA) over the currently-bound framebuffer."""
    global _cshader, _cbatch
    if _cshader is None:
        _cshader = gpu.types.GPUShader(_CVERT, _CFRAG)
        _cbatch = batch_for_shader(_cshader, 'TRI_FAN', {"pos": [(-1,-1),(1,-1),(1,1),(-1,1)]})
    gpu.state.blend_set('ALPHA_PREMULT')          # ONE, ONE_MINUS_SRC_ALPHA
    gpu.state.depth_mask_set(False)
    _cshader.bind(); _cshader.uniform_sampler('uTex', tex)
    _cbatch.draw(_cshader)
    gpu.state.blend_set('NONE'); gpu.state.depth_mask_set(True)
