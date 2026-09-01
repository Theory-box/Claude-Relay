# Ray Portal bake — prototypes

Standalone, self-contained headless render tests that build the scene and print a
pass/fail line. Run each with:

```
blender -b --python 01_portal_mechanism.py
```

Requires Blender 4.2+ (tested on 4.4.0), Cycles. They write a small PNG to /tmp
and print the check to stdout.

1. `01_portal_mechanism.py` — Ray Portal redirects rays to a different surface.
2. `02_uv_bake_gradient.py` — a 3D position gradient baked correctly into UV space.
3. `03_uv_bake_lighting.py` — real point-light lighting baked into UV space.
4. `04_uv_bake_curved.py` — curved surface via per-point normals (full coverage).

See `../FINDINGS.md` for the mechanism, recipe, gotchas, and the add-on plan.
