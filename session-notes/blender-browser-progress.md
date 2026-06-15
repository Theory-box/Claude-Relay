# Blender Browser — Progress Notes

**Branch:** `research/blender-browser`
**Topic:** Embedding a fully interactive web browser inside Blender as an add-on.

## Current state (session 1)
- Explored 3 architectures. **Chose Option 3:** bundled helper process + raw
  shared-memory frame transport + small control socket. Engine = CEF off-screen.
- Rationale: self-contained, full fidelity, no compressed streaming, and decoupled
  from Blender's Python version (helper has its own runtime) — important because
  Blender 4.4=Py3.11 but 5.1=Py3.13.
- Wrote full design doc: `docs/blender-browser/architecture.md`.
- Doc includes open design decisions (§9), a phased plan (§10, Phase 1 spike is the
  gate), and a question set for a collaborating AI instance (§11).

## Decision state
- LOCKED: add-on only, no source edits, self-contained, no JPEG streaming, full
  fidelity, interactive. Option 3 architecture.
- OPEN: helper impl (cefpython vs C++ CEF), CEF bundle-vs-download, frame buffering
  scheme, control transport, host display surface, keyboard/IME scope, partial
  texture update availability.

## Next steps
- Get the collaborating instance's answers/critique on §11.
- Phase 0: confirm 4.4 bpy/gpu API limits + pick helper impl + pin CEF build.
- Phase 1: the spike (CEF OSR → SHM → GPUTexture → visible page in Blender).

## Verified facts (Jun 2026)
- 4.4 = Python 3.11.11; 5.0 = 3.11; 5.1 = Python 3.13 + Vulkan default.
- cefpython has no 3.11/3.13 binding → engine must live in a decoupled helper.
