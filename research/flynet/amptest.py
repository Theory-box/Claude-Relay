import numpy as np
rng = np.random.default_rng(0)

# ---- synthetic scene: space N x time T ----
N, T = 160, 300
x = np.arange(N)
I = np.zeros((T, N), np.float32)
amp = 0.05                         # tiny sub-threshold amplitude (both signal & flicker)

# SIGNAL patch [30:60]: coherent RIGHTWARD drifting grating (real directional motion)
sig = slice(30, 60)
k, w = 2*np.pi/12, 2*np.pi/20      # spatial & temporal freq
for t in range(T):
    I[t, sig] += amp*np.sin(k*x[sig] - w*t)

# FLICKER patch [100:130]: same amplitude, temporal noise, NO spatial motion
flk = slice(100, 130)
I[:, flk] += amp*rng.standard_normal((T, flk.stop-flk.start)).astype(np.float32)

# broadband sensor noise everywhere
I += 0.02*rng.standard_normal((T, N)).astype(np.float32)

# temporal high-pass (contrast, like photoreceptor/lamina) : subtract slow mean
Ihp = I - I.mean(0, keepdims=True)

# ---- Detector A: motion ENERGY (direction-agnostic) ----
dt = np.diff(Ihp, axis=0)
alpha_energy = (dt**2).mean(0)                       # per-pixel temporal power
alpha_energy = np.r_[alpha_energy, alpha_energy[-1]]

# ---- Detector B: fly-style REICHARDT (direction-selective, opponent) ----
D = 2                                                # delay (frames)
Ir = np.roll(Ihp, -1, axis=1)                        # neighbor to the right
Id = np.roll(Ihp,  D, axis=0)                        # delayed self
Ird = np.roll(Ir,  D, axis=0)                        # delayed neighbor
right = Ir*Id
left  = Ihp*Ird
HR = (right - left)[D:]                              # opponent; + = rightward
alpha_hr = np.clip(HR.mean(0), 0, None)              # rightward-tuned amplification map
alpha_hr = np.r_[alpha_hr, [alpha_hr[-1]]*D]

def sep(a):
    s = np.median(a[sig]); f = np.median(a[flk]); b = np.median(a[:20])  # blank baseline
    return s, f, s/max(f,1e-9), s/max(b,1e-9)

for name, a in [('motion-energy', alpha_energy), ('fly Reichardt', alpha_hr)]:
    s,f,sf,sb = sep(a)
    print(f'{name:14s}  signal={s:.2e}  flicker={f:.2e}  signal/flicker={sf:6.1f}x  signal/blank={sb:6.1f}x')

np.save('/tmp/ae.npy', alpha_energy); np.save('/tmp/ah.npy', alpha_hr)
