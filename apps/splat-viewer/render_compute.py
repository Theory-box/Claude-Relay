"""
render_compute.py — prototype + validate the splat compute pre-pass headless (moderngl/llvmpipe).

Path A (current): the vertex shader computes the EWA projection per corner (4x/splat, per pass).
Path B (new): a COMPUTE shader computes the projection ONCE per splat into an output texture; the
render vertex shader just reads it and places the quad. We render both and diff — must be identical.

moderngl uses an image2D output from compute + texelFetch to read it back in the vertex shader, which
mirrors Blender's compute I/O (no SSBO there).
"""
import numpy as np, moderngl
from PIL import Image
from render_gl import look_at
import splat_io as S

TW = 4096      # data texture width
OTW = 4096     # projected-output texture width (4 texels/splat)

# ---- shared EWA projection GLSL (as a compute body + as a vertex body) ----
_PROJ_BODY = """
  vec3 ic=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
  vec3 icol=vec3(d2.z,d2.w,d3.x); float iop=d3.y;
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uRow0,dp),dot(uRow1,dp),dot(uRow2,dp));
  vec4 clipC=uViewProj*vec4(ic,1.0);
  float cull = (t.z<0.02 || clipC.w<=0.0) ? 1.0 : 0.0;
  float w=iq.x,x=iq.y,y=iq.z,z=iq.w;
  vec3 c0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  float iz=1.0/max(t.z,1e-6);
  mat3 J=mat3(vec3(uF.x*iz,0,0),vec3(0,uF.y*iz,0),vec3(-uF.x*t.x*iz*iz,-uF.y*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uRow0.x,uRow1.x,uRow2.x),vec3(uRow0.y,uRow1.y,uRow2.y),vec3(uRow0.z,uRow1.z,uRow2.z));
  mat3 M=mat3(c0*is.x,c1*is.y,c2*is.z); mat3 Sig=M*transpose(M);
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float ca=cov[0][0]+0.3,cb=cov[0][1],cc=cov[1][1]+0.3;
  float tr=ca+cc,det=ca*cc-cb*cb,mid=0.5*tr,disc=sqrt(max(mid*mid-det,0.0));
  float l1=mid+disc,l2=max(mid-disc,1e-9); float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
  vec2 e1=vec2(cb,l1-ca); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
  vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
  vec2 A1=e1*r1*p2n, A2=e2*r2*p2n;
"""

_UNIS = """
uniform vec3 uRow0,uRow1,uRow2; uniform vec3 uCam; uniform vec2 uF; uniform vec2 uVP; uniform float uSigma;
uniform mat4 uViewProj;
"""

# Path A: projection in the vertex shader (current)
VERT_A = "#version 330\n" + _UNIS + """
uniform sampler2D uData; uniform sampler2D uIndex; uniform int uTW; uniform int uITW;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin%w, lin/w); }
void main(){
  int sid=int(texelFetch(uIndex,at(gl_InstanceID,uITW),0).r+0.5); int base=sid*4;
  vec4 d0=texelFetch(uData,at(base,uTW),0),d1=texelFetch(uData,at(base+1,uTW),0),
       d2=texelFetch(uData,at(base+2,uTW),0),d3=texelFetch(uData,at(base+3,uTW),0);
""" + _PROJ_BODY + """
  vC=corner; vCol=icol; vOp=iop;
  if(cull>0.5){ gl_Position=vec4(2,2,2,1); return; }
  gl_Position=vec4(clipC.xy + (corner.x*A1+corner.y*A2)*clipC.w, clipC.z, clipC.w);
}"""

# Path B: COMPUTE writes projected params; vertex reads them
COMPUTE = "#version 430\n" + _UNIS + """
layout(local_size_x=64) in;
layout(rgba32f, binding=0) uniform writeonly image2D uOut;
uniform sampler2D uData; uniform int uTW; uniform int uOTW; uniform int uCount;
ivec2 at(int lin,int w){ return ivec2(lin%w, lin/w); }
void main(){
  int id=int(gl_GlobalInvocationID.x); if(id>=uCount) return; int base=id*4;
  vec4 d0=texelFetch(uData,at(base,uTW),0),d1=texelFetch(uData,at(base+1,uTW),0),
       d2=texelFetch(uData,at(base+2,uTW),0),d3=texelFetch(uData,at(base+3,uTW),0);
""" + _PROJ_BODY + """
  int ob=id*4;
  imageStore(uOut, at(ob+0,uOTW), vec4(clipC.xy, clipC.z, clipC.w));
  imageStore(uOut, at(ob+1,uOTW), vec4(A1, A2));
  imageStore(uOut, at(ob+2,uOTW), vec4(icol, iop));
  imageStore(uOut, at(ob+3,uOTW), vec4(cull,0,0,0));
}"""

VERT_B = """#version 330
uniform sampler2D uProj; uniform sampler2D uIndex; uniform int uOTW; uniform int uITW;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin%w, lin/w); }
void main(){
  int sid=int(texelFetch(uIndex,at(gl_InstanceID,uITW),0).r+0.5); int ob=sid*4;
  vec4 p0=texelFetch(uProj,at(ob+0,uOTW),0), p1=texelFetch(uProj,at(ob+1,uOTW),0),
       p2=texelFetch(uProj,at(ob+2,uOTW),0), p3=texelFetch(uProj,at(ob+3,uOTW),0);
  vC=corner; vCol=p2.rgb; vOp=p2.w;
  if(p3.x>0.5){ gl_Position=vec4(2,2,2,1); return; }
  gl_Position=vec4(p0.xy + (corner.x*p1.xy+corner.y*p1.zw)*p0.w, p0.z, p0.w);
}"""

FRAG = """#version 330
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.004) discard; o=vec4(vCol*al,al); }"""

def _pack(d):
    N=d['count']; xyz=d['xyz']; sc=d['scale']; q=d['quat']; cl=d['color']; op=d['opacity']
    tex=np.zeros((N*4,4),'f4')
    tex[0::4]=np.column_stack([xyz,sc[:,0]]); tex[1::4]=np.column_stack([sc[:,1],sc[:,2],q[:,0],q[:,1]])
    tex[2::4]=np.column_stack([q[:,2],q[:,3],cl[:,0],cl[:,1]]); tex[3::4]=np.column_stack([cl[:,2],op,np.zeros(N,'f4'),np.zeros(N,'f4')])
    TH=(N*4+TW-1)//TW; full=np.zeros((TH*TW,4),'f4'); full[:N*4]=tex
    return full.reshape(TH,TW,4), TH

def run():
    d=S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    N=d['count']; W=H=760
    xyz=d['xyz']; bb0,bb1=xyz.min(0),xyz.max(0); ctr=(bb0+bb1)*0.5; ext=float(np.linalg.norm(bb1-bb0))
    cam=ctr+np.array([ext*0.55,-ext*1.25,ext*0.15],'f4'); up=np.array([0,-1,0],'f4')
    Rv,campos=look_at(cam,ctr,up); f=0.5*H/np.tan(np.radians(48)*0.5)
    view_proj=None
    # build a projection matrix consistent with the shader (use render_gl-style: derive from f)
    import numpy as _np
    near,far=ext*0.05,ext*6
    P=_np.array([[2*f/W,0,0,0],[0,2*f/H,0,0],[0,0,-(far+near)/(far-near),-2*far*near/(far-far+far-near) if False else -2*far*near/(far-near)],[0,0,-1,0]],'f4')
    # view matrix: z-forward-negative standard from Rv (forward=Rv[2]) — but our shader uses uViewProj @ world
    Vm=_np.eye(4,dtype='f4'); Vm[:3,:3]=_np.array([Rv[0],Rv[1],-Rv[2]]); Vm[:3,3]=-Vm[:3,:3]@campos
    view_proj=(P@Vm).astype('f4')
    tz=(xyz-campos)@Rv[2]; order=np.argsort(-tz).astype('f4')
    texdata,TH=_pack(d)

    ctx=moderngl.create_context(standalone=True, backend='egl')
    dtex=ctx.texture((TW,TH),4,texdata.tobytes(),dtype='f4'); dtex.filter=(moderngl.NEAREST,moderngl.NEAREST)
    itw=4096; ith=(N+itw-1)//itw; ibuf=np.zeros(itw*ith,'f4'); ibuf[:N]=order
    itex=ctx.texture((itw,ith),1,ibuf.tobytes(),dtype='f4'); itex.filter=(moderngl.NEAREST,moderngl.NEAREST)
    quad=ctx.buffer(np.array([-1,-1,1,-1,1,1,-1,1],'f4').tobytes())

    def set_proj_unis(prog):
        for nm,v in [('uRow0',tuple(Rv[0])),('uRow1',tuple(Rv[1])),('uRow2',tuple(Rv[2])),
                     ('uCam',tuple(campos)),('uF',(float(f),float(f))),('uVP',(float(W),float(H))),('uSigma',2.4)]:
            try: prog[nm].value=v
            except Exception: pass
        try: prog['uViewProj'].write(view_proj.T.tobytes())
        except Exception: pass

    def render(prog, extra):
        fbo=ctx.simple_framebuffer((W,H)); fbo.use(); fbo.clear(0.05,0.05,0.06,1.0)
        ctx.enable(moderngl.BLEND); ctx.blend_func=moderngl.ONE,moderngl.ONE_MINUS_SRC_ALPHA
        extra()
        vao=ctx.vertex_array(prog,[(quad,'2f','corner')])
        vao.render(moderngl.TRIANGLE_FAN, instances=N)
        return np.frombuffer(fbo.read(components=4),'u1').reshape(H,W,4)

    # Path A
    pa=ctx.program(vertex_shader=VERT_A, fragment_shader=FRAG)
    dtex.use(0); itex.use(1); pa['uData'].value=0; pa['uIndex'].value=1; pa['uTW'].value=TW; pa['uITW'].value=itw
    set_proj_unis(pa)
    imgA=render(pa, lambda: None)

    # Path B: compute -> projected texture -> read
    cs=ctx.compute_shader(COMPUTE)
    oth=(N*4+OTW-1)//OTW; otex=ctx.texture((OTW,oth),4,dtype='f4'); otex.filter=(moderngl.NEAREST,moderngl.NEAREST)
    dtex.use(0); cs['uData'].value=0; cs['uTW'].value=TW; cs['uOTW'].value=OTW; cs['uCount'].value=N
    set_proj_unis(cs)
    otex.bind_to_image(0, read=False, write=True)
    cs.run(group_x=(N+63)//64)
    ctx.memory_barrier()
    pb=ctx.program(vertex_shader=VERT_B, fragment_shader=FRAG)
    otex.use(2); itex.use(1); pb['uProj'].value=2; pb['uIndex'].value=1; pb['uOTW'].value=OTW; pb['uITW'].value=itw
    imgB=render(pb, lambda: None)

    diff=np.abs(imgA[...,:3].astype(int)-imgB[...,:3].astype(int))
    print("Path A (per-vertex) vs Path B (compute pre-pass):")
    print("  mean|Δ|=%.3f  max|Δ|=%d  pixels>2=%.4f%%"%(diff.mean(),diff.max(),100*(diff.max(2)>2).mean()))
    Image.fromarray(imgA[::-1]).save("/tmp/cmp_A.png"); Image.fromarray(imgB[::-1]).save("/tmp/cmp_B.png")
    print("  saved /tmp/cmp_A.png /tmp/cmp_B.png")

if __name__=="__main__": run()
