# Simulate the PARALLEL scatter (local-rank via bitmask popcount) + chunked scan,
# exactly as the new GLSL does, and verify sortedness + STABILITY.
import numpy as np
BITS=4; RADIX=16; PASSES=8; GROUP=256; SCAN_CHUNK=1024

def scan_parallel(counts_flat):
    n=len(counts_flat); nch=(n+SCAN_CHUNK-1)//SCAN_CHUNK
    off=np.zeros(n,np.int64); tot=np.zeros(nch,np.int64)
    for c in range(nch):
        s,e=c*SCAN_CHUNK,min((c+1)*SCAN_CHUNK,n)
        seg=counts_flat[s:e]
        inc=np.cumsum(seg); off[s:e]=inc-seg; tot[c]=inc[-1] if len(inc) else 0
    for c in range(nch):   # add chunk bases
        base=tot[:c].sum()
        s,e=c*SCAN_CHUNK,min((c+1)*SCAN_CHUNK,n)
        off[s:e]+=base
    return off

def radix_parallel(keys, vals):
    N=len(keys); ng=(N+GROUP-1)//GROUP
    k=keys.copy(); v=vals.copy()
    for p in range(PASSES):
        sh=p*BITS; dig=(k>>np.uint32(sh))&np.uint32(RADIX-1)
        counts=np.zeros((RADIX,ng),np.int64)
        for g in range(ng):
            seg=dig[g*GROUP:min((g+1)*GROUP,N)]
            for d in range(RADIX): counts[d,g]=int((seg==d).sum())
        off=scan_parallel(counts.reshape(-1)).reshape(RADIX,ng)
        nk=np.zeros_like(k); nv=np.zeros_like(v)
        for g in range(ng):
            lo,hi=g*GROUP,min((g+1)*GROUP,N)
            seg=dig[lo:hi]
            for lid in range(hi-lo):
                d=int(seg[lid])
                rank=int((seg[:lid]==d).sum())        # == the bitmask popcount rank
                dst=int(off[d,g])+rank
                nk[dst]=k[lo+lid]; nv[dst]=v[lo+lid]
        k,v=nk,nv
    return k,v

rng=np.random.default_rng(0); bad=0
for N in [1,300,1000,5000,20000]:
    depth=(rng.random(N).astype(np.float32)-0.5)*200
    b=depth.view(np.uint32); neg=(b>>np.uint32(31)).astype(bool)
    keys=np.where(neg,~b,b|np.uint32(0x80000000)).astype(np.uint32)
    vals=np.arange(N,dtype=np.uint32)
    sk,sv=radix_parallel(keys,vals)
    ok=bool(np.array_equal(sk,np.sort(keys,kind='stable')))
    perm=bool(np.array_equal(keys[sv],sk))
    print("N=%6d sorted=%s perm=%s"%(N,ok,perm))
    if not(ok and perm): bad+=1
# stability with many duplicate keys
keys=np.array([5,3,5,3,5,3,7,3]*200,np.uint32); vals=np.arange(len(keys),dtype=np.uint32)
sk,sv=radix_parallel(keys,vals)
grp=sv[sk==3]; stable=list(grp)==sorted(list(grp))
print("stability (duplicate keys keep original order):",stable)
print("ALL CORRECT" if bad==0 and stable else "FAIL")
