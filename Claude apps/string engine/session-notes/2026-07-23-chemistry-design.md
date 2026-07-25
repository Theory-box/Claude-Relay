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

---

## Snap-distance legibility: fixed reach calc + live halo overlay

User: snap slider felt wrong ("says 8px but 25px won't snap"). Verified the ENGINE trigger is
exact — bonding fires precisely at snap x (effR_self + effR_target) (measured across 5 configs,
matched to the pixel). The bug was in the READOUT I'd added earlier:
- `bondRest = 2*effR(self)` — wrong for bonding to a different-thickness target; should be
  `effR(self) + effR(target)`.
- `reachC = 2*(effR+pad)` — **double-counted padding**; the real collision standoff is
  `effR_self + effR_target + pad` (ONE gap between the two surfaces, not two).
So it reported a larger "needed" snap than reality — exactly the user's symptom.

Fixed `updReach`: looks up the real target object's effR, uses single padding (padSelf for self,
max padOther for cross), and now reads "bonds within X px · collision holds Y px apart · breaks
at Z" with a warning when snap can't reach past the standoff. Verified: THICK(8)+THIN(2) self
padSelf 4 -> standoff 20 (was buggy 24), snapPx 24.

**Live halo overlay:** `updReach` sets `S.snapViz={objIdx,snapPx,standoff}`; render draws at each
free end of the selected bonding object a filled green disc at the snap-reach radius and an amber
dashed ring at the collision standoff. Updates live as the snap/thickness/padding sliders move.
When the amber ring sits OUTSIDE the green fill, you can see at a glance that collision holds ends
too far apart to bond. Cleared on reselect (S.snapViz=null in selectObject). Shows for whichever
profile is open (self by default, or the clicked external-target chip). Regressions + health pass.

---

## UI: General/Affinity/Connect as distinct panels

User found the editor sub-sections hard to read as separate collapsible panels (small labels in
one shared box). Restyled `.subfold` as distinct inset panels: dark fill (--ink2), border, 11px
radius, 13-14px padding, 11-12px margin between. Headers bumped to 11.5px bright text with a
bottom-border separator and an accent-coloured collapse triangle (clearly foldable). Made
`#objEditor` borderless/padding-0 so the three inner panels are the visible boxes, with a light
"Editing · name" label above. Removed the inline label styles. Collapse still works; editor still
renders. CSS/markup only, no logic change.

---

## Fix: snap halo now tracks padding (and everything) live

User: increasing self-padding didn't move the collision-standoff (amber) ring. Cause: the halo
drew CACHED snapPx/standoff written only inside `updReach` (runs on Connect-slider move / re-render),
so the General-tab thickness/padding sliders didn't update it — thickness only appeared to work when
a re-render happened to fire. Fix: added `snapDistances(o,type)` helper (er+erT bond rest, single
padding: padSelf for self / max padOther for cross) and made render call it EVERY FRAME, so the
halo recomputes from current thickness, gThick, padSelf/padOther live. `S.snapViz` now stores
`{objIdx,type}` (which profile), not cached numbers. `updReach` uses the same helper for the text
and stores the active updater in `curReachUpd`; the thickness/padOther/padSelf sliders call it so
the text readout stays in sync too. Verified: padSelf 6 moves standoff 8->14, thickness 8 moves
snap 12->24 and standoff ->16, live. Regressions pass, render clean.

---

## Snap viz audit + generalized padding envelope

Audited the "green circle too big at high thickness" report: measured actual max bond gap vs drawn
green radius across thickness 3/6/12 -> EXACT match (9=9, 18=18, 36=36). No calc bug. The green
radius IS the true bond distance. User's confusion was geometric: two full-radius circles visually
overlap at 2x the bond distance, but bonding fires at 1x — so "circles overlap" is not the bond
test; "the other endpoint's dot inside the circle" is.

Redesigned the overlay per user's idea:
- **Padding = whole-object envelope**: amber translucent band (lineWidth 2*(effR+max(padSelf,padOther)),
  round caps) stroked along every segment of the selected object — shows the collision keep-out
  everywhere, not just at ends. Only when padding>0. Recomputed live (uses effR + pads).
- **Green snap-reach circles stay at free ends** (only while a bonding profile is open via S.snapViz),
  now each with a solid green **dot** at the endpoint so it reads as reach-from-the-dot (a partner
  end's dot entering the circle bonds) rather than misleading circle-overlap.
Frees the endpoints for future weak/strong range rings. Connect note updated to explain the colors.
Green radius still equals the true bond distance; envelope tracks thickness+padding live.
Regressions pass, render clean.

---

## Heat / energy visualization (overlay)

User wanted to SEE bond energy / heat accumulation (recalling an old background-red cue). Added a
`show heat` toggle (Physics·Chemistry, `S.showHeat`, default off). When on, render overlays:
- additive warm glow at each node whose per-frame speed (|x-px|) exceeds ~0.6px, colour/size
  ramping cool-warm to hot (yellow->orange->red) up to ~4.6px/frame — shows WHERE energy is
  (bond-energy release, thermal wobble, collisions);
- a faint whole-field red tint scaled by average kinetic energy (the old background-red cue).
Works as an overlay on top of normal colours (visible alongside the wiggling), not a replacement
view mode. Guarded by `if(S.showHeat)` so zero cost when off. Verified: bond-energy release raised
KE 0->1.65 and the glow warmed a hot node's pixel (r 55->130); toggle wires; regressions pass.
Frees us to later tie glow intensity explicitly to releaseHeat events if the ambient-speed proxy
isn't punchy enough.

---

## Energy consolidation: heat-drop bug + retire wobble + energy-aware damping

Three changes, all verified:

**1. Heat-drop bug (fixed).** The "heat instantly cuts in half after a while" was the heat overlay
glowing EVERY node — including thousands of invisible orphan leftovers from merges. When
`compactNodes` fired (halving node count), half the glow blinked out at once. Fix: the heat overlay
(and its background-tint average) now only counts CONNECTED nodes (`G.nbrs[i].length>0`). Orphans
don't glow; compaction no longer causes a phantom heat drop. Verified: across a compaction event
(nodes 3970->2476) live-node heat stayed 5.77->4.76 (smooth), vs the old instant halving.

**2. Retired the wobble knob; real motion drives breaking.** `thermalBreaks` (stochastic
temp-probability dissociation) is retired to a no-op. `flagBondBreaks` now tears a holding bond when
its ACTUAL stretch exceeds a **stability-scaled** threshold: `brkRatio = 1 + (brk-1)*bondStability`.
A young bond (low stability) breaks near rest length — fragile; a hardened bond holds to full
brk x rest. So heat/collisions/bond-energy create real strain, and strain breaks bonds — one physical
mechanism, not a separate probability. Energy cost (coolNodes) + re-heal gate (sepFrom/sepDist)
moved into flagBondBreaks. Removed `bondWobble` state, UI slider, sync, and save/capture refs.
Selection pressure preserved: strained young bonds exceed their low threshold and die; comfortable
ones survive to harden. Verified: bonds still form, and a pinned/strained bond breaks with no wobble.

**3. Energy-aware damping (heat lingers).** In `integrate`, a node moving faster than ~1.5px/frame
sheds up to 65% of its damping (floored). Ambient thermal jitter damps normally; hot bursts
(bond-energy release, collisions) persist and spread instead of draining in ~3 frames — so heat
accumulates locally the way the user expected, using the existing nodes (no heat grid). Verified
stable (no NaN) under temp 1.6 + bond energy 3; live heat sustained ~4-7 through the churn phase.

Regressions (atomic edges, no-Y, expand-to-fit, save/load) pass; default+user scenes NaN-free.

DEFERRED (user's to-do): a coarse heat-field grid to act as "the millions of unimportant particles"
that carry/transfer heat — only worth it later if heat needs to cross empty space independent of the
strings. Current microscopic model (moving nodes = heat) is the honest representation; the grid would
fake the large-N reservoir. Revisit after assembly mechanics mature.

---

## Strand look: fill + outline controls

User: merged sub-strings read as separate because of "black outlines" between them. Diagnosis:
there is NO drawn outline on non-solid strands — the "borders" are background GAPS. The fill was
drawn at r*1.7 (~0.85 of the collision diameter 2r), so touching strands leave a background sliver
that reads as an outline, and a dense chimera bundle looks disconnected.

Added (View card · Strand look):
- **Fill** (0.5-1, default 0.95): fill width = 2r*fill. Near 1 closes the gaps so a merged bundle
  reads as one connected shape. This is the default fix for the user's problem.
- **Outline** (0-1.2, default 0 = off): optional dark casing (rgba(8,9,18)) of half-width
  fill + r*outline, i.e. scaled by thickness (bigger strands get bigger outlines) as the user asked.
- **Outline opacity** (0-1, default 0.85).
State: strandFill/outlineW/outlineA (view prefs, not serialized — persist across reset naturally).
Verified by pixel sampling: fill widens the strand (5px off-centre filled at 1.0, dark at 0.55);
outline draws casing (8,9,18) distinct from bg. Regressions pass.

---

## Performance pass (no quality loss): numeric bucket keys + tighter endpoint search

Profiled the churn scene (temp 1, bonding+breaking, ~3000 nodes/1666 segs): collide 48% +
endpointForces 30% = 78%. Two clean wins landed (~47.7ms -> ~40ms/frame, ~15-18% faster):

1. **Numeric bucket keys** in collide AND endpointForces — replaced string `x+'_'+y` Map keys with
   `(x+16384)*32768+(y+16384)`. Pure hashing speedup, identical pair sets, zero behavior change.
2. **Exact endpoint search radius** — endpointForces search was `snap*4*effR` (a 4x fudge). Replaced
   with `snap*(effR+maxER)` where maxER = global max effR = the true max bond distance. Tighter grid
   -> far fewer candidate pairs. endpointForces dropped 30% -> ~18-20%. Verified bonding still fires
   at EXACT distances (9=9, 20=20 both asymmetric directions).

REJECTED (quality would change): (a) an AABB-reject before closest() — no help in dense scenes (most
bucket pairs are real contacts), adds per-pair overhead. (b) a 2D-flat collide path (use3 only in 3D
when weave>0) — LOOKED equivalent since h=0 at weave 0, but an A/B showed flat-scene overshoot
diverging (74.7 -> 131+ over 80 frames). The overshoot is chaotic, so even sub-epsilon differences
between the 2D and 3D-with-h=0 code paths amplify. Also caught a real bug it introduced: `use3` does
double duty (3D math AND the `use3?0:S.wallPad` rule), so tying it to weave wrongly added wallPad to
flat strand-strand contacts. Reverted entirely — collide is now byte-identical to the original.

collide (48-60%) remains the floor; it's inherent to dense contact resolution (closest() x pairs x
iters). Broad-phase can't help a uniformly dense field. Left as-is. Regressions + health pass.

---

## Perf brainstorm round 2: hypot WIN, flat-2D + buffers DUDS

**WIN — Math.hypot -> plain sqrt (~1.25x, shipped).** Microbench: Math.hypot(x,y,z) is 7.4x slower
than Math.sqrt(x*x+y*y+z*z) in V8 (hypot does overflow-safe scaling, pointless at pixel scale);
accuracy diff 4e-16 (last bit). Replaced all 19 hot-loop hypot calls with inlineable hyp2/hyp3.
End-to-end 1.25x faster; emergent behaviour statistically identical (bonds 1014->953, KE 6.11->6.33,
both within chaotic run-to-run variance; no NaN). NOT bit-identical (4e-16 amplifies chaotically) but
quality-identical — the sim already uses Math.random so it isn't bit-reproducible across runs anyway.
Regressions pass. This is the real gain.

**DUD — flat-mode 2D (skip h when weave=0) + buffer reuse + render-sort skip.** User requested both.
Implemented carefully: separated use3 (drives wallPad) from the 3D-math flag (use3 && weave>0);
reused bucket Map / pooled bucket arrays / pairs array / seen Set across frames; skipped the render
height-sort in flat mode. VERIFIED bit-identical in flat mode (deterministic hash matched exactly:
1295176995/2420970263) and weave still runs clean. BUT measured 0.97x raw and 0.99x avg / 0.95x p99 —
neutral-to-slightly-WORSE. Why: (a) the h terms in closest() are a couple of multiply-adds, negligible
next to the divisions + sqrt, so skipping them saves nothing; (b) V8's generational GC handles the
short-lived per-frame allocations cheaply, so pooling just adds pop/reset overhead that cancels any
saving. Reverted all three — no dead complexity for zero gain.

Standing conclusion (reinforced): the hot path is compute-bound (divisions, sqrt). CPU wins now come
from cutting the actual float ops (hypot was the big one) — data layout, allocation, and skipping
near-zero terms don't move it. Remaining CPU levers are thin; GPU (throughput) is the real next tier.

---

## Perf brainstorm round 3: microbench sweep + structural ideas

Microbenched the remaining "slow stdlib call" candidates (the hypot-hunting method):
- **Math.pow(x, hardenPow): NO win.** V8 optimizes pow even for variable exponents; a fastPow
  integer special-case was 0.9x (branching cost > saving). Dead end.
- **Math.min/Math.max vs ternary: 1.1x.** Marginal, not in the hottest loop (closest doesn't use
  them). Skipped.
- **division vs shared inverse: 1.2x on the op.** APPLIED to the contact push: share `1/dist` and
  `1/Wt` instead of 3x `/dist` + 2x `/Wt`. ~1.1x on collision-dominated frames (~3-5% on full dense
  frames). 1-ULP change (like hypot), quality-identical, regressions pass. Shipped.
- clamp is already a ternary (no win).

Structural ideas considered and rejected:
- **"Single strings cheaper"** (user idea): a 2-point string still needs segment-segment distance;
  closest() is already the minimal exact computation. Treating short segments as points would be an
  approximation = behaviour change. No clean win.
- **Existing libraries** (user idea): Box2D/Matter.js/Rapier are rigid-body; none model deformable
  strings with dynamic bonding/breaking topology. Would be a rewrite AND wouldn't fit the model.
- **Warm-starting contact points** (cache closest's s,t across the 4 iterations, recompute only
  distance): a real physics-engine technique, but it's an approximation (s,t drift) -> behaviour
  change. Opt-in only, not a free win.
- **Cutting-edge (2023-24)**: VBD (Vertex Block Descent, SIGGRAPH'24), XPBD variants, IPC — all
  either GPU-parallelism plays or higher-quality-but-slower. Nothing that speeds up single-threaded
  compute-bound CPU work.

CONCLUSION after 3 passes: hypot (20%) was the one big CPU win; div-inverse is a small bonus. The
loop is compute-bound and now near its floor. Verdict stands: further real speed = GPU (throughput),
which needs a testable env and is a dedicated project. CPU perf pass is DONE.

---

## Endpoint connectors — Stage 1: click-select + dynamic panel (built)

Building toward per-tip connector types (the replicator unlock). Design agreed with user:
- Connector types = a creatable/assignable LIST (like materials); assign in-app by clicking a tip.
- A connector has: a type/slot, what it bonds to, and (later) a preferred CONNECTING ANGLE (60deg
  builds triangles, 90 grids, 180 straight chains — turns "sticks together" into "assembles").
- Dynamic settings panel: the editor shows only what's relevant to the selection.
Build order: (1) click-select + dynamic panel [THIS], (2) per-endpoint slot types, (3) angle constraint.
Sibling feature logged: eyedropper to reassign a strand's material.

Stage 1 shipped:
- `selectEndpoint(node)` — clicking a free tip (degree-1 node) selects it as a connector (Sel.end).
  pointerdown now routes: free tip -> selectEndpoint; mid-strand node/body -> selectObject (material);
  empty -> pan (selection untouched). Material-list click clears Sel.end.
- `refreshPanelMode()` — dynamic panel: endpoint selected -> shows ONLY the Connect subfold + header
  reads "Connector"; strand selected -> shows General + Affinity, hides Connect, header "Editing".
  Called at the end of selectObject. Header span #edKind toggles the label.
Verified: strand -> {General:on, Affinity:on, Connect:off, "Editing"}; endpoint -> {General:off,
Affinity:off, Connect:on, "Connector", Sel.end set}. No errors. The selected tip already draws a
bright dot (existing render). NEXT: Stage 2 per-endpoint slot types.

---

## Endpoint connectors — course correction + quick UI wins

**Reverted Stage 1's endpoint-gating.** User caught the flaw: a closed loop (circle) has no free
tips, so gating connector settings behind endpoint-selection makes them unreachable without cutting.
Better model (user's): connectors are RULES ON THE MATERIAL ("heads accept X, tails accept Y,
self-connect y/n") applied to ends procedurally — NOT hand-assigned per tip. So connector settings
live with the material again (Connect subfold always visible). refreshPanelMode now shows all
sections; pointerdown selects the material for any geometry click (no endpoint branch). selectEndpoint
removed. Stage 2 is re-scoped: material-level connector RULES + per-end ROLES (head/tail) rather than
manual slot assignment.

**Quick wins shipped (all verified):**
- Leaving edit mode (Tab) now RESUMES the sim (was staying paused).
- **H key = clean view**: hides ALL overlays (heat, snap/collision viz, padding envelope,
  selection/hover highlights) so you see just the strings — for debugging behaviour, then toggle back.
  State S.cleanView; render blocks gated with !S.cleanView.

Regressions pass.

**BACKLOG captured from user (this session):**
- Dynamic TABS: click empty -> Scene tab, click object -> Objects tab (the right dynamic UI, works
  for circles). [agreed, next]
- Show selected MATERIAL NAME top-left / prominent so you know what you're editing without scrolling
  to the list. [agreed, next]
- Close-shape on draw: if the stroke ends near where it began (+margin), close the loop (draw
  circles/squares). Snapping may already auto-close; matters for no-snap shapes. [agreed]
- Resample-curve tool (fix too-few/too-many-point shapes); maybe a global "resample to smallest unit"
  on load. [later]
- Eyedropper to reassign a strand's material. [later]
- Diegetic/in-canvas editing (drag a handle to set stiffness/angle) + attribute "paint" tools
  (thickness/stiffness/curl brushes that edit the whole material). [far future, user unsure]

---

## Dynamic tabs + connector model locked

**Auto-tabs shipped:** clicking geometry -> Objects tab (via showTab('objects') in pointerdown),
clicking empty space -> Scene tab. The active tab now reflects what you're looking at. (Manual tab
buttons still work; collapsing to a single contextual label is a later polish.) Verified.

**Connector type model — DECIDED (clean, no redundancy):**
User spotted the double-spec problem (connector says "connects to red" AND red says "accepts
connector"). Resolved with a type-compatibility model (DNA sticky-end / Winfree tile):
- Connector TYPES are a creatable list (like materials): "A","B","hook","loop",...
- Compatibility lives in the TYPE SYSTEM as a pair table: "A binds B", strength/snap/angle stored on
  the PAIR. One source of truth.
- A string just ASSIGNS a type to each end (head=A, tail=B). No accept-lists on strings/objects.
- Layering is one-directional: objects -> point at types; types -> point at each other. Objects never
  reference objects; types never reference objects. => the type assignments + pair table ARE the genome.
OPEN Q for user: symmetric compatibility (A~B implies B~A) vs directional (A-head seeks B-tail only,
DNA 5'/3' polarity). Lean symmetric first, add direction later.

Stage 2 build (pending user's symmetric/directional answer): a connector-type registry (create/name/
color types) + a compatibility table UI + per-material end-type assignment (head/tail). Then bonding
reads the endpoint's type (not objType) and the pair table. Stage 3: the angle constraint on the pair.

---

## Mass from thickness (area scaling) — shipped

Decoupling "solid": mass now comes from THICKNESS, not a flag. Established with user that solid was
bundling five things (heavy mass, anti-tunnel CCD, wall-pad, beady render, no-weave) and the "forces
weaker in solid" they noticed was just the inv=0.25 heavier mass reducing response to ALL forces
(force is applied as pos += force*inv). Fix: make mass a real physical property of thickness.

Implemented: inv = clamp(9/effR^2, 0.08, 3), i.e. mass proportional to AREA (r^2). 9 = R0^2 (R0=3) so
a default-thickness strand keeps inv=1 EXACTLY -> existing scenes behave identically. Thicker = heavier
(plows through), thinner = lighter (flung around). Helpers: invFromEffR(er), objInv(o),
refreshObjMass(o). Replaced all six inv-assignment sites (import, addGraphObject, addStrokeToObject,
setObjFixed, two merge/dup paths). setObjSolid NO LONGER touches mass (solid decoupled from mass).
eThick slider now calls refreshObjMass so mass updates live as you drag thickness.

Verified: inv by thickness r1->3, r2->2.25, r3->1 (default unchanged), r5->0.36, r8->0.14, r14->0.08
(clean r^2). Plow-through: thick r10 moves 36 vs thin r2 moves 138 (thin shoved ~4x). Live slider
update works. STABILITY: mixed-thickness (1.5/3/7) hot bonding scene has the SAME speed distribution
as uniform r3 (p50 2.4~2.5, p99 32.8~33) and a LOWER max transient (127 vs 216) — no destabilisation,
no NaN. Regressions pass.

Note: the beady SOLID render is already gone (user confirmed — happened via an earlier fill change).
Remaining "solid" bundle pieces still to fully decouple later: make reliable-collision (CCD) the
default for all so you don't need solid for accurate collision; then solid reduces to just "fixed
wall". fixed=immovable and weave stay their own toggles. Not urgent now.
