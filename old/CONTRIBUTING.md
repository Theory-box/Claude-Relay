# Contributing to Claude-Relay / OpenGOAL Addon

This file defines the contracts that all contributors (human and AI) must follow
when working on the OpenGOAL Blender addon (`addons/opengoal_tools/`).

**If you are an AI starting a session on this repo: read this file before writing any code.**

---

## Branch Rules

| Branch | Rule |
|---|---|
| `main` | Never commit directly. Only merged from feature branches with explicit user permission. |
| `feature/*` | Working branches. `addons/opengoal_tools/` is the working file. Edit freely. |
| `knowledge-base/` | **Protected on all branches.** Propose changes in chat first. Always lives on main. |
| `session-notes/` | Free to update. Stays on its feature branch, never pushed to main. |
| `scratch/` | Throwaway/WIP. Free to use. |

---

## Audit Contract — MANDATORY

The addon has a Level Audit system in `addons/opengoal_tools/audit.py`.

**Every session that adds a new actor type, property requirement, or structural
dependency MUST update the audit system in the same commit. This is not optional.**

### New actor type → populate ENTITY_DEFS audit block

Every entry in `ENTITY_DEFS` must include an `"audit"` key:

```python
"my-actor": {
    "label": "...", "cat": "...", ...,
    "audit": {
        "requires_navmesh": False,   # True if this is a nav-enemy (nav_safe=False)
        "requires_path":    False,   # True if needs_path=True
        "requires_pathb":   False,   # True if needs_pathb=True
        "required_links":   [],      # lump_key strings that must be set (from ACTOR_LINK_DEFS)
        "custom_checks":    [],      # callables: (scene, obj) → (severity, msg) | None
    }
}
```

The audit reads this block automatically — no changes to `audit.py` needed for
standard cases. Fill it in correctly and the audit gains coverage for free.

### New structural dependency → register an audit rule

If a new feature introduces something that ENTITY_DEFS can't express (new object
prefix, new scene-level invariant, new inter-object relationship), register a
check alongside the feature code:

```python
# In the same file as the feature, or in audit.py for now
from .audit_registry import register_rule

@register_rule(description="brief description of what this checks")
def check_my_feature(scene, obj):
    if <condition indicating a problem>:
        return "ERROR", f"Human-readable description of the issue."
    return None
```

`run_audit()` calls all registered rules automatically.

### The audit block is part of the feature

Write it in the **same commit** as the feature. Do not defer it.
If uncertain what the audit block should contain, ask the user before proceeding.

---

## What the Audit Currently Covers (auto-detected from existing data)

| Check | Source |
|---|---|
| Nav-enemy has no navmesh link | `NAV_UNSAFE_TYPES` (nav_safe=False in ENTITY_DEFS) |
| Actor missing required path waypoints | `needs_path` / `needs_pathb` in ENTITY_DEFS |
| Required actor link slots unset | `ACTOR_LINK_DEFS` required slots |
| Broken actor link targets | `og_actor_links` CollectionProperty |
| Trigger volume with no links | `og_vol_links` CollectionProperty |
| Broken volume link targets | `og_vol_links` CollectionProperty |
| Missing / multiple spawn points | `SPAWN_` prefix |
| Duplicate ACTOR_ names | Object name scan |
| Tpage budget exceeded (>2 non-global groups) | `tpage_group` in ENTITY_DEFS |
| Scene summary (actor counts, group breakdown) | ENTITY_DEFS categories |

---

## Session Start Checklist (for AI sessions)

1. Read `CLAUDE-SKILLS.md` — techniques, storage rules, branch workflow
2. Read the relevant `session-notes/` file — current branch, what was done, next steps
3. `git checkout feature/X && git pull && git merge main`
4. Read this file — audit contract
5. Do the work
6. If new actors/properties/dependencies were added → update the audit (same commit)
7. Update `session-notes/` with what was done and what's next
8. Push to feature branch — **never to main without explicit user permission**
