"""
render_depth.py — Route 1 proof (headless): render true-gaussian splats with MRT so DEPTH is
alpha-blended with the SAME 'over' operator as colour, giving a coherent per-pixel depth buffer.
Then run a screen-space AO pass on that depth buffer to show splats getting AO 'for free' — the
exact mechanism we'd port into Workbench 2.0.

Depth-over math: colour target accumulates (c*a, a); depth target accumulates (d*a, a). Both use
premultiplied over-blend, so expected_depth = Σ d_i a_i T_i / Σ a_i T_i = depth.r / colour.a.
"""
import numpy as np, moderngl
from PIL import Image, ImageDraw
from render_gl import look_at

VERT = """#version 330
in vec2 corner;
in vec3 iCenter; in vec3 iScale; in vec4 iQuat; in vec3 iCol; in float iOp;
uniform vec3 uRow0,uRow1,uRow2; uniform vec3 uCam; uniform float uF; uniform vec2 uVP; uniform float uSigma;
out vec2 vC; out vec3 vCol; out float vOp; out float vDepth;
void main(){
  vC=corner; vCol=iCol; vOp=iOp;
  vec3 d=iCenter-uCam; vec3 t=vec3(dot(uRow0,d),dot(uRow1,d),dot(uRow2,d));
  vDepth=t.z;
  if(t.z<0.02){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }
  float w=iQuat.x,x=iQuat.y,y=iQuat.z,z=iQuat.w;
  vec3 c0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  mat3 M=mat3(c0*iScale.x,c1*iScale.y,c2*iScale.z); mat3 Sig=M*transpose(M);
  float iz=1.0/t.z;
  mat3 J=mat3(vec3(uF*iz,0,0),vec3(0,uF*iz,0),vec3(-uF*t.x*iz*iz,-uF*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uRow0.x,uRow1.x,uRow2.x),vec3(uRow0.y,uRow1.y,uRow2.y),vec3(uRow0.z,uRow1.z,uRow2.z));
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float a=cov[0][0]+0.3,b=cov[0][1],c=cov[1][1]+0.3;
  float tr=a+c,det=a*c-b*b,mid=0.5*tr,disc=sqrt(max(mid*mid-det,0.0));
  float l1=mid+disc,l2=max(mid-disc,1e-9); float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
  vec2 e1=vec2(b,l1-a); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
  vec2 ndc=vec2((uF*t.x*iz)/(uVP.x*0.5),(uF*t.y*iz)/(uVP.y*0.5)); vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
  gl_Position=vec4(ndc+corner.x*e1*r1*p2n+corner.y*e2*r2*p2n,0.0,1.0);
}"""
FRAG = """#version 330
in vec2 vC; in vec3 vCol; in float vOp; in float vDepth;
layout(location=0) out vec4 oColor;
layout(location=1) out vec4 oDepth;
void main(){
  float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.003) discard;
  oColor=vec4(vCol*al, al);            // premultiplied colour + coverage
  oDepth=vec4(vDepth*al, 0.0, 0.0, al);// premultiplied depth; A=al drives the same over-blend
}"""

def ssao(depth, mask, radius_px=14, samples=16, strength=1.7, bias=0.010):
    """Simple range-based screen-space AO on a view-space depth buffer (numpy = same algo as a shader pass)."""
    H,W = depth.shape
    ao = np.zeros((H,W), np.float32)
    rng = np.random.default_rng(0)
    ang = rng.uniform(0, 2*np.pi, samples); rad = radius_px*np.sqrt(rng.uniform(0.1,1.0,samples))
    for a,r in zip(ang,rad):
        dx=int(round(np.cos(a)*r)); dy=int(round(np.sin(a)*r))
        nb = np.roll(np.roll(depth, dy, 0), dx, 1)
        nbm = np.roll(np.roll(mask, dy, 0), dx, 1)
        # neighbour closer to camera (smaller depth) than centre by > bias => occluder
        occ = ((depth - nb) > bias) & mask & nbm
        ao += occ.astype(np.float32)
    ao = np.clip(1.0 - strength*ao/samples, 0.0, 1.0)
    # light blur
    k=np.array([1,2,1],np.float32); k=k/k.sum()
    for _ in range(2):
        ao=np.apply_along_axis(lambda m:np.convolve(m,k,'same'),0,ao)
        ao=np.apply_along_axis(lambda m:np.convolve(m,k,'same'),1,ao)
    ao[~mask]=1.0
    return ao

def render(splat, W=820,H=820, out_prefix="/tmp/depth", fov_deg=48, sigma=2.4):
    xyz=splat['xyz']; bb0,bb1=xyz.min(0),xyz.max(0); ctr=(bb0+bb1)*0.5; ext=float(np.linalg.norm(bb1-bb0))
    cam=ctr+np.array([ext*0.55,-ext*1.25,ext*0.15],np.float32); up=np.array([0,-1,0],np.float32)
    Rv,campos=look_at(cam.astype(np.float32),ctr.astype(np.float32),up)
    f=0.5*H/np.tan(np.radians(fov_deg)*0.5)
    tz=(xyz-campos)@Rv[2]; order=np.argsort(-tz)                    # back-to-front
    inst=np.concatenate([xyz[order],splat['scale'][order],splat['quat'][order],
                         splat['color'][order],splat['opacity'][order][:,None]],1).astype('f4')
    try: ctx=moderngl.create_context(standalone=True, backend='egl')
    except Exception: ctx=moderngl.create_standalone_context()
    prog=ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
    for nm,v in [('uRow0',tuple(Rv[0])),('uRow1',tuple(Rv[1])),('uRow2',tuple(Rv[2])),
                 ('uCam',tuple(campos)),('uF',float(f)),('uVP',(float(W),float(H))),('uSigma',float(sigma))]:
        prog[nm].value=v
    quad=ctx.buffer(np.array([-1,-1,1,-1,1,1,-1,1],'f4').tobytes())
    ibuf=ctx.buffer(inst.tobytes())
    vao=ctx.vertex_array(prog,[(quad,'2f','corner'),(ibuf,'3f 3f 4f 3f 1f/i','iCenter','iScale','iQuat','iCol','iOp')])
    ctex=ctx.texture((W,H),4,dtype='f4'); dtex=ctx.texture((W,H),4,dtype='f4')
    fbo=ctx.framebuffer(color_attachments=[ctex,dtex]); fbo.use(); fbo.clear(0,0,0,0)
    ctx.enable(moderngl.BLEND); ctx.blend_func=moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
    vao.render(moderngl.TRIANGLE_FAN, instances=len(inst))
    col=np.frombuffer(ctex.read(),'f4').reshape(H,W,4)
    dep=np.frombuffer(dtex.read(),'f4').reshape(H,W,4)
    cov=col[...,3]                                                  # accumulated alpha
    mask=cov>0.15
    exp_depth=np.where(mask, dep[...,0]/np.maximum(cov,1e-6), 0.0)  # expected depth = Σd·a·T / Σa·T
    # colour over dark bg
    bg=np.array([0.05,0.05,0.06]); rgb=col[...,:3]+ (1-cov)[...,None]*bg
    ao=ssao(exp_depth.astype(np.float32), mask)
    lit=np.clip(rgb*ao[...,None],0,1)
    # visualise depth
    dv=exp_depth[mask]; d0,d1=(np.percentile(dv,2),np.percentile(dv,98)) if mask.any() else (0,1)
    depth_vis=np.clip((exp_depth-d0)/max(d1-d0,1e-6),0,1); depth_vis=np.where(mask,1.0-depth_vis,0.0)
    def save(a,p): Image.fromarray((np.clip(a,0,1)[::-1]*255).astype(np.uint8)).save(p)
    save(rgb,out_prefix+"_color.png"); save(np.repeat(depth_vis[...,None],3,2),out_prefix+"_depth.png")
    save(np.repeat(ao[...,None],3,2),out_prefix+"_ao.png"); save(lit,out_prefix+"_lit.png")
    return dict(mask_frac=float(mask.mean()), depth_range=(float(d0),float(d1)))

if __name__=="__main__":
    import splat_io as S
    d=S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    info=render(d)
    print("coverage %.2f  depth range %.2f..%.2f"%(info['mask_frac'],*info['depth_range']))
    # 4-panel
    ims=[Image.open("/tmp/depth_%s.png"%k).convert("RGB") for k in ["color","depth","ao","lit"]]
    labels=["COLOUR (splats)","DEPTH (over-blended)","SSAO from that depth","COLOUR x AO"]
    W,H=ims[0].size; pad=8; combo=Image.new("RGB",(W*4+pad*5,H+40),(20,20,22)); dr=ImageDraw.Draw(combo)
    for i,(im,lb) in enumerate(zip(ims,labels)):
        x=pad+i*(W+pad); combo.paste(im,(x,34)); dr.text((x+6,12),lb,fill=(235,235,235))
    combo.save("/tmp/depth_route1.png"); print("saved")
