"""
SESSION 01 — follow-up: split R into mean Jacobian + residual.

If two networks learn the same function, the *average* Jacobian
(averaged over inputs) should agree. The *residual* J(x) - E[J(x)]
carries the input-dependent sensitivity pattern.  It's that residual
where the network-specific structure lives.

Hypothesis: residuals will disagree sharply between nets even when
mean Jacobians agree.  That would mean R has a functional core + a
network-specific fingerprint.
"""
import numpy as np
from numpy.linalg import svd
rng = np.random.default_rng(0)

# --- reuse the MLP class definition from the other file (inlined for standalone run) ---
class TinyMLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in),  (d_hid, d_in))
        self.b1 = np.zeros(d_hid)
        self.W2 = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid))
        self.b2 = np.zeros(d_out)
    def forward(self, X):
        Z1 = X @ self.W1.T + self.b1
        H  = np.tanh(Z1)
        Y  = H @ self.W2.T + self.b2
        return Y, H, Z1
    def jacobian_batch(self, X):
        _, H, _ = self.forward(X)
        sech2 = 1.0 - H**2
        return np.einsum('oh,nh,hi->noi', self.W2, sech2, self.W1)
    def train(self, X, Y, lr=0.05, steps=2000):
        for t in range(steps):
            Yp, H, _ = self.forward(X)
            err = Yp - Y
            N = X.shape[0]
            gW2 = err.T @ H / N; gb2 = err.mean(0)
            dH  = err @ self.W2; dZ1 = dH * (1 - H**2)
            gW1 = dZ1.T @ X / N; gb1 = dZ1.mean(0)
            self.W1 -= lr*gW1; self.b1 -= lr*gb1
            self.W2 -= lr*gW2; self.b2 -= lr*gb2

D_IN, D_HID, D_OUT, N = 12, 64, 6, 800
X = rng.normal(0, 1, (N, D_IN))
teacher = TinyMLP(D_IN, 24, D_OUT, seed=7)
Y = teacher.forward(X)[0] + 0.02 * rng.normal(0, 1, (N, D_OUT))

net_a = TinyMLP(D_IN, D_HID, D_OUT, seed=11); net_a.train(X, Y)
net_b = TinyMLP(D_IN, D_HID, D_OUT, seed=42); net_b.train(X, Y)

Ra = net_a.jacobian_batch(X)
Rb = net_b.jacobian_batch(X)

# ------------------------------------------------------------------
# Mean Jacobian (averaged over inputs) — a single [d_out, d_in] matrix
# ------------------------------------------------------------------
Ja_mean = Ra.mean(axis=0)
Jb_mean = Rb.mean(axis=0)

# relative Frobenius distance
def rel_frob(A, B):
    return np.linalg.norm(A - B) / (0.5 * (np.linalg.norm(A) + np.linalg.norm(B)))

print("Mean Jacobian comparison:")
print(f"  ||Ja_mean||        = {np.linalg.norm(Ja_mean):.4f}")
print(f"  ||Jb_mean||        = {np.linalg.norm(Jb_mean):.4f}")
print(f"  rel Frob distance  = {rel_frob(Ja_mean, Jb_mean):.4f}")
# also cosine between flattened mean Jacobians
va, vb = Ja_mean.ravel(), Jb_mean.ravel()
print(f"  cosine(J_a, J_b)   = {va @ vb / (np.linalg.norm(va)*np.linalg.norm(vb)):.4f}")

# ------------------------------------------------------------------
# Residual tensor: R - mean_J
# ------------------------------------------------------------------
Ra_res = Ra - Ja_mean    # broadcasting over N
Rb_res = Rb - Jb_mean
print(f"\nEnergy partition for net A:")
total_E   = np.sum(Ra**2)
mean_E    = N * np.sum(Ja_mean**2)     # since each of N copies contributes |Ja_mean|^2
resid_E   = np.sum(Ra_res**2)
print(f"  total ||R||^2      = {total_E:.2f}")
print(f"  mean-part  (N|Ja_mean|^2)    = {mean_E:.2f}  ({100*mean_E/total_E:.1f}%)")
print(f"  residual-part               = {resid_E:.2f}  ({100*resid_E/total_E:.1f}%)")

# ------------------------------------------------------------------
# Compare the *residual* subspaces — this is where the
# network-specific signature should live, if it exists.
# ------------------------------------------------------------------
Ra_res_flat = Ra_res.reshape(N, D_OUT * D_IN)
Rb_res_flat = Rb_res.reshape(N, D_OUT * D_IN)
_, Sa_r, Vta_r = svd(Ra_res_flat, full_matrices=False)
_, Sb_r, Vtb_r = svd(Rb_res_flat, full_matrices=False)
print(f"\nResidual spectrum (top 10):")
print(f"  A: {np.round(Sa_r[:10],3)}")
print(f"  B: {np.round(Sb_r[:10],3)}")

print("\nResidual subspace overlap (principal angles):")
for k in [2, 5, 10, 20, 40]:
    M = Vta_r[:k] @ Vtb_r[:k].T
    ang = svd(M, compute_uv=False)
    print(f"  k={k:3d}:  mean cos = {ang.mean():.4f}   min cos = {ang.min():.4f}")

# ------------------------------------------------------------------
# Sanity: if we project each net's *full* R into the OTHER's top
# response subspace, how much energy is preserved?
# If R were purely function-determined, this would be ~100%.
# ------------------------------------------------------------------
def proj_energy(R_flat, V_basis):
    """Fraction of R's Frobenius^2 energy captured by projecting onto V_basis."""
    proj = R_flat @ V_basis.T @ V_basis
    return np.sum(proj**2) / np.sum(R_flat**2)

print("\nCross-projection: fraction of A's residual energy captured by B's basis")
for k in [5, 10, 20, 40, 60]:
    f = proj_energy(Ra_res_flat, Vtb_r[:k])
    print(f"  top-{k:3d} of B captures  {100*f:5.2f}%  of A's residual energy")
