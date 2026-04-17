"""
SESSION 05 — Write-to-future-self

The network emits a message m each step that persists and is read by the next
forward pass. Tied weights mean W_m serves both reading (incorporating m_{t-1}
into current hidden) and writing (producing m_t from current hidden).

    Read:    z1 = W1 x + b1 + W_m · m_prev           [m_prev stop-grad]
             h  = tanh(z1)
             y  = W_out · h + b_out
    Write:   m_new = W_m^T · mean(h) + b_m           [mean over batch]

Stop-gradient on m_prev when read: no BPTT. The write-to-future-self mechanism
only gets gradient signal through the READ direction of W_m; because W_m is
tied, what-to-write evolves implicitly as what-to-read-usefully evolves.

Mini-batch training: each step sees a different batch, so messages can actually
encode batch-to-batch information rather than being trivially redundant.

Conditions (5 seeds each):
  no_memory      : W_m disabled (baseline)
  self_write     : real thing; network reads its own previous message
  random_prev    : reads fresh random noise each step
  frozen_random  : reads a fixed random vector (init, never updated)
  other_write    : reads another seed's messages (staged, like session 4)
"""
import numpy as np

# ------------------------------------------------------------------
# Task — teacher regression, mini-batched
# ------------------------------------------------------------------
def make_task(seed=0, N_train=1000, N_test=300, d_in=8, d_out=4, d_latent=3):
    r = np.random.default_rng(seed)
    Wt1 = r.normal(0, 1/np.sqrt(d_in), (20, d_in)); bt1 = np.zeros(20)
    Wt2 = r.normal(0, 1/np.sqrt(20),  (d_out, 20)); bt2 = np.zeros(d_out)
    def teacher(X):
        return np.tanh(X @ Wt1.T + bt1) @ Wt2.T + bt2
    B_embed = r.normal(0, 1, (d_latent, d_in))
    _, _, Vt = np.linalg.svd(B_embed, full_matrices=True)
    null_basis = Vt[d_latent:].T
    def on(N):
        z = r.normal(0, 1, (N, d_latent)); return z @ B_embed
    def off(N):
        z = r.normal(0, 1, (N, null_basis.shape[1])); return z @ null_basis.T
    X_tr = on(N_train); Y_tr = teacher(X_tr) + 0.02*r.normal(0,1,(N_train,d_out))
    X_te = on(N_test);  Y_te = teacher(X_te)
    X_off = off(N_test)*3.0; Y_off = teacher(X_off)
    return dict(X_tr=X_tr, Y_tr=Y_tr, X_te=X_te, Y_te=Y_te,
                X_off=X_off, Y_off=Y_off, d_in=d_in, d_out=d_out)

# ------------------------------------------------------------------
# MLP with persistent message channel
# ------------------------------------------------------------------
class MessageMLP:
    def __init__(self, d_in, d_hid, d_out, d_m, seed=0, disable_memory=False):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in),  (d_hid, d_in))
        self.b1 = np.zeros(d_hid)
        self.Wm = r.normal(0, 0.1/np.sqrt(d_m), (d_hid, d_m))  # small init
        self.bm = np.zeros(d_m)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid))
        self.bo = np.zeros(d_out)
        self.disable_memory = disable_memory
        self.d_hid, self.d_m = d_hid, d_m

    def forward(self, X, m_prev):
        # m_prev: [d_m]
        read_bias = 0.0 if self.disable_memory else (self.Wm @ m_prev)   # [d_hid]
        z1 = X @ self.W1.T + self.b1 + read_bias
        h  = np.tanh(z1)
        y  = h @ self.Wo.T + self.bo
        if self.disable_memory:
            m_new = m_prev                            # don't update
        else:
            h_mean = h.mean(0)                        # [d_hid]
            m_new  = self.Wm.T @ h_mean + self.bm     # [d_m]
        return y, h, m_new

    def train_step(self, X, Y, m_prev, lr):
        Yp, h, m_new = self.forward(X, m_prev)
        err = Yp - Y; N = X.shape[0]
        gWo = err.T @ h / N
        gbo = err.mean(0)
        dh  = err @ self.Wo
        dz1 = dh * (1 - h**2)
        gW1 = dz1.T @ X / N
        gb1 = dz1.mean(0)
        self.W1 -= lr*gW1; self.b1 -= lr*gb1
        self.Wo -= lr*gWo; self.bo -= lr*gbo
        # gradient to Wm via read direction only:
        # z1 = ... + Wm @ m_prev  →  dWm[i,j] = sum_n dz1[n,i] * m_prev[j] / N
        if not self.disable_memory:
            gWm = np.outer(dz1.mean(0), m_prev)
            self.Wm -= lr * gWm
            # note: bm doesn't get gradient through read (m_prev is stop-grad), and
            # we don't backprop through write either, so bm just stays
        return (err**2).mean(), m_new

# ------------------------------------------------------------------
# Message providers per condition
# ------------------------------------------------------------------
def make_message_provider(condition, seed, d_m, other_messages=None):
    """Returns a function (step, net, batch_X, m_prev_real) -> m_to_read.
    Also returns initial m_0."""
    rng = np.random.default_rng(seed + 888)
    m0 = np.zeros(d_m)

    if condition == 'no_memory':
        # ignored — network has disable_memory=True
        return (lambda t, net, X, m_prev_real: np.zeros(d_m)), m0
    if condition == 'self_write':
        return (lambda t, net, X, m_prev_real: m_prev_real), m0
    if condition == 'random_prev':
        return (lambda t, net, X, m_prev_real: rng.normal(0, 1, d_m)), m0
    if condition == 'frozen_random':
        fixed = rng.normal(0, 1, d_m)
        return (lambda t, net, X, m_prev_real: fixed), fixed.copy()
    if condition == 'other_write':
        # other_messages: list of messages from another seed's training, index by step
        if other_messages is None:
            raise ValueError("other_write needs other_messages")
        def prov(t, net, X, m_prev_real):
            idx = min(t, len(other_messages) - 1)
            return other_messages[idx]
        return prov, m0
    raise ValueError(condition)

# ------------------------------------------------------------------
# Train one run
# ------------------------------------------------------------------
def train_run(condition, seed, task, steps=2500, batch=64, lr=0.05,
              d_m=8, other_messages=None, record_messages=False):
    d_in, d_out = task['d_in'], task['d_out']
    d_hid = 24
    disable = (condition == 'no_memory')
    net = MessageMLP(d_in, d_hid, d_out, d_m, seed=seed, disable_memory=disable)

    provider, m_prev_real = make_message_provider(condition, seed, d_m, other_messages)
    rng = np.random.default_rng(seed)

    message_log = [] if record_messages else None
    for t in range(steps):
        # sample mini-batch
        idx = rng.integers(0, task['X_tr'].shape[0], batch)
        Xb, Yb = task['X_tr'][idx], task['Y_tr'][idx]
        # choose what the net READS this step (differs per condition)
        m_to_read = provider(t, net, Xb, m_prev_real)
        # train, getting the net's ACTUAL write (what it would write)
        _, m_actual = net.train_step(Xb, Yb, m_to_read, lr)
        # update the "real" self-message (for self_write) based on actual write
        m_prev_real = m_actual
        if record_messages:
            message_log.append(m_actual.copy())

    # eval
    def eval_on(X, Y):
        # at test, read whatever the last message was (or zero for no_memory)
        m_read = provider(steps-1, net, X, m_prev_real)
        Yp, _, _ = net.forward(X, m_read); return ((Yp - Y)**2).mean(), Yp

    tr,_   = eval_on(task['X_tr'],  task['Y_tr'])
    te, _  = eval_on(task['X_te'],  task['Y_te'])
    off,_  = eval_on(task['X_off'], task['Y_off'])

    # ablation: zero message at test
    if not disable:
        Yp_abl, _, _ = net.forward(task['X_te'], np.zeros(d_m))
        abl_te = ((Yp_abl - task['Y_te'])**2).mean()
        Yp_abl_off, _, _ = net.forward(task['X_off'], np.zeros(d_m))
        abl_off = ((Yp_abl_off - task['Y_off'])**2).mean()
    else:
        abl_te = abl_off = None

    # message usage: how much does output change when we zero the message?
    if not disable:
        m_test = provider(steps-1, net, task['X_te'], m_prev_real)
        Yp_live, _, _ = net.forward(task['X_te'], m_test)
        Yp_zero, _, _ = net.forward(task['X_te'], np.zeros(d_m))
        msg_effect = float(np.sqrt(((Yp_live - Yp_zero)**2).mean()))
    else:
        msg_effect = 0.0

    return dict(condition=condition, seed=seed,
                train=tr, test=te, off=off,
                abl_te=abl_te, abl_off=abl_off,
                msg_effect=msg_effect, message_log=message_log)

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
SEEDS = [1, 2, 3, 4, 5]
task = make_task()
print(f"Task: {task['X_tr'].shape[0]} train (mini-batch), d_in={task['d_in']}, d_out={task['d_out']}\n")

results = []

# Stage 1: run self_write first, record message trajectories for other_write
print("Stage 1: self_write (records message trajectories)")
message_trajectories = {}
for s in SEEDS:
    r = train_run('self_write', s, task, record_messages=True)
    message_trajectories[s] = r['message_log']
    results.append(r)
    print(f"  seed {s}: train={r['train']:.4f}  test={r['test']:.4f}  "
          f"off={r['off']:.3f}  msg_eff={r['msg_effect']:.3f}")

# Stage 2: other conditions
print("\nStage 2: other conditions")
for cond in ['no_memory', 'random_prev', 'frozen_random', 'other_write']:
    for s in SEEDS:
        if cond == 'other_write':
            other_seed = SEEDS[(SEEDS.index(s)+1) % len(SEEDS)]
            omsg = message_trajectories[other_seed]
            r = train_run(cond, s, task, other_messages=omsg)
        else:
            r = train_run(cond, s, task)
        results.append(r)
        print(f"  [{cond:15s}] seed {s}: train={r['train']:.4f}  test={r['test']:.4f}  "
              f"off={r['off']:.3f}  msg_eff={r['msg_effect']:.3f}")

# ------------------------------------------------------------------
# Aggregate
# ------------------------------------------------------------------
print("\n" + "="*78)
print(f"{'condition':18s}{'train':>9s}{'test':>9s}{'off':>9s}"
      f"{'msg_eff':>10s}{'abl_te':>10s}{'abl_off':>10s}")
print("="*78)
for cond in ['no_memory','self_write','other_write','random_prev','frozen_random']:
    rs = [r for r in results if r['condition'] == cond]
    tr = np.array([r['train'] for r in rs])
    te = np.array([r['test']  for r in rs])
    off= np.array([r['off']   for r in rs])
    me = np.array([r['msg_effect'] for r in rs])
    abl_te  = [r['abl_te']  for r in rs if r['abl_te']  is not None]
    abl_off = [r['abl_off'] for r in rs if r['abl_off'] is not None]
    abl_te_m  = np.mean(abl_te)  if abl_te  else float('nan')
    abl_off_m = np.mean(abl_off) if abl_off else float('nan')
    abl_te_str  = f"{abl_te_m:.4f}" if not np.isnan(abl_te_m)  else "   —   "
    abl_off_str = f"{abl_off_m:.3f}" if not np.isnan(abl_off_m) else "   —   "
    print(f"{cond:18s}{tr.mean():9.4f}{te.mean():9.4f}{off.mean():9.3f}"
          f"{me.mean():10.3f}{abl_te_str:>10s}{abl_off_str:>10s}")
    print(f"{'  ± std':18s}{tr.std():9.4f}{te.std():9.4f}{off.std():9.3f}"
          f"{me.std():10.3f}")

# ------------------------------------------------------------------
# Probe: what do messages look like over training?
# ------------------------------------------------------------------
print("\n" + "="*78)
print("Message dynamics (self_write, seed 1):")
print("="*78)
log = message_trajectories[1]
log = np.array(log)  # [steps, d_m]
print(f"  Shape: {log.shape}")
print(f"  Norm at t=0:      {np.linalg.norm(log[0]):.4f}")
print(f"  Norm at t=500:    {np.linalg.norm(log[500]):.4f}")
print(f"  Norm at t=1500:   {np.linalg.norm(log[1500]):.4f}")
print(f"  Norm at t=2499:   {np.linalg.norm(log[-1]):.4f}")
print(f"  Cosine(t=500, t=2499): {log[500]@log[-1]/(np.linalg.norm(log[500])*np.linalg.norm(log[-1])+1e-12):.4f}")
print(f"  Cosine(t=2000, t=2499): {log[2000]@log[-1]/(np.linalg.norm(log[2000])*np.linalg.norm(log[-1])+1e-12):.4f}")
# how much does the message change step-to-step?
diffs = np.linalg.norm(np.diff(log, axis=0), axis=1)
print(f"  Mean step-to-step ||Δm||: early={diffs[:100].mean():.4f}, late={diffs[-100:].mean():.4f}")

# across seeds, do messages converge to similar directions?
end_msgs = np.array([message_trajectories[s][-1] for s in SEEDS])
print(f"\n  End messages across 5 seeds:")
for i in range(5):
    for j in range(i+1, 5):
        cos = end_msgs[i] @ end_msgs[j] / (np.linalg.norm(end_msgs[i])*np.linalg.norm(end_msgs[j])+1e-12)
        print(f"    seed {SEEDS[i]} vs seed {SEEDS[j]}:  cos = {cos:.4f}")
