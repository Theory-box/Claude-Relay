"""
SESSION 10C — on-manifold K sweep

On-manifold probes won at K=4 (+24.6%). Does scaling K help or does the
optimization collapse we saw in session 9 (K>=16 catastrophic) still apply?
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

X, Y = task_teacher()
A = train_standard(MLP(10, 20, 4, seed=1), X, Y)
C = train_standard(MLP(10, 20, 4, seed=77), X, Y)
BASELINE = func_rms(A, C, X)
print(f"Baseline indep C: ||f_A - f_C|| = {BASELINE:.4f}\n")

# On-manifold probe generator (d=0): sample random points in the 3-d data subspace
_, _, Vt = svd(X, full_matrices=False)
U_on = Vt[:3]

def make_on_manifold_probe(rng):
    # sample in the 3-d data coordinates with the empirical distribution of data
    coeffs = rng.normal(0, 1, 3)
    coeffs *= np.sqrt(3)   # typical magnitude
    return coeffs @ U_on

# Alternative: just sample directly from training X (truly on-manifold)
def pick_from_X(rng, k):
    idx = rng.choice(X.shape[0], k, replace=False)
    return X[idx]

B_seeds = [55, 66, 88]
N_PROBE_SAMPLES = 3

print("="*78)
print("K sweep at d=0 (on-manifold probes, two variants)")
print("="*78)
print(f"{'K':>3s}  {'synth d=0':>20s}  {'from training X':>22s}")
print("-"*78)

for K in [1, 2, 4, 8, 12, 16, 24]:
    # Variant 1: synthetic on-manifold (d=0 exactly, sampled in subspace)
    dists_synth = []
    for ps in range(N_PROBE_SAMPLES):
        rng_p = np.random.default_rng(200 + ps * 17 + K)
        probes = np.stack([make_on_manifold_probe(rng_p) for _ in range(K)])
        target = A.forward(probes)[0].ravel()
        for s in B_seeds:
            B = train_with_probes(MLP(10, 20, 4, seed=s), X, Y,
                                  probes=probes, target=target, seed=s)
            dists_synth.append(func_rms(A, B, X))
    mean_s = np.mean(dists_synth)
    imp_s = 100 * (1 - mean_s / BASELINE)

    # Variant 2: picked from training data (truly on-manifold, with noise)
    dists_X = []
    for ps in range(N_PROBE_SAMPLES):
        rng_p = np.random.default_rng(300 + ps * 19 + K)
        probes = pick_from_X(rng_p, K)
        target = A.forward(probes)[0].ravel()
        for s in B_seeds:
            B = train_with_probes(MLP(10, 20, 4, seed=s), X, Y,
                                  probes=probes, target=target, seed=s)
            dists_X.append(func_rms(A, B, X))
    mean_x = np.mean(dists_X)
    imp_x = 100 * (1 - mean_x / BASELINE)

    print(f"{K:>3d}  {mean_s:.4f} ({imp_s:+5.1f}%)   {mean_x:.4f} ({imp_x:+5.1f}%)")
