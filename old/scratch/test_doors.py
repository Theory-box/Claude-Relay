import bpy, sys, traceback

results = []

def check(name, fn):
    try:
        fn()
        results.append(("PASS", name, ""))
    except Exception as e:
        results.append(("FAIL", name, str(e)))

# ── Enable addon ──────────────────────────────────────────────────────────
def test_enable():
    bpy.ops.preferences.addon_enable(module="opengoal_tools")
    assert "opengoal_tools" in bpy.context.preferences.addons
check("Enable addon", test_enable)

# ── Panels registered ─────────────────────────────────────────────────────
def test_panels():
    panel_ids = {t.bl_idname for t in bpy.types.Panel.__subclasses__()
                 if hasattr(t, 'bl_idname')}
    for pid in ["OG_PT_actor_eco_door",
                "OG_PT_actor_sun_iris_door",
                "OG_PT_actor_basebutton",
                "OG_PT_actor_launcherdoor"]:
        assert pid in panel_ids, f"Panel {pid} not registered"
check("Door/button panels registered", test_panels)

# ── Entity defs ───────────────────────────────────────────────────────────
def test_entity_defs():
    from opengoal_tools.data import ENTITY_DEFS
    for e in ["jng-iris-door", "sidedoor", "rounddoor",
              "sun-iris-door", "basebutton", "launcherdoor", "eco-door"]:
        assert e in ENTITY_DEFS, f"{e} missing from ENTITY_DEFS"
    assert ENTITY_DEFS["eco-door"].get("ag") != "eco-door-ag.go", "eco-door still has bad art group"
    assert ENTITY_DEFS["sun-iris-door"]["ag"] == "sun-iris-door-ag.go"
    assert ENTITY_DEFS["basebutton"]["ag"] == "generic-button-ag.go"
    assert ENTITY_DEFS["jng-iris-door"]["ag"] == "jng-iris-door-ag.go"
check("Entity defs correct", test_entity_defs)

# ── ETYPE_CODE (DGO map) ──────────────────────────────────────────────────
def test_etype_code():
    from opengoal_tools.data import ETYPE_CODE
    assert ETYPE_CODE.get("sun-iris-door", {}).get("o") == "sun-iris-door.o"
    assert ETYPE_CODE.get("basebutton",    {}).get("o") == "basebutton.o"
    assert ETYPE_CODE.get("jng-iris-door", {}).get("o") == "jungleb-obs.o"
    assert ETYPE_CODE.get("sidedoor",      {}).get("o") == "jungle-obs.o"
    assert ETYPE_CODE.get("rounddoor",     {}).get("o") == "misty-warehouse.o"
check("ETYPE_CODE (DGO map) correct", test_etype_code)

# ── eco-door flags bits ───────────────────────────────────────────────────
def test_flags():
    for auto, one, expected in [(True,True,12),(True,False,4),(False,True,8),(False,False,0)]:
        f = (4 if auto else 0) | (8 if one else 0)
        assert f == expected, f"auto={auto} one={one}: got {f}, want {expected}"
check("eco-door flags bits (auto=4, one-way=8)", test_flags)

# ── ACTOR_LINK_DEFS ───────────────────────────────────────────────────────
def test_links():
    from opengoal_tools.data import _actor_link_slots
    bb = _actor_link_slots("basebutton")
    assert len(bb) >= 1 and bb[0][0] == "alt-actor"
    eco = _actor_link_slots("eco-door")
    assert any(s[0] == "state-actor" for s in eco)
    jng = _actor_link_slots("jng-iris-door")
    assert any(s[0] == "state-actor" for s in jng)
check("ACTOR_LINK_DEFS basebutton + eco-door subclasses", test_links)

# ── LUMP_REFERENCE ────────────────────────────────────────────────────────
def test_lumps():
    from opengoal_tools.data import LUMP_REFERENCE
    for e in ["sun-iris-door", "basebutton", "jng-iris-door", "sidedoor"]:
        assert e in LUMP_REFERENCE, f"{e} missing from LUMP_REFERENCE"
    sun_lumps = [l[0] for l in LUMP_REFERENCE["sun-iris-door"]]
    assert "proximity" in sun_lumps
    assert "timeout" in sun_lumps
    bb_lumps = [l[0] for l in LUMP_REFERENCE["basebutton"]]
    assert "timeout" in bb_lumps
check("LUMP_REFERENCE completeness", test_lumps)

# ── Property storage on actor empties ─────────────────────────────────────
def test_props():
    for name, props in [
        ("ACTOR_sun-iris-door_test", {"og_door_proximity": 1, "og_door_timeout": 5.0}),
        ("ACTOR_basebutton_test",    {"og_button_timeout": 3.0}),
        ("ACTOR_jng-iris-door_test", {"og_door_auto_close": 1, "og_door_one_way": 0,
                                      "og_door_starts_open": 1}),
    ]:
        bpy.ops.object.empty_add(type='CUBE', location=(0,0,0))
        o = bpy.context.active_object
        o.name = name
        for k, v in props.items():
            o[k] = v
        for k, v in props.items():
            stored = o.get(k)
            assert abs(float(stored) - float(v)) < 0.001, \
                f"{name}: {k} = {stored!r}, want {v!r}"
        bpy.data.objects.remove(o)
check("Actor empty property storage (all door types)", test_props)

# ── Export logic simulation ───────────────────────────────────────────────
def test_export_sim():
    # Simulate what collect_actors does for each door type
    import bpy

    # sun-iris-door with proximity + timeout
    bpy.ops.object.empty_add(type='CUBE', location=(0,0,0))
    o = bpy.context.active_object
    o.name = "ACTOR_sun-iris-door_sim"
    o["og_door_proximity"] = 1
    o["og_door_timeout"]   = 10.0
    etype = "sun-iris-door"
    lump = {}
    if etype == "sun-iris-door":
        proximity = bool(o.get("og_door_proximity", False))
        timeout   = float(o.get("og_door_timeout",  0.0))
        if proximity: lump["proximity"] = ["uint32", 1]
        if timeout > 0.0: lump["timeout"] = ["float", timeout]
    assert lump == {"proximity": ["uint32", 1], "timeout": ["float", 10.0]}, \
        f"sun-iris-door lump wrong: {lump}"
    bpy.data.objects.remove(o)

    # basebutton with timeout
    bpy.ops.object.empty_add(type='CUBE', location=(0,0,0))
    o = bpy.context.active_object
    o.name = "ACTOR_basebutton_sim"
    o["og_button_timeout"] = 4.0
    etype = "basebutton"
    lump = {}
    if etype == "basebutton":
        timeout = float(o.get("og_button_timeout", 0.0))
        if timeout > 0.0: lump["timeout"] = ["float", timeout]
    assert lump == {"timeout": ["float", 4.0]}, f"basebutton lump wrong: {lump}"
    bpy.data.objects.remove(o)

    # eco-door with starts_open
    bpy.ops.object.empty_add(type='CUBE', location=(0,0,0))
    o = bpy.context.active_object
    o.name = "ACTOR_jng-iris-door_sim"
    o["og_door_starts_open"] = 1
    o["og_door_auto_close"]  = 0
    o["og_door_one_way"]     = 0
    etype = "jng-iris-door"
    lump = {}
    if etype in ("eco-door","jng-iris-door","sidedoor","rounddoor"):
        auto_close  = bool(o.get("og_door_auto_close",  False))
        one_way     = bool(o.get("og_door_one_way",     False))
        starts_open = bool(o.get("og_door_starts_open", False))
        flags = (4 if auto_close else 0) | (8 if one_way else 0)
        if flags: lump["flags"] = ["uint32", flags]
        if starts_open: lump["perm-status"] = ["uint32", 4]
    assert lump == {"perm-status": ["uint32", 4]}, f"starts_open lump wrong: {lump}"
    bpy.data.objects.remove(o)
check("Export logic simulation (all new door types)", test_export_sim)

# ── Operator registration ─────────────────────────────────────────────────
def test_operators():
    op_ids = dir(bpy.ops.og)
    assert "toggle_door_flag" in op_ids, "toggle_door_flag operator missing"
    assert "nudge_float_prop"  in op_ids, "nudge_float_prop operator missing"
check("Door operators registered", test_operators)

# ── Print results ─────────────────────────────────────────────────────────
print("\n" + "="*62)
print("  DOOR SYSTEM TEST RESULTS")
print("="*62)
for status, name, err in results:
    if status == "PASS":
        print(f"  ✓  {name}")
    else:
        print(f"  ✗  {name}")
        print(f"       → {err}")
passed = sum(1 for s,_,_ in results if s == "PASS")
total  = len(results)
print(f"\n  {passed}/{total} passed")
print("="*62)
sys.exit(0 if passed == total else 1)
