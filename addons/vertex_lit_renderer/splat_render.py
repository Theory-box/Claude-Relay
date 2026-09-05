"""
vertex_lit_renderer/splat_render.py
----------------------------------
Renders 3D gaussian-splat clouds INSIDE the Workbench 2.0 engine, into the same G-buffer as the
meshes so they composite (depth-test against mesh depth) and, later, feed the screen-space effects.

Built from the already-GPU-validated standalone viewer: dependency-free .ply loader, EWA covariance
projection in the vertex shader, 2D-tiled data texture indexed by gl_InstanceID (dodges the 16384
limit), and the optimised throttled uint16 depth sort.

Milestone 1: draw() blends splats over the current framebuffer, depth-tested against whatever is
already there (meshes), depth-write OFF. Milestone 2 will add a core depth write for AO.
"""
import gpu, numpy as np, os
from gpu.types import GPUShader, GPUTexture, Buffer
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

_SH_C0 = 0.28209479177387814
# Module-level registry of SplatCloud instances, populated by the generate operator and drawn
# by the engine each frame. Survives viewport redraws (cleared on file reload / Clear button).
SCENE_CLOUDS = []
_PLY_T = {'char':'i1','uchar':'u1','short':'i2','ushort':'u2','int':'i4','uint':'u4',
          'float':'f4','float32':'f4','double':'f8','int8':'i1','uint8':'u1',
          'int16':'i2','uint16':'u2','int32':'i4','uint32':'u4','float64':'f8'}
_TW = 4096

def _sig(x): return 1.0/(1.0+np.exp(-x))

def load_ply(path):
    """Standard 3DGS .ply -> dict of activated numpy arrays (dependency-free)."""
    with open(path, 'rb') as f:
        assert f.readline().strip() == b'ply'
        fmt=None; n=None; props=[]; inv=False
        while True:
            t=f.readline().split()
            if not t: continue
            if t[0]==b'format': fmt=t[1].decode()
            elif t[0]==b'element': inv=(t[1]==b'vertex'); n=int(t[2]) if inv else n
            elif t[0]==b'property' and inv: props.append((t[2].decode(), t[1].decode()))
            elif t[0]==b'end_header': break
        names=[p[0] for p in props]; types=[p[1] for p in props]; little=(fmt=='binary_little_endian')
        if len(set(types))==1 and _PLY_T[types[0]] in ('f4','f8'):
            fdt=('<' if little else '>')+_PLY_T[types[0]]
            raw=np.frombuffer(f.read(n*len(props)*np.dtype(fdt).itemsize),fdt).reshape(n,len(props)).astype('f4',copy=False)
            d={nm:raw[:,i] for i,nm in enumerate(names)}
        else:
            dt=np.dtype([(nm,('<' if little else '>')+_PLY_T[t2]) for nm,t2 in props])
            a=np.frombuffer(f.read(n*dt.itemsize),dt,n); d={nm:a[nm].astype('f4') for nm in names}
    col=lambda *k: np.stack([d[x] for x in k],1)
    xyz=col('x','y','z').astype('f4')
    if all(k in d for k in ('f_dc_0','f_dc_1','f_dc_2')):
        color=np.clip(0.5+_SH_C0*col('f_dc_0','f_dc_1','f_dc_2'),0,1)
    elif all(k in d for k in ('red','green','blue')):
        color=col('red','green','blue')/255.0
    else:
        color=np.full((len(xyz),3),0.7,'f4')
    opacity=_sig(d['opacity']) if 'opacity' in d else np.ones(len(xyz),'f4')
    scale=np.exp(col('scale_0','scale_1','scale_2')) if all(k in d for k in ('scale_0','scale_1','scale_2')) \
          else np.full((len(xyz),3), float(np.linalg.norm(xyz.max(0)-xyz.min(0)))/max(len(xyz),1)**(1/3)*0.5,'f4')
    if all(k in d for k in ('rot_0','rot_1','rot_2','rot_3')):
        q=col('rot_0','rot_1','rot_2','rot_3'); q=q/(np.linalg.norm(q,axis=1,keepdims=True)+1e-9)
    else:
        q=np.tile(np.array([1,0,0,0],'f4'),(len(xyz),1))
    return dict(count=len(xyz), xyz=xyz, color=np.clip(color,0,1).astype('f4'),
                opacity=opacity.astype('f4'), scale=scale.astype('f4'), quat=q.astype('f4'))

# EWA vertex shader (validated). Milestone-1 fragment: premultiplied colour only.
_VERT = """
uniform sampler2D uData; uniform sampler2D uIndex; uniform int uTW; uniform int uITW;
uniform vec3 uRow0,uRow1,uRow2; uniform vec3 uCam; uniform vec2 uF; uniform vec2 uVP; uniform float uSigma;
uniform mat4 uViewProj;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin % w, lin / w); }
void main(){
  int sid=int(texelFetch(uIndex,at(gl_InstanceID,uITW),0).r+0.5); int base=sid*4;
  vec4 d0=texelFetch(uData,at(base,uTW),0); vec4 d1=texelFetch(uData,at(base+1,uTW),0);
  vec4 d2=texelFetch(uData,at(base+2,uTW),0); vec4 d3=texelFetch(uData,at(base+3,uTW),0);
  vec3 ic=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
  vec3 icol=vec3(d2.z,d2.w,d3.x); float iop=d3.y; vC=corner; vCol=icol; vOp=iop;
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uRow0,dp),dot(uRow1,dp),dot(uRow2,dp));
  vec4 clipC = uViewProj * vec4(ic, 1.0);           // real clip pos (for centre + DEPTH)
  if(t.z<0.02 || clipC.w<=0.0){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }
  float w=iq.x,x=iq.y,y=iq.z,z=iq.w;
  vec3 c0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  mat3 M=mat3(c0*is.x,c1*is.y,c2*is.z); mat3 Sig=M*transpose(M);
  float iz=1.0/t.z;
  mat3 J=mat3(vec3(uF.x*iz,0,0),vec3(0,uF.y*iz,0),vec3(-uF.x*t.x*iz*iz,-uF.y*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uRow0.x,uRow1.x,uRow2.x),vec3(uRow0.y,uRow1.y,uRow2.y),vec3(uRow0.z,uRow1.z,uRow2.z));
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float a=cov[0][0]+0.3,b=cov[0][1],c=cov[1][1]+0.3;
  float tr=a+c,det=a*c-b*b,mid=0.5*tr,disc=sqrt(max(mid*mid-det,0.0));
  float l1=mid+disc,l2=max(mid-disc,1e-9); float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
  vec2 e1=vec2(b,l1-a); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
  vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
  vec2 off = corner.x*e1*r1*p2n + corner.y*e2*r2*p2n;    // NDC billboard offset
  // centre + depth from the real projection; billboard offset applied in NDC (x by w)
  gl_Position = vec4(clipC.xy + off*clipC.w, clipC.z, clipC.w);
}"""
_FRAG = """
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.003) discard; o=vec4(vCol*al,al); }"""


def _mkbuf(arr):
    n=len(arr)
    try:
        buf=Buffer('FLOAT', n); np.frombuffer(buf, dtype=np.float32)[:]=arr; return buf
    except Exception: pass
    try: return Buffer('FLOAT', n, arr)
    except Exception: return Buffer('FLOAT', n, arr.tolist())


class SplatCloud:
    """One splat cloud: owns its GPU data texture + shader, sorts + draws into the current FBO."""
    def __init__(self, data, sigma=2.2):
        self.d = data; self.sigma = float(sigma)
        self._gpu = False; self._idxtex = None; self._last = None

    def _pack(self):
        d=self.d; N=d['count']; xyz=d['xyz']; sc=d['scale']; q=d['quat']; cl=d['color']; op=d['opacity']
        tex=np.zeros((N*4,4),'f4')
        tex[0::4]=np.column_stack([xyz,sc[:,0]]); tex[1::4]=np.column_stack([sc[:,1],sc[:,2],q[:,0],q[:,1]])
        tex[2::4]=np.column_stack([q[:,2],q[:,3],cl[:,0],cl[:,1]]); tex[3::4]=np.column_stack([cl[:,2],op,np.zeros(N,'f4'),np.zeros(N,'f4')])
        TH=(N*4+_TW-1)//_TW; full=np.zeros((TH*_TW,4),'f4'); full[:N*4]=tex
        return full.reshape(TH,_TW,4), TH

    def ensure_gpu(self):
        if self._gpu: return
        texdata, TH = self._pack()
        self.datatex = GPUTexture((_TW, TH), format='RGBA32F', data=_mkbuf(texdata.ravel()))
        self.shader = GPUShader(_VERT, _FRAG)
        self.batch = batch_for_shader(self.shader, 'TRI_FAN', {"corner": [(-1,-1),(1,-1),(1,1),(-1,1)]})
        self.itw = 4096
        ext = float(np.linalg.norm(self.d['xyz'].max(0)-self.d['xyz'].min(0)))
        self.move_eps = ext*0.02
        self._gpu = True

    def _sorted_index(self, cam_np, fwd_np):
        need = self._idxtex is None
        if not need:
            need = (float(np.dot(fwd_np, self._last[1])) < 0.9994
                    or float(np.linalg.norm(cam_np - self._last[0])) > self.move_eps)
        if need:
            depth=(self.d['xyz']-cam_np)@fwd_np; lo=float(depth.min()); hi=float(depth.max())
            q=65535-((depth-lo)*(65535.0/(hi-lo+1e-9))).astype(np.uint16)
            order=np.argsort(q,kind='stable').astype(np.float32)
            ith=(len(order)+self.itw-1)//self.itw
            ibuf=np.zeros(self.itw*ith,'f4'); ibuf[:len(order)]=order
            self._idxtex=GPUTexture((self.itw,ith),format='R32F',data=_mkbuf(ibuf))
            self._last=(cam_np, fwd_np)
        return self._idxtex

    def draw(self, view_matrix, window_matrix, w, h):
        """Draw into the currently-bound framebuffer. Depth-tested against what's there, blended over."""
        self.ensure_gpu()
        vm=view_matrix; pm=window_matrix
        right=Vector(vm[0][:3]); up=Vector(vm[1][:3]); fwd=-Vector(vm[2][:3])
        cam=vm.inverted().translation
        fx=0.5*w*pm[0][0]; fy=0.5*h*pm[1][1]
        idxtex=self._sorted_index(np.array(cam,'f4'), np.array(fwd,'f4'))
        view_proj = pm @ vm
        gpu.state.blend_set('ALPHA_PREMULT')
        gpu.state.depth_test_set('LESS_EQUAL')   # meshes in front occlude splats
        gpu.state.depth_mask_set(False)          # blend: don't write depth yet (M2 will)
        sh=self.shader; sh.bind()
        sh.uniform_sampler('uData', self.datatex); sh.uniform_sampler('uIndex', idxtex)
        sh.uniform_int('uTW', _TW); sh.uniform_int('uITW', self.itw)
        sh.uniform_float('uRow0', right); sh.uniform_float('uRow1', up); sh.uniform_float('uRow2', fwd)
        sh.uniform_float('uCam', cam); sh.uniform_float('uF', (fx,fy)); sh.uniform_float('uVP', (float(w),float(h)))
        sh.uniform_float('uSigma', self.sigma)
        sh.uniform_float('uViewProj', view_proj)
        self.batch.draw_instanced(sh, instance_count=self.d['count'])
        gpu.state.blend_set('NONE')

    def free(self):
        self._gpu=False; self._idxtex=None; self.datatex=None
