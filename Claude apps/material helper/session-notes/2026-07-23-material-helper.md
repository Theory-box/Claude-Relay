# Material Helper — Session Notes

**Status:** spec only. No code written. Paused at user's request 2026-07-23.
**Target:** Blender 4.4 add-on.
**Branch:** `feature/material-helper`

Idea capture from a brainstorm session. Nothing here is settled; the user expects to add more
features before implementation starts.

---

## Concept

A material management panel — a list of the materials in the file, with tools for the
housekeeping problems that pile up in a real scene: junk auto-names, accidental duplicates,
and materials that should have been one material all along.

Proposed location: Material Properties tab. Not confirmed — Sidebar (N-panel) or a dedicated
editor are also plausible and no decision was made.

---

## Features requested

### 1. Material list
Enumerate materials in a `UIList`. Baseline feature everything else hangs off.

### 2. Default-name filter
Hide materials still carrying Blender's auto-generated name (`Material`, `Material.001`,
`Material.002`, …) so the list shows only deliberately named ones. A toggle; user leaned
toward it being on by default.

### 3. Duplicate collapsing
Materials that differ only by Blender's `.###` duplication suffix (`Floor`, `Floor.001`,
`Floor.002`) collapse into a single row with a disclosure triangle. Expanding reveals the
members.

**Explicitly not fuzzy matching.** The user floated `Floor_Gray` / `Floor_Black` as an example
and then corrected themselves — semantically related names with different base names stay
separate. Only the numeric-suffix case groups.

Motivating scenario: 20 materials in a scene, 5 of them suffix-duplicates of others, so the
list should read as ~15 rows rather than 20.

### 4. Drag and drop
Drag a material from the list onto an object in the viewport to assign it.

### 5. Rename in place
Edit names directly in the list.

### 6. Multi-select and remap
Select several materials, press Remap, pick a target material, and every user of the selected
materials across the whole file repoints to the target. Then optionally delete the sources,
which are now unused.

Motivating scenario: 20 materials, 10 are duplicates, user wants them unified to one.

---

## Technical notes

Assessed during the session, not verified against the 4.4 API. Confidence values are estimates
and should be re-checked before anyone builds on them.

### Remap — easy
`Material.user_remap(target)` already does exactly what feature 6 describes: file-wide, all
users, one call. Purging afterward is a zero-user cleanup. Watch for materials carrying a fake
user, which will not report as unused. **Confidence ~0.95.**

### Collapsible tree — fakeable
`UIList` is flat and has no native tree. Workable approach: build the displayed item list
dynamically so child rows only exist while the parent is expanded, drawing indentation and a
disclosure triangle per row. **Confidence ~0.9.**

### Multi-select — fakeable
No native multi-select in `UIList`. Standard workaround is a per-item boolean drawn as a
checkbox in each row. **Confidence ~0.9.**

### Drag and drop — probably blocked
Blender's Python API does not appear to expose custom drag-source / drop-target handling for
`UIList` items. The drag-and-drop in the Outliner and Asset Browser is implemented in C. A pure
Python add-on likely cannot do list → viewport dragging. **Confidence ~0.8 that this is off the
table** — verify against the 4.4 API before committing.

Fallback options if confirmed blocked:
- An "Assign to Selected" button.
- A modal operator: press a button, then click an object in the viewport to receive the material.

---

## Open questions

Raised, not answered. Worth resolving before implementation.

1. **List scope.** The user said "all the materials in the scene" for the list but "the whole
   blender file" for remap. These differ — a `.blend` can hold materials on objects in other
   scenes, on unlinked objects, or with zero users. Is the list file-wide, scene-wide, or is
   scope itself a toggle?

2. **Default-name detection strictness.** Strictly `Material[.###]`, or should it also catch
   import junk like `lambert1`, `Material_001` (underscore, no dot), `defaultMat`?

3. **Linked / library materials.** Read-only when linked from another `.blend`. Excluded from
   the list, or shown greyed out?

---

## Possible direction (unprompted, not requested)

Noted here only so it is not lost. A later session explored normalized compression distance as
a similarity measure. It could in principle find materials that are *functionally* identical but
named differently — something name-based duplicate detection (feature 3) cannot catch by
construction. Speculative, unvalidated, and outside the current scope.

---

## Next session

Pick up by re-reading this file. The user intends to add more features before any code is
written, so start by asking what else they thought of rather than assuming this list is final.
