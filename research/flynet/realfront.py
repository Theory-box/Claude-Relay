"""
realfront.py — REAL connectome front-end (flyvis, Lappalainen 2024).
Feed a vibrating-beam + flicker scene through the actual connectome-constrained
fly visual network, read the true T4/T5 direction-selective motion cells,
and build a motion/amplification map. Compare beam-vs-flicker selectivity.
"""
import torch, numpy as np, flyvis
from flyvis.datasets.rendering.eye import BoxEye
from scipy.ndimage import gaussian_filter
from scipy.interpolate import griddata
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

net = flyvis.NetworkView('flow/0000/000').init_network()
eye = BoxEye()
rc = np.array(eye.receptor_centers).astype(np.float32)   # (721,2), range ~[-195,195]
FRAME = float(eye.min_frame_size[0])                     # 391

S, T, NCYC = 220, 48, 6
rng = np.random.default_rng(0)
yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
def osc(t): return np.sin(2*np.pi*NCYC*t/T)
vid = np.full((T,S,S), 0.5, np.float32)
beam_col, flk = 85, (slice(55,95), slice(128,164))
for t in range(T):
    cx = beam_col + 0.9*osc(t)
    m = ((yy>40)&(yy<180)).astype(np.float32)
    vid[t] += 0.4*np.exp(-((xx-cx)**2)/(2*3.0**2))*m     # swaying beam
vid[:, flk[0], flk[1]] += 0.18*rng.standard_normal((T, 40, 36)).astype(np.float32)  # flicker
vid += 0.03*rng.standard_normal((T,S,S)).astype(np.float32)
vid = np.clip(vid,0,1)

# ---- through the REAL connectome ----
hexv = eye(torch.tensor(vid)[None])                      # (1,T,1,721)
la = net.simulate(hexv, 0.02, as_layer_activity=True)

def tbp(x, ncyc=NCYC, half=3):                            # temporal bandpass (motion band)
    Xf=np.fft.rfft(x,axis=0); mm=np.zeros(Xf.shape[0],bool); mm[max(ncyc-half,1):ncyc+half+1]=True
    Xf[~mm]=0; return np.fft.irfft(Xf,n=x.shape[0],axis=0)

# in-band power of the real direction-selective cells, pooled over all 8 subtypes
M = np.zeros(721, np.float32)
for st in ['T4a','T4b','T4c','T4d','T5a','T5b','T5c','T5d']:
    a = getattr(la, st)[0].detach().numpy()              # (T,721)
    M += tbp(a).var(0)

# map hexal positions -> image coords
pos = (rc + FRAME/2) / FRAME * S                         # (721,2) in [0,S]
py, px = pos[:,0], pos[:,1]
def in_region(r):
    ys,xs = r; return (py>=ys.start)&(py<ys.stop)&(px>=xs.start)&(px<xs.stop)
beam_reg = (slice(40,180), slice(int(beam_col-8),int(beam_col+8)))
mask_beam, mask_flk = in_region(beam_reg), in_region(flk)
mb, mf = np.median(M[mask_beam]), np.median(M[mask_flk])
print(f'REAL connectome T4/T5 in-band motion power:')
print(f'  beam(signal)   median = {mb:.3e}   ({mask_beam.sum()} hexals)')
print(f'  flicker(noise) median = {mf:.3e}   ({mask_flk.sum()} hexals)')
print(f'  beam / flicker selectivity = {mb/max(mf,1e-12):.2f}x')

# back-project M to a 2D map for visualization
gy, gx = np.mgrid[0:S, 0:S]
amap = griddata(pos, M, (gy, gx), method='linear', fill_value=0)
amap = gaussian_filter(np.nan_to_num(amap), 2.0)

fig,ax=plt.subplots(1,2,figsize=(8.5,3.6))
ax[0].imshow(vid[T//4],cmap='gray'); ax[0].set_title('scene (beam + flicker)')
ax[1].imshow(amap,cmap='magma',vmin=0,vmax=np.percentile(amap,99.5))
ax[1].set_title('REAL connectome T4/T5 motion map')
for a in ax: a.axis('off')
fig.savefig('/home/claude/flynet/real_connectome_map.png',dpi=110,bbox_inches='tight')
print('wrote real_connectome_map.png')
