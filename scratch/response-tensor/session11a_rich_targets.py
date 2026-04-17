"""
SESSION 11A — richer compression targets

Can we break the ~25% recovery ceiling by matching richer targets than f_A(x)?

Signature types (all at on-manifold probes):
  1. OUTPUT   f(x)            4 numbers per probe (baseline, +22-24%)
  2. JACOBIAN J(x) = df/dx    40 numbers per probe (10x richer)
  3. HIDDEN   H(x)            20 numbers per probe (internal repr)
  4. COMBINED f + J + H       64 numbers per probe (everything)

Plus: match on FULL DATASET instead of K probes (dark knowledge distillation,
known strong baseline from Hinton 2015, included for reference).

Comparison at K=1 and K=4.
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
    def jacobian_at(self, X):
        """Return [N, d_out, d_in] array of Jacobians at each row of X."""
        _, H = self.forward(X); sech2 = 1.0 - H**2
        return np.einsum('oh,nh,hi->noi', self.Wo, sech2, self.W1)
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

# ------------------------------------------------------------------
# Signature functions — various richness levels
# ------------------------------------------------------------------
def sig_output(net, probes):
    return net.forward(probes)[0].ravel()

def sig_jacobian(net, probes):
    return net.jacobian_at(probes).ravel()

def sig_hidden(net, probes):
    _, H = net.forward(probes)
    return H.ravel()

def sig_combined(net, probes):
    return np.concatenate([sig_output(net, probes),
                           sig_jacobian(net, probes),
                           sig_hidden(net, probes)])

SIG_FNS = {
    'output':   (sig_output,   4),    # dims per probe
    'hidden':   (sig_hidden,  20),
    'jacobian': (sig_jacobian, 40),
    'combined': (sig_combined, 64),
}

# ------------------------------------------------------------------
# ES signature gradient (same as before but uses generic sig_fn)
# ------------------------------------------------------------------
def sig_grad_es(net, probes, target, sig_fn, rng, eps=1e-3, n_dirs=2):
    base = net.snapshot()
    shapes = [p.shape for p in base]; sizes = [p.size for p in base]
    total = sum(sizes); accum = [np.zeros_like(p) for p in base]
    for _ in range(n_dirs):
        df = rng.normal(0, 1, total); df /= (np.linalg.norm(df)+1e-12)
        deltas = []; i = 0
        for sh, sz in zip(shapes, sizes):
            deltas.append(df[i:i+sz].reshape(sh)); i += sz
        net.set_params([b+eps*d for b,d in zip(base, deltas)])
        lp = float(np.sum((sig_fn(net, probes) - target)**2))
        net.set_params([b-eps*d for b,d in zip(base, deltas)])
        lm = float(np.sum((sig_fn(net, probes) - target)**2))
        net.set_params(base)
        c = (lp - lm)/(2*eps)
        for k in range(len(accum)): accum[k] += c * deltas[k]
    return [a/n_dirs for a in accum]

def train_with_sig(net, X, Y, probes, target, sig_fn, lam=5.0, steps=2000,
                   lr=0.05, sig_lr=0.05, sig_every=3, seed=0):
    rng = np.random.default_rng(seed)
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if probes is not None and t % sig_every == 0 and lam > 0:
            apply(net, sig_grad_es(net, probes, target, sig_fn, rng), sig_lr * lam)
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
print(f"Anchor A task loss: {mse(A.forward(X)[0], Y):.5f}")
print(f"Baseline indep C: ||f_A - f_C|| = {BASELINE:.4f}\n")

# On-manifold probes (from training X)
def sample_probes(K, rng):
    idx = rng.choice(X.shape[0], K, replace=False)
    return X[idx]

B_seeds = [55, 66, 88]
N_PROBE_SAMPLES = 3

# Calibrate lambda per signature type to compensate for target magnitude
# Rule: initial sig_loss should be ~1 unit so λ=5 makes sig gradient ~5x task gradient
def calibrate_lam(sig_fn, probes, target_A, base_lam=5.0):
    """Lambda scaled so initial sig_loss is ~O(5) regardless of target magnitude."""
    B_init = MLP(10, 20, 4, seed=999)
    init_loss = float(np.sum((sig_fn(B_init, probes) - target_A)**2))
    return base_lam / max(init_loss, 1e-6)

# ==================================================================
# MAIN COMPARISON
# ==================================================================
print("="*84)
print("Signature type × K comparison — functional recovery")
print("="*84)
print(f"{'type':>12s}{'K':>4s}{'sig dim':>10s}"
      f"{'||f_A - f_B||':>18s}{'recovery':>12s}")
print("-"*84)

results = {}
for sig_name, (sig_fn, dims_per_probe) in SIG_FNS.items():
    for K in [1, 4]:
        all_dists = []
        for ps in range(N_PROBE_SAMPLES):
            rng_p = np.random.default_rng(500 + ps * 11 + K)
            probes = sample_probes(K, rng_p)
            target = sig_fn(A, probes)
            lam_cal = calibrate_lam(sig_fn, probes, target)
            lam_cal = min(max(lam_cal, 0.1), 50.0)   # clip
            for s in B_seeds:
                B = train_with_sig(MLP(10, 20, 4, seed=s), X, Y,
                                   probes=probes, target=target,
                                   sig_fn=sig_fn, lam=lam_cal, seed=s)
                all_dists.append(func_rms(A, B, X))
        mean_d = np.mean(all_dists); std_d = np.std(all_dists)
        imp = 100 * (1 - mean_d / BASELINE)
        results[(sig_name, K)] = (mean_d, std_d, imp)
        sig_dim = K * dims_per_probe
        print(f"{sig_name:>12s}{K:>4d}{sig_dim:>10d}"
              f"{mean_d:12.4f} ± {std_d:.4f}{imp:+10.1f}%")

# ==================================================================
# DATASET-WIDE MATCHING — classic distillation for reference
# Match f_A on FULL training set (akin to Hinton distillation but without softmax)
# ==================================================================
print("\n" + "="*84)
print("Reference: full-dataset output distillation (not a signature, just context)")
print("="*84)

def distill(net_B, X_tr, Y_tr_soft, steps=2000, lr=0.05):
    """Train B to match soft targets Y_tr_soft (from A) on full training set."""
    for _ in range(steps):
        apply(net_B, task_grad(net_B, X_tr, Y_tr_soft), lr)
    return net_B

Y_soft = A.forward(X)[0]   # A's outputs = soft targets
all_dists_dist = []
for s in B_seeds:
    B_dist = distill(MLP(10, 20, 4, seed=s), X, Y_soft)
    all_dists_dist.append(func_rms(A, B_dist, X))
mean_dist = np.mean(all_dists_dist); std_dist = np.std(all_dists_dist)
imp_dist = 100 * (1 - mean_dist / BASELINE)
print(f"  full-dataset distillation (600 probes × 4 outputs = 2400 dims): "
      f"||f_A-f_B|| = {mean_dist:.4f} ± {std_dist:.4f}  ({imp_dist:+.1f}%)")

# ==================================================================
# SUMMARY
# ==================================================================
print("\n" + "="*84)
print("SUMMARY")
print("="*84)
print(f"  {'type':>12s} {'K':>3s} {'dim':>6s} {'recovery':>10s}  bar")
print("  " + "-"*68)

all_rows = []
for (sig_name, K), (d, s, imp) in results.items():
    dim = K * SIG_FNS[sig_name][1]
    all_rows.append((sig_name, K, dim, imp))
all_rows.sort(key=lambda r: -r[3])

for name, K, dim, imp in all_rows:
    bar = "▓" * max(0, int(imp/2))
    print(f"  {name:>12s} {K:>3d} {dim:>6d} {imp:+9.1f}%  {bar}")

dim = 600 * 4
bar = "▓" * max(0, int(imp_dist/2))
print(f"  {'full-dataset':>12s} 600 {dim:>6d} {imp_dist:+9.1f}%  {bar}  ← for context")

# ------------------------------------------------------------------
# Is the ceiling broken? What's the best richer-target result?
# ------------------------------------------------------------------
output_k1 = results[('output', 1)][2]
output_k4 = results[('output', 4)][2]
best_rich = max([v[2] for k, v in results.items() if k[0] != 'output'])
print(f"\n  Output-only ceiling (K=1): {output_k1:+.1f}%")
print(f"  Output-only ceiling (K=4): {output_k4:+.1f}%")
print(f"  Best richer target result: {best_rich:+.1f}%")
if best_rich > max(output_k1, output_k4) + 3.0:
    print(f"  → CEILING BROKEN by richer targets (Δ ≈ {best_rich - max(output_k1, output_k4):+.1f}%)")
elif best_rich > max(output_k1, output_k4):
    print(f"  → slight improvement from richer targets but not a qualitative break")
else:
    print(f"  → ceiling NOT broken by these richer targets")
