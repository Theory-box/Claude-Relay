"""
radix_prototype.py — design + validate the GPU radix sort that replaces the bitonic sort in
splat_gpusort.py. Runs the EXACT algorithm the GPU will run, but in numpy, so correctness and the
work/pass counts can be proven before any GLSL is written.

Why radix: bitonic is O(N log^2 N) and must pad to a power of two (at 1.1M splats it pads to 2.1M and
sorts the padding too). Radix is O(N) per pass with a fixed small number of passes and NO padding, so
6 clouds of 1M stop costing ~15 ms/frame, and a UNIFIED cross-cloud sort finally becomes cheaper than
separate sorts (fixing inter-tree blending as a bonus).

Design (4-bit digits, 16 buckets, LSD, stable):
  keys   = depth as a sortable uint32 (float bits flipped so ascending uint order == far->near)
  passes = 8 passes of 4 bits (32-bit key)
  per pass:
    1) histogram : count occurrences of each digit, per workgroup  -> counts[group][16]
    2) scan      : exclusive prefix sum over (digit-major) counts   -> global offsets
    3) scatter   : each element writes to its offset, stably        -> reordered keys+vals
  Every stage is a compute dispatch over image-backed buffers (no SSBOs, no atomics required for the
  per-group histogram approach; the scan is over a small counts buffer).
"""
import numpy as np

BITS = 4                 # bits per pass
RADIX = 1 << BITS        # 16 buckets
PASSES = 32 // BITS      # 8 passes for a 32-bit key
GROUP = 256              # elements per workgroup (matches local_size_x)


def depth_to_key(depth):
    """Map float depth -> uint32 so that ascending uint order == the draw order we want (far->near).
    IEEE trick: for positive floats the bit pattern is already monotonic; flipping the sign bit (and
    inverting negatives) makes the whole float range monotonic as unsigned."""
    b = depth.astype(np.float32).view(np.uint32)
    neg = (b >> np.uint32(31)).astype(bool)
    out = np.where(neg, ~b, b | np.uint32(0x80000000)).astype(np.uint32)
    return out


def radix_sort_sim(keys, vals, verbose=False):
    """Simulate the exact per-workgroup GPU algorithm. Returns sorted keys/vals + a work report."""
    N = len(keys)
    ngroups = (N + GROUP - 1) // GROUP
    k = keys.copy(); v = vals.copy()
    dispatches = 0
    for p in range(PASSES):
        shift = p * BITS
        digits = (k >> np.uint32(shift)) & np.uint32(RADIX - 1)

        # ---- stage 1: per-group histogram (one dispatch over N) ----
        counts = np.zeros((ngroups, RADIX), np.int64)
        for g in range(ngroups):
            seg = digits[g*GROUP:(g+1)*GROUP]
            for d in range(RADIX):
                counts[g, d] = int((seg == d).sum())
        dispatches += 1

        # ---- stage 2: exclusive scan over digit-major counts (one small dispatch) ----
        # order: all groups for digit 0, then digit 1, ... so a stable global offset falls out.
        flat = counts.T.reshape(-1)                      # [digit][group]
        offsets = np.zeros_like(flat)
        offsets[1:] = np.cumsum(flat)[:-1]
        offsets = offsets.reshape(RADIX, ngroups)
        dispatches += 1

        # ---- stage 3: scatter (one dispatch over N), stable within each group ----
        nk = np.zeros_like(k); nv = np.zeros_like(v)
        cursor = offsets.copy()
        for g in range(ngroups):
            lo, hi = g*GROUP, min((g+1)*GROUP, N)
            for i in range(lo, hi):                      # ascending i -> stability preserved
                d = int(digits[i])
                dst = int(cursor[d, g]); cursor[d, g] += 1
                nk[dst] = k[i]; nv[dst] = v[i]
        dispatches += 1
        k, v = nk, nv
        if verbose:
            print("  pass %d (shift %2d): sorted-so-far=%s" % (p, shift, bool(np.all(k[:-1] <= k[1:]))))
    return k, v, dispatches


def bitonic_work(N):
    """Dispatch count + element-ops of the CURRENT bitonic sort, for comparison."""
    M = 1
    while M < N: M <<= 1
    stages = 0
    k = 2
    while k <= M:
        j = k >> 1
        while j >= 1:
            stages += 1; j >>= 1
        k <<= 1
    return stages, stages * M


def radix_work(N):
    ngroups = (N + GROUP - 1)//GROUP
    dispatches = PASSES * 3
    # element-touches: histogram N + scan (RADIX*ngroups) + scatter N, per pass
    ops = PASSES * (N + RADIX*ngroups + N)
    return dispatches, ops


def run():
    rng = np.random.default_rng(0)
    print("=== correctness (radix vs numpy reference) ===")
    bad = 0
    for N in [1, 2, 300, 1000, 1100, 4096, 50000, 200000]:
        depth = (rng.random(N).astype(np.float32) - 0.5) * 200.0      # include negatives
        keys = depth_to_key(depth)
        vals = np.arange(N, dtype=np.uint32)
        sk, sv, _ = radix_sort_sim(keys, vals)
        ref = np.sort(keys, kind='stable')
        ok_sorted = bool(np.array_equal(sk, ref))
        # values must be a true permutation carrying the right keys
        ok_perm = bool(np.array_equal(keys[sv], sk))
        # and the depth order must be ascending (far->near) after the key mapping
        ok_depth = bool(np.all(np.diff(depth[sv]) >= -1e-6))
        if not (ok_sorted and ok_perm and ok_depth): bad += 1
        print("  N=%7d sorted=%s perm=%s depth-ordered=%s" % (N, ok_sorted, ok_perm, ok_depth))

    print("\n=== stability check (equal keys keep original order) ===")
    keys = np.array([5,3,5,3,5,3], np.uint32); vals = np.arange(6, dtype=np.uint32)
    sk, sv, _ = radix_sort_sim(keys, vals)
    stable = list(sv[sk == 3]) == sorted(list(sv[sk == 3]))
    print("  equal-key order preserved:", stable)

    print("\n=== work comparison: radix vs current bitonic ===")
    print("  %9s | %-26s | %-26s | %s" % ("N", "bitonic (dispatch/ops)", "radix (dispatch/ops)", "ops saved"))
    for N in [200_000, 500_000, 1_000_000, 1_100_000, 6_000_000]:
        bd, bo = bitonic_work(N)
        rd, ro = radix_work(N)
        print("  %9d | %6d / %15d | %6d / %15d | %5.1fx" % (N, bd, bo, rd, ro, bo/ro))

    print("\n=== the 1.1M padding case (why bitonic hurts) ===")
    M = 1
    while M < 1_100_000: M <<= 1
    print("  bitonic pads 1,100,000 -> %d (%.0f%% of the sort is padding)" % (M, 100*(M-1_100_000)/M))
    print("  radix: no padding, %d dispatches regardless" % (PASSES*3))

    print("\n" + ("ALL CORRECT" if bad == 0 else "FAILURES: %d" % bad))


if __name__ == "__main__":
    run()
