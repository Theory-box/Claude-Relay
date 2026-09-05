"""
tile_raster.py — prototype of a compute TILE RASTERIZER for splats (the top-tier approach) + a
measurement of how much overdraw its front-to-back EARLY TERMINATION saves vs blending everything.

Pipeline (prototype): CPU projects each splat to a 2D conic (inverse covariance) + bins it into the
16x16 screen tiles it covers, sorted front-to-back per tile. A compute kernel then blends per pixel,
looping only that pixel's tile list and STOPPING once the pixel is opaque. We run it with early-term
ON and OFF, count the blend operations each does, and diff the images — the ops ratio is the win.
"""
import numpy as np, moderngl
from PIL import Image
from render_gl import look_at, quat_to_R, cov3d
import splat_io as S

TILE = 16

def project(d, W, H, fov=48.0):
    xyz=d['xyz']; bb0,bb1=xyz.min(0),xyz.max(0); ctr=(bb0+bb1)*0.5; ext=float(np.linalg.norm(bb1-bb0))
    cam=ctr+np.array([ext*0.55,-ext*1.25,ext*0.15],np.float32)
    Rv,campos=look_at(cam.astype(np.float32),ctr.astype(np.float32),np.array([0,-1,0],np.float32))
    f=0.5*H/np.tan(np.radians(fov)*0.5)
    t=(xyz-campos)@Rv.T                                  # view space (z fwd)
    front=t[:,2]>ext*0.02
    Sig=cov3d(d['scale'], d['quat'])
    tz=t[:,2]; tx=t[:,0]; ty=t[:,1]
    J=np.zeros((len(xyz),2,3),np.float32)
    J[:,0,0]=f/tz; J[:,0,2]=-f*tx/(tz*tz); J[:,1,1]=f/tz; J[:,1,2]=-f*ty/(tz*tz)
    Tm=J@Rv; cov2=Tm@Sig@Tm.transpose(0,2,1)
    a=cov2[:,0,0]+0.3; b=cov2[:,0,1]; c=cov2[:,1,1]+0.3
    det=a*c-b*b; det=np.where(np.abs(det)<1e-9,1e-9,det)
    ca=c/det; cb=-b/det; cc=a/det                        # conic (inverse 2D covariance)
    cx=((f*tx/tz)/(W*0.5)*0.5+0.5)*W; cy=((f*ty/tz)/(H*0.5)*0.5+0.5)*H
    tr=a+c; disc=np.sqrt(np.maximum(tr*tr/4-det,0)); lam=tr/2+disc
    rad=3.0*np.sqrt(np.maximum(lam,1e-6))                # 3-sigma radius (px) for the tile bbox
    keep=front & (rad<W)
    col=d['color']; op=d['opacity']
    proj=np.zeros((len(xyz),9),np.float32)
    proj[:,0]=cx; proj[:,1]=cy; proj[:,2]=ca; proj[:,3]=cb; proj[:,4]=cc
    proj[:,5:8]=col; proj[:,8]=op
    return proj, cx, cy, rad, tz, keep

def bin_tiles(cx, cy, rad, depth, keep, W, H):
    TX=(W+TILE-1)//TILE; TY=(H+TILE-1)//TILE
    idx=np.nonzero(keep)[0]
    cxk=cx[idx]; cyk=cy[idx]; rk=rad[idx]; dk=depth[idx]
    tx0=np.clip(((cxk-rk)//TILE).astype(int),0,TX-1); tx1=np.clip(((cxk+rk)//TILE).astype(int),0,TX-1)
    ty0=np.clip(((cyk-rk)//TILE).astype(int),0,TY-1); ty1=np.clip(((cyk+rk)//TILE).astype(int),0,TY-1)
    nx=tx1-tx0+1; ny=ty1-ty0+1; ntiles=(nx*ny).astype(np.int64)
    total=int(ntiles.sum())
    splat_of=np.repeat(idx, ntiles)
    starts=np.repeat(np.cumsum(ntiles)-ntiles, ntiles)
    local=np.arange(total)-starts
    nxr=np.repeat(nx, ntiles)
    dx=local%nxr; dy=local//nxr
    tid=(np.repeat(ty0,ntiles)+dy)*TX + (np.repeat(tx0,ntiles)+dx)
    dep=np.repeat(dk, ntiles)
    o=np.lexsort((dep, tid))                              # group by tile, front-to-back within
    tid_s=tid[o]; ids_s=splat_of[o].astype(np.int32)
    offset=np.searchsorted(tid_s, np.arange(TX*TY+1)).astype(np.int32)
    return offset, ids_s, TX, TY, total

BLEND = """#version 430
layout(local_size_x=16, local_size_y=16) in;
layout(rgba32f, binding=0) uniform image2D uOut;
layout(std430, binding=1) buffer Off { int off[]; };
layout(std430, binding=2) buffer Ids { int ids[]; };
layout(std430, binding=3) buffer Proj { float proj[]; };
layout(std430, binding=4) buffer Cnt { uint blendops; };
uniform int uW; uniform int uH; uniform int uTX; uniform int uEarly;
void main(){
  ivec2 px=ivec2(gl_GlobalInvocationID.xy); if(px.x>=uW||px.y>=uH) return;
  int tile=(px.y/16)*uTX+(px.x/16); int s=off[tile], e=off[tile+1];
  vec3 C=vec3(0.0); float T=1.0; uint ops=0u; vec2 p=vec2(px)+0.5;
  for(int i=s;i<e;i++){
    int b=ids[i]*9; vec2 dd=p-vec2(proj[b],proj[b+1]);
    float power=-0.5*(proj[b+2]*dd.x*dd.x + 2.0*proj[b+3]*dd.x*dd.y + proj[b+4]*dd.y*dd.y);
    if(power>0.0) continue;
    float al=min(proj[b+8]*exp(power), 0.99); if(al<0.004) continue;
    C+=T*al*vec3(proj[b+5],proj[b+6],proj[b+7]); T*=(1.0-al); ops++;
    if(uEarly==1 && T<0.003) break;
  }
  imageStore(uOut, px, vec4(C, 1.0-T));
  atomicAdd(blendops, ops);
}"""

def run():
    d=S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    W=H=760
    proj,cx,cy,rad,depth,keep=project(d,W,H)
    offset,ids,TX,TY,total=bin_tiles(cx,cy,rad,depth,keep,W,H)
    print("splats %d (kept %d) | tile entries %d (avg %.1f/tile)"%(d['count'],int(keep.sum()),total,total/(TX*TY)))
    ctx=moderngl.create_context(standalone=True, backend='egl')
    cs=ctx.compute_shader(BLEND)
    bOff=ctx.buffer(offset.tobytes()); bIds=ctx.buffer(ids.tobytes()); bProj=ctx.buffer(proj.tobytes())
    for nm,val in [('uW',W),('uH',H),('uTX',TX)]: cs[nm].value=val
    def render(early):
        out=ctx.texture((W,H),4,dtype='f4'); out.bind_to_image(0,read=False,write=True)
        bCnt=ctx.buffer(np.zeros(1,'u4').tobytes())
        bOff.bind_to_storage_buffer(1); bIds.bind_to_storage_buffer(2); bProj.bind_to_storage_buffer(3); bCnt.bind_to_storage_buffer(4)
        cs['uEarly'].value=early
        cs.run(group_x=(W+15)//16, group_y=(H+15)//16); ctx.memory_barrier()
        img=np.frombuffer(out.read(),'f4').reshape(H,W,4)
        ops=np.frombuffer(bCnt.read(),'u4')[0]
        return img, int(ops)
    imgN, opsN = render(0)   # no early term (blend everything)
    imgE, opsE = render(1)   # early termination
    diff=np.abs(imgN[...,:3]-imgE[...,:3])
    print("blend ops:  all=%d  early=%d  ->  %.2fx fewer (overdraw killed)"%(opsN,opsE,opsN/max(opsE,1)))
    print("image diff early-vs-all:  mean=%.4f  max=%.4f  (should be ~0 = identical result)"%(diff.mean(),diff.max()))
    Image.fromarray((np.clip(imgE,0,1)[::-1]*255).astype(np.uint8)).save("/tmp/tile_raster.png")
    print("saved /tmp/tile_raster.png")

if __name__=="__main__": run()
