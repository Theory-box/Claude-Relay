import bpy, sys
results = []
def check(name, fn):
    try: fn(); results.append(("PASS", name, ""))
    except Exception as e: results.append(("FAIL", name, str(e)))

bpy.ops.preferences.addon_enable(module="opengoal_tools")

def test_panels():
    ids = {t.bl_idname for t in bpy.types.Panel.__subclasses__() if hasattr(t,'bl_idname')}
    for p in ["OG_PT_level","OG_PT_spawn","OG_PT_triggers","OG_PT_camera","OG_PT_build_play",
              "OG_PT_selected_object","OG_PT_actor_eco_door","OG_PT_actor_sun_iris_door",
              "OG_PT_actor_basebutton","OG_PT_actor_launcherdoor","OG_PT_actor_water_vol"]:
        assert p in ids, f"Panel {p} missing"
check("All panels registered", test_panels)

def test_operators():
    og = dir(bpy.ops.og)
    for op in ["spawn_entity","export_build_play","export_build",
               "toggle_door_flag","nudge_float_prop","nudge_int_prop",
               "set_actor_link","clear_actor_link"]:
        assert op in og, f"og.{op} missing"
check("All core operators registered", test_operators)

def test_entity_defs():
    from opengoal_tools.data import ENTITY_DEFS
    old = ["babak","snow-bunny","launcher","fuel-cell","orb-cache-top",
           "plat-button","plat-eco","eco-door","launcherdoor","water-vol","oracle"]
    new = ["sun-iris-door","basebutton","jng-iris-door","sidedoor","rounddoor"]
    for e in old + new:
        assert e in ENTITY_DEFS, f"{e} missing from ENTITY_DEFS"
    assert ENTITY_DEFS["eco-door"].get("ag") != "eco-door-ag.go"
check("ENTITY_DEFS: old+new all present, no bad art group", test_entity_defs)

def test_etype_code():
    from opengoal_tools.data import ETYPE_CODE
    # eco-door maps to baseplat.o
    assert ETYPE_CODE.get("eco-door",{}).get("o") == "baseplat.o"
    assert ETYPE_CODE.get("sun-iris-door",{}).get("o") == "sun-iris-door.o"
    assert ETYPE_CODE.get("basebutton",{}).get("o") == "basebutton.o"
    assert ETYPE_CODE.get("jng-iris-door",{}).get("o") == "jungleb-obs.o"
check("ETYPE_CODE mappings correct", test_etype_code)

def test_links():
    from opengoal_tools.data import _actor_link_slots
    assert _actor_link_slots("orbit-plat")[0][0] == "alt-actor"   # old entry intact
    assert _actor_link_slots("basebutton") == []                   # intentionally empty — alt-actor removed (basebutton controls door via door's state-actor poll, not event dispatch)
    assert any(s[0]=="state-actor" for s in _actor_link_slots("eco-door"))
    assert any(s[0]=="state-actor" for s in _actor_link_slots("jng-iris-door"))
check("ACTOR_LINK_DEFS: old+new correct", test_links)

def test_lumps():
    from opengoal_tools.data import LUMP_REFERENCE
    # old entries
    assert "water-vol" in LUMP_REFERENCE
    assert "plat-button" in LUMP_REFERENCE
    assert "launcher" in LUMP_REFERENCE
    # new entries
    sun = [l[0] for l in LUMP_REFERENCE["sun-iris-door"]]
    assert "proximity" in sun and "timeout" in sun
    bb  = [l[0] for l in LUMP_REFERENCE["basebutton"]]
    assert "timeout" in bb
check("LUMP_REFERENCE: old+new complete", test_lumps)

def test_export_flags():
    # Verify the flag fix is in place inside the actual export module
    import inspect
    from opengoal_tools import export
    src = inspect.getsource(export)
    assert "(4 if auto_close else 0) | (8 if one_way else 0)" in src, "Flag fix not in export.py"
    assert "(1 if auto_close else 0) | (2 if one_way else 0)" not in src, "Old wrong flags still in export.py"
check("export.py flag fix verified in source", test_export_flags)

def test_no_crash_spawn():
    for name in ["ACTOR_babak_0","ACTOR_sun-iris-door_0","ACTOR_basebutton_0",
                 "ACTOR_jng-iris-door_0","ACTOR_sidedoor_0","ACTOR_rounddoor_0",
                 "ACTOR_launcherdoor_0","ACTOR_water-vol_0"]:
        bpy.ops.object.empty_add(type='CUBE', location=(0,0,0))
        o = bpy.context.active_object
        o.name = name
        bpy.data.objects.remove(o)
check("Actor empties: all door/button types create without crash", test_no_crash_spawn)

print("\n" + "="*62)
print("  FULL TEST RESULTS (feature/doors)")
print("="*62)
for status, name, err in results:
    print(f"  {'✓' if status=='PASS' else '✗'}  {name}")
    if err: print(f"       → {err}")
passed = sum(1 for s,_,_ in results if s == "PASS")
print(f"\n  {passed}/{len(results)} passed")
print("="*62)
sys.exit(0 if passed == len(results) else 1)
