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

---

## Follow-up fixes (cutting audit)

- **Cross-object bonding** now works one-way (either side attracting is enough; a repel blocks it).
- **Merge scope** fixed: merging one string of a multi-string object joins only that string, not the whole object (reassigns the fused connected-piece; averages attributes only in the clean single-string case).
- **Removed cut auto-rejoin.** It set the whole object's own-type profile on cut, which in the type-based model activates attraction for *every* same-type end — causing scene-wide "everything zooms together" on the first cut, cuts snapping back instantly, and lag + reset-proof weirdness (a persisted setting, not geometry; turning off bonding masked it). Cutting now just cuts. Proper per-cut rejoin needs the deferred "separate ids by connected geometry" (per-piece ids) feature so it can target only the two fresh ends.

---

## Per-object bonding UI (relationship editor)

Replaced the per-type "wall of every type in the scene" with a proper relationship editor in the Connect tab:
- **Per-object "endpoint bonding" toggle.** Off = object sits out. On = reveals sections below.
- **Self section** — this object's own ends bonding to each other (edits the own-type profile).
- **External list** — add/remove other objects; click an entry to make it active and edit its profile. Each entry is this object's directional pull toward that target (weak/strong/snap/merge/blend).
- **Auto-mirror + directional:** adding B to A's list also creates A's entry on B and enables B's bonding, but each side keeps its OWN values (so A can chase while B flees).
- **Gate:** a bond needs BOTH objects' bonding on (consent) AND the master on.
- **Master bonding** is now a kill-switch in Physics, defaults ON (so a forgotten master never silently blocks per-object bonding). Physics snap/break/merge/blend relabeled "defaults for new connections" (template new relationships inherit).

---

## Auto-space by thickness (per-object)

Radius-derived rest length so fat strands/chains space out instead of overlapping.
- **segAutoRest** = (effR(a)+effR(b)) × avg(spaceMult). Nodes sit ~1 diameter apart; as a bonus this drops the collision-exclusion depth to ~2, so self-collision on folds starts working automatically.
- **Merge/holding-bond joints** always use the radius-derived rest (× the two objects' avg spaceMult).
- **Authored segments**: untouched by default. Per-object **"auto-space by thickness"** toggle (Objects → General) re-derives that object's segment rest-lengths; toggling off restores the original authored rests (stored as seg.rest0).
- **Spacing multiplier** (per-object, default 1, range 0.5–2.5) nudges looser/tighter; re-applies live when thickness or the multiplier changes.
- Reset preserves autoSpace + spaceMult and re-applies after geometry restore.

---

## Breaking (instant strain-break, per-object)

- **flagStrainBreaks**: a segment of a breakable object snaps when stretched past `breakStrain × rest` (marks s.dead). **removeDead** now runs every frame independent of bonding (was buried in maintainBonds, gated on S.bonding).
- **Per-object "breakable" toggle** (Objects → General) + **"Break at" × rest-length** slider (default 2.5, range 1.2–6). Off (default) = unbreakable.
- Works on **normal AND merged segments** — this is the case the old bondBreak never covered (bondBreak only checked s.bond=true holding-bonds, so pulling a merged/fused strand never broke; strain-break fixes that).
- Broken strands split into free ends → reactive again, so with bonding on a tear can re-heal (no cooldown, by design).
- Reset preserves breakable + breakStrain.
- Deferred fast-follows discussed: fatigue/damage accumulation (wear), force-based (tension) mode, optional re-bond cooldown.

---

## Cut & break now SEVER, not delete

Previously cut (G.segs.filter) and break (removeDead splice) deleted the whole segment, leaving a gap (material appeared to vanish). Now both call **severSegment(i,t)**: splits the segment at param t into two half-segments (A–m1, m2–B) with two fresh free-end nodes at the split point (tiny perpendicular offset), proportional rest lengths, original edge dropped. Material (total rest length) is conserved; the strand just separates where you cut/tear. Cut computes t from the cut-line/segment intersection; break severs at midpoint (t=0.5). Verified: material conserved, splits into pieces, no NaN on the real scene. Note: reset re-imports for file scenes (discards the split nodes → back to original); demo-scene reset is a no-op after a sever (node-count guard).

---

## Fix: break + self-bonding freeze (runaway break/rebond loop)

When a shape was both breakable AND self-bonding, a break created two free ends ~1.2px apart → self-connectivity instantly re-bonded/merged them → the re-merged segment was still over-strained → broke again → forever, growing nodes and running rebuildTopology twice/frame until the program froze. Fix: a **bonding cooldown** — severSegment stamps the new ends with `noBond = S.frame + 30`; endpointForces skips force+bond for any end whose cooldown hasn't expired (added a global `S.frame` counter, incremented in frame()/stepFrame()). Freshly-severed ends stay inert for 30 frames so they separate instead of re-healing into a loop. Verified: breakable+self-bonding strand under a sustained yank stabilizes at a bounded node count (8→14→14…) instead of exploding; no NaN.
