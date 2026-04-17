"""
SESSION 06B — what macro-properties does dream dynamics preserve?

Session 6 showed dream dynamics causes weight drift + function divergence BUT
preserves output variance and Jacobian effective rank. This run probes a wider
set of macro-properties to map what's stable vs what drifts.

Measure at t=0, t=500, t=2000:
  - output variance (scalar)
  - output covariance spectrum (vector)
  - Jacobian effective rank (scalar)
  - Jacobian spectrum (vector)
  - hidden-activation covariance spectrum (vector)
  - hidden sparsity (fraction near zero)
  - Lipschitz estimate (max Jacobian norm over test)
  - loss on trained task (expected to degrade)

If a property's relative change is < 5%, we call it "preserved."
If > 20%, we call it "drifts."

Also: test whether preservation depends on trained-vs-random starting point.
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
        Z1 = X @ self.W1.T + self.b1; H = np.tanh(Z1); Y = H @ self.Wo.T + self.bo
        return Y, H
    def train_step(self, X, Y, lr):
        Yp, H = self.forward(X); err = Yp - Y; N = X.shape[0]
        gWo = err.T @ H / N; gbo = err.mean(0)
        dH = err @ self.Wo; dZ1 = dH * (1 - H**2)
        gW1 = dZ1.T @ X / N; gb1 = dZ1.mean(0)
        self.W1 -= lr*gW1; self.b1 -= lr*gb1
        self.Wo -= lr*gWo; self.bo -= lr*gbo
        return (err**2).mean()
    def jacobian(self, X):
        _, H = self.forward(X); sech2 = 1.0 - H**2
        return np.einsum('oh,nh,hi->noi', self.Wo, sech2, self.W1)

def make_task(seed=0, N_train=600, N_test=400, d_in=10, d_out=4, d_latent=3):
    r = np.random.default_rng(seed)
    Wt1 = r.normal(0, 1/np.sqrt(d_in), (16, d_in)); bt1 = np.zeros(16)
    Wt2 = r.normal(0, 1/np.sqrt(16),  (d_out, 16)); bt2 = np.zeros(d_out)
    teacher = lambda X: np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2
    B_embed = r.normal(0, 1, (d_latent, d_in))
    on = lambda N: r.normal(0, 1, (N, d_latent)) @ B_embed
    X_tr = on(N_train); Y_tr = teacher(X_tr) + 0.02*r.normal(0,1,(N_train,d_out))
    X_te = on(N_test); Y_te = teacher(X_te)
    return dict(X_tr=X_tr, Y_tr=Y_tr, X_te=X_te, Y_te=Y_te, d_in=d_in, d_out=d_out)

def dream_step(net, B, eps, lr, rng):
    N = rng.normal(0, 1, (B, net.d_in))
    Y, _ = net.forward(N)
    net.train_step(N, Y + eps*rng.normal(0, 1, Y.shape), lr)

def probe_all(net, X_te, Y_te, noise_rng):
    """Return dict of macro-measurements."""
    Yp, H = net.forward(X_te)                        # outputs + hidden on test data
    N_noise = noise_rng.normal(0, 1, (400, net.d_in))
    Yp_n, H_n = net.forward(N_noise)                 # on noise inputs
    J = net.jacobian(X_te)                           # [N, d_out, d_in]

    # (1) output variance on noise
    out_var = float(Yp_n.var(axis=0).mean())
    # (2) output covariance spectrum on noise
    out_cov = np.cov(Yp_n.T)
    out_spec = np.linalg.eigvalsh(out_cov)[::-1]
    out_spec = np.clip(out_spec, 0, None)
    # (3) Jacobian effective rank
    J_flat = J.reshape(X_te.shape[0], -1)
    s_J = svd(J_flat, compute_uv=False)
    p = s_J/s_J.sum(); p = p[p>1e-12]
    J_eff_rank = float(np.exp(-(p*np.log(p)).sum()))
    J_top = float(s_J[0])
    J_frob = float(norm(s_J))
    # (4) hidden activation covariance spectrum
    H_cov = np.cov(H_n.T)
    H_spec = np.linalg.eigvalsh(H_cov)[::-1]
    H_spec = np.clip(H_spec, 0, None)
    p_h = H_spec/(H_spec.sum()+1e-12); p_h = p_h[p_h>1e-12]
    H_eff_rank = float(np.exp(-(p_h*np.log(p_h)).sum()))
    # (5) hidden sparsity (fraction of |h| < 0.1)
    H_sparsity = float((np.abs(H_n) < 0.1).mean())
    # (6) Lipschitz estimate: max operator norm of J over samples
    J_opnorms = np.array([svd(J[i], compute_uv=False).max() for i in range(J.shape[0])])
    lipschitz = float(J_opnorms.max())
    # (7) weight norms
    W_norm = float(norm(net.W1)**2 + norm(net.Wo)**2)
    # (8) task test loss
    test_loss = float(((Yp - Y_te)**2).mean())

    return dict(
        out_var=out_var,
        out_spec_top=float(out_spec[0]),
        out_spec_ratio=float(out_spec[0]/(out_spec[1]+1e-12)),
        J_eff_rank=J_eff_rank,
        J_top=J_top,
        J_frob=J_frob,
        H_eff_rank=H_eff_rank,
        H_sparsity=H_sparsity,
        lipschitz=lipschitz,
        W_norm=W_norm,
        test_loss=test_loss,
    )

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------
task = make_task()
SEEDS = [1, 2, 3, 4, 5]
print("Phase 1: train 5 networks")
nets_trained = {}
for s in SEEDS:
    net = MLP(task['d_in'], 40, task['d_out'], seed=s)
    for _ in range(2500):
        net.train_step(task['X_tr'], task['Y_tr'], lr=0.05)
    nets_trained[s] = net

print("Phase 2: probe + dream + reprobe, 2000 steps")
CHECKPOINTS = [0, 500, 2000]
records = {t: [] for t in CHECKPOINTS}
probe_rng = np.random.default_rng(42)

# record initial
for s in SEEDS:
    records[0].append(probe_all(nets_trained[s], task['X_te'], task['Y_te'], probe_rng))

# dream + record
dream_rng = {s: np.random.default_rng(s + 777) for s in SEEDS}
for t in range(1, 2001):
    for s in SEEDS:
        dream_step(nets_trained[s], 64, 0.1, 0.01, dream_rng[s])
    if t in CHECKPOINTS:
        for s in SEEDS:
            records[t].append(probe_all(nets_trained[s], task['X_te'], task['Y_te'], probe_rng))

# ------------------------------------------------------------------
# Results: percent change from t=0 to t=2000
# ------------------------------------------------------------------
print("\n" + "="*78)
print("MACRO-PROPERTY PRESERVATION — % change from t=0 to t=2000")
print(f"  (averaged over 5 trained networks)")
print("="*78)
print(f"{'property':20s}{'t=0':>12s}{'t=500':>12s}{'t=2000':>12s}{'% change':>12s}{'verdict':>12s}")
print("-"*78)

keys = ['out_var', 'out_spec_top', 'out_spec_ratio',
        'J_eff_rank', 'J_top', 'J_frob',
        'H_eff_rank', 'H_sparsity',
        'lipschitz', 'W_norm', 'test_loss']

for k in keys:
    v0 = np.mean([r[k] for r in records[0]])
    v1 = np.mean([r[k] for r in records[500]])
    v2 = np.mean([r[k] for r in records[2000]])
    change = (v2 - v0) / (abs(v0) + 1e-12) * 100
    verdict = ('PRESERVED' if abs(change) < 5
               else 'STABLE  ' if abs(change) < 20
               else 'DRIFTS  ')
    print(f"{k:20s}{v0:12.4f}{v1:12.4f}{v2:12.4f}{change:+11.1f}%  {verdict}")

# ------------------------------------------------------------------
# Compare to random-init baseline: which properties does the random net
# preserve under the same dynamics? If same set preserved → architectural
# invariants, not training-specific.
# ------------------------------------------------------------------
print("\n" + "="*78)
print("Same experiment from RANDOM init — what's preserved when untrained?")
print("="*78)
rand_nets = {s: MLP(task['d_in'], 40, task['d_out'], seed=s+99999) for s in SEEDS}
rand_init_records = []
for s in SEEDS:
    rand_init_records.append(probe_all(rand_nets[s], task['X_te'], task['Y_te'], probe_rng))
rand_dream_rng = {s: np.random.default_rng(s + 111) for s in SEEDS}
for t in range(2000):
    for s in SEEDS:
        dream_step(rand_nets[s], 64, 0.1, 0.01, rand_dream_rng[s])
rand_final_records = []
for s in SEEDS:
    rand_final_records.append(probe_all(rand_nets[s], task['X_te'], task['Y_te'], probe_rng))

print(f"{'property':20s}{'rand t=0':>12s}{'rand t=2000':>14s}{'% change':>12s}{'verdict':>12s}")
print("-"*70)
for k in keys:
    v0 = np.mean([r[k] for r in rand_init_records])
    v2 = np.mean([r[k] for r in rand_final_records])
    change = (v2 - v0) / (abs(v0) + 1e-12) * 100
    verdict = ('PRESERVED' if abs(change) < 5
               else 'STABLE  ' if abs(change) < 20
               else 'DRIFTS  ')
    print(f"{k:20s}{v0:12.4f}{v2:14.4f}{change:+11.1f}%  {verdict}")

# ------------------------------------------------------------------
# Cross-network agreement: do ALL trained networks share macro-values,
# or is the preservation per-network?
# ------------------------------------------------------------------
print("\n" + "="*78)
print("Do trained networks SHARE the same macro-values? (cross-net agreement)")
print("="*78)
for k in keys:
    vs0 = np.array([r[k] for r in records[0]])
    vs2 = np.array([r[k] for r in records[2000]])
    # coefficient of variation
    cv0 = vs0.std() / (abs(vs0.mean())+1e-12) * 100
    cv2 = vs2.std() / (abs(vs2.mean())+1e-12) * 100
    # compare to random-init CV
    vsr = np.array([r[k] for r in rand_init_records])
    cvr = vsr.std() / (abs(vsr.mean())+1e-12) * 100
    print(f"  {k:20s}  trained CV: t=0 {cv0:5.1f}%  t=2000 {cv2:5.1f}%  "
          f"| random-init CV: {cvr:5.1f}%")
