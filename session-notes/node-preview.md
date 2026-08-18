# Node Preview Live — session notes

**Branch:** `feature/node-preview` (off `main`)
**Blender target:** 4.4 (tested against a local 4.4.0 build)

## Goal
See procedural shader nodes (Brick, Noise, ColorRamp, Hue/Sat...) as an image
while editing, since the final render is Workbench (which never evaluates the
node graph, only shows the active image-texture node).

## Architecture (v0.2 — REWRITTEN after a freeze bug)
v0.1 rendered in-process on the main thread -> **froze the whole UI for the
render duration** (verified: a 256px render took ~2 min under software EEVEE;
also mangled the output path). Replaced with a **background-process** design:

1. Build a tiny temp scene in the main Blender: a COPY of the user's material,
   its target-node output rewired through an Emission to a fresh Output, on a
   1x1 UV plane under an orthographic camera. (Real material never touched.)
2. `bpy.data.libraries.write({scene})` -> a small temp .blend (only that scene
   + deps). Then the temp datablocks are removed from the main file.
3. Spawn a headless `blender -b job.blend --python np_worker.py -- SCENE OUT`
   via `subprocess.Popen` (non-blocking). The worker forces Cycles (1 sample,
   CPU), renders to PNG.
4. A `bpy.app.timers` poll (0.1s) loads the PNG when ready, tiles it (numpy
   np.tile NxN), writes it into a persistent image datablock, shows it in any
   open Image Editor. Temp files cleaned up.

Live mode: `depsgraph_update_post` sets a dirty flag; the timer starts a job
after `debounce` seconds of quiet (guarded by a busy flag + 0.1s cooldown so
our own datablock churn doesn't self-trigger).

## Verified on local Blender 4.4 (headless + xvfb)
- start_job returns in ~0.003s (non-blocking; no UI freeze).
- Full round-trip ~1-2s on a 1-core/no-GPU VM (spawn + render + load).
- Brick + Noise render correctly; tiling=2 -> 512x512 as expected.
- Live auto-render fires on edit and updates the image (brick -> noise).
- Temp files cleaned; timer unregisters when idle.
- `_find_target` resolves material+node via the active-object-material
  fallback even when space.id/edit_tree are unpopulated.

## Known remaining costs / limitations
- Fresh Blender spawn per render (~1-2s launch overhead each). NEXT OPTIMISATION:
  a persistent worker to cut this to <0.5s.
- Colour round-trips linear->linear through the PNG (both images default sRGB;
  should match, minor risk of a slight shift).
- Top-level Material nodes only (not groups, not World/Light).
- Materials using packed/relative image textures may not resolve in the worker.

## Milestones
1. **DONE + tested:** live render -> image datablock -> Image Editor.
2. **TODO:** viewport (Workbench) routing via a shader Image Texture node +
   active-vs-selected node handling + viewport GPU-texture refresh.
3. **TODO:** persistent worker; "Finalize" high-res bake button.

## Next actions
- User device test on the 4090 (expect much faster than the VM numbers).
- If good, add persistent worker, then start Milestone 2.

## v0.3 — hardening pass (audited on Blender 4.4)
- FIX: live mode now follows the active node (selection doesn't fire a
  depsgraph update, so the timer polls active-node identity). Fixed a deadlock
  where the debounce reset every tick.
- NEW: Lock feature — "Lock to Node" captures the current node; preview stays
  on it while you click/edit other nodes; unlock to resume following.
- Process cleanup verified: children reaped after completion, after 120s
  timeout, and on unregister/close mid-render (0 lingering in all tests).
- Confirmed no self-triggered render loop (the busy flag is the real guard);
  post-render cooldown reduced 0.1 -> 0.05s so live edits aren't dropped.
- No leftover temp files in any tested path.
- All checks pass headless on a local 4.4.0 build.

## v0.4 — GPU + samples + bigger sizes
- Worker now renders on GPU (activates the first available backend: OPTIX/
  CUDA/HIP/METAL/ONEAPI from the user's prefs) with automatic CPU fallback if
  no GPU device is present.
- NEW "Samples" slider (default 1, 1-256) passed through to the worker — raise
  for anti-aliased edges. Denoising stays off (emission has no light noise).
- Resolution cap raised 2048 -> 4096; tiling output cap raised 4096 -> 8192.
- Verified headless on 4.4: samples plumbing, CPU-fallback path, 4096 accepted,
  tiling 4 -> 1024. GPU branch is static-reviewed only (no GPU on the test box).
- Note: fresh-process-per-render means GPU context init each spawn; GPU mainly
  wins on big (4096+) / high-sample renders. A persistent worker would remove
  that per-spawn overhead — still the top future optimisation.

## v0.5 — device preference + status readout
- Add-on Preferences: "Render Device" = Auto / GPU / CPU. GPU uses the backend
  already set in the user's Cycles prefs (OptiX on desktop, Metal on the Mac).
- Worker writes a .status sidecar with the device it actually used; the panel
  shows "Rendered on: GPU (OPTIX)" (checkmark) or "Rendered on: CPU" (error icon
  if GPU/Auto was requested but fell back) — so GPU success/fallback is visible.
- BUGFIX: worker script was cached and only written if missing -> add-on updates
  ran a STALE worker (arg mismatch -> crash). Now always rewritten.
- Verified headless: Auto/CPU/GPU modes all report correctly (CPU on the no-GPU
  test box, incl. visible fallback when GPU requested); status files cleaned up.
  Actual GPU-success path is static-reviewed only (no GPU on the test box).

## v0.6 — Finalize to Object (fixes multi-object sharing)
- ROOT CAUSE of "refreshing one object changes another": there is a single
  shared image datablock (NodePreview_Result); the preview overwrites its
  pixels by NAME every render. Saving-as-JPEG doesn't detach the object's node
  from that datablock (the datablock keeps its name), so later previews clobber
  it. Any object whose node points at NodePreview_Result shares it.
- FIX: "Finalize to Active Object" button. Copies the current preview into a
  new independent, uniquely-named, packed image and repoints the active
  object's image-texture node(s) at it. Object then owns its image; future
  previews never touch it. Removes the manual save/reload workflow.
- Verified headless on 4.4: after finalize, later previews change
  NodePreview_Result but leave the finalized object's image untouched.

## v0.7 — fix multi-object texture clobbering (real root cause)
- ROOT CAUSE (verified): "Save As" on the preview image binds that file's path
  to the preview datablock. Blender then REUSES that datablock when the file is
  opened (reuse-on-open by filepath) -> the user's node becomes the preview
  datablock -> next render overwrites their texture. (v0.6's dedup theory was
  wrong; confirmed by test.)
- FIX (safeguard in _store_result): never render into a preview datablock that
  the user has claimed (has a filepath or source != GENERATED). Such a datablock
  is renamed aside (to its file's basename) and a fresh generated preview is
  created. Verified: claimed texture preserved & independent; normal
  render-to-render reuse still works.
- RECOMMENDED native workflow: use Image > "Save a Copy" (not "Save As") — it
  writes the file WITHOUT binding the path to the datablock, so reload is always
  independent and the preview stays the clean live target. Verified.
- REMOVED the "Finalize to Active Object" button (was a workaround for the bug;
  no longer needed).

## v0.8 — warm worker for live mode (safe persistent process)
- LIVE mode now keeps ONE persistent `blender -b --python worker --serve`
  process warm between renders (skips startup + GPU init). Verified reuse:
  first job ~0.5s, subsequent ~0.05s on the test box.
- MANUAL refresh stays a one-shot spawn (cold), as requested.
- SAFETY (all three verified on 4.4, cannot orphan):
  1. Dead-man switch: worker reads jobs from our stdin pipe; if the main
     Blender dies, stdin hits EOF and the worker exits immediately (~0.1s).
     (Reader thread pushes a sentinel to wake the job loop at once.)
  2. Idle timeout: worker self-exits after WARM_IDLE_SECS (60s) with no job.
  3. Explicit stop: QUIT + kill/reap on live-off, addon disable, and quit.
- Protocol: main writes "RENDER<TAB>blend<TAB>scene<TAB>out<TAB>samples<TAB>mode";
  worker opens the job .blend, renders, writes "<out>.done" (device string, or
  "ERR:..."). Main polls the .done file in its timer (no main-thread stdout read).
- Verified: warm reuse, dead-man switch (0.1s), idle timeout (~3s w/ idle=3),
  QUIT, live-off stops worker, unregister stops worker, 0 orphan processes,
  0 leftover temp files, manual one-shot still works.

## v0.9 — fix image-texture materials rendering pink
- BUG: materials using external image textures with RELATIVE paths (Blender's
  default, e.g. //tex/wood.jpg) rendered PINK (missing-texture placeholder),
  because the temp job .blend was written to /tmp with path_remap="NONE", so
  the relative path resolved against /tmp instead of the user's project.
- FIX: libraries.write now uses path_remap="ABSOLUTE" -> the job .blend stores
  absolute image paths, so the worker finds the files. No-op for procedural
  materials. Verified: relative-path texture renders correctly (green test
  swatch) in both manual and warm paths; was magenta before.
- Note: pink != dead worker — a missing image renders fine, just placeholder-
  coloured (mix nodes on top still show their effect, which is the tell).

## v0.10 — neutral colour management (no grading on previews)
- BUG: a freshly created job scene defaults to AgX view transform (Blender 4.x),
  so previews were being colour-graded (e.g. pure green rendered as muted
  [0.43,0.77,0.32]).
- FIX: job scene now forces View Transform = Standard, Look = None, Exposure = 0,
  Gamma = 1 -> raw texture/node colours. Verified: green test texture now renders
  [0,1,0] (was [0.43,0.77,0.32]); manual + warm paths.
- Note: user mentioned "Medium Contrast" but that Look ADDS grading; used Look =
  None to actually eliminate grading. Switch to Medium Contrast only if desired.

## v0.11 — always-on guard fixes native save/load of the preview
- PROBLEM (persisted): Save As on the preview stamps the file path onto the
  NodePreview_Result datablock; opening that file then REUSES the preview
  datablock (Blender reuse-by-filepath), so the node collapses back to the
  preview and the image can't be packed. v0.7's in-_store_result safeguard only
  ran on the NEXT render, so save+open-without-render still broke.
- FIX: always-on timer (_guard_preview_datablock, ~1s, persistent) that, the
  moment the preview gains a file path (user saved it), renames it to the file's
  basename -> it becomes a normal, packable, file-backed texture and frees the
  'NodePreview_Result' name for a fresh preview. Verified end-to-end: save ->
  guard releases -> open gives the user's packable texture -> next preview is a
  clean new datablock. Guard unregisters cleanly.
- During normal live preview the datablock is generated/pathless, so the guard
  never touches it.

## v0.12 — replace always-on guard with an explicit Save button
- Per user preference (nervous about a background watcher), REMOVED the
  always-on _guard_preview_datablock timer.
- ADDED "Save Preview to File" button: opens a native file browser, saves the
  preview to the chosen path via a throwaway datablock (so it NEVER stamps a
  path onto the live preview), reloads it as a normal FILE-backed packable
  image, and (optional toggle) adds it as an image-texture node in the active
  material. Because the preview datablock is never given a path, the loaded
  file can't collapse back onto it.
- Kept the lightweight render-time safeguard as a quiet net.
- Verified headless: file written; independent FILE-backed packable datablock;
  preview left generated/pathless (untouched); node added and pointing at it.

## v0.13 — audit pass fixes
- Save button: capture the anchor node BEFORE creating the new node (was
  positioning the new node relative to itself).
- Save button: reload() after load(check_existing=True) so re-saving to the
  same filename shows fresh pixels, not the cached datablock's stale ones.
- Robustness: persistent load_post handler resets to Live-off (clears job,
  stops warm worker, drops timer flag) when a .blend is opened — otherwise a
  file load silently killed the timer while state still said "live on".
- Verified: node placement correct, re-save fresh, load resets cleanly; full
  regression (warm live/manual, save button, multi-object safeguard) green.

## v0.14 — engine dropdown (Cycles / EEVEE)
- Added "Engine" dropdown (Scene prop np_engine) in the side panel: Cycles or
  EEVEE. Default Cycles (safe on CPU/GPU); EEVEE is usually much faster on a GPU
  and needs fewer samples for flat emission.
- Worker _setup_and_render now takes an engine arg: EEVEE -> BLENDER_EEVEE_NEXT
  (fallback BLENDER_EEVEE) with eevee.taa_render_samples; Cycles unchanged.
  Engine passed through both one-shot args and the warm RENDER protocol (now 7
  fields). Device readout shows "EEVEE (GPU)" for EEVEE.
- Verified on 4.4 (no GPU box): both engines render correct identical swatch via
  manual AND warm paths. EEVEE ~6.6s here in software; will be fast on the user's
  GPU. Note: the Auto/GPU/CPU device pref only affects Cycles (EEVEE always GPU).

## v0.15 — EEVEE background crash -> auto-fallback to Cycles
- BUG: EEVEE ("Background render failed (code 11)") — EEVEE needs a GPU context
  that `blender -b` doesn't reliably provide; it crashes (segfault) on real GPU
  drivers even though it limped through in software on the test box (EGL_BAD_MATCH
  warnings). EEVEE-in-background is fundamentally unreliable cross-platform.
- FIX: when an EEVEE job fails (one-shot non-zero exit / warm worker crash /
  no image), auto-switch np_engine to Cycles and retry immediately, with a
  persistent panel notice "EEVEE couldn't render in background — using Cycles."
  Warm path now detects worker DEATH (not just 120s timeout) so fallback is fast.
- The notice clears on the next user-initiated render. EEVEE stays selectable
  for setups/versions where it works; it just can't leave you stuck.
- Immediate user unblock: switch Engine dropdown back to Cycles.
- Verified: EEVEE-fail -> Cycles retry renders; normal Cycles clean; warm live
  reuse intact (0.07s reuse vs 10.7s cold); worker stops on live-off; no leftovers.

## v0.16 — degrade chain + real error surfacing (code 11 on Cycles/OptiX)
- REPORT: WF-1 material crashed the worker with "code 11" on Cycles GPU (OPTIX)
  too, not just EEVEE. Likely an OptiX-specific crash on some node in that
  material (OptiX has feature limits CPU/CUDA don't).
- FIX 1: generalised the fallback into a degrade chain — EEVEE -> Cycles, then
  Cycles-on-GPU -> Cycles-on-CPU. A GPU/OptiX crash now auto-retries on CPU
  (reliable) with a notice. start_job gained mode_override; jobs record engine+mode.
- FIX 2: worker now wraps the render in try/except and writes ERR:<traceback> to
  the status/done file, so Python-level failures show the REAL message instead of
  "code 11". One-shot worker stdout+stderr captured to <temp>/np_last_render.log
  for diagnosing hard (C-level) crashes; failure message points at it.
- Verified: EEVEE->Cycles->CPU chain retries and renders; real ERR surfaced;
  normal renders don't spuriously degrade; warm reuse intact.

## v0.17 — the REAL "code 11" cause: shutdown crash, not the render
- DIAGNOSIS (from user's np_last_render.log on Windows): the render SUCCEEDED
  ("Saved: ...np_out...png"), but Blender then crashed at SHUTDOWN inside an
  unrelated third-party add-on — blender_visual_scripting_addon (Serpens)
  unregister() raised ValueError, then EXCEPTION_ACCESS_VIOLATION. That gave a
  non-zero exit which we wrongly reported as "render failed (code 11)". The
  v0.15/0.16 EEVEE/OptiX-crash theories were WRONG; the material renders fine.
- FIX 1 (critical): one-shot success is judged by PNG existence (+ no ERR
  status), NOT the exit code. A crash after the image is saved no longer counts
  as failure.
- FIX 2: run the worker with --factory-startup and enable Cycles inside it, so
  it does NOT load the user's ~30 add-ons (engon/polygoniq, BlenderKit, Serpens,
  BlenderGIS, ...). Removes the shutdown crash entirely and speeds up worker
  startup. GPU still selected via the worker's own device scan (refresh_devices
  detects hardware regardless of prefs).
- Verified: PNG-with-nonzero-exit accepted as success; isolated worker renders
  one-shot (2.1s) + warm (0.06s reuse); factory-startup + enable cycles works.
- Caveats: if a material uses a shader-node TYPE defined by an add-on (rare),
  --factory-startup won't have it (standard nodes + groups + images are fine);
  if GPU isn't detected under factory-startup it falls back to CPU.
