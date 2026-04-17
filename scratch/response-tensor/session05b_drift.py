"""
SESSION 05B — write-to-future-self with a task that REWARDS memory

Task modification: teacher output has an added sinusoidal drift based on training
step t, invisible in x. Without memory, best the net can do is predict the mean
over the drift. With memory, it can potentially track the phase across batches.

    target(x, t) = teacher(x) + A · sin(2πt/T) · direction

where `direction` is a fixed random unit vector in d_out space. The net sees only
x, not t. So t must be inferred from the message trajectory.

Rerun the same 5 conditions. If self_write now outperforms no_memory, the
mechanism carries genuine temporal signal. If even here it doesn't help, the
tied-weights implicit-write design is too weak (we'd need BPTT).
"""
import numpy as np

# ------------------------------------------------------------------
# Task with hidden sinusoidal drift
# ------------------------------------------------------------------
class DriftTask:
    def __init__(self, seed=0, N_train=1000, d_in=8, d_out=4, d_latent=3,
                 period=400, amplitude=0.6):
        r = np.random.default_rng(seed)
        Wt1 = r.normal(0, 1/np.sqrt(d_in), (20, d_in)); bt1 = np.zeros(20)
        Wt2 = r.normal(0, 1/np.sqrt(20),  (d_out, 20)); bt2 = np.zeros(d_out)
        self.teacher_fn = lambda X: np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2
        B_embed = r.normal(0, 1, (d_latent, d_in))
        _, _, Vt = np.linalg.svd(B_embed, full_matrices=True)
        self.null_basis = Vt[d_latent:].T
        self.B_embed = B_embed
        self.X_pool = self._on(N_train, r)
        self.Y_pool_base = self.teacher_fn(self.X_pool)
        # fixed drift direction
        self.direction = r.normal(0, 1, d_out); self.direction /= np.linalg.norm(self.direction)
        self.period, self.amplitude = period, amplitude
        self.d_in, self.d_out = d_in, d_out
        self.noise_rng = np.random.default_rng(seed+1)

    def _on(self, N, r):
        z = r.normal(0, 1, (N, 3)); return z @ self.B_embed

    def drift(self, t):
        return self.amplitude * np.sin(2*np.pi * t / self.period) * self.direction

    def batch(self, t, batch_size, rng):
        idx = rng.integers(0, self.X_pool.shape[0], batch_size)
        X = self.X_pool[idx]
        Y = self.Y_pool_base[idx] + self.drift(t) + 0.02*self.noise_rng.normal(0,1,(batch_size,self.d_out))
        return X, Y

    def test_at_step(self, t, N=300, seed=123):
        r = np.random.default_rng(seed)
        X = self._on(N, r)
        Y = self.teacher_fn(X) + self.drift(t)
        return X, Y

# ------------------------------------------------------------------
# MessageMLP (reused from 5A)
# ------------------------------------------------------------------
class MessageMLP:
    def __init__(self, d_in, d_hid, d_out, d_m, seed=0, disable_memory=False):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in), (d_hid, d_in)); self.b1 = np.zeros(d_hid)
        self.Wm = r.normal(0, 0.1/np.sqrt(d_m), (d_hid, d_m)); self.bm = np.zeros(d_m)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid)); self.bo = np.zeros(d_out)
        self.disable_memory = disable_memory
        self.d_hid, self.d_m = d_hid, d_m

    def forward(self, X, m_prev):
        read_bias = 0.0 if self.disable_memory else (self.Wm @ m_prev)
        z1 = X @ self.W1.T + self.b1 + read_bias
        h  = np.tanh(z1)
        y  = h @ self.Wo.T + self.bo
        if self.disable_memory:
            m_new = m_prev
        else:
            m_new = self.Wm.T @ h.mean(0) + self.bm
        return y, h, m_new

    def train_step(self, X, Y, m_prev, lr):
        Yp, h, m_new = self.forward(X, m_prev)
        err = Yp - Y; N = X.shape[0]
        gWo = err.T @ h / N; gbo = err.mean(0)
        dh = err @ self.Wo; dz1 = dh * (1 - h**2)
        gW1 = dz1.T @ X / N; gb1 = dz1.mean(0)
        self.W1 -= lr*gW1; self.b1 -= lr*gb1
        self.Wo -= lr*gWo; self.bo -= lr*gbo
        if not self.disable_memory:
            gWm = np.outer(dz1.mean(0), m_prev)
            self.Wm -= lr * gWm
        return (err**2).mean(), m_new

# ------------------------------------------------------------------
# Runner (same conditions as 5A)
# ------------------------------------------------------------------
def make_provider(condition, seed, d_m, other_messages=None):
    rng = np.random.default_rng(seed + 13579)
    m0 = np.zeros(d_m)
    if condition == 'no_memory':
        return (lambda t, m_prev_real: np.zeros(d_m)), m0
    if condition == 'self_write':
        return (lambda t, m_prev_real: m_prev_real), m0
    if condition == 'random_prev':
        return (lambda t, m_prev_real: rng.normal(0, 1, d_m)), m0
    if condition == 'frozen_random':
        v = rng.normal(0, 1, d_m)
        return (lambda t, m_prev_real: v), v.copy()
    if condition == 'other_write':
        def prov(t, m_prev_real):
            idx = min(t, len(other_messages)-1)
            return other_messages[idx]
        return prov, m0
    raise ValueError(condition)

def train_run(condition, seed, task, steps=3000, batch=64, lr=0.05, d_m=8,
              other_messages=None, record_messages=False):
    d_in, d_out = task.d_in, task.d_out
    d_hid = 24
    disable = (condition == 'no_memory')
    net = MessageMLP(d_in, d_hid, d_out, d_m, seed=seed, disable_memory=disable)
    provider, m_prev_real = make_provider(condition, seed, d_m, other_messages)
    rng = np.random.default_rng(seed)

    msg_log = [] if record_messages else None
    for t in range(steps):
        X, Y = task.batch(t, batch, rng)
        m_read = provider(t, m_prev_real)
        _, m_actual = net.train_step(X, Y, m_read, lr)
        m_prev_real = m_actual
        if record_messages:
            msg_log.append(m_actual.copy())

    # Evaluate at two different timesteps (different phases of drift)
    losses_by_phase = []
    for test_step in [0, 100, 200, 300]:     # span one period
        X, Y = task.test_at_step(test_step)
        m_read = provider(test_step, m_prev_real)
        Yp, _, _ = net.forward(X, m_read)
        losses_by_phase.append(((Yp - Y)**2).mean())

    # overall test loss (averaged across phases)
    test_mean = np.mean(losses_by_phase)

    # ablation: zero msg at test
    if not disable:
        abl_losses = []
        for test_step in [0, 100, 200, 300]:
            X, Y = task.test_at_step(test_step)
            Yp, _, _ = net.forward(X, np.zeros(d_m))
            abl_losses.append(((Yp - Y)**2).mean())
        abl_mean = np.mean(abl_losses)
    else:
        abl_mean = None

    # msg effect at test: RMS change when zeroing message
    if not disable:
        X, Y = task.test_at_step(steps-1)
        m_read = provider(steps-1, m_prev_real)
        Yp_live, _, _ = net.forward(X, m_read)
        Yp_zero, _, _ = net.forward(X, np.zeros(d_m))
        msg_eff = float(np.sqrt(((Yp_live - Yp_zero)**2).mean()))
    else:
        msg_eff = 0.0

    return dict(condition=condition, seed=seed,
                test=test_mean, losses_by_phase=losses_by_phase,
                abl=abl_mean, msg_eff=msg_eff, msg_log=msg_log)

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
SEEDS = [1,2,3,4,5]
task = DriftTask()
print(f"Task: drift period={task.period}, amplitude={task.amplitude}")
print(f"  Best-no-memory predictor = teacher(x) + 0 (mean drift),")
print(f"  residual MSE floor ~ amplitude^2/2 = {task.amplitude**2/2:.3f}\n")

results = []
# Stage 1: self_write + record
print("Stage 1: self_write (records trajectories)")
traj = {}
for s in SEEDS:
    r = train_run('self_write', s, task, record_messages=True)
    traj[s] = r['msg_log']
    results.append(r)
    print(f"  seed {s}: test={r['test']:.4f}  phases={[f'{l:.3f}' for l in r['losses_by_phase']]}  "
          f"msg_eff={r['msg_eff']:.3f}  abl={r['abl']:.4f}")

print("\nStage 2: other conditions")
for cond in ['no_memory', 'random_prev', 'frozen_random', 'other_write']:
    for s in SEEDS:
        if cond == 'other_write':
            o = SEEDS[(SEEDS.index(s)+1) % len(SEEDS)]
            r = train_run(cond, s, task, other_messages=traj[o])
        else:
            r = train_run(cond, s, task)
        results.append(r)
        print(f"  [{cond:15s}] seed {s}: test={r['test']:.4f}  msg_eff={r['msg_eff']:.3f}"
              + (f"  abl={r['abl']:.4f}" if r['abl'] is not None else ""))

# Aggregate
print("\n" + "="*72)
print(f"{'condition':18s}{'test (mean)':>14s}{'msg_eff':>12s}{'abl (mean)':>14s}")
print("="*72)
for cond in ['no_memory','self_write','other_write','random_prev','frozen_random']:
    rs = [r for r in results if r['condition'] == cond]
    te = np.array([r['test'] for r in rs])
    me = np.array([r['msg_eff'] for r in rs])
    abl = [r['abl'] for r in rs if r['abl'] is not None]
    abl_m = f"{np.mean(abl):.4f}" if abl else "   —   "
    print(f"{cond:18s}{te.mean():9.4f} ± {te.std():.4f}"
          f"{me.mean():9.4f} ± {me.std():.4f}    {abl_m:>10s}")

print("\n" + "="*72)
print("Per-phase test loss (can the net track drift across phases?)")
print("="*72)
for cond in ['no_memory', 'self_write', 'other_write']:
    rs = [r for r in results if r['condition'] == cond]
    phases = np.array([r['losses_by_phase'] for r in rs])  # [n_seeds, 4]
    print(f"  {cond:18s}  step 0: {phases[:,0].mean():.3f}  step 100: {phases[:,1].mean():.3f}  "
          f"step 200: {phases[:,2].mean():.3f}  step 300: {phases[:,3].mean():.3f}")

# message dynamics: do they oscillate with the drift period?
print("\n" + "="*72)
print("Message dynamics (self_write, seed 1) — does message track the drift?")
print("="*72)
log = np.array(traj[1])                # [steps, d_m]
# FFT to see if message oscillates at the drift period (T=400, freq=1/400 per step)
# projected onto its top PC
from numpy.fft import rfft, rfftfreq
msg_centered = log - log.mean(0)
# top component
U, S, Vt = np.linalg.svd(msg_centered, full_matrices=False)
top_comp = U[:, 0] * S[0]              # scalar time series
freqs = rfftfreq(len(top_comp))
spec  = np.abs(rfft(top_comp))
target_freq = 1.0 / task.period
# find index nearest target
target_idx = int(round(target_freq * len(top_comp)))
# peak and magnitude at drift freq
peak_idx = np.argmax(spec[1:]) + 1     # skip DC
print(f"  Drift fundamental freq: {target_freq:.5f} cycles/step (period {task.period})")
print(f"  Message PC1 peak freq  : {freqs[peak_idx]:.5f} cycles/step (period {1/max(freqs[peak_idx],1e-9):.1f})")
print(f"  Spectral energy at drift freq / total: "
      f"{spec[target_idx]/spec.sum():.4f}   (uniform would be ~{1/len(spec):.4f})")
