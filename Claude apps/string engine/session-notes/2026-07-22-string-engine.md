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

---

## Break/cut rewritten: node-based, edge is atomic (fixes fragmentation explosion)

Old severSegment split the EDGE (added midpoint nodes + shrank rest lengths), so grow could re-stretch each fragment past threshold and subdivide forever → 300 verts became thousands (crash). New model severs AT A NODE: **dupNode** copies the shared node, **severEdgeAt(si,preferA)** reassigns the edge to the copy so it detaches from whatever else shared that node — NO new edges, NO shrinking rests. A lone edge (both ends degree 1) returns false = indivisible. So an N-edge strand breaks into at most N lone edges, then stops. Verified: 59-edge strand + heavy grow + break settles at exactly 59 lone edges / 119 nodes, edges never grew, stable over 400 frames, no NaN. Cut severs at the vertex nearer the crossing (0 new edges, +1 node/cut, splits into pieces).

Also removed the 30-frame bonding cooldown (user prevents instant re-bond physically via own-connector repulsion; re-bond oscillation is now just lag, not a freeze, since no geometry is created). Kept grab-release-on-break (prevents the fountain bug). S.frame counter left in (harmless, unused now).

---

## Fix: weak-repel + strong-attract now bonds (strong band drives bonding)

Old gate blocked bonding if EITHER band repelled (`!p1r&&!p2r` where repel = wStr<0||sStr<0), so a weak-repel killed bonding even with strong-attract — breaking the whole "repel at range, snap up close" model. New gate: **wants(p)** = sStr>0 (or weak-attract when no strong); **blocks(p)** = sStr<0 only. So a weak repel no longer vetoes bonding; only a STRONG (close-range) repel does. Verified: weak-repel+strong-attract bonds when close, strong-repel blocks, weak-repel pushes apart at range.

---

## Hysteresis (break distance) — stops the bond/break buzz

Bonding and breaking were triggered at the same threshold, so a pair at the boundary bonded and broke every frame (each event runs rebuildTopology -> 3fps). Fix = a dead zone between bond distance (snap) and break distance (brk>snap):
- Added per-connection **brk** (break distance) to the profile; **ensureProf** defaults it to max(global bondBrk, snap+2).
- **Holding bonds** now break when stretched past their brk (per-connection), replacing the old global S.bondBreak.
- **Re-heal gate:** severEdgeAt tags the two fresh ends with mutual sepFrom + sepDist(=object's own-type brk); endpointForces won't re-bond that pair until they've pulled apart past sepDist (then clears the tag). So a fresh break can't instantly re-heal into a loop.
- UI: removed the vestigial global "Break distance" slider; added a **Break dist** default in Physics ("Defaults for new connections") and a per-connection **break dist** row in the Connect profile, floored above snap (setter: max(x, snap+2)) so it can't invert into a buzz.
- Verified: break then bonding-on (no grow) = 0 fresh severs (no buzz); ends settle 4->2. Strain-break (per-object "Break at x rest") kept separate. Note: grow + self-bonding still churns (grow continuously re-tears — a force fight, not the threshold buzz); bounded by atomic edges; safety cap next to smooth it.

---

## Unified breaking: one ratio-based concept, snap+break linked

Consolidated the two confusing break controls into one. snap and brk are now RATIOS (x rest length), not distances:
- **Bonding:** snaps when `dist < snap * (effR(a)+effR(b))` (the would-be bond length).
- **Breaking (bond release AND strand tearing):** `dist/rest > brk`. Holding bonds use s.brk*s.rest; strain-break uses `objBrk(o)` = the object's own-type profile brk (default 2.5). Re-heal gate distance = brk*rest.
- **UI:** Connect profile has **snap distance** + **break distance** (ratios). Moving snap scales break proportionally (preserves current ratio); break floored at snap*1.2 (setter + live coupling updates the break slider DOM). Global "Snap distance"/"Break distance" defaults in Physics now ratios (1.5 / 2.5).
- **Removed:** General "Break at x rest length" slider and per-object breakStrain (OBJDEF/capture/restore); the General **breakable toggle stays** and now uses the object's own-type break ratio (note in UI points to Connect for the value). Removed sepDistFor.
- Verified: strain tears at ratio, bond snaps at ratio, snap->break link scales, break floors at snap*1.2, load/run/cut/reset clean, no NaN.

---

## Fix: bonding could form Y-junctions (one endpoint bonding to two partners in one batch)

The newBonds batch deduped only by pair key, so if endpoint n1 was near both n2 and n3, it pushed (n1,n2) and (n1,n3) and merged BOTH -> n1 became degree 3 (a Y). Endpoint bonding is meant endpoint-to-endpoint, one-to-one. Fix in the newBonds loop: record each candidate's distance (d), **sort by distance** (nearest pairs claim endpoints first), track a **usedNodes** set (skip a bond if either endpoint is already used this batch), and a **degree guard** (skip if either endpoint isn't a genuine free end, nbrs.length>1). So each free end accepts at most one bond and bonding never attaches to a non-endpoint. Verified: three ends clustered on one point -> max degree 2 (no Y); normal two-end bonding still fuses into a line; authored high-degree mesh nodes are untouched (bonding only ever touches degree-1 ends).

---

## Bend-break (angle-based) + reach readout

**Bend break** — a second, independent breaking axis alongside stretch break. computeRestBend now also stores each degree-2 node's rest angle (n.bAng) via jointAngle(a,n,c) (PI=straight). New **flagBendBreaks** (runs in the k-loop after flagStrainBreaks): per-object **bendMode** ('off'/'abs'/'rel') + **bendLimit** (degrees). abs = joint tears if it folds sharper than the limit; rel = tears if bent >limit degrees from its own rest angle (so curved/curly shapes hold at rest, squiggly lines can wander with abs). Severs at the node (detaches one incident edge via severEdgeAt) — atomic-edge consistent. OBJDEF + capture/restore updated. Verified: abs holds straight/shallow, breaks at 64°<90° limit; rel holds a curved arc at rest, breaks when bent 62°>40° past rest.

**Reach readout** — above the snap/break sliders (per profile): `surface ≈ Npx (reach Mpx) · snap → Xpx · break → Ypx`, warns "⚠ too low to touch" when snap distance in px < 2*(effR+pad). Converts the snap/break RATIOS to px live (updates as you drag snap/break) using bondRest=2*effR, so you can set snap/break against the object's actual padded surface. Snap ratio range widened to 0.3–8, break to 0.5–16 for headroom with thick padding. UI: bend toggle cycles off→absolute→relative; all in the Connect tab.

---

## Breaking consolidated (stretch + abs + rel, any combination) + merge-joint rest angle

Unified all breaking under one **breakable** master with independent sub-toggles: **stretch** (brkStretch, break distance ratio, shown with snap / standalone when bonding off), **bend · absolute** (brkAbs + bendAbsLim), **bend · relative** (brkRel + bendRelLim) — any combination active at once (replaces the old single bendMode cycle). flagStrainBreaks gated on breakable&&brkStretch; flagBendBreaks checks abs and rel independently (breaks if either fires); both gated on the breakable master. OBJDEF/capture/restore updated (removed bendMode/bendLimit). All in the Connect tab.

**Merge rest-angle fix** (candidate fix for the bend-break clumping/spin the user reported): mergeEnds now sets the merged node's bAng to its current joint angle, so a freshly-formed bent joint's rest = where it formed → relative bend-break won't instantly snap it (was treating merged joints as rest=straight → instant break → merge/break churn → overlapping spinning clumps). Verified: abs+rel independent, master gate holds, stretch gate works, reset preserves. NOTE: could not reproduce the exact spin in isolation (test strands resist bending past the limit); asked user to test and offer file if it persists.

---

## Auto-space fix: only expand (never compress) + include padding

segAutoRest was `(ra+rb)*m` and applyAutoSpace OVERWROTE each seg's rest with it -> two bugs: (1) ignored padding, so it under-spaced padded strands; (2) it REPLACED rest, so any strand authored wider than 2*radius got COMPRESSED toward a point (the user's "every other substring collapsed to a dot" — fits a strand with alternating long/short authored segments; drags back out because nodes are intact, just held by a tiny rest). Fix: `segAutoRest = max(authored rest0, (ra+rb+padSelf)*spaceMult)` — only ever EXPANDS to prevent overlap, includes padSelf. Verified: wide 40px strand stays 40 (no compress), crammed fat strand expands to 2*effR, thin+padSelf=10 spaces to ~16. No NaN on real scene with auto-space on.
