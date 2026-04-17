"""
SESSION 11C — exact gradients, richer targets, push the curve further

Session 11B showed exact-gradient output matching gives +42.3% at K=64.
Now:
  1. Test richer targets (hidden activations, output+hidden combined) with exact
     gradients
  2. Push K higher (128, 256, 400, 600)
  3. Find where the curve truly saturates
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

# Task gradient
def task_grad(net, X, Y):
    Yp, H = net.forward(X); err = Yp - Y; N = X.shape[0]
    gWo = err.T @ H / N; gbo = err.mean(0)
    dH = err @ net.Wo; dZ1 = dH * (1 - H**2)
    gW1 = dZ1.T @ X / N; gb1 = dZ1.mean(0)
    return [gW1, gb1, gWo, gbo]

# Hidden-match gradient: d/dθ ||H_B(P) - target_H||^2
# Only affects W1, b1 (H doesn't depend on Wo, bo)
def hidden_match_grad(net, P, target_H):
    _, H = net.forward(P); err = H - target_H; N = P.shape[0]
    sech2 = 1.0 - H**2
    dZ1 = err * sech2
    gW1 = dZ1.T @ P / N; gb1 = dZ1.mean(0)
    gWo = np.zeros_like(net.Wo); gbo = np.zeros_like(net.bo)
    return [gW1, gb1, gWo, gbo]

# Combined output + hidden gradient (weighted sum)
def combined_match_grad(net, P, target_out, target_H, alpha_h=1.0):
    g_out = task_grad(net, P, target_out)            # output match
    g_hid = hidden_match_grad(net, P, target_H)
    return [a + alpha_h * b for a, b in zip(g_out, g_hid)]

def apply(net, grads, lr):
    for p, g in zip(net.params(), grads): p -= lr * g

def train_output_match(net, X, Y, P, T_out, lam, steps=2000, lr=0.05, sig_every=3):
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if t % sig_every == 0 and lam > 0:
            apply(net, task_grad(net, P, T_out), lr * lam)
    return net

def train_hidden_match(net, X, Y, P, T_H, lam, steps=2000, lr=0.05, sig_every=3):
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if t % sig_every == 0 and lam > 0:
            apply(net, hidden_match_grad(net, P, T_H), lr * lam)
    return net

def train_combined_match(net, X, Y, P, T_out, T_H, lam, alpha_h=1.0,
                          steps=2000, lr=0.05, sig_every=3):
    for t in range(steps):
        apply(net, task_grad(net, X, Y), lr)
        if t % sig_every == 0 and lam > 0:
            apply(net, combined_match_grad(net, P, T_out, T_H, alpha_h), lr * lam)
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
N_PROBE_SAMPLES = 2

def probes_and_targets(K, seed):
    rng = np.random.default_rng(seed)
    if K < X.shape[0]:
        idx = rng.choice(X.shape[0], K, replace=False)
        P = X[idx]
    else:
        P = X
    T_out = A.forward(P)[0]
    _, T_H = A.forward(P)
    return P, T_out, T_H

def evaluate(train_fn, K, **kwargs):
    """Train multiple B seeds, return mean recovery."""
    all_dists = []
    for ps in range(N_PROBE_SAMPLES):
        P, T_out, T_H = probes_and_targets(K, seed=900 + ps * 37 + K)
        for s in B_seeds:
            B = train_fn(MLP(10, 20, 4, seed=s), X, Y, P, T_out, T_H=T_H, **kwargs)
            all_dists.append(func_rms(A, B, X))
    mean_d = np.mean(all_dists)
    imp = 100 * (1 - mean_d / BASELINE)
    return mean_d, imp

# ==================================================================
# Compare target types at fixed K
# ==================================================================
print("="*80)
print("Target type comparison at K=64 (exact gradients)")
print("="*80)

# wrap train fns so signatures match
def _out(net, X, Y, P, T_out, T_H, lam):
    return train_output_match(net, X, Y, P, T_out, lam)
def _hid(net, X, Y, P, T_out, T_H, lam):
    return train_hidden_match(net, X, Y, P, T_H, lam)
def _com(net, X, Y, P, T_out, T_H, lam, alpha_h=1.0):
    return train_combined_match(net, X, Y, P, T_out, T_H, lam, alpha_h)

K = 64
for label, train_fn, kwargs in [
    ('output-match',      _out, {'lam': 5.0}),
    ('hidden-match',      _hid, {'lam': 5.0}),
    ('combined (α_h=1)',  _com, {'lam': 5.0, 'alpha_h': 1.0}),
    ('combined (α_h=0.3)',_com, {'lam': 5.0, 'alpha_h': 0.3}),
    ('combined (α_h=3)',  _com, {'lam': 5.0, 'alpha_h': 3.0}),
]:
    d, imp = evaluate(train_fn, K, **kwargs)
    print(f"  {label:22s}: ||f_A - f_B|| = {d:.4f}  recovery = {imp:+.1f}%")

# ==================================================================
# Push K higher for best target type
# ==================================================================
print("\n" + "="*80)
print("Full K sweep with output-match (best target), exact gradients")
print("="*80)
print(f"{'K':>6s}{'lam':>6s}{'||f_A-f_B||':>15s}{'recovery':>12s}")
print("-"*80)

# Tune lam per K: more probes need smaller lam because each step does more damage
# Heuristic: lam * K ≈ const (so total sig gradient per step is roughly fixed)
lam_by_K = {1: 0.1, 2: 0.5, 4: 2.0, 8: 3.0, 16: 4.0, 32: 5.0, 64: 5.0, 128: 4.0,
            200: 3.0, 300: 2.0, 400: 1.5, 600: 1.0}

k_sweep = {}
for K in [4, 16, 64, 128, 200, 300, 400, 600]:
    lam = lam_by_K[K]
    d, imp = evaluate(_out, K, lam=lam)
    k_sweep[K] = (d, imp)
    bar = "▓" * max(0, int(imp/2))
    print(f"{K:>6d}{lam:>6.1f}{d:>12.4f}{imp:>+10.1f}%  {bar}")

best_K = max(k_sweep.keys(), key=lambda k: k_sweep[k][1])
print(f"\n  Peak recovery at K={best_K}: {k_sweep[best_K][1]:+.1f}%")

# ==================================================================
# Lambda sweep at best K — find optimal weighting
# ==================================================================
print("\n" + "="*80)
print(f"Lambda sweep at K={best_K}")
print("="*80)

for lam in [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 15.0]:
    d, imp = evaluate(_out, best_K, lam=lam)
    bar = "▓" * max(0, int(imp/2))
    print(f"  lam={lam:>5.1f}: ||f_A-f_B||={d:.4f}  recovery={imp:+.1f}%  {bar}")
