# Community — Questions, Statements & Feature Requests

> Running log. Add anything raised by community members that's worth tracking.
> For researched answers, link to the relevant knowledge doc rather than duplicating here.

---

## Feature Requests

- **Multiple levels per blend file** — user working on TFL wanted all levels visible simultaneously in different collections with per-collection export settings. → See `lump-system.md` for architecture research (collection approach).
- **Non-exported collections** — reference models, connection to existing levels, backup objects. Free with collection-scoped export system.
- **Spawn at build time** — dropdown to choose which continue point to spawn at when hitting Build & Play, for fast iteration.
- **Load boundaries** — LOADBOUNDARY_ empty with fwd/bwd flags, player flag, closed flag, near/far continue point pickers (custom + vanilla list).
- **Change continue point** — reminder or auto-patch for `mod-settings.gc` spawn when using mod-base.

## Questions (Answered)

- **Custom actor types & custom lumps** — answered, see `lump-system.md`. `og_lump_*` passthrough is the solution, `og_custom_type` for actor type.
- **One level per blend file?** — yes currently. Collection approach researched, see `lump-system.md`.
- **Full JSON regeneration?** — yes, manual edits are wiped. Long-term fix is JSON passthrough block, short-term is exposing more fields in UI.
- **mod-settings.gc spawn checkpoint** — when using mod-base, need to update `mod-settings.gc` manually or auto-patch. nREPL flow bypasses this for iteration.

## Statements / Tips

- Time of day change only needs color attributes in Blender (all `_NAME` prefixed), just bake to each one. Actors handled separately via `mood-tables.gc`. → See `time-of-day-mood.md`.
- `mod-settings.gc` spawn checkpoint should be changed when using mod-base.

