import bpy
SRC=open("/home/claude/Claude-Relay/research/ray-portal-bake/ray_portal_bake.py").read()
ns={}; exec(SRC, ns); ns["register"]()
print("_get_device_mode() =", ns["_get_device_mode"]())
# inspect cycles prefs the way the addon does
try:
    cprefs=bpy.context.preferences.addons["cycles"].preferences
    print("compute_device_type =", getattr(cprefs,"compute_device_type","?"))
    print("num devices =", len(cprefs.devices))
    for d in cprefs.devices:
        print("  device:", d.name, "type=", d.type, "use=", d.use)
except Exception as e:
    print("cycles prefs err:", e)
sc=bpy.context.scene
sc.render.engine="CYCLES"
print("_apply_device_to_scene ->", ns["_apply_device_to_scene"](sc), "| scene.cycles.device =", sc.cycles.device)
ns["unregister"]()
