"""
mesh_to_splat.py — generate a gaussian-splat cloud from a mesh by surface sampling (Mesh2Splat-style).
Pure CPU/numpy. Each sample becomes a flat disk gaussian lying in the surface tangent plane, coloured
by a supplied albedo function. No optimisation, no AI — a direct one-shot conversion.
"""
import numpy as np, trimesh

def _R_to_quat(R):
    """(N,3,3) rotation matrices -> (N,4) quaternions (w,x,y,z)."""
    m = R; N = len(m)
    tr = m[:,0,0]+m[:,1,1]+m[:,2,2]
    q = np.zeros((N,4), np.float32)
    # standard branchy conversion, vectorised by masks
    s0 = tr > 0
    S = np.sqrt(tr[s0]+1.0)*2
    q[s0,0]=0.25*S; q[s0,1]=(m[s0,2,1]-m[s0,1,2])/S
    q[s0,2]=(m[s0,0,2]-m[s0,2,0])/S; q[s0,3]=(m[s0,1,0]-m[s0,0,1])/S
    rest = ~s0
    if rest.any():
        mm=m[rest]
        d0=mm[:,0,0]; d1=mm[:,1,1]; d2=mm[:,2,2]
        c0=(d0>=d1)&(d0>=d2); c1=(~c0)&(d1>=d2); c2=(~c0)&(~c1)
        idx=np.nonzero(rest)[0]
        def fill(mask, a,b,c):  # a=major diag axis
            ii=idx[mask]; M=m[ii]
            S=np.sqrt(1.0+M[:,a,a]-M[:,b,b]-M[:,c,c])*2
            q[ii,0]=(M[:,c,b]-M[:,b,c])/S
            q[ii,1+a]=0.25*S
            q[ii,1+b]=(M[:,b,a]+M[:,a,b])/S
            q[ii,1+c]=(M[:,c,a]+M[:,a,c])/S
        if c0.any(): fill(c0,0,1,2)
        if c1.any(): fill(c1,1,2,0)
        if c2.any(): fill(c2,2,0,1)
    q /= (np.linalg.norm(q,axis=1,keepdims=True)+1e-9)
    return q.astype(np.float32)

def _frames_from_normals(n):
    """Build per-point tangent frames; returns R (N,3,3) with columns [t, b, n]."""
    n = n/(np.linalg.norm(n,axis=1,keepdims=True)+1e-9)
    up = np.tile(np.array([0,1,0],np.float32),(len(n),1))
    bad = np.abs((n*up).sum(1)) > 0.99
    up[bad] = np.array([1,0,0],np.float32)
    t = np.cross(up, n); t /= (np.linalg.norm(t,axis=1,keepdims=True)+1e-9)
    b = np.cross(n, t)
    R = np.stack([t, b, n], axis=2)   # columns
    return R.astype(np.float32)

def mesh_to_splats(mesh, n=60000, albedo_fn=None, radius_scale=0.75, thin=0.15, opacity=0.9, seed=0):
    """
    mesh: trimesh.Trimesh
    albedo_fn: (points[N,3], normals[N,3]) -> colors[N,3] in [0,1]. Defaults to mid-grey.
    Returns a splat dict compatible with render_gl.render / the Blender viewer.
    """
    pts, fidx = trimesh.sample.sample_surface_even(mesh, n, seed=seed)
    pts = np.asarray(pts, np.float32)
    nrm = np.asarray(mesh.face_normals[fidx], np.float32)
    spacing = float(np.sqrt(mesh.area / max(len(pts),1)))     # mean point spacing
    r = spacing*radius_scale
    scale = np.tile(np.array([r, r, r*thin],np.float32),(len(pts),1))   # flat disk in tangent plane
    R = _frames_from_normals(nrm)
    quat = _R_to_quat(R)
    if albedo_fn is None:
        color = np.full((len(pts),3),0.6,np.float32)
    else:
        color = np.clip(albedo_fn(pts, nrm),0,1).astype(np.float32)
    return dict(count=len(pts), xyz=pts, color=color, normal=nrm,
                opacity=np.full(len(pts),opacity,np.float32), scale=scale, quat=quat)
