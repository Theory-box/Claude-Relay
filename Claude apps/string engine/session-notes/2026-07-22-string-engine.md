# String Engine — Session Notes

A browser-based topology/physics artificial-life sandbox (single self-contained `string-engine.html`,
vanilla JS + canvas). Companion Blender add-on `mesh_to_json_addon.py` for import/export.

---

## Audit results (this session)

**Bug found & fixed — cross-object bonding required *mutual* attraction.**
Setting "B connects to C" (one direction only) made the ends cluster but never bond; you had to set
*both* B→C and C→B. Self-connect worked because both ends share one profile. Fixed: a bond now forms
if **either** side attracts and **neither** side repels. (Nulls guarded; a repel on either side blocks it.)

**Not a bug — "third line connects to a midpoint."**
Bonding is strictly **endpoint-to-endpoint**. Verified: interior nodes never gain bonds, no end ever bonds
to a midpoint. What looks like midpoint-connection is *chaining* (lines bonding end-to-end look like they
meet at points). "Connect to any point vs endpoints-only" is a genuine **future feature**, not a fix.

**Known design ambiguity (documented, not changed) — blend/merge arbitration.**
When two different objects' ends meet, each carries its own merge-time and blend for that type. The bond
currently uses **min merge-time** (fuses at the eager one's pace) and **average blend**. This is invisible
in the UI, which is why it feels confusing. No clearly-better rule exists for a two-opinion shared event;
the real resolution is the planned node-graph UI where the relationship (and its single agreed settings)
is explicit. Left as-is for now.

**Stability sweep (on real sim_1.json): all clean.**
No NaNs through load→run→cut→bond→reset; no degenerate segments; segIdx + neighbor integrity intact;
bond segments well-formed; no console errors.

**Also fixed this session — cut re-stressed the whole scene.**
`cutLine` was calling `computeRestBend()`, which re-baselined *every* strand's rest shape to its
mid-motion position at the instant of the cut, so the whole scene suddenly fought to hold bent poses.
Removed that call; cuts now preserve all rest shapes (cut points become free ends/hinges). Verified
far strands' rest memory is byte-identical before/after a cut.

---

## Engine architecture (quick map)

- **Graph model:** `G.nodes` (x,y,h + verlet prev px,py,ph + obj,fixed,solid,inv,ids,aff), `G.segs`
  (a,b,rest,obj,solid,ids,excl, +bond fields), `G.objs` (per-object attrs + nodeIdx/segIdx),
  `G.nbrs`, `G.ends` (degree-1 nodes), `G.piece` (connected-component id per node), `G.init`
  (start-layout snapshot), `G.lastImport`, `G.bondBank` (cumulative-timer memory).
- **Frame pipeline:** `attract(); endpointForces(); for(k<speed){ integrate(); flagBondBreaks();
  constraints(); collide(); wallCCD(); dragApply(); } maintainBonds();`
- **Object attributes:** r(thickness), stiff, curl, grow, affinity, polarity, solid, fixed, damp,
  padSelf, padOther, selfSolid, inter{}/interSelf (body affinity), endType{} (endpoint profiles).

## Endpoint / connector system (current)

- **Connector-type = object id.** Every free end's type is its object's base id. Cut inherits it.
- **Per-type profile** (`o.endType[typeId]`): `wStr, wRange` (weak: long-range gentle),
  `sStr, sRange` (strong: short-range firm), `snap` (bond trigger distance), `merge` (frames in
  contact before fusing; 0=instant, ≥900=never/elastic), `blend` (0 keep-separate → 1 average).
- **Two-band physics:** each end feels weak (`*0.12*(1-d/wRange)`) + strong (`*0.42*(1-d/sRange)`),
  directional (each end acts by its own object's profile toward the other's type).
- **Bonding:** within `snap`, either side attracting + neither repelling → bond. `merge<=0` fuses
  instantly; `merge>0` forms a holding bond that ages then merges. `flagBondBreaks` uses global
  `S.bondBreak` (0 = unbreakable).
- **Merge:** `mergeEnds` fuses two end-nodes into one continuous strand; **blend** 0 keeps both object
  identities (topologically joined), 1 averages their scalar attributes into one.
- **Cut auto-rejoin:** cutting sets the object's own-type profile to attract (sStr .5 / wStr .3) so
  fresh cut ends seek their own kind (magnet-snapped-in-half).
- **UI:** object editor has 3 sub-tabs (General / Affinity / Connect). Connect shows a dense per-type
  profile block (7 controls × each type). Physics tab holds the global bonding master toggle + snap/
  break/merge/blend **defaults** (new profiles inherit these) + timer mode (continuous/cumulative).

## Other systems

- **Reset:** restores original geometry + **preserves ALL settings** (object edits + globals) and
  resyncs sliders. (Fixed earlier this session — was dropping endpoint/global settings.)
- **Collision smoothing** (`contactDamp`): inelastic — bleeds normal velocity. Turn UP (~0.6–0.8) to
  fix both jitter AND layer-crossings.
- **Left toolbar:** Move (drag nodes) + Cut (slice segments).
- **Save/Load JSON**, **Weld**, **temporal spread** (chunked interactions), per-object damping,
  split padding (self vs others), directional per-object affinity.

---

## Deferred / next (agreed, not built)

- **Node-graph / matrix UI** for the dense per-type profiles (data model is ready; pure front-end swap).
- **"Separate ids by connected geometry"** per-object toggle — each connected piece gets its own
  connector-type (e.g. three concentric rings heal independently). `G.piece` already tracks this.
- **Sub-ids** ("003-B") for finer handles on cut halves.
- **Per-type break distance** (currently one global).
- **Contact-dwell visual** so merge-time is visible (ends hover/court, then fuse) instead of the
  holding-bond looking instant.
- **"Connect to any point vs endpoints-only"** setting (currently endpoints-only).
- Bigger ALife direction: plastic/settable rest shapes (self-templating), a reservoir of blank
  "food" material, measurement/statistics instrumentation to detect emergent replication.
- Performance heavy-artillery (only if a scene demands it): Web Workers / spatial tiling.

## Verification tooling

Headless Playwright (chromium at `/home/claude/.pw`, env `PLAYWRIGHT_BROWSERS_PATH`). Extract the
`<script>` block → `node --check` for syntax. Write tests to `.js` files then run. Always
`pkill -9 chromium` after each test (sandbox gets flaky otherwise). Verify numerically, not by eye.
