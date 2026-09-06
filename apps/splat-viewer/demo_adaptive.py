"""Compare uniform vs adaptive splat generation at equal count on a mixed-detail object."""
import numpy as np, trimesh
from PIL import Image, ImageDraw
from adaptive_fit import adaptive_fit
from mesh_to_splat import _frames_from_normals, _R_to_quat
from render_gl import render as render_splats

rng=np.random.default_rng(2)
DIRS=rng.normal(size=(6,3)); DIRS/=np.linalg.norm(DIRS,axis=1,keepdims=True)
FREQ=np.array([4.,7.,12.,19.,28.,40.]); PH=rng.uniform(0,6.28,6); AMP=0.6**np.arange(6)
def fn(P):
    s=np.zeros(len(P))
    for k in range(6): s+=AMP[k]*np.sin(FREQ[k]*(P@DIRS[k])+PH[k])
    return s/AMP.sum()

# mixed-detail object: icosphere, smooth top (z>0), rough bottom (z<0)
m=trimesh.creation.icosphere(subdivisions=6)
V=np.asarray(m.vertices)
rough=np.clip(-V[:,2],0,1)                       # 0 on top, ->1 at bottom
V=V*(1.0+0.18*rough*fn(V*2.0))[:,None]
m=trimesh.Trimesh(vertices=V,faces=m.faces); m.fix_normals()

def color_fn(P):
    t=np.clip(-P[:,2]*0.5+0.5,0,1)               # top vs bottom gradient
    smooth=np.array([0.30,0.45,0.65]); # calm blue on top
    detail=np.stack([fn(P*6)*0.5+0.5, fn(P*6+10)*0.5+0.5, fn(P*6+20)*0.5+0.5],1)  # busy on bottom
    return np.clip(smooth[None]*(1-t[:,None])+detail*t[:,None],0,1)

# dense ground-truth surface samples
pts,fidx=trimesh.sample.sample_surface(m, 500000, seed=0)
pts=np.asarray(pts,np.float32); nrm=np.asarray(m.face_normals[fidx],np.float32); col=color_fn(pts).astype(np.float32)
area=float(m.area)

def uniform(n):
    sel=rng.choice(len(pts), n, replace=False)
    P=pts[sel]; N=nrm[sel]; C=col[sel]
    sp=float(np.sqrt(area/n)); r=sp*0.9
    scale=np.tile(np.array([r*0.15,r,r],np.float32),(n,1))   # thin along normal (axis0)
    # frames put normal as 3rd col; reorder so thin axis matches -> use frames then set scale [t,b,n]=[r,r,thin]
    scale=np.tile(np.array([r,r,r*0.15],np.float32),(n,1))
    quat=_R_to_quat(_frames_from_normals(N))
    return dict(count=n,xyz=P,color=C,opacity=np.full(n,0.9,np.float32),scale=scale,quat=quat)

N=10000
sp_uni  = uniform(N)
sp_adap = adaptive_fit(pts, col, N, cover=2.0)
sp_uni4 = uniform(N*4)
print("uniform %d | adaptive %d | uniform %d"%(sp_uni['count'],sp_adap['count'],sp_uni4['count']))

W=H=760
ctr=pts.mean(0); ext=float(np.linalg.norm(pts.max(0)-pts.min(0)))
cam=ctr+np.array([ext*0.5,-ext*1.2,-ext*0.4],np.float32); up=np.array([0,0,1],np.float32)
common=dict(W=W,H=H,cam=cam.astype(np.float32),target=ctr.astype(np.float32),up=up,fov_deg=45,three_sigma=2.4)
render_splats(sp_uni,  out="/tmp/a_uni.png", **common)
render_splats(sp_adap, out="/tmp/a_adap.png",**common)
render_splats(sp_uni4, out="/tmp/a_uni4.png",**common)

labels=["UNIFORM  %dk"%(N//1000),"ADAPTIVE  %dk"%(N//1000),"UNIFORM  %dk (4x)"%(N*4//1000)]
imgs=[Image.open(p).convert("RGB") for p in ["/tmp/a_uni.png","/tmp/a_adap.png","/tmp/a_uni4.png"]]
pad=10; combo=Image.new("RGB",(W*3+pad*4,H+50),(20,20,22)); dr=ImageDraw.Draw(combo)
for i,(im,lb) in enumerate(zip(imgs,labels)):
    x=pad+i*(W+pad); combo.paste(im,(x,44)); dr.text((x+8,16),lb,fill=(235,235,235))
combo.save("/tmp/adaptive_compare.png"); print("saved /tmp/adaptive_compare.png")
