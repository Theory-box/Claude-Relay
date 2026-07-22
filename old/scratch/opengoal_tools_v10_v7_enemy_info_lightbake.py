bl_info = {
    "name": "OpenGOAL Level Tools",
    "author": "water111 / JohnCheathem",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > N-Panel > OpenGOAL",
    "description": "Jak 1 level export, actor placement, build and launch tools",
    "category": "Development",
}

import bpy, os, re, json, socket, subprocess, threading, time, math
from pathlib import Path
from bpy.props import (StringProperty, BoolProperty, IntProperty,
                       EnumProperty, PointerProperty, FloatProperty)
from bpy.types import Panel, Operator, PropertyGroup, AddonPreferences

# ---------------------------------------------------------------------------
# PAT ENUMS
# ---------------------------------------------------------------------------

pat_surfaces = [
    ("stone","stone","",0), ("ice","ice","",1), ("quicksand","quicksand","",2),
    ("waterbottom","waterbottom","",3), ("tar","tar","",4), ("sand","sand","",5),
    ("wood","wood","",6), ("grass","grass","",7), ("pcmetal","pcmetal","",8),
    ("snow","snow","",9), ("deepsnow","deepsnow","",10), ("hotcoals","hotcoals","",11),
    ("lava","lava","",12), ("crwood","crwood","",13), ("gravel","gravel","",14),
    ("dirt","dirt","",15), ("metal","metal","",16), ("straw","straw","",17),
    ("tube","tube","",18), ("swamp","swamp","",19), ("stopproj","stopproj","",20),
    ("rotate","rotate","",21), ("neutral","neutral","",22),
]
pat_events = [
    ("none","none","",0), ("deadly","deadly","",1), ("endlessfall","endlessfall","",2),
    ("burn","burn","",3), ("deadlyup","deadlyup","",4), ("burnup","burnup","",5),
    ("melt","melt","",6),
]
pat_modes = [
    ("ground","ground","",0), ("wall","wall","",1), ("obstacle","obstacle","",2),
]

# ---------------------------------------------------------------------------
# ENTITY DEFINITIONS
# ---------------------------------------------------------------------------
# nav_safe=True  → can spawn without navmesh (flying, simple, or kermit-style)
# nav_safe=False → uses move-to-ground pathfinding; crashes without navmesh
#                  workaround: inject nav-mesh-sphere res tag at export time

ENTITY_DEFS = {
    # ---------------------------------------------------------------------------
    # Field reference:
    #   nav_safe    : False = nav-enemy (needs real navmesh + entity.gc patch)
    #                 True  = process-drawable / prop (no navmesh needed)
    #   needs_path  : True  = crashes/errors without a 'path' lump in JSONC
    #                         waypoints drive path export; minimum 1 wp unless noted
    #   needs_pathb : True  = also needs a second 'pathb' lump (swamp-bat only)
    #   is_prop     : True  = decorative only, no AI/combat whatsoever
    #   ai_type     : "nav-enemy"        → uses nav-mesh pathfinding
    #                 "process-drawable" → custom AI, ignores navmesh
    #                 "prop"             → idle animation only
    # ---------------------------------------------------------------------------

    # ---- NAV-ENEMIES — nav_safe=False, need navmesh + entity.gc patch ----
    # Grouped by tpage source level. Mix max 2 groups per scene to avoid heap OOM.
    # Beach group (tpages: 212, 214, 213, 215)
    "babak":            {"label":"Babak (Lurker)",       "cat":"Enemies",   "tpage_group":"Beach",    "ag":"babak-ag.go",             "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(1.0,0.1,0.1,1.0), "shape":"SPHERE"},
    "lurkercrab":       {"label":"Lurker Crab",          "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkercrab-ag.go",        "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.8,0.4,0.0,1.0), "shape":"SPHERE"},
    "lurkerpuppy":      {"label":"Lurker Puppy",         "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkerpuppy-ag.go",       "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.5,0.1,1.0), "shape":"SPHERE"},
    # Jungle group (tpages: 385, 531, 386, 388)
    "hopper":           {"label":"Hopper",               "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"hopper-ag.go",            "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(1.0,0.2,0.1,1.0), "shape":"SPHERE"},
    # Swamp group (tpages: 358, 659, 629, 630)
    "swamp-rat":        {"label":"Swamp Rat",            "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"swamp-rat-ag.go",         "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.5,0.35,0.1,1.0),"shape":"SPHERE"},
    "kermit":           {"label":"Kermit (Lurker)",      "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"kermit-ag.go",            "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.2,0.7,0.2,1.0), "shape":"SPHERE"},
    # Snow group (tpages: 710, 842, 711, 712)
    "snow-bunny":       {"label":"Snow Bunny",           "cat":"Enemies",   "tpage_group":"Snow",     "ag":"snow-bunny-ag.go",        "nav_safe":False, "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.9,1.0,1.0), "shape":"SPHERE"},
    # Sunken group (tpages: 661, 663, 714, 662)
    "double-lurker":    {"label":"Double Lurker",        "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"double-lurker-ag.go",     "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.7,0.15,0.15,1.0),"shape":"SPHERE"},
    # Misty group (tpages: 516, 521, 518, 520)
    "bonelurker":       {"label":"Bone Lurker",          "cat":"Enemies",   "tpage_group":"Misty",    "ag":"bonelurker-ag.go",        "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.8,0.7,0.5,1.0), "shape":"SPHERE"},
    "muse":             {"label":"Muse",                 "cat":"Enemies",   "tpage_group":"Misty",    "ag":"muse-ag.go",              "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.6,0.9,1.0), "shape":"SPHERE"},
    # Maincave group (tpages: 1313, 1315, 1314, 1312)
    "baby-spider":      {"label":"Baby Spider",          "cat":"Enemies",   "tpage_group":"Maincave", "ag":"baby-spider-ag.go",       "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.5,0.2,0.1,1.0), "shape":"SPHERE"},
    # Final group (tpages: varies)
    "green-eco-lurker": {"label":"Green Eco Lurker",     "cat":"Enemies",   "tpage_group":"Final",    "ag":"green-eco-lurker-ag.go",  "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.2,0.8,0.2,1.0), "shape":"SPHERE"},

    # ---- PROCESS-DRAWABLE ENEMIES — nav_safe=True, no navmesh, may need path ----
    # Grouped by tpage source level.
    # Beach group
    "lurkerworm":       {"label":"Lurker Worm",          "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkerworm-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.6,0.1,1.0), "shape":"SPHERE"},
    # Jungle group
    "junglesnake":      {"label":"Jungle Snake",         "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"junglesnake-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.2,0.6,0.2,1.0), "shape":"SPHERE"},
    # Swamp group
    "swamp-bat":        {"label":"Swamp Bat",            "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"swamp-bat-ag.go",         "nav_safe":True,  "needs_path":True,  "needs_pathb":True,  "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.2,0.5,1.0), "shape":"SPHERE"},
    # Snow group
    "yeti":             {"label":"Yeti",                 "cat":"Enemies",   "tpage_group":"Snow",     "ag":"yeti-ag.go",              "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.95,1.0,1.0),"shape":"SPHERE"},
    # Sunken group
    "bully":            {"label":"Bully",                "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"bully-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.9,1.0), "shape":"SPHERE"},
    "puffer":           {"label":"Puffer",               "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"puffer-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.4,0.9,1.0), "shape":"SPHERE"},
    # Ogre group (tpages: 875, 967, 884, 1117)
    "flying-lurker":    {"label":"Flying Lurker",        "cat":"Enemies",   "tpage_group":"Ogre",     "ag":"flying-lurker-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.2,0.8,1.0), "shape":"SPHERE"},
    "plunger-lurker":   {"label":"Plunger Lurker",       "cat":"Enemies",   "tpage_group":"Ogre",     "ag":"plunger-lurker-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.8,0.3,0.3,1.0), "shape":"SPHERE"},
    # Maincave group
    "mother-spider":    {"label":"Mother Spider",        "cat":"Enemies",   "tpage_group":"Maincave", "ag":"mother-spider-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.2,0.1,1.0), "shape":"SPHERE"},
    "gnawer":           {"label":"Gnawer",               "cat":"Enemies",   "tpage_group":"Maincave", "ag":"gnawer-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.3,0.1,1.0), "shape":"SPHERE"},
    "driller-lurker":   {"label":"Driller Lurker",       "cat":"Enemies",   "tpage_group":"Maincave", "ag":"driller-lurker-ag.go",    "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.5,0.5,1.0), "shape":"SPHERE"},
    "dark-crystal":     {"label":"Dark Crystal",         "cat":"Enemies",   "tpage_group":"Maincave", "ag":"dark-crystal-ag.go",      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.0,0.6,1.0), "shape":"SPHERE"},
    # Robocave group (tpages: 1318, 1319, 1317, 1316)
    "cavecrusher":      {"label":"Cave Crusher",         "cat":"Enemies",   "tpage_group":"Robocave", "ag":"cavecrusher-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.6,1.0), "shape":"SPHERE"},
    # Misty group
    "quicksandlurker":  {"label":"Quicksand Lurker",     "cat":"Enemies",   "tpage_group":"Misty",    "ag":"quicksandlurker-ag.go",   "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.8,0.3,1.0), "shape":"SPHERE"},
    # Village1 group (always loaded — free)
    "ram":              {"label":"Ram",                  "cat":"Enemies",   "tpage_group":"Village1", "ag":"ram-ag.go",               "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.4,0.2,1.0), "shape":"SPHERE"},
    # Unknown/untested tpage group
    "lightning-mole":   {"label":"Lightning Mole",       "cat":"Enemies",   "tpage_group":"Unknown",  "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.7,0.9,1.0), "shape":"SPHERE"},
    "ice-cube":         {"label":"Ice Cube",             "cat":"Enemies",   "tpage_group":"Unknown",  "ag":None,                      "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.9,1.0,1.0), "shape":"CUBE"},
    "fireboulder":      {"label":"Fire Boulder",         "cat":"Enemies",   "tpage_group":"Unknown",  "ag":"fireboulder-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(1.0,0.4,0.0,1.0), "shape":"SPHERE"},

    # ---- PROPS — is_prop=True, idle animation only, no AI/combat ----
    # evilplant: process-drawable with ONE state (idle loop). No attack, no chase.
    # Listed under Props not Enemies to avoid confusion.
    "evilplant":        {"label":"Evil Plant (Prop)",    "cat":"Props",     "ag":"evilplant-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.5,0.1,1.0), "shape":"SPHERE"},
    "dark-plant":       {"label":"Dark Plant (Prop)",    "cat":"Props",     "ag":"dark-plant-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.3,0.1,0.5,1.0), "shape":"SPHERE"},

    # ---- BOSSES ----
    "ogreboss":         {"label":"Klaww (Ogre Boss)",    "cat":"Bosses",    "ag":"ogreboss-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(1.0,0.3,0.0,1.0), "shape":"SPHERE"},
    "plant-boss":       {"label":"Plant Boss",           "cat":"Bosses",    "ag":"plant-boss-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.1,0.7,0.1,1.0), "shape":"SPHERE"},
    "robotboss":        {"label":"Metal Head Boss",      "cat":"Bosses",    "ag":"robotboss-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.8,1.0), "shape":"SPHERE"},
    # ---- NPCs ----
    "yakow":            {"label":"Yakow",                "cat":"NPCs",      "ag":"yakow-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.8,0.5,1.0), "shape":"SPHERE"},
    "flutflut":         {"label":"Flut Flut",            "cat":"NPCs",      "ag":"flutflut-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.7,1.0,1.0), "shape":"SPHERE"},
    "mayor":            {"label":"Mayor",                "cat":"NPCs",      "ag":"mayor-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.7,0.2,1.0), "shape":"SPHERE"},
    "farmer":           {"label":"Farmer",               "cat":"NPCs",      "ag":"farmer-ag.go",            "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.5,0.2,1.0), "shape":"SPHERE"},
    "fisher":           {"label":"Fisher",               "cat":"NPCs",      "ag":"fisher-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.5,0.7,1.0), "shape":"SPHERE"},
    "explorer":         {"label":"Explorer",             "cat":"NPCs",      "ag":"explorer-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.5,0.3,1.0), "shape":"SPHERE"},
    "geologist":        {"label":"Geologist",            "cat":"NPCs",      "ag":"geologist-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.4,0.3,1.0), "shape":"SPHERE"},
    "warrior":          {"label":"Warrior",              "cat":"NPCs",      "ag":"warrior-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.3,0.3,1.0), "shape":"SPHERE"},
    "gambler":          {"label":"Gambler",              "cat":"NPCs",      "ag":"gambler-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.7,0.4,1.0), "shape":"SPHERE"},
    "sculptor":         {"label":"Sculptor",             "cat":"NPCs",      "ag":"sculptor-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.6,0.5,1.0), "shape":"SPHERE"},
    "billy":            {"label":"Billy",                "cat":"NPCs",      "ag":"billy-ag.go",             "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.7,0.9,1.0), "shape":"SPHERE"},
    "pelican":          {"label":"Pelican",              "cat":"NPCs",      "ag":"pelican-ag.go",           "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.9,0.7,1.0), "shape":"SPHERE"},
    "seagull":          {"label":"Seagull",              "cat":"NPCs",      "ag":"seagull-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.9,0.9,1.0), "shape":"SPHERE"},
    "robber":           {"label":"Robber (Lurker)",      "cat":"NPCs",      "ag":"robber-ag.go",            "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.3,0.7,1.0), "shape":"SPHERE"},
    # ---- PICKUPS ----
    "fuel-cell":        {"label":"Power Cell",           "cat":"Pickups",   "ag":"fuel-cell-ag.go",         "nav_safe":True,  "color":(1.0,0.9,0.0,1.0), "shape":"ARROWS"},
    "money":            {"label":"Orb (Precursor)",      "cat":"Pickups",   "ag":"money-ag.go",             "nav_safe":True,  "color":(0.8,0.8,0.0,1.0), "shape":"PLAIN_AXES"},
    "buzzer":           {"label":"Scout Fly",            "cat":"Pickups",   "ag":"buzzer-ag.go",            "nav_safe":True,  "color":(0.9,0.9,0.2,1.0), "shape":"PLAIN_AXES"},
    "crate":            {"label":"Crate",                "cat":"Pickups",   "ag":"crate-ag.go",             "nav_safe":True,  "color":(0.8,0.5,0.1,1.0), "shape":"CUBE"},
    "orb-cache-top":    {"label":"Orb Cache",            "cat":"Pickups",   "ag":"orb-cache-top-ag.go",     "nav_safe":True,  "color":(0.9,0.7,0.1,1.0), "shape":"CUBE"},
    "powercellalt":     {"label":"Power Cell (alt)",     "cat":"Pickups",   "ag":"powercellalt-ag.go",      "nav_safe":True,  "color":(1.0,0.85,0.0,1.0),"shape":"ARROWS"},
    "eco-yellow":       {"label":"Yellow Eco Vent",      "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(1.0,0.9,0.0,1.0), "shape":"PLAIN_AXES"},
    "eco-red":          {"label":"Red Eco Vent",         "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(1.0,0.2,0.1,1.0), "shape":"PLAIN_AXES"},
    "eco-blue":         {"label":"Blue Eco Vent",        "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(0.2,0.4,1.0,1.0), "shape":"PLAIN_AXES"},
    "eco-green":        {"label":"Green Eco Vent",       "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(0.1,0.9,0.2,1.0), "shape":"PLAIN_AXES"},
    # ---- PLATFORMS ----
    "plat":             {"label":"Floating Platform",    "cat":"Platforms", "ag":"plat-ag.go",              "nav_safe":True,  "color":(0.5,0.5,0.8,1.0), "shape":"CUBE"},
    "plat-eco":         {"label":"Eco Platform",         "cat":"Platforms", "ag":"plat-eco-ag.go",          "nav_safe":True,  "color":(0.3,0.7,0.9,1.0), "shape":"CUBE"},
    "plat-button":      {"label":"Button Platform",      "cat":"Platforms", "ag":"plat-button-ag.go",       "nav_safe":True,  "color":(0.6,0.6,0.7,1.0), "shape":"CUBE"},
    "plat-flip":        {"label":"Flip Platform",        "cat":"Platforms", "ag":"plat-flip-ag.go",         "nav_safe":True,  "color":(0.5,0.5,0.7,1.0), "shape":"CUBE"},
    "wall-plat":        {"label":"Wall Platform",        "cat":"Platforms", "ag":"wall-plat-ag.go",         "nav_safe":True,  "color":(0.4,0.5,0.7,1.0), "shape":"CUBE"},
    "balance-plat":     {"label":"Balance Platform",     "cat":"Platforms", "ag":"balance-plat-ag.go",      "nav_safe":True,  "color":(0.5,0.6,0.8,1.0), "shape":"CUBE"},
    "teetertotter":     {"label":"Teeter Totter",        "cat":"Platforms", "ag":"teetertotter-ag.go",      "nav_safe":True,  "color":(0.6,0.5,0.4,1.0), "shape":"CUBE"},
    "side-to-side-plat":{"label":"Side-to-Side Plat",   "cat":"Platforms", "ag":"side-to-side-plat-ag.go", "nav_safe":True,  "color":(0.4,0.5,0.8,1.0), "shape":"CUBE"},
    "wedge-plat":       {"label":"Wedge Platform",       "cat":"Platforms", "ag":"wedge-plat-ag.go",        "nav_safe":True,  "color":(0.5,0.5,0.7,1.0), "shape":"CUBE"},
    "tar-plat":         {"label":"Tar Platform",         "cat":"Platforms", "ag":"tar-plat-ag.go",          "nav_safe":True,  "color":(0.2,0.2,0.2,1.0), "shape":"CUBE"},
    "revcycle":         {"label":"Rotating Platform",    "cat":"Platforms", "ag":"revcycle-ag.go",          "nav_safe":True,  "color":(0.6,0.4,0.6,1.0), "shape":"CUBE"},
    "launcher":         {"label":"Launcher",             "cat":"Platforms", "ag":"floating-launcher-ag.go", "nav_safe":True,  "color":(0.9,0.6,0.1,1.0), "shape":"CONE"},
    "warpgate":         {"label":"Warp Gate",            "cat":"Platforms", "ag":"warpgate-ag.go",          "nav_safe":True,  "color":(0.3,0.8,0.9,1.0), "shape":"CIRCLE"},
    # ---- OBJECTS / INTERACTABLES ----
    "cavecrystal":      {"label":"Cave Crystal",         "cat":"Objects",   "ag":"cavecrystal-ag.go",       "nav_safe":True,  "color":(0.7,0.4,0.9,1.0), "shape":"SPHERE"},
    "cavegem":          {"label":"Cave Gem",             "cat":"Objects",   "ag":"cavegem-ag.go",           "nav_safe":True,  "color":(0.8,0.2,0.8,1.0), "shape":"SPHERE"},
    "tntbarrel":        {"label":"TNT Barrel",           "cat":"Objects",   "ag":"tntbarrel-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(1.0,0.4,0.0,1.0), "shape":"CUBE"},
    "shortcut-boulder": {"label":"Shortcut Boulder",     "cat":"Objects",   "ag":"shortcut-boulder-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.6,0.5,0.4,1.0), "shape":"SPHERE"},
    "spike":            {"label":"Spike",                "cat":"Objects",   "ag":"spike-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.8,0.2,0.2,1.0), "shape":"CONE"},
    "steam-cap":        {"label":"Steam Cap",            "cat":"Objects",   "ag":"steam-cap-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.8,0.8,0.8,1.0), "shape":"CUBE"},
    "windmill-one":     {"label":"Windmill",             "cat":"Objects",   "ag":"windmill-one-ag.go",      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.7,0.7,0.5,1.0), "shape":"CUBE"},
    "ecoclaw":          {"label":"Eco Claw",             "cat":"Objects",   "ag":"ecoclaw-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.8,0.3,1.0), "shape":"CUBE"},
    "ecovalve":         {"label":"Eco Valve",            "cat":"Objects",   "ag":"ecovalve-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.3,0.7,0.3,1.0), "shape":"CUBE"},
    "swamp-rock":       {"label":"Swamp Rock",           "cat":"Objects",   "ag":"swamp-rock-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.4,0.4,0.3,1.0), "shape":"SPHERE"},
    "gondola":          {"label":"Gondola",              "cat":"Objects",   "ag":"gondola-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.3,1.0), "shape":"CUBE"},
    "swamp-blimp":      {"label":"Swamp Blimp",          "cat":"Objects",   "ag":"swamp-blimp-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.6,0.5,0.3,1.0), "shape":"SPHERE"},
    "swamp-rope":       {"label":"Swamp Rope",           "cat":"Objects",   "ag":"swamp-rope-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.2,1.0), "shape":"CUBE"},
    "swamp-spike":      {"label":"Swamp Spike",          "cat":"Objects",   "ag":"swamp-spike-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.7,0.3,0.2,1.0), "shape":"CONE"},
    "whirlpool":        {"label":"Whirlpool",            "cat":"Objects",   "ag":"whirlpool-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.4,0.8,1.0), "shape":"CIRCLE"},
    "warp-gate":        {"label":"Warp Gate Switch",     "cat":"Objects",   "ag":"warp-gate-switch-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.7,0.8,1.0), "shape":"CIRCLE"},
    # ---- DEBUG ----
    "test-actor":       {"label":"Test Actor",           "cat":"Debug",     "ag":"test-actor-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"prop",             "color":(0.8,0.8,0.8,1.0), "shape":"PLAIN_AXES"},
}

CRATE_ITEMS = [
    ("steel","Steel (empty)","",0), ("wood","Wood (orbs)","",1),
    ("metal","Metal","",2), ("darkeco","Dark Eco","",3),
    ("iron","Iron (spin to break)","",4),
]


# ---------------------------------------------------------------------------
# WIKI DATA — images + descriptions scraped from jakanddaxter.fandom.com
# Images live in: <addon_dir>/enemy-images/<filename>
# ---------------------------------------------------------------------------

ENTITY_WIKI = {
    'aphid':                 {'img': 'Aphid lurker render.jpg',                               'desc': 'The aphid lurker is an insectoid lurker enemy in The Precursor Legacy. They spawn from the dark eco plant to defend it during the mission "Defeat the dark eco plant" within the Forbidden Temple.'},
    'babak':                 {'img': 'Babak render.jpg',                                      'desc': "The babak is a type of lurker in The Precursor Legacy, Daxter, and Jak II. They are introduced as enemies, being the most common foot soldiers in Gol Acheron and Maia's army."},
    'baby-spider':           {'img': 'Baby spider (lurker) render.jpg',                       'desc': 'Small spider lurkers found in Spider Cave. They accompany the Mother Spider and swarm Jak on approach.'},
    'balloonlurker':         {'img': None,                                                    'desc': 'The mine dropper, also known as the lurker balloon, is a vehicle operated by a balloon lurker in The Precursor Legacy. Several were seen flying around the bay near the Lurker ship at Misty Island.'},
    'billy':                 {'img': None,                                                    'desc': 'A lurker frog type found in Boggy Swamp.'},
    'bonelurker':            {'img': 'Bone armor lurker render.jpg',                          'desc': "The bone armor lurker is an enemy in The Precursor Legacy, only seen on Misty Island. It confronted Jak and Daxter in the opening cutscene, causing Daxter's transformation into an ottsel."},
    'bully':                 {'img': 'Bully render.jpg',                                      'desc': 'The bully, also known as the spinning lurker, is an enemy in The Precursor Legacy. They were only found in pool hubs at the lost Precursor city.'},
    'double-lurker':         {'img': 'Double lurker render.jpg',                              'desc': 'The double lurker is a team of enemies in The Precursor Legacy — two blue-tinted lurkers stacked on top of each other, the smaller riding on the larger to provide height and reach.'},
    'driller-lurker':        {'img': 'Driller lurker render.jpg',                             'desc': 'The driller lurker is an enemy in The Precursor Legacy that mines cave rock with its drill. Found in Spider Cave, drilling away at the Precursor robot excavation site.'},
    'flying-lurker':         {'img': 'Pedal-copter lurker render.jpg',                        'desc': 'The pedal-copter lurker, also known as a flying lurker, is an enemy in The Precursor Legacy. Only found in Mountain Pass, they travel in a scouting party to detonate mines in the Pass.'},
    'gnawer':                {'img': 'Gnawing lurker render.jpg',                             'desc': 'The gnawing lurker is a species of lurker encountered at Spider Cave. Found throughout the cave gnawing on wooden support beams — Jak must eliminate them before they bring the cave down.'},
    'green-eco-lurker':      {'img': 'Green eco lurker render.jpg',                           'desc': 'The green eco lurker, also known as the dark eco lurker, is a lurker enemy in The Precursor Legacy. They were created by Gol Acheron and Maia — one of the only lurkers known to be artificially created.'},
    'hopper':                {'img': 'Hopper (lurker) render.jpg',                            'desc': 'A type of lurker encountered in the Forbidden Jungle during The Precursor Legacy. They are agile, jumping lurkers that patrol the jungle floor.'},
    'junglefish':            {'img': 'Jungle fish render.jpg',                                'desc': 'The jungle fish, also known as the fish lurker, is an enemy in The Precursor Legacy. Fish transformed into lurkers by Maia through dark eco sorcery — among the only lurkers known to be artificially created.'},
    'junglesnake':           {'img': 'Lurker snake render.jpg',                               'desc': 'The lurker snake is an enemy in The Precursor Legacy — large brown serpentine lurkers residing in the canopy of Forbidden Jungle. They hang from branches at fixed points, attacking intruders below.'},
    'kermit':                {'img': 'Lurker toad render.jpg',                                'desc': 'The lurker toad is an enemy in The Precursor Legacy. A large purple frog lurker found hopping around Boggy Swamp, making a very loud croaking noise.'},
    'lurker-shark':          {'img': 'Lurker shark from The Precursor Legacy render.jpg',     'desc': "The lurker shark is a large orange shark-like creature inhabiting the oceans in The Precursor Legacy, serving as the game's invisible wall mechanism to prevent the player from moving too far into the water."},
    'lurkercrab':            {'img': 'Lurker crab render.jpg',                                'desc': 'The lurker crab is an enemy found at Sentinel Beach. They closely resemble hermit crabs, hiding under their shell until they reach out for an attack.'},
    'lurkerpuppy':           {'img': 'Lurker puppy render.jpg',                               'desc': 'The lurker puppy is a small lurker patrolling the higher regions of Sentinel Beach. Maroon in colour, bearing close resemblance to a small dog.'},
    'lurkerworm':            {'img': 'Sand worm render.jpg',                                  'desc': 'The sand worm, also known as the sea serpent lurker, is an enemy in The Precursor Legacy. Lurkers dwelling in sand pits at Sentinel Beach — they burst from the ground to attack.'},
    'mother-spider':         {'img': 'Mother spider (lurker) render.jpg',                     'desc': 'The mother spider is the boss-type spider lurker in Spider Cave. Larger than its baby spider offspring, it serves as the primary threat of the cave.'},
    'ogreboss':              {'img': 'Klaww render.jpg',                                      'desc': "Klaww is a large lurker boss in The Precursor Legacy, operating from a volcanic section of Mountain Pass. He terrorized Rock Village by bombarding it with boulders before Jak confronted him."},
    'plant-boss':            {'img': 'Dark eco plant render.jpg',                             'desc': "The dark eco plant is a boss-level enemy in The Precursor Legacy — a massively mutated dark eco plant in the Forbidden Temple. It is the first boss in the game, though its defeat is entirely optional."},
    'puffer':                {'img': 'Puffer render.jpg',                                     'desc': 'The puffer, also known as a flying lurker, is an enemy in The Precursor Legacy, found in the lost Precursor city. It inflates to deal damage on contact.'},
    'quicksandlurker':       {'img': 'Quicksand lurker render.jpg',                           'desc': 'The quicksand lurker, also known as the fireball lurker, is an enemy in The Precursor Legacy. A small purple lurker indigenous to the mud ponds of Misty Island — it spits dark eco fireballs.'},
    'robotboss':             {'img': None,                                                    'desc': "Gol and Maia's Precursor robot is the final boss of The Precursor Legacy. An ancient Precursor war machine excavated and reactivated by the two dark eco sages to open the dark eco silos."},
    'rolling-lightning-mole':{'img': None,                                                    'desc': 'The lightning mole is a medium-sized subterranean animal in The Precursor Legacy. Scared out of their holes by a band of lurker robbers — Jak must herd them back into their holes in Precursor Basin.'},
    'rolling-robber':        {'img': 'Robber render.jpg',                                     'desc': "The robber is a lurker enemy in The Precursor Legacy, found in Precursor Basin. Robbers scared the rare lightning moles out of their underground holes — Jak must drive them off to restore order."},
    'snow-bunny':            {'img': 'Snow bunny render.jpg',                                 'desc': "The snow bunny is an enemy in The Precursor Legacy, encountered at Snowy Mountain and Gol and Maia's citadel. Small but aggressive cold-weather lurkers."},
    'snow-ram-boss':         {'img': 'Ice lurker render.jpg',                                 'desc': 'The ice lurker, also known as the ice monster, is an enemy in The Precursor Legacy, spawning from the slippery ice regions of Snowy Mountain.'},
    'swamp-bat':             {'img': 'Swamp bat render.jpg',                                  'desc': 'The swamp bat is an enemy in The Precursor Legacy, commonly found flying in swarms near Boggy Swamp. They follow set patrol paths through the air.'},
    'swamp-rat':             {'img': 'Swamp rat render.jpg',                                  'desc': 'The swamp rat, also known as the rat lurker, is an enemy in The Precursor Legacy. Mutated rats bearing lurker traits, dwelling in the poisonous mud of Boggy Swamp. They spawn from nest-like structures.'},
    'yeti':                  {'img': 'Yeti render.jpg',                                       'desc': "The yeti is the glacier variant of the babak lurker, encountered in The Precursor Legacy's colder regions. Larger and tougher than the standard babak."},
}

# Preview collection — loaded once at register(), cleared at unregister().
# bpy.utils.previews is the correct Blender API for custom images in panels.
# icon_id is just an integer texture lookup — zero overhead in draw().
_preview_collections: dict = {}


def _load_previews():
    """Load all enemy images into a PreviewCollection. Called from register()."""
    import bpy.utils.previews, os
    pcoll = bpy.utils.previews.new()
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'enemy-images')
    if os.path.isdir(img_dir):
        for etype, wiki in ENTITY_WIKI.items():
            fname = wiki.get('img')
            if not fname:
                continue
            fpath = os.path.join(img_dir, fname)
            if os.path.exists(fpath) and etype not in pcoll:
                pcoll.load(etype, fpath, 'IMAGE')
    _preview_collections['wiki'] = pcoll


def _unload_previews():
    """Remove preview collection. Called from unregister()."""
    import bpy.utils.previews
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()


def _draw_wiki_preview(layout, etype: str, ctx=None):
    """Draw image + description preview for the selected entity. Call from panel draw()."""
    wiki = ENTITY_WIKI.get(etype)
    if not wiki:
        return

    pcoll = _preview_collections.get('wiki')
    box = layout.box()

    # ── Image ─────────────────────────────────────────────────────────────
    # layout.label(icon_value=) is the standard Blender addon pattern for
    # custom images. scale_y enlarges the row so the icon renders big.
    if pcoll and etype in pcoll:
        icon_id = pcoll[etype].icon_id
        col = box.column(align=True)
        col.template_icon(icon_value=icon_id, scale=8.0)
    elif wiki.get('img'):
        box.label(text="Image not found — check enemy-images/ folder", icon="ERROR")
    else:
        box.label(text="No image available", icon="IMAGE_DATA")

    # ── Description ────────────────────────────────────────────────────────
    desc = wiki.get('desc', '').strip()
    if desc:
        col = box.column(align=True)
        words = desc.split()
        line, out = [], []
        for w in words:
            if sum(len(x) + 1 for x in line) + len(w) > 52:
                out.append(' '.join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            out.append(' '.join(line))
        for ln in out:
            col.label(text=ln)



def _build_entity_enum():
    # Tpage group display order — enemies are grouped so users know which share heap budget.
    # Mixing more than 2 groups in one scene risks OOM crash on level load.
    TPAGE_GROUP_ORDER = ["Beach", "Jungle", "Swamp", "Snow", "Sunken", "Ogre",
                         "Misty", "Maincave", "Robocave", "Village1", "Final", "Unknown"]
    cats = {}
    for etype, info in ENTITY_DEFS.items():
        cat = info["cat"]
        cats.setdefault(cat, []).append((etype, info))
    order = ["Enemies", "Bosses", "Props", "NPCs", "Pickups", "Platforms", "Objects", "Debug"]
    items, i = [], 0
    for cat in order:
        if cat not in cats:
            continue
        if cat == "Enemies":
            # Group enemies by tpage_group, in TPAGE_GROUP_ORDER order
            by_group = {}
            for etype, info in cats[cat]:
                g = info.get("tpage_group", "Unknown")
                by_group.setdefault(g, []).append((etype, info))
            for group in TPAGE_GROUP_ORDER:
                if group not in by_group:
                    continue
                for etype, info in sorted(by_group[group], key=lambda x: x[1]["label"]):
                    nav_safe    = info.get("nav_safe", True)
                    needs_path  = info.get("needs_path", False)
                    warn = "" if nav_safe else " [nav]"
                    if needs_path:
                        warn += " [path]"
                    tip = ENTITY_WIKI.get(etype, {}).get("desc", "") or etype
                    items.append((etype, f"[{group}] {info['label']}{warn}", tip, i))
                    i += 1
        else:
            for etype, info in sorted(cats[cat], key=lambda x: x[1]["label"]):
                nav_safe   = info.get("nav_safe", True)
                needs_path = info.get("needs_path", False)
                warn = "" if nav_safe else " [nav]"
                if needs_path:
                    warn += " [path]"
                tip = ENTITY_WIKI.get(etype, {}).get("desc", "") or etype
                items.append((etype, f"[{cat}] {info['label']}{warn}", tip, i))
                i += 1
    return items

ENTITY_ENUM_ITEMS = _build_entity_enum()

# Derived lookup sets — computed once from ENTITY_DEFS
NAV_UNSAFE_TYPES  = {e for e, info in ENTITY_DEFS.items() if not info.get("nav_safe", True)}
NEEDS_PATH_TYPES  = {e for e, info in ENTITY_DEFS.items() if info.get("needs_path", False)}
NEEDS_PATHB_TYPES = {e for e, info in ENTITY_DEFS.items() if info.get("needs_pathb", False)}
IS_PROP_TYPES     = {e for e, info in ENTITY_DEFS.items() if info.get("is_prop", False)}
ETYPE_AG          = {e: [info["ag"]] for e, info in ENTITY_DEFS.items() if info.get("ag")}

# ---------------------------------------------------------------------------
# ENTITY CODE DEPENDENCIES
# ---------------------------------------------------------------------------
# Each enemy whose code is NOT in GAME.CGO needs:
#   1. Its .o added to our custom DGO (.gd) so the engine can load it.
#   2. A goal-src line in game.gp so GOALC compiles it.
# Without this the type is undefined at runtime -> entity spawns as a do-nothing
# process (animates its idle but has zero AI, collision, or attack).
# Only babak is in GAME.CGO and always available; everything else needs this table.
#
# Format: etype -> {o, gc, dep}  |  "in_game_cgo": True -> already loaded, skip.

ETYPE_CODE = {
    # ---------------------------------------------------------------------------
    # HOW THIS TABLE WORKS (v9 fix):
    #
    # "in_game_cgo": True  → type lives in GAME.CGO, always loaded. Skip entirely.
    #
    # "o_only": True       → compiled .o lives in a vanilla level DGO (not GAME.CGO).
    #                        Vanilla game.gp already has the goal-src line so we must
    #                        NOT inject a duplicate (causes fatal "duplicate defstep").
    #                        We DO inject the .o into the custom DGO so the type is
    #                        available when the vanilla level DGO isn't loaded.
    #
    # Neither flag         → fully custom enemy. Inject both .o AND goal-src.
    #
    # Source file paths verified against goal_src/jak1/game.gp and dgos/*.gd
    # ---------------------------------------------------------------------------

    # GAME.CGO — always loaded, skip entirely
    "babak":           {"in_game_cgo": True},

    # Vanilla enemies — inject .o into custom DGO only, no goal-src
    "kermit":          {"o": "kermit.o",          "o_only": True},
    "hopper":          {"o": "hopper.o",           "o_only": True},
    "puffer":          {"o": "puffer.o",           "o_only": True},
    "bully":           {"o": "bully.o",            "o_only": True},
    "yeti":            {"o": "yeti.o",             "o_only": True},
    "snow-bunny":      {"o": "snow-bunny.o",       "o_only": True},
    "swamp-bat":       {"o": "swamp-bat.o",        "o_only": True},
    "swamp-rat":       {"o": "swamp-rat.o",        "o_only": True},
    "gnawer":          {"o": "gnawer.o",           "o_only": True},
    "lurkercrab":      {"o": "lurkercrab.o",       "o_only": True},
    "lurkerworm":      {"o": "lurkerworm.o",       "o_only": True},
    "lurkerpuppy":     {"o": "lurkerpuppy.o",      "o_only": True},
    "flying-lurker":   {"o": "flying-lurker.o",    "o_only": True},
    "double-lurker":   {"o": "double-lurker.o",    "o_only": True},
    "driller-lurker":  {"o": "driller-lurker.o",   "o_only": True},
    "quicksandlurker": {"o": "quicksandlurker.o",  "o_only": True},
    "junglesnake":     {"o": "junglesnake.o",      "o_only": True},
    "muse":            {"o": "muse.o",             "o_only": True},
    "bonelurker":      {"o": "bonelurker.o",       "o_only": True},  # ⚠ known crash - see open questions

    # NPCs — vanilla, inject .o only
    "flutflut":        {"o": "flutflut.o",         "o_only": True},
    "billy":           {"o": "billy.o",            "o_only": True},
    "yakow":           {"o": "yakow.o",            "o_only": True},
    "farmer":          {"o": "farmer.o",           "o_only": True},
    "fisher":          {"o": "fisher.o",           "o_only": True},
    "mayor":           {"o": "mayor.o",            "o_only": True},
    "sculptor":        {"o": "sculptor.o",         "o_only": True},
    "explorer":        {"o": "explorer.o",         "o_only": True},
    "geologist":       {"o": "geologist.o",        "o_only": True},
    "warrior":         {"o": "warrior.o",          "o_only": True},
    "gambler":         {"o": "gambler.o",          "o_only": True},
    "ogreboss":        {"o": "ogreboss.o",         "o_only": True},
}


# ---------------------------------------------------------------------------
# ENTITY TPAGE DEPENDENCIES
# ---------------------------------------------------------------------------
# Each art group needs its source level's tpages in the DGO so the GOAL
# texture system can resolve texture IDs at runtime.  Without these, the
# merc renderer dereferences null and crashes when the entity is drawn.
# Tpage lists match the order used in each vanilla level's .gd file.
#
# beach tpages:  212, 214, 213, 215
# ---------------------------------------------------------------------------
# All tpage numbers verified against copy-textures calls in goal_src/jak1/game.gp.
# Order within each list must match the vanilla level's copy-textures order.
# HEAP WARNING: the game kheap has ~4MB free during level load. Each tpage set
# is ~200-250KB. Mixing more than ~2 source levels at once risks OOM crash.
# The error looks like: kmalloc: !alloc mem data-segment (50480 bytes)
# ---------------------------------------------------------------------------

BEACH_TPAGES   = ["tpage-212.go",  "tpage-214.go",  "tpage-213.go",  "tpage-215.go"]              # bea.gd
JUNGLE_TPAGES  = ["tpage-385.go",  "tpage-531.go",  "tpage-386.go",  "tpage-388.go"]              # jun.gd
SWAMP_TPAGES   = ["tpage-358.go",  "tpage-659.go",  "tpage-629.go",  "tpage-630.go"]              # swa.gd
SNOW_TPAGES    = ["tpage-710.go",  "tpage-842.go",  "tpage-711.go",  "tpage-712.go"]              # sno.gd
SUNKEN_TPAGES  = ["tpage-661.go",  "tpage-663.go",  "tpage-714.go",  "tpage-662.go"]              # sun.gd  (bully, double-lurker, puffer)
SUB_TPAGES     = ["tpage-163.go",  "tpage-164.go",  "tpage-166.go",  "tpage-162.go"]              # sub.gd  (sunken city B)
CAVE_TPAGES    = ["tpage-1313.go", "tpage-1315.go", "tpage-1314.go", "tpage-1312.go"]             # mai.gd  (gnawer, driller-lurker, dark-crystal, baby-spider, mother-spider)
ROBOCAVE_TPAGES= ["tpage-1318.go", "tpage-1319.go", "tpage-1317.go", "tpage-1316.go"]             # rob.gd  (cavecrusher)
DARK_TPAGES    = ["tpage-1306.go", "tpage-1307.go", "tpage-1305.go", "tpage-1304.go"]             # dar.gd  (darkcave spiders — NOT maincave)
OGRE_TPAGES    = ["tpage-875.go",  "tpage-967.go",  "tpage-884.go",  "tpage-1117.go"]             # ogr.gd  (flying-lurker)
MISTY_TPAGES   = ["tpage-516.go",  "tpage-521.go",  "tpage-518.go",  "tpage-520.go"]              # mis.gd  (quicksandlurker, muse, bonelurker, balloonlurker)

ETYPE_TPAGES = {
    # Beach (bea.gd)
    "babak":           BEACH_TPAGES,
    "lurkercrab":      BEACH_TPAGES,
    "lurkerpuppy":     BEACH_TPAGES,
    "lurkerworm":      BEACH_TPAGES,
    # Jungle (jun.gd)
    "hopper":          JUNGLE_TPAGES,
    "junglesnake":     JUNGLE_TPAGES,
    # Swamp (swa.gd)
    "kermit":          SWAMP_TPAGES,
    "swamp-bat":       SWAMP_TPAGES,
    "swamp-rat":       SWAMP_TPAGES,
    # Snow (sno.gd)
    "yeti":            SNOW_TPAGES,
    "snow-bunny":      SNOW_TPAGES,
    # Sunken A (sun.gd)
    "double-lurker":   SUNKEN_TPAGES,
    "puffer":          SUNKEN_TPAGES,
    "bully":           SUNKEN_TPAGES,
    # Ogre (ogr.gd)
    "flying-lurker":   OGRE_TPAGES,
    # Maincave (mai.gd) — dark-crystal, gnawer, driller-lurker, baby-spider, mother-spider
    "dark-crystal":    CAVE_TPAGES,
    "gnawer":          CAVE_TPAGES,
    "driller-lurker":  CAVE_TPAGES,
    "baby-spider":     CAVE_TPAGES,
    "mother-spider":   CAVE_TPAGES,
    # Robocave (rob.gd) — cavecrusher
    "cavecrusher":     ROBOCAVE_TPAGES,
    # Darkcave (dar.gd) — NOTE: different from maincave; spiders from darkcave use these
    # Misty (mis.gd)
    "quicksandlurker": MISTY_TPAGES,
    "muse":            MISTY_TPAGES,
    "bonelurker":      MISTY_TPAGES,
    "balloonlurker":   MISTY_TPAGES,
}

def needed_tpages(actors):
    """Return de-duplicated ordered list of tpage .go files needed for placed entities."""
    seen, r = set(), []
    for a in actors:
        for tp in ETYPE_TPAGES.get(a["etype"], []):
            if tp not in seen:
                seen.add(tp)
                r.append(tp)
    return r


# ---------------------------------------------------------------------------
# NAV MESH — geometry processing and GOAL code generation
# ---------------------------------------------------------------------------

def _navmesh_compute(world_tris):
    """
    world_tris: list of 3-tuples of (x,y,z) world-space points (already in game coords)
    Returns dict with all data needed to write the GOAL nav-mesh struct.
    """
    import math
    EPS = 0.01

    verts = []
    def find_or_add(pt):
        for i, v in enumerate(verts):
            if abs(v[0]-pt[0]) < EPS and abs(v[1]-pt[1]) < EPS and abs(v[2]-pt[2]) < EPS:
                return i
        verts.append(pt)
        return len(verts) - 1

    polys = []
    for tri in world_tris:
        i0 = find_or_add(tri[0])
        i1 = find_or_add(tri[1])
        i2 = find_or_add(tri[2])
        if len({i0, i1, i2}) == 3:
            polys.append((i0, i1, i2))

    N = len(polys)
    V = len(verts)
    if N == 0 or V == 0:
        return None

    ox = sum(v[0] for v in verts) / V
    oy = sum(v[1] for v in verts) / V
    oz = sum(v[2] for v in verts) / V
    rel = [(v[0]-ox, v[1]-oy, v[2]-oz) for v in verts]
    max_dist = max(math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in rel)
    bounds_r = max_dist + 5.0

    def edge_key(a, b): return (min(a,b), max(a,b))
    edge_to_polys = {}
    for pi, (v0,v1,v2) in enumerate(polys):
        for ea, eb in [(v0,v1),(v1,v2),(v2,v0)]:
            edge_to_polys.setdefault(edge_key(ea,eb), []).append(pi)

    adj = []
    for pi, (v0,v1,v2) in enumerate(polys):
        neighbors = []
        for ea, eb in [(v0,v1),(v1,v2),(v2,v0)]:
            others = [p for p in edge_to_polys.get(edge_key(ea,eb),[]) if p != pi]
            neighbors.append(others[0] if others else 0xFF)
        adj.append(tuple(neighbors))

    INF = 9999
    def bfs_from(src):
        dist = [INF] * N
        came = [None] * N
        dist[src] = 0
        q = [src]; qi = 0
        while qi < len(q):
            cur = q[qi]; qi += 1
            for slot, nb in enumerate(adj[cur]):
                if nb != 0xFF and dist[nb] == INF:
                    dist[nb] = dist[cur] + 1
                    came[nb] = (cur, slot)
                    q.append(nb)
        next_hop = [3] * N
        for dst in range(N):
            if dst == src or dist[dst] == INF:
                continue
            node = dst
            while came[node][0] != src:
                node = came[node][0]
            next_hop[dst] = came[node][1]
        return next_hop

    route_table = [bfs_from(i) for i in range(N)]
    total_bits = N * N * 2
    total_bytes = (total_bits + 7) // 8
    route_bytes = bytearray(total_bytes)
    for frm in range(N):
        for to in range(N):
            val = route_table[frm][to] & 3
            bit_idx = (frm * N + to) * 2
            byte_idx = bit_idx // 8
            bit_off = bit_idx % 8
            route_bytes[byte_idx] |= (val << bit_off)
    total_vec4ub = (total_bytes + 3) // 4
    padded = route_bytes + bytearray(total_vec4ub * 4 - len(route_bytes))
    vec4ubs = [tuple(padded[i*4:(i+1)*4]) for i in range(total_vec4ub)]

    # Build BVH nodes — required by find-poly-fast (called during enemy chase).
    # Without nodes, recursive-inside-poly dereferences null -> crash.
    # For small meshes we use a simple flat structure:
    # One root node per group of <=4 polys, so ceil(N/4) leaf nodes,
    # plus one branch node if more than one leaf.
    # For our typical small meshes (2-16 polys) one leaf node is enough.
    # Leaf node: type != 0, num-tris stored in low 16 bits of left-offset field.
    # first-tris: up to 4 poly indices packed in 4 uint8 slots.
    # last-tris:  next 4 poly indices (for polys 5-8).
    # center/radius: AABB of all verts in the node (in local/rel coords).
    import math as _math

    # Compute AABB of all relative verts for the node bounding box
    xs = [v[0] for v in rel]; ys = [v[1] for v in rel]; zs = [v[2] for v in rel]
    cx = (_math.fsum(xs)) / V
    cy = (_math.fsum(ys)) / V
    cz = (_math.fsum(zs)) / V
    rx = max(abs(x - cx) for x in xs) + 1.0  # 1m padding
    ry = max(abs(y - cy) for y in ys) + 5.0  # extra Y padding for height tolerance
    rz = max(abs(z - cz) for z in zs) + 1.0

    # Build flat list of leaf nodes — one per group of 4 polys
    # Each leaf: (cx, cy, cz, rx, ry, rz, [poly_idx...])
    nodes = []
    for start in range(0, N, 4):
        chunk = list(range(start, min(start+4, N)))
        # AABB for this chunk's verts
        chunk_verts = []
        for pi in chunk:
            for vi in polys[pi]:
                chunk_verts.append(rel[vi])
        if chunk_verts:
            cxs = [v[0] for v in chunk_verts]
            cys = [v[1] for v in chunk_verts]
            czs = [v[2] for v in chunk_verts]
            ncx = (_math.fsum(cxs)) / len(cxs)
            ncy = (_math.fsum(cys)) / len(cys)
            ncz = (_math.fsum(czs)) / len(czs)
            nrx = max(abs(x - ncx) for x in cxs) + 1.0
            nry = max(abs(y - ncy) for y in cys) + 5.0
            nrz = max(abs(z - ncz) for z in czs) + 1.0
        else:
            ncx, ncy, ncz, nrx, nry, nrz = cx, cy, cz, rx, ry, rz
        nodes.append((ncx, ncy, ncz, nrx, nry, nrz, chunk))

    return {
        'origin': (ox, oy, oz), 'bounds_r': bounds_r,
        'verts_rel': rel, 'polys': polys, 'adj': adj,
        'vec4ubs': vec4ubs, 'poly_count': N, 'vertex_count': V,
        'nodes': nodes,
        'node_aabb': (cx, cy, cz, rx, ry, rz),
    }


def _navmesh_to_goal(mesh, actor_aid):
    ox, oy, oz = mesh['origin']
    br = mesh['bounds_r']
    N = mesh['poly_count']
    V = mesh['vertex_count']

    def gx(n):
        """Format integer as GOAL hex literal: #x0, #xff, #x1a etc."""
        return f"#x{n:x}"

    def gadj(n):
        """Format adjacency index — #xff for boundary, else #xNN."""
        return "#xff" if n == 0xFF else f"#x{n:x}"

    L = []
    L.append(f"    (({actor_aid})")
    L.append(f"      (set! (-> this nav-mesh)")
    L.append(f"        (new 'static 'nav-mesh")
    L.append(f"          :bounds (new 'static 'sphere :x (meters {ox:.4f}) :y (meters {oy:.4f}) :z (meters {oz:.4f}) :w (meters {br:.4f}))")
    L.append(f"          :origin (new 'static 'vector :x (meters {ox:.4f}) :y (meters {oy:.4f}) :z (meters {oz:.4f}) :w 1.0)")
    node_list = mesh.get('nodes', [])
    L.append(f"          :node-count {len(node_list)}")
    L.append(f"          :nodes (new 'static 'inline-array nav-node {len(node_list)}")
    for ncx, ncy, ncz, nrx, nry, nrz, chunk in node_list:
        # Leaf node: type=1, num-tris in lower 16 of left-offset field
        # first-tris: poly indices 0-3, last-tris: poly indices 4-7
        ft = chunk[:4] + [0] * (4 - len(chunk[:4]))
        lt = (chunk[4:8] if len(chunk) > 4 else []) + [0] * (4 - len(chunk[4:8]) if len(chunk) > 4 else 4)
        L.append(f"            (new 'static 'nav-node")
        L.append(f"              :center-x (meters {ncx:.4f}) :center-y (meters {ncy:.4f}) :center-z (meters {ncz:.4f})")
        L.append(f"              :type #x1 :parent-offset #x0")
        L.append(f"              :radius-x (meters {nrx:.4f}) :radius-y (meters {nry:.4f}) :radius-z (meters {nrz:.4f})")
        L.append(f"              :num-tris {len(chunk)}")
        L.append(f"              :first-tris (new 'static 'array uint8 4 {gx(ft[0])} {gx(ft[1])} {gx(ft[2])} {gx(ft[3])})")
        L.append(f"              :last-tris  (new 'static 'array uint8 4 {gx(lt[0])} {gx(lt[1])} {gx(lt[2])} {gx(lt[3])})")
        L.append(f"            )")
    L.append(f"          )")
    L.append(f"          :vertex-count {V}")
    L.append(f"          :vertex (new 'static 'inline-array nav-vertex {V}")
    for vx, vy, vz in mesh['verts_rel']:
        L.append(f"            (new 'static 'nav-vertex :x (meters {vx:.4f}) :y (meters {vy:.4f}) :z (meters {vz:.4f}) :w 1.0)")
    L.append(f"          )")
    L.append(f"          :poly-count {N}")
    L.append(f"          :poly (new 'static 'inline-array nav-poly {N}")
    for i, ((v0,v1,v2),(a0,a1,a2)) in enumerate(zip(mesh['polys'], mesh['adj'])):
        L.append(f"            (new 'static 'nav-poly :id {gx(i)} :vertex (new 'static 'array uint8 3 {gx(v0)} {gx(v1)} {gx(v2)}) :adj-poly (new 'static 'array uint8 3 {gadj(a0)} {gadj(a1)} {gadj(a2)}))")
    L.append(f"          )")
    rc = len(mesh['vec4ubs'])
    L.append(f"          :route (new 'static 'inline-array vector4ub {rc}")
    for b0,b1,b2,b3 in mesh['vec4ubs']:
        L.append(f"            (new 'static 'vector4ub :data (new 'static 'array uint8 4 {gx(b0)} {gx(b1)} {gx(b2)} {gx(b3)}))")
    L.append(f"          )")
    L.append(f"        )")
    L.append(f"      )")
    L.append(f"    )")
    return "\n".join(L)


def _canonical_actor_objects(scene):
    """
    Single source of truth for actor ordering and AID assignment.
    Both collect_actors and _collect_navmesh_actors must use this so
    idx values — and therefore AIDs — are guaranteed to match.
    Sorted by name for full determinism regardless of Blender object order.
    Excludes waypoints (_wp_, _wpb_) and non-EMPTY objects.
    """
    actors = []
    for o in scene.objects:
        if not (o.name.startswith("ACTOR_") and o.type == "EMPTY"):
            continue
        if "_wp_" in o.name or "_wpb_" in o.name:
            continue
        if len(o.name.split("_", 2)) < 3:
            continue
        actors.append(o)
    actors.sort(key=lambda o: o.name)
    return actors


def _collect_navmesh_actors(scene):
    """
    Returns list of (actor_aid, mesh_data) for actors linked to navmeshes.
    actor_aid = base_id + 1-based index in canonical actor order,
    matching exactly what collect_actors and the JSONC builder assign.
    """
    base_id = scene.og_props.base_id
    ordered = _canonical_actor_objects(scene)

    result = []
    for idx, o in enumerate(ordered):
        nm_name = o.get("og_navmesh_link", "")
        if not nm_name:
            continue
        nm_obj = scene.objects.get(nm_name)
        if not nm_obj or nm_obj.type != "MESH":
            continue

        actor_aid = base_id + idx + 1  # base_id+1 = first actor AID
        log(f"[navmesh] {o.name} idx={idx} aid={actor_aid} -> {nm_name}")

        nm_obj.data.calc_loop_triangles()
        mat = nm_obj.matrix_world
        tris = []
        for tri in nm_obj.data.loop_triangles:
            pts = []
            for vi in tri.vertices:
                co = mat @ nm_obj.data.vertices[vi].co
                # Blender Y-up -> game coords: game_x=bl_x, game_y=bl_z, game_z=-bl_y
                pts.append((round(co.x, 4), round(co.z, 4), round(-co.y, 4)))
            tris.append(tuple(pts))

        mesh_data = _navmesh_compute(tris)
        if mesh_data:
            result.append((actor_aid, mesh_data))
            log(f"[navmesh]   {mesh_data['poly_count']} polys OK")
        else:
            log(f"[navmesh]   WARNING: navmesh compute returned nothing for {o.name}")

    return result


def write_gc(name):
    """Write the minimal obs.gc stub for the level."""
    d = _goal_src() / "levels" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-obs.gc"
    p.write_text(f";;-*-Lisp-*-\n(in-package goal)\n;; {name}-obs.gc\n")
    log(f"Wrote {p}")


# ---------------------------------------------------------------------------
# ADDON PREFERENCES
# ---------------------------------------------------------------------------

class OGPreferences(AddonPreferences):
    bl_idname = __name__

    exe_path: StringProperty(
        name="EXE folder",
        description="Folder containing gk.exe and goalc.exe",
        subtype="DIR_PATH",
        default=r"C:\Users\John\Documents\JakAndDaxter\versions\official\v0.2.29",
    )
    data_path: StringProperty(
        name="Data folder",
        description="Folder containing data/goal_src  (usually active/jak1)",
        subtype="DIR_PATH",
        default=r"C:\Users\John\Documents\JakAndDaxter\active\jak1",
    )

    def draw(self, ctx):
        self.layout.label(text="EXE folder — contains gk.exe and goalc.exe:")
        self.layout.prop(self, "exe_path", text="")
        self.layout.label(text="Data folder — contains data/goal_src (e.g. active/jak1):")
        self.layout.prop(self, "data_path", text="")

# ---------------------------------------------------------------------------
# PATH HELPERS
# ---------------------------------------------------------------------------

GOALC_PORT    = 8182   # 8181 permanently held by 3dxnlserver.exe (3Dconnexion SpaceMouse driver)
GOALC_TIMEOUT = 120

def _find_free_nrepl_port(start=8182, attempts=10):
    """Find a free TCP port for GOALC's nREPL server.

    Strategy: try to CONNECT to each port. If connection is refused, nothing
    is listening there — it's free. If it connects or gets any other response,
    something is already using it (e.g. 3dxnlserver.exe on 8181).

    This avoids the need to bind 0.0.0.0 (which needs admin on some Windows
    configs) and accurately detects ports held on any interface.
    """
    import socket as _socket
    for port in range(start, start + attempts):
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=0.3):
                # Something answered — port is in use
                log(f"[nREPL] port {port} in use, trying next...")
        except ConnectionRefusedError:
            # Nothing listening — port is free
            log(f"[nREPL] free port found: {port}")
            return port
        except OSError:
            # Timeout or other error — treat as in use to be safe
            log(f"[nREPL] port {port} unclear, trying next...")
    log(f"[nREPL] no free port in {start}-{start+attempts-1}, defaulting to {start+1}")
    return start + 1

def _strip(p): return p.strip().rstrip("\\").rstrip("/")

def _exe_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.exe_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _data_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.data_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _gk():         return _exe_root() / "gk.exe"
def _goalc():      return _exe_root() / "goalc.exe"
def _data():       return _data_root() / "data"
def _levels_dir(): return _data() / "custom_assets" / "jak1" / "levels"
def _goal_src():   return _data() / "goal_src" / "jak1"
def _level_info(): return _goal_src() / "engine" / "level" / "level-info.gc"
def _game_gp():    return _goal_src() / "game.gp"
def _ldir(name):   return _levels_dir() / name
def _entity_gc():  return _goal_src() / "engine" / "entity" / "entity.gc" 

def _lname(ctx):   return ctx.scene.og_props.level_name.strip().lower().replace(" ","-")
def _nick(n):      return n.replace("-","")[:3].lower()
def _iso(n):       return n.replace("-","").upper()[:8]
def log(m):        print(f"[OpenGOAL] {m}")

# ---------------------------------------------------------------------------
# SCENE PROPERTIES
# ---------------------------------------------------------------------------

class OGProperties(PropertyGroup):
    level_name:  StringProperty(name="Name", description="Lowercase with dashes", default="my-level")
    entity_type: EnumProperty(name="Entity Type", items=ENTITY_ENUM_ITEMS)
    crate_type:  EnumProperty(name="Crate Type",  items=CRATE_ITEMS)
    nav_radius:  FloatProperty(name="Nav Sphere Radius (m)", default=6.0, min=0.5, max=50.0,
                               description="Fallback navmesh sphere radius for nav-unsafe enemies")
    base_id:     IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000,
                             description="Starting actor ID for this level. Must be unique across all custom levels to avoid ghost entity spawns.")
    lightbake_samples: IntProperty(name="Sample Count", default=128, min=1, max=4096,
                                   description="Number of Cycles render samples used when baking lighting to vertex colors")

# ---------------------------------------------------------------------------
# PROCESS MANAGEMENT
# ---------------------------------------------------------------------------

def _process_running(exe_name):
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/fi", f"imagename eq {exe_name}"],
                               capture_output=True, text=True)
            return exe_name.lower() in r.stdout.lower()
        else:
            r = subprocess.run(["pgrep", "-f", exe_name], capture_output=True, text=True)
            return bool(r.stdout.strip())
    except Exception:
        return False

def _kill_process(exe_name):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/im", exe_name], capture_output=True)
        else:
            subprocess.run(["pkill", "-f", exe_name], capture_output=True)
        time.sleep(0.8)
    except Exception:
        pass

def kill_gk():
    _kill_process("gk.exe")
    time.sleep(0.5)

def kill_goalc():
    _kill_process("goalc.exe")
    time.sleep(0.5)
    # On Windows, SO_EXCLUSIVEADDRUSE holds port 8181 until the process fully
    # exits. Poll until the port is free so the next launch_goalc() doesn't
    # hit "nREPL: DISABLED" from a bind() on a not-yet-released port.
    for _ in range(20):
        try:
            with socket.create_connection(("localhost", GOALC_PORT), timeout=0.3):
                pass
            time.sleep(0.3)  # port still held, keep waiting
        except (ConnectionRefusedError, OSError):
            break  # port is free
# ---------------------------------------------------------------------------
# GOALC / nREPL
# ---------------------------------------------------------------------------

def goalc_send(cmd, timeout=GOALC_TIMEOUT):
    """Send a GOAL expression to the nREPL server and return the response.

    Wire format (from common/repl/nrepl/ReplClient.cpp):
      [u32 length LE][u32 type=10 LE][utf-8 string]
    Sending raw text causes "Bad message, aborting the read" errors.
    """
    import struct
    EVAL_TYPE = 10
    try:
        with socket.create_connection(("localhost", GOALC_PORT), timeout=10) as s:
            encoded = cmd.encode("utf-8")
            header = struct.pack("<II", len(encoded), EVAL_TYPE)
            s.sendall(header + encoded)
            chunks = []
            s.settimeout(timeout)
            while True:
                try:
                    c = s.recv(4096)
                    if not c: break
                    chunks.append(c)
                    if b"g >" in c or b"g  >" in c: break
                except socket.timeout: break
            return b"".join(chunks).decode(errors="replace")
    except ConnectionRefusedError: return None
    except Exception as e: return f"ERROR:{e}"

def goalc_ok():
    return goalc_send("(+ 1 1)", timeout=3) is not None

USER_NAME = "blender"

def _user_base(): return _data_root() / "data" / "goal_src" / "user"
def _user_dir():
    d = _user_base() / USER_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_startup_gc(commands):
    base = _user_base()
    base.mkdir(parents=True, exist_ok=True)
    (base / "user.txt").write_text(USER_NAME)
    udir = _user_dir()
    (udir / "user.gc").write_text(
        ";; Auto-generated by OpenGOAL Tools Blender addon\n"
        "(define-extern bg (function symbol int))\n"
        "(define-extern bg-custom (function symbol object))\n"
        "(define-extern *artist-all-visible* symbol)\n"
    )
    p = udir / "startup.gc"
    p.write_text("\n".join(commands) + "\n")
    log(f"Wrote startup.gc: {commands}")

def launch_goalc(wait_for_nrepl=False):
    global GOALC_PORT
    exe = _goalc()
    if not exe.exists():
        return False, f"goalc.exe not found at {exe}"
    # Caller is responsible for kill_goalc() + port-free wait before calling here.
    # Do NOT kill internally — it would reset the port-free polling the caller did.
    # Find a free port before launching so goalc doesn't show "nREPL: DISABLED".
    GOALC_PORT = _find_free_nrepl_port(start=8182)  # skip 8181 (3Dconnexion SpaceMouse)
    log(f"[nREPL] launching GOALC on port {GOALC_PORT}")
    try:
        data_dir = str(_data())
        cmd = [str(exe), "--user-auto", "--game", "jak1", "--proj-path", data_dir,
               "--port", str(GOALC_PORT)]
        if os.name == "nt":
            proc = subprocess.Popen(cmd, cwd=str(_exe_root()),
                                    creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd, cwd=str(_exe_root()))
        log(f"launch_goalc: pid={proc.pid}")
        if wait_for_nrepl:
            for _ in range(60):
                time.sleep(0.5)
                if goalc_ok():
                    return True, "GOALC started with nREPL"
            return False, "GOALC started but nREPL not available"
        return True, f"GOALC launched (pid={proc.pid})"
    except Exception as e:
        return False, str(e)

def launch_gk():
    exe = _gk()
    if not exe.exists(): return False, f"Not found: {exe}"
    # Kill existing GK — no window stacking
    if _process_running("gk.exe"):
        log("launch_gk: killing existing GK")
        kill_gk()
    try:
        data_dir = str(_data())
        subprocess.Popen([str(exe), "-v", "--game", "jak1",
                          "--proj-path", data_dir,
                          "--", "-boot", "-fakeiso", "-debug"],
                         cwd=str(_exe_root()))
        return True, "gk launched"
    except Exception as e:
        return False, str(e)

# ---------------------------------------------------------------------------
# SCENE PARSING
# ---------------------------------------------------------------------------

def collect_spawns(scene):
    out = []
    for o in scene.objects:
        if o.name.startswith("SPAWN_") and o.type == "EMPTY":
            uid = o.name[6:] or "start"
            l = o.location
            out.append({"name":uid, "x":l.x, "y":l.z, "z":-l.y})
    return out

def collect_actors(scene):
    """Build actor list from ACTOR_ empties.

    Nav-unsafe enemies (move-to-ground=True, hover-if-no-ground=False) will
    crash the game when they try to resolve a navmesh and find a null pointer.
    Workaround: inject a 'nav-mesh-sphere' res-lump tag on each such actor.
    This tells the nav-control initialiser to use *default-nav-mesh* (a tiny
    stub mesh in navigate.gc) instead of dereferencing null.  The enemy will
    stand, idle, and notice Jak but won't properly pathfind — that requires a
    real navmesh (future work).
    """
    out = []
    for o in _canonical_actor_objects(scene):
        p = o.name.split("_", 2)
        etype, uid = p[1], p[2]
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)

        lump = {"name": f"{etype}-{uid}"}

        if etype == "fuel-cell":
            lump["eco-info"] = ["cell-info", "(game-task none)"]
        elif etype == "buzzer":
            lump["eco-info"] = ["buzzer-info", "(game-task none)", 1]
        elif etype == "crate":
            ct = o.get("og_crate_type", "steel")
            lump["crate-type"] = f"'{ct}"
            lump["eco-info"] = ["eco-info", "(pickup-type money)", 3]
        elif etype == "money":
            lump["eco-info"] = ["eco-info", "(pickup-type money)", 1]

        einfo = ENTITY_DEFS.get(etype, {})

        # Collect waypoints for this actor (named ACTOR_<etype>_<uid>_wp_00 etc.)
        wp_prefix = o.name + "_wp_"
        wp_objects = sorted(
            [sc_obj for sc_obj in bpy.data.objects
             if sc_obj.name.startswith(wp_prefix) and sc_obj.type == "EMPTY"],
            key=lambda sc_obj: sc_obj.name
        )
        path_pts = []
        for wp in wp_objects:
            wl = wp.location
            path_pts.append([round(wl.x, 4), round(wl.z, 4), round(-wl.y, 4), 1.0])

        # ── Nav-enemy workaround (nav_safe=False) ────────────────────────────
        # These extend nav-enemy. Without a real navmesh they idle forever.
        # Inject nav-mesh-sphere so the engine doesn't dereference null.
        # entity.gc is also patched separately with a real navmesh if linked.
        if etype in NAV_UNSAFE_TYPES:
            nav_r = float(o.get("og_nav_radius", 6.0))
            if path_pts:
                first = path_pts[0]
                lump["nav-mesh-sphere"] = ["vector4m", [first[0], first[1], first[2], nav_r]]
                log(f"  [nav+path] {o.name}  {len(wp_objects)} waypoints  sphere r={nav_r}m")
            else:
                lump["nav-mesh-sphere"] = ["vector4m", [gx, gy, gz, nav_r]]
                log(f"  [nav-workaround] {o.name}  sphere r={nav_r}m  (no waypoints - will idle)")

        # ── Path lump (needs_path=True) ───────────────────────────────────────
        # process-drawable enemies that error without a path lump.
        # Also used by nav-enemies that patrol (snow-bunny, muse etc.).
        # Waypoints tagged _wp_00, _wp_01 ... drive this lump.
        # For needs_path enemies with no waypoints we log a warning — the level
        # will likely crash or error at runtime without at least 1 waypoint.
        if einfo.get("needs_path") or (etype in NAV_UNSAFE_TYPES and path_pts):
            if path_pts:
                lump["path"] = ["vector4m"] + path_pts
                log(f"  [path] {o.name}  {len(path_pts)} points")
            elif einfo.get("needs_path"):
                log(f"  [WARNING] {o.name} needs a path but has no waypoints — will crash/error at runtime!")

        # ── Second path lump (needs_pathb=True — swamp-bat only) ─────────────
        # swamp-bat reads 'pathb' for its second patrol route for bat slaves.
        # Tag secondary waypoints as ACTOR_swamp-bat_<uid>_wpb_00 etc.
        if einfo.get("needs_pathb"):
            wpb_prefix = o.name + "_wpb_"
            wpb_objects = sorted(
                [sc_obj for sc_obj in bpy.data.objects
                 if sc_obj.name.startswith(wpb_prefix) and sc_obj.type == "EMPTY"],
                key=lambda sc_obj: sc_obj.name
            )
            pathb_pts = []
            for wp in wpb_objects:
                wl = wp.location
                pathb_pts.append([round(wl.x, 4), round(wl.z, 4), round(-wl.y, 4), 1.0])
            if pathb_pts:
                lump["pathb"] = ["vector4m"] + pathb_pts
                log(f"  [pathb] {o.name}  {len(pathb_pts)} points")
            else:
                log(f"  [WARNING] {o.name} (swamp-bat) needs 'pathb' waypoints (_wpb_00, _wpb_01 ...) — will error at runtime!")

        # Bsphere radius controls vis-culling distance.  nav-enemy run-logic?
        # only processes AI/collision events when draw-status was-drawn is set,
        # which requires the bsphere to pass the renderer's cull test.
        # Custom levels lack a proper BSP vis system, so enemies need a large
        # bsphere (120m) to guarantee was-drawn is always true in a play area.
        # Pickups / static props can stay small.
        info     = ENTITY_DEFS.get(etype, {})
        is_enemy = info.get("cat") in ("Enemies", "Bosses")
        bsph_r   = 10.0  # Rockpool uses 10m for all entities; 120m caused merc renderer crashes

        # Add vis-dist for enemies so they stay active at reasonable range.
        # Rockpool uses 50m on distant babaks; we use 200m as a generous default.
        if is_enemy and "vis-dist" not in lump:
            lump["vis-dist"] = ["meters", 200.0]

        out.append({
            "trans":     [gx, gy, gz],
            "etype":     etype,
            "game_task": "(game-task none)",
            "quat":      [0, 0, 0, 1],
            "vis_id":    0,
            "bsphere":   [gx, gy, gz, bsph_r],
            "lump":      lump,
        })
    return out

def collect_ambients(scene):
    out = []
    for o in scene.objects:
        if not (o.name.startswith("AMBIENT_") and o.type == "EMPTY"):
            continue
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)
        out.append({
            "trans": [gx, gy, gz, 10.0], "bsphere": [gx, gy, gz, 15.0],
            "lump": {"name": o.name[8:].lower() or "ambient",
                     "type": "'hint",
                     "text-id": ["enum-uint32", "(text-id fuel-cell)"],
                     "play-mode": "'notice"},
        })
    return out

def collect_nav_mesh_geometry(scene, level_name):
    """Collect geometry tagged og_navmesh=True for future navmesh generation.

    Full navmesh injection into the level BSP is not yet implemented in the
    OpenGOAL custom level pipeline (Entity.cpp writes a null pointer for the
    nav-mesh field).  This function gathers the data so it's ready when
    engine-side support lands.
    """
    tris = []
    for o in scene.objects:
        if not (o.type == "MESH" and o.get("og_navmesh", False)):
            continue
        mesh = o.data
        mat  = o.matrix_world
        verts = [mat @ v.co for v in mesh.vertices]
        mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            a, b, c = [verts[tri.vertices[i]] for i in range(3)]
            tris.append((
                (round(a.x,4), round(a.z,4), round(-a.y,4)),
                (round(b.x,4), round(b.z,4), round(-b.y,4)),
                (round(c.x,4), round(c.z,4), round(-c.y,4)),
            ))
    log(f"[navmesh] collected {len(tris)} tris from '{level_name}' "
        f"(injection pending engine support)")
    return tris

def needed_ags(actors):
    seen, r = set(), []
    for a in actors:
        for g in ETYPE_AG.get(a["etype"], []):
            if g and g not in seen:
                seen.add(g); r.append(g)
    return r

def needed_code(actors):
    """Return list of (o_file, gc_path, dep) for enemy types not in GAME.CGO.

    o_only=True entries: inject .o into custom DGO only — vanilla game.gp already
    has the goal-src line so we must not duplicate it (causes 'duplicate defstep').

    Returns list of (o_file, gc_path_or_None, dep_or_None).
    write_gd() uses o_file for DGO injection.
    patch_game_gp() skips entries where gc_path is None.
    """
    seen, r = set(), []
    for a in actors:
        etype = a["etype"]
        info = ETYPE_CODE.get(etype)
        if not info or info.get("in_game_cgo"):
            continue
        o = info["o"]
        if o not in seen:
            seen.add(o)
            if info.get("o_only"):
                r.append((o, None, None))
            else:
                r.append((o, info["gc"], info.get("dep", "process-drawable")))
    return r

# ---------------------------------------------------------------------------
# FILE WRITERS
# ---------------------------------------------------------------------------

def write_jsonc(name, actors, ambients, base_id=10000):
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    ags = needed_ags(actors)
    data = {
        "long_name": name, "iso_name": _iso(name), "nickname": _nick(name),
        "gltf_file": f"custom_assets/jak1/levels/{name}/{name}.glb",
        "automatic_wall_detection": True, "automatic_wall_angle": 45.0,
        "double_sided_collide": False, "base_id": base_id,
        "art_groups": [g.replace(".go","") for g in ags],
        "custom_models": [], "textures": [["village1-vis-alpha"]],
        "tex_remap": "village1", "sky": "village1", "tpages": [],
        "ambients": ambients, "actors": actors,
    }
    p = d / f"{name}.jsonc"
    with open(p, "w") as f:
        f.write(f"// OpenGOAL custom level: {name}\n")
        json.dump(data, f, indent=2)
    log(f"Wrote {p}")

def write_gd(name, ags, code_deps, tpages=None):
    """Write .gd file.

    code_deps is a list of (o_file, gc_path, dep) from needed_code().
    Each enemy .o is inserted before the art groups so it links first.

    FIX v0.5.0 (Bug 1): The opening paren for the inner file list is now its
    own line so that the first file entry keeps correct indentation.  The old
    code concatenated ' (' + files[0].lstrip() which produced a malformed
    S-expression when enemy .o entries were present and caused GOALC to crash.
    """
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    dgo_name = f"{_nick(name).upper()}.DGO"
    code_o   = [f'  "{o}"' for o, _, _ in code_deps]
    # Village1 sky tpages always present; add entity-specific tpages before art groups
    base_tpages = ['  "tpage-398.go"', '  "tpage-400.go"', '  "tpage-399.go"',
                   '  "tpage-401.go"', '  "tpage-1470.go"']
    extra_tpages = [f'  "{tp}"' for tp in (tpages or [])
                    if f'  "{tp}"' not in base_tpages]
    files = (
        [f'  "{name}-obs.o"']
        + code_o
        + base_tpages
        + extra_tpages
        + [f'  "{g}"' for g in ags]
        + [f'  "{name}.go"']
    )
    lines = (
        [f';; DGO for {name}', f'("{dgo_name}"', ' (']
        + files
        + ['  )', ' )']
    )
    p = d / f"{_nick(name)}.gd"
    new_text = "\n".join(lines) + "\n"
    if not p.exists() or p.read_text() != new_text:
        p.write_text(new_text)
        log(f"Wrote {p}  (enemy .o files: {[o for o,_,_ in code_deps]})")
    else:
        log(f"Skipped {p} (unchanged)")



def _make_continues(name, spawns):
    def cp(sp):
        return (f"(new 'static 'continue-point\n"
                f"             :name \"{name}-{sp['name']}\"\n"
                f"             :level '{name}\n"
                f"             :trans (new 'static 'vector"
                f" :x (meters {sp['x']:.4f}) :y (meters {sp['y']:.4f}) :z (meters {sp['z']:.4f}) :w 1.0)\n"
                f"             :quat (new 'static 'quaternion :w 1.0)\n"
                f"             :camera-trans (new 'static 'vector :x 0.0 :y 4096.0 :z 0.0 :w 1.0)\n"
                f"             :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)\n"
                f"             :load-commands '()\n"
                f"             :vis-nick 'none\n"
                f"             :lev0 '{name}\n"
                f"             :disp0 'display\n"
                f"             :lev1 #f\n"
                f"             :disp1 #f)")
    if spawns:
        return "'(" + "\n             ".join(cp(s) for s in spawns) + ")"
    return (f"'((new 'static 'continue-point\n"
            f"             :name \"{name}-start\"\n"
            f"             :level '{name}\n"
            f"             :trans (new 'static 'vector :x 0.0 :y (meters 10.) :z 0.0 :w 1.0)\n"
            f"             :quat (new 'static 'quaternion :w 1.0)\n"
            f"             :camera-trans (new 'static 'vector :x 0.0 :y 4096.0 :z 0.0 :w 1.0)\n"
            f"             :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)\n"
            f"             :load-commands '()\n"
            f"             :vis-nick 'none\n"
            f"             :lev0 '{name}\n"
            f"             :disp0 'display\n"
            f"             :lev1 #f\n"
            f"             :disp1 #f))")

def patch_level_info(name, spawns):
    p = _level_info()
    if not p.exists(): log(f"WARNING: {p} not found"); return
    block = (f"\n(define {name}\n"
             f"  (new 'static 'level-load-info\n"
             f"       :index 27\n"
             f"       :name '{name}\n"
             f"       :visname '{name}-vis\n"
             f"       :nickname '{_nick(name)}\n"
             f"       :packages '()\n"
             f"       :sound-banks '()\n"
             f"       :music-bank #f\n"
             f"       :ambient-sounds '()\n"
             f"       :mood '*village1-mood*\n"
             f"       :mood-func 'update-mood-village1\n"
             f"       :ocean #f\n"
             f"       :sky #t\n"
             f"       :sun-fade 1.0\n"
             f"       :continues\n"
             f"       {_make_continues(name, spawns)}\n"
             f"       :tasks '()\n"
             f"       :priority 100\n"
             f"       :load-commands '()\n"
             f"       :alt-load-commands '()\n"
             f"       :bsp-mask #xffffffffffffffff\n"
             f"       :bsphere (new 'static 'sphere :w 167772160000.0)\n"
             f"       :bottom-height (meters -20)\n"
             f"       :run-packages '()\n"
             f"       :wait-for-load #t))\n"
             f"\n(cons! *level-load-list* '{name})\n")
    txt = p.read_text(encoding="utf-8")
    txt = re.sub(rf"\n\(define {re.escape(name)}\b.*?\(cons!.*?'{re.escape(name)}\)\n",
                 "", txt, flags=re.DOTALL)
    marker = ";;;;; CUSTOM LEVELS"
    new_txt = (txt.replace(marker, marker+block, 1) if marker in txt
               else txt + "\n;;;;; CUSTOM LEVELS\n" + block)
    original = p.read_text(encoding="utf-8")
    if new_txt != original:
        p.write_text(new_txt, encoding="utf-8")
        log("Patched level-info.gc")
    else:
        log("Skipped level-info.gc (unchanged)")

def patch_game_gp(name, code_deps=None):
    """Patch game.gp to build our custom level and compile enemy code files.

    code_deps: list of (o_file, gc_path, dep) from needed_code().
    For each enemy type not in GAME.CGO we add a goal-src line so GOALC
    compiles and links its code into our DGO.  Without this the type is
    undefined at runtime and the entity spawns as a do-nothing process.
    """
    p = _game_gp()
    if not p.exists(): log(f"WARNING: {p} not found"); return
    raw  = p.read_bytes()
    crlf = b"\r\n" in raw
    txt  = raw.decode("utf-8").replace("\r\n", "\n")
    nick = _nick(name)
    dgo  = f"{nick.upper()}.DGO"

    # goal-src lines for enemy code (de-duplicated)
    # Skip o_only entries (gc=None) — vanilla game.gp already has their goal-src lines.
    extra_goal_src = ""
    if code_deps:
        seen_gc = set()
        for o, gc, dep in code_deps:
            if gc is None:
                continue  # o_only: .o injected into DGO but no goal-src needed
            if gc not in seen_gc:
                seen_gc.add(gc)
                extra_goal_src += f'(goal-src "{gc}" "{dep}")\n'

    correct_block = (
        f'(build-custom-level "{name}")\n'
        f'(custom-level-cgo "{dgo}" "{name}/{nick}.gd")\n'
        f'(goal-src "levels/{name}/{name}-obs.gc" "process-drawable")\n'
        + extra_goal_src
    )

    # Strip any previously written block for this level
    txt = re.sub(r'\(build-custom-level "' + re.escape(name) + r'"\)\n', '', txt)
    txt = re.sub(r'\(custom-level-cgo "[^"]*" "' + re.escape(name) + r'/[^"]+"\)\n', '', txt)
    # FIX v0.5.0 (Bug 2): was r'/[^"]+\"[^)]*\)' — the \" was a literal
    # backslash+quote so the regex never matched, leaving stale goal-src lines
    # in game.gp across exports which caused duplicate-compile crashes in GOALC.
    txt = re.sub(r'\(goal-src "levels/' + re.escape(name) + r'/[^"]+"[^)]*\)\n', '', txt)
    # Strip ALL enemy goal-src lines that could have been injected by any previous export.
    # This catches leftover entries even if the dep changed between exports.
    # We match any goal-src line whose path matches a known ETYPE_CODE gc file.
    for _etype_info in ETYPE_CODE.values():
        _gc = _etype_info.get("gc", "")
        if _gc:
            txt = re.sub(r'\(goal-src "' + re.escape(_gc) + r'"[^)]*\)\n', '', txt)

    if correct_block in txt:
        log("game.gp already correct"); return

    for anchor in ['(build-custom-level "test-zone")', '(group-list "all-code"']:
        if anchor in txt:
            txt = txt.replace(anchor, correct_block + "\n" + anchor, 1)
            break
    else:
        txt += "\n" + correct_block

    if crlf:
        txt = txt.replace("\n", "\r\n")
    p.write_bytes(txt.encode("utf-8"))
    log(f"Patched game.gp  (extra goal-src: {[gc for _,gc,_ in (code_deps or []) if gc is not None]})")

def export_glb(ctx, name):
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(d / f"{name}.glb"), export_format="GLB",
        export_vertex_color="ACTIVE", export_normals=True,
        export_materials="EXPORT", export_texcoords=True,
        export_apply=True, use_selection=False,
        export_yup=True, export_skins=False, export_animations=False,
        export_extras=True)
    log("Exported GLB")

# ---------------------------------------------------------------------------
# OPERATORS — Spawn / NavMesh
# ---------------------------------------------------------------------------

class OG_OT_SpawnPlayer(Operator):
    bl_idname = "og.spawn_player"
    bl_label  = "Add Player Spawn"
    bl_description = "Place a player spawn empty at the 3D cursor"
    def execute(self, ctx):
        n   = len([o for o in ctx.scene.objects if o.name.startswith("SPAWN_")])
        uid = "start" if n == 0 else f"spawn{n}"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"SPAWN_{uid}"; o.show_name = True
        o.empty_display_size = 1.0; o.color = (0.0,1.0,0.0,1.0)
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}

class OG_OT_SpawnEntity(Operator):
    bl_idname = "og.spawn_entity"
    bl_label  = "Add Entity"
    bl_description = "Place selected entity at the 3D cursor"
    def execute(self, ctx):
        etype = ctx.scene.og_props.entity_type
        info  = ENTITY_DEFS.get(etype, {})
        shape = info.get("shape", "SPHERE")
        color = info.get("color", (1.0,0.5,0.1,1.0))
        n     = len([o for o in ctx.scene.objects if o.name.startswith(f"ACTOR_{etype}_")])
        bpy.ops.object.empty_add(type=shape, location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"ACTOR_{etype}_{n}"
        o.show_name = True
        o.empty_display_size = 0.6
        o.color = color
        if etype == "crate":
            o["og_crate_type"] = ctx.scene.og_props.crate_type
        if etype in NAV_UNSAFE_TYPES:
            o["og_nav_radius"] = ctx.scene.og_props.nav_radius
            self.report({"WARNING"},
                f"Added {o.name}  —  nav-mesh workaround will be applied on export. "
                f"Enemy will idle/notice but won't pathfind without a real navmesh.")
        elif etype in NEEDS_PATHB_TYPES:
            self.report({"WARNING"},
                f"Added {o.name}  —  swamp-bat needs TWO path sets: "
                f"waypoints named _wp_00/_wp_01... AND _wpb_00/_wpb_01... (second patrol route).")
        elif etype in NEEDS_PATH_TYPES:
            self.report({"WARNING"},
                f"Added {o.name}  —  this entity requires at least 1 waypoint (_wp_00). "
                f"It will crash or error at runtime without a path.")
        elif etype in IS_PROP_TYPES:
            self.report({"INFO"}, f"Added {o.name}  (prop — idle animation only, no AI/combat)")
        else:
            self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}

class OG_OT_MarkNavMesh(Operator):
    bl_idname = "og.mark_navmesh"
    bl_label  = "Mark as NavMesh"
    bl_description = "Tag selected mesh objects for future auto-navmesh generation"
    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if o.type == "MESH":
                o["og_navmesh"] = True
                count += 1
        self.report({"INFO"}, f"Tagged {count} object(s) as navmesh geometry")
        return {"FINISHED"}

class OG_OT_UnmarkNavMesh(Operator):
    bl_idname = "og.unmark_navmesh"
    bl_label  = "Unmark NavMesh"
    bl_description = "Remove navmesh tag from selected objects"
    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if "og_navmesh" in o:
                del o["og_navmesh"]; count += 1
        self.report({"INFO"}, f"Untagged {count} object(s)")
        return {"FINISHED"}

def validate_ambients(ambients):
    errors = []
    for i, a in enumerate(ambients):
        t = a.get("trans", [])
        b = a.get("bsphere", [])
        name = a.get("lump", {}).get("name", f"ambient[{i}]")
        if len(t) != 4:
            errors.append(f"{name}: ambient trans has {len(t)} elements, expected 4  (value={t})")
        if len(b) != 4:
            errors.append(f"{name}: ambient bsphere has {len(b)} elements, expected 4  (value={b})")
    return errors




# ---------------------------------------------------------------------------
# OPERATORS — NavMesh linking
# ---------------------------------------------------------------------------

class OG_OT_LinkNavMesh(Operator):
    """Link selected enemy actor(s) to the selected navmesh mesh.
    Select any combination of enemy empties + one mesh — order doesn't matter."""
    bl_idname = "og.link_navmesh"
    bl_label  = "Link to NavMesh"
    bl_description = "Select enemy actor(s) + navmesh mesh (any order), then click"

    def execute(self, ctx):
        selected = ctx.selected_objects

        # Find the mesh and the enemy empties from the full selection — order irrelevant
        meshes  = [o for o in selected if o.type == "MESH"]
        enemies = [o for o in selected if o.type == "EMPTY"
                   and o.name.startswith("ACTOR_") and "_wp_" not in o.name
                   and "_wpb_" not in o.name]

        if not meshes:
            self.report({"ERROR"}, "No mesh in selection — select a navmesh quad too")
            return {"CANCELLED"}
        if len(meshes) > 1:
            self.report({"ERROR"}, "Multiple meshes selected — select only one navmesh quad")
            return {"CANCELLED"}
        if not enemies:
            self.report({"ERROR"}, "No enemy actor in selection — select the enemy empty too")
            return {"CANCELLED"}

        nm = meshes[0]

        # Tag mesh as navmesh and prefix name if needed
        nm["og_navmesh"] = True
        if not nm.name.startswith("NAVMESH_"):
            nm.name = "NAVMESH_" + nm.name

        for enemy in enemies:
            enemy["og_navmesh_link"] = nm.name

        self.report({"INFO"}, f"Linked {len(enemies)} actor(s) to {nm.name}")
        return {"FINISHED"}


class OG_OT_UnlinkNavMesh(Operator):
    """Remove navmesh link from selected enemy actors."""
    bl_idname = "og.unlink_navmesh"
    bl_label  = "Unlink NavMesh"
    bl_description = "Remove navmesh link from selected enemy actor(s)"

    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if "og_navmesh_link" in o:
                del o["og_navmesh_link"]
                count += 1
        self.report({"INFO"}, f"Unlinked {count} actor(s)")
        return {"FINISHED"}

# ---------------------------------------------------------------------------
# OPERATOR — Export & Build
# ---------------------------------------------------------------------------

_BUILD_STATE = {"done":False, "status":"", "error":None, "ok":False}


def patch_entity_gc(navmesh_actors):
    """
    Patch engine/entity/entity.gc to add custom-nav-mesh-check-and-setup.

    navmesh_actors: list of (actor_aid, mesh_data) tuples.

    Adds/replaces:
      1. A (defun custom-nav-mesh-check-and-setup ...) with one case per actor.
      2. A call to it at the top of (defmethod birth! entity-actor ...).

    Safe to call repeatedly — old injected code is stripped before re-injecting.
    """
    p = _entity_gc()
    if not p.exists():
        log(f"WARNING: entity.gc not found at {p}")
        return

    raw  = p.read_bytes()
    crlf = b"\r\n" in raw
    txt  = raw.decode("utf-8").replace("\r\n", "\n")

    # ── Strip any previously injected block ──────────────────────────────────
    import re
    txt = re.sub(
        r"\n;; \[OpenGOAL Tools\] BEGIN custom-nav-mesh.*?;; \[OpenGOAL Tools\] END custom-nav-mesh\n",
        "",
        txt,
        flags=re.DOTALL,
    )
    # Strip old birth! injection line
    txt = re.sub(r"  \(custom-nav-mesh-check-and-setup this\)\n", "", txt)

    if not navmesh_actors:
        # Nothing to inject — just clean file
        out = txt.replace("\n", "\r\n") if crlf else txt
        p.write_bytes(out.encode("utf-8"))
        log("entity.gc: cleaned (no navmesh actors)")
        return

    # ── Build the defun block ─────────────────────────────────────────────────
    lines = [
        "",
        ";; [OpenGOAL Tools] BEGIN custom-nav-mesh",

        "(defun custom-nav-mesh-check-and-setup ((this entity-actor))",
        "  (case (-> this aid)",
    ]
    for aid, mesh in navmesh_actors:
        lines.append(_navmesh_to_goal(mesh, aid))
    lines += [
        "  )",
        "  ;; Manually init the nav-mesh without calling entity-nav-login.",
        "  ;; entity-nav-login calls update-route-table which writes back to the route",
        "  ;; array — but our mesh is 'static (read-only GAME.CGO memory), so that",
        "  ;; write would segfault. Instead we just set up the user-list engine.",
        "  (when (nonzero? (-> this nav-mesh))",
        "    (when (zero? (-> (-> this nav-mesh) user-list))",
        "      (set! (-> (-> this nav-mesh) user-list)",
        "            (new 'loading-level 'engine 'nav-engine 32))",
        "    )",
        "  )",
        "  (none)",
        ")",
        ";; [OpenGOAL Tools] END custom-nav-mesh",
        "",
    ]
    inject_block = "\n".join(lines)

    # Insert before (defmethod birth! ((this entity-actor))
    BIRTH_MARKER = "(defmethod birth! ((this entity-actor))"
    if BIRTH_MARKER not in txt:
        log("WARNING: entity.gc birth! marker not found — cannot inject nav-mesh")
        return
    txt = txt.replace(BIRTH_MARKER, inject_block + "\n" + BIRTH_MARKER, 1)

    # ── Inject call at top of birth! body ────────────────────────────────────
    # Find the body start — line after "Create a process for this entity..."
    # We look for the first (let* ... after the birth! marker
    CALL_MARKER = "  (let* ((entity-type (-> this etype))"
    txt = txt.replace(
        CALL_MARKER,
        "  (custom-nav-mesh-check-and-setup this)\n" + CALL_MARKER,
        1,
    )

    out = txt.replace("\n", "\r\n") if crlf else txt
    p.write_bytes(out.encode("utf-8"))
    log(f"Patched entity.gc with {len(navmesh_actors)} nav-mesh actor(s)")

def _bg_build(name, scene):
    state = _BUILD_STATE
    try:
        state["status"] = "Collecting scene..."
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)
        collect_nav_mesh_geometry(scene, name)

        if code_deps:
            state["status"] = f"Injecting code for: {[o for o,_,_ in code_deps]}..."
            log(f"[code-deps] {code_deps}")

        state["status"] = "Writing files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        write_gc(name)
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns)
        patch_game_gp(name, code_deps)

        if goalc_ok():
            state["status"] = "Running (mi) via nREPL..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is not None:
                state["ok"] = True; state["status"] = "Build complete!"; return

        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(mi)"])
        state["status"] = "Launching GOALC (old instance killed)..."
        ok, msg = launch_goalc()
        if not ok:
            state["error"] = msg; return
        state["ok"] = True
        state["status"] = "GOALC launched — watch console for compile progress."
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True

class OG_OT_ExportBuild(Operator):
    bl_idname = "og.export_build"
    bl_label  = "Export & Build"
    bl_description = "Export GLB, write all level files, compile with GOALC"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}"); return {"CANCELLED"}
        _BUILD_STATE.clear()
        _BUILD_STATE.update({"done":False,"status":"Starting...","error":None,"ok":False})
        threading.Thread(target=_bg_build, args=(name, ctx.scene), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _BUILD_STATE.get("status","Working..."))
            if _BUILD_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _BUILD_STATE.get("error"):
                    self.report({"ERROR"}, _BUILD_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Build complete!"); return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)

# ---------------------------------------------------------------------------
# OPERATOR — Play
# ---------------------------------------------------------------------------

_PLAY_STATE = {"done":False, "error":None, "status":""}

def _bg_play(name):
    """Kill GK+GOALC, relaunch GOALC with nREPL, launch GK, load level, spawn player.

    ARCHITECTURE NOTES (read before modifying):

    nREPL (port 8181) is a TCP socket that GOALC opens on startup.  The addon
    sends all commands ((lt), (bg), (start)) through this socket via goalc_send().
    If another GOALC instance is already holding port 8181, bind() fails and
    GOALC prints "nREPL: DISABLED" — every goalc_send() then silently returns
    None and nothing happens.

    FIX: Always kill GOALC before relaunching it.  The goalc_ok() fast-path
    (reuse existing GOALC) is ONLY safe when nREPL is confirmed working.

    startup.gc SEQUENCING:
    Lines above ";; og:run-below-on-listen" → run_before_listen (run immediately
    at GOALC startup, before GK exists).
    Lines below the sentinel             → run_after_listen (run automatically
    when (lt) successfully connects to GK).
    (lt) itself is in run_before_listen so it fires first; everything after the
    sentinel fires after GK connects.  No need for (suspend-for) here — the
    run_after_listen lines don't execute until GK is alive and (lt) connected.

    WHY (start) IS NEEDED:
    (bg) loads geometry and calls set-continue! to our level's first continue-
    point, but does NOT kill/respawn the player.  The boot-sequence player is
    still alive, falls in the void, dies, and respawns in a race with level load.
    (start 'play ...) kills that player and spawns fresh at the continue-point.
    """
    state = _PLAY_STATE
    try:
        # Always kill both GK and GOALC before relaunching.
        # GOALC must be killed so port 8181 is free for the new instance.
        # If an old GOALC holds 8181, the new one shows "nREPL: DISABLED" and
        # all goalc_send() calls silently fail.
        state["status"] = "Killing GK and GOALC..."
        kill_gk()
        kill_goalc()

        # Write startup.gc with only (lt) and (bg).
        # (start) is NOT in startup.gc because run_after_listen fires the moment
        # (lt) connects — before GAME.CGO finishes linking and *game-info* exists.
        # Calling (start) before *game-info* is defined causes a compile error.
        # Instead we poll via nREPL after GK boots until *game-info* is live.
        # Write startup.gc with ONLY (lt) — no (bg) here.
        # Putting (bg) in run_after_listen causes two problems:
        #   1. It re-fires every time GK reconnects, triggering "generated code,
        #      but wasn't supposed to" spam after play is done.
        #   2. It fires before GAME.CGO finishes linking, so the level may load
        #      into an unready engine state.
        # Instead we send (bg) manually via nREPL once *game-info* is confirmed live.
        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(lt)"])

        state["status"] = "Launching GOALC (waiting for nREPL)..."
        ok, msg = launch_goalc(wait_for_nrepl=True)
        if not ok:
            state["error"] = f"GOALC failed to start: {msg}"; return

        state["status"] = "Launching game..."
        ok, msg = launch_gk()
        if not ok: state["error"] = msg; return

        # Poll until *game-info* exists (GAME.CGO finished linking) then load level + spawn.
        # Match "'ready" (with leading quote) to catch only the GOAL symbol return value,
        # not console noise like "Listener: ready" which was causing false-positive triggers.
        state["status"] = "Waiting for game to finish loading..."
        spawned = False
        for _ in range(240):
            time.sleep(0.5)
            r = goalc_send("(if (nonzero? *game-info*) 'ready 'wait)", timeout=3)
            if r and "'ready" in r:
                state["status"] = "Loading level..."
                goalc_send(f"(bg '{name}-vis)", timeout=30)
                time.sleep(1.0)  # brief extra wait for level geometry to become active
                state["status"] = "Spawning player..."
                goalc_send(f"(start 'play (or (get-continue-by-name *game-info* \"{name}-start\") (get-or-create-continue! *game-info*)))")
                spawned = True
                break
        if not spawned:
            state["status"] = "Done (spawn timed out — load level manually)"
            return
        state["status"] = "Done!"
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


# ── Waypoint operators ────────────────────────────────────────────────────────

class OG_OT_AddWaypoint(Operator):
    """Add a waypoint empty at the 3D cursor, linked to the selected enemy."""
    bl_idname = "og.add_waypoint"
    bl_label  = "Add Waypoint"

    enemy_name: bpy.props.StringProperty()
    pathb_mode: bpy.props.BoolProperty(default=False,
        description="Add to secondary path (pathb) — swamp-bat only")

    def execute(self, ctx):
        if not self.enemy_name:
            self.report({"ERROR"}, "No enemy name provided")
            return {"CANCELLED"}

        # Find next available index for primary (_wp_) or secondary (_wpb_) path
        suffix = "_wpb_" if self.pathb_mode else "_wp_"
        prefix = self.enemy_name + suffix
        existing = [o.name for o in bpy.data.objects if o.name.startswith(prefix)]
        idx = 0
        while f"{prefix}{idx:02d}" in existing:
            idx += 1

        wp_name = f"{prefix}{idx:02d}"

        # Create empty at 3D cursor
        empty = bpy.data.objects.new(wp_name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        empty.location = ctx.scene.cursor.location.copy()

        # Custom property to link back to enemy
        empty["og_waypoint_for"] = self.enemy_name

        ctx.collection.objects.link(empty)

        # Do NOT change active object — user needs to keep the actor selected
        # so they can quickly add more waypoints without re-selecting.
        self.report({"INFO"}, f"Added {wp_name} at cursor")
        return {"FINISHED"}


class OG_OT_DeleteWaypoint(Operator):
    """Remove a waypoint empty."""
    bl_idname = "og.delete_waypoint"
    bl_label  = "Delete Waypoint"

    wp_name: bpy.props.StringProperty()

    def execute(self, ctx):
        ob = bpy.data.objects.get(self.wp_name)
        if ob:
            bpy.data.objects.remove(ob, do_unlink=True)
            self.report({"INFO"}, f"Deleted {self.wp_name}")
        return {"FINISHED"}


class OG_OT_Play(Operator):
    """Launch GK in debug mode. No GOALC, no auto-load — just opens the game
    so you can navigate to your level manually via the debug menu."""
    bl_idname      = "og.play"
    bl_label       = "Launch Game (Debug)"
    bl_description = "Kill existing GK, launch fresh in debug mode. Navigate to your level manually."

    def execute(self, ctx):
        kill_gk()
        ok, msg = launch_gk()
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, "Game launched in debug mode — select your level manually")
        return {"FINISHED"}


class OG_OT_PlayAutoLoad(Operator):
    """Kill GK+GOALC, relaunch, and auto-load the level via nREPL.
    Slower (~30-60s) but fully automated."""
    bl_idname      = "og.play_autoload"
    bl_label       = "Launch & Auto-Load Level"
    bl_description = "Kill GK/GOALC, relaunch, and automatically load your level via nREPL (slower)"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        _PLAY_STATE.clear()
        _PLAY_STATE.update({"done":False,"error":None,"status":"Starting..."})
        threading.Thread(target=_bg_play, args=(name,), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _PLAY_STATE.get("status","..."))
            if _PLAY_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _PLAY_STATE.get("error"):
                    self.report({"ERROR"}, _PLAY_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Game launched!")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)



# ---------------------------------------------------------------------------
# OPERATORS — Open Folder / File
# ---------------------------------------------------------------------------

class OG_OT_OpenFolder(Operator):
    """Open a folder in the system file explorer."""
    bl_idname  = "og.open_folder"
    bl_label   = "Open Folder"
    bl_description = "Open folder in system file explorer"

    folder: bpy.props.StringProperty()

    def execute(self, ctx):
        p = Path(self.folder)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                self.report({"WARNING"}, f"Folder not found: {p}")
                return {"CANCELLED"}
        try:
            if os.name == "nt":
                os.startfile(str(p))
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self.report({"ERROR"}, f"Could not open folder: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class OG_OT_OpenFile(Operator):
    """Open a specific file in the default system editor."""
    bl_idname  = "og.open_file"
    bl_label   = "Open File"
    bl_description = "Open file in default editor"

    filepath: bpy.props.StringProperty()

    def execute(self, ctx):
        p = Path(self.filepath)
        if not p.exists():
            self.report({"WARNING"}, f"File not found: {p}")
            return {"CANCELLED"}
        try:
            if os.name == "nt":
                os.startfile(str(p))
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self.report({"ERROR"}, f"Could not open file: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}

# ---------------------------------------------------------------------------
# OPERATOR — Export, Build & Play (combined)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# OPERATOR — Quick Geo Rebuild
# Re-exports GLB + actor placement, repacks DGO, relaunches GK.
# Skips all GOAL (.gc) recompilation — fastest iteration for geo/placement changes.
# ---------------------------------------------------------------------------

_GEO_REBUILD_STATE = {"done": False, "status": "", "error": None, "ok": False}


def _bg_geo_rebuild(name, scene):
    """Export geo + actor placement, repack DGO, relaunch GK. No GOAL recompile.

    (mi) is GOALC's incremental build command — it skips .gc files that haven't
    changed, so it only re-extracts the GLB and repacks the DGO.

    NOTE: if you've added a NEW enemy type since the last full Export & Compile,
    use that instead — this path skips the game.gp patch those types need.
    """
    state = _GEO_REBUILD_STATE
    try:
        state["status"] = "Collecting scene..."
        actors   = collect_actors(scene)
        ambients = collect_ambients(scene)
        spawns   = collect_spawns(scene)
        ags      = needed_ags(actors)
        tpages   = needed_tpages(actors)
        code_deps = needed_code(actors)  # still needed for DGO .o injection

        state["status"] = "Writing level files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, base_id)
        write_gd(name, ags, code_deps, tpages)
        patch_level_info(name, spawns)  # update spawn continue-points if moved

        # Run (mi) — re-extracts GLB, repacks DGO, skips unchanged .gc files
        if goalc_ok():
            state["status"] = "Running (mi) — re-extracting geo..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is None:
                state["error"] = "(mi) timed out or GOALC lost connection"; return
        else:
            state["status"] = "GOALC not running — launching for (mi)..."
            write_startup_gc(["(mi)"])
            ok, msg = launch_goalc(wait_for_nrepl=True)
            if not ok:
                state["error"] = f"GOALC failed to start: {msg}"; return
            state["status"] = "Running (mi)..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is None:
                state["error"] = "(mi) timed out"; return

        state["ok"] = True
        state["status"] = "Done! Reload your level in-game."
    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


class OG_OT_GeoRebuild(Operator):
    """Re-export geometry and actor placement, repack DGO, relaunch game.
    Skips GOAL compilation — fastest loop for geo and enemy placement changes."""
    bl_idname      = "og.geo_rebuild"
    bl_label       = "Quick Geo Rebuild"
    bl_description = (
        "Re-export geo + actor placement, repack DGO, relaunch game. "
        "No GOAL recompile. Use when only geometry or placement changed."
    )
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first"); return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}"); return {"CANCELLED"}
        _GEO_REBUILD_STATE.clear()
        _GEO_REBUILD_STATE.update({"done": False, "status": "Starting...", "error": None, "ok": False})
        threading.Thread(target=_bg_geo_rebuild, args=(name, ctx.scene), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL Geo: " + _GEO_REBUILD_STATE.get("status", "Working..."))
            if _GEO_REBUILD_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _GEO_REBUILD_STATE.get("error"):
                    self.report({"ERROR"}, _GEO_REBUILD_STATE["error"]); return {"CANCELLED"}
                self.report({"INFO"}, "Geo rebuild done — load your level in-game")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)


_BUILD_PLAY_STATE = {"done": False, "status": "", "error": None, "ok": False}


def _bg_build_and_play(name, scene):
    """Export files, compile with GOALC, then launch GK and load the level.

    FLOW:
      Phase 1 — collect scene, write all level files.
      Phase 2 — compile: ensure GOALC+nREPL are live, send (mi).
      Phase 3 — launch: write startup.gc with (lt)/(bg)/(start), restart GOALC
                 so it auto-runs those commands when GK connects.

    WHY WE RESTART GOALC AFTER COMPILE:
      After (mi) finishes we need GOALC to re-read startup.gc so it can auto-run
      (lt)/(bg)/(start) when GK boots.  Restarting is simpler and more reliable
      than trying to sequence manual goalc_send() calls with arbitrary sleeps —
      the startup.gc run_after_listen mechanism handles the GK-ready timing for us.

    WHY startup.gc INSTEAD OF goalc_send() FOR LAUNCH:
      goalc_send() is fire-and-forget with fixed sleeps.  If GK takes longer to
      boot than expected the (lt) call fails and nothing loads.  startup.gc
      run_after_listen fires only after (lt) actually connects — it is driven by
      GK being ready, not by a sleep timer.  See _bg_play() docstring for more.
    """
    state = _BUILD_PLAY_STATE
    try:
        # ── Phase 1: Build ────────────────────────────────────────────────────
        state["status"] = "Collecting scene..."
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)

        state["status"] = "Writing level files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        write_gc(name)
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns)
        patch_game_gp(name, code_deps)

        # ── Phase 2: Compile ──────────────────────────────────────────────────
        # Kill GK first — game must not be running during compile.
        # Keep GOALC alive if nREPL is working — saves startup time for (mi).
        state["status"] = "Killing existing GK..."
        kill_gk()
        time.sleep(0.3)

        if not goalc_ok():
            # nREPL not reachable — kill any stale GOALC holding port 8181
            # and launch fresh so (mi) can connect.
            state["status"] = "Launching GOALC (waiting for nREPL)..."
            kill_goalc()
            ok, msg = launch_goalc(wait_for_nrepl=True)
            if not ok:
                state["error"] = f"GOALC failed to start: {msg}"; return

        state["status"] = "Compiling (mi) — please wait..."
        r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
        if r is None:
            state["error"] = "Compile timed out — check GOALC console"; return

        # ── Phase 3: Launch game and load level ───────────────────────────────
        # Write startup.gc with ONLY (lt) — no (bg) here.
        # Putting (bg) in run_after_listen causes "generated code, but wasn't
        # supposed to" spam every time GK reconnects after play is done.
        # We send (bg) manually via nREPL once *game-info* is confirmed live.
        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(lt)"])

        # Restart GOALC so it reads the new startup.gc.
        state["status"] = "Restarting GOALC with launch startup..."
        kill_goalc()
        ok, msg = launch_goalc(wait_for_nrepl=True)
        if not ok:
            state["error"] = f"GOALC relaunch failed: {msg}"; return

        state["status"] = "Launching game..."
        ok, msg = launch_gk()
        log(f"[launch] launch_gk returned: ok={ok} msg={msg}")
        if not ok:
            state["error"] = f"GK launch failed: {msg}"; return

        # Poll until *game-info* exists (GAME.CGO done) then load level + spawn.
        # Match "'ready" (with leading quote) to catch only the GOAL symbol return,
        # not console noise like "Listener: ready" which causes false-positive triggers.
        state["status"] = "Waiting for game to finish loading..."
        spawned = False
        for _ in range(240):
            time.sleep(0.5)
            r = goalc_send("(if (nonzero? *game-info*) 'ready 'wait)", timeout=3)
            if r and "'ready" in r:
                state["status"] = "Loading level..."
                goalc_send(f"(bg '{name}-vis)", timeout=30)
                time.sleep(1.0)
                state["status"] = "Spawning player..."
                goalc_send(f"(start 'play (or (get-continue-by-name *game-info* \"{name}-start\") (get-or-create-continue! *game-info*)))")
                spawned = True
                break
        if not spawned:
            state["status"] = "Done (spawn timed out — load level manually)"
            return
        state["status"] = "Done!"
        state["ok"] = True

    except Exception as e:
        state["error"] = str(e)
    finally:
        state["done"] = True


class OG_OT_ExportBuildPlay(Operator):
    bl_idname      = "og.export_build_play"
    bl_label       = "Export, Build & Play"
    bl_description = "Export GLB, write level files, compile with GOALC, then launch the game"
    _timer = None

    def execute(self, ctx):
        name = _lname(ctx)
        if not name:
            self.report({"ERROR"}, "Enter a level name first")
            return {"CANCELLED"}
        try:
            export_glb(ctx, name)
        except Exception as e:
            self.report({"ERROR"}, f"GLB export failed: {e}")
            return {"CANCELLED"}

        _BUILD_PLAY_STATE.clear()
        _BUILD_PLAY_STATE.update({"done": False, "status": "Starting...", "error": None, "ok": False})
        threading.Thread(target=_bg_build_and_play, args=(name, ctx.scene), daemon=True).start()
        wm = ctx.window_manager
        self._timer = wm.event_timer_add(0.5, window=ctx.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, ctx, event):
        if event.type == "TIMER":
            ctx.workspace.status_text_set("OpenGOAL: " + _BUILD_PLAY_STATE.get("status", "Working..."))
            if _BUILD_PLAY_STATE.get("done"):
                ctx.window_manager.event_timer_remove(self._timer)
                ctx.workspace.status_text_set(None)
                if _BUILD_PLAY_STATE.get("error"):
                    self.report({"ERROR"}, _BUILD_PLAY_STATE["error"])
                    return {"CANCELLED"}
                self.report({"INFO"}, "Build & launch complete!")
                return {"FINISHED"}
        return {"PASS_THROUGH"}

    def cancel(self, ctx):
        ctx.window_manager.event_timer_remove(self._timer)
        ctx.workspace.status_text_set(None)



# ---------------------------------------------------------------------------
# HELPERS — waypoint eligibility
# ---------------------------------------------------------------------------

def _actor_uses_waypoints(etype):
    """True if this entity type can use waypoints (path lump or nav patrol)."""
    info = ENTITY_DEFS.get(etype, {})
    return (not info.get("nav_safe", True)   # nav-enemy — optional patrol path
            or info.get("needs_path", False)  # process-drawable that requires path
            or info.get("needs_pathb", False))


def _actor_uses_navmesh(etype):
    """True if this entity type is a nav-enemy and needs entity.gc navmesh patch."""
    info = ENTITY_DEFS.get(etype, {})
    return info.get("ai_type") == "nav-enemy"


# ---------------------------------------------------------------------------
# PANELS
# ---------------------------------------------------------------------------
# Panel hierarchy (all under "OpenGOAL" N-panel tab):
#
#  OG_PT_LevelSettings   — Level name, base ID
#  OG_PT_Scene           — Player spawn (expandable later)
#  OG_PT_PlaceObjects    — Entity picker + Add Entity
#  OG_PT_Waypoints       — Waypoint management (context-sensitive, collapsible)
#  OG_PT_NavMesh         — NavMesh linking via object picker
#  OG_PT_BuildPlay       — Big ▶ Export, Build & Play button
#  OG_PT_DevTools        — Expert options + Quick Open (collapsed)
#  OG_PT_Collision       — Per-object collision (separate, object-context)
# ---------------------------------------------------------------------------

# Shared header style helper
def _header_sep(layout):
    """A subtle separator line used between sub-sections inside a panel."""
    layout.separator(factor=0.4)


# ── Level Settings ───────────────────────────────────────────────────────────

class OG_PT_LevelSettings(Panel):
    bl_label       = "⚙  Level Settings"
    bl_idname      = "OG_PT_level_settings"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        name   = props.level_name.strip()

        col = layout.column(align=True)
        col.prop(props, "level_name", text="Name")
        col.prop(props, "base_id",    text="Base Actor ID")

        if name:
            row = layout.row()
            row.enabled = False
            row.label(text=f"ISO: {_iso(name)}   Nick: {_nick(name)}", icon="INFO")


# ── Scene Setup ──────────────────────────────────────────────────────────────

class OG_PT_Scene(Panel):
    bl_label       = "🎬  Scene"
    bl_idname      = "OG_PT_scene"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        layout.operator("og.spawn_player", text="Add Player Spawn", icon="ARMATURE_DATA")


# ── Place Objects ─────────────────────────────────────────────────────────────

class OG_PT_PlaceObjects(Panel):
    bl_label       = "➕  Place Objects"
    bl_idname      = "OG_PT_place_objects"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        etype  = props.entity_type
        einfo  = ENTITY_DEFS.get(etype, {})

        layout.prop(props, "entity_type", text="")

        if etype == "crate":
            layout.prop(props, "crate_type", text="Crate Type")

        # ── Wiki image + description preview ──────────────────────────────
        _draw_wiki_preview(layout, etype, ctx)

        # ── Spawn requirements info box ───────────────────────────────────
        if einfo.get("is_prop"):
            box = layout.box()
            box.label(text="Prop — idle animation only", icon="INFO")
            box.label(text="No AI or combat")
        elif etype in NAV_UNSAFE_TYPES:
            box = layout.box()
            box.label(text="Nav-enemy — needs navmesh", icon="ERROR")
            box.prop(props, "nav_radius", text="Sphere Radius (m)")
        elif einfo.get("needs_pathb"):
            box = layout.box()
            box.label(text="Needs 2 path sets", icon="INFO")
            box.label(text="Waypoints: _wp_00... and _wpb_00...")
        elif einfo.get("needs_path"):
            box = layout.box()
            box.label(text="Needs waypoints to patrol", icon="INFO")

        layout.separator(factor=0.3)
        layout.operator("og.spawn_entity", text="Add Entity", icon="ADD")


# ── Waypoints ─────────────────────────────────────────────────────────────────

class OG_PT_Waypoints(Panel):
    bl_label       = "〰  Waypoints"
    bl_idname      = "OG_PT_waypoints"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        """Only show panel when an actor that can use waypoints is selected."""
        sel = ctx.active_object
        if not sel or not sel.name.startswith("ACTOR_") or "_wp_" in sel.name:
            return False
        parts = sel.name.split("_", 2)
        if len(parts) < 3:
            return False
        return _actor_uses_waypoints(parts[1])

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object
        etype  = sel.name.split("_", 2)[1]
        einfo  = ENTITY_DEFS.get(etype, {})

        # ── Primary path ─────────────────────────────────────────────────────
        prefix = sel.name + "_wp_"
        wps = sorted(
            [o for o in bpy.data.objects if o.name.startswith(prefix) and o.type == "EMPTY"],
            key=lambda o: o.name
        )

        layout.label(text=f"Path  ({len(wps)} point{'s' if len(wps) != 1 else ''})", icon="ANIM")

        if wps:
            col = layout.column(align=True)
            for wp in wps:
                row = col.row(align=True)
                row.label(text=wp.name, icon="EMPTY_AXIS")
                op = row.operator("og.delete_waypoint", text="", icon="X")
                op.wp_name = wp.name
        else:
            layout.label(text="No waypoints yet", icon="INFO")

        op = layout.operator("og.add_waypoint", text="Add Waypoint at Cursor", icon="PLUS")
        op.enemy_name = sel.name
        op.pathb_mode = False

        if einfo.get("needs_path") and len(wps) < 1:
            layout.label(text="⚠ Needs ≥ 1 waypoint or will crash", icon="ERROR")

        # ── Secondary path (swamp-bat only) ──────────────────────────────────
        if einfo.get("needs_pathb"):
            _header_sep(layout)
            prefixb = sel.name + "_wpb_"
            wpsb = sorted(
                [o for o in bpy.data.objects if o.name.startswith(prefixb) and o.type == "EMPTY"],
                key=lambda o: o.name
            )
            layout.label(text=f"Path B — slave bats  ({len(wpsb)} points)", icon="ANIM")
            if wpsb:
                col2 = layout.column(align=True)
                for wp in wpsb:
                    row = col2.row(align=True)
                    row.label(text=wp.name, icon="EMPTY_AXIS")
                    op2 = row.operator("og.delete_waypoint", text="", icon="X")
                    op2.wp_name = wp.name
            else:
                layout.label(text="No Path B waypoints yet", icon="INFO")

            op3 = layout.operator("og.add_waypoint", text="Add Path B Waypoint at Cursor", icon="PLUS")
            op3.enemy_name = sel.name
            op3.pathb_mode = True

            if len(wpsb) < 1:
                layout.label(text="⚠ swamp-bat crashes without Path B", icon="ERROR")


# ── NavMesh ───────────────────────────────────────────────────────────────────


class OG_OT_SpawnCamera(Operator):
    bl_idname = "og.spawn_camera"
    bl_label  = "Add Camera"
    bl_description = "Place a camera entity at the 3D cursor (placeholder — switching coming soon)"
    def execute(self, ctx):
        n = len([o for o in ctx.scene.objects if o.name.startswith("CAMERA_") and o.type == "EMPTY"])
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"CAMERA_{n}"
        o.show_name = True
        o.empty_display_size = 0.8
        o.color = (0.0, 0.8, 0.9, 1.0)
        self.report({"INFO"}, f"Added {o.name} — camera switching coming soon!")
        return {"FINISHED"}


class OG_PT_Camera(Panel):
    bl_label       = "📷  Camera"
    bl_idname      = "OG_PT_camera"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx): return True

    def draw(self, ctx):
        layout = self.layout
        layout.operator("og.spawn_camera", text="Add Camera", icon="CAMERA_DATA")
        layout.separator()
        box = layout.box()
        box.label(text="Camera switching: coming soon", icon="INFO")


class OG_PT_NavMesh(Panel):
    bl_label       = "🕸  NavMesh"
    bl_idname      = "OG_PT_navmesh"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        """Only show when a nav-enemy actor or a linked navmesh mesh is selected."""
        sel = ctx.active_object
        if not sel:
            return False
        # Actor selected — show only if it's a nav-enemy
        if sel.name.startswith("ACTOR_") and "_wp_" not in sel.name:
            parts = sel.name.split("_", 2)
            if len(parts) >= 3:
                return _actor_uses_navmesh(parts[1])
            return False
        # Mesh selected — show if it's tagged as a navmesh or linked to any actor
        if sel.type == "MESH":
            if sel.get("og_navmesh"):
                return True
            for o in bpy.data.objects:
                if o.get("og_navmesh_link") in (sel.name,
                        sel.name if sel.name.startswith("NAVMESH_")
                        else "NAVMESH_" + sel.name):
                    return True
        return False

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # ── Actor selected ────────────────────────────────────────────────────
        if sel and sel.name.startswith("ACTOR_") and "_wp_" not in sel.name:
            parts = sel.name.split("_", 2)
            etype = parts[1] if len(parts) >= 3 else ""
            einfo = ENTITY_DEFS.get(etype, {})

            if not _actor_uses_navmesh(etype):
                box = layout.box()
                box.label(text=f"{etype} doesn't use navmesh", icon="INFO")
                ai = einfo.get("ai_type", "?")
                box.label(text=f"AI type: {ai}")
                return

            layout.label(text=f"Enemy: {sel.name}", icon="OBJECT_DATA")

            # Object picker stored as custom property og_navmesh_obj
            nm_name = sel.get("og_navmesh_link", "")
            nm_obj  = bpy.data.objects.get(nm_name) if nm_name else None

            # Current link status
            row = layout.row(align=True)
            if nm_obj:
                row.label(text=nm_obj.name, icon="MESH_DATA")
                row.operator("og.unlink_navmesh", text="", icon="X")
            else:
                layout.label(text="No mesh linked", icon="ERROR")

            # Link instruction + button
            if nm_obj:
                layout.operator("og.unlink_navmesh", text="Unlink NavMesh", icon="UNLINKED")
            else:
                box2 = layout.box()
                box2.label(text="To link:", icon="INFO")
                box2.label(text="1. Select enemy + navmesh quad")
                box2.label(text="   (either order, shift-click both)")
                box2.label(text="2. Click Link below")
                box2.operator("og.link_navmesh", text="Link NavMesh", icon="LINKED")

            # Status
            if nm_obj:
                try:
                    nm_obj.data.calc_loop_triangles()
                    pc = len(nm_obj.data.loop_triangles)
                except Exception:
                    pc = 0
                box = layout.box()
                box.label(text=f"✓ Linked: {nm_obj.name}", icon="CHECKMARK")
                box.label(text=f"{pc} triangles")
            else:
                box = layout.box()
                box.label(text="No navmesh linked!", icon="ERROR")
                box.label(text="Enemy will use underground default")
                box.label(text="→ never chases Jak")

        # ── NavMesh mesh selected ─────────────────────────────────────────────
        elif sel and sel.type == "MESH":
            # Check both the current name and the NAVMESH_-prefixed version
            # (link operator may have just renamed it)
            linked = [o for o in bpy.data.objects
                      if o.get("og_navmesh_link") in (sel.name,
                         sel.name if sel.name.startswith("NAVMESH_")
                         else "NAVMESH_" + sel.name)]
            box = layout.box()
            if sel.get("og_navmesh") or linked:
                box.label(text=f"NavMesh: {sel.name}", icon="MOD_MESHDEFORM")
                if linked:
                    box.label(text=f"{len(linked)} actor(s) linked:")
                    for o in linked:
                        row = box.row(align=True)
                        row.label(text=f"  {o.name}", icon="OBJECT_DATA")
                else:
                    box.label(text="No actors linked yet", icon="INFO")
                    box.label(text="Select enemy + this mesh, click Link", icon="INFO")
            else:
                box.label(text="Not a navmesh object", icon="INFO")
                box.label(text="Select enemy + this mesh, click Link", icon="INFO")

        # ── Nothing useful selected ───────────────────────────────────────────
        else:
            layout.label(text="Select a nav-enemy actor", icon="INFO")
            layout.label(text="to link a navmesh to it")


# ── Build & Play ──────────────────────────────────────────────────────────────

class OG_PT_BuildPlay(Panel):
    bl_label       = "▶  Build & Play"
    bl_idname      = "OG_PT_build_play"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"

    def draw(self, ctx):
        layout = self.layout
        gk_ok  = _gk().exists()
        gc_ok  = _goalc().exists()
        gp_ok  = _game_gp().exists()

        if not (gk_ok and gc_ok and gp_ok):
            box = layout.box()
            box.label(text="Missing paths — open Developer Tools", icon="ERROR")
            layout.separator(factor=0.3)

        col = layout.column(align=True)
        col.scale_y = 1.8
        col.operator("og.export_build",  text="⚙  Export & Compile",        icon="EXPORT")
        col.scale_y = 1.4
        col.operator("og.geo_rebuild",   text="🔄  Quick Geo Rebuild",       icon="FILE_REFRESH")
        col.scale_y = 1.8
        col.operator("og.play",          text="▶  Launch Game (Debug)",      icon="PLAY")
        col.scale_y = 1.4
        col.operator("og.play_autoload", text="⚡  Launch & Auto-Load Level", icon="SEQUENCE_COLOR_04")


# ── Developer Tools ───────────────────────────────────────────────────────────

class OG_PT_DevTools(Panel):
    bl_label       = "🔧  Developer Tools"
    bl_idname      = "OG_PT_dev_tools"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout

        # Paths
        layout.label(text="Paths", icon="PREFERENCES")
        box = layout.box()
        gk_ok = _gk().exists()
        gc_ok = _goalc().exists()
        gp_ok = _game_gp().exists()
        box.label(text=f"gk.exe:    {'✓ OK' if gk_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gk_ok else "ERROR")
        box.label(text=f"goalc.exe: {'✓ OK' if gc_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gc_ok else "ERROR")
        box.label(text=f"game.gp:   {'✓ OK' if gp_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gp_ok else "ERROR")
        box.operator("preferences.addon_show", text="Set EXE / Data Paths", icon="PREFERENCES").module = __name__

        layout.separator()

        # Quick Open — nested here
        layout.label(text="Quick Open", icon="FILE_FOLDER")
        name = ctx.scene.og_props.level_name.strip().lower().replace(" ", "-")
        self._quick_open(layout, name)

    def _btn(self, layout, label, icon, path, is_file=False):
        p = Path(path) if path else None
        row = layout.row(align=True)
        row.enabled = bool(path)
        if is_file:
            op = row.operator("og.open_file",   text=label, icon=icon)
            op.filepath = str(p) if p else ""
        else:
            op = row.operator("og.open_folder", text=label, icon=icon)
            op.folder = str(p) if p else ""
        if p and not p.exists():
            row.label(text="", icon="ERROR")

    def _quick_open(self, layout, name):
        col = layout.column(align=True)
        self._btn(col, "goal_src/",    "FILE_FOLDER", str(_goal_src()) if _goal_src().parent.exists() else "")
        self._btn(col, "game.gp",      "FILE_SCRIPT", str(_game_gp()), is_file=True)
        self._btn(col, "level-info.gc","FILE_SCRIPT", str(_level_info()), is_file=True)
        self._btn(col, "entity.gc",    "FILE_SCRIPT", str(_entity_gc()), is_file=True)

        if name:
            layout.separator(factor=0.3)
            ldir       = _ldir(name)
            goal_level = _goal_src() / "levels" / name
            col2 = layout.column(align=True)
            self._btn(col2, f"{name}/",           "FILE_FOLDER", str(ldir))
            self._btn(col2, f"{name}.jsonc",      "FILE_TEXT",   str(ldir / f"{name}.jsonc"), is_file=True)
            self._btn(col2, f"{name}.glb",        "FILE_3D",     str(ldir / f"{name}.glb"),   is_file=True)
            self._btn(col2, f"{_nick(name)}.gd",  "FILE_SCRIPT", str(ldir / f"{_nick(name)}.gd"), is_file=True)
            self._btn(col2, f"{name}-obs.gc",     "FILE_SCRIPT", str(goal_level / f"{name}-obs.gc"), is_file=True)

        layout.separator(factor=0.3)
        col3 = layout.column(align=True)
        self._btn(col3, "custom_assets/", "FILE_FOLDER", str(_data() / "custom_assets" / "jak1" / "levels"))
        self._btn(col3, "Game logs",      "SCRIPT",      str(_data_root() / "data" / "log"))
        self._btn(col3, "startup.gc",     "FILE_SCRIPT", str(_user_dir() / "startup.gc"), is_file=True)


# ── Collision (per-object, separate panel) ────────────────────────────────────

class OG_PT_Collision(Panel):
    bl_label       = "OpenGOAL Collision"
    bl_idname      = "OG_PT_collision"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx): return ctx.active_object is not None

    def draw(self, ctx):
        layout = self.layout
        ob     = ctx.active_object

        # Actor info summary
        if ob.name.startswith("ACTOR_") and "_wp_" not in ob.name:
            parts = ob.name.split("_", 2)
            if len(parts) >= 3:
                etype = parts[1]
                einfo = ENTITY_DEFS.get(etype, {})
                box = layout.box()
                box.label(text=f"{etype}", icon="OBJECT_DATA")
                box.label(text=f"AI: {einfo.get('ai_type', '?')}")
                nm = ob.get("og_navmesh_link", "")
                if nm:
                    box.label(text=f"NavMesh: {nm}", icon="LINKED")
                elif einfo.get("ai_type") == "nav-enemy":
                    box.label(text="No navmesh linked!", icon="ERROR")
                layout.separator(factor=0.3)

        layout.prop(ob, "set_invisible")
        layout.prop(ob, "enable_custom_weights")
        layout.prop(ob, "copy_eye_draws")
        layout.prop(ob, "copy_mod_draws")
        layout.prop(ob, "set_collision")
        if ob.set_collision:
            col = layout.column()
            col.prop(ob, "ignore")
            col.prop(ob, "collide_mode")
            col.prop(ob, "collide_material")
            col.prop(ob, "collide_event")
            r = col.row(align=True)
            r.prop(ob, "noedge");  r.prop(ob, "noentity")
            r2 = col.row(align=True)
            r2.prop(ob, "nolineofsight"); r2.prop(ob, "nocamera")


def _draw_mat(self, ctx):
    ob = ctx.object
    if not ob or not ob.active_material: return
    mat    = ob.active_material
    layout = self.layout
    layout.prop(mat, "set_invisible")
    layout.prop(mat, "set_collision")
    if mat.set_collision:
        layout.prop(mat, "ignore")
        layout.prop(mat, "collide_mode")
        layout.prop(mat, "collide_material")
        layout.prop(mat, "collide_event")
        layout.prop(mat, "noedge"); layout.prop(mat, "noentity")
        layout.prop(mat, "nolineofsight"); layout.prop(mat, "nocamera")


# ---------------------------------------------------------------------------
# OPERATOR — Pick NavMesh (eyedropper-style via active selection)
# ---------------------------------------------------------------------------

class OG_OT_PickNavMesh(Operator):
    """Link the active mesh object as the navmesh for the selected enemy actor.
    Select the enemy, then shift-click the navmesh quad, then click this button."""
    bl_idname      = "og.pick_navmesh"
    bl_label       = "Pick NavMesh Mesh"
    bl_description = "Select enemy actor(s) + navmesh mesh (active), then click"

    actor_name: bpy.props.StringProperty()

    def execute(self, ctx):
        actor = bpy.data.objects.get(self.actor_name)
        if not actor:
            self.report({"ERROR"}, f"Actor not found: {self.actor_name}")
            return {"CANCELLED"}

        # Active object must be a mesh to use as navmesh
        active = ctx.active_object
        if not active or active.type != "MESH":
            self.report({"ERROR"}, "Make the navmesh quad the active object (shift-click it last)")
            return {"CANCELLED"}

        if active == actor:
            self.report({"ERROR"}, "Active object must be the navmesh mesh, not the enemy")
            return {"CANCELLED"}

        # Mark it as a navmesh object
        active["og_navmesh"] = True

        # Link actor to this mesh
        actor["og_navmesh_link"] = active.name
        self.report({"INFO"}, f"Linked {actor.name} → {active.name}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# OPERATOR — Light Bake (Cycles → Vertex Color)
# ---------------------------------------------------------------------------

class OG_OT_BakeLighting(Operator):
    """Bake Cycles lighting to vertex colors on each selected mesh object."""
    bl_idname      = "og.bake_lighting"
    bl_label       = "Bake Lighting"
    bl_description = "Bake Cycles lighting to vertex colors on each selected mesh object"

    def execute(self, ctx):
        scene   = ctx.scene
        props   = scene.og_props
        samples = props.lightbake_samples

        # Collect only MESH objects from the selection
        targets = [o for o in ctx.selected_objects if o.type == "MESH"]
        if not targets:
            self.report({"ERROR"}, "No mesh objects selected")
            return {"CANCELLED"}

        # Store previous render settings
        prev_engine  = scene.render.engine
        prev_samples = scene.cycles.samples
        prev_device  = scene.cycles.device

        scene.render.engine  = "CYCLES"
        scene.cycles.samples = samples

        baked = []
        failed = []

        for obj in targets:
            try:
                # Ensure vertex color layer exists (named "BakedLight")
                vc_name = "BakedLight"
                mesh = obj.data
                if vc_name not in mesh.color_attributes:
                    mesh.color_attributes.new(name=vc_name, type="BYTE_COLOR", domain="CORNER")

                # Set as active render and active display layer
                attr = mesh.color_attributes[vc_name]
                mesh.color_attributes.active_color = attr

                # Deselect all, select only this object, make it active
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                ctx.view_layer.objects.active = obj

                # Run Cycles bake — diffuse pass (combined colour + indirect)
                bpy.ops.object.bake(
                    type="DIFFUSE",
                    pass_filter={"COLOR", "DIRECT", "INDIRECT"},
                    target="VERTEX_COLORS",
                    save_mode="INTERNAL",
                )
                baked.append(obj.name)

            except Exception as exc:
                failed.append(f"{obj.name}: {exc}")

        # Restore render settings
        scene.render.engine  = prev_engine
        scene.cycles.samples = prev_samples

        # Restore original selection
        bpy.ops.object.select_all(action="DESELECT")
        for obj in targets:
            obj.select_set(True)
        if targets:
            ctx.view_layer.objects.active = targets[0]

        if failed:
            self.report({"WARNING"}, f"Baked {len(baked)}, failed: {'; '.join(failed)}")
        else:
            self.report({"INFO"}, f"Baked lighting to vertex colors on: {', '.join(baked)}")

        return {"FINISHED"}


# ---------------------------------------------------------------------------
# PANEL — Light Baking
# ---------------------------------------------------------------------------

class OG_PT_LightBaking(Panel):
    bl_label       = "OpenGOAL Light Baking"
    bl_idname      = "OG_PT_lightbaking"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props

        # Sample count input
        col = layout.column(align=True)
        col.label(text="Cycles Bake Settings:", icon="LIGHT")
        col.prop(props, "lightbake_samples")

        layout.separator(factor=0.5)

        # Info about what will be baked
        targets = [o for o in ctx.selected_objects if o.type == "MESH"]
        if targets:
            box = layout.box()
            box.label(text=f"{len(targets)} mesh(es) selected:", icon="OBJECT_DATA")
            for o in targets[:6]:
                box.label(text=f"  • {o.name}")
            if len(targets) > 6:
                box.label(text=f"  … and {len(targets) - 6} more")
        else:
            layout.label(text="Select mesh object(s) to bake", icon="INFO")

        layout.separator(factor=0.5)

        # Bake button — disabled when nothing is selected
        row = layout.row()
        row.enabled = len(targets) > 0
        row.scale_y = 1.6
        row.operator("og.bake_lighting", text="Bake Lighting → Vertex Color", icon="RENDER_STILL")

        layout.separator(factor=0.3)
        layout.label(text="Result stored in 'BakedLight' layer", icon="GROUP_VCOL")


# ---------------------------------------------------------------------------
# REGISTER / UNREGISTER
# ---------------------------------------------------------------------------

classes = (
    OGPreferences, OGProperties,
    OG_OT_SpawnPlayer, OG_OT_SpawnEntity,
    OG_OT_SpawnCamera,
    OG_OT_AddWaypoint, OG_OT_DeleteWaypoint,
    OG_OT_MarkNavMesh, OG_OT_UnmarkNavMesh,
    OG_OT_LinkNavMesh, OG_OT_UnlinkNavMesh,
    OG_OT_PickNavMesh,
    OG_OT_ExportBuild, OG_OT_GeoRebuild, OG_OT_Play, OG_OT_PlayAutoLoad,
    OG_OT_ExportBuildPlay,
    OG_OT_OpenFolder, OG_OT_OpenFile,
    OG_OT_BakeLighting,
    OG_PT_LevelSettings,
    OG_PT_Scene,
    OG_PT_PlaceObjects,
    OG_PT_Waypoints,
    OG_PT_Camera,
    OG_PT_NavMesh,
    OG_PT_BuildPlay,
    OG_PT_DevTools,
    OG_PT_Collision,
    OG_PT_LightBaking,
)

def register():
    _load_previews()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.og_props = PointerProperty(type=OGProperties)

    bpy.types.Material.set_invisible    = bpy.props.BoolProperty(name="Invisible")
    bpy.types.Material.set_collision    = bpy.props.BoolProperty(name="Apply Collision Properties")
    bpy.types.Material.ignore           = bpy.props.BoolProperty(name="ignore")
    bpy.types.Material.noedge           = bpy.props.BoolProperty(name="No-Edge")
    bpy.types.Material.noentity         = bpy.props.BoolProperty(name="No-Entity")
    bpy.types.Material.nolineofsight    = bpy.props.BoolProperty(name="No-LOS")
    bpy.types.Material.nocamera         = bpy.props.BoolProperty(name="No-Camera")
    bpy.types.Material.collide_material = bpy.props.EnumProperty(items=pat_surfaces, name="Material")
    bpy.types.Material.collide_event    = bpy.props.EnumProperty(items=pat_events,   name="Event")
    bpy.types.Material.collide_mode     = bpy.props.EnumProperty(items=pat_modes,    name="Mode")
    bpy.types.MATERIAL_PT_custom_props.prepend(_draw_mat)

    bpy.types.Object.set_invisible         = bpy.props.BoolProperty(name="Invisible")
    bpy.types.Object.set_collision         = bpy.props.BoolProperty(name="Apply Collision Properties")
    bpy.types.Object.enable_custom_weights = bpy.props.BoolProperty(name="Use Custom Bone Weights")
    bpy.types.Object.copy_eye_draws        = bpy.props.BoolProperty(name="Copy Eye Draws")
    bpy.types.Object.copy_mod_draws        = bpy.props.BoolProperty(name="Copy Mod Draws")
    bpy.types.Object.ignore                = bpy.props.BoolProperty(name="ignore")
    bpy.types.Object.noedge                = bpy.props.BoolProperty(name="No-Edge")
    bpy.types.Object.noentity              = bpy.props.BoolProperty(name="No-Entity")
    bpy.types.Object.nolineofsight         = bpy.props.BoolProperty(name="No-LOS")
    bpy.types.Object.nocamera              = bpy.props.BoolProperty(name="No-Camera")
    bpy.types.Object.collide_material      = bpy.props.EnumProperty(items=pat_surfaces, name="Material")
    bpy.types.Object.collide_event         = bpy.props.EnumProperty(items=pat_events,   name="Event")
    bpy.types.Object.collide_mode          = bpy.props.EnumProperty(items=pat_modes,    name="Mode")

def unregister():
    _unload_previews()
    bpy.types.MATERIAL_PT_custom_props.remove(_draw_mat)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "og_props"):
        del bpy.types.Scene.og_props
    for a in ("set_invisible","set_collision","ignore","noedge","noentity",
              "nolineofsight","nocamera","collide_material","collide_event","collide_mode"):
        try: delattr(bpy.types.Material, a)
        except Exception: pass
    for a in ("set_invisible","set_collision","ignore","noedge","noentity",
              "nolineofsight","nocamera","collide_material","collide_event","collide_mode",
              "enable_custom_weights","copy_eye_draws","copy_mod_draws"):
        try: delattr(bpy.types.Object, a)
        except Exception: pass

if __name__ == "__main__":
    register()
