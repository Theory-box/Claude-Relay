import numpy as np
rng = np.random.default_rng(0)
N, T = 180, 300; x = np.arange(N); I = np.zeros((T,N),np.float32); amp=0.05
k,w = 2*np.pi/12, 2*np.pi/20
R=slice(20,50); L=slice(80,110); F=slice(140,170)          # rightward / leftward / flicker
for t in range(T):
    I[t,R]+=amp*np.sin(k*x[R]-w*t)                          # rightward (target)
    I[t,L]+=amp*np.sin(k*x[L]+w*t)                          # leftward (opposite-dir contaminant)
I[:,F]+=amp*rng.standard_normal((T,F.stop-F.start)).astype(np.float32)   # flicker
I+=0.02*rng.standard_normal((T,N)).astype(np.float32)
Ihp=I-I.mean(0,keepdims=True)
# energy
alpha_e=np.r_[(np.diff(Ihp,0)**2).mean(0), 0]
# rightward-tuned Reichardt
D=2; Ir=np.roll(Ihp,-1,1); Id=np.roll(Ihp,D,0); Ird=np.roll(Ir,D,0)
HR=(Ir*Id - Ihp*Ird)[D:]
alpha_h=np.r_[np.clip(HR.mean(0),0,None),[0]*D]
def reg(a): 
    n=a/np.median(a[R]); return [1.0, float(np.median(n[L])), float(np.median(n[F]))]
e=reg(alpha_e); h=reg(alpha_h)
print('region:        rightward(target)  leftward(opp)   flicker(noise)')
print(f'motion-energy   {e[0]:6.2f}            {e[1]:6.2f}          {e[2]:6.2f}')
print(f'fly Reichardt   {h[0]:6.2f}            {h[1]:6.2f}          {h[2]:6.2f}')
import json; print('CHART', json.dumps({'energy':e,'hr':h}))
