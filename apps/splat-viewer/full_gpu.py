"""
full_gpu.py — the full-GPU tile rasterizer assembled end-to-end (moderngl/llvmpipe), NO per-frame CPU.
Pipeline, all compute:
  1) project_emit : per splat -> conic+centre+depth (projected buffer), and atomicAdd-allocate + write
                    its (tileHi, depthLo, splatId) pairs for every tile its 3-sigma bbox covers.
  2) bitonic sort : sort the pairs by (tileHi, depthLo) -> grouped by tile, front-to-back within.
  3) tile_ranges  : per tile, binary-search the sorted pairs for its [start,end).
  4) blend        : per pixel, walk its tile's pairs front-to-back, evaluate the conic gaussian,
                    accumulate, and EARLY-OUT once opaque.
Validated against the reference tile_raster (which itself matched the splat render).
"""
import numpy as np, moderngl
from PIL import Image
import splat_io as S
from render_gl import look_at, cov3d

TILE=16; LOCAL=256

PROJ_SRC="""#version 430
layout(local_size_x=64) in;
layout(std430,binding=0) buffer In  { float sdata[]; };    // 14 floats/splat: c3 s3 q4 col3 op
layout(std430,binding=1) buffer Prj { float proj[]; };     // 9 floats/splat: cx cy ca cb cc r g b op
layout(std430,binding=2) buffer KHi { uint  khi[]; };
layout(std430,binding=3) buffer KLo { uint  klo[]; };
layout(std430,binding=4) buffer Val { uint  val[]; };
layout(std430,binding=5) buffer Ctr { uint  ctr; };
uniform vec3 uR0,uR1,uR2,uCam; uniform float uF; uniform vec2 uVP;
uniform int uN,uTX,uTY,uMaxPairs;
void main(){
  uint id=gl_GlobalInvocationID.x; if(id>=uint(uN)) return; int b=int(id)*14;
  vec3 ic=vec3(sdata[b],sdata[b+1],sdata[b+2]); vec3 is=vec3(sdata[b+3],sdata[b+4],sdata[b+5]);
  vec4 iq=vec4(sdata[b+6],sdata[b+7],sdata[b+8],sdata[b+9]);
  vec3 col=vec3(sdata[b+10],sdata[b+11],sdata[b+12]); float op=sdata[b+13];
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uR0,dp),dot(uR1,dp),dot(uR2,dp));
  int pb=int(id)*9;
  if(t.z<0.02){ proj[pb+8]=0.0; return; }
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
  float cx=(uF*t.x*iz)/(uVP.x*0.5); cx=(cx*0.5+0.5)*uVP.x;
  float cy=(uF*t.y*iz)/(uVP.y*0.5); cy=(cy*0.5+0.5)*uVP.y;
  float tr=a+cc,disc=sqrt(max(tr*tr/4.0-det,0.0)); float lam=tr/2.0+disc; float rad=3.0*sqrt(max(lam,1e-6));
  proj[pb]=cx; proj[pb+1]=cy; proj[pb+2]=conA; proj[pb+3]=conB; proj[pb+4]=conC;
  proj[pb+5]=col.r; proj[pb+6]=col.g; proj[pb+7]=col.b; proj[pb+8]=op;
  if(rad>=uVP.x){ return; }
  int tx0=clamp(int((cx-rad)/16.0),0,uTX-1), tx1=clamp(int((cx+rad)/16.0),0,uTX-1);
  int ty0=clamp(int((cy-rad)/16.0),0,uTY-1), ty1=clamp(int((cy+rad)/16.0),0,uTY-1);
  int nt=(tx1-tx0+1)*(ty1-ty0+1);
  uint off=atomicAdd(ctr, uint(nt));
  if(off+uint(nt)>uint(uMaxPairs)) return;
  uint dlo=floatBitsToUint(t.z);   // depth>0 -> monotonic key
  int k=0;
  for(int ty=ty0; ty<=ty1; ty++) for(int tx=tx0; tx<=tx1; tx++){
    uint slot=off+uint(k); khi[slot]=uint(ty*uTX+tx); klo[slot]=dlo; val[slot]=id; k++;
  }
}"""

SORT_SRC="""#version 430
layout(local_size_x=256) in;
layout(std430,binding=0) buffer KHi { uint khi[]; };
layout(std430,binding=1) buffer KLo { uint klo[]; };
layout(std430,binding=2) buffer Val { uint val[]; };
uniform int uJ,uK,uN;
void main(){
  uint i=gl_GlobalInvocationID.x; if(i>=uint(uN)) return; uint ixj=i^uint(uJ);
  if(ixj>i){
    bool asc=((i&uint(uK))==0u);
    bool gt = (khi[i]>khi[ixj]) || (khi[i]==khi[ixj] && klo[i]>klo[ixj]);
    if(gt==asc){
      uint a=khi[i]; khi[i]=khi[ixj]; khi[ixj]=a;
      uint c=klo[i]; klo[i]=klo[ixj]; klo[ixj]=c;
      uint d=val[i]; val[i]=val[ixj]; val[ixj]=d;
    }
  }
}"""

RANGE_SRC="""#version 430
layout(local_size_x=64) in;
layout(std430,binding=0) buffer KHi { uint khi[]; };
layout(std430,binding=1) buffer Off { int off[]; };
uniform int uNumTiles,uNumPairs;
void main(){                       // per tile: lower_bound of tile in sorted khi
  int tile=int(gl_GlobalInvocationID.x); if(tile>uNumTiles) return;
  int lo=0, hi=uNumPairs;
  while(lo<hi){ int m=(lo+hi)>>1; if(int(khi[m])<tile) lo=m+1; else hi=m; }
  off[tile]=lo;
}"""

BLEND_SRC="""#version 430
layout(local_size_x=16, local_size_y=16) in;
layout(rgba32f,binding=0) uniform image2D uOut;
layout(std430,binding=1) buffer Off { int off[]; };
layout(std430,binding=2) buffer Val { uint val[]; };
layout(std430,binding=3) buffer Prj { float proj[]; };
layout(std430,binding=4) buffer Cnt { uint blendops; };
uniform int uW,uH,uTX;
void main(){
  ivec2 px=ivec2(gl_GlobalInvocationID.xy); if(px.x>=uW||px.y>=uH) return;
  int tile=(px.y/16)*uTX+(px.x/16); int s=off[tile], e=off[tile+1];
  vec3 C=vec3(0.0); float T=1.0; uint ops=0u; vec2 p=vec2(px)+0.5;
  for(int i=s;i<e;i++){
    int b=int(val[i])*9; vec2 dd=p-vec2(proj[b],proj[b+1]);
    float power=-0.5*(proj[b+2]*dd.x*dd.x+2.0*proj[b+3]*dd.x*dd.y+proj[b+4]*dd.y*dd.y);
    if(power>0.0) continue;
    float al=min(proj[b+8]*exp(power),0.99); if(al<0.004) continue;
    C+=T*al*vec3(proj[b+5],proj[b+6],proj[b+7]); T*=(1.0-al); ops++;
    if(T<0.003) break;
  }
  imageStore(uOut,px,vec4(C,1.0-T)); atomicAdd(blendops,ops);
}"""

def run():
    d=S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    N=d['count']; W=H=760; TX=(W+TILE-1)//TILE; TY=(H+TILE-1)//TILE
    xyz=d['xyz']; bb0,bb1=xyz.min(0),xyz.max(0); ctr=(bb0+bb1)*0.5; ext=float(np.linalg.norm(bb1-bb0))
    cam=ctr+np.array([ext*0.55,-ext*1.25,ext*0.15],np.float32)
    Rv,campos=look_at(cam.astype(np.float32),ctr.astype(np.float32),np.array([0,-1,0],np.float32))
    f=0.5*H/np.tan(np.radians(48)*0.5)
    sdata=np.concatenate([d['xyz'],d['scale'],d['quat'],d['color'],d['opacity'][:,None]],1).astype('f4')
    MAXP=1<<21
    ctx=moderngl.create_context(standalone=True, backend='egl')
    bIn=ctx.buffer(sdata.tobytes()); bPrj=ctx.buffer(reserve=N*9*4)
    khi=np.full(MAXP,0xFFFFFFFF,np.uint32)
    bKHi=ctx.buffer(khi.tobytes()); bKLo=ctx.buffer(reserve=MAXP*4); bVal=ctx.buffer(reserve=MAXP*4)
    bCtr=ctx.buffer(np.zeros(1,'u4').tobytes())
    # 1) project + emit
    pr=ctx.compute_shader(PROJ_SRC)
    for nm,v in [('uR0',tuple(Rv[0])),('uR1',tuple(Rv[1])),('uR2',tuple(Rv[2])),('uCam',tuple(campos)),
                 ('uF',float(f)),('uVP',(float(W),float(H))),('uN',N),('uTX',TX),('uTY',TY),('uMaxPairs',MAXP)]:
        pr[nm].value=v
    for i,bb in enumerate([bIn,bPrj,bKHi,bKLo,bVal,bCtr]): bb.bind_to_storage_buffer(i)
    pr.run(group_x=(N+63)//64); ctx.memory_barrier()
    numPairs=int(np.frombuffer(bCtr.read(),'u4')[0])
    n2=1
    while n2<numPairs: n2<<=1
    # 2) bitonic sort (first n2 entries; unused are 0xFFFFFFFF -> sort to end)
    so=ctx.compute_shader(SORT_SRC); so['uN'].value=n2
    bKHi.bind_to_storage_buffer(0); bKLo.bind_to_storage_buffer(1); bVal.bind_to_storage_buffer(2)
    g=(n2+255)//256; k=2
    while k<=n2:
        j=k>>1
        while j>=1:
            so['uK'].value=k; so['uJ'].value=j; so.run(group_x=g); ctx.memory_barrier(); j>>=1
        k<<=1
    # 3) tile ranges
    bOff=ctx.buffer(reserve=(TX*TY+1)*4)
    rg=ctx.compute_shader(RANGE_SRC); rg['uNumTiles'].value=TX*TY; rg['uNumPairs'].value=numPairs
    bKHi.bind_to_storage_buffer(0); bOff.bind_to_storage_buffer(1)
    rg.run(group_x=(TX*TY+1+63)//64); ctx.memory_barrier()
    # 4) blend
    out=ctx.texture((W,H),4,dtype='f4'); out.bind_to_image(0,read=False,write=True)
    bBops=ctx.buffer(np.zeros(1,'u4').tobytes())
    bl=ctx.compute_shader(BLEND_SRC)
    for nm,v in [('uW',W),('uH',H),('uTX',TX)]: bl[nm].value=v
    bOff.bind_to_storage_buffer(1); bVal.bind_to_storage_buffer(2); bPrj.bind_to_storage_buffer(3); bBops.bind_to_storage_buffer(4)
    bl.run(group_x=(W+15)//16, group_y=(H+15)//16); ctx.memory_barrier()
    img=np.frombuffer(out.read(),'f4').reshape(H,W,4); bops=int(np.frombuffer(bBops.read(),'u4')[0])
    print("full-GPU pipeline: %d splats -> %d pairs (sorted %d) -> blend ops %d"%(N,numPairs,n2,bops))
    # compare to the reference tile_raster (CPU-binned, same blend)
    import tile_raster as TR
    proj,cx,cy,rad,depth,keep=TR.project(d,W,H)
    offset,ids,rTX,rTY,total=TR.bin_tiles(cx,cy,rad,depth,keep,W,H)
    ctx2=ctx; # reuse
    # render reference via tile_raster's compute (early on)
    csR=ctx.compute_shader(TR.BLEND)
    for nm,v in [('uW',W),('uH',H),('uTX',rTX)]: csR[nm].value=v
    bO=ctx.buffer(offset.tobytes()); bI=ctx.buffer(ids.tobytes()); bP=ctx.buffer(proj.tobytes())
    outR=ctx.texture((W,H),4,dtype='f4'); outR.bind_to_image(0,read=False,write=True)
    bC=ctx.buffer(np.zeros(1,'u4').tobytes())
    bO.bind_to_storage_buffer(1); bI.bind_to_storage_buffer(2); bP.bind_to_storage_buffer(3); bC.bind_to_storage_buffer(4)
    csR['uEarly'].value=1; csR.run(group_x=(W+15)//16, group_y=(H+15)//16); ctx.memory_barrier()
    imgR=np.frombuffer(outR.read(),'f4').reshape(H,W,4)
    diff=np.abs(img[...,:3]-imgR[...,:3])
    print("full-GPU vs CPU-binned reference:  mean|d|=%.4f  max|d|=%.4f  (should be ~0)"%(diff.mean(),diff.max()))
    Image.fromarray((np.clip(img,0,1)[::-1]*255).astype(np.uint8)).save("/tmp/full_gpu.png")
    print("saved /tmp/full_gpu.png")

if __name__=="__main__": run()
