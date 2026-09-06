"""Generate the fir-tree splats and export as a standard 3DGS .ply the Blender viewer can load."""
import trimesh, numpy as np
from mesh_to_splat import _frames_from_normals, _R_to_quat
from splat_io import save_ply, load_ply, SH_C0

rng=np.random.default_rng(1); TARGET=700000
s=trimesh.load('/tmp/tree/t.gltf', force='scene')
geoms=[]; areas=[]
for name,g in s.geometry.items():
    mat=getattr(g.visual,'material',None); mn=getattr(mat,'name','') if mat else ''
    geoms.append((g,'twig' in mn)); areas.append(g.area)
areas=np.array(areas); frac=areas/areas.sum()
allP=[];allN=[];allC=[]
for (g,is_fol),fr in zip(geoms,frac):
    ni=max(int(TARGET*fr),50)
    pts,fidx=trimesh.sample.sample_surface(g,ni,seed=int(rng.integers(1e6)))
    pts=np.asarray(pts,np.float32); nrm=np.asarray(g.face_normals[fidx],np.float32)
    t=rng.random((len(pts),1)).astype(np.float32)
    if is_fol: col=np.array([0.10,0.28,0.06])[None]+t*np.array([0.18,0.30,0.12])[None]
    else:      col=np.array([0.22,0.15,0.09])[None]+t*np.array([0.20,0.15,0.10])[None]
    allP.append(pts);allN.append(nrm);allC.append(col.astype(np.float32))
P=np.concatenate(allP);N=np.concatenate(allN);C=np.clip(np.concatenate(allC),0,1)
# glTF Y-up -> Blender Z-up:  (x,y,z) -> (x,-z,y)
P=np.column_stack([P[:,0],-P[:,2],P[:,1]]).astype(np.float32)
N=np.column_stack([N[:,0],-N[:,2],N[:,1]]).astype(np.float32)
Nsp=len(P); spacing=float(np.sqrt(sum(areas)/Nsp))
scale=np.tile(np.array([spacing*0.8,spacing*0.8,spacing*0.12],np.float32),(Nsp,1))
quat=_R_to_quat(_frames_from_normals(N))

# invert activations -> RAW values for the standard .ply
f_dc=((C-0.5)/SH_C0).astype(np.float32)
op=np.full(Nsp,0.9,np.float32); opacity_raw=np.log(op/(1-op)).astype(np.float32)   # logit
scale_raw=np.log(np.maximum(scale,1e-9)).astype(np.float32)

out="/mnt/user-data/outputs/fir_tree_700k_splats.ply"
save_ply(out, P.astype(np.float32), f_dc, opacity_raw, scale_raw, quat.astype(np.float32))

# round-trip verify: load it back, confirm activations recover the colours/opacity/scale
d=load_ply(out)
import os
print("wrote %s  (%.1f MB, %d splats)"%(out, os.path.getsize(out)/1e6, d['count']))
print("roundtrip color err:", round(float(np.abs(d['color']-C).max()),4))
print("roundtrip opacity:", round(float(d['opacity'][0]),3), "(expect 0.9)")
print("roundtrip scale err:", round(float(np.abs(d['scale']-scale).max()),5))
