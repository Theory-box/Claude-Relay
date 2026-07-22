# Lump Panel — Design Discussion
_April 2026 — Research findings + design constraints_

---

## What Blender Actually Supports in N-Panels

**No native multiline text box.** `layout.prop()` on a `StringProperty` gives one single-line
text field. There is no embeddable textarea or code editor widget in the sidebar.

**What IS available:**
- Single-line `StringProperty` fields (text inputs)
- `EnumProperty` dropdowns
- `IntProperty` / `FloatProperty` number fields
- `UIList` + `template_list()` — a scrollable list of rows, each row can contain
  any combination of fields. This is what vertex groups, shape keys, and modifier
  lists use. It's the only "multi-row editable list" widget in Blender.
- `CollectionProperty` — the data backing a UIList (already used in this addon
  for `og_vol_links` on volume meshes — see OGVolLink)

**Conclusion:** The UIList / CollectionProperty pattern is the right approach for
assisted lump rows. We already have one working example in the addon to follow.

---

## Lump Key Ordering — Does It Matter?

**Short answer: No, and yes.**

The C++ level builder (`ResLump.cpp`) runs a `stable_sort` on all tags by the
first 8 bytes of the key name before writing the binary lump. This is a binary
search optimisation in the engine runtime. **The JSONC order the addon emits
does not matter** — the builder reorders everything.

**BUT: duplicate keys are a problem.**

If the same key name appears twice in the lump dict, both tags get written with
different offsets pointing to different data. The engine's `lookup_tag_idx` does
a binary search then returns the first match in the sorted array. Which entry
"wins" is effectively undefined (depends on stable_sort tie-breaking). This is
a silent data corruption bug — no crash, wrong value used.

**Design rule:** The addon must deduplicate keys before writing JSONC. If a key
appears in both panels, one panel must win. See "Priority Rule" below.

---

## Two-Panel Architecture

### Panel 1 — Manual (Passthrough)

**What it is:** User adds custom properties on the actor empty, prefixed `og_lump_`.
The addon reads these at export time and injects them into the lump dict.

Example: user adds `og_lump_notice-dist` = `50.0` → emitted as `"notice-dist": 50.0`

**Storage:** Blender custom properties on the Object (always available, no registration needed).

**UI in the panel:** Show a list of the current `og_lump_*` props. Each row shows
the key (name minus prefix) and the raw value. Read-only display — user edits
via Blender's built-in Object Properties > Custom Properties panel.

Optionally: a small "Go to Custom Properties" button that opens the Properties
panel. Blender can't auto-scroll to custom props but a tooltip note works.

**Value format:** Whatever the user types is passed through as-is.
- If it starts with `[` → treated as a JSON array (parsed)
- If it's a number → emitted as a number
- If it starts with `'` → bare symbol
- Otherwise → bare string
The passthrough is intentionally dumb — power users are expected to know the format.

**Pros:** Zero UI work. Maximally flexible. Already possible right now.
**Cons:** No discoverability. User must know key names and type formats. Error-prone.

---

### Panel 2 — Assisted (Freeform Rows)

**What it is:** A UIList where each row is a `[key] [type▾] [value]` triplet.
User adds rows, picks a type from the 18-item dropdown, types a key name and value.
Stored as a `CollectionProperty` on the Object (`og_lump_rows`).

Each row has:
- `key`: StringProperty — the lump key name (e.g. `notice-dist`)
- `ltype`: EnumProperty — one of the 18 valid type strings
- `value`: StringProperty — the value, interpreted by ltype at export

On export: each row is converted to a properly-typed lump entry.

**Type → value parsing examples:**
| Type | User types | Emitted |
|---|---|---|
| `meters` | `50` | `["meters", 50.0]` |
| `float` | `4.0 0.0 0.15 0.15` | `["float", 4.0, 0.0, 0.15, 0.15]` |
| `int32` | `3` | `["int32", 3]` |
| `symbol` | `thunder` | `["symbol", "thunder"]` |
| `vector3m` | `1.5 2.0 -3.0` | `["vector3m", [1.5, 2.0, -3.0]]` |
| `enum-uint32` | `(game-task none)` | `["enum-uint32", "(game-task none)"]` |

Space-separated numbers for multi-value types. Simple to parse.

**Pros:** Guided. Shows all 18 types. Key names are explicit. Stored cleanly.
**Cons:** More code. Still needs user to know key names. Value parsing can fail.

---

## Priority Rule (Deduplication)

When both panels have an entry for the same key:

**Assisted rows take priority over passthrough props.**

Reason: assisted rows are an explicit, intentional choice with a type. The
passthrough is the "raw escape hatch" — if a user has both, they probably
migrated from passthrough and forgot to remove the custom prop.

At export, the merge order:
1. Start with hardcoded lump values (name, eco-info, path, sync, etc.)
2. Merge passthrough props (`og_lump_*`) — overwrite hardcoded if key matches
3. Merge assisted rows — overwrite anything above if key matches

Wait — this means assisted rows could silently overwrite `name` or `path` if
someone is careless. Better approach:

**Protected keys** — a set of keys the hardcoded system always owns:
`name`, `path`, `pathb`, `sync`, `options`, `eco-info`, `nav-mesh-sphere`,
`idle-distance`, `vis-dist`, `notice-dist`

If a user tries to set a protected key via either panel, show a warning in the
panel and skip it at export (or override, with a loud log warning).

Actually — simpler: **let them override, but log a warning.**
The hardcoded values are defaults. Power users may want to override `vis-dist`
or `idle-distance` without using the dedicated UI. Don't block it.

Merge order:
1. Hardcoded (lowest priority)
2. Passthrough `og_lump_*` props
3. Assisted rows (highest priority)
4. Log a warning if any key appears in more than one source

---

## Sub-Panel Structure Proposal

```
┌──────────────────────────────────────────────┐
│  🔍 Selected Object                          │
│  [existing actor UI: idle-dist, navmesh etc] │
│                                              │
│  ▼ Custom Lumps                              │  ← new sub-panel, DEFAULT_CLOSED
│  ┌────────────────────────────────────────┐  │
│  │ Assisted                               │  │
│  │ ┌──────────┬──────────┬──────────────┐ │  │
│  │ │ Key      │ Type     │ Value        │ │  │
│  │ ├──────────┼──────────┼──────────────┤ │  │
│  │ │notice-   │ meters ▾ │ 50           │ │  │
│  │ │dist      │          │              │ │  │
│  │ ├──────────┼──────────┼──────────────┤ │  │
│  │ │mode      │ int32  ▾ │ 1            │ │  │
│  │ └──────────┴──────────┴──────────────┘ │  │
│  │  [+ Add Row]              [− Remove]   │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Manual (og_lump_* custom props)             │
│  og_lump_notice-dist  →  50.0               │
│  og_lump_mode         →  1                  │
│  ℹ Edit in: Object Props > Custom Props      │
│                                              │
│  ⚠ Conflict: 'notice-dist' in both panels   │
│    Assisted rows take priority               │
└──────────────────────────────────────────────┘
```

This is a `bl_parent_id = "OG_PT_selected_object"` sub-panel with
`bl_options = {"DEFAULT_CLOSED"}` — same pattern as Collision, Light Baking, NavMesh.

The poll function: only show when selected object is an `ACTOR_` empty.

---

## What We Still Need To Decide

1. **Value input format for multi-value types** — space-separated? comma-separated?
   Leaning toward space-separated (simpler to type, consistent with GOAL source style).

2. **Error handling for bad values** — silently skip? export warning? red text in UI?
   Leaning toward: show a red "!" icon on the row, log warning at export, skip that key.

3. **Should passthrough show editable fields or read-only display?**
   - Read-only is simpler (user goes to Custom Props to edit)
   - Editable would mean the panel IS the custom props UI, less context switching
   - Could do: read-only display + "Edit Custom Properties" button

4. **Do we need a UIList for assisted rows, or just stacked box rows?**
   UIList supports scroll + active index (needed for delete). Stacked rows are simpler
   but won't scroll if there are many. UIList is the right call for >3 rows.

5. **Phase 1 scope** — build just passthrough display + export wiring first?
   Or build both panels at once? Passthrough is much simpler to ship first.
