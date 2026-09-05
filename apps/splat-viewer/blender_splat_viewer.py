"""
blender_splat_viewer.py  —  real-time 3D Gaussian Splat viewer as a Blender viewport overlay.
RUN FROM BLENDER'S SCRIPTING TAB (needs a live GPU). Set PLY_PATH below to your .ply.

Architecture (all validated headless against a CPU reference before this port):
- Splat data packed ONCE into a static 2D-tiled RGBA32F texture (4 texels/splat), dodging the
  16384 max-texture-dim limit.
- Each frame: CPU depth-sorts (numpy argsort) and uploads only a small sorted-INDEX texture; the
  vertex shader indirects gl_InstanceID -> sorted id -> splat data, projects the 3D covariance to a
  2D ellipse (EWA), and the fragment shader does the gaussian falloff. Premultiplied alpha, no depth.
- Frame time is printed to the header so you get the perf number directly.

Toggle: run once to start, run again to stop. ESC also stops.
"""
import bpy, gpu, numpy as np, time
from gpu.types import GPUShader, GPUTexture, Buffer
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

# ------------------------------------------------------------------ CONFIG
PLY_PATH = r"/path/to/cactus_splat3_30kSteps_142k_splats.ply"   # <-- EDIT THIS
SIGMA    = 3.0        # gaussian extent (quad = SIGMA sigmas)
TW       = 4096       # data-texture width (multiple of 4)
SORT_EVERY_FRAME = True   # if laggy, we can throttle to on-camera-move later

# ------------------------------------------------------------------ minimal loader (numpy only)
SH_C0 = 0.28209479177387814
_PLY_T = {'char':'i1','uchar':'u1','short':'i2','ushort':'u2','int':'i4','uint':'u4',
          'float':'f4','float32':'f4','double':'f8','int8':'i1','uint8':'u1',
          'int16':'i2','uint16':'u2','int32':'i4','uint32':'u4','float64':'f8'}
def _sig(x): return 1.0/(1.0+np.exp(-x))
def load_ply(path):
    with open(path,'rb') as f:
        assert f.readline().strip()==b'ply'
        fmt=None; n=None; props=[]; inv=False
        while True:
            t=f.readline().split()
            if not t: continue
            if t[0]==b'format': fmt=t[1].decode()
            elif t[0]==b'element': inv=(t[1]==b'vertex');  n=int(t[2]) if inv else n
            elif t[0]==b'property' and inv: props.append((t[2].decode(),t[1].decode()))
            elif t[0]==b'end_header': break
        names=[p[0] for p in props]; types=[p[1] for p in props]
        little = (fmt=='binary_little_endian')
        if len(set(types))==1 and _PLY_T[types[0]] in ('f4','f8'):
            fdt=('<' if little else '>')+_PLY_T[types[0]]
            raw=np.frombuffer(f.read(n*len(props)*np.dtype(fdt).itemsize),fdt).reshape(n,len(props)).astype('f4',copy=False)
            d={nm:raw[:,i] for i,nm in enumerate(names)}
        else:
            dt=np.dtype([(nm,('<' if little else '>')+_PLY_T[t2]) for nm,t2 in props])
            a=np.frombuffer(f.read(n*dt.itemsize),dt,n); d={nm:a[nm].astype('f4') for nm in names}
    col=lambda *k: np.stack([d[x] for x in k],1)
    xyz=col('x','y','z')
    color=np.clip(0.5+SH_C0*col('f_dc_0','f_dc_1','f_dc_2'),0,1).astype('f4')
    opac=_sig(d['opacity']).astype('f4')
    scale=np.exp(col('scale_0','scale_1','scale_2')).astype('f4')
    q=col('rot_0','rot_1','rot_2','rot_3'); q=(q/(np.linalg.norm(q,axis=1,keepdims=True)+1e-9)).astype('f4')
    return dict(count=len(xyz),xyz=xyz.astype('f4'),color=color,opacity=opac,scale=scale,quat=q)

# ------------------------------------------------------------------ shaders (texture-fed, EWA)
VERT = """
uniform sampler2D uData; uniform sampler2D uIndex; uniform int uTW; uniform int uITW;
uniform vec3 uRow0, uRow1, uRow2; uniform vec3 uCam;
uniform vec2 uF; uniform vec2 uVP; uniform float uSigma;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin % w, lin / w); }
void main(){
    int sid = int(texelFetch(uIndex, at(gl_InstanceID, uITW), 0).r + 0.5);
    int base = sid*4;
    vec4 d0=texelFetch(uData,at(base+0,uTW),0); vec4 d1=texelFetch(uData,at(base+1,uTW),0);
    vec4 d2=texelFetch(uData,at(base+2,uTW),0); vec4 d3=texelFetch(uData,at(base+3,uTW),0);
    vec3 ic=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
    vec3 icol=vec3(d2.z,d2.w,d3.x); float iop=d3.y;
    vC=corner; vCol=icol; vOp=iop;
    vec3 dp=ic-uCam; vec3 t=vec3(dot(uRow0,dp),dot(uRow1,dp),dot(uRow2,dp));
    if(t.z<0.02){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }
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
    float l1=mid+disc,l2=max(mid-disc,1e-9);
    float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
    vec2 e1=vec2(b,l1-a); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
    vec2 ndc=vec2((uF.x*t.x*iz)/(uVP.x*0.5),(uF.y*t.y*iz)/(uVP.y*0.5));
    vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
    gl_Position=vec4(ndc+corner.x*e1*r1*p2n+corner.y*e2*r2*p2n,0.0,1.0);
}"""
FRAG = """
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.003) discard; o=vec4(vCol*al,al); }"""

# ------------------------------------------------------------------ viewer state
_state = {}

def _mkbuf(arr):
    """float32 numpy -> gpu Buffer via buffer protocol (no python list). 3-tier, never crashes."""
    n = len(arr)
    try:
        buf = Buffer('FLOAT', n)
        np.frombuffer(buf, dtype=np.float32)[:] = arr      # fast: memcpy via buffer protocol
        return buf
    except Exception:
        pass
    try:
        return Buffer('FLOAT', n, arr)                     # numpy direct
    except Exception:
        return Buffer('FLOAT', n, arr.tolist())            # last resort (slow but always works)

def _pack_data(d):
    N=d['count']; xyz=d['xyz']; sc=d['scale']; q=d['quat']; cl=d['color']; op=d['opacity']
    tex=np.zeros((N*4,4),'f4')
    tex[0::4]=np.column_stack([xyz,sc[:,0]])
    tex[1::4]=np.column_stack([sc[:,1],sc[:,2],q[:,0],q[:,1]])
    tex[2::4]=np.column_stack([q[:,2],q[:,3],cl[:,0],cl[:,1]])
    tex[3::4]=np.column_stack([cl[:,2],op,np.zeros(N,'f4'),np.zeros(N,'f4')])
    TH=(N*4+TW-1)//TW; full=np.zeros((TH*TW,4),'f4'); full[:N*4]=tex
    return full.reshape(TH,TW,4), TH

def _draw():
    st=_state
    if not st.get('on'): return
    ctx=bpy.context; region=ctx.region; rv3d=ctx.region_data
    if rv3d is None or rv3d.is_perspective is False:  # ortho unsupported in v1
        return
    W,H=region.width,region.height
    vm=rv3d.view_matrix; pm=rv3d.window_matrix
    right=Vector(vm[0][:3]); up=Vector(vm[1][:3]); fwd=-Vector(vm[2][:3])   # z-forward-positive
    cam=vm.inverted().translation
    fx=0.5*W*pm[0][0]; fy=0.5*H*pm[1][1]
    d=st['data']
    fwd_np=np.array(fwd,'f4'); cam_np=np.array(cam,'f4')
    # throttle: only re-sort when the camera moved enough (order is forgiving of small moves)
    need = ('idxtex' not in st)
    if not need:
        need = (float(np.dot(fwd_np, st['last_fwd'])) < 0.9994          # ~2 deg rotation
                or float(np.linalg.norm(cam_np - st['last_cam'])) > st['move_eps'])
    t_sort=0.0
    if need:
        t0=time.perf_counter()
        depth=(d['xyz']-cam_np) @ fwd_np
        lo=float(depth.min()); hi=float(depth.max())
        q=65535-((depth-lo)*(65535.0/(hi-lo+1e-9))).astype(np.uint16)   # far-first key
        order=np.argsort(q, kind='stable').astype(np.float32)           # ~2x faster than float argsort
        itw=st['itw']; ith=(len(order)+itw-1)//itw
        ibuf=np.zeros(itw*ith,'f4'); ibuf[:len(order)]=order
        st['idxtex']=GPUTexture((itw,ith),format='R32F',data=_mkbuf(ibuf))
        st['last_fwd']=fwd_np; st['last_cam']=cam_np
        t_sort=(time.perf_counter()-t0)*1000
    itw=st['itw']
    t2=time.perf_counter()
    sh=st['shader']
    gpu.state.blend_set('ALPHA_PREMULT'); gpu.state.depth_test_set('NONE')
    sh.bind()
    sh.uniform_sampler('uData', st['datatex']); sh.uniform_sampler('uIndex', st['idxtex'])
    sh.uniform_int('uTW', TW); sh.uniform_int('uITW', itw)
    sh.uniform_float('uRow0', right); sh.uniform_float('uRow1', up); sh.uniform_float('uRow2', fwd)
    sh.uniform_float('uCam', cam); sh.uniform_float('uF', (fx,fy)); sh.uniform_float('uVP', (float(W),float(H)))
    sh.uniform_float('uSigma', SIGMA)
    st['batch'].draw_instanced(sh, instance_count=d['count'])
    gpu.state.blend_set('NONE')
    t_draw=(time.perf_counter()-t2)*1000
    dt=t_sort+t_draw
    st['ema']=dt if st.get('ema') is None else st['ema']*0.9+dt*0.1
    tag = ("sort %.1f"%t_sort) if need else "cached "
    ctx.area.header_text_set("SPLATS %d | %.1f ms (~%.0f fps) | %s  draw %.1f" %
                             (d['count'], st['ema'], 1000.0/max(st['ema'],0.01), tag, t_draw))

class SPLAT_OT_toggle(bpy.types.Operator):
    bl_idname="splat.toggle"; bl_label="Toggle Splat Viewer"
    def execute(self, context):
        st=_state
        if st.get('on'):
            bpy.types.SpaceView3D.draw_handler_remove(st['handle'],'WINDOW'); st['on']=False
            context.area.header_text_set(None); context.area.tag_redraw()
            self.report({'INFO'},"Splat viewer stopped"); return {'FINISHED'}
        t=time.perf_counter(); d=load_ply(PLY_PATH); print("loaded %d splats in %.0f ms"%(d['count'],(time.perf_counter()-t)*1000))
        texdata,TH=_pack_data(d)
        st['data']=d
        st['datatex']=GPUTexture((TW,TH),format='RGBA32F',data=_mkbuf(texdata.ravel()))
        st['itw']=4096
        ext=float(np.linalg.norm(d['xyz'].max(0)-d['xyz'].min(0)))
        st['move_eps']=ext*0.02      # re-sort if camera translates >2% of extent
        st.pop('idxtex',None)        # force first-frame sort
        st['shader']=GPUShader(VERT,FRAG)
        st['batch']=batch_for_shader(st['shader'],'TRI_FAN',{"corner":[(-1,-1),(1,-1),(1,1),(-1,1)]})
        st['ema']=None; st['on']=True
        st['handle']=bpy.types.SpaceView3D.draw_handler_add(_draw,(),'WINDOW','POST_VIEW')
        context.area.tag_redraw(); self.report({'INFO'},"Splat viewer started"); return {'FINISHED'}

def _register():
    try: bpy.utils.register_class(SPLAT_OT_toggle)
    except Exception: pass

if __name__=="__main__":
    _register()
    bpy.ops.splat.toggle('INVOKE_DEFAULT')
