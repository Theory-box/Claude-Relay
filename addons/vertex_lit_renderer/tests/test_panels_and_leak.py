# tests/test_panels_and_leak.py
import bpy, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
import vertex_lit_renderer as vlr
import vertex_lit_renderer.engine as eng

F = []
def check(c, m): print(("  PASS " if c else "  FAIL ") + m); (F.append(m) if not c else None)

def ce(name):
    p = getattr(bpy.types, name, None)
    return getattr(p, 'COMPAT_ENGINES', set()) if p else set()

print("=== panels: before register ===")
check('VERTEX_LIT' not in ce('EEVEE_MATERIAL_PT_context_material'), "not present before register")

vlr.register()
print("=== panels: after register ===")
check('VERTEX_LIT' in ce('EEVEE_MATERIAL_PT_context_material'), "material selector shows VERTEX_LIT")
check('VERTEX_LIT' in ce('EEVEE_MATERIAL_PT_surface'), "material surface panel shows VERTEX_LIT")
check('VERTEX_LIT' in ce('MATERIAL_PT_custom_props'), "generic material panel shows VERTEX_LIT")

print("=== gpu cache release (leak fix) ===")
eng._main_shader = "sentinel"
eng._tex_cache['x'] = "sentinel"
eng._release_gpu_caches()
check(eng._main_shader is None, "main shader released")
check(len(eng._tex_cache) == 0, "texture cache cleared")

print("=== unregister cleans panels ===")
vlr.unregister()
check('VERTEX_LIT' not in ce('EEVEE_MATERIAL_PT_context_material'), "selector cleaned on unregister")
check('VERTEX_LIT' not in ce('MATERIAL_PT_custom_props'), "generic cleaned on unregister")

print("=== register/unregister cycle is clean ===")
vlr.register(); vlr.unregister()
vlr.register(); vlr.unregister()
check('VERTEX_LIT' not in ce('EEVEE_MATERIAL_PT_context_material'), "clean after a second full cycle")

print("SUMMARY: " + ("FAILED " + ", ".join(F) if F else "ALL CHECKS PASSED"))
sys.exit(1 if F else 0)
