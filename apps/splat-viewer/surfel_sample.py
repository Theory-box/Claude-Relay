"""
surfel_sample.py — topology-independent anisotropic surfels: sample the surface uniformly (density
you choose, no decimation), then orient/size each splat from its LOCAL neighbourhood (KNN PCA in the
tangent plane). Normal comes from the mesh (accurate, no gap-bridging); anisotropy comes from the real
local surface, not triangle shape. Decouples density (sampling) from orientation (local fit) from
topology (irrelevant).
"""
import numpy as np
from scipy.spatial import cKDTree
from mesh_to_splat import _R_to_quat

def surfels_from_points(pts, nrm, colors, k=12, cover=2.2, thin_ratio=0.12, reject=3.0, opacity=0.9):
    """
    pts:(N,3) surface samples, nrm:(N,3) mesh normals at those samples, colors:(N,3).
    Returns a splat dict of N anisotropic surfels, oriented by local-neighbourhood PCA.
    """
    N = len(pts); pts = pts.astype(np.float64); nrm = nrm.astype(np.float64)
    nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True)+1e-12)
    tree = cKDTree(pts)
    kk = min(k+1, N)
    d, idx = tree.query(pts, k=kk)                     # includes self at col 0
    d = d[:,1:]; idx = idx[:,1:]
    med = np.median(d, axis=1, keepdims=True) + 1e-9   # local spacing

    # tangent basis per point (from the mesh normal)
    ref = np.tile(np.array([0,0,1.0]), (N,1))
    bad = np.abs((nrm*ref).sum(1)) > 0.9
    ref[bad] = np.array([1,0,0.0])
    t1 = np.cross(nrm, ref); t1 /= (np.linalg.norm(t1,axis=1,keepdims=True)+1e-12)
    t2 = np.cross(nrm, t1)

    off = pts[idx] - pts[:,None,:]                     # (N,k,3) neighbour offsets
    inlier = (d <= reject*med)                         # drop neighbours across gaps
    u = np.einsum('nkc,nc->nk', off, t1)               # tangent coords
    v = np.einsum('nkc,nc->nk', off, t2)
    w = inlier.astype(np.float64); wsum = w.sum(1)+1e-9
    # weighted 2x2 tangent covariance per point
    uu = (w*u*u).sum(1)/wsum; uv = (w*u*v).sum(1)/wsum; vv = (w*v*v).sum(1)/wsum

    # eigendecomposition of [[uu,uv],[uv,vv]] (closed form)
    tr = uu+vv; det = uu*vv-uv*uv
    disc = np.sqrt(np.maximum(tr*tr/4-det, 0))
    l1 = tr/2+disc; l2 = np.maximum(tr/2-disc, 1e-12)   # l1>=l2
    # eigenvector for l1 in (u,v) space
    ex = uv; ey = l1-uu
    en = np.sqrt(ex*ex+ey*ey)
    small = en < 1e-9
    ex = np.where(small, 1.0, ex/np.maximum(en,1e-12)); ey = np.where(small, 0.0, ey/np.maximum(en,1e-12))
    # in-plane world axes
    ax1 = ex[:,None]*t1 + ey[:,None]*t2                # major
    ax2 = -ey[:,None]*t1 + ex[:,None]*t2               # minor
    s1 = cover*np.sqrt(l1); s2 = cover*np.sqrt(l2)
    thin = thin_ratio*np.maximum(s1,s2)

    # rotation columns = [normal(thin), ax2(minor), ax1(major)]  -> scale [thin, s2, s1]
    R = np.stack([nrm, ax2, ax1], axis=2)
    det3 = np.linalg.det(R); R[det3<0,:,0] *= -1
    scale = np.stack([thin, s2, s1], axis=1).astype(np.float32)
    quat = _R_to_quat(R.astype(np.float32))
    return dict(count=N, xyz=pts.astype(np.float32), color=np.clip(colors,0,1).astype(np.float32),
                opacity=np.full(N, opacity, np.float32), scale=scale, quat=quat)
