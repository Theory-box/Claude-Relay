import trimesh, numpy as np, time
from mesh_to_splat import _frames_from_normals, _R_to_quat
from render_gl import render as render_splats

rng=np.random.default_rng(1)
TARGET=700000
s=trimesh.load('/tmp/tree/t.gltf', force='scene')

# per-geometry area-proportional sampling, colour by material
geoms=[]; areas=[]
for name,g in s.geometry.items():
    mat=getattr(g.visual,'material',None); mn=getattr(mat,'name','') if mat else ''
    geoms.append((g, 'twig' in mn)); areas.append(g.area)
areas=np.array(areas); frac=areas/areas.sum()
tot_faces=sum(len(g.faces) for g,_ in geoms)

allP=[]; allN=[]; allC=[]
for (g,is_foliage),fr in zip(geoms,frac):
    ni=max(int(TARGET*fr),50)
    pts,fidx=trimesh.sample.sample_surface(g, ni, seed=int(rng.integers(1e6)))
    pts=np.asarray(pts,np.float32); nrm=np.asarray(g.face_normals[fidx],np.float32)
    if is_foliage:
        t=rng.random((len(pts),1)).astype(np.float32)
        col=np.array([0.10,0.28,0.06])[None]+t*np.array([0.18,0.30,0.12])[None]   # green range
    else:
        t=rng.random((len(pts),1)).astype(np.float32)
        col=np.array([0.22,0.15,0.09])[None]+t*np.array([0.20,0.15,0.10])[None]   # brown range
    allP.append(pts); allN.append(nrm); allC.append(col.astype(np.float32))
P=np.concatenate(allP); N=np.concatenate(allN); C=np.concatenate(allC)
Nsp=len(P)
area_tot=sum(areas); spacing=float(np.sqrt(area_tot/Nsp))
scale=np.tile(np.array([spacing*0.8,spacing*0.8,spacing*0.12],np.float32),(Nsp,1))
quat=_R_to_quat(_frames_from_normals(N))
sp=dict(count=Nsp,xyz=P.astype(np.float32),color=np.clip(C,0,1),normal=N,
        opacity=np.full(Nsp,0.9,np.float32),scale=scale,quat=quat)
print("tree: %d tris -> %d splats (%.1fx fewer primitives)"%(tot_faces,Nsp,tot_faces/Nsp))

# camera: fir trees are tall (Z up in this asset?); fit from bbox
bb_min=P.min(0); bb_max=P.max(0); ctr=(bb_min+bb_max)*0.5
ext=float(np.linalg.norm(bb_max-bb_min))
# figure tall axis
tall=np.argmax(bb_max-bb_min); up=np.eye(3,dtype=np.float32)[tall]
# camera in front, offset on the two non-tall axes
others=[i for i in range(3) if i!=tall]
cam=ctr.copy(); cam[others[0]]+=ext*0.0; cam[others[1]]-=ext*0.9; cam[tall]+=ext*0.05
render_splats(sp, 700,950, cam=cam.astype(np.float32), target=ctr.astype(np.float32),
              up=up, fov_deg=45, three_sigma=2.4, out="/tmp/tree_splats.png")
print("saved /tmp/tree_splats.png  |  splats:",Nsp,"| up axis:",tall)
