# Reproduce the batching hazard Claude Code identified: 256 threads, 1024 slots,
# Hillis-Steele where later batches read slots earlier batches already wrote THIS step.
import numpy as np
CHUNK=1024; THREADS=256
def scan_buggy(vals):
    s=vals.copy().astype(np.int64)
    off=1
    while off<CHUNK:
        # GLSL: for(i=lid; i<CHUNK; i+=THREADS) -> 4 batches, in-place, same buffer
        for lid in range(THREADS):
            for i in range(lid, CHUNK, THREADS):
                v = s[i-off] if i>=off else 0
                s[i]+=v          # in-place: later batches see earlier batches' writes
        off<<=1
    return s
def scan_correct(vals):
    s=vals.copy().astype(np.int64)
    off=1
    while off<CHUNK:
        prev=s.copy()            # double-buffered: read previous step only
        for i in range(CHUNK):
            if i>=off: s[i]=prev[i]+prev[i-off]
        off<<=1
    return s
rng=np.random.default_rng(0)
v=rng.integers(0,5,CHUNK)
ref=np.cumsum(v)
b=scan_buggy(v); c=scan_correct(v)
print("correct scan matches cumsum:", bool(np.array_equal(c,ref)))
print("BUGGY scan matches cumsum:  ", bool(np.array_equal(b,ref)))
bad=int((b!=ref).sum())
print("buggy mismatches: %d of %d slots (first bad at %d)"%(bad,CHUNK,int(np.argmax(b!=ref)) if bad else -1))
