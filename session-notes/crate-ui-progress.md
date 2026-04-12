# Crate UI — Session Notes

**Branch:** `feature/crate-ui`
**Status:** Implementation complete, syntax verified, pushed. Needs Blender install test.
**Last updated:** 2026-04-12

---

## What Was Built

### Research (session 1)
- Sparse-cloned jak-project, read `crates.gc` and `fact-h.gc` in full
- Confirmed all engine pickup types: none/eco-yellow/eco-red/eco-blue/eco-green/money/fuel-cell/eco-pill/buzzer/eco-pill-random
- Confirmed `eco-info` lump format: `["eco-info", "(pickup-type X)", amount_int]`
- Confirmed scout fly edge case: engine auto-upgrades wood→iron in `params-init` when `pickup-type=buzzer`

### Implementation (session 2)
All changes on `feature/crate-ui` branch.

**Files changed:**
| File | What changed |
|---|---|
| `data.py` | `CRATE_ITEMS` fixed (6 types: steel/wood/iron/darkeco/barrel/bucket), `CRATE_PICKUP_ITEMS` added |
| `operators.py` | `SetCrateType` updated (wood→iron guard), `SetCratePickup` + `SetCrateAmount` added, spawn defaults |
| `export.py` | Hardcoded `eco-info` replaced with dynamic lookup from `og_crate_pickup`/`og_crate_pickup_amount` |
| `panels.py` | `OG_PT_ActorCrate` fully rewritten; selected-object summary updated |
| `__init__.py` | New operators imported and registered |

---

## Custom Properties on Crate Objects

| Property | Type | Default | Notes |
|---|---|---|---|
| `og_crate_type` | string | `"steel"` | Visual + defense: steel/wood/iron/darkeco/barrel/bucket |
| `og_crate_pickup` | string | `"money"` | What drops: none/money/eco-yellow/eco-red/eco-blue/eco-green/buzzer |
| `og_crate_pickup_amount` | int | `1` | How many (1–5); locked to 1 for buzzer |

---

## Scout Fly Edge Case

Engine rule from `crates.gc params-init`:
```lisp
(case (-> this fact pickup-type)
  (((pickup-type buzzer))
   (set! (-> this type) crate-buzzer)
   (when (= (-> this look) 'wood)
     (set! (-> this look) 'iron)
     (set! (-> this defense) 'iron))))
```

Addon mirrors this:
- `SetCratePickup(buzzer)` → if crate_type is wood, auto-sets to iron + warning
- `SetCrateType(wood)` → if pickup is buzzer, stays iron instead + warning
- Wood button greyed out in UI when pickup=buzzer
- Red alert box shown if somehow state is wood+buzzer

Steel + scout fly is valid (engine doesn't prevent it).
Dark eco + scout fly is technically valid but unusual — no UI restriction.

---

## Export Output Examples

```json
// Wood crate, 3 orbs
{ "crate-type": "'wood", "eco-info": ["eco-info", "(pickup-type money)", 3] }

// Iron crate, scout fly
{ "crate-type": "'iron", "eco-info": ["eco-info", "(pickup-type buzzer)", 1] }

// Steel crate, empty (no eco-info emitted)
{ "crate-type": "'steel" }

// Darkeco crate, blue eco
{ "crate-type": "'darkeco", "eco-info": ["eco-info", "(pickup-type eco-blue)", 1] }
```

---

## Known Limitations

- **fuel-cell** not supported as crate pickup — needs `task` lump + game-task assignment (separate feature)
- **eco-pill / eco-pill-random** not exposed — engine uses these as fallback defaults, not intended for manual crate use
- Amount stepper only exposed for `money` (orbs) — all eco types default to 1 (sensible, matches base game)
- Old `.blend` files with crates won't have `og_crate_pickup` → export falls back to `"money"` default gracefully

---

## Session Log
- 2026-04-12 (Session 1): Branch created. Research complete (crates.gc, fact-h.gc). Partial impl (data, operators, __init__).
- 2026-04-12 (Session 2): Implementation complete. Export + panel finished. Syntax verified. Pushed.
