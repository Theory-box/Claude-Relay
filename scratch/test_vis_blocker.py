import sys, os, json, tempfile, traceback, pathlib
import bpy

# Fix: addons dir not in sys.path in headless mode
_ADDON_DIR = "/home/claude/blender-4.4.3-linux-x64/4.4/scripts/addons"
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)

# Now register the addon so bpy props are available
import addon_utils
addon_utils.enable("opengoal_tools", default_set=True)

PASS = []
FAIL = []

def test(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL.append((name, str(e)))
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()

# ── 1. Import ────────────────────────────────────────────────────────────────
def t_import():
    from opengoal_tools.export import (
        _classify_target, collect_vis_blockers, collect_vis_trigger_actors,
        write_jsonc, write_gc, _vismesh_ag_name, _vismesh_sg_name, _vismesh_lump_name,
        export_vis_blocker_glbs,
    )
    from opengoal_tools.utils import _is_linkable
    from opengoal_tools.data import VIS_TRIGGER_ENUM_ITEMS, AGGRO_EVENT_ENUM_ITEMS

test("1. addon imports cleanly", t_import)

# ── 2. _classify_target ──────────────────────────────────────────────────────
def t_classify():
    from opengoal_tools.export import _classify_target
    assert _classify_target("VISMESH_wall-1")   == "vis-blocker", "VISMESH_ not classified"
    assert _classify_target("CAMERA_main")      == "camera"
    assert _classify_target("CHECKPOINT_start") == "checkpoint"
    assert _classify_target("random_object")    == ""

test("2. _classify_target handles VISMESH_", t_classify)

# ── 3. Name helpers ──────────────────────────────────────────────────────────
def t_names():
    from opengoal_tools.export import _vismesh_ag_name, _vismesh_sg_name, _vismesh_lump_name
    assert _vismesh_ag_name("VISMESH_wall-1")       == "wall-1-ag",           repr(_vismesh_ag_name("VISMESH_wall-1"))
    assert _vismesh_sg_name("VISMESH_wall-1")       == "*wall-1-sg*",         repr(_vismesh_sg_name("VISMESH_wall-1"))
    assert _vismesh_lump_name("VISMESH_wall-1")     == "vis-blocker-wall-1",  repr(_vismesh_lump_name("VISMESH_wall-1"))
    assert _vismesh_ag_name("VISMESH_my_blocker")   == "my-blocker-ag",       repr(_vismesh_ag_name("VISMESH_my_blocker"))
    assert _vismesh_lump_name("VISMESH_my_blocker") == "vis-blocker-my-blocker"

test("3. name helpers (ag/sg/lump, underscore->dash)", t_names)

# ── 4. Enum items ────────────────────────────────────────────────────────────
def t_enum():
    from opengoal_tools.data import VIS_TRIGGER_ENUM_ITEMS
    ids = [item[0] for item in VIS_TRIGGER_ENUM_ITEMS]
    assert "hide"   in ids, f"hide missing: {ids}"
    assert "show"   in ids, f"show missing: {ids}"
    assert "toggle" in ids, f"toggle missing: {ids}"

test("4. VIS_TRIGGER_ENUM_ITEMS has hide/show/toggle", t_enum)

# ── Scene builder ────────────────────────────────────────────────────────────
def build_scene():
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    level_col = bpy.data.collections.new("my-level")
    scene.collection.children.link(level_col)
    level_col["og_level_name"] = "my-level"
    level_col["og_base_id"] = 10000

    bpy.ops.mesh.primitive_cube_add(size=2, location=(5, 0, 0))
    vismesh = bpy.context.active_object
    vismesh.name = "VISMESH_wall-1"
    scene.collection.objects.unlink(vismesh)
    level_col.objects.link(vismesh)

    bpy.ops.mesh.primitive_cube_add(size=3, location=(0, 0, 0))
    vol = bpy.context.active_object
    vol.name = "VOL_1"
    scene.collection.objects.unlink(vol)
    level_col.objects.link(vol)

    return scene, level_col, vismesh, vol

# ── 5. collect_vis_blockers ──────────────────────────────────────────────────
def t_collect():
    from opengoal_tools.export import collect_vis_blockers
    scene, _, vismesh, _ = build_scene()
    blockers = collect_vis_blockers(scene)
    assert len(blockers) == 1, f"expected 1, got {len(blockers)}"
    b = blockers[0]
    assert b["etype"]             == "vis-blocker",        repr(b["etype"])
    assert b["lump"]["art-name"]  == "wall-1-ag",          repr(b["lump"]["art-name"])
    assert b["lump"]["name"]      == "vis-blocker-wall-1", repr(b["lump"]["name"])
    assert b["lump"]["hidden"]    == ["uint32", 0],         repr(b["lump"]["hidden"])
    assert b["_ag_name"]          == "wall-1-ag"
    assert b["_blender_obj_name"] == "VISMESH_wall-1"

test("5. collect_vis_blockers actor dict", t_collect)

# ── 6. og_hidden_at_start ────────────────────────────────────────────────────
def t_hidden_start():
    from opengoal_tools.export import collect_vis_blockers
    scene, _, vismesh, _ = build_scene()
    vismesh["og_hidden_at_start"] = True
    blockers = collect_vis_blockers(scene)
    assert blockers[0]["lump"]["hidden"] == ["uint32", 1], repr(blockers[0]["lump"]["hidden"])

test("6. og_hidden_at_start=True → hidden lump = 1", t_hidden_start)

# ── 7. _is_linkable ──────────────────────────────────────────────────────────
def t_linkable():
    from opengoal_tools.utils import _is_linkable
    scene, _, vismesh, vol = build_scene()
    assert     _is_linkable(vismesh), "VISMESH_ should be linkable"
    assert not _is_linkable(vol),     "VOL_ should NOT be linkable"

test("7. _is_linkable accepts VISMESH_", t_linkable)

# ── 8. collect_vis_trigger_actors ────────────────────────────────────────────
def t_triggers(behaviour, expected_action):
    from opengoal_tools.export import collect_vis_blockers, collect_vis_trigger_actors
    scene, _, vismesh, vol = build_scene()
    entry = vol.og_vol_links.add()
    entry.target_name = "VISMESH_wall-1"
    entry.behaviour   = behaviour
    blockers = collect_vis_blockers(scene)
    triggers = collect_vis_trigger_actors(scene, blockers)
    assert len(triggers) == 1, f"expected 1 trigger, got {len(triggers)}"
    t = triggers[0]
    assert t["etype"]                   == "vis-trigger",            repr(t["etype"])
    assert t["lump"]["target-name"]     == "vis-blocker-wall-1",     repr(t["lump"]["target-name"])
    assert t["lump"]["action"]          == ["uint32", expected_action], f"{behaviour}={expected_action}, got {t['lump']['action']}"
    assert "bound-xmin" in t["lump"],  "missing bound-xmin"
    assert "bound-xmax" in t["lump"],  "missing bound-xmax"
    assert "bound-ymin" in t["lump"],  "missing bound-ymin"
    assert "bound-zmin" in t["lump"],  "missing bound-zmin"

test("8a. vis-trigger: hide → action=0",   lambda: t_triggers("hide",   0))
test("8b. vis-trigger: show → action=1",   lambda: t_triggers("show",   1))
test("8c. vis-trigger: toggle → action=2", lambda: t_triggers("toggle", 2))

# ── 9. write_jsonc ───────────────────────────────────────────────────────────
def t_jsonc():
    from opengoal_tools.export import collect_vis_blockers, write_jsonc
    import opengoal_tools.export as exp
    orig_ldir = exp._ldir
    scene, _, vismesh, _ = build_scene()
    blockers = collect_vis_blockers(scene)
    with tempfile.TemporaryDirectory() as tmpdir:
        exp._ldir = lambda name: pathlib.Path(tmpdir)
        try:
            write_jsonc("my-level", [], [], [], 10000, vis_blockers=blockers)
            out = pathlib.Path(tmpdir) / "my-level.jsonc"
            assert out.exists(), "jsonc not written"
            data = json.loads(out.read_text().split("\n", 1)[1])
            # art_groups contains vis-blocker ag
            assert "wall-1-ag" in data["art_groups"], f"art_groups: {data['art_groups']}"
            vis_actors = [a for a in data["actors"] if a.get("etype") == "vis-blocker"]
            assert len(vis_actors) == 1, f"expected 1 actor, got {len(vis_actors)}"
            # Private keys stripped
            for k in ("_blender_obj_name", "_sg_name", "_ag_name"):
                assert k not in vis_actors[0], f"private key leaked: {k!r}"
            assert vis_actors[0]["lump"]["art-name"] == "wall-1-ag"
            assert vis_actors[0]["lump"]["hidden"]   == ["uint32", 0]
        finally:
            exp._ldir = orig_ldir

test("9. write_jsonc: art_groups correct, private keys stripped", t_jsonc)

# ── 10 & 11. write_gc ────────────────────────────────────────────────────────
def t_write_gc(flag, expect_present):
    import opengoal_tools.export as exp
    orig_goal = exp._goal_src
    with tempfile.TemporaryDirectory() as tmpdir:
        exp._goal_src = lambda: pathlib.Path(tmpdir)
        try:
            exp.write_gc("my-level", has_vis_blockers=flag)
            gc = (pathlib.Path(tmpdir) / "levels" / "my-level" / "my-level-obs.gc").read_text()
            if expect_present:
                assert "deftype vis-blocker"         in gc, "missing deftype vis-blocker"
                assert "deftype vis-trigger"         in gc, "missing deftype vis-trigger"
                assert "draw-status hidden"          in gc, "missing draw-status hidden"
                assert "process-by-ename"            in gc, "missing process-by-ename"
                assert "initialize-skeleton-by-name" in gc, "missing initialize-skeleton-by-name"
                assert "send-event target"           in gc, "missing send-event target"
                assert "defstate vis-blocker-idle"   in gc, "missing vis-blocker-idle state"
                assert "defstate vis-trigger-active" in gc, "missing vis-trigger-active state"
            else:
                assert "vis-blocker" not in gc, "vis-blocker leaked without flag"
                assert "vis-trigger"  not in gc, "vis-trigger leaked without flag"
        finally:
            exp._goal_src = orig_goal

test("10. write_gc WITH has_vis_blockers emits GOAL types",    lambda: t_write_gc(True,  True))
test("11. write_gc WITHOUT has_vis_blockers omits GOAL types", lambda: t_write_gc(False, False))

# ── 12. VISMESH_ in export_glb exclusion list ────────────────────────────────
def t_prefix():
    import opengoal_tools.export as exp, inspect
    src = inspect.getsource(exp.export_glb)
    assert "VISMESH_" in src, "VISMESH_ not in export_glb exclusion prefix"

test("12. VISMESH_ excluded from level GLB prefix list", t_prefix)

# ── 13. write_gc camera-marker still present (regression) ───────────────────
def t_regression_gc():
    import opengoal_tools.export as exp
    orig_goal = exp._goal_src
    with tempfile.TemporaryDirectory() as tmpdir:
        exp._goal_src = lambda: pathlib.Path(tmpdir)
        try:
            exp.write_gc("my-level", has_vis_blockers=True)
            gc = (pathlib.Path(tmpdir) / "levels" / "my-level" / "my-level-obs.gc").read_text()
            assert "deftype camera-marker" in gc, "camera-marker type regressed"
        finally:
            exp._goal_src = orig_goal

test("13. camera-marker type still emitted (regression check)", t_regression_gc)

# ── 14. Multiple VISMESH_ objects ────────────────────────────────────────────
def t_multi_blockers():
    from opengoal_tools.export import collect_vis_blockers
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    level_col = bpy.data.collections.new("my-level")
    scene.collection.children.link(level_col)
    level_col["og_level_name"] = "my-level"

    for i, name in enumerate(["VISMESH_wall-1", "VISMESH_ceiling-1", "VISMESH_door-a"]):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(i*5, 0, 0))
        obj = bpy.context.active_object
        obj.name = name
        scene.collection.objects.unlink(obj)
        level_col.objects.link(obj)

    blockers = collect_vis_blockers(scene)
    assert len(blockers) == 3, f"expected 3, got {len(blockers)}"
    names = {b["lump"]["name"] for b in blockers}
    assert "vis-blocker-wall-1"    in names
    assert "vis-blocker-ceiling-1" in names
    assert "vis-blocker-door-a"    in names
    ags = {b["_ag_name"] for b in blockers}
    assert "wall-1-ag" in ags and "ceiling-1-ag" in ags and "door-a-ag" in ags

test("14. multiple VISMESH_ objects all collected", t_multi_blockers)

# ── Results ──────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
print("=" * 60)
if FAIL:
    print("\nFAILED:")
    for n, e in FAIL:
        print(f"  ✗ {n}")
        print(f"    {e}")
    sys.exit(1)
else:
    print("\nAll tests passed! ✓")
    sys.exit(0)
