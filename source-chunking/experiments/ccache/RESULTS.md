# ccache + chunking: measured results

Environment: Ubuntu 24.04 container, g++ 13.3.0, ccache 4.9.1, mold 2.30.0.
Model: 20 spine TUs + 5 toggleable chunk TUs, all including a heavy 1209-line
shared header (stands in for Blender's DNA_/BKE_ headers). Reproduce with
`python3 model_gen.py && bash run.sh`.

These validate the *mechanisms* on a controlled model. Real-Blender wall-clock
figures will be larger (heavier files) but the ratios and behaviours transfer.

## 1. ccache + chunking delivers the core promise

| step | wall time | ccache |
|------|-----------|--------|
| cold build (config A) | 12.9 s | 0 hits / 23 miss |
| reconfigure: add one chunk | 0.86 s | 22 hits / 2 miss |
| reconfigure: swap to different chunk | 0.79 s | 21 hits / 2 miss |

~15x faster on reconfigure. The only recompiles are (a) the newly-added chunk and
(b) the gating TU (our stand-in for spacetypes.cc), whose `#define`s changed.
The whole spine and every previously-built chunk come from cache.

## 2. Path normalization is MANDATORY

| build | ccache |
|-------|--------|
| absolute source paths, checkout #2 (different root) | 0 hits / 20 miss |
| relative paths + `CCACHE_BASEDIR`, checkout #2 | **20 hits / 20 miss=0** |

A fresh per-config checkout gets **zero** cache benefit unless the engine compiles
with normalized relative paths. This is a hard requirement.

## 3. Unity build: use it, but align blob boundaries to chunk boundaries

Anchor: one heavy TU cold = 0.575 s. A unity blob of 11 files = 0.714 s
(the shared header is parsed once per blob instead of once per file -> ~8x cold win).

| blob strategy | reconfigure (toggle 1 chunk) |
|---------------|------------------------------|
| chunk-aligned (spine and chunks never share a blob) | spine blob = cache HIT; only toggled chunk recompiles |
| mixed (spine + chunk in one blob) | full MISS: all 20 spine files recompile |

Rule: **unity ON, but a unity blob must never mix spine files with chunk files, or
files from two different chunks.** That keeps both the cold-build speedup and the
reconfigure cache granularity.

## Net effect for a rebuild-often tool

After one slow initial build, toggling chunks costs only the changed chunks -
seconds, not a rebuild - provided: relative paths + `CCACHE_BASEDIR`, mold linker,
and chunk-aligned unity blobs.
