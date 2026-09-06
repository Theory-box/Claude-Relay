"""
triangle_splat.py — deterministic mesh->splat: one anisotropic gaussian per triangle, from the
triangle's own covariance (the Steiner-inellipse / uniform-triangle-distribution ellipse). Fully
vectorised (batched covariance + batched eigh + batched quat) — no clustering loop, milliseconds.

Each triangle -> a flat surfel: centre at the centroid, the two in-plane axes sized to the triangle's
shape (anisotropic), the normal as the thin axis. Adaptive "for free" when the mesh tessellation
follows detail; use decimate_to() first for count control + curvature-driven adaptivity.
"""
import numpy as np
from mesh_to_splat import _R_to_quat            # batched (N,3,3)->(N,4)

# covariance of a uniform distribution over the 2-simplex: Var=1/18 on diag, Cov=-1/36 off
_C11 = 1.0/18.0; _C12 = -1.0/36.0

def triangles_to_splats(V, F, face_colors, cover=2.4, thin_ratio=0.12, opacity=0.9):
    """
    V:(nv,3) vertices (world), F:(nt,3) triangle vertex indices, face_colors:(nt,3) colour per triangle.
    Returns a splat dict (one splat per triangle).
    """
    V = V.astype(np.float64)
    tri = V[F]                                   # (nt,3,3)
    a, b, c = tri[:,0], tri[:,1], tri[:,2]
    e1 = b - a; e2 = c - a
    centroid = (a + b + c) / 3.0
    # Sigma = [e1 e2] C [e1 e2]^T  (rank-2, lies in the triangle plane)
    def outer(x, y): return np.einsum('ni,nj->nij', x, y)
    Sig = _C11*(outer(e1,e1)+outer(e2,e2)) + _C12*(outer(e1,e2)+outer(e2,e1))
    w, Vec = np.linalg.eigh(Sig)                 # batched: w ascending (nt,3), Vec (nt,3,3) columns
    # ensure proper rotations (flip the (near-zero) normal axis where det<0)
    det = np.linalg.det(Vec)
    Vec[det < 0, :, 0] *= -1.0

    std = np.sqrt(np.maximum(w, 0.0))            # [~0(normal), mid, long] per triangle
    s = (cover*std).astype(np.float32)
    inplane = np.maximum(s[:,1], s[:,2])
    s[:,0] = np.maximum(s[:,0], thin_ratio*inplane)   # give the flat normal axis a small thickness
    quat = _R_to_quat(Vec.astype(np.float32))
    n = len(F)
    return dict(count=n, xyz=centroid.astype(np.float32),
                color=np.clip(face_colors,0,1).astype(np.float32),
                opacity=np.full(n, opacity, np.float32), scale=s, quat=quat)

def face_colors_from_vertices(F, vertex_colors):
    """Mean of the triangle's 3 vertex colours."""
    return vertex_colors[F].mean(1)

def decimate_to(mesh, target_faces):
    """Curvature-preserving decimation for count control + adaptivity (fewer tris on flat areas)."""
    if len(mesh.faces) <= target_faces:
        return mesh
    try:
        return mesh.simplify_quadric_decimation(face_count=target_faces)
    except TypeError:
        return mesh.simplify_quadric_decimation(target_faces)     # older trimesh signature
