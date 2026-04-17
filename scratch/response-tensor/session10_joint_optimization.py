"""
SESSION 10 — joint probe optimization

Goal: find probe inputs P such that signature-matching B → A works best.
Previous best: K=4 random probes → 23.3% functional recovery.

Methods compared at K=4:
  1. RANDOM            : baseline from 9B
  2. MAX_DISAGREEMENT  : 9B heuristic — probes where independent nets disagree most
  3. FISHER_INFO       : NEW — probes where f_A is most sensitive to A's weights
                          (high parameter-gradient norm = high info per number)
  4. ACTIVE_ITERATIVE  : NEW — greedily add probes where current B disagrees with A
                          (closed-loop: train B, find gap, add probe, retrain)
  5. BILEVEL_ES        : NEW — outer ES loop on probe locations, inner loop is
                          full B training. Most expensive, should be best.

All use K=4 (sweet spot from session 9). Target outputs T = f_A(P) for each.
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
# Parameter-gradient of f_A(p) w.r.t. A's weights (Fisher info measure)
# For MLP: f(p) = tanh(W1 p + b1) Wo^T + bo
# ------------------------------------------------------------------
def fisher_info_at(net, p):
    """Return ||∂f(p)/∂θ||^2 summed over output dims.
    Measures how much info about θ the single output f(p) carries."""
    p = p.reshape(1, -1)
    z1 = p @ net.W1.T + net.b1
    h  = np.tanh(z1)
    sech2 = 1.0 - h**2
    # For each output o: ∂f_o/∂W1[i,j] = Wo[o,i] * sech2[i] * p[j]
    #                    ∂f_o/∂b1[i]   = Wo[o,i] * sech2[i]
    #                    ∂f_o/∂Wo[o,i] = h[i]
    #                    ∂f_o/∂bo[o]   = 1
    d_out = net.d_out; d_hid = net.d_hid; d_in = net.d_in
    total_sq = 0.0
    for o in range(d_out):
        g_W1 = (net.Wo[o:o+1, :] * sech2).T @ p    # [d_hid, d_in]
        g_b1 = net.Wo[o, :] * sech2[0]             # [d_hid]
        g_Wo = np.zeros((d_out, d_hid))
        g_Wo[o, :] = h[0]                          # [d_out, d_hid]
        g_bo = np.zeros(d_out); g_bo[o] = 1.0
        total_sq += float((g_W1**2).sum() + (g_b1**2).sum()
                         + (g_Wo**2).sum() + (g_bo**2).sum())
    return total_sq

# ==================================================================
# Setup: train anchor A + siblings for disagreement scoring
# ==================================================================
print("Training anchor A and siblings ...")
X, Y = task_teacher()
A = train_standard(MLP(10, 20, 4, seed=1), X, Y)
siblings = [train_standard(MLP(10, 20, 4, seed=s), X, Y) for s in [2,3,4,5,6,7]]
C_baseline = train_standard(MLP(10, 20, 4, seed=77), X, Y)
BASELINE = func_rms(A, C_baseline, X)
print(f"  A task loss: {mse(A.forward(X)[0], Y):.5f}")
print(f"  Baseline indep C: ||f_A - f_C||={BASELINE:.4f}\n")

# Candidate probe pool (larger than session 9B)
rng_pool = np.random.default_rng(2024)
CANDIDATES = rng_pool.normal(0, 1, (1000, 10))

K = 4                                   # fixed sweet-spot from session 9
N_EVAL = 3                              # multiple B seeds per method for stability
eval_seeds = [55, 66, 88]

def eval_probe_set(probes, label):
    """Train N_EVAL B's with this probe set, report mean ||f_A - f_B||."""
    target = A.forward(probes)[0].ravel()
    dists = []
    for s in eval_seeds:
        B = train_with_probes(MLP(10, 20, 4, seed=s), X, Y,
                              probes=probes, target=target, seed=s)
        dists.append(func_rms(A, B, X))
    mean_d = np.mean(dists)
    std_d  = np.std(dists)
    improvement = 100 * (1 - mean_d / BASELINE)
    print(f"  {label:25s} : ||f_A-f_B||={mean_d:.4f}±{std_d:.4f}  ({improvement:+.1f}% vs indep)")
    return mean_d, improvement

# ==================================================================
# METHOD 1: RANDOM
# ==================================================================
print("="*78)
print("METHOD 1: RANDOM")
print("="*78)
rng_rand = np.random.default_rng(42)
probes_random = CANDIDATES[rng_rand.choice(len(CANDIDATES), K, replace=False)]
d_rand, imp_rand = eval_probe_set(probes_random, "random")

# ==================================================================
# METHOD 2: MAX DISAGREEMENT (session 9B)
# ==================================================================
print("\n" + "="*78)
print("METHOD 2: MAX DISAGREEMENT across 7 nets (session 9B baseline)")
print("="*78)
all_nets = [A] + siblings
outs = np.stack([n.forward(CANDIDATES)[0] for n in all_nets])  # [7, N, d_out]
disagreement = outs.var(axis=0).sum(axis=-1)                    # [N]
probes_disagree = CANDIDATES[np.argsort(-disagreement)[:K]]
d_disagree, imp_disagree = eval_probe_set(probes_disagree, "max-disagreement")

# ==================================================================
# METHOD 3: FISHER INFORMATION
# Rank candidates by ||∂f_A/∂θ|_p||^2. Higher = more param-info per number.
# ==================================================================
print("\n" + "="*78)
print("METHOD 3: FISHER INFORMATION — max ||∂f_A/∂θ|_p||^2")
print("="*78)
fisher_scores = np.array([fisher_info_at(A, c) for c in CANDIDATES])
probes_fisher = CANDIDATES[np.argsort(-fisher_scores)[:K]]
d_fisher, imp_fisher = eval_probe_set(probes_fisher, "fisher-info")
print(f"  [info] avg Fisher score of top-K  : {fisher_scores[np.argsort(-fisher_scores)[:K]].mean():.2f}")
print(f"  [info] avg Fisher score of random : {fisher_scores.mean():.2f}")

# ==================================================================
# METHOD 4: ACTIVE ITERATIVE
# Greedily add probes where current B (trained with existing probes)
# disagrees most with A. Bootstrap up to K probes.
# ==================================================================
print("\n" + "="*78)
print("METHOD 4: ACTIVE ITERATIVE — add probes where B disagrees with A")
print("="*78)
# Start with 1 random probe (or Fisher-best probe)
active_probes = [CANDIDATES[np.argmax(fisher_scores)]]   # seed with best Fisher
print(f"  Initial probe: Fisher-best (score {fisher_scores.max():.1f})")
for i in range(K - 1):
    # Train B with current probes
    P_cur = np.stack(active_probes)
    target_cur = A.forward(P_cur)[0].ravel()
    B_cur = train_with_probes(MLP(10, 20, 4, seed=101), X, Y,
                              probes=P_cur, target=target_cur, seed=101,
                              steps=1500)  # slightly shorter for speed
    cur_gap = func_rms(A, B_cur, X)
    # Find candidate with max pointwise disagreement between A and B_cur
    A_out = A.forward(CANDIDATES)[0]
    B_out = B_cur.forward(CANDIDATES)[0]
    pointwise_gap = ((A_out - B_out)**2).sum(axis=-1)
    # Avoid picking duplicates: zero out candidates close to existing probes
    for p_exist in active_probes:
        dists = np.linalg.norm(CANDIDATES - p_exist, axis=1)
        pointwise_gap[dists < 0.5] = 0
    next_idx = int(np.argmax(pointwise_gap))
    new_probe = CANDIDATES[next_idx]
    active_probes.append(new_probe)
    print(f"  Step {i+1}: after {len(active_probes)-1} probes, gap={cur_gap:.4f}; "
          f"added probe at max-disagreement (gap_new={pointwise_gap[next_idx]:.4f})")
probes_active = np.stack(active_probes)
d_active, imp_active = eval_probe_set(probes_active, "active-iterative")

# ==================================================================
# METHOD 5: BILEVEL ES — outer loop optimizes probe locations
# Start from Fisher-info probes; perturb and retrain B; keep best.
# Budget: 8 outer iterations × 2 random perturbations = 16 inner trainings
# ==================================================================
print("\n" + "="*78)
print("METHOD 5: BILEVEL ES — outer optimization of probe locations")
print("="*78)
es_probes = probes_fisher.copy()
best_dist = None
best_probes = es_probes.copy()

# evaluate starting point
target_es = A.forward(es_probes)[0].ravel()
B_init = train_with_probes(MLP(10, 20, 4, seed=55), X, Y,
                           probes=es_probes, target=target_es, seed=55, steps=1500)
best_dist = func_rms(A, B_init, X)
print(f"  Starting (Fisher-init): gap={best_dist:.4f}")

rng_es = np.random.default_rng(7)
N_OUTER = 8
step_size = 0.3
for it in range(N_OUTER):
    improved = False
    for _ in range(2):
        perturb = rng_es.normal(0, 1, es_probes.shape)
        perturb /= (np.linalg.norm(perturb) + 1e-12)
        trial = es_probes + step_size * perturb
        tgt_t = A.forward(trial)[0].ravel()
        B_t = train_with_probes(MLP(10, 20, 4, seed=55), X, Y,
                                probes=trial, target=tgt_t, seed=55, steps=1500)
        d_t = func_rms(A, B_t, X)
        if d_t < best_dist:
            best_dist = d_t
            best_probes = trial.copy()
            es_probes = trial.copy()
            improved = True
            break
    marker = "↓" if improved else "·"
    print(f"  outer iter {it+1:2d} {marker}: best gap={best_dist:.4f}")
    if not improved:
        step_size *= 0.7                 # anneal step size on failed iter
probes_es = best_probes
d_es, imp_es = eval_probe_set(probes_es, "bilevel-ES (final eval)")

# ==================================================================
# Summary
# ==================================================================
print("\n" + "="*78)
print("SUMMARY — K=4 probes, functional recovery vs independent baseline")
print("="*78)
rows = [
    ("random",           d_rand,     imp_rand),
    ("max-disagreement", d_disagree, imp_disagree),
    ("fisher-info",      d_fisher,   imp_fisher),
    ("active-iterative", d_active,   imp_active),
    ("bilevel-ES",       d_es,       imp_es),
]
rows.sort(key=lambda r: r[1])  # by distance ascending
for name, d, imp in rows:
    bar = "▓" * max(0, int(imp/2))
    print(f"  {name:22s} {d:.4f}  ({imp:+6.1f}%)  {bar}")

# Characterize the winning probes
best = min(rows, key=lambda r: r[1])
print(f"\n  Winner: {best[0]}")
print(f"  vs session 9 best (K=4 random, 23.3%): "
      f"{'WIN' if best[2] > 23.3 else 'no improvement'}")
