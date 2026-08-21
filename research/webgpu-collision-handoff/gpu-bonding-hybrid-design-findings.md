# GPU/CPU hybrid bonding design for the String Engine

Context: `Theory-box/Claude-Relay`, branch `feature/gpu`. This report addresses endpoint proximity detection that forms or breaks topology links. It is a design review only; it contains no engine code.

## Executive recommendation

Keep **topology authority on the CPU**. Move formation proximity discovery to GPU only when profiling shows that scanning free endpoints or transferring all endpoint positions is the hotspot. The GPU should emit a conservative, compact list of possible endpoint pairs; the CPU should revalidate, deterministically arbitrate one-bond-per-endpoint, mutate topology, increment topology generations, and rebuild dependent buffers.

This split avoids trying to perform dynamic graph mutation, allocation, and all dependent CSR/grid rebuilds inside WebGPU. It also preserves deterministic engine rules while allowing the GPU to discard the overwhelming majority of non-near endpoints.

Breaking existing bonds is simpler than formation: evaluate the current bond list directly on GPU, emit break candidates/flags, and let the CPU apply them. A spatial grid is unnecessary for an already-known list of bonds.

## Q4 — where to split GPU and CPU work

### Recommended pipeline

For bond formation:

1. CPU or GPU produces the current compact set of **free, bond-eligible endpoints** and immutable compatibility metadata.
2. GPU inserts each free endpoint once into a grid whose cell width is near the capture radius.
3. GPU scans the 3×3 neighborhood in 2D, performs cheap compatibility filters and exact distance testing, and appends canonical candidate records.
4. The compact counter and candidate records are copied to a readback buffer.
5. CPU rejects stale/invalid records, sorts them deterministically, greedily accepts non-conflicting bonds, and applies topology changes as one batch.
6. CPU increments the topology version and rebuilds node/segment adjacency, exclusions, strand classification, bond flags, and affected GPU buffers before the next topology-dependent GPU pass.

Uniform grids are a standard GPU broad phase for bounded-radius proximity; [GPU Gems 3, Chapter 32](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda) describes the spatial-subdivision and duplicate-pair issues. Here the objects are points inserted exactly once, so the formation grid is simpler than the segment-AABB collision grid.

### When GPU detection is worthwhile

GPU discovery is attractive when:

- endpoint positions already live on GPU;
- many free endpoints exist;
- CPU currently reads back or scans a large population merely to find a small candidate set;
- bond checks need to occur often enough that the CPU broad phase is measurable;
- asynchronous consumption with one or more frames of latency is acceptable.

Keep detection on CPU when:

- the free endpoint set is small;
- bonding is rare or checked infrequently;
- topology changes force frequent synchronous stalls anyway;
- the CPU already has current endpoint positions for other reasons;
- readback latency and pipeline complexity cost more than the scan.

Use profiling, not total node count, to choose. A GPU path should retain a CPU brute-force/grid oracle for validation and a fallback for overflow or unsupported conditions.

### Readback is the central trade-off

WebGPU mapping transfers buffer ownership to the CPU and completes only after earlier GPU work using that buffer has finished. The [WebGPU Explainer's mapping section](https://gpuweb.github.io/gpuweb/explainer/#buffer-mapping) explicitly describes this asynchronous ownership transfer. Awaiting same-frame readback in the simulation loop can serialize CPU and GPU and erase the gain from GPU detection.

Prefer double- or triple-buffered staging readback:

- frame/substep N writes candidate batch N;
- the CPU consumes the newest completed older batch;
- every batch carries snapshot versions so stale results are rejected safely.

If immediate bond formation is required, measure the synchronous stall. A less frequent bonding cadence is often the better compromise, with a slightly conservative GPU capture radius followed by an exact current-position CPU check.

### Do not mutate GPU topology in the detection pass

Concurrent endpoint claims can be expressed with atomics, but choosing locally does not solve the complete matching problem and tends to make results scheduling-dependent. It also leaves the harder work—allocation, deletions, CSR reconstruction, strand/ring classification, exclusions, and buffer resizing—unsolved.

The CPU is already the natural transaction boundary. It can apply a deterministic maximal set of compatible candidates and publish one coherent new topology version.

## Q5 — compact candidate output

### Atomic append buffer

Use a storage-buffer `atomic<u32>` counter. Each passing invocation reserves a slot with `atomicAdd`; if the returned slot is below capacity, it writes the candidate payload. If it is not below capacity, it sets an overflow flag and performs no payload write.

WGSL atomics operate on `i32` or `u32`, live in mutable storage/workgroup memory, and `atomicAdd` returns the previous value, which makes it suitable for append-slot allocation. Atomic operations have relaxed ordering, so the counter is not a general publication barrier for non-atomic payload writes inside the same dispatch. These rules are specified in the [WGSL atomic built-ins section](https://www.w3.org/TR/WGSL/#atomic-builtin-functions).

Practical consequences:

- Do not have invocations consume the partially appended list in the same dispatch.
- Consume it only after the producing pass has completed and normal WebGPU command/buffer synchronization applies.
- The counter may exceed capacity; the payload must never be indexed before checking the reserved slot.
- **Any overflow invalidates the batch.** A truncated candidate set can change which bonds win, so accepting its prefix is not correct.

### Candidate record

Each record should contain enough immutable identity to survive asynchronous readback and enough score data for deterministic CPU ordering:

- canonical endpoint IDs `(minID, maxID)`;
- generation number for each endpoint, or stable handles that include generation;
- topology version/snapshot epoch;
- position/substep epoch if position freshness is tracked separately;
- squared distance or a deterministic quantized priority score;
- optional compatibility/type fields only if they help diagnose why CPU revalidation rejected it.

Do not rely on append order. Atomic reservation order is not a stable priority. The CPU should sort by the engine's intended policy, for example distance/score first and canonical endpoint IDs as the tie-break. If exact cross-device determinism matters, quantize the priority before sorting or recompute it from current CPU-visible positions.

### Pair dedup for free endpoints

The cleanest endpoint grid inserts every free endpoint into exactly one home cell. Each endpoint invocation scans the neighboring cells and emits only when its endpoint ID is smaller than the partner ID. Then each unordered pair is considered by exactly one invocation and no local seen array is needed.

If endpoints are instead inserted into multiple expanded cells, the `ID A < ID B` rule does not remove multi-cell duplicates. In that design, restore the deterministic lowest-shared/home-cell rule used by segment collision.

The formation capture test must be exact after the conservative cell query. Use squared distance to avoid a square root unless distance itself is needed for ranking.

### One-bond-per-endpoint is an arbitration result, not an append invariant

The raw candidate list should be allowed to contain several candidates for the same endpoint. Requiring the GPU list itself to contain only one candidate per endpoint can discard the only feasible alternate:

- A chooses B as nearest.
- C also chooses B and wins the CPU tie-break.
- If A's alternate D was discarded on GPU, A remains unnecessarily unbonded.

The safe sequence is: output all valid nearby pairs, sort deterministically on CPU, then greedily accept a pair only if both endpoints remain free. That yields a deterministic maximal matching under the chosen priority, though not necessarily the globally maximum-cardinality or minimum-cost matching. This matches typical game-engine needs and is easy to reason about.

If candidate volume becomes excessive, a per-endpoint top-K reduction is possible, but it is an explicit behavioral approximation and needs adversarial tests. It must not silently replace the complete-list reference path.

## CPU consumption invariants

Before applying any formation candidate, the CPU must confirm all of the following against the **current** state:

1. The candidate batch did not overflow and its count is within capacity.
2. The batch topology version matches, or the candidate is fully revalidated under a policy that explicitly permits older snapshots.
3. Both stable endpoint IDs still resolve and both generation numbers match; IDs have not been deleted and reused.
4. The endpoints are distinct and the pair key is canonical.
5. Both endpoints are still free and eligible for bonding.
6. Object/tag/type compatibility, self-bond, strand-distance, and exclusion rules still pass.
7. The pair is not already bonded or otherwise topologically connected in a forbidden way.
8. Current exact distance satisfies the formation threshold; all numeric values are finite.
9. No previously accepted candidate in this CPU transaction has claimed either endpoint.
10. The accepted topology batch is committed atomically from the solver's perspective, followed by all dependent buffer rebuilds before physics resumes.

Version the compatibility configuration as well if bond rules or object tags can change without changing topology. A candidate created under old rules must not be accepted merely because endpoint generations still match.

### Snapshot-wide rejection versus per-record revalidation

The simplest rule is to reject the whole batch whenever `batch.topologyVersion != currentTopologyVersion`. This is conservative and easy to prove.

Per-record generation checks can salvage unaffected candidates after unrelated topology changes, but only if every relevant dependency is versioned: endpoint identity, free/bond state, object membership, compatibility parameters, exclusions, and current distance. Start with whole-batch rejection; optimize only if stale-batch loss is measurable.

## Bond breaking

Existing bonds already provide the pair list. A GPU pass can test each bond's break condition directly and append a canonical bond handle plus topology/generation version, or write one break flag per bond followed by compaction/readback.

CPU consumption must revalidate:

- the bond handle and bond generation still identify the same link;
- the topology/config version is valid;
- the current break rule still passes;
- the same bond is removed at most once.

Formations and breaks should be applied in a defined transaction order. A robust default is:

1. validate and apply breaks;
2. update the free-endpoint set;
3. validate formation candidates against that updated state;
4. accept non-conflicting formations;
5. publish one new topology version and rebuild once.

If CPU semantics use the opposite order, preserve that initially because it can change which endpoint bonds in the same frame.

## Capacity and diagnostics

Track at least:

- number of free eligible endpoints;
- endpoint-grid insertion count and maximum bin occupancy;
- grid overflow;
- raw pair tests;
- passing candidate count;
- append overflow and maximum observed count;
- candidates rejected for stale version, generation mismatch, current distance, compatibility, and endpoint conflict;
- accepted formations and breaks;
- readback latency in frames and milliseconds;
- topology rebuild time.

Capacity should be chosen from measured worst cases plus headroom. A dense pile of `M` mutually close free endpoints has `M(M-1)/2` valid pairs; no fixed append capacity can make that case cheap. Overflow should trigger a larger rerun, CPU fallback, or skipped bonding update with a visible diagnostic—never partial acceptance.

## Validation checklist

- GPU candidate set matches a CPU brute-force oracle for frozen positions before arbitration.
- Every unordered eligible pair appears exactly once.
- Append order changes do not change accepted bonds after CPU sorting.
- Competing-star and chain cases verify one-bond-per-endpoint and alternate-candidate behavior.
- Grid overflow and append overflow cause batch rejection.
- Delayed batches are rejected after endpoint deletion/reuse, bond-state change, rule change, or topology rebuild.
- Endpoint generation prevents ABA reuse bugs even if an integer slot is recycled.
- CPU rechecks current distance before formation.
- Break and form ordering matches documented CPU semantics.
- No topology-dependent GPU pass runs between CPU mutation and completion of all rebuilt buffers.
- Synchronous and pipelined-readback modes produce the same accepted bonds for the same snapshots.

## Final answers

### Q4

Use the hybrid split when profiling justifies it: GPU performs conservative proximity discovery over free endpoints; CPU remains the sole authority for arbitration, mutation, version increments, and buffer rebuilds. Keep a CPU detection path for small sets, validation, and overflow fallback. Test existing bonds directly rather than through a grid.

### Q5

Emit canonical candidate records through a bounded `atomicAdd` append buffer. Dedup by single-cell endpoint insertion plus `ID A < ID B`. Treat overflow as fatal. Carry topology/config epochs and endpoint generations, ignore atomic append order, revalidate current state on CPU, sort deterministically, and enforce one-bond-per-endpoint during CPU acceptance—not by prematurely pruning the GPU candidate list.

## Sources

- W3C GPU for the Web Community Group, [WebGPU Shading Language: atomic built-in functions](https://www.w3.org/TR/WGSL/#atomic-builtin-functions).
- W3C GPU for the Web Community Group, [WebGPU Explainer: buffer mapping and CPU–GPU ownership transfer](https://gpuweb.github.io/gpuweb/explainer/#buffer-mapping).
- Scott Le Grand, [GPU Gems 3, Chapter 32: Broad-Phase Collision Detection with CUDA](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-32-broad-phase-collision-detection-cuda).
- David Algis et al., [Efficient GPU Implementation of Particle Interactions with Cutoff Radius and Few Particles per Cell](https://arxiv.org/abs/2406.16091).
- Project context: [`Claude apps/string engine/string-engine.html` on `feature/gpu`](https://github.com/Theory-box/Claude-Relay/blob/feature/gpu/Claude%20apps/string%20engine/string-engine.html). Exact formation, break, and transaction ordering should be mirrored directly from the current branch during implementation.
