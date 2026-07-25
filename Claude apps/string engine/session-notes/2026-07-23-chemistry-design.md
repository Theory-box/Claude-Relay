# Chemistry update — design notes (branch `feature/chemistry`)

Implementing, in agreed order: **reversible bonds + hardening → bond energy → per-endpoint types.**
See `philosophy-and-direction.md` for the reasoning behind all of this.

---

## KEY FINDING: the two-stage bond already exists

Before writing anything I read the bonding pipeline closely. **The engine already has a
two-stage bond**, which changes the scope of "reversible bonds" considerably:

1. `endpointForces()` detects a pair within snap and either
   - `merge <= 0` → **instant fuse** (`mergeEnds()`), or
   - `merge > 0` → pushes a **holding bond**: a real segment with `bond:true`, `bondAge`,
     `mergeTime`, `blend`, `brk`. It's a spring; `constraints()` acts on it.
2. `maintainBonds()` increments `bondAge`; at `bondAge >= mergeTime` it calls `mergeEnds()`
   — i.e. the bond **commits/hardens** into a real strand.
3. `flagBondBreaks()` kills a holding bond stretched past `brk * rest`.
4. `mergeTime >= 900` is treated as "never merge" — a permanently elastic bond.

So weak-bond → commit is already the architecture. `mergeTime` *is* the hardening duration.

### What's actually missing

**Holding bonds only die from overstretch.** There is no spontaneous dissociation. A bond that
is geometrically *comfortable* survives and commits regardless of whether it's a good fit.
That means there is currently **no selection pressure** — which is the entire point of
reversible bonding.

So the real work is:
- **thermal dissociation** — a per-frame break probability driven by temperature and stability
- **hardening ramp** — stability rising with age along a curve (not a binary timer)
- **bond energy** — formation releases, breaking costs

---

## Design: thermal dissociation

Arrhenius-shaped, because the exponential is what makes selection *sharp* — small differences
in fit produce large differences in lifetime.

```
stability = bondStability(s) - strain        // strain eats into the barrier
p_break   = bondWobble * exp(-stability / kT),  kT = temp * 0.5
```

**Why strain is the right fitness measure (important):** a holding bond's rest length is
derived from the two radii. If the pair docked in a way that conflicts with their other
constraints, the bond sits stretched or compressed → strain → the barrier drops → it dies
fast. If the pairing is geometrically comfortable, strain ≈ 0 → it survives → it hardens.

**Nobody defines "good fit."** Geometric comfort does it, and it emerges from the existing
constraint solver. This is the emergent version the user asked for.

## Design: hardening

```
stability(age) = bStr + (1 - bStr) * (age/mergeTime)^hardenPow
```

- `bStr` (per-profile) — stability at birth. Low = very reversible early.
- `hardenPow` — curve shape. >1 = stays weak longer then commits fast (more search time);
  <1 = hardens quickly.
- At `age = mergeTime` stability hits 1 and `maintainBonds` merges it (covalent commitment).

Hardening is therefore *the same knob* as merge time, with a curve on it. No new lifecycle
system needed yet — the timeline/keyframe UI can come later and drive this.

## Design: bond energy

Verlet velocity is `x - px`, so:
- **form** → `px -= dir * amt` (adds kinetic energy, random direction = heat)
- **break** → scale `(x - px)` down (removes it)

Falls out for free: assembly heats its neighborhood → more thermal breaking → self-limiting;
decomposition costs energy; high-energy monomers are literally fuel.

---

## Problems found while designing (and how they're handled)

**1. Rebuild churn.** Every bond add and every `removeDead` triggers `rebuildTopology()` (full
flood fill), and `mergeEnds` triggers 1–2 *each*. Reversible bonding makes topology change the
norm rather than the exception. Mitigations: keep break probabilities low (bonds should live
tens–hundreds of frames, not 1–2), and a **per-frame event cap** (the long-backlogged safety
cap) so a pathological scene degrades to "busy" rather than freezing.

**2. Instant re-bond after a thermal break.** The bond dies, `removeDead` drops the segment,
both nodes become degree-1 endpoints again, and next frame they're still within snap → they
re-bond immediately. That's a buzz, not a search. Handled with the *existing* hysteresis
mechanism (`sepFrom`/`sepDist`), but with a **small** gate (~1.15 × rest) — they only need to
drift slightly apart. Distance-based, not a timer, consistent with the earlier hysteresis
decision and with the user's dislike of arbitrary cooldowns.

**3. Defaults must not change existing scenes.** `bondWobble` and `bondEnergy` both default
**0** (off). Existing saved scenes behave exactly as before; the new physics is opt-in, which
also matches the "every feature is a zeroable slider" principle. Note the consequence: to get
the intended behaviour the user must set **both** merge time > 0 *and* bond wobble > 0. The UI
needs to say this clearly or the feature will look broken.

**4. Instant-fuse bonds are exempt.** With `merge <= 0` there is no holding phase at all, so
thermal breaking has nothing to act on. `bondStability` returns 1 for those. Fine — but worth
being explicit that instant-fuse is the "frozen garbage" regime by construction.

**5. Grow applies to holding bonds.** `constraints()` scales rest by `1+grow` using `s.obj`,
and a holding bond inherits the obj of node `a`. A growing object will therefore stretch its
own holding bonds → constant strain → they die faster. Arguably *correct* (growth strains
fresh bonds) but it's an interaction to watch.

---

## Per-endpoint types — design sketch (not yet built)

Current model: connector identity is **per object** (`objType(o) = o.ids[0] || o.name`), and
profiles live at `o.endType[targetType]`. Every tip of a Y therefore shares one rule set —
exactly the ceiling the user hit.

Minimal-restructure proposal:
- Each node may carry `n.ctype` (its own connector identity); falls back to the object's type.
- Lookup becomes `nodeType(n)` instead of `objType(o)` — so the *target* is identified by the
  tip it presents.
- For *my* tip to have its own rules, profiles key on a pair: `o.endType[myTip + '>' + target]`.
  Flat string key keeps object-level storage, so save/load stays simple.

Touches: profile lookup, `ensureProf`, the whole Connect tab (becomes a matrix), save/load,
and node id assignment on import. Genuinely the biggest change discussed — deserves its own
pass rather than being bolted onto this one.

Open question for the user: how should tips get their types? Options are (a) authored in
Blender via vertex attribute, (b) assigned in-app by clicking endpoints, (c) auto-assigned by
index (tip 0, tip 1, tip 2) with renaming. (c) is cheapest and probably enough to start.

---

# IMPLEMENTATION LOG — reversible bonds, hardening, bond energy (DONE, untested by user)

## What shipped

**`bondStability(s)`** — `bStr + (1-bStr)*(age/mergeTime)^hardenPow`. Returns 1 for
instant-fuse bonds (no weak phase to speak of).

**`thermalBreaks()`** — runs once per frame (not per substep; dissociation is slow). For each
holding bond: `p = bondWobble * exp(-stab*4/kT)`, `kT = temp*0.5`,
`stab = bondStability - smoothedStrain`. On break: energy cost, plus a small distance gate
(1.15 × rest) via the existing `sepFrom`/`sepDist` so it can't re-bond in the same spot next frame.

**Bond energy** — `releaseHeat()` on formation (0.5×) and on commit (1×); `coolNodes()` on break.

**Safety cap** — `S.maxBondEvents` (40/frame) on bond creation, thermal breaks, and merges.
This is the long-backlogged cap; it's a fixed constant, *not* load-dependent, per the
stationarity rule in `philosophy-and-direction.md`.

**UI** — Physics · Chemistry: *bond wobble*, *bond energy*. Connect profile: *bond strength*,
*harden curve*. Both globals default **0** (off) so existing scenes are untouched.

## Four calibration problems found by measurement (all fixed)

1. **The exponential wasn't sharp enough.** `exp(-stab/kT)` gave only ~1.8× discrimination
   between a comfortable and a strained bond. Real bond barriers are *many* kT deep — that
   depth is exactly what turns a small difference in fit into a large difference in lifetime.
   Added a ×4 factor → discrimination went to ~7.6×.

2. **Thermal jitter swamped the fit signal.** Instantaneous strain is dominated by vibration,
   not by fit. Fixed by smoothing (`strainAvg`, 0.92/0.08). Physically right: dissociation is
   slow next to vibration, so it responds to average stress.

3. **Raw strain ratio penalised everything.** A bond forms wherever the ends happen to be
   (up to `snap × rest`), so a perfectly good bond could sit at 25%+ "strain" forever and
   permanently lose that much stability. Fixed by normalising against the bond's own break
   span: `strain = (len - rest) / ((brk-1) * rest)` — i.e. *how far along the way to snapping
   is this bond sitting*. Bounded, meaningful, and zero for a comfortable bond.

4. **Hardening outran breaking.** With `hardenPow` 1 (linear), stability rose faster than
   thermal breaking could act, so bonds were safe before selection had a chance. Default is
   now **2** (ease-in): stays weak longer, then commits — which is the whole point of having
   a curve.

Also: **bond energy applied directly to the two bonded nodes is invisible** — their brand-new
constraint cancels it on the same frame. `releaseHeat()` therefore spreads it to the
neighbours (0.6) as well as the pair (0.4), which is also the physically correct picture
(bond energy goes into the structure's vibrational modes).

## Verified

thermal breaks fire and scale with temperature · temp 0 → no spontaneous breaking · stability
ramps with age (0.43 → 0.88) · strained bonds die ~7.6× faster than comfortable ones · bond
energy raises kinetic energy · save/load round-trips `bStr`/`hardenPow`/`bondWobble`/`bondEnergy` ·
defaults off leave the default scene and the user's Circle.002 scene NaN-free · **regressions
pass**: atomic-edge breaking (39→39 edges under grow), no Y-junctions (max degree 2),
expand-to-fit still scales (175→351).

## HONEST CAVEAT — needs the user's eyes

The *mechanism* is verified. The **operating window is not**: whether good bonds commit while
bad ones don't depends on `bondWobble` × `mergeTime` × `bStr` × scene geometry, and my
synthetic two-strand rig turned out to be a poor proxy (collinear strands wedged by collision
sit at odd rest lengths, so absolute lifetimes there don't transfer). Rough starting point to
try, then tune by eye:

- `merge time` 60–200, `bond strength` 0.3–0.4, `harden curve` 2, `bond wobble` 0.02–0.06,
  temperature ~1.
- If nothing ever commits → lower wobble or shorten merge time.
- If everything commits regardless of fit → raise wobble, lower bond strength, or raise the
  harden curve.

**Watch for:** wobble does nothing unless `merge time > 0` (the UI says so, but it's the most
likely "it's broken" report).

## Not started: per-endpoint types

Design sketch is above and unchanged. Still needs a decision on **how tips get their types** —
authored in Blender (vertex attribute), assigned in-app by clicking an endpoint, or
auto-assigned by index with renaming. Auto-by-index is cheapest and probably enough to start.

---

# SELECTION — steps 1-2 built (hover + double-click select), UNTESTED by user

Additive only; the existing object editor and workflow are untouched. Build order steps 1-2 of
`selection-and-materials-spec.md`.

**State:** `Sel = {hoverNodes, hoverEnd, nodes, end}`. Selections stored as **node index sets**
(never segment indices — those reindex on break/merge, per the spec).

**Picking:** `pickHover(mx,my)` — endpoint if cursor is within ~16/z px of a degree-1 node, else
the **stretch** under the cursor. `stretchAt(si,adj)` flood-fills same-material (`s.obj`)
non-bond segments from the hovered segment → node set; stops at material boundaries. `segAdj()`
builds a node→segIdx map once per pick (O(E), on pointermove only). `nearestSeg`/`nearestEnd`
are linear scans for now — fine at current scene sizes; reuse the collide bucket grid if it bites.

**Interaction:** idle pointermove (move tool) → hover highlight. `dblclick` → select hovered
stretch/endpoint and `selectObject()` its material so the panel focuses it. **shift+dblclick** →
grow selection to the whole connected piece (`pieceNodesOf`). Single-click still grabs/drags
exactly as before (no mode change).

**Render:** hover = soft blue over the stretch (or a blue dot on the endpoint); selection =
bright white over the stretch (or cyan dot on the endpoint). Replaced the old whole-object white
outline; the list-selected material still faint-outlines when no geometry stretch is picked.
`pruneSel()` drops degree-0 (orphaned/merged-away) nodes each frame and clears a stale endpoint.

**Verified:** hover detects a 6-node stretch mid-body and an endpoint near a free end; double-
click focuses the right material; grow-to-piece returns the whole piece; in a fused RED+BLUE
strand (one 5-node piece) hovering the red half selects only the 3 red nodes (stops at the
material boundary); live material editing still works; render doesn't throw; regressions
(atomic edges, no-Y, expand-to-fit, save/load) all pass; default + user scenes NaN-free.

**Next (step 3+):** panel routing (endpoint selected → show that slot's rules), then endpoint
slots replacing the single shared connector type, then select-similar/box-select and
"make its own material". Paused here for user testing per the plan.

---

## Fix: default blend 1 -> 0 (chimera, not cascade)

User reported merging a green string into a red one turned the WHOLE green string red — a
material cascade. Cause: `mergeEnds` line ~803 (inside `if(blend>0)`) reassigns every segment of
the fused piece to objA (`s.obj=objA`), so with blend>0 the whole joined string unifies to one
material. The default blend was still **1**, despite our earlier agreement (philosophy doc / the
materials discussion) that blend 0 = keep-your-own-material chimera should be the default. Flipped
ENDDEF.blend and S.bondBlend to **0**. Verified: default-profile green+red merge now keeps 2
materials (chimera); blend 1 still available and still unifies for anyone who wants attribute
averaging. The blend>0 whole-string reassignment behaviour is left as-is (opt-in).

---

## Click-to-activate-material (replaces double-click select)

Per user: any click on geometry now makes that material active in the panel — including a click
that starts a drag — so you tinker with settings without visiting the list. Implementation: in
pointerdown, grabbing a node calls `selectObject(node.obj)`; a click that lands mid-strand (no
node close enough to grab) does a `nearestSeg` pick and activates that segment's material without
panning; only a click on truly empty space pans, and it leaves the active material untouched.
Removed the `dblclick` stretch/endpoint-select handler and the bright Sel.nodes/end selection
render (hover highlight stays as the pre-click cue; endpoint selection returns with the slot
panel). Verified: click strand A -> AAA active, click B -> BBB, click empty -> stays BBB, hover
still detects stretches.

---

# IN-APP AUTHORING: materials list + draw/erase (Tab = edit mode), UNTESTED by user

Data model decision: **a material IS an object** (least invasive; the list already shows objects,
editing writes to one, bonding uses it, scattered geometry already supported). Drawing appends
strokes to the active object.

**Materials list** (was "Objects"): `+ material` creates an empty user-made object
(`o.userMade=true`, `OBJDEF` blank-ish so a drawn strand holds shape — stiff 0.12 not 0),
auto-named "Material N", palette colour, auto-selected. Empty user-made materials now show in the
list (merge-absorbed empties still hidden). Each row has a `×` delete (`removeMaterial` splices
the object, decrements higher `obj` refs on nodes/segs, rebuilds index lists). `new scene` clears
and drops in a fresh "Material 1".

**Tab toggles Edit/Scene** (`setEditMode`): auto-pauses, swaps the toolbar (Move/Cut ⇄
Pencil/Eraser), ensures a material exists, sets the Pencil tool, and flips the scene tag to
"edit".

**Pencil** (`tool==='draw'`): pointer path sampled at ~12px spacing into a point list, preview
drawn live in the material's colour; on release `addStrokeToObject(activeObj, pts)` builds a node
chain + segments belonging to that material and rebuilds nbrs/exclusions/init snapshot. Draws onto
the active material; if none exists one is created.

**Eraser** (`tool==='erase'`): drag → `eraseAt` marks segments within ~14px of the cursor dead,
filters them out, rebuilds index lists (orphaned nodes drop from nodeIdx but stay in G.nodes so
indices remain stable — critical, per the selection spec).

**Verified:** material create (+ shows empty in list), stroke append, multi-stroke accumulation
onto one material, erase, edit-mode toggle (pauses + swaps toolbar + draw tool), new scene;
authored strands simulate stably, hold their drawn shape (don't collapse), and save/load
round-trips them; regressions (atomic edges, no-Y, expand-to-fit, save/load chemistry fields)
all pass; no NaN.

**Deferred (as agreed):** convert-strings-to-material (eyedropper/painter), polyline-precision
pencil (freehand only for now), curated per-demo UI. Next natural step remains endpoint slots
(per-tip connector types) — now easy to author test rigs for with the pencil.

---

## UI restructure: 2 tabs + collapsible panels, UNTESTED by user

Tab bar cut from Scene/Objects/Physics to **Scene / Objects**. Physics cards moved into the Scene
panel (Simulation + Globals now live under Scene); About moved to the bottom of Scene as a footer.
So Scene reads: Scene, View, Simulation (with Defaults/Chemistry sub-headers + bonding master),
Globals, About.

**Collapsible cards:** each `.card`'s first eyebrow toggles `.collapsed`; CSS
`.card.collapsed > *:not(:first-child){display:none}` folds everything but the header (so a card's
own sub-headers like Defaults/Chemistry hide too). A rotating triangle marks state. Handler only
wires each card's FIRST direct-child eyebrow, so sub-headers aren't accidental toggles and clicking
a control inside a header doesn't collapse it.

**Object editor:** the General/Affinity/Connect sub-tabs (`.etab`/`.etabpanel`, removed) are now
stacked **`.subfold`** sections, each independently collapsible with its own small header. Editor
still populates + edits normally.

**New scene** button added to the Scene tab too (`bNewScene2`); both it and the Objects-tab button
call `doNewScene()`.

Verified: two tabs; physics/bonding-master present under Scene; cards + subfolds collapse/expand;
collapsing hides sub-headers; sub-headers don't toggle; About nested correctly inside Scene;
editor works; default scene runs (46fps, no NaN). Screenshotted both tabs — layout clean.

---

## Performance audit — heavy bonding/breaking churn

User reported large slowdowns during lots of bonding/breaking (wobble/energy off). Profiled the
churn case (Circle.002, instant-fuse + bend-break, ~8 merges/frame):

**Breakdown found:** collide 63-73%, endpointForces 18-27% (scales with pull wRange — small ranges
~halve it), computeExclusions 14%, buildNbrs 5%. So the floor is dense collision, not the new
chemistry (bonding added only ~3.6ms over a ~17ms baseline). But two real inefficiencies:

1. **`mergeEnds` rebuilt topology ~8x/frame**, and `rebuildTopology` recomputed exclusions each
   time (computeExclusions is O(segs x skip-depth x degree)). FIX: `rebuildTopology` now only does
   segIdx + buildNbrs and sets `G.exclDirty`; `collide` calls `flushExcl()` at its top, so
   exclusions recompute **lazily, at most once per frame**, coalescing all the frame's merges/breaks
   into one pass. flagStrain/BendBreaks also just set exclDirty. Result: computeExclusions calls
   dropped from ~9/frame to **1/frame**; clean churn timing ~63fps.

2. **Node count grew unbounded** — sever adds a node (dupNode), merge orphans one, and with
   instant-fuse there are no dead segments so `removeDead` never cleaned up. Over a long session
   every O(nodes) pass (integrate, buildNbrs, computeExclusions map) slowly degrades. FIX:
   `compactNodes()` (called every frame, self-gating: only fires when orphans >=128 and >=50% of
   nodes) drops orphaned nodes and remaps every index that points at one — seg.a/b, obj.nodeIdx,
   G.init, bondBank keys, `grab`, and Sel.* selections. Node count now oscillates in a bounded
   sawtooth (~live..2x-live) instead of climbing (was 601 -> 1989+ over 400 frames; now caps
   ~1200 and drops back to ~600).

**Verified:** exclusions 1/frame; node count bounded; zero bad seg refs after compaction;
selections survive compaction (valid indices); reset works post-compaction (no NaN); regressions
(atomic edges, no-Y, expand-to-fit) pass; default + user scenes NaN-free; bond energy still works.

**Honest note:** the residual cost is collide on a canvas-filling dense scene — inherent, not a
bug. Biggest user-side lever is smaller endpoint pull ranges (wRange/sRange). The churn itself
(instant-fuse + bend-break shatter/reform) is the earlier-diagnosed dynamic; wouldBendBreak reduced
it but it still cycles. A future collision broad-phase optimisation would help the floor.

---

## Investigation: "draw a string -> framerate halves, reset doesn't fix it"

Profiled the exact scenario (busy Circle.002 scene, draw ~20-pt string, play, reset). Findings:

**1. Drawing adds real, expected collision cost.** A drawn string is a NEW object, so wherever it
overlaps dense geometry it collides with everything there — its segments don't get the
self-exclusion the scene's own object enjoys. Measured ~1.3-1.6x in a canvas-filling scene
(more where the stroke crosses denser regions). Not a bug; it's the geometry doing work.

**2. Why reset doesn't clear it (the real answer).** `build()` (demo scenes) sets
`G.lastImport=null`; only `importJSON` sets it. `resetSim` reimports ONLY when `G.lastImport`
exists. For a demo/drawn scene it falls to the `G.init` snapshot path — and `addStrokeToObject`
calls `snapshotInit()`, so the snapshot now INCLUDES the drawn string. Reset restores it right
back -> cost persists. (Imported JSON scenes DO drop the drawn string on reset.) Also:
`resetSim` early-returns if `G.init.length !== G.nodes.length`, so after churn changes the node
count, reset can silently no-op entirely.

**3. No persistent algorithmic leak.** After reset, collision pair count (~4600-4900) and all
collide params (r, padSelf, gThick) are identical with vs without a prior draw; `inter` maps are
empty in both. The engine workload is genuinely restored. A ~1.3x timing wobble I measured
post-reset does NOT correspond to more collision pairs -> attributable to GC/JIT + a little stale
editor DOM, not the sim doing more work.

**4. The perf fixes from the prior commit** (exclusion coalescing 9->1/frame, node compaction)
still apply and help the general churn case the user is in.

**Fix shipped:** on reset, if the selected material no longer exists after reimport, clear
`S.selected` and hide the editor (removes stale editor DOM). Small hygiene fix.

**Open design question for the user:** should Reset *discard* drawn/edited geometry (return to
the authored/original scene) or *keep* it (re-run the sim from the current layout)? Right now
imported scenes discard, demo/drawn scenes keep — inconsistent. Worth unifying once they say which
they want. Also worth making resetSim robust to node-count mismatch so it never silently no-ops.
