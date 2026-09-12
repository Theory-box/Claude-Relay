import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.stats import rankdata

def scene(noise, rng, N=180, T=300, amp=0.05):
    x=np.arange(N); I=np.zeros((T,N),np.float32); k,w=2*np.pi/12,2*np.pi/20
    R=slice(20,50); F=slice(140,170)
    for t in range(T): I[t,R]+=amp*np.sin(k*x[R]-w*t)
    I[:,F]+=amp*rng.standard_normal((T,F.stop-F.start)).astype(np.float32)
    I+=noise*rng.standard_normal((T,N)).astype(np.float32)
    return I,R,F

def a_energy(I):
    Ihp=I-I.mean(0,keepdims=True); return np.r_[(np.diff(Ihp,0)**2).mean(0),0]
def a_hr_ideal(I,D=2):
    Ihp=I-I.mean(0,keepdims=True); Ir=np.roll(Ihp,-1,1); Id=np.roll(Ihp,D,0); Ird=np.roll(Ir,D,0)
    return np.r_[np.clip((Ir*Id-Ihp*Ird)[D:].mean(0),0,None),[0]*D]
def a_hr_bio(I,rng,D=2):
    Ihp=I-I.mean(0,keepdims=True); Ihp=gaussian_filter1d(Ihp,1.0,axis=1)
    lp=gaussian_filter1d(Ihp,1.2,axis=0)
    neu=lambda a: np.tanh(3*(a+0.015*rng.standard_normal(a.shape).astype(np.float32)))
    A=neu(Ihp); B=neu(lp); Ar=np.roll(A,-1,1); Bd=np.roll(B,D,0); Bdr=np.roll(np.roll(B,-1,1),D,0)
    return np.r_[np.clip((Ar*Bd-A*Bdr)[D:].mean(0),0,None),[0]*D]

def auc(a,R,F):                       # P(signal pixel alpha > flicker pixel alpha)
    s=a[R]; f=a[F]; n1,n2=len(s),len(f)
    r=rankdata(np.r_[s,f]); return (r[:n1].sum()-n1*(n1+1)/2)/(n1*n2)

noises=[0.01,0.02,0.05,0.1,0.2]; TR=10
rows={'energy':[],'ideal':[],'bio':[]}
print(f'{"noise":>6} {"energy":>8} {"HR ideal":>9} {"HR bio":>8}   (AUC: 1=perfect, .5=chance)')
for nz in noises:
    ee,ii,bb=[],[],[]
    for tr in range(TR):
        rng=np.random.default_rng(100+tr); I,R,F=scene(nz,rng)
        ee.append(auc(a_energy(I),R,F)); ii.append(auc(a_hr_ideal(I),R,F)); bb.append(auc(a_hr_bio(I,rng),R,F))
    e,i,b=np.mean(ee),np.mean(ii),np.mean(bb)
    rows['energy'].append(float(round(e,3))); rows['ideal'].append(float(round(i,3))); rows['bio'].append(float(round(b,3)))
    print(f'{nz:>6} {e:>8.3f} {i:>9.3f} {b:>8.3f}')
import json; print('CHART',json.dumps(rows))
