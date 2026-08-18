# blend-merge-analyzer — design & spec

A standalone desktop app (sibling of `blend-compat-scanner`) that reads the object
names out of a heavy Revit-exported `.blend`, discovers naming patterns on its own,
lets the user build grouping lists interactively, and — on Execute — hands a merge
plan to headless Blender to collapse each group into a single object.

Status: **design locked, not yet built.** This doc is the reference we point back to.

---

## Problem

Revit → Blender exports arrive with hundreds of thousands of objects. In the test
file: **52,361 meshes** (plus 467 empties = Revit assembly parents, 2 curves, 1
camera). The viewport chokes. The user currently cleans up by hand: search a name
fragment, select the matches, collapse instances, join. Goal: an app that proposes
the groupings so the join step is fast and safe — **the app never merges on its own;
every merge is a manual per-list button.**

### What the names look like

`Basic Wall INT_WD-AW16 [5114268]_[5768506].003`

- Human/category + spec codes: `Basic Wall INT_WD-AW16`
- Revit element IDs: `[5114268]`, `_[5768506]`  ← noise for grouping
- Blender collision suffix `.003`, 7-char hex hash on truncated long names,
  trailing ` Geometry` on datablocks  ← noise for grouping

### Instancing reality (important)

`instance_type` is `NONE` for every object — there are **no Blender
instance-collections**. The "instancing" is **linked mesh datablocks**: many objects
share one `mesh` via `data`. 35,152 objects share just 1,115 unique meshes; one mesh
is used by **9,007 objects** (patio railing). So "collapse instances" mechanically =
**make-single-user, then join**.

### Materials

Only 88 objects carry a material here, so materials are effectively a non-issue in
this file. Design still assumes join preserves per-object materials — which Blender's
join does natively (unions slot lists, keeps per-face assignment). No special
handling needed.

---

## Data findings (from the 52,361-object test file)

- Stripping **only** the noise (IDs / `.NNN` / hex / ` Geometry`) collapses
  52,361 objects → **719 unique keys**. This is the always-safe "increment/ID" layer.
- **Skeleton grouping** (replace every number run with `#`) folds those 719 keys into
  374 families; 68 families hold real variants to review, e.g.
  `Basic Wall INT_WD-AW#` → AW16 (1604), AW17 (623), AW20 (376), AW56 (200).
  This is the "16-inch vs 17-inch" case — proposed, never auto-merged.
- **Facet codes** are real design-sheet disciplines and make clean filters:
  `CW_` casework (9082), `INT_` interior wall (7486), `SE_` bath accessories (3960),
  `EXT_` (3045), `LEAF_` (2861), `UNITS_` (2653), `GEN_`, `PF_`, `WN_`, `LF_`, `ME_`,
  `COL_`, `DR_`, `VP_`/`HP_` …
- **Sticky-compound detection works.** A Mikolov-style phrase score over adjacent
  tokens auto-promotes genuine compounds (`WD-AW16`, `Vinyl Plank`, `Standing Seam`,
  `Fire Extinguisher`, `(PT-01)`) without hardcoding. Confirmed the user's intuition:
  `WD` appears ~13,500× and is followed by another token ~11,100× (AW16, F1, DW10,
  2X6, GW31, AW17). Needs a min-count threshold + tighter upstream noise-strip to
  keep junk out of the top results — tuning, not structural.

---

## Locked interaction design

1. **No auto-grouping on open.** The app opens to a **word cloud**.
2. **Word cloud** = single tokens **and** statistically-sticky compounds (learned from
   the data, e.g. `WD-AW16`), sized by frequency, all clickable. Plus a
   **type-your-own** box for terms the cloud split or hid.
3. **Dynamic Venn lists.** Selecting terms builds lists by region: each term's full
   list, **plus** a combined list for any real overlap. Number of lists flexes with
   the selection. An object with both `concrete` and `PT01` appears in the `concrete`
   list, the `PT01` list, **and** the combined list (user's explicit choice — single
   lists are full sets; overlaps are extra lists on top). The combined list existing
   is what lets the user pick the finer grain before merging.
   - **Claiming.** When a group is merged or deleted, its objects leave the pool. Every
     list recomputes against what remains, so a later group can never re-include
     already-claimed objects — this is what prevents the "merge Patio Railing, then
     merge Railing" double-claim. No separate conflict section is needed.
   - **Grey-out.** A cloud chip greys out only when **zero** of its objects remain in
     the pool (all claimed). If some remain it stays live with a reduced count — so
     merging broad `Railing` greys narrow `Patio Railing` (fully claimed), while
     merging narrow `Patio Railing` only shrinks `Railing`'s count. Greyed chips are
     not deleted; the user can still remove them manually.
   - **Union card.** Whenever 2+ terms are selected, the grouping list also shows an
     **"All selected"** card: the de-duplicated union of every object matched by any
     selected chip, regardless of shared wording. It carries its own Merge and Delete
     buttons, so terms that never co-occur in a name (e.g. `hand` + `railing`) can still
     be merged or deleted together. Objects matching several selected terms count once;
     the card respects claiming like any other.
   - The **∩ overlap card** remains the pre-merge decision surface: two still-live terms
     that share objects show a combined card so the user chooses which bucket the shared
     objects go to; once one side is merged, the shared objects leave and the overlap
     dissolves.
4. **Ignore box** — visible, editable, wildcard-capable, pre-filled with the default
   junk-strip patterns (`[digits]`, `.NNN`, hex hash, ` Geometry`). The user can see
   and change every rule; nothing is stripped invisibly.
5. **Splitter/facet section** — auto-found codes shown as chips **plus** user-added
   hard-splitters (e.g. `PT##`). A hard-splitter means the tool refuses to merge two
   objects that differ on that token.
6. **Per-list Merge button** — manual, always. On click: make-single-user on the
   selection, then join; merged objects leave the pool and everything re-counts.
7. **Leftover bucket** — the ~235 true one-offs (a name appearing on exactly one
   object) surface here. A singleton can't be *merged* (nothing to join it to), but it
   can still be **deleted**, and the bucket supports multi-select delete. "No safe
   merge" applies only to count = 1 — it is never a reason a real group is blocked.
8. **Merge eligibility** — any group resolving to 2+ objects always gets live Merge and
   Delete buttons. A group does **not** need to share wording with any other group;
   e.g. `Fire Extinguisher` → 40 objects is a normal, fully mergeable list. Only
   count = 1 disables Merge (Delete still allowed).
8. **Execute** — hands the accumulated plan to headless Blender, saves a *new* result
   file (original untouched), then opens that result in Blender for inspection.
   - **Save as copy is ON by default** and writes a new `.blend`; the original is
     never modified. An "overwrite original in place" toggle exists but is OFF by
     default and, being destructive, must confirm before it will overwrite.
   - Plan has two operation types: **merge** (make-single-user + join → 1 object) and
     **delete** (remove objects entirely). Execute reports the delete count separately
     and confirms it before running, since a wrong delete is worse than a wrong merge.

### Cloud refresh

As merges and deletes claim objects, the pool shrinks and the initial cloud (ranked
on the full 52k) goes stale. A **Refresh** control rebuilds the cloud from only the
objects still in the pool: chip frequencies re-rank, fully-claimed terms drop out, and
terms too rare to surface at the start can now appear — letting the user work down
through the remaining "untouched" objects until the file is clean. Refresh re-runs
facet detection and sticky-compound analysis on the remaining names; hand-added custom
chips are preserved if they still have objects, and current selection is kept where
its terms still resolve. The Refresh button shows a subtle "stale" state once anything
is queued, signalling when a rebuild is worthwhile.

### Undo / un-queue

Nothing is permanent until Execute, so the plan is fully reversible. In the **Results**
tab each queued group (merge or delete) carries an ✕ that **un-queues** it: the
operation comes off the plan, its objects return to the pool, and the word cloud
updates live — a chip that had greyed out on full claim becomes active again and its
count restores. No geometry is touched; it's a pure reversal of the queue. Un-queue
lives only in Results (the cloud-tab card already shows a greyed "queued" state with
its objects out of the pool), making Results the single place to review and edit the
plan.

### Merge vs delete (UI)

Each grouping list carries two manual buttons: **Merge** (amber — collapses the
group to one object) and **Delete** (red — removes the group's objects). They are
visually distinct because they are different kinds of destructive action. Nothing
runs until Execute.

### Drill-in sub-cloud

Clicking any cloud chip (a) toggles its list and (b) opens a scoped sub-cloud of the
tokens that co-occur with that term (computed live from the matching groups, the
selected term's own tokens removed). Clicking a sub-cloud chip behaves exactly like
clicking a main-cloud chip; if that token isn't already in the main cloud it is
promoted there so it's findable later. Chips can be removed (✕) or added (+ / type
box). This replaces the earlier "click a more specific chip" narrowing model.

---

## Performance — why the merge runs in a fresh file

Blender's `join()` and `make_single_user` scale with **total objects in memory**, not
just the selection — so merging inside a 52k-object file is punishingly slow even
headless (the source file's own bloat, not the operation). Benchmarked on a 50k
synthetic scene, Blender 4.4.3:

| approach | merge 2,000 objects |
| --- | --- |
| in-place, inside the 50k file (operator) | **75 s** |
| in-place, data-level bmesh | 37 s |
| in a fresh file containing only those objects | **1.3 s** (~56× faster) |

So the engine **never merges inside the big file**. It builds the result in a fresh
empty file, and for each merge group it appends only that group's objects and joins
them while the scene is still small. Per-group file reopen costs ~0.15 s (negligible);
the only real cost is loading each group's geometry once. Deletes are simply never
appended. Untouched objects are bulk-appended at the end (no joins) if a full-model
result is requested.

End-to-end on the 50k scene (merge 16,541 → 3 groups, delete 732): merge phase **57 s**;
full-model rebuild (appending 32,727 untouched) ~130 s more. When most of the file is
merged (the usual endgame), "untouched" is small and total time collapses toward the
merge phase alone.

**Result-contents toggle:** *full model* (merged + untouched, the safe default) or
*merged only* (skips the untouched bulk-append — much faster when the user just wants
the cleaned geometry). Original is never modified unless overwrite is chosen; overwrite
writes to a temp file and moves it over the original only after a successful build.

## Delivery & packaging

Single-entry requirement: the user touches exactly one thing. Two deliverables:

- **`.exe`** — one self-contained Windows executable built by **GitHub Actions**
  (PyInstaller, mirroring the existing `relay.spec`). Double-click, no Python install.
- **Zip + one-click launcher** — for immediate use without a build wait: unzip and
  double-click a single launcher (`.bat`/`.command`) that opens the app window.

Internally the app is still multiple small files (a browser-sandboxed `.html` cannot
launch Blender or read disk, so it can't be the clickable entry). The entire UI is one
self-contained HTML file; the Python backend sits alongside it. Blender scripts that
run inside Blender are **embedded as string constants in the engine and written to a
temp file at runtime**, so the "inside-Blender" logic doesn't add loose files.

## Execution model

- **Blender discovery** — auto-detect installed Blenders (reuse
  `blender_manage.discover`); the UI shows a **version dropdown** so the user picks
  which build runs. Missing builds can be fetched as portable downloads.
- **Two execute buttons:** **Execute** (runs headless/silent, saves the copy) and
  **Execute & open** (runs, then opens the result in Blender's GUI for inspection).
- Save-as-copy remains ON by default for both; original never modified unless the user
  explicitly toggles overwrite (which confirms first).

## Architecture (mirrors blend-compat-scanner)

```
apps/blend-merge-analyzer/
  backend/
    relay_app.py        # pywebview shell: local http server + native window + file picker
                        #   (lift the pattern from blend-compat-scanner/backend/relay_app.py)
    server.py           # serves ui/ and the JSON API
    engine.py           # orchestration, NO bpy. header-detect + headless Blender subprocesses
    blender_manage.py   # REUSE from blend-compat-scanner: discover/download Blender builds
    dump_names.py       # runs INSIDE Blender (-b --python): object names+meta -> names.json
    merge_plan.py       # runs INSIDE Blender: reads plan.json, make_single_user + join per group,
                        #   saves result.blend
    analyze.py          # pure Python: tokenize, noise-strip, collocation, facet detect, Venn lists
    requirements.txt    # pywebview, zstandard
  ui/
    merge-ui.html       # word cloud, ignore box, splitters, dynamic lists, per-list Merge, Execute
  README.md
  DESIGN.md             # this file
```

### Flow

1. User drops/pick a `.blend`. `engine.detect_version()` reads the header (handles
   gzip/zstd) → resolves a matching Blender via `blender_manage` (downloads a portable
   build if absent).
2. `engine` runs `blender -b file.blend --python dump_names.py -- --out names.json`
   (headless, data-only, fast). Result cached.
3. All interactive analysis (`analyze.py` + UI) runs on the cached JSON — instant, no
   Blender. Word cloud, ignore rules, splitters, Venn lists, per-list previews.
4. Each **Merge** appends a group (its resolved object-name set) to the in-app plan.
5. **Execute**: `engine` copies the original to a work dir, runs
   `blender -b copy.blend --python merge_plan.py -- --plan plan.json --out result.blend`,
   then launches `blender result.blend` (GUI) for inspection. Original never written.

### Why headless works for the merge

`make_single_user` and `join` are ordinary Blender operators; run under
`blender -b … --python …` they need no window. Opening the GUI is only for the final
human inspection step, by choice.

---

## Open tuning knobs (not blockers)

- Collocation min-count + phrase-score delta (keep junk compounds out of the cloud).
- Default cloud ordering / how many chips to show before "more".
- Merge chunking for very large groups (e.g. the 9,007-object railing) to stay within
  Blender operator limits — join in batches if needed.

## Explicitly rejected / decided

- Not a Blender addon — a standalone app (drag a `.blend` in).
- No AND-only faceting — Venn regions, with full single-term lists kept.
- No auto-merge, ever.
- No material special-casing — native join behavior is correct here.
