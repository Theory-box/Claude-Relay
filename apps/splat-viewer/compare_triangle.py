import numpy as np, trimesh, time
from PIL import Image, ImageDraw
import triangle_splat as TS
from mesh_to_splat import _frames_from_normals, _R_to_quat
from render_gl import render as render_splats

rng=np.random.default_rng(2)
DIRS=rng.normal(size=(6,3)); DIRS/=np.linalg.norm(DIRS,axis=1,keepdims=True)
FREQ=np.array([4.,7.,12.,19.,28.,40.]); PH=rng.uniform(0,6.28,6); AMP=0.6**np.arange(6)
def fn(P):
    s=np.zeros(len(P))
    for k in range(6): s+=AMP[k]*np.sin(FREQ[k]*(P@DIRS[k])+PH[k])
    return s/AMP.sum()
def color_fn(P):
    t=np.clip(-P[:,2]*0.5+0.5,0,1)
    smooth=np.array([0.30,0.45,0.65])
    detail=np.stack([fn(P*6)*0.5+0.5,fn(P*6+10)*0.5+0.5,fn(P*6+20)*0.5+0.5],1)
    return np.clip(smooth[None]*(1-t[:,None])+detail*t[:,None],0,1)

m=trimesh.creation.icosphere(subdivisions=6); V=np.asarray(m.vertices)
rough=np.clip(-V[:,2],0,1); V=V*(1.0+0.18*rough*fn(V*2.0))[:,None]
m=trimesh.Trimesh(vertices=V,faces=m.faces); m.fix_normals()
print('rock: %d faces'%len(m.faces))
area=float(m.area)

# dense samples for the uniform baseline
pts,fidx=trimesh.sample.sample_surface(m,600000,seed=0)
pts=np.asarray(pts,np.float32); nrm=np.asarray(m.face_normals[fidx],np.float32); col=color_fn(pts).astype(np.float32)
def uniform(n):
    sel=rng.choice(len(pts),n,replace=False); r=float(np.sqrt(area/n))*0.9
    scale=np.tile(np.array([r,r,r*0.15],np.float32),(n,1))
    return dict(count=n,xyz=pts[sel],color=col[sel],opacity=np.full(n,0.9,np.float32),scale=scale,quat=_R_to_quat(_frames_from_normals(nrm[sel])))

N=40000
# per-triangle: decimate to N faces (adaptive) -> one splat per triangle
t=time.perf_counter(); dm=TS.decimate_to(m,N)
Vd=np.asarray(dm.vertices); Fd=np.asarray(dm.faces)
cent=Vd[Fd].mean(1); fcol=color_fn(cent).astype(np.float32)
sp_tri=TS.triangles_to_splats(Vd,Fd,fcol,cover=2.4)
print('per-triangle (decimated to %d): %d splats in %.2fs'%(N,sp_tri['count'],time.perf_counter()-t))
sp_uni=uniform(sp_tri['count']); sp_uni4=uniform(sp_tri['count']*4)

W=H=760
ctr=pts.mean(0); ext=float(np.linalg.norm(pts.max(0)-pts.min(0)))
cam=ctr+np.array([ext*0.5,-ext*1.2,-ext*0.4],np.float32); up=np.array([0,0,1],np.float32)
common=dict(W=W,H=H,cam=cam.astype(np.float32),target=ctr.astype(np.float32),up=up,fov_deg=45,three_sigma=2.4)
render_splats(sp_uni,  out="/tmp/t_uni.png", **common)
render_splats(sp_tri,  out="/tmp/t_tri.png", **common)
render_splats(sp_uni4, out="/tmp/t_uni4.png",**common)
labels=["UNIFORM %dk"%(sp_tri['count']//1000),"PER-TRIANGLE %dk (decimated)"%(sp_tri['count']//1000),"UNIFORM %dk (4x)"%(sp_tri['count']*4//1000)]
imgs=[Image.open(p).convert("RGB") for p in ["/tmp/t_uni.png","/tmp/t_tri.png","/tmp/t_uni4.png"]]
pad=10; combo=Image.new("RGB",(W*3+pad*4,H+46),(20,20,22)); dr=ImageDraw.Draw(combo)
for i,(im,lb) in enumerate(zip(imgs,labels)):
    x=pad+i*(W+pad); combo.paste(im,(x,40)); dr.text((x+8,14),lb,fill=(235,235,235))
combo.save("/tmp/triangle_compare.png"); print("saved")
