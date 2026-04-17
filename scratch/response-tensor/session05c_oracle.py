"""
SESSION 05C — oracle memory probe

Tests whether the memory-channel architecture CAN use temporal info at all,
separating two possible explanations for 5B's failure:
  (a) architecture is fine but optimization can't bootstrap memory usage
  (b) architecture genuinely can't exploit memory

Conditions:
  no_memory       : as before (floor)
  self_write      : as before (should match 5B)
  oracle_sin_cos  : m_prev = [sin(2πt/T), cos(2πt/T), 0, ..., 0]  (perfect phase)
  oracle_drift    : m_prev = the actual drift vector at step t (direct task info)

If oracle conditions beat no_memory → architecture works, 5B failure was bootstrap.
If oracle conditions tie no_memory → architecture itself can't use memory.
"""
import numpy as np

class DriftTask:
    def __init__(self, seed=0, N_train=1000, d_in=8, d_out=4, d_latent=3,
                 period=400, amplitude=0.6):
        r = np.random.default_rng(seed)
        Wt1 = r.normal(0, 1/np.sqrt(d_in), (20, d_in)); bt1 = np.zeros(20)
        Wt2 = r.normal(0, 1/np.sqrt(20),  (d_out, 20)); bt2 = np.zeros(d_out)
        self.teacher_fn = lambda X: np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2
        B_embed = r.normal(0, 1, (d_latent, d_in))
        self.B_embed = B_embed
        self.X_pool = self._on(N_train, r)
        self.Y_pool_base = self.teacher_fn(self.X_pool)
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
        r = np.random.default_rng(seed); X = self._on(N, r)
        Y = self.teacher_fn(X) + self.drift(t)
        return X, Y

class MessageMLP:
    def __init__(self, d_in, d_hid, d_out, d_m, seed=0, disable_memory=False):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in), (d_hid, d_in)); self.b1 = np.zeros(d_hid)
        self.Wm = r.normal(0, 0.1/np.sqrt(d_m), (d_hid, d_m)); self.bm = np.zeros(d_m)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid)); self.bo = np.zeros(d_out)
        self.disable_memory = disable_memory
        self.d_hid, self.d_m = d_hid, d_m
    def forward(self, X, m_prev):
        read = 0.0 if self.disable_memory else (self.Wm @ m_prev)
        z1 = X @ self.W1.T + self.b1 + read
        h  = np.tanh(z1); y = h @ self.Wo.T + self.bo
        if self.disable_memory: m_new = m_prev
        else: m_new = self.Wm.T @ h.mean(0) + self.bm
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

def provider_for(condition, task, d_m, seed):
    if condition == 'no_memory':
        return lambda t, m_prev_real: np.zeros(d_m)
    if condition == 'self_write':
        return lambda t, m_prev_real: m_prev_real
    if condition == 'oracle_sin_cos':
        def p(t, m_prev_real):
            m = np.zeros(d_m)
            m[0] = np.sin(2*np.pi * t / task.period)
            m[1] = np.cos(2*np.pi * t / task.period)
            return m
        return p
    if condition == 'oracle_drift':
        # feed the actual drift vector, zero-padded to d_m
        def p(t, m_prev_real):
            d = task.drift(t)              # [d_out]
            m = np.zeros(d_m)
            m[:len(d)] = d
            return m
        return p
    raise ValueError(condition)

def train_run(condition, seed, task, steps=3000, batch=64, lr=0.05, d_m=8):
    d_in, d_out = task.d_in, task.d_out
    disable = (condition == 'no_memory')
    net = MessageMLP(d_in, 24, d_out, d_m, seed=seed, disable_memory=disable)
    prov = provider_for(condition, task, d_m, seed)
    rng = np.random.default_rng(seed)
    m_prev_real = np.zeros(d_m)
    for t in range(steps):
        X, Y = task.batch(t, batch, rng)
        m_read = prov(t, m_prev_real)
        _, m_actual = net.train_step(X, Y, m_read, lr)
        m_prev_real = m_actual

    # per-phase eval
    phases = []
    for test_step in [0, 100, 200, 300]:
        X, Y = task.test_at_step(test_step)
        m_read = prov(test_step, m_prev_real)
        Yp, _, _ = net.forward(X, m_read)
        phases.append(((Yp - Y)**2).mean())
    return dict(condition=condition, seed=seed,
                test_mean=np.mean(phases), phases=phases)

# Run
SEEDS = [1,2,3,4,5]
task = DriftTask()
print(f"Task: drift period={task.period}, amp={task.amplitude}\n")

results = []
for cond in ['no_memory', 'self_write', 'oracle_sin_cos', 'oracle_drift']:
    for s in SEEDS:
        r = train_run(cond, s, task)
        results.append(r)
        print(f"  [{cond:18s}] seed {s}: mean={r['test_mean']:.4f}  "
              f"phases={[f'{p:.3f}' for p in r['phases']]}")

print("\n" + "="*70)
print(f"{'condition':20s}{'mean test':>14s}{'step 0':>10s}{'step 100':>10s}{'step 200':>10s}{'step 300':>10s}")
print("="*70)
for cond in ['no_memory', 'self_write', 'oracle_sin_cos', 'oracle_drift']:
    rs = [r for r in results if r['condition'] == cond]
    mean_arr = np.array([r['test_mean'] for r in rs])
    phases = np.array([r['phases'] for r in rs])
    print(f"{cond:20s}{mean_arr.mean():9.4f} ± {mean_arr.std():.4f}"
          f"{phases[:,0].mean():10.3f}{phases[:,1].mean():10.3f}"
          f"{phases[:,2].mean():10.3f}{phases[:,3].mean():10.3f}")
