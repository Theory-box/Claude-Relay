"""
adaptive_fit.py — fit gaussian splats to a mesh surface in 3D (no images, no AI, no training).

Idea: densely sample the surface -> adaptively partition the points into patches where each patch
is well-approximated by ONE gaussian (flat + uniform-colour regions become few big anisotropic
splats; curved / detailed / colour-varying regions get subdivided into many small ones) -> fit each
patch with PCA (mean=centre, covariance=ellipsoid, mean albedo=colour). Closed-form, deterministic.

Partitioning is a max-error-first priority queue: start with one patch (all points), repeatedly split
the worst-fitting patch until we hit the target splat count -> exact budget control, detail where it
matters. This is the classic adaptive-approximation approach, not gradient descent.
"""
import numpy as np, heapq, itertools

# error weights: A=non-flatness(curvature), B=colour variance, G=size (keeps big flat patches from
# becoming one giant blob), all times point-count so large important regions split first.
def _pca(P):
    mean = P.mean(0); X = P - mean
    cov = (X.T @ X) / max(len(P), 1)
    w, V = np.linalg.eigh(cov)            # ascending: w[0]<=w[1]<=w[2]; V[:,i] eigenvector
    return mean, np.maximum(w, 0.0), V

def _cell(P, C):
    mean, w, V = _pca(P)
    cstd = float(C.std(0).mean())
    err = len(P) * (3.0*np.sqrt(w[0]) + 1.2*cstd + 0.35*np.sqrt(w[2]))
    return err, (mean, w, V, C.mean(0))

def adaptive_fit(P, C, target, min_points=8, cover=2.0, thin_min=0.15):
    """P:(M,3) points, C:(M,3) colours. -> splat dict of ~`target` anisotropic gaussians."""
    P = P.astype(np.float64); cnt = itertools.count()
    heap = []
    def push(idx):
        if len(idx) < 1: return
        err, fit = _cell(P[idx], C[idx]); heapq.heappush(heap, (-err, next(cnt), idx, fit))
    push(np.arange(len(P)))
    leaves = []
    while len(heap) + len(leaves) < target and heap:
        _, _, idx, fit = heapq.heappop(heap)
        if len(idx) <= min_points:
            leaves.append((idx, fit)); continue
        mean, w, V, _ = fit
        axis = V[:, 2]                                   # split along longest extent
        proj = (P[idx] - mean) @ axis; med = np.median(proj)
        L = idx[proj <= med]; R = idx[proj > med]
        if len(L) == 0 or len(R) == 0:
            leaves.append((idx, fit)); continue
        push(L); push(R)
    cells = leaves + [(idx, fit) for (_, _, idx, fit) in heap]

    # build gaussians from each patch's covariance
    n = len(cells)
    xyz = np.empty((n,3),np.float32); col = np.empty((n,3),np.float32)
    scale = np.empty((n,3),np.float32); quat = np.empty((n,4),np.float32)
    for i,(idx,fit) in enumerate(cells):
        mean, w, V, c = fit
        R = V.copy()
        if np.linalg.det(R) < 0: R[:,0] = -R[:,0]        # ensure proper rotation
        std = np.sqrt(np.maximum(w,1e-12))
        s = cover*std
        s[0] = max(s[0], thin_min*max(s[1],s[2]))        # keep a minimum thickness (normal axis)
        xyz[i]=mean; col[i]=np.clip(c,0,1); scale[i]=s
        quat[i]=_R_to_quat(R)
    return dict(count=n, xyz=xyz, color=col, opacity=np.full(n,0.9,np.float32),
                scale=scale, quat=quat)

def _R_to_quat(R):
    m=R; tr=m[0,0]+m[1,1]+m[2,2]
    if tr>0:
        S=np.sqrt(tr+1.0)*2; w=0.25*S; x=(m[2,1]-m[1,2])/S; y=(m[0,2]-m[2,0])/S; z=(m[1,0]-m[0,1])/S
    elif m[0,0]>=m[1,1] and m[0,0]>=m[2,2]:
        S=np.sqrt(1.0+m[0,0]-m[1,1]-m[2,2])*2; w=(m[2,1]-m[1,2])/S; x=0.25*S; y=(m[0,1]+m[1,0])/S; z=(m[0,2]+m[2,0])/S
    elif m[1,1]>=m[2,2]:
        S=np.sqrt(1.0+m[1,1]-m[0,0]-m[2,2])*2; w=(m[0,2]-m[2,0])/S; x=(m[0,1]+m[1,0])/S; y=0.25*S; z=(m[1,2]+m[2,1])/S
    else:
        S=np.sqrt(1.0+m[2,2]-m[0,0]-m[1,1])*2; w=(m[1,0]-m[0,1])/S; x=(m[0,2]+m[2,0])/S; y=(m[1,2]+m[2,1])/S; z=0.25*S
    q=np.array([w,x,y,z],np.float32); return q/(np.linalg.norm(q)+1e-9)
