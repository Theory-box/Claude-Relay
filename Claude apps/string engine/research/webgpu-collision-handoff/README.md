# Claude handoff — String Engine `0179580`

Prepared against exact commit `0179580410aff2cbdf2fc062b1e4d0ccf5c8a80e` (`origin/feature/gpu`). No repository files were changed.

Files:

- `WEBGPU_VALIDATION.md` — exact local and hardware-log results.
- `validate-string-engine-wgsl.mjs` — extracts the three embedded WGSL modules and validates them with Naga.
- `SPATIAL_HASH_FINDINGS.md` — findings and recommended particle-collision architecture for 10k–100k particles.

Fast read: use count → exclusive scan → scatter for the robust default, then one Jacobi gather invocation per particle over its 3×3 cells. Each invocation writes only its own output position, so collision response needs no float atomics. Treat radix sorting as a later benchmark candidate, especially above 100k or when sorted order is reused by several kernels.

