import numpy as np, trimesh, time
from PIL import Image, ImageDraw
from adaptive_fit import adaptive_fit
from mesh_to_splat import _frames_from_normals, _R_to_quat
from render_gl import render as render_splats

s=trimesh.load('/mnt/user-data/uploads/Untitlesdgdsgdsgsdgd.glb', force='scene')
g=list(s.geometry.values())[0]
img=np.array(g.visual.material.baseColorTexture).astype(np.float32)/255.0
if img.shape[2]==4: img=img[...,:3]
print('mesh %d faces, texture %dx%d'%(len(g.faces), img.shape[1], img.shape[0]))

def bilinear(im, uv):
    h,w=im.shape[:2]; u=(uv[:,0]%1.0)*(w-1); v=(uv[:,1]%1.0)*(h-1)
    x0=np.floor(u).astype(int);y0=np.floor(v).astype(int);x1=np.minimum(x0+1,w-1);y1=np.minimum(y0+1,h-1)
    fx=(u-x0)[:,None];fy=(v-y0)[:,None]
    return (im[y0,x0]*(1-fx)*(1-fy)+im[y0,x1]*fx*(1-fy)+im[y1,x0]*(1-fx)*fy+im[y1,x1]*fx*fy)

# dense surface samples with texture colour + smooth normals
DENSE=600000
pts,fidx=trimesh.sample.sample_surface(g, DENSE, seed=0)
pts=np.asarray(pts,np.float32)
tris=g.triangles[fidx]
bary=trimesh.triangles.points_to_barycentric(tris, pts).astype(np.float32)
face_uv=g.visual.uv[g.faces[fidx]]                       # (N,3,2)
uv=(bary[:,:,None]*face_uv).sum(1)
uv[:,1]=1.0-uv[:,1]                                       # glTF v-flip for PIL row order
col=np.clip(bilinear(img, uv),0,1).astype(np.float32)
vn=g.vertex_normals[g.faces[fidx]]
nrm=(bary[:,:,None]*vn).sum(1); nrm/=(np.linalg.norm(nrm,axis=1,keepdims=True)+1e-9); nrm=nrm.astype(np.float32)
area=float(g.area)
rng=np.random.default_rng(0)

def uniform(n):
    sel=rng.choice(len(pts), n, replace=False)
    sp=float(np.sqrt(area/n)); r=sp*0.9
    scale=np.tile(np.array([r,r,r*0.15],np.float32),(n,1))
    quat=_R_to_quat(_frames_from_normals(nrm[sel]))
    return dict(count=n,xyz=pts[sel],color=col[sel],opacity=np.full(n,0.9,np.float32),scale=scale,quat=quat)

N=60000
t=time.perf_counter(); sp_adap=adaptive_fit(pts, col, N, cover=2.0); print('adaptive fit: %.1fs'%(time.perf_counter()-t))
sp_uni=uniform(N); sp_uni4=uniform(N*4)
print("uniform %d | adaptive %d | uniform %d"%(sp_uni['count'],sp_adap['count'],sp_uni4['count']))

W,H=620,880
ctr=pts.mean(0); ext=float(np.linalg.norm(pts.max(0)-pts.min(0)))
tall=int(np.argmax(pts.max(0)-pts.min(0))); up=np.eye(3,dtype=np.float32)[tall]
others=[i for i in range(3) if i!=tall]
cam=ctr.copy(); cam[others[0]]+=ext*0.1; cam[others[1]]-=ext*1.15; cam[tall]+=ext*0.02
common=dict(W=W,H=H,cam=cam.astype(np.float32),target=ctr.astype(np.float32),up=up,fov_deg=42,three_sigma=2.4)
render_splats(sp_uni,  out="/tmp/p_uni.png", **common)
render_splats(sp_adap, out="/tmp/p_adap.png",**common)
render_splats(sp_uni4, out="/tmp/p_uni4.png",**common)
labels=["UNIFORM %dk"%(N//1000),"ADAPTIVE %dk"%(N//1000),"UNIFORM %dk (4x)"%(N*4//1000)]
imgs=[Image.open(p).convert("RGB") for p in ["/tmp/p_uni.png","/tmp/p_adap.png","/tmp/p_uni4.png"]]
pad=10; combo=Image.new("RGB",(W*3+pad*4,H+46),(20,20,22)); dr=ImageDraw.Draw(combo)
for i,(im,lb) in enumerate(zip(imgs,labels)):
    x=pad+i*(W+pad); combo.paste(im,(x,40)); dr.text((x+8,14),lb,fill=(235,235,235))
combo.save("/tmp/plant_compare.png"); print("saved")
