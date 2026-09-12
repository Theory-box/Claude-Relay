"""
directionbank.py — fly-INSPIRED (not the actual connectome) oriented motion-detector bank.
Mirrors T4/T5 organization: K direction-tuned channels + wide-field pooling.
Goal: one alpha-map that covers as many motion TYPES as possible
(horizontal + vertical translation, rotation, expansion/pulsing) while rejecting flicker.
"""
import numpy as np
from scipy.ndimage import gaussian_filter
import imageio.v2 as imageio
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

rng = np.random.default_rng(0)
H, W, T = 130, 210, 90
NCYC = 6
def osc(t, ph=0): return np.sin(2*np.pi*NCYC*t/T + ph)

# ---------- multi-motion synthetic scene ----------
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
vid = np.full((T, H, W), 0.35, np.float32)
def vbar(cx, y0, y1, s=2.5, a=0.5):      # vertical bar (moves horizontally)
    m = ((yy>y0)&(yy<y1)).astype(np.float32); return a*np.exp(-((xx-cx)**2)/(2*s*s))*m
def hbar(cy, x0, x1, s=2.5, a=0.5):      # horizontal bar (moves vertically)
    m = ((xx>x0)&(xx<x1)).astype(np.float32); return a*np.exp(-((yy-cy)**2)/(2*s*s))*m
def rod(py, px, ang, L=16, s=2.0, a=0.5):# rotating rod
    dx, dy = xx-px, yy-py; perp = dx*np.sin(ang)+dy*(-np.cos(ang)); along = dx*np.cos(ang)+dy*np.sin(ang)
    return a*np.exp(-perp**2/(2*s*s))*np.exp(-along**2/(2*L*L))
def ring(py, px, r, s=2.0, a=0.5):       # pulsing ring (expansion)
    rr = np.sqrt((xx-px)**2+(yy-py)**2); return a*np.exp(-((rr-r)**2)/(2*s*s))

for t in range(T):
    f = vbar(38+0.9*osc(t), 12, 60)                    # 1: horizontal translation
    f = f + hbar(38+0.9*osc(t,1), 130, 185)            # 2: vertical translation
    f = f + rod(100, 55, 0.5+0.10*osc(t))              # 3: rotation
    f = f + ring(100, 160, 15+1.2*osc(t))              # 4: expansion / pulsing
    vid[t] += f
# flicker distractor (no motion), strong
FL = (slice(5,22), slice(92,124))
vid[:, FL[0], FL[1]] += 0.12*rng.standard_normal((T, 17, 32)).astype(np.float32)
vid += 0.03*rng.standard_normal((T,H,W)).astype(np.float32)

# region masks for scoring
regions = {'H-translate':(slice(10,62),slice(28,50)), 'V-translate':(slice(28,50),slice(128,188)),
           'rotation':(slice(82,120),slice(38,74)), 'expansion':(slice(82,120),slice(142,180)),
           'flicker':FL}

def tbp(v, ncyc=NCYC, half=3):
    Vf=np.fft.rfft(v,axis=0); m=np.zeros(Vf.shape[0],bool); m[max(ncyc-half,1):ncyc+half+1]=True
    Vf[~m]=0; return np.fft.irfft(Vf,n=v.shape[0],axis=0).astype(np.float32)

band = tbp(gaussian_filter(vid-vid.mean(0,keepdims=True),(0,0.8,0.8)))

# ---------- oriented detector (one T4/T5-like channel) ----------
def oriented(theta, D=2, pool=2.6):
    sx, sy = int(round(np.cos(theta))), int(round(np.sin(theta)))
    Ash = np.roll(np.roll(band,-sx,2),-sy,1)           # neighbor along +theta
    Ad  = np.roll(band, D, 0)                            # delayed self
    Ashd= np.roll(np.roll(Ad,-sx,2),-sy,1)              # delayed neighbor
    HR  = band*Ashd - Ash*Ad                            # opponent along theta
    HRp = gaussian_filter(HR,(0,pool,pool))             # wide-field spatial pooling
    return HRp.var(0)                                    # temporal power of pooled oriented signal

thetas = np.linspace(0, 2*np.pi, 8, endpoint=False)     # 8 directions
chans = np.stack([gaussian_filter(oriented(th),1.5) for th in thetas])  # (8,H,W)

# COVERAGE + flicker rejection = amplitude-invariant coherence gate (direction-agnostic)
P = band.var(0); Pcoh = gaussian_filter(band,(0,2.2,2.2)).var(0)
coh = gaussian_filter(Pcoh,1.2)/(gaussian_filter(P,1.2)+1e-8)     # alpha magnitude
single_h = gaussian_filter(oriented(0.0),1.5)                     # horizontal-only baseline (raw)

def med(a,r): return float(np.median(a[r[0],r[1]]))
print("alpha per region (want every motion type >> flicker):")
print(f"{'region':13s} {'single-H':>9} {'coherence gate':>15}")
for k,r in regions.items():
    print(f"{k:13s} {med(single_h/single_h.mean(),r):>9.2f} {med(coh,r):>15.3f}")
fl = med(coh, regions['flicker'])
cov = np.mean([med(coh,regions[k])>2*fl for k in regions if k!='flicker'])
print(f"\nmotion-type coverage (coherence-gate alpha > 2x flicker): {cov:.0%}  (all 4 types)")

# DIRECTION MAP: dominant direction per pixel (hue), brightness = coherence (flicker stays dark)
from matplotlib.colors import hsv_to_rgb
dom = np.argmax(chans, 0)                                          # which direction dominates
hue = dom/8.0
val = np.clip(coh/np.percentile(coh,99.5),0,1)
sat = np.ones_like(val)*0.9
dirmap = hsv_to_rgb(np.stack([hue,sat,val],-1))

fig,ax=plt.subplots(1,3,figsize=(12,3.0))
ax[0].imshow(vid[T//4],cmap='gray'); ax[0].set_title('scene: H-trans, V-trans, rotation, expansion + flicker')
ax[1].imshow(coh,cmap='magma',vmin=0,vmax=np.percentile(coh,99.5)); ax[1].set_title('coherence gate: covers all motion, flicker dark')
ax[2].imshow(dirmap); ax[2].set_title('direction bank: motion direction (hue)')
for a in ax: a.axis('off')
fig.savefig('/home/claude/flynet/bank_heatmap.png',dpi=110,bbox_inches='tight')

fig2,ax2=plt.subplots(2,4,figsize=(12,4.2))
for i,th in enumerate(thetas):
    r=ax2[i//4,i%4]; r.imshow(chans[i]*coh,cmap='magma'); r.set_title(f'{int(np.degrees(th))}deg'); r.axis('off')
fig2.suptitle('per-direction channels x coherence (each tuned to one motion direction, flicker removed)')
fig2.savefig('/home/claude/flynet/bank_channels.png',dpi=100,bbox_inches='tight')
print("wrote bank_heatmap.png, bank_channels.png")
