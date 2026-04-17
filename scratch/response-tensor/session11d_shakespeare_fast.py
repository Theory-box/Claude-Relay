"""
SESSION 11D (fast) — Shakespeare test

Minimal char-level next-char prediction on Shakespeare text.
Tiny architecture so it runs fast.
"""
import numpy as np

TEXT = """to be or not to be that is the question
whether tis nobler in the mind to suffer
the slings and arrows of outrageous fortune
or to take arms against a sea of troubles
and by opposing end them to die to sleep
no more and by a sleep to say we end
the heart ache and the thousand natural shocks
that flesh is heir to tis a consummation
devoutly to be wished to die to sleep
to sleep perchance to dream ay there's the rub
for in that sleep of death what dreams may come
when we have shuffled off this mortal coil
must give us pause there's the respect
that makes calamity of so long life
for who would bear the whips and scorns of time""".lower()

chars = sorted(set(TEXT))
VOCAB = {c: i for i, c in enumerate(chars)}
V = len(chars)
CTX = 4

text_idx = np.array([VOCAB[c] for c in TEXT])
N = len(text_idx) - CTX
X_idx = np.stack([text_idx[i:i+CTX] for i in range(N)])
Y_idx = text_idx[CTX:]

X_full = np.zeros((N, CTX*V), dtype=np.float32)
for i in range(N):
    for c in range(CTX):
        X_full[i, c*V + X_idx[i, c]] = 1.0

perm = np.random.default_rng(0).permutation(N)
ntr = int(0.85*N)
X_tr = X_full[perm[:ntr]]; Y_tr = Y_idx[perm[:ntr]]
X_te = X_full[perm[ntr:]]; Y_te = Y_idx[perm[ntr:]]
print(f"Vocab={V}, context={CTX}, samples={N} ({ntr} train / {N-ntr} test), "
      f"input_dim={CTX*V}")

class MLP:
    def __init__(self, d_in, d_hid, d_out, seed=0):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, 1/np.sqrt(d_in), (d_hid, d_in)).astype(np.float32)
        self.b1 = np.zeros(d_hid, dtype=np.float32)
        self.Wo = r.normal(0, 1/np.sqrt(d_hid), (d_out, d_hid)).astype(np.float32)
        self.bo = np.zeros(d_out, dtype=np.float32)
    def forward(self, X):
        Z1 = X @ self.W1.T + self.b1
        H = np.tanh(Z1)
        return H @ self.Wo.T + self.bo, H
    def params(self): return [self.W1, self.b1, self.Wo, self.bo]

def softmax(z):
    z = z - z.max(axis=-1, keepdims=True); e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)

def ce_grad(net, X, Y):
    logits, H = net.forward(X); probs = softmax(logits); n = X.shape[0]
    err = probs.copy(); err[np.arange(n), Y] -= 1.0; err /= n
    gWo = err.T @ H; gbo = err.sum(0)
    dH = err @ net.Wo; dZ1 = dH * (1 - H**2)
    gW1 = dZ1.T @ X; gb1 = dZ1.sum(0)
    return [gW1, gb1, gWo, gbo]

def distill_grad(net, X, T):
    logits, H = net.forward(X); err = (logits - T) / X.shape[0]
    gWo = err.T @ H; gbo = err.sum(0)
    dH = err @ net.Wo; dZ1 = dH * (1 - H**2)
    gW1 = dZ1.T @ X; gb1 = dZ1.sum(0)
    return [gW1, gb1, gWo, gbo]

def apply(net, grads, lr):
    for p, g in zip(net.params(), grads): p -= lr * g

def test_ce(net, X, Y):
    probs = softmax(net.forward(X)[0])
    return float(-np.log(probs[np.arange(len(Y)), Y] + 1e-12).mean())

def func_dist(a, b, X):
    pa = softmax(a.forward(X)[0]); pb = softmax(b.forward(X)[0])
    return float(np.sqrt(((pa - pb)**2).mean()))

D_HID = 32
D_IN = CTX * V
print(f"Architecture: {D_IN} → {D_HID} → {V}, params ≈ "
      f"{D_IN*D_HID + D_HID + D_HID*V + V}")

def train(seed, P=None, T=None, lam=0.0, steps=4000, lr=0.05):
    net = MLP(D_IN, D_HID, V, seed=seed)
    for t in range(steps):
        apply(net, ce_grad(net, X_tr, Y_tr), lr)
        if P is not None and t % 3 == 0 and lam > 0:
            apply(net, distill_grad(net, P, T), lr * lam)
    return net

print("\nTraining anchor A ...")
# Show trajectory
A = MLP(D_IN, D_HID, V, seed=1)
for step in range(4000):
    apply(A, ce_grad(A, X_tr, Y_tr), 0.05)
    if step % 1000 == 0:
        print(f"  step {step}: train CE={test_ce(A, X_tr, Y_tr):.3f}  test CE={test_ce(A, X_te, Y_te):.3f}")
A_ce = test_ce(A, X_te, Y_te)
print(f"  A final test CE: {A_ce:.3f}  (uniform ref = {np.log(V):.3f})")

print("Training baseline C (indep) ...")
C = train(seed=77)
C_ce = test_ce(C, X_te, Y_te)
BASELINE = func_dist(A, C, X_te)
print(f"  C test CE: {C_ce:.3f}  ||f_A - f_C||={BASELINE:.4f}")

# Uniform distribution baseline (no training)
uniform_probs = np.ones(V) / V
rand_dist = np.sqrt(((softmax(A.forward(X_te)[0]) - uniform_probs)**2).mean())
print(f"  Random-uniform ref ||f_A - unif||={rand_dist:.4f}")
print()

print("="*70)
print("Signature matching at various K")
print("="*70)
print(f"{'K':>6s}{'lam':>6s}{'||f_A-f_B||':>14s}{'recovery':>12s}{'test CE':>12s}")
print("-"*70)

seeds = [55, 66]
results = {}
for K in [4, 16, 64, min(ntr, 256)]:
    lam = {4: 0.3, 16: 1.0, 64: 1.5, 256: 1.0}.get(K, 0.5)
    rng = np.random.default_rng(1000 + K)
    idx = rng.choice(ntr, K, replace=False)
    P = X_tr[idx]; T = A.forward(P)[0]
    dists = []; ces = []
    for s in seeds:
        B = train(seed=s, P=P, T=T, lam=lam)
        dists.append(func_dist(A, B, X_te))
        ces.append(test_ce(B, X_te, Y_te))
    md = np.mean(dists); mce = np.mean(ces)
    imp = 100 * (1 - md / BASELINE)
    results[K] = (md, imp, mce)
    bar = "▓" * max(0, int(imp/2))
    print(f"{K:>6d}{lam:>6.1f}{md:>12.4f}{imp:>+10.1f}%{mce:>12.3f}  {bar}")

# full dataset
P_full = X_tr; T_full = A.forward(P_full)[0]
dists_f = []; ces_f = []
for s in seeds:
    B = train(seed=s, P=P_full, T=T_full, lam=0.5)
    dists_f.append(func_dist(A, B, X_te))
    ces_f.append(test_ce(B, X_te, Y_te))
md_f = np.mean(dists_f); mce_f = np.mean(ces_f)
imp_f = 100 * (1 - md_f / BASELINE)
print(f"{ntr:>6d}{1.0:>6.1f}{md_f:>12.4f}{imp_f:>+10.1f}%{mce_f:>12.3f}  {'▓'*max(0,int(imp_f/2))}   ← full")

print("\n" + "="*70)
print("Generalization check: same pattern as teacher-regression task?")
print("="*70)
print(f"  Teacher task best (from 11C): +52% at K=128, lam=8")
print(f"  Shakespeare best: ", end="")
best_K = max(list(results.keys()) + [ntr],
              key=lambda k: (results[k][1] if k in results else imp_f))
if best_K in results:
    print(f"K={best_K} → {results[best_K][1]:+.1f}%")
else:
    print(f"K=full → {imp_f:+.1f}%")

# Does the "sparse beats full" pattern hold?
max_sparse = max([v[1] for v in results.values()])
print(f"\n  Best sparse K: {max_sparse:+.1f}%")
print(f"  Full dataset:  {imp_f:+.1f}%")
if max_sparse > imp_f + 2:
    print("  → sparse beats full (same as teacher task)")
elif abs(max_sparse - imp_f) < 2:
    print("  → sparse ≈ full")
else:
    print("  → full beats sparse (DIFFERENT from teacher task)")
