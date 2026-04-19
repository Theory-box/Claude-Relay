"""
VertexLit Renderer — Diagnostic Script
Paste into Blender's Text Editor and click Run Script.
Run it before entering render view, then again after a few in/out cycles.
"""

import threading
import gc
import bpy


def snapshot(label=""):
    print(f"\n{'='*60}")
    print(f"  VertexLit Diagnostic  {label}")
    print(f"{'='*60}")

    # ── 1. Python threads ─────────────────────────────────────────────────
    all_threads = threading.enumerate()
    vl_threads  = [t for t in all_threads if 'VertexLit' in t.name]
    print(f"\n[Threads]")
    print(f"  Total Python threads : {len(all_threads)}")
    print(f"  VertexLit-GI threads : {len(vl_threads)}")
    for t in vl_threads:
        print(f"    • {t.name}  alive={t.is_alive()}  daemon={t.daemon}")

    # ── 2. Module-level globals ───────────────────────────────────────────
    print(f"\n[Module globals]")
    try:
        import vertex_lit_renderer.engine as eng
        print(f"  _tex_cache entries   : {len(eng._tex_cache)}")
        print(f"  _shadow_map          : {eng._shadow_map is not None}")
        print(f"  _shadow_shader set   : {eng._shadow_shader is not None}")
        print(f"  _main_shader set     : {eng._main_shader is not None}")
        has_gi_active = hasattr(eng, '_gi_active')
        print(f"  _gi_active           : {eng._gi_active if has_gi_active else 'not present (good)'}")
    except Exception as e:
        print(f"  ERROR importing engine: {e}")

    # ── 3. Live ProgressiveGI instances via GC ────────────────────────────
    print(f"\n[ProgressiveGI instances]")
    try:
        from vertex_lit_renderer.gi import ProgressiveGI
        gis = [o for o in gc.get_objects() if type(o) is ProgressiveGI]
        print(f"  Count : {len(gis)}  (>1 means old instance not freed)")
        for i, gi in enumerate(gis):
            print(f"    [{i}] running={gi.is_running}  "
                  f"count={gi._count}  gen={gi._gen}  "
                  f"thread_alive={gi._thread.is_alive() if gi._thread else False}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── 4. Live BVHTree instances via GC ──────────────────────────────────
    print(f"\n[BVHTree instances]")
    try:
        from mathutils.bvhtree import BVHTree
        bvhs = [o for o in gc.get_objects() if type(o) is BVHTree]
        print(f"  Count : {len(bvhs)}  (>1 means BVH not freed after cancel)")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── 5. Live VertexLitEngine instances via GC ──────────────────────────
    print(f"\n[VertexLitEngine instances]")
    try:
        from vertex_lit_renderer.engine import VertexLitEngine
        engines = [o for o in gc.get_objects() if type(o) is VertexLitEngine]
        print(f"  Count : {len(engines)}  (>1 means engine not freed between sessions)")
        for i, e in enumerate(engines):
            gi = getattr(e, '_gi', None)
            print(f"    [{i}] state_ready={getattr(e,'_state_ready',False)}  "
                  f"dirty={getattr(e,'_dirty','?')}  "
                  f"gi_running={gi.is_running if gi else 'N/A'}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── 6. numpy arrays (GI accumulator arrays) ───────────────────────────
    print(f"\n[numpy arrays]")
    try:
        import numpy as np
        arrs = [o for o in gc.get_objects() if type(o) is np.ndarray]
        mb   = sum(a.nbytes for a in arrs) / 1048576
        print(f"  Count : {len(arrs)}  Total size: {mb:.1f} MB")
        # Show large arrays (likely GI accum buffers)
        large = sorted(arrs, key=lambda a: a.nbytes, reverse=True)[:5]
        for a in large:
            if a.nbytes > 1024:
                print(f"    • shape={a.shape}  dtype={a.dtype}  "
                      f"size={a.nbytes/1024:.1f} KB")
    except Exception as e:
        print(f"  ERROR: {e}")

    # ── 7. free() patch check — tells us if Blender calls it ─────────────
    print(f"\n[free() call tracking]")
    try:
        from vertex_lit_renderer.engine import VertexLitEngine
        if not getattr(VertexLitEngine, '_free_call_count', None):
            original_free = VertexLitEngine.free
            VertexLitEngine._free_call_count = 0
            def patched_free(self):
                VertexLitEngine._free_call_count += 1
                print(f"[VertexLit Diag] free() called — total calls: {VertexLitEngine._free_call_count}")
                original_free(self)
            VertexLitEngine.free = patched_free
            print("  Patched free() to count calls.")
            print("  Now enter/exit render view and re-run this script to see the count.")
        else:
            print(f"  free() has been called {VertexLitEngine._free_call_count} times since patch.")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n{'='*60}\n")


snapshot("— run before entering render view, then again after 5 in/out cycles —")
