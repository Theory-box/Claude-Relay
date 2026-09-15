# Validate the "active window" bitonic optimization on the CPU: does skipping threads
# i >= N+j still produce a correctly sorted result over the real N entries?
import numpy as np
def bitonic(keys, N, MAXN, optimize):
    k=2; ops=0
    while k<=MAXN:
        j=k>>1
        while j>=1:
            active = min(MAXN, N+j) if optimize else MAXN
            ops += active
            for i in range(active):
                ixj = i ^ j
                if ixj > i and ixj < MAXN:
                    asc = ((i & k)==0)
                    if (keys[i] > keys[ixj]) == asc:
                        keys[i], keys[ixj] = keys[ixj], keys[i]
            j >>= 1
        k <<= 1
    return keys, ops

rng=np.random.default_rng(0); bad=0
for N in [1000, 1100, 1500, 2000, 3000]:
    MAXN=1
    while MAXN<N: MAXN<<=1
    base=np.concatenate([rng.random(N), np.full(MAXN-N, np.inf)])
    a,opsA=bitonic(base.copy(), N, MAXN, False)
    b,opsB=bitonic(base.copy(), N, MAXN, True)
    okA=bool(np.all(a[:-1]<=a[1:])); okB=bool(np.all(b[:-1]<=b[1:]))
    same=bool(np.allclose(a[:N], b[:N]))
    if not(okA and okB and same): bad+=1
    print("N=%5d MAXN=%5d | full sorted=%s opt sorted=%s identical=%s | work %d -> %d (%.0f%% saved)"
          %(N,MAXN,okA,okB,same,opsA,opsB,100*(1-opsB/opsA)))
print("ALL CORRECT" if bad==0 else "FAILURES: %d"%bad)
