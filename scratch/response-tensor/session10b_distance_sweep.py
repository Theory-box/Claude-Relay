"""
SESSION 10B — probe distance sweep

Hypothesis from session 10: optimal probes are NEAR the data manifold, not far
off. The sweet spot is probes close enough to couple to on-manifold behavior
but off enough to carry discriminative signal.

Protocol: generate K=4 probes at controlled off-manifold distances d in
[0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0]. Measure functional recovery at each d,
averaged over 3 B-training seeds.

Data manifold is the 3-dim subspace spanned by B_embed from task_teacher.
"""
import numpy as np
from numpy.linalg import svd, norm

class MLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in), (d_hid, d_in)); self.b1 = np.zeros(d_hid)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid)); self.bo = np.zeros(d_out)
        self.d_in, self.d_hid, self.d_out = d_in, d_hid, d_out
    def forward(self, X):
        Z1 = X @ self.W1.T + self.b1; H = np.tanh(Z1); return H @ self.Wo.T + self.bo, H
    def params(self): return [self.W1, self.b1, self.Wo, self.bo]
    def set_params(self, ps): self.W1, self.b1, self.Wo, self.bo = ps[0], ps[1], ps[2], ps[3]
    def snapshot(self): return [p.copy() for p in self.params()]

def task_teacher(seed=0, N=600):
    r = np.random.default_rng(seed)
    Wt1 = r.normal(0, 1/np.sqrt(10), (16, 10)); bt1 = np.zeros(16)
    Wt2 = r.normal(0, 1/np.sqrt(16), (4, 16)); bt2 = np.zeros(4)
    B = r.normal(0, 1, (3, 10))
    X = r.normal(0, 1, (N, 3)) @ B
    Y = np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2 + 0.02*r.normal(0, 1, (N, 4))
    return X, Y

def task_grad(net, X, Y):
    Yp, H = net.forward(X); err = Yp - Y; N = X.shape[0]
    gWo = err.T @ H / N; gbo = err.mean(0)
    dH = err @ net.Wo; dZ1 = dH * (1 - H**2)
    gW1 = dZ1.T @ X / N; gb1 = dZ1.mean(0)
    return [gW1, gb1, gWo, gbo]

def apply(net, grads, lr):
    for p, g in zip(net.params(), grads): p -= lr * g

def sig_grad_es(net, probes, target, rng, eps=1e-3, n_dirs=2):
    base = net.snapshot()
    shapes = [p.shape for p in base]; sizes = [p.size for p in base]
    total = sum(sizes); accum = [np.zeros_like(p) for p in base]
    for _ in range(n_dirs):
        df = rng.normal(0, 1, total); df /= (np.linalg.norm(df)+1e-12)
        deltas = []; i = 0
        for sh, sz in zip(shapes, sizes):
            deltas.append(df[i:i+sz].reshape(sh)); i += sz
        net.set_params([b+eps*d for b,d in zip(base, deltas)])
        lp = float(np.sum((net.forward(probes)[0].ravel() - target)**2))
        net.set_params([b-eps*d for b,d in zip(base, deltas)])
        lm = float(np.sum((net.forward(probes)[0].ravel() - target)**2))
        net.set_params(base)
        c = (lp - lm)/(2*eps)
        for k in range(len(accum)): accum[k] += c * deltas[k]
    return [a/n_dirs for a in accum]

def train_with_probes(net, X, Y, probes, target, lam=5.0, steps=2000,
                      lr=0.05, sig_lr=0.05, sig_every=3, seed=0):
    rng = np.random.default_rng(seed)
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if probes is not None and t % sig_every == 0 and lam > 0:
            apply(net, sig_grad_es(net, probes, target, rng), sig_lr * lam)
    return net

def train_standard(net, X, Y, steps=2000, lr=0.05):
    for _ in range(steps):
        apply(net, task_grad(net, X, Y), lr)
    return net

def func_rms(a, b, X): return float(np.sqrt(((a.forward(X)[0] - b.forward(X)[0])**2).mean()))
def mse(Yp, Y): return float(((Yp - Y)**2).mean())

# ------------------------------------------------------------------
# Find data manifold subspace (3-dim in 10-dim input space)
# ------------------------------------------------------------------
X, Y = task_teacher()
# SVD of X gives manifold basis
_, _, Vt = svd(X, full_matrices=False)
U_on = Vt[:3]          # [3, 10]  rows span the data's 3-d subspace
U_off = Vt[3:]         # [7, 10]  rows span the orthogonal complement

def make_probe_at_distance(d, rng):
    """Generate a probe at off-manifold distance d.
    On-manifold component: random in span(U_on) with magnitude ~1 (typical data)
    Off-manifold component: random in span(U_off) with magnitude d.
    """
    on_coeffs  = rng.normal(0, 1, 3)       # on-manifold coords
    on_coeffs  /= (np.linalg.norm(on_coeffs)+1e-12)  # unit magnitude
    on_coeffs  *= np.sqrt(3)                # typical on-manifold norm ~sqrt(3)

    off_coeffs = rng.normal(0, 1, 7)
    off_coeffs /= (np.linalg.norm(off_coeffs)+1e-12)
    off_coeffs *= d

    on_part  = on_coeffs @ U_on             # [10]
    off_part = off_coeffs @ U_off
    return on_part + off_part

# ------------------------------------------------------------------
# Setup anchor
# ------------------------------------------------------------------
A = train_standard(MLP(10, 20, 4, seed=1), X, Y)
C = train_standard(MLP(10, 20, 4, seed=77), X, Y)
BASELINE = func_rms(A, C, X)
print(f"Anchor A task loss: {mse(A.forward(X)[0], Y):.5f}")
print(f"Baseline indep C:   ||f_A - f_C|| = {BASELINE:.4f}\n")

# Verify the subspace projection logic
test_probe_0 = make_probe_at_distance(0.0, np.random.default_rng(0))
off_part_norm = np.linalg.norm(test_probe_0 - U_on.T @ (U_on @ test_probe_0))
print(f"  sanity check: d=0 probe has off-manifold norm {off_part_norm:.4f} (should be ~0)")
test_probe_3 = make_probe_at_distance(3.0, np.random.default_rng(0))
off_part_norm = np.linalg.norm(test_probe_3 - U_on.T @ (U_on @ test_probe_3))
print(f"  sanity check: d=3 probe has off-manifold norm {off_part_norm:.4f} (should be ~3)\n")

# ------------------------------------------------------------------
# Distance sweep
# ------------------------------------------------------------------
K = 4
B_seeds = [55, 66, 88]
distances = [0.0, 0.3, 0.6, 1.0, 1.5, 2.5, 4.0, 6.0]
N_PROBE_SAMPLES = 3      # sample each distance 3 times with different probe draws

print("="*78)
print(f"Distance sweep (K={K}, averaged over {N_PROBE_SAMPLES} probe samples "
      f"× {len(B_seeds)} B seeds)")
print("="*78)
print(f"{'distance':>10s}{'mean ||f_A-f_B||':>20s}{'std':>10s}{'vs baseline':>15s}")
print("-"*78)

results = []
for d in distances:
    all_dists = []
    for ps in range(N_PROBE_SAMPLES):
        rng_probe = np.random.default_rng(100 + ps * 13 + int(d*100))
        probes = np.stack([make_probe_at_distance(d, rng_probe) for _ in range(K)])
        target = A.forward(probes)[0].ravel()
        for s in B_seeds:
            B = train_with_probes(MLP(10, 20, 4, seed=s), X, Y,
                                  probes=probes, target=target, seed=s)
            all_dists.append(func_rms(A, B, X))
    mean_d = np.mean(all_dists); std_d = np.std(all_dists)
    imp = 100 * (1 - mean_d / BASELINE)
    results.append((d, mean_d, std_d, imp))
    bar = "▓" * max(0, int(imp/2))
    print(f"{d:10.2f}{mean_d:14.4f} ± {std_d:.4f}{imp:+12.1f}% {bar}")

# find optimal distance
best = min(results, key=lambda r: r[1])
print(f"\n  Best distance: d={best[0]:.2f}  (recovery {best[3]:+.1f}%)")

# ------------------------------------------------------------------
# Comparison to standard isotropic Gaussian probes (what random=N(0,I) does)
# In 10-dim, E[||p||] = sqrt(10). Projected onto 3d/7d split:
#   E[on-part norm]  = sqrt(3) ≈ 1.73
#   E[off-part norm] = sqrt(7) ≈ 2.65
# So random-N(0,I) probes are at effective distance ~2.65 by our measure
# ------------------------------------------------------------------
print("\n  For reference: standard N(0,I) random probes in 10-d have ~2.65 off-manifold distance")

# ------------------------------------------------------------------
# Can we push past with an even better selection within the best distance?
# At the optimal distance, use max-disagreement among same-distance candidates
# ------------------------------------------------------------------
print("\n" + "="*78)
print(f"Refinement: at optimal distance d={best[0]:.2f}, pick max-disagreement probes")
print("="*78)

# Build candidate pool at optimal distance
best_d = best[0]
rng_cand = np.random.default_rng(2025)
N_CANDIDATES = 500
candidates = np.stack([make_probe_at_distance(best_d, rng_cand)
                        for _ in range(N_CANDIDATES)])

# Train 5 nets for disagreement scoring
siblings = [train_standard(MLP(10, 20, 4, seed=s), X, Y) for s in [2,3,4,5,6]]
all_nets = [A] + siblings
outs = np.stack([n.forward(candidates)[0] for n in all_nets])
disagreement = outs.var(axis=0).sum(axis=-1)

# Pick top-K disagreement within this distance band
probes_refined = candidates[np.argsort(-disagreement)[:K]]
target_refined = A.forward(probes_refined)[0].ravel()

all_dists = []
for s in B_seeds:
    B = train_with_probes(MLP(10, 20, 4, seed=s), X, Y,
                          probes=probes_refined, target=target_refined, seed=s)
    all_dists.append(func_rms(A, B, X))
mean_refined = np.mean(all_dists); std_refined = np.std(all_dists)
imp_refined = 100 * (1 - mean_refined / BASELINE)
print(f"  distance-optimal + max-disagreement: "
      f"||f_A-f_B|| = {mean_refined:.4f} ± {std_refined:.4f}  ({imp_refined:+.1f}%)")

# Summary
print("\n" + "="*78)
print("FINAL RESULTS")
print("="*78)
print(f"  Random N(0,I) probes (session 10 baseline) : +19.2%")
print(f"  Best distance ({best[0]:.2f})               : {best[3]:+.1f}%")
print(f"  Best distance + max-disagreement refinement: {imp_refined:+.1f}%")
if imp_refined > best[3]:
    print(f"\n  Combined approach improved on pure distance by {imp_refined - best[3]:+.1f}%")
else:
    print(f"\n  Combined approach did not improve; distance alone is sufficient")
