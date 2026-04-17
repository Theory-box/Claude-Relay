"""
SESSION 01 — Response Tensor: foundational experiments
========================================================

Goal: Probe the hypothesis that weights and activations are two
projections of a single underlying object — the "response tensor" R —
by studying the input-output Jacobian as a function of input.

Definitions used here:
    - Tiny MLP:  y(x) = W2 @ tanh(W1 @ x + b1) + b2
    - Per-input Jacobian: J(x) = dy/dx  (shape: [d_out, d_in])
    - Response tensor:    R = { J(x_i) : x_i in data }  (shape: [N, d_out, d_in])

Tests in this session:
    T1. Activations-as-gradients duality (sanity check with closed form)
    T2. Spectrum / effective rank of R — is it low-dimensional?
    T3. Two networks trained on same task: do they share a response subspace?
    T4. How much of R is captured by its top-k components vs. raw weight count?
"""

import numpy as np
from numpy.linalg import svd, norm

rng = np.random.default_rng(0)

# ------------------------------------------------------------------
# 1. Tiny MLP, manual forward + analytic Jacobians
# ------------------------------------------------------------------
class TinyMLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in),  (d_hid, d_in))
        self.b1 = np.zeros(d_hid)
        self.W2 = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid))
        self.b2 = np.zeros(d_out)

    def forward(self, X):              # X: [N, d_in]
        Z1 = X @ self.W1.T + self.b1   # [N, d_hid]
        H  = np.tanh(Z1)
        Y  = H @ self.W2.T + self.b2
        return Y, H, Z1

    def jacobian_batch(self, X):
        """Analytic dy/dx for every input. Returns [N, d_out, d_in]."""
        _, H, Z1 = self.forward(X)
        sech2 = 1.0 - H**2                    # [N, d_hid], tanh'(z) = 1 - tanh(z)^2
        # J(x) = W2 @ diag(sech2(x)) @ W1
        # Vectorized: J[n] = (W2 * sech2[n]) @ W1
        J = np.einsum('oh,nh,hi->noi', self.W2, sech2, self.W1)
        return J

    def params_vec(self):
        return np.concatenate([self.W1.ravel(), self.b1, self.W2.ravel(), self.b2])

    def n_params(self):
        return self.params_vec().size

    # simple full-batch gradient descent on MSE
    def train(self, X, Y, lr=0.05, steps=2000, verbose=False):
        for t in range(steps):
            Yp, H, Z1 = self.forward(X)
            err = Yp - Y                                # [N, d_out]
            N = X.shape[0]
            gW2 = err.T @ H / N
            gb2 = err.mean(0)
            dH  = err @ self.W2                         # [N, d_hid]
            dZ1 = dH * (1 - H**2)
            gW1 = dZ1.T @ X / N
            gb1 = dZ1.mean(0)
            self.W1 -= lr * gW1; self.b1 -= lr * gb1
            self.W2 -= lr * gW2; self.b2 -= lr * gb2
            if verbose and t % 500 == 0:
                print(f"  step {t:4d}  loss={((err**2).mean()):.5f}")

# ------------------------------------------------------------------
# 2. Generate a simple nonlinear task
# ------------------------------------------------------------------
D_IN, D_HID, D_OUT, N = 12, 64, 6, 800
X = rng.normal(0, 1, (N, D_IN))

# target: fixed nonlinear teacher, so the student must actually learn structure
teacher = TinyMLP(D_IN, 24, D_OUT, seed=7)
Y = teacher.forward(X)[0] + 0.02 * rng.normal(0, 1, (N, D_OUT))

# ------------------------------------------------------------------
# 3. Train two students with different init seeds
# ------------------------------------------------------------------
print("Training student A ...")
net_a = TinyMLP(D_IN, D_HID, D_OUT, seed=11); net_a.train(X, Y, verbose=True)
print("Training student B ...")
net_b = TinyMLP(D_IN, D_HID, D_OUT, seed=42); net_b.train(X, Y, verbose=True)

# verify both reach similar loss
la = ((net_a.forward(X)[0] - Y)**2).mean()
lb = ((net_b.forward(X)[0] - Y)**2).mean()
print(f"\nFinal loss: A={la:.5f}  B={lb:.5f}")
print(f"Param count per net: {net_a.n_params()}")

# function-space agreement (they solved the same task, so should match)
Ya = net_a.forward(X)[0]
Yb = net_b.forward(X)[0]
print(f"Function-space RMS diff (A vs B outputs): {np.sqrt(((Ya-Yb)**2).mean()):.5f}")

# ------------------------------------------------------------------
# T1. Activations-as-gradients duality (numeric check)
# ------------------------------------------------------------------
# Claim: for the last linear layer y = W2 h + b2,
#        d y_i / d W2_ij = h_j
# i.e. the hidden activation h IS the gradient of the output w.r.t. the
# weight feeding into it.
x0 = X[:1]
Y0, H0, _ = net_a.forward(x0)
# finite-diff check on one entry
eps = 1e-6
W2_save = net_a.W2.copy()
i, j = 2, 17
net_a.W2[i, j] += eps
Y1 = net_a.forward(x0)[0]
net_a.W2 = W2_save
grad_fd = (Y1[0, i] - Y0[0, i]) / eps
print("\n[T1] activations-as-gradients duality:")
print(f"     h[j]          = {H0[0, j]:.6f}")
print(f"     dy_i/dW2_ij   = {grad_fd:.6f}   (finite-diff)")
print(f"     match: {np.isclose(H0[0, j], grad_fd, atol=1e-4)}")

# ------------------------------------------------------------------
# T2. Spectrum of the response tensor
# ------------------------------------------------------------------
Ra = net_a.jacobian_batch(X)              # [N, d_out, d_in]
Rb = net_b.jacobian_batch(X)
Ra_flat = Ra.reshape(N, D_OUT * D_IN)     # [N, 72]
Rb_flat = Rb.reshape(N, D_OUT * D_IN)

sa = svd(Ra_flat, compute_uv=False)
sb = svd(Rb_flat, compute_uv=False)

def eff_rank(s):
    p = s / s.sum()
    p = p[p > 1e-12]
    H = -(p * np.log(p)).sum()
    return float(np.exp(H))

print("\n[T2] Response tensor spectrum:")
print(f"     R shape        : {Ra.shape}  -> flat {Ra_flat.shape}")
print(f"     top-10 sing (A): {np.round(sa[:10], 3)}")
print(f"     top-10 sing (B): {np.round(sb[:10], 3)}")
print(f"     effective rank : A={eff_rank(sa):.2f}   B={eff_rank(sb):.2f}   of {sa.size}")
# cumulative variance capture
cum_a = np.cumsum(sa**2) / np.sum(sa**2)
k90 = int(np.searchsorted(cum_a, 0.90)) + 1
k99 = int(np.searchsorted(cum_a, 0.99)) + 1
print(f"     k for 90% energy (A): {k90}   / 99%: {k99}   / full dim: {sa.size}")

# ------------------------------------------------------------------
# T3. Do two independently-trained networks share a response subspace?
# ------------------------------------------------------------------
# Use principal angles between top-k right-singular subspaces of Ra_flat, Rb_flat.
# Each row of Rx_flat is a flattened Jacobian J(x_i), so the row-space tells
# us "what shapes of J does this network produce across the data."
Ua, Sa, Vta = svd(Ra_flat, full_matrices=False)
Ub, Sb, Vtb = svd(Rb_flat, full_matrices=False)

print("\n[T3] Response subspace overlap (principal angles):")
for k in [2, 5, 10, 20, min(40, Vta.shape[0])]:
    Va_k = Vta[:k].T          # [d_out*d_in, k]
    Vb_k = Vtb[:k].T
    M = Va_k.T @ Vb_k
    ang = svd(M, compute_uv=False)  # cosines of principal angles
    print(f"     k={k:3d}:  mean cos = {ang.mean():.4f}   min cos = {ang.min():.4f}")

# ------------------------------------------------------------------
# T4. How much of R's information is captured by k components vs params?
# ------------------------------------------------------------------
# If a rank-k truncation of R faithfully reproduces the function's input-output
# behavior (via J as a linear local approximation), then the "functional content"
# of the network is ~k * (d_out + d_in) numbers, which may be << total params.
print("\n[T4] Information compression ratio:")
print(f"     Raw params per net        : {net_a.n_params()}")
print(f"     Numbers in full R (A)     : {Ra.size}   ({N}×{D_OUT}×{D_IN})")
for k in [5, 10, 20]:
    # storing k basis vecs in R-flat space + k coeffs per sample
    compressed = k * (D_OUT * D_IN) + k * N
    captured = cum_a[k-1]
    print(f"     rank-{k:2d} of R: {compressed:5d} numbers,  energy captured = {captured*100:5.2f}%")
