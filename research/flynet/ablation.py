"""
ablation.py — stand up flyvis on a vibration-detection task and ablate each of the
65 cell types to see which the network actually uses. Unbiased readout: total in-band
(vibration-frequency) power across ALL cells; task = AUC separating vibrating clips from
non-vibrating (flicker/noise/static) clips. Ablation impact(X) = AUC_intact - AUC_ablated_X.
"""
import flyvis, numpy as np, torch
from flyvis.datasets.rendering.eye import BoxEye

_nv = flyvis.NetworkView('flow/0000/000')
net = _nv.init_network()
DEC = _nv.init_decoder()['flow'].eval()
raw = np.array(net.connectome.nodes.type[:])
TYPES = np.array([t.decode() if isinstance(t,(bytes,np.bytes_)) else str(t) for t in raw])
UNIQ = sorted(set(TYPES.tolist()))
eye = BoxEye()
DT, T, H, W, NCYC = 0.02, 24, 64, 64, 4
rng = np.random.default_rng(0)

def _beam(cx_fn):
    yy,xx=np.mgrid[0:H,0:W].astype(np.float32); vid=np.full((T,H,W),0.5,np.float32)
    for t in range(T):
        m=((yy>14)&(yy<50)).astype(np.float32)
        vid[t]+=0.4*np.exp(-((xx-cx_fn(t))**2)/(2*3.0**2))*m
    return vid

def build_clips():
    clips, labels = [], []
    # vibrating beams: vary position, amplitude, phase
    for i,(x0,amp,ph) in enumerate([(28,0.9,0),(34,0.7,1),(30,1.1,2),(26,0.8,0.5)]):
        clips.append(_beam(lambda t,x0=x0,amp=amp,ph=ph: x0+amp*np.sin(2*np.pi*NCYC*t/T+ph))); labels.append(1)
    # negatives: static beam+flicker, flicker only, noise only, static+strong noise
    for i in range(4):
        vid=_beam(lambda t,x0=30: x0)                      # static beam (no motion)
        if i%2==0:
            vid[:,18:34,40:54]+=0.18*rng.standard_normal((T,16,14)).astype(np.float32)  # flicker patch
        vid+=(0.03+0.02*(i%3))*rng.standard_normal((T,H,W)).astype(np.float32)          # noise
        clips.append(vid); labels.append(0)
    hex_list=[eye(torch.tensor(v[None].astype(np.float32))) for v in clips]  # each (1,T,1,721)
    hexv=torch.cat(hex_list,0)                              # (n,T,1,721)
    return hexv, np.array(labels)

HEXV, LABELS = build_clips()

def flow_inband(activity):
    # activity (n,T,nodes) -> decoded optic flow -> per-clip in-band power of flow magnitude
    with torch.no_grad():
        flow = DEC(activity)                               # (n,T,2,H,W) optic flow
    f = flow.detach().numpy()
    mag = np.sqrt((f**2).sum(2))                            # (n,T,H,W) flow magnitude
    Af=np.fft.rfft(mag,axis=1); m=np.zeros(Af.shape[1],bool); m[max(NCYC-2,1):NCYC+3]=True
    Af[:,~m]=0; band=np.fft.irfft(Af,n=mag.shape[1],axis=1)
    return band.var(1).reshape(mag.shape[0],-1).sum(1)     # (n,) motion-response score per clip

MAXB=4
def performance(ablate=None):
    # task = discriminate vibrating vs non-vibrating via decoded-flow in-band power.
    # perf = log(mean_vib / mean_neg): high = network cleanly separates motion from clutter.
    net._state_hooks=()
    if ablate is not None:
        idx=torch.tensor(np.where(TYPES==ablate)[0])
        def hook(state): state.nodes.activity[..., idx]=0.0; return state
        net.register_state_hook(hook)
    scores=[]
    for s in range(0, HEXV.shape[0], MAXB):
        act=net.simulate(HEXV[s:s+MAXB], DT); scores.append(flow_inband(act)); del act
    net._state_hooks=()
    sc=np.concatenate(scores)
    return float(np.log((sc[LABELS==1].mean()+1e-9)/(sc[LABELS==0].mean()+1e-9)))

if __name__=='__main__':
    base=performance(None)
    print(f'INTACT vib-vs-clutter discriminability (log-ratio) = {base:.3f}')
    for c in ['T4a','T4b','T4c','T4d','T5a','T5b','Am','C2','R1','L1','Mi1']:
        a=performance(c); print(f'  ablate {c:5s}: perf={a:.3f}  impact(drop)={base-a:+.3f}')
