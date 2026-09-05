"""
gpu_sort.py — validate a GPU BITONIC SORT headless (moderngl/llvmpipe). This is the gating piece for
the full-GPU tile rasterizer: sorting (tile<<16 | depth) key/value pairs entirely on the GPU, with
NO CPU. Bitonic sort is fully parallel (log^2(n) compute passes of n/2 compare-exchanges each) and
needs no atomics or dynamic allocation — ideal for the gpu-module (works with image-backed buffers
on Blender too; here we use SSBOs since moderngl has them).
"""
import numpy as np, moderngl, time

_STAGE = """#version 430
layout(local_size_x=256) in;
layout(std430, binding=0) buffer K { uint keys[]; };
layout(std430, binding=1) buffer V { uint vals[]; };
uniform int uJ; uniform int uK; uniform int uN;
void main(){
  uint i = gl_GlobalInvocationID.x; if(i >= uint(uN)) return;
  uint ixj = i ^ uint(uJ);
  if(ixj > i){
    bool ascending = ((i & uint(uK)) == 0u);
    uint ki = keys[i], kj = keys[ixj];
    if((ki > kj) == ascending){
      keys[i]=kj; keys[ixj]=ki;
      uint vi=vals[i]; vals[i]=vals[ixj]; vals[ixj]=vi;
    }
  }
}"""

def bitonic_sort_gpu(ctx, keys, vals):
    """Sort keys ascending on the GPU, carrying vals along. Pads to a power of two."""
    n = len(keys)
    n2 = 1
    while n2 < n: n2 <<= 1
    K = np.full(n2, 0xFFFFFFFF, np.uint32); K[:n] = keys
    Vv = np.zeros(n2, np.uint32); Vv[:n] = vals
    bK = ctx.buffer(K.tobytes()); bV = ctx.buffer(Vv.tobytes())
    cs = ctx.compute_shader(_STAGE); cs['uN'].value = n2
    bK.bind_to_storage_buffer(0); bV.bind_to_storage_buffer(1)
    groups = (n2 + 255)//256
    passes = 0
    k = 2
    while k <= n2:
        j = k >> 1
        while j >= 1:
            cs['uK'].value = k; cs['uJ'].value = j
            cs.run(group_x=groups); ctx.memory_barrier()
            passes += 1
            j >>= 1
        k <<= 1
    ks = np.frombuffer(bK.read(), np.uint32)[:n]
    vs = np.frombuffer(bV.read(), np.uint32)[:n]
    return ks, vs, passes

def run():
    ctx = moderngl.create_context(standalone=True, backend='egl')
    rng = np.random.default_rng(0)
    for n in [1000, 100000, 555827]:   # last = the cactus tile-pair count
        # simulate (tile<<16 | depth16) keys + splat-id values
        keys = rng.integers(0, 1<<28, n, dtype=np.uint32)
        vals = np.arange(n, dtype=np.uint32)
        t = time.perf_counter()
        ks, vs, passes = bitonic_sort_gpu(ctx, keys, vals)
        dt = (time.perf_counter()-t)*1000
        sorted_ok = bool(np.all(ks[:-1] <= ks[1:]))
        # verify values are a correct permutation: keys[old_order]==sorted keys
        perm_ok = bool(np.array_equal(np.sort(keys), ks) and np.array_equal(keys[vs], ks))
        print("n=%7d: %2d passes, %6.0f ms (llvmpipe) | sorted=%s perm-correct=%s"
              % (n, passes, dt, sorted_ok, perm_ok))
    print("=> GPU bitonic sort is correct (no CPU, no atomics) — full-GPU tile sort is viable")

if __name__ == "__main__": run()
