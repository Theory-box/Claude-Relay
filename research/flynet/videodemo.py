"""
videodemo.py — vibrating cantilever beam, standard EVM vs fly-gated EVM.
Self-contained minimal Eulerian magnification (no external app).
Both methods get the SAME total amplification budget; only the spatial distribution differs.
"""
import numpy as np
from scipy.ndimage import gaussian_filter1d, gaussian_filter
import imageio.v2 as imageio

rng = np.random.default_rng(0)
H, W, T = 120, 200, 100
NCYC = 6                                  # vibration cycles over the clip
A_TOP = 0.9                               # sub-pixel sway amplitude at the free end
BASE, BEAMB = 0.35, 0.55                  # background / beam brightness

# ---------- build the synthetic video ----------
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
x0 = 70.0                                 # beam rest column
mode = ((H-1-yy)/(H-1))**2                # cantilever mode shape: sway grows toward top
vid = np.empty((T, H, W), np.float32)
for t in range(T):
    disp = A_TOP*mode*np.sin(2*np.pi*NCYC*t/T)     # per-row horizontal displacement
    cx = x0 + disp
    beam = BEAMB*np.exp(-((xx-cx)**2)/(2*3.0**2))  # smooth (sub-pixel) gaussian bar
    frame = BASE + beam
    vid[t] = frame
# flicker region (a 'noisy light' patch, NO motion) — same intensity swing as the beam edge
flk = (slice(20,55), slice(150,185))
vid[:, flk[0], flk[1]] += 0.12*rng.standard_normal((T, 35, 35)).astype(np.float32)
# broadband sensor noise everywhere
vid += 0.03*rng.standard_normal((T,H,W)).astype(np.float32)

# ---------- temporal bandpass (isolate the vibration band) ----------
def temporal_bandpass(v, ncyc=NCYC, half=3):
    Vf = np.fft.rfft(v, axis=0)
    mask = np.zeros(Vf.shape[0], bool); mask[max(ncyc-half,1):ncyc+half+1] = True
    Vf[~mask] = 0
    return np.fft.irfft(Vf, n=v.shape[0], axis=0).astype(np.float32)

band = temporal_bandpass(vid)

# ---------- fly direction-selective map (biological Reichardt, horizontal) ----------
def fly_map(v):
    # Fly motion pathway, honestly rendered: temporal band-tuning + wide-field spatial pooling.
    # Coherent motion (edge moves in phase) survives spatial blur; incoherent flicker cancels.
    hp = v - v.mean(0, keepdims=True)
    hp = gaussian_filter(hp, (0,0.8,0.8))                  # optics: finite acceptance angle
    band = temporal_bandpass(hp)                           # frequency-tuned motion channel
    P = band.var(0)                                        # in-band temporal power (per pixel)
    Pcoh = gaussian_filter(band, (0,2.0,2.0)).var(0)       # power that SURVIVES spatial pooling
    coh = gaussian_filter(Pcoh,1.0) / (gaussian_filter(P,1.0) + 1e-8)   # spatial-coherence gate [0..1]
    return gaussian_filter(coh, 1.5)

M = fly_map(vid)

# ---------- amplification maps on EQUAL budget ----------
ALPHA = 28.0
global_map = np.full((H,W), ALPHA, np.float32)
fly = M/ (M.mean()+1e-9) * ALPHA                            # same mean as global -> same total budget
fly = np.clip(fly, 0, ALPHA*8)

def magnify(v, band, amap):
    return np.clip(v + amap[None]*band, 0, 1)

std_evm = magnify(vid, band, global_map)
fly_evm = magnify(vid, band, fly)

# ---------- metrics: variance amplification by region ----------
beam_col = (slice(0,70), slice(60,82))     # around the swaying beam
def tvar(v, reg): return v[:, reg[0], reg[1]].var(0).mean()
print("temporal-variance amplification (after / before):")
for nm, out in [("standard EVM", std_evm), ("fly-gated EVM", fly_evm)]:
    beam_gain = tvar(out, beam_col)/tvar(vid, beam_col)
    flk_gain  = tvar(out, flk)/tvar(vid, flk)
    print(f"  {nm:14s} beam(signal) x{beam_gain:5.1f}   flicker(noise) x{flk_gain:5.1f}   ratio signal/noise = {beam_gain/flk_gain:5.2f}")

# ---------- render ----------
def to8(a): return (np.clip(a,0,1)*255).astype(np.uint8)
def label(img, text):                       # crude text via PIL
    from PIL import Image, ImageDraw
    im = Image.fromarray(img); d = ImageDraw.Draw(im); d.text((4,2), text, fill=255); return np.array(im)

frames = []
gap = np.full((H,6), 255, np.uint8)
for t in range(0,T,2):
    a = label(to8(vid[t]), "original")
    b = label(to8(std_evm[t]), "standard EVM")
    c = label(to8(fly_evm[t]), "fly-gated EVM")
    frames.append(np.concatenate([a,gap,b,gap,c], axis=1))
imageio.mimsave('/home/claude/flynet/beam_sidebyside.gif', frames, duration=0.08, loop=0)

# heatmap of the two alpha strategies
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
fig,ax = plt.subplots(1,3,figsize=(11,3.2))
ax[0].imshow(vid[T//4],cmap='gray'); ax[0].set_title('scene (beam + flicker patch)')
im1=ax[1].imshow(global_map,cmap='magma',vmin=0,vmax=fly.max()); ax[1].set_title('standard: flat budget')
im2=ax[2].imshow(fly,cmap='magma',vmin=0,vmax=fly.max()); ax[2].set_title('fly: budget on real motion')
for a_ in ax: a_.axis('off')
fig.colorbar(im2,ax=ax,fraction=0.025,label='amplification alpha')
fig.savefig('/home/claude/flynet/alpha_heatmap.png',dpi=110,bbox_inches='tight')

# a still frame at peak sway
peak = int(T*(0.25))
still = np.concatenate([to8(vid[peak]), gap, to8(std_evm[peak]), gap, to8(fly_evm[peak])],axis=1)
imageio.imwrite('/home/claude/flynet/beam_still.png', still)
print("wrote beam_sidebyside.gif, alpha_heatmap.png, beam_still.png")
