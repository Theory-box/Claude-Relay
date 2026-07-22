# Community Feedback Doc — Maintenance Notes

## Current state
- **Path:** `community-feedback/Community Feedback.md`
- **Scope:** community-reported observations about the addon, organized by feature area.
- **Branch:** main (commits go directly — this doc isn't under any feature branch).

## Structure
H2 sections in order:
1. Macros & Level Info
2. Level UI / Settings
3. Platforms
4. Pickups / Collectables
5. Checkpoints
6. Baking & Lighting
7. Bugs & Misc
8. Feature Questions & Analysis (deep-dive Q&A format, merged from the former `feature-community-questions.md`)

Sections 1–7 are short observational bullets / tables. Section 8 is longer analytical Q&A with Options A/B/C, code snippets, etc. — different flavor, deliberately kept as-is.

## Conventions
- **No dates in the doc title or filename** — it's a single evolving doc, not per-session.
- New items: propose placement + wording in chat before editing. Don't silently add.
- GOAL-specific values (e.g. `'*village1-mood*`) keep their leading apostrophe in tables.
- Cross-references between sections use anchor links (e.g. `[Level Settings Tab](#level-settings-tab)`).
- Preserve original qualifications from feedback verbatim ("needs retesting," "not sure if already fixed," opinions, etc.) — don't flatten them out.

## Related docs (NOT merged — keep separate)
- `docs/known-issues.md` — internal dev tracker (code actions, regression checklist, panels.py size). Audience is different; leave alone.
- `docs/entity-spawning.md` §17 — live enemy compatibility matrix.
- `scratch/unsupported-actors-draft.md` — actors not yet in ENTITY_DEFS.

User considered merging known-issues in during the April 19 session and decided against it — it's internal tracking, not community feedback.

## Last session
**April 19, 2026** — merged `feature-community-questions.md` into this doc; renamed from `Community Feedback - April 17th 2026.md`; added 10 feedback items.
