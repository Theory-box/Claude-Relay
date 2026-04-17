"""
SESSION 06 — Dream attractor dynamics

Committed direction. Combined Möbius + dreams: after training, networks evolve
under their own dream-driven weight updates with NO external gradient signal.
Question: where do they drift, and do networks trained on the same task
converge to the same place?

Update rule:
  1. sample Gaussian noise N
  2. y = f(N; θ_t)                       (network's output on noise = dream)
  3. y_target = y + ε · noise_y          (perturb target by small noise)
  4. θ_{t+1} = θ_t - η · ∇_θ ||f(N;θ) - y_target||²

This gives non-trivial dynamics: target differs from current output by ε, so
gradient is nonzero. Over many iterations, network drifts under pure
self-imagination, no data.

Measurements, over time during dream dynamics:
  - weight movement ||θ_t - θ_0||
  - function movement on test data (independent of dynamics)
  - pairwise similarity across 5 networks (do they converge?)
  - output variance (collapse to constant?)
  - Jacobian spectrum (rank collapse?)
  - task performance (degrade or preserve?)
"""

import numpy as np
from numpy.linalg import norm, svd

# ------------------------------------------------------------------
# MLP
# ------------------------------------------------------------------
class MLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in),  (d_hid, d_in))
        self.b1 = np.zeros(d_hid)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid))
        self.bo = np.zeros(d_out)
        self.d_in, self.d_hid, self.d_out = d_in, d_hid, d_out

    def forward(self, X):
        Z1 = X @ self.W1.T + self.b1
        H  = np.tanh(Z1)
        Y  = H @ self.Wo.T + self.bo
        return Y, H

    def train_step(self, X, Y, lr):
        Yp, H = self.forward(X)
        err = Yp - Y; N = X.shape[0]
        gWo = err.T @ H / N; gbo = err.mean(0)
        dH = err @ self.Wo; dZ1 = dH * (1 - H**2)
        gW1 = dZ1.T @ X / N; gb1 = dZ1.mean(0)
        self.W1 -= lr*gW1; self.b1 -= lr*gb1
        self.Wo -= lr*gWo; self.bo -= lr*gbo
        return (err**2).mean()

    def jacobian(self, X):
        _, H = self.forward(X)
        sech2 = 1.0 - H**2
        return np.einsum('oh,nh,hi->noi', self.Wo, sech2, self.W1)

    def params_vec(self):
        return np.concatenate([self.W1.ravel(), self.b1, self.Wo.ravel(), self.bo])

    def clone(self):
        new = MLP.__new__(MLP)
        new.W1 = self.W1.copy(); new.b1 = self.b1.copy()
        new.Wo = self.Wo.copy(); new.bo = self.bo.copy()
        new.d_in = self.d_in; new.d_hid = self.d_hid; new.d_out = self.d_out
        return new

# ------------------------------------------------------------------
# Task
# ------------------------------------------------------------------
def make_task(seed=0, N_train=600, N_test=400, d_in=10, d_out=4, d_latent=3):
    r = np.random.default_rng(seed)
    Wt1 = r.normal(0, 1/np.sqrt(d_in), (16, d_in)); bt1 = np.zeros(16)
    Wt2 = r.normal(0, 1/np.sqrt(16),  (d_out, 16)); bt2 = np.zeros(d_out)
    def teacher(X):
        return np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2
    B_embed = r.normal(0, 1, (d_latent, d_in))
    def on(N):
        z = r.normal(0, 1, (N, d_latent)); return z @ B_embed
    X_tr = on(N_train); Y_tr = teacher(X_tr) + 0.02*r.normal(0,1,(N_train,d_out))
    X_te = on(N_test);  Y_te = teacher(X_te)
    return dict(X_tr=X_tr, Y_tr=Y_tr, X_te=X_te, Y_te=Y_te, d_in=d_in, d_out=d_out)

# ------------------------------------------------------------------
# Dream step
# ------------------------------------------------------------------
def dream_step(net, batch_noise, target_eps, lr, rng):
    """One dream-consolidation step.
    - sample noise input of shape batch_noise × d_in
    - predict y on noise
    - perturb target: y_target = y + target_eps * unit_gaussian
    - gradient step minimizing ||f(N) - y_target||^2
    """
    N = rng.normal(0, 1, (batch_noise, net.d_in))
    Y, H = net.forward(N)
    perturbation = target_eps * rng.normal(0, 1, Y.shape)
    Y_target = Y + perturbation
    # gradient step
    return net.train_step(N, Y_target, lr)

# ------------------------------------------------------------------
# Setup: train 5 networks to similar loss
# ------------------------------------------------------------------
task = make_task()
SEEDS = [1, 2, 3, 4, 5]
nets = {}
print("Phase 1: train 5 networks to similar loss")
for s in SEEDS:
    net = MLP(task['d_in'], 40, task['d_out'], seed=s)
    for _ in range(2500):
        net.train_step(task['X_tr'], task['Y_tr'], lr=0.05)
    loss = ((net.forward(task['X_tr'])[0] - task['Y_tr'])**2).mean()
    test = ((net.forward(task['X_te'])[0] - task['Y_te'])**2).mean()
    nets[s] = net
    print(f"  seed {s}: train_loss={loss:.4f}  test_loss={test:.4f}")

# snapshot initial state (pre-dream)
trained_snaps = {s: nets[s].clone() for s in SEEDS}

# also a baseline: networks that DON'T undergo dream dynamics, for control
static_snaps = {s: nets[s].clone() for s in SEEDS}

# ------------------------------------------------------------------
# Diagnostics helpers
# ------------------------------------------------------------------
def pairwise_function_distance(net_dict, X):
    """Mean pairwise RMS prediction distance on X."""
    preds = {s: net_dict[s].forward(X)[0] for s in net_dict}
    seeds = sorted(net_dict.keys())
    dists = []
    for i, si in enumerate(seeds):
        for sj in seeds[i+1:]:
            d = np.sqrt(((preds[si] - preds[sj])**2).mean())
            dists.append(d)
    return float(np.mean(dists)), float(np.std(dists))

def weight_drift(net, ref):
    return float(norm(net.params_vec() - ref.params_vec()))

def output_variance(net, noise_batch, rng):
    """Variance of outputs over noise inputs (measures expressivity)."""
    N = rng.normal(0, 1, (noise_batch, net.d_in))
    Y, _ = net.forward(N)
    return float(Y.var(axis=0).mean())

def jacobian_effective_rank(net, X):
    J = net.jacobian(X)                  # [N, d_out, d_in]
    J_flat = J.reshape(X.shape[0], -1)
    s = svd(J_flat, compute_uv=False)
    p = s/s.sum(); p = p[p > 1e-12]
    return float(np.exp(-(p*np.log(p)).sum()))

# ------------------------------------------------------------------
# Phase 2: run dream dynamics on each net, snapshot periodically
# ------------------------------------------------------------------
print("\nPhase 2: run dream dynamics for 1000 steps per network, snapshot every 100")

CHECKPOINTS = [0, 50, 100, 200, 400, 700, 1000]
snapshots = {t: {s: nets[s].clone() for s in SEEDS} for t in [0]}    # t=0 starts populated

# run for ALL steps, but snapshot at checkpoints
dynamics_rng = {s: np.random.default_rng(s + 5555) for s in SEEDS}
max_steps = max(CHECKPOINTS)
for t in range(1, max_steps + 1):
    for s in SEEDS:
        dream_step(nets[s], batch_noise=64, target_eps=0.1, lr=0.01,
                   rng=dynamics_rng[s])
    if t in CHECKPOINTS:
        snapshots[t] = {s: nets[s].clone() for s in SEEDS}

# ------------------------------------------------------------------
# Phase 3: measure trajectories
# ------------------------------------------------------------------
print("\nPhase 3: measurements at each checkpoint")
print(f"{'step':>6s} | {'avg wt drift':>14s} | {'pairwise func dist':>20s} | "
      f"{'test loss':>11s} | {'output var':>12s} | {'J eff rank':>11s}")
print("-"*90)

diag_rng = np.random.default_rng(99)
for t in CHECKPOINTS:
    snap = snapshots[t]
    # average weight drift from pre-dream trained state
    drifts = [weight_drift(snap[s], trained_snaps[s]) for s in SEEDS]
    avg_drift = np.mean(drifts)
    # pairwise function distance between the 5 nets
    pwd_mean, pwd_std = pairwise_function_distance(snap, task['X_te'])
    # avg test loss
    tests = [((snap[s].forward(task['X_te'])[0] - task['Y_te'])**2).mean() for s in SEEDS]
    avg_test = np.mean(tests)
    # output variance on noise
    ovs = [output_variance(snap[s], 200, diag_rng) for s in SEEDS]
    avg_ov = np.mean(ovs)
    # Jacobian effective rank on test set
    ers = [jacobian_effective_rank(snap[s], task['X_te'][:200]) for s in SEEDS]
    avg_er = np.mean(ers)
    print(f"{t:6d} | {avg_drift:14.4f} | {pwd_mean:10.4f} ± {pwd_std:5.4f}  | "
          f"{avg_test:11.4f} | {avg_ov:12.4f} | {avg_er:11.3f}")

# ------------------------------------------------------------------
# Phase 4: how does pairwise similarity compare across matched quantities?
# ------------------------------------------------------------------
print("\nPhase 4: convergence/divergence signature")
pwd0, _ = pairwise_function_distance(snapshots[0],    task['X_te'])
pwd_end, _ = pairwise_function_distance(snapshots[max_steps], task['X_te'])
print(f"  Pairwise function distance at t=0        : {pwd0:.4f}")
print(f"  Pairwise function distance at t={max_steps:<5d}    : {pwd_end:.4f}")
change = (pwd_end - pwd0) / pwd0 * 100
print(f"  Relative change                          : {change:+.1f}%  "
      f"({'CONVERGING' if change < -5 else 'DIVERGING' if change > 5 else 'STABLE'})")

# Also look at position relative to initial training trajectory
# Are networks at t=1000 closer to their own t=0 selves than to each other?
print("\n  Within-net vs between-net distance at t=1000:")
within_dists = []
between_dists = []
for s in SEEDS:
    within_dists.append(weight_drift(snapshots[max_steps][s], trained_snaps[s]))
    for s2 in SEEDS:
        if s2 != s:
            between_dists.append(
                weight_drift(snapshots[max_steps][s], snapshots[max_steps][s2]))
print(f"  avg ||θ_1000^s - θ_0^s||         : {np.mean(within_dists):.3f}  "
      f"(self-drift)")
print(f"  avg ||θ_1000^s - θ_1000^s'||     : {np.mean(between_dists):.3f}  "
      f"(cross-distance)")
if np.mean(within_dists) < np.mean(between_dists):
    print("  → networks stay closer to their own past than to each other (DIVERGE in weight space)")
else:
    print("  → networks move closer together than they drift (CONVERGE in weight space)")

# ------------------------------------------------------------------
# Phase 5: what if we do the SAME dynamics but FROM RANDOM INIT (not trained)?
# If the attractor is trained-state-specific vs architecture-universal, this differs.
# ------------------------------------------------------------------
print("\nPhase 5: run same dynamics from random (untrained) init — where does THAT drift?")
random_nets = {s: MLP(task['d_in'], 40, task['d_out'], seed=s + 10000) for s in SEEDS}
random_initial = {s: random_nets[s].clone() for s in SEEDS}
dynamics_rng2 = {s: np.random.default_rng(s + 66666) for s in SEEDS}
pwd_init, _ = pairwise_function_distance(random_nets, task['X_te'])
for t in range(max_steps):
    for s in SEEDS:
        dream_step(random_nets[s], 64, 0.1, 0.01, dynamics_rng2[s])
pwd_final, _ = pairwise_function_distance(random_nets, task['X_te'])
print(f"  random init pairwise dist @ t=0:     {pwd_init:.4f}")
print(f"  random init pairwise dist @ t={max_steps}:  {pwd_final:.4f}")

# compare: do trained nets drift to a point similar to where random nets drift?
print("\n  Trained-final vs random-final: are their attractors similar?")
trained_final = snapshots[max_steps]
cross_dists = []
for s in SEEDS:
    for s2 in SEEDS:
        preds_t = trained_final[s].forward(task['X_te'])[0]
        preds_r = random_nets[s2].forward(task['X_te'])[0]
        cross_dists.append(np.sqrt(((preds_t - preds_r)**2).mean()))
print(f"  avg func dist trained-final ↔ random-final: {np.mean(cross_dists):.4f}")
# if this is small → trained and random end up in similar place (universal attractor)
# if this is large → attractor depends on where you started (local attractors)
