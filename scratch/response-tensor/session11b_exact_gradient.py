"""
SESSION 11B — exact gradient output matching

The 22-25% "ceiling" from sessions 9-10 used ES-estimated signature gradients.
Full-dataset distillation (exact gradient on A's outputs over 600 training points)
gets +37.3%. So the gap between K=1 signatures (22%) and full distillation (37%) is
15 points. How much of that gap is:

   (a) probe count            — more points = more info
   (b) gradient quality       — ES noise artifact of our method
   (c) loss weighting         — how strongly to weight probes vs task

This session: replace ES-gradient with EXACT gradient (treat probes as an extra
training batch). Compare at K=1, 4, 16, 64, 600.
"""
import numpy as np
from numpy.linalg import norm

class MLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in), (d_hid, d_in)); self.b1 = np.zeros(d_hid)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid)); self.bo = np.zeros(d_out)
        self.d_in, self.d_hid, self.d_out = d_in, d_hid, d_out
    def forward(self, X):
        Z1 = X @ self.W1.T + self.b1; H = np.tanh(Z1); return H @ self.Wo.T + self.bo, H
    def params(self): return [self.W1, self.b1, self.Wo, self.bo]

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

def train_with_exact_sig(net, X, Y, probes, targets,
                         lam=5.0, steps=2000, lr=0.05, sig_every=3):
    """Training with exact-gradient signature matching.
    Treat (probes, targets) as extra mini-batch trained every sig_every steps."""
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if t % sig_every == 0 and lam > 0:
            apply(net, task_grad(net, probes, targets), lr * lam)
    return net

def train_standard(net, X, Y, steps=2000, lr=0.05):
    for _ in range(steps):
        apply(net, task_grad(net, X, Y), lr)
    return net

def func_rms(a, b, X): return float(np.sqrt(((a.forward(X)[0] - b.forward(X)[0])**2).mean()))
def mse(Yp, Y): return float(((Yp - Y)**2).mean())

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------
X, Y = task_teacher()
A = train_standard(MLP(10, 20, 4, seed=1), X, Y)
C = train_standard(MLP(10, 20, 4, seed=77), X, Y)
BASELINE = func_rms(A, C, X)
print(f"Baseline indep C: ||f_A - f_C|| = {BASELINE:.4f}\n")

B_seeds = [55, 66, 88]
N_PROBE_SAMPLES = 3

# ==================================================================
# K sweep with exact-gradient output matching
# ==================================================================
print("="*78)
print("Exact-gradient output matching — K sweep")
print("  Signature = A's outputs on K on-manifold probes, exact backprop")
print("="*78)
print(f"{'K':>5s}{'lam':>6s}{'sig dim':>10s}{'||f_A - f_B||':>18s}{'recovery':>14s}")
print("-"*78)

# Choose lambda per K: want similar effective sig-gradient influence
# If lam * K ≈ const, then roughly equal total probe-influence per gradient step
def pick_lam(K):
    if K == 600: return 1.0           # full dataset: use equal weight to task
    # For fewer probes, weight them more heavily to have comparable impact
    return max(0.5, 5.0)

results_exact = {}
K_values = [1, 2, 4, 8, 16, 64, 600]
for K in K_values:
    all_dists = []
    lam = pick_lam(K)
    for ps in range(N_PROBE_SAMPLES):
        rng_p = np.random.default_rng(700 + ps * 13 + K)
        if K < X.shape[0]:
            idx = rng_p.choice(X.shape[0], K, replace=False)
            probes = X[idx]
        else:
            probes = X                # full dataset
        targets = A.forward(probes)[0]   # A's outputs as soft targets
        for s in B_seeds:
            B = train_with_exact_sig(MLP(10, 20, 4, seed=s), X, Y,
                                     probes, targets, lam=lam)
            all_dists.append(func_rms(A, B, X))
    mean_d = np.mean(all_dists); std_d = np.std(all_dists)
    imp = 100 * (1 - mean_d / BASELINE)
    sig_dim = K * 4
    results_exact[K] = (mean_d, std_d, imp)
    print(f"{K:>5d}{lam:>6.1f}{sig_dim:>10d}"
          f"{mean_d:12.4f} ± {std_d:.4f}{imp:+10.1f}%")

# ==================================================================
# Compare to ES-gradient results for same K
# Re-run output matching with ES at matching K (same as sessions 9-10)
# ==================================================================
def sig_grad_es(net, probes, target, rng, eps=1e-3, n_dirs=2):
    base = [p.copy() for p in net.params()]
    shapes = [p.shape for p in base]; sizes = [p.size for p in base]
    total = sum(sizes); accum = [np.zeros_like(p) for p in base]
    for _ in range(n_dirs):
        df = rng.normal(0, 1, total); df /= (np.linalg.norm(df)+1e-12)
        deltas = []; i = 0
        for sh, sz in zip(shapes, sizes):
            deltas.append(df[i:i+sz].reshape(sh)); i += sz
        for k in range(len(base)): net.params()[k][:] = base[k] + eps*deltas[k]
        lp = float(np.sum((net.forward(probes)[0].ravel() - target)**2))
        for k in range(len(base)): net.params()[k][:] = base[k] - eps*deltas[k]
        lm = float(np.sum((net.forward(probes)[0].ravel() - target)**2))
        for k in range(len(base)): net.params()[k][:] = base[k]
        c = (lp - lm)/(2*eps)
        for k in range(len(accum)): accum[k] += c * deltas[k]
    return [a/n_dirs for a in accum]

def train_with_es_sig(net, X, Y, probes, target_flat, lam=5.0, steps=2000,
                      lr=0.05, sig_lr=0.05, sig_every=3, seed=0):
    rng = np.random.default_rng(seed)
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if t % sig_every == 0 and lam > 0:
            apply(net, sig_grad_es(net, probes, target_flat, rng), sig_lr * lam)
    return net

print("\n" + "="*78)
print("Compare: same K, EXACT gradient vs ES gradient")
print("="*78)
print(f"{'K':>5s}{'exact':>12s}{'ES':>12s}{'gap':>12s}")
print("-"*78)

for K in [1, 4, 16]:
    # already have exact
    exact_imp = results_exact[K][2]
    # ES version
    all_es = []
    for ps in range(N_PROBE_SAMPLES):
        rng_p = np.random.default_rng(800 + ps * 13 + K)
        idx = rng_p.choice(X.shape[0], K, replace=False)
        probes = X[idx]
        target_flat = A.forward(probes)[0].ravel()
        for s in B_seeds:
            B = train_with_es_sig(MLP(10, 20, 4, seed=s), X, Y,
                                  probes, target_flat, lam=5.0, seed=s)
            all_es.append(func_rms(A, B, X))
    es_d = np.mean(all_es)
    es_imp = 100 * (1 - es_d / BASELINE)
    print(f"{K:>5d}{exact_imp:+10.1f}%{es_imp:+10.1f}%{exact_imp - es_imp:+10.1f}%")

# ==================================================================
# Final summary: compression curve with exact gradients
# ==================================================================
print("\n" + "="*78)
print("FINAL: compression curve with exact gradients")
print("="*78)
print(f"  Random init baseline (untrained B):   ~0%")
print(f"  Independent training (C):              0% (reference)")
for K in K_values:
    mean_d, std_d, imp = results_exact[K]
    bar = "▓" * max(0, int(imp/2))
    print(f"  K={K:>4d} exact-gradient output match: {imp:+6.1f}%  {bar}")

best_K = max(results_exact.keys(), key=lambda k: results_exact[k][2])
best_imp = results_exact[best_K][2]
print(f"\n  Best: K={best_K} → {best_imp:+.1f}% recovery")
