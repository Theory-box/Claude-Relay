bl_info = {
    "name": "OpenGOAL Level Tools",
    "author": "water111 / JohnCheathem",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "View3D > N-Panel > OpenGOAL",
    "description": "Jak 1 level export, actor placement, build and launch tools",
    "category": "Development",
}

import bpy, os, re, json, socket, subprocess, threading, time, math, mathutils
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
    # needs_sync       : True = reads 'sync' res lump (period/phase/easing) for path movement
    # needs_path       : True = reads 'path' res lump (waypoints drive movement directly, e.g. plat-button)
    # needs_notice_dist: True = reads 'notice-dist' lump (plat-eco activation range)
    "plat":             {"label":"Floating Platform",    "cat":"Platforms", "ag":"plat-ag.go",              "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":False, "color":(0.5,0.5,0.8,1.0), "shape":"CUBE"},
    "plat-eco":         {"label":"Eco Platform",         "cat":"Platforms", "ag":"plat-eco-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":True,  "color":(0.3,0.7,0.9,1.0), "shape":"CUBE"},
    "plat-button":      {"label":"Button Platform",      "cat":"Platforms", "ag":"plat-button-ag.go",       "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.6,0.7,1.0), "shape":"CUBE"},
    "plat-flip":        {"label":"Flip Platform",        "cat":"Platforms", "ag":"plat-flip-ag.go",         "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.5,0.7,1.0), "shape":"CUBE"},
    "wall-plat":        {"label":"Wall Platform",        "cat":"Platforms", "ag":"wall-plat-ag.go",         "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.4,0.5,0.7,1.0), "shape":"CUBE"},
    "balance-plat":     {"label":"Balance Platform",     "cat":"Platforms", "ag":"balance-plat-ag.go",      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.6,0.8,1.0), "shape":"CUBE"},
    "teetertotter":     {"label":"Teeter Totter",        "cat":"Platforms", "ag":"teetertotter-ag.go",      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.5,0.4,1.0), "shape":"CUBE"},
    "side-to-side-plat":{"label":"Side-to-Side Plat",   "cat":"Platforms", "ag":"side-to-side-plat-ag.go", "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":False, "color":(0.4,0.5,0.8,1.0), "shape":"CUBE"},
    "wedge-plat":       {"label":"Wedge Platform",       "cat":"Platforms", "ag":"wedge-plat-ag.go",        "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.5,0.7,1.0), "shape":"CUBE"},
    "tar-plat":         {"label":"Tar Platform",         "cat":"Platforms", "ag":"tar-plat-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.2,0.2,0.2,1.0), "shape":"CUBE"},
    "revcycle":         {"label":"Rotating Platform",    "cat":"Platforms", "ag":"revcycle-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.4,0.6,1.0), "shape":"CUBE"},
    "launcher":         {"label":"Launcher",             "cat":"Platforms", "ag":"floating-launcher-ag.go", "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.9,0.6,0.1,1.0), "shape":"CONE"},
    "warpgate":         {"label":"Warp Gate",            "cat":"Platforms", "ag":"warpgate-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.3,0.8,0.9,1.0), "shape":"CIRCLE"},
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

# Platform-only enum for the Platforms panel spawn dropdown
PLATFORM_ENUM_ITEMS = [
    (etype, info["label"], info.get("label", etype), i)
    for i, (etype, info) in enumerate(
        sorted(
            [(e, inf) for e, inf in ENTITY_DEFS.items() if inf.get("cat") == "Platforms"],
            key=lambda x: x[1]["label"]
        )
    )
]

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


def _camera_aabb_to_planes(b_min, b_max):
    """Convert an AABB in game-space meters to 6 half-space plane equations.

    Each plane is [nx, ny, nz, d_meters] where a point P (meters) is INSIDE
    the volume when dot(P, normal) <= d for ALL planes.

    The C++ loader (vector_vol_from_json) multiplies the w component by 4096,
    so we provide values in meters here.
    """
    mn = tuple(min(b_min[i], b_max[i]) for i in range(3))
    mx = tuple(max(b_min[i], b_max[i]) for i in range(3))
    return [
        [ 1.0,  0.0,  0.0,  mx[0]],  # +X wall
        [-1.0,  0.0,  0.0, -mn[0]],  # -X wall
        [ 0.0,  1.0,  0.0,  mx[1]],  # +Y ceiling
        [ 0.0, -1.0,  0.0, -mn[1]],  # -Y floor
        [ 0.0,  0.0,  1.0,  mx[2]],  # +Z back
        [ 0.0,  0.0, -1.0, -mn[2]],  # -Z front
    ]


def collect_cameras(scene):
    """Build camera actor list from CAMERA_ camera objects.

    Returns (camera_actors, trigger_actors) where both are JSONC actor dicts.
    camera_actors  -- camera-marker entities (hold position/rotation)
    trigger_actors -- camera-trigger entities (AABB polling, birth on level load)
    """
    cam_objects = sorted(
        [o for o in scene.objects
         if o.name.startswith("CAMERA_") and o.type == "CAMERA"],
        key=lambda o: o.name,
    )

    vol_by_cam = {}
    for o in scene.objects:
        if o.type == "MESH" and o.name.startswith("VOL_"):
            link = o.get("og_vol_link", "")
            if link:
                vol_by_cam[link] = o

    camera_actors  = []
    trigger_actors = []

    for cam_obj in cam_objects:
        cam_name = cam_obj.name

        loc = cam_obj.matrix_world.translation
        gx = round(loc.x, 4)
        gy = round(loc.z, 4)
        gz = round(-loc.y, 4)

        # Blender -> game camera quaternion.
        #
        # 1. Extract camera look direction: -local_Z of matrix_world (BL cam looks along -Z)
        # 2. Remap to game space: (bl.x, bl.z, -bl.y)  -- same as position remap
        # 3. Build canonical rotation via forward-down->inv-matrix style (world-down roll ref)
        # 4. Conjugate the result (negate xyz) -- the game's quaternion->matrix reads
        #    the inverse convention from what standard math produces.
        #
        # All four steps confirmed empirically via nREPL inv-camera-rot readback.
        m3 = cam_obj.matrix_world.to_3x3()
        bl_look = -m3.col[2]   # BL camera looks along local -Z (world space)
        # Remap to game space: bl(x,y,z) -> game(x,z,-y)
        gl = mathutils.Vector((bl_look.x, bl_look.z, -bl_look.y))
        gl.normalize()
        # Build canonical game rotation: forward=gl, roll from world down (0,-1,0)
        game_down = mathutils.Vector((0.0, -1.0, 0.0))
        right = gl.cross(game_down)
        if right.length < 1e-6:
            right = mathutils.Vector((1.0, 0.0, 0.0))  # degenerate: straight up/down
        right.normalize()
        up = gl.cross(right)
        up.normalize()
        game_mat = mathutils.Matrix([right, up, gl])
        gq = game_mat.to_quaternion()
        # Game's quaternion->matrix uses the conjugate convention (negate xyz).
        # Confirmed empirically: sending (0,-0.7071,0,0.7071) for a BL +X camera
        # produced r2=(-1,0,0) in game. Conjugate fixes it to r2=(+1,0,0).
        qx = round(-gq.x, 6)
        qy = round(-gq.y, 6)
        qz = round(-gq.z, 6)
        qw = round( gq.w, 6)

        cam_mode = cam_obj.get("og_cam_mode",  "fixed")
        interp_t = float(cam_obj.get("og_cam_interp", 1.0))
        fov_deg  = float(cam_obj.get("og_cam_fov",    0.0))

        lump = {"name": cam_name}
        lump["interpTime"] = ["float", round(interp_t, 3)]
        if fov_deg > 0.0:
            lump["fov"] = ["degrees", round(fov_deg, 2)]

        # Look-at target: export "interesting" lump (bypasses quaternion entirely)
        look_at_name = cam_obj.get("og_cam_look_at", "").strip()
        if look_at_name:
            look_obj = scene.objects.get(look_at_name)
            if look_obj:
                lt = look_obj.matrix_world.translation
                lump["interesting"] = ["vector3m", [round(lt.x,4), round(lt.z,4), round(-lt.y,4)]]
                log(f"  [camera] {cam_name} look-at -> {look_at_name} game({lump['interesting'][1]})")
            else:
                log(f"  [camera] WARNING: look-at object '{look_at_name}' not found in scene")
        if cam_mode == "standoff":
            align_name = cam_name + "_ALIGN"
            align_obj  = scene.objects.get(align_name)
            if align_obj:
                al = align_obj.matrix_world.translation
                lump["trans"] = ["vector3m", [round(al.x,4), round(al.z,4), round(-al.y,4)]]
                lump["align"] = ["vector3m", [gx, gy, gz]]
                log(f"  [camera] {cam_name} standoff -- align={align_name}")
            else:
                log(f"  [camera] WARNING: {cam_name} standoff but no {align_name}")
        elif cam_mode == "orbit":
            pivot_name = cam_name + "_PIVOT"
            pivot_obj  = scene.objects.get(pivot_name)
            if pivot_obj:
                pl = pivot_obj.matrix_world.translation
                lump["trans"] = ["vector3m", [gx, gy, gz]]
                lump["pivot"] = ["vector3m", [round(pl.x,4), round(pl.z,4), round(-pl.y,4)]]
                log(f"  [camera] {cam_name} orbit -- pivot={pivot_name}")
            else:
                log(f"  [camera] WARNING: {cam_name} orbit but no {pivot_name}")

        camera_actors.append({
            "trans":     [gx, gy, gz],
            "etype":     "camera-marker",
            "game_task": 0,
            "quat":      [qx, qy, qz, qw],
            "vis_id":    0,
            "bsphere":   [gx, gy, gz, 30.0],
            "lump":      lump,
        })

        vol_obj = vol_by_cam.get(cam_name)
        if vol_obj:
            corners = [vol_obj.matrix_world @ v.co for v in vol_obj.data.vertices]
            gc = [(c.x, c.z, -c.y) for c in corners]
            xs = [c[0] for c in gc]; ys = [c[1] for c in gc]; zs = [c[2] for c in gc]
            cx = round((min(xs)+max(xs))/2, 4)
            cy = round((min(ys)+max(ys))/2, 4)
            cz = round((min(zs)+max(zs))/2, 4)
            rad = round(max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))/2 + 5.0, 2)
            trigger_actors.append({
                "trans":     [cx, cy, cz],
                "etype":     "camera-trigger",
                "game_task": 0,
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [cx, cy, cz, rad],
                "lump": {
                    "name":       f"camtrig-{cam_name.lower()}",
                    "cam-name":   cam_name,
                    "bound-xmin": ["meters", round(min(xs), 4)],
                    "bound-xmax": ["meters", round(max(xs), 4)],
                    "bound-ymin": ["meters", round(min(ys), 4)],
                    "bound-ymax": ["meters", round(max(ys), 4)],
                    "bound-zmin": ["meters", round(min(zs), 4)],
                    "bound-zmax": ["meters", round(max(zs), 4)],
                },
            })
            log(f"  [camera] {cam_name} + trigger {vol_obj.name}")
        else:
            log(f"  [camera] {cam_name} -- no trigger volume")

    return camera_actors, trigger_actors


def write_gc(name, has_triggers=False, has_checkpoints=False):
    """Write obs.gc: always emits camera-marker type; if has_triggers also
    emits camera-trigger type; if has_checkpoints emits checkpoint-trigger type.
    All types birth automatically via entity-actor.birth! — no nREPL needed.
    """
    d = _goal_src() / "levels" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-obs.gc"

    lines = [
        ";;-*-Lisp-*-",
        "(in-package goal)",
        f";; {name}-obs.gc -- auto-generated by OpenGOAL Level Tools",
        "",
        ";; camera-marker: inert entity that holds camera position/rotation.",
        "(deftype camera-marker (process-drawable)",
        "  ()",
        "  (:states camera-marker-idle))",
        "",
        "(defstate camera-marker-idle (camera-marker)",
        "  :code (behavior () (loop (suspend))))",
        "",
        "(defmethod init-from-entity! ((this camera-marker) (arg0 entity-actor))",
        "  (set! (-> this root) (new (quote process) (quote trsqv)))",
        "  (process-drawable-from-entity! this arg0)",
        "  (go camera-marker-idle)",
        "  (none))",
        "",
    ]

    if has_triggers:
        lines += [
            ";; camera-trigger: AABB volume entity that switches the active camera.",
            ";; Reads bounds from meters lumps; reads cam-name string lump.",
            ";; No nREPL call needed -- births automatically on level load.",
            "(deftype camera-trigger (process-drawable)",
            "  ((cam-name  string  :offset-assert 176)",
            "   (xmin      float   :offset-assert 180)",
            "   (xmax      float   :offset-assert 184)",
            "   (ymin      float   :offset-assert 188)",
            "   (ymax      float   :offset-assert 192)",
            "   (zmin      float   :offset-assert 196)",
            "   (zmax      float   :offset-assert 200)",
            "   (inside    symbol  :offset-assert 204))",
            "  :heap-base #x60",
            "  :size-assert #xd0",
            "  (:states camera-trigger-active))",
            "",
            "(defstate camera-trigger-active (camera-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when *target*",
            "        (let* ((pos (-> *target* control trans))",
            "               (in-vol (and",
            "                 (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                 (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                 (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))))",
            "          (cond",
            "            ((and in-vol (not (-> self inside)))",
            "             (set! (-> self inside) #t)",
            "             (send-event *camera* (quote change-to-entity-by-name) (-> self cam-name)))",
            "            ((and (not in-vol) (-> self inside))",
            "             (set! (-> self inside) #f)",
            "             (send-event *camera* (quote clear-entity))))))",
            "      (suspend))))",
            "",
            "(defmethod init-from-entity! ((this camera-trigger) (arg0 entity-actor))",
            "  (set! (-> this root) (new (quote process) (quote trsqv)))",
            "  (process-drawable-from-entity! this arg0)",
            "  (set! (-> this cam-name) (res-lump-struct arg0 (quote cam-name) string))",
            "  (set! (-> this xmin) (res-lump-float arg0 (quote bound-xmin)))",
            "  (set! (-> this xmax) (res-lump-float arg0 (quote bound-xmax)))",
            "  (set! (-> this ymin) (res-lump-float arg0 (quote bound-ymin)))",
            "  (set! (-> this ymax) (res-lump-float arg0 (quote bound-ymax)))",
            "  (set! (-> this zmin) (res-lump-float arg0 (quote bound-zmin)))",
            "  (set! (-> this zmax) (res-lump-float arg0 (quote bound-zmax)))",
            "  (set! (-> this inside) #f)",
            "  (go camera-trigger-active)",
            "  (none))",
            "",
        ]
        log(f"  [write_gc] camera-trigger type embedded")

    if has_checkpoints:
        lines += [
            ";; checkpoint-trigger: invisible entity that calls set-continue! when Jak enters.",
            ";; Two modes depending on lumps present:",
            ";;   Sphere mode (default): polls distance against 'radius lump.",
            ";;   AABB mode (when has-volume lump = 1): polls against 6 bound-* lumps.",
            ";; One-shot — triggered flag latches, never fires again this session.",
            "(deftype checkpoint-trigger (process-drawable)",
            "  ((cp-name   string  :offset-assert 176)",
            "   (radius    float   :offset-assert 180)",
            "   (triggered symbol  :offset-assert 184)",
            "   (use-vol   symbol  :offset-assert 188)",
            "   (xmin      float   :offset-assert 192)",
            "   (xmax      float   :offset-assert 196)",
            "   (ymin      float   :offset-assert 200)",
            "   (ymax      float   :offset-assert 204)",
            "   (zmin      float   :offset-assert 208)",
            "   (zmax      float   :offset-assert 212))",
            "  :heap-base #x70",
            "  :size-assert #xd8",
            "  (:states checkpoint-trigger-active))",
            "",
            "(defstate checkpoint-trigger-active (checkpoint-trigger)",
            "  :code",
            "  (behavior ()",
            "    (loop",
            "      (when (and *target* (not (-> self triggered)))",
            "        (let* ((pos (-> *target* control trans))",
            "               (inside (if (-> self use-vol)",
            "                 (and",
            "                   (< (-> self xmin) (-> pos x)) (< (-> pos x) (-> self xmax))",
            "                   (< (-> self ymin) (-> pos y)) (< (-> pos y) (-> self ymax))",
            "                   (< (-> self zmin) (-> pos z)) (< (-> pos z) (-> self zmax)))",
            "                 (let* ((dx (- (-> pos x) (-> self root trans x)))",
            "                        (dy (- (-> pos y) (-> self root trans y)))",
            "                        (dz (- (-> pos z) (-> self root trans z)))",
            "                        (r  (-> self radius)))",
            "                   (< (+ (* dx dx) (* dy dy) (* dz dz)) (* r r))))))",
            "          (when inside",
            "            (set! (-> self triggered) #t)",
            "            (set-continue! *game-info* (-> self cp-name)))))",
            "      (suspend))))",
            "",
            "(defmethod init-from-entity! ((this checkpoint-trigger) (arg0 entity-actor))",
            "  (set! (-> this root) (new (quote process) (quote trsqv)))",
            "  (process-drawable-from-entity! this arg0)",
            "  (set! (-> this cp-name)   (res-lump-struct arg0 (quote continue-name) string))",
            "  (set! (-> this radius)    (res-lump-float  arg0 (quote radius)     :default 12288.0))",
            "  (set! (-> this triggered) #f)",
            "  (set! (-> this use-vol)   (!= 0 (the int (res-lump-value arg0 (quote has-volume) uint128))))",
            "  (set! (-> this xmin)      (res-lump-float arg0 (quote bound-xmin)))",
            "  (set! (-> this xmax)      (res-lump-float arg0 (quote bound-xmax)))",
            "  (set! (-> this ymin)      (res-lump-float arg0 (quote bound-ymin)))",
            "  (set! (-> this ymax)      (res-lump-float arg0 (quote bound-ymax)))",
            "  (set! (-> this zmin)      (res-lump-float arg0 (quote bound-zmin)))",
            "  (set! (-> this zmax)      (res-lump-float arg0 (quote bound-zmax)))",
            "  (go checkpoint-trigger-active)",
            "  (none))",
            "",
        ]
        log(f"  [write_gc] checkpoint-trigger type embedded")

    new_text = "\n".join(lines)
    if p.exists() and p.read_text() == new_text:
        log(f"Skipped {p} (unchanged)")
    else:
        p.write_text(new_text)
        log(f"Wrote {p}")



# ---------------------------------------------------------------------------
# ADDON PREFERENCES
# ---------------------------------------------------------------------------

class OGPreferences(AddonPreferences):
    bl_idname = __name__

    exe_path: StringProperty(
        name="EXE folder",
        description=(
            "Folder containing the OpenGOAL executables (gk / gk.exe and goalc / goalc.exe). "
            "Usually the versioned release folder, e.g. .../opengoal/v0.2.29/"
        ),
        subtype="DIR_PATH",
        default="",
    )
    data_path: StringProperty(
        name="Data folder",
        description=(
            "Your active jak1 source folder — the one that contains data/goal_src. "
            "Usually .../jak-project/ or .../active/jak1/"
        ),
        subtype="DIR_PATH",
        default="",
    )
    def draw(self, ctx):
        layout = self.layout
        layout.label(text="EXE folder — contains gk / goalc executables:")
        layout.prop(self, "exe_path", text="")
        layout.label(text="Data folder — contains data/goal_src (e.g. your jak-project folder):")
        layout.prop(self, "data_path", text="")

# ---------------------------------------------------------------------------
# PATH HELPERS
# ---------------------------------------------------------------------------

import sys as _sys
_EXE = ".exe" if _sys.platform == "win32" else ""   # platform-aware exe extension

GOALC_PORT    = 8181   # runtime default; updated by launch_goalc() and _load_port_file()
GOALC_TIMEOUT = 120

import tempfile as _tempfile
_PORT_FILE = Path(_tempfile.gettempdir()) / "opengoal_blender_goalc.port"

def _save_port_file(port):
    try:
        _PORT_FILE.write_text(str(port))
    except Exception:
        pass

def _load_port_file():
    """Read port from previous launch. Only applies if goalc is still running."""
    global GOALC_PORT
    try:
        if _PORT_FILE.exists() and _process_running(f"goalc{_EXE}"):
            port = int(_PORT_FILE.read_text().strip())
            if 1024 <= port <= 65535:
                GOALC_PORT = port
                log(f"[nREPL] restored port {port} from port file")
    except Exception:
        pass

def _delete_port_file():
    try:
        _PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def _find_free_nrepl_port():
    """Ask the OS for a free port — guaranteed to work on any machine.
    Binds to port 0 (OS assigns a free one), records it, releases it,
    then passes it to GOALC via --port. No scanning, no timeouts.
    """
    import socket as _socket
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log(f"[nREPL] OS-assigned free port: {port}")
    return port

def _strip(p): return p.strip().rstrip("\\").rstrip("/")

def _exe_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.exe_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _data_root():
    prefs = bpy.context.preferences.addons.get(__name__)
    p = prefs.preferences.data_path if prefs else ""
    return Path(_strip(p)) if p.strip() else Path(".")

def _gk():         return _exe_root() / f"gk{_EXE}"
def _goalc():      return _exe_root() / f"goalc{_EXE}"
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
# AUDIO ENUMS
# ---------------------------------------------------------------------------


LEVEL_BANKS = [
    ("none", "None", "", 0),
    ("beach", "beach", "", 1),
    ("citadel", "citadel", "", 2),
    ("darkcave", "darkcave", "", 3),
    ("finalboss", "finalboss", "", 4),
    ("firecanyon", "firecanyon", "", 5),
    ("jungle", "jungle", "", 6),
    ("jungleb", "jungleb", "", 7),
    ("lavatube", "lavatube", "", 8),
    ("maincave", "maincave", "", 9),
    ("misty", "misty", "", 10),
    ("ogre", "ogre", "", 11),
    ("robocave", "robocave", "", 12),
    ("rolling", "rolling", "", 13),
    ("snow", "snow", "", 14),
    ("sunken", "sunken", "", 15),
    ("swamp", "swamp", "", 16),
    ("village1", "village1", "", 17),
    ("village2", "village2", "", 18),
    ("village3", "village3", "", 19),
]

SBK_SOUNDS = {
    "common": ['---close-racerin', '---large-steam-l', '-lav-dark-eco', 'arena', 'arena-steps', 'arenadoor-close', 'arenadoor-open', 'babak-breathin', 'babak-chest', 'babak-dies', 'babak-roar', 'babak-taunt', 'babk-taunt', 'balloon-dies', 'bigshark-alert', 'bigshark-bite', 'bigshark-idle', 'bigshark-taunt', 'bigswing', 'blob-explode', 'blob-land', 'blue-eco-charg', 'blue-eco-idle', 'blue-eco-jak', 'blue-eco-on', 'blue-eco-start', 'blue-light', 'bluesage-fires', 'boat-start', 'boat-stop', 'bomb-open', 'bonelurk-roar', 'bonelurker-dies', 'bonelurker-grunt', 'breath-in', 'breath-in-loud', 'breath-out', 'breath-out-loud', 'bridge-button', 'bridge-hover', 'bully-bounce', 'bully-dies', 'bully-dizzy', 'bully-idle', 'bully-jump', 'bully-land', 'bully-spin1', 'bully-spin2', 'bumper-button', 'bumper-pwr-dwn', 'burst-out', 'buzzer', 'buzzer-pickup', 'caught-eel', 'cave-spatula', 'cave-top-falls', 'cave-top-lands', 'cave-top-rises', 'cell-prize', 'chamber-land', 'chamber-lift', 'close-orb-cash', 'crab-walk1', 'crab-walk2', 'crab-walk3', 'crate-jump', 'crystal-on', 'cursor-l-r', 'cursor-options', 'cursor-up-down', 'darkeco-pool', 'dcrate-break', 'death-darkeco', 'death-drown', 'death-fall', 'death-melt', 'door-lock', 'door-unlock', 'dril-step', 'eco-beam', 'eco-bg-blue', 'eco-bg-green', 'eco-bg-red', 'eco-bg-yellow', 'eco-engine-1', 'eco-engine-2', 'eco-plat-hover', 'eco3', 'ecohit2', 'ecoroom1', 'electric-loop', 'elev-button', 'elev-land', 'eng-shut-down', 'eng-start-up', 'explosion', 'explosion-2', 'fire-boulder', 'fire-crackle', 'fire-loop', 'fish-spawn', 'flame-pot', 'flop-down', 'flop-hit', 'flop-land', 'flut-land-crwood', 'flut-land-dirt', 'flut-land-grass', 'flut-land-pcmeta', 'flut-land-sand', 'flut-land-snow', 'flut-land-stone', 'flut-land-straw', 'flut-land-swamp', 'flut-land-water', 'flut-land-wood', 'flylurk-dies', 'flylurk-idle', 'flylurk-plane', 'flylurk-roar', 'flylurk-taunt', 'foothit', 'gdl-gen-loop', 'gdl-pulley', 'gdl-shut-down', 'gdl-start-up', 'get-all-orbs', 'get-big-fish', 'get-blue-eco', 'get-burned', 'get-fried', 'get-green-eco', 'get-powered', 'get-red-eco', 'get-shocked', 'get-small-fish', 'get-yellow-eco', 'glowing-gen', 'green-eco-idle', 'green-eco-jak', 'green-fire', 'green-steam', 'greensage-fires', 'grunt', 'hand-grab', 'heart-drone', 'helix-dark-eco', 'hit-back', 'hit-dizzy', 'hit-dummy', 'hit-lurk-metal', 'hit-metal', 'hit-metal-big', 'hit-metal-large', 'hit-metal-small', 'hit-metal-tiny', 'hit-temple', 'hit-up', 'ice-breathin', 'ice-loop', 'icelurk-land', 'icelurk-step', 'icrate-break', 'irisdoor1', 'irisdoor2', 'jak-clap', 'jak-deatha', 'jak-idle1', 'jak-shocked', 'jak-stretch', 'jng-piston-dwn', 'jng-piston-up', 'jngb-eggtop-seq', 'jump', 'jump-double', 'jump-long', 'jump-low', 'jump-lurk-metal', 'jungle-part', 'kermit-loop', 'land-crwood', 'land-dirt', 'land-dpsnow', 'land-dwater', 'land-grass', 'land-hard', 'land-metal', 'land-pcmetal', 'land-sand', 'land-snow', 'land-stone', 'land-straw', 'land-swamp', 'land-water', 'land-wood', 'launch-fire', 'launch-idle', 'launch-start', 'lav-blue-vent', 'lav-dark-boom', 'lav-green-vent', 'lav-mine-boom', 'lav-spin-gen', 'lav-yell-vent', 'lava-mines', 'lava-pulley', 'ldoor-close', 'ldoor-open', 'lev-mach-fires', 'lev-mach-idle', 'lev-mach-start', 'loop-racering', 'lurkerfish-swim', 'maindoor', 'mayor-step-carp', 'mayor-step-wood', 'mayors-gears', 'medium-steam-lp', 'menu-close', 'menu-stats', 'miners-fire', 'misty-steam', 'money-pickup', 'mother-charge', 'mother-fire', 'mother-hit', 'mother-track', 'mud', 'mud-lurk-inhale', 'mushroom-gen', 'mushroom-off', 'ogre-rock', 'ogre-throw', 'ogre-windup', 'oof', 'open-orb-cash', 'oracle-awake', 'oracle-sleep', 'pedals', 'pill-pickup', 'piston-close', 'piston-open', 'plat-light-off', 'plat-light-on', 'pontoonten', 'powercell-idle', 'powercell-out', 'prec-button1', 'prec-button2', 'prec-button3', 'prec-button4', 'prec-button6', 'prec-button7', 'prec-button8', 'prec-on-water', 'punch', 'punch-hit', 'ramboss-charge', 'ramboss-dies', 'ramboss-fire', 'ramboss-hit', 'ramboss-idle', 'ramboss-land', 'ramboss-roar', 'ramboss-shield', 'ramboss-step', 'ramboss-taunt', 'ramboss-track', 'red-eco-idle', 'red-eco-jak', 'red-fireball', 'redsage-fires', 'robber-dies', 'robber-idle', 'robber-roar', 'robber-taunt', 'robo-blue-lp', 'robo-warning', 'robot-arm', 'robotcage-lp', 'robotcage-off', 'rock-hover', 'roll-crwood', 'roll-dirt', 'roll-dpsnow', 'roll-dwater', 'roll-grass', 'roll-pcmetal', 'roll-sand', 'roll-snow', 'roll-stone', 'roll-straw', 'roll-swamp', 'roll-water', 'roll-wood', 'rounddoor', 'run-step-left', 'run-step-right', 'sagecage-gen', 'sagecage-off', 'sages-machine', 'sandworm-dies', 'scrate-break', 'scrate-nobreak', 'select-menu', 'select-option', 'select-option2', 'shark-bite', 'shark-dies', 'shark-idle', 'shark-swim', 'shield-zap', 'shldlurk-breathi', 'shldlurk-chest', 'shldlurk-dies', 'shldlurk-roar', 'shldlurk-taunt', 'shut-down', 'sidedoor', 'silo-button', 'slide-crwood', 'slide-dirt', 'slide-dpsnow', 'slide-dwater', 'slide-grass', 'slide-pcmetal', 'slide-sand', 'slide-snow', 'slide-stone', 'slide-straw', 'slide-swamp', 'slide-water', 'slide-wood', 'slider2001', 'smack-surface', 'small-steam-lp', 'snow-bumper', 'snow-pist-cls2', 'snow-pist-cls3', 'snow-pist-opn2', 'snow-pist-opn3', 'snow-piston-cls', 'snow-piston-opn', 'snow-plat-1', 'snow-plat-2', 'snow-plat-3', 'snw-door', 'snw-eggtop-seq', 'spin', 'spin-hit', 'spin-kick', 'spin-pole', 'split-steps', 'start-options', 'start-up', 'steam-long', 'steam-medium', 'steam-short', 'stopwatch', 'sunk-top-falls', 'sunk-top-lands', 'sunk-top-rises', 'swim-dive', 'swim-down', 'swim-flop', 'swim-idle1', 'swim-idle2', 'swim-jump', 'swim-kick-surf', 'swim-kick-under', 'swim-noseblow', 'swim-stroke', 'swim-surface', 'swim-to-down', 'swim-turn', 'swim-up', 'temp-enemy-die', 'touch-pipes', 'uppercut', 'uppercut-hit', 'v3-bridge', 'v3-cartride', 'v3-minecart', 'vent-switch', 'walk-crwood1', 'walk-crwood2', 'walk-dirt1', 'walk-dirt2', 'walk-dpsnow1', 'walk-dpsnow2', 'walk-dwater1', 'walk-dwater2', 'walk-grass1', 'walk-grass2', 'walk-metal1', 'walk-metal2', 'walk-pcmetal1', 'walk-pcmetal2', 'walk-sand1', 'walk-sand2', 'walk-slide', 'walk-snow1', 'walk-snow2', 'walk-step-left', 'walk-step-right', 'walk-stone1', 'walk-stone2', 'walk-straw1', 'walk-straw2', 'walk-swamp1', 'walk-swamp2', 'walk-water1', 'walk-water2', 'walk-wood1', 'walk-wood2', 'warning', 'warpgate-act', 'warpgate-butt', 'warpgate-loop', 'warpgate-tele', 'water-drop', 'water-explosion', 'water-loop', 'water-off', 'water-on', 'waterfall', 'wcrate-break', 'wood-gears2', 'yel-eco-idle', 'yel-eco-jak', 'yellsage-fire', 'yeti-breathin', 'yeti-dies', 'yeti-roar', 'yeti-taunt', 'zoom-boost', 'zoom-hit-crwood', 'zoom-hit-dirt', 'zoom-hit-grass', 'zoom-hit-lava', 'zoom-hit-metal', 'zoom-hit-sand', 'zoom-hit-stone', 'zoom-hit-water', 'zoom-hit-wood', 'zoom-land-crwood', 'zoom-land-dirt', 'zoom-land-grass', 'zoom-land-lava', 'zoom-land-metal', 'zoom-land-sand', 'zoom-land-stone', 'zoom-land-water', 'zoom-land-wood', 'zoom-teleport', 'zoomer-crash-2', 'zoomer-explode', 'zoomer-jump', 'zoomer-melt', 'zoomer-rev1', 'zoomer-rev2'],
    "beach": ['beach-amb2', 'bird', 'cannon-charge', 'cannon-shot', 'crab-slide', 'dirt-crumble', 'drip', 'egg-crack', 'egg-hit', 'falling-egg', 'fuse', 'gears-rumble', 'grotto-pole-hit', 'lurkercrab-dies', 'lurkerdog-bite', 'lurkerdog-dies', 'lurkerdog-idle', 'monkey', 'pelican-flap', 'pelican-gulp', 'puppy-bark', 'rope-stretch', 'sack-incoming', 'sack-land', 'seagull-takeoff', 'shell-down', 'shell-up', 'snap', 'telescope', 'tower-wind2', 'tower-wind3', 'tower-winds', 'vent-rock-break', 'water-lap', 'worm-bite', 'worm-dies', 'worm-idle', 'worm-rise1', 'worm-sink', 'worm-taunt'],
    "citadel": ['assembly-moves', 'bridge-piece-dn', 'bridge-piece-up', 'bunny-attack', 'bunny-dies', 'bunny-taunt-1', 'citadel-amb', 'eco-beam', 'eco-torch', 'elev-button', 'mushroom-break', 'robot-arm', 'rotate-plat', 'sagecage-open', 'snow-bunny1', 'snow-bunny2', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "darkcave": ['bab-spid-dies', 'bab-spid-roar', 'button-1b', 'cavelevator', 'cavewind', 'crystal-explode', 'drill-idle', 'drill-idle2', 'drill-no-start', 'drill-start', 'drill-stop', 'drlurker-dies', 'drlurker-roar', 'eggs-hatch', 'eggs-lands', 'lay-eggs', 'mom-spid-dies', 'mom-spid-roar', 'spatula', 'spider-step', 'trapdoor', 'web-tramp', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "finalboss": ['-bfg-buzz', 'assembly-moves', 'bfg-buzz', 'bfg-fire', 'bfg-fizzle', 'blob-attack', 'blob-dies', 'blob-jump', 'blob-out', 'blob-roar', 'bomb-spin', 'bridge-piece-dn', 'bridge-piece-up', 'charge-loop', 'dark-eco-buzz', 'dark-eco-fire', 'eco-beam', 'eco-torch', 'elev-land', 'explod-bfg', 'explod-bomb', 'explod-eye', 'explosion1', 'explosion2', 'explosion3', 'mushroom-break', 'red-buzz', 'red-explode', 'red-fire', 'robo-hurt', 'robo-servo1', 'robo-servo2', 'robo-servo3', 'robo-servo4', 'robo-servo5', 'robo-servo6', 'robo-servo7', 'robo-servo8', 'robo-servo9', 'robo-taunt', 'robo-yell', 'sagecage-open', 'silo-moves', 'white-eco-beam', 'white-eco-lp', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "firecanyon": ['bubling-lava', 'cool-balloon', 'explod-mine', 'explosion1', 'explosion2', 'lava-amb', 'lava-steam', 'magma-rock', 'zoomer-loop', 'zoomer-start', 'zoomer-stop'],
    "jungle": ['accordian-pump', 'aphid-dies', 'aphid-roar', 'aphid-spike-in', 'aphid-spike-out', 'aphid-step', 'beam-connect', 'bird', 'bug-step', 'cascade', 'darkvine-down', 'darkvine-move', 'darkvine-snap', 'darkvine-up', 'eco-tower-rise', 'eco-tower-stop', 'elev-land', 'elev-loop', 'fish-miss', 'floating-rings', 'frog-dies', 'frog-idle', 'frog-taunt', 'frogspeak', 'jungle-river', 'jungle-shores', 'logtrap1', 'logtrap2', 'lurk-bug', 'lurkerfish-bite', 'lurkerfish-dies', 'lurkerfish-idle', 'lurkerm-hum', 'lurkerm-squeak', 'mirror-smash', 'monkey', 'pc-bridge', 'plant-chomp', 'plant-eye', 'plant-fall', 'plant-laugh', 'plant-leaf', 'plant-ouch', 'plant-recover', 'plant-roar', 'plat-flip', 'site-moves', 'snake-bite', 'snake-drop', 'snake-idle', 'snake-rattle', 'spider-step', 'steam-release', 'telescope', 'trampoline', 'wind-loop'],
    "jungleb": ['accordian-pump', 'beam-connect', 'bird', 'bug-step', 'cascade', 'darkvine-down', 'darkvine-move', 'darkvine-snap', 'darkvine-up', 'eco-tower-rise', 'eco-tower-stop', 'elev-land', 'elev-loop', 'floating-rings', 'frog-dies', 'frog-idle', 'frog-taunt', 'frogspeak', 'jungle-river', 'jungle-shores', 'logtrap1', 'logtrap2', 'lurk-bug', 'lurkerfish-bite', 'lurkerfish-dies', 'lurkerfish-idle', 'lurkerm-hum', 'lurkerm-squeak', 'mirror-smash', 'monkey', 'pc-bridge', 'plant-chomp', 'plant-eye', 'plant-fall', 'plant-laugh', 'plant-leaf', 'plant-ouch', 'plant-recover', 'plant-roar', 'plat-flip', 'site-moves', 'snake-bite', 'snake-drop', 'snake-idle', 'snake-rattle', 'spider-step', 'steam-release', 'telescope', 'trampoline', 'wind-loop'],
    "lavatube": ['ball-explode', 'ball-gen', 'bubling-lava', 'cool-balloon', 'lav-dark-eco', 'lav-mine-chain', 'lava-amb', 'lava-steam', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle', 'zoomer-loop', 'zoomer-start', 'zoomer-stop'],
    "maincave": ['bab-spid-dies', 'bab-spid-roar', 'button-1b', 'cavelevator', 'cavewind', 'crush-click', 'crystal-explode', 'drill-idle2', 'eggs-hatch', 'eggs-lands', 'gnawer-chew', 'gnawer-crawl', 'gnawer-dies', 'gnawer-taunt', 'hot-flame', 'lay-eggs', 'mom-spid-dies', 'mom-spid-grunt', 'mom-spid-roar', 'spatula', 'spider-step', 'trapdoor', 'web-tramp', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "misty": ['barrel-bounce', 'barrel-roll', 'bone-bigswing', 'bone-die', 'bone-freehead', 'bone-helmet', 'bone-smallswing', 'bone-stepl', 'bone-stepr', 'bonebridge-fall', 'cage-boom', 'cannon-charge', 'cannon-shot', 'falling-bones', 'fuse', 'get-muse', 'keg-conveyor', 'mud-lurk-laugh', 'mud-lurker-idle', 'mud-plat', 'mudlurker-dies', 'muse-taunt-1', 'muse-taunt-2', 'paddle-boat', 'propeller', 'qsl-breathin', 'qsl-fire', 'qsl-popup', 'sack-incoming', 'sack-land', 'teeter-launch', 'teeter-rockland', 'teeter-rockup', 'teeter-wobble', 'telescope', 'trade-muse', 'water-lap', 'water-lap-cl0se', 'zoomer-loop', 'zoomer-start', 'zoomer-stop'],
    "ogre": ['bridge-appears', 'bridge-breaks', 'dynomite', 'flylurk-plane', 'hit-lurk-metal', 'hits-head', 'lava-loop', 'lava-plat', 'ogre-amb', 'ogre-boulder', 'ogre-dies', 'ogre-explode', 'ogre-fires', 'ogre-grunt1', 'ogre-grunt2', 'ogre-grunt3', 'ogre-roar1', 'ogre-roar2', 'ogre-roar3', 'ogre-walk', 'ogreboss-out', 'rock-hits-metal', 'rock-in-lava', 'rock-roll', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle', 'zoomer-loop', 'zoomer-start'],
    "robocave": ['bab-spid-dies', 'bab-spid-roar', 'button-1b', 'cavelevator', 'cavewind', 'crush-click', 'drill-hit', 'drill-idle', 'drill-idle2', 'drill-no-start', 'drill-start', 'drill-stop', 'drlurker-dies', 'drlurker-roar', 'eggs-hatch', 'eggs-lands', 'hot-flame', 'lay-eggs', 'mom-spid-dies', 'mom-spid-roar', 'spatula', 'spider-step', 'trapdoor', 'web-tramp', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "rolling": ['close-racering', 'darkvine-grow', 'darkvine-kill', 'darkvine-move', 'get-mole', 'mole-dig', 'mole-taunt-1', 'mole-taunt-2', 'plant-dies', 'plant-move', 'robber-flap', 'roling-amb', 'zoomer-loop', 'zoomer-start', 'zoomer-stop'],
    "snow": ['--snowball-roll', 'bunny-attack', 'bunny-dies', 'bunny-taunt-1', 'flut-coo', 'flut-death', 'flut-flap', 'flut-hit', 'ice-explode', 'ice-monster1', 'ice-monster2', 'ice-monster3', 'ice-monster4', 'ice-spike-in', 'ice-spike-out', 'ice-stop', 'jak-slide', 'lodge-close', 'lodge-door-mov', 'ramboss-laugh', 'ramboss-yell', 'set-ram', 'slam-crash', 'snow-bunny1', 'snow-bunny2', 'snow-engine', 'snow-spat-long', 'snow-spat-short', 'snowball-land', 'snowball-roll', 'walk-ice1', 'walk-ice2', 'winter-amb', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "sunken": ['--submerge', 'chamber-move', 'dark-plat-rise', 'elev-button', 'elev-land', 'elev-loop', 'large-splash', 'plat-flip', 'puffer-change', 'puffer-wing', 'slide-loop', 'splita-charge', 'splita-dies', 'splita-idle', 'splita-roar', 'splita-spot', 'splita-taunt', 'splitb-breathin', 'splitb-dies', 'splitb-roar', 'splitb-spot', 'splitb-taunt', 'sub-plat-rises', 'sub-plat-sinks', 'submerge', 'sunken-amb', 'sunken-pool', 'surface', 'wall-plat', 'whirlpool'],
    "swamp": ['bat-celebrate', 'flut-coo', 'flut-death', 'flut-flap', 'flut-hit', 'kermit-dies', 'kermit-letgo', 'kermit-shoot', 'kermit-speak1', 'kermit-speak2', 'kermit-stretch', 'kermit-taunt', 'land-tar', 'lurkbat-bounce', 'lurkbat-dies', 'lurkbat-idle', 'lurkbat-notice', 'lurkbat-wing', 'lurkrat-bounce', 'lurkrat-dies', 'lurkrat-idle', 'lurkrat-notice', 'lurkrat-walk', 'pole-down', 'pole-up', 'rat-celebrate', 'rat-eat', 'rat-gulp', 'rock-break', 'roll-tar', 'rope-snap', 'rope-stretch', 'slide-tar', 'swamp-amb', 'walk-tar1', 'walk-tar2', 'yellow-buzz', 'yellow-explode', 'yellow-fire', 'yellow-fizzle'],
    "village1": ['-fire-crackle', '-water-lap-cls', 'bird-1', 'bird-2', 'bird-3', 'bird-4', 'bird-house', 'boat-engine', 'boat-splash', 'bubbling-still', 'cage-bird-2', 'cage-bird-4', 'cage-bird-5', 'cricket-single', 'crickets', 'drip-on-wood', 'fire-bubble', 'fly1', 'fly2', 'fly3', 'fly4', 'fly5', 'fly6', 'fly7', 'fly8', 'fountain', 'gear-creak', 'hammer-tap', 'hover-bike-hum', 'ocean-bg', 'seagulls-2', 'snd-', 'temp-enemy-die', 'village-amb', 'water-lap', 'weld', 'welding-loop', 'wind-loop', 'yakow-1', 'yakow-2', 'yakow-grazing', 'yakow-idle', 'yakow-kicked'],
    "village2": ['boulder-splash', 'control-panel', 'hits-head', 'rock-roll', 'spark', 'thunder', 'v2ogre-boulder', 'v2ogre-roar1', 'v2ogre-roar2', 'v2ogre-walk', 'village2-amb', 'wind-chimes'],
    "village3": ['-bubling-lava', 'cave-wind', 'cool-balloon', 'lava-amb', 'lava-erupt', 'lava-steam', 'sulphur'],
}

ALL_SFX_ITEMS = [
    ("breath-in", "[Plyr] breath-in", "", 0),
    ("breath-in-loud", "[Plyr] breath-in-loud", "", 1),
    ("breath-out", "[Plyr] breath-out", "", 2),
    ("breath-out-loud", "[Plyr] breath-out-loud", "", 3),
    ("death-darkeco", "[Plyr] death-darkeco", "", 4),
    ("death-drown", "[Plyr] death-drown", "", 5),
    ("death-fall", "[Plyr] death-fall", "", 6),
    ("death-melt", "[Plyr] death-melt", "", 7),
    ("flop-down", "[Plyr] flop-down", "", 8),
    ("flop-hit", "[Plyr] flop-hit", "", 9),
    ("flop-land", "[Plyr] flop-land", "", 10),
    ("foothit", "[Plyr] foothit", "", 11),
    ("get-burned", "[Plyr] get-burned", "", 12),
    ("get-fried", "[Plyr] get-fried", "", 13),
    ("get-shocked", "[Plyr] get-shocked", "", 14),
    ("hit-back", "[Plyr] hit-back", "", 15),
    ("hit-dizzy", "[Plyr] hit-dizzy", "", 16),
    ("hit-dummy", "[Plyr] hit-dummy", "", 17),
    ("hit-lurk-metal", "[Plyr] hit-lurk-metal", "", 18),
    ("hit-metal", "[Plyr] hit-metal", "", 19),
    ("hit-metal-big", "[Plyr] hit-metal-big", "", 20),
    ("hit-metal-large", "[Plyr] hit-metal-large", "", 21),
    ("hit-metal-small", "[Plyr] hit-metal-small", "", 22),
    ("hit-metal-tiny", "[Plyr] hit-metal-tiny", "", 23),
    ("hit-temple", "[Plyr] hit-temple", "", 24),
    ("hit-up", "[Plyr] hit-up", "", 25),
    ("jak-clap", "[Plyr] jak-clap", "", 26),
    ("jak-deatha", "[Plyr] jak-deatha", "", 27),
    ("jak-idle1", "[Plyr] jak-idle1", "", 28),
    ("jak-shocked", "[Plyr] jak-shocked", "", 29),
    ("jak-stretch", "[Plyr] jak-stretch", "", 30),
    ("jump", "[Plyr] jump", "", 31),
    ("jump-double", "[Plyr] jump-double", "", 32),
    ("jump-long", "[Plyr] jump-long", "", 33),
    ("jump-low", "[Plyr] jump-low", "", 34),
    ("jump-lurk-metal", "[Plyr] jump-lurk-metal", "", 35),
    ("land-crwood", "[Plyr] land-crwood", "", 36),
    ("land-dirt", "[Plyr] land-dirt", "", 37),
    ("land-dpsnow", "[Plyr] land-dpsnow", "", 38),
    ("land-dwater", "[Plyr] land-dwater", "", 39),
    ("land-grass", "[Plyr] land-grass", "", 40),
    ("land-hard", "[Plyr] land-hard", "", 41),
    ("land-metal", "[Plyr] land-metal", "", 42),
    ("land-pcmetal", "[Plyr] land-pcmetal", "", 43),
    ("land-sand", "[Plyr] land-sand", "", 44),
    ("land-snow", "[Plyr] land-snow", "", 45),
    ("land-stone", "[Plyr] land-stone", "", 46),
    ("land-straw", "[Plyr] land-straw", "", 47),
    ("land-swamp", "[Plyr] land-swamp", "", 48),
    ("land-water", "[Plyr] land-water", "", 49),
    ("land-wood", "[Plyr] land-wood", "", 50),
    ("oof", "[Plyr] oof", "", 51),
    ("punch", "[Plyr] punch", "", 52),
    ("punch-hit", "[Plyr] punch-hit", "", 53),
    ("roll-crwood", "[Plyr] roll-crwood", "", 54),
    ("roll-dirt", "[Plyr] roll-dirt", "", 55),
    ("roll-dpsnow", "[Plyr] roll-dpsnow", "", 56),
    ("roll-dwater", "[Plyr] roll-dwater", "", 57),
    ("roll-grass", "[Plyr] roll-grass", "", 58),
    ("roll-pcmetal", "[Plyr] roll-pcmetal", "", 59),
    ("roll-sand", "[Plyr] roll-sand", "", 60),
    ("roll-snow", "[Plyr] roll-snow", "", 61),
    ("roll-stone", "[Plyr] roll-stone", "", 62),
    ("roll-straw", "[Plyr] roll-straw", "", 63),
    ("roll-swamp", "[Plyr] roll-swamp", "", 64),
    ("roll-water", "[Plyr] roll-water", "", 65),
    ("roll-wood", "[Plyr] roll-wood", "", 66),
    ("run-step-left", "[Plyr] run-step-left", "", 67),
    ("run-step-right", "[Plyr] run-step-right", "", 68),
    ("slide-crwood", "[Plyr] slide-crwood", "", 69),
    ("slide-dirt", "[Plyr] slide-dirt", "", 70),
    ("slide-dpsnow", "[Plyr] slide-dpsnow", "", 71),
    ("slide-dwater", "[Plyr] slide-dwater", "", 72),
    ("slide-grass", "[Plyr] slide-grass", "", 73),
    ("slide-pcmetal", "[Plyr] slide-pcmetal", "", 74),
    ("slide-sand", "[Plyr] slide-sand", "", 75),
    ("slide-snow", "[Plyr] slide-snow", "", 76),
    ("slide-stone", "[Plyr] slide-stone", "", 77),
    ("slide-straw", "[Plyr] slide-straw", "", 78),
    ("slide-swamp", "[Plyr] slide-swamp", "", 79),
    ("slide-water", "[Plyr] slide-water", "", 80),
    ("slide-wood", "[Plyr] slide-wood", "", 81),
    ("spin", "[Plyr] spin", "", 82),
    ("spin-hit", "[Plyr] spin-hit", "", 83),
    ("spin-kick", "[Plyr] spin-kick", "", 84),
    ("spin-pole", "[Plyr] spin-pole", "", 85),
    ("swim-dive", "[Plyr] swim-dive", "", 86),
    ("swim-down", "[Plyr] swim-down", "", 87),
    ("swim-flop", "[Plyr] swim-flop", "", 88),
    ("swim-idle1", "[Plyr] swim-idle1", "", 89),
    ("swim-idle2", "[Plyr] swim-idle2", "", 90),
    ("swim-jump", "[Plyr] swim-jump", "", 91),
    ("swim-kick-surf", "[Plyr] swim-kick-surf", "", 92),
    ("swim-kick-under", "[Plyr] swim-kick-under", "", 93),
    ("swim-noseblow", "[Plyr] swim-noseblow", "", 94),
    ("swim-stroke", "[Plyr] swim-stroke", "", 95),
    ("swim-surface", "[Plyr] swim-surface", "", 96),
    ("swim-to-down", "[Plyr] swim-to-down", "", 97),
    ("swim-turn", "[Plyr] swim-turn", "", 98),
    ("swim-up", "[Plyr] swim-up", "", 99),
    ("uppercut", "[Plyr] uppercut", "", 100),
    ("uppercut-hit", "[Plyr] uppercut-hit", "", 101),
    ("walk-crwood1", "[Plyr] walk-crwood1", "", 102),
    ("walk-crwood2", "[Plyr] walk-crwood2", "", 103),
    ("walk-dirt1", "[Plyr] walk-dirt1", "", 104),
    ("walk-dirt2", "[Plyr] walk-dirt2", "", 105),
    ("walk-dpsnow1", "[Plyr] walk-dpsnow1", "", 106),
    ("walk-dpsnow2", "[Plyr] walk-dpsnow2", "", 107),
    ("walk-dwater1", "[Plyr] walk-dwater1", "", 108),
    ("walk-dwater2", "[Plyr] walk-dwater2", "", 109),
    ("walk-grass1", "[Plyr] walk-grass1", "", 110),
    ("walk-grass2", "[Plyr] walk-grass2", "", 111),
    ("walk-metal1", "[Plyr] walk-metal1", "", 112),
    ("walk-metal2", "[Plyr] walk-metal2", "", 113),
    ("walk-pcmetal1", "[Plyr] walk-pcmetal1", "", 114),
    ("walk-pcmetal2", "[Plyr] walk-pcmetal2", "", 115),
    ("walk-sand1", "[Plyr] walk-sand1", "", 116),
    ("walk-sand2", "[Plyr] walk-sand2", "", 117),
    ("walk-slide", "[Plyr] walk-slide", "", 118),
    ("walk-snow1", "[Plyr] walk-snow1", "", 119),
    ("walk-snow2", "[Plyr] walk-snow2", "", 120),
    ("walk-step-left", "[Plyr] walk-step-left", "", 121),
    ("walk-step-right", "[Plyr] walk-step-right", "", 122),
    ("walk-stone1", "[Plyr] walk-stone1", "", 123),
    ("walk-stone2", "[Plyr] walk-stone2", "", 124),
    ("walk-straw1", "[Plyr] walk-straw1", "", 125),
    ("walk-straw2", "[Plyr] walk-straw2", "", 126),
    ("walk-swamp1", "[Plyr] walk-swamp1", "", 127),
    ("walk-swamp2", "[Plyr] walk-swamp2", "", 128),
    ("walk-water1", "[Plyr] walk-water1", "", 129),
    ("walk-water2", "[Plyr] walk-water2", "", 130),
    ("walk-wood1", "[Plyr] walk-wood1", "", 131),
    ("walk-wood2", "[Plyr] walk-wood2", "", 132),
    ("blue-eco-charg", "[Eco] blue-eco-charg", "", 133),
    ("blue-eco-idle", "[Eco] blue-eco-idle", "", 134),
    ("blue-eco-jak", "[Eco] blue-eco-jak", "", 135),
    ("blue-eco-on", "[Eco] blue-eco-on", "", 136),
    ("blue-eco-start", "[Eco] blue-eco-start", "", 137),
    ("darkeco-pool", "[Eco] darkeco-pool", "", 138),
    ("eco-beam", "[Eco] eco-beam", "", 139),
    ("eco-bg-blue", "[Eco] eco-bg-blue", "", 140),
    ("eco-bg-green", "[Eco] eco-bg-green", "", 141),
    ("eco-bg-red", "[Eco] eco-bg-red", "", 142),
    ("eco-bg-yellow", "[Eco] eco-bg-yellow", "", 143),
    ("eco-engine-1", "[Eco] eco-engine-1", "", 144),
    ("eco-engine-2", "[Eco] eco-engine-2", "", 145),
    ("eco-plat-hover", "[Eco] eco-plat-hover", "", 146),
    ("eco3", "[Eco] eco3", "", 147),
    ("ecohit2", "[Eco] ecohit2", "", 148),
    ("ecoroom1", "[Eco] ecoroom1", "", 149),
    ("get-blue-eco", "[Eco] get-blue-eco", "", 150),
    ("get-green-eco", "[Eco] get-green-eco", "", 151),
    ("get-red-eco", "[Eco] get-red-eco", "", 152),
    ("get-yellow-eco", "[Eco] get-yellow-eco", "", 153),
    ("green-eco-idle", "[Eco] green-eco-idle", "", 154),
    ("green-eco-jak", "[Eco] green-eco-jak", "", 155),
    ("helix-dark-eco", "[Eco] helix-dark-eco", "", 156),
    ("lav-blue-vent", "[Eco] lav-blue-vent", "", 157),
    ("lav-dark-boom", "[Eco] lav-dark-boom", "", 158),
    ("lav-green-vent", "[Eco] lav-green-vent", "", 159),
    ("lav-yell-vent", "[Eco] lav-yell-vent", "", 160),
    ("red-eco-idle", "[Eco] red-eco-idle", "", 161),
    ("red-eco-jak", "[Eco] red-eco-jak", "", 162),
    ("yel-eco-idle", "[Eco] yel-eco-idle", "", 163),
    ("yel-eco-jak", "[Eco] yel-eco-jak", "", 164),
    ("cave-spatula", "[Env] cave-spatula", "", 165),
    ("cave-top-falls", "[Env] cave-top-falls", "", 166),
    ("cave-top-lands", "[Env] cave-top-lands", "", 167),
    ("cave-top-rises", "[Env] cave-top-rises", "", 168),
    ("electric-loop", "[Env] electric-loop", "", 169),
    ("fire-boulder", "[Env] fire-boulder", "", 170),
    ("fire-crackle", "[Env] fire-crackle", "", 171),
    ("fire-loop", "[Env] fire-loop", "", 172),
    ("flame-pot", "[Env] flame-pot", "", 173),
    ("glowing-gen", "[Env] glowing-gen", "", 174),
    ("green-steam", "[Env] green-steam", "", 175),
    ("heart-drone", "[Env] heart-drone", "", 176),
    ("ice-breathin", "[Env] ice-breathin", "", 177),
    ("ice-loop", "[Env] ice-loop", "", 178),
    ("lav-mine-boom", "[Env] lav-mine-boom", "", 179),
    ("lav-spin-gen", "[Env] lav-spin-gen", "", 180),
    ("lava-mines", "[Env] lava-mines", "", 181),
    ("lava-pulley", "[Env] lava-pulley", "", 182),
    ("medium-steam-lp", "[Env] medium-steam-lp", "", 183),
    ("misty-steam", "[Env] misty-steam", "", 184),
    ("mushroom-gen", "[Env] mushroom-gen", "", 185),
    ("mushroom-off", "[Env] mushroom-off", "", 186),
    ("rock-hover", "[Env] rock-hover", "", 187),
    ("small-steam-lp", "[Env] small-steam-lp", "", 188),
    ("snow-bumper", "[Env] snow-bumper", "", 189),
    ("snow-plat-1", "[Env] snow-plat-1", "", 190),
    ("snow-plat-2", "[Env] snow-plat-2", "", 191),
    ("snow-plat-3", "[Env] snow-plat-3", "", 192),
    ("steam-long", "[Env] steam-long", "", 193),
    ("steam-medium", "[Env] steam-medium", "", 194),
    ("steam-short", "[Env] steam-short", "", 195),
    ("water-drop", "[Env] water-drop", "", 196),
    ("water-explosion", "[Env] water-explosion", "", 197),
    ("water-loop", "[Env] water-loop", "", 198),
    ("water-off", "[Env] water-off", "", 199),
    ("water-on", "[Env] water-on", "", 200),
    ("waterfall", "[Env] waterfall", "", 201),
    ("arenadoor-close", "[Obj] arenadoor-close", "", 202),
    ("arenadoor-open", "[Obj] arenadoor-open", "", 203),
    ("boat-start", "[Obj] boat-start", "", 204),
    ("boat-stop", "[Obj] boat-stop", "", 205),
    ("bomb-open", "[Obj] bomb-open", "", 206),
    ("bridge-button", "[Obj] bridge-button", "", 207),
    ("bridge-hover", "[Obj] bridge-hover", "", 208),
    ("bumper-button", "[Obj] bumper-button", "", 209),
    ("bumper-pwr-dwn", "[Obj] bumper-pwr-dwn", "", 210),
    ("chamber-land", "[Obj] chamber-land", "", 211),
    ("chamber-lift", "[Obj] chamber-lift", "", 212),
    ("crate-jump", "[Obj] crate-jump", "", 213),
    ("dcrate-break", "[Obj] dcrate-break", "", 214),
    ("door-lock", "[Obj] door-lock", "", 215),
    ("door-unlock", "[Obj] door-unlock", "", 216),
    ("elev-button", "[Obj] elev-button", "", 217),
    ("elev-land", "[Obj] elev-land", "", 218),
    ("gdl-gen-loop", "[Obj] gdl-gen-loop", "", 219),
    ("gdl-pulley", "[Obj] gdl-pulley", "", 220),
    ("gdl-shut-down", "[Obj] gdl-shut-down", "", 221),
    ("gdl-start-up", "[Obj] gdl-start-up", "", 222),
    ("icrate-break", "[Obj] icrate-break", "", 223),
    ("irisdoor1", "[Obj] irisdoor1", "", 224),
    ("irisdoor2", "[Obj] irisdoor2", "", 225),
    ("launch-fire", "[Obj] launch-fire", "", 226),
    ("launch-idle", "[Obj] launch-idle", "", 227),
    ("launch-start", "[Obj] launch-start", "", 228),
    ("ldoor-close", "[Obj] ldoor-close", "", 229),
    ("ldoor-open", "[Obj] ldoor-open", "", 230),
    ("lev-mach-fires", "[Obj] lev-mach-fires", "", 231),
    ("lev-mach-idle", "[Obj] lev-mach-idle", "", 232),
    ("lev-mach-start", "[Obj] lev-mach-start", "", 233),
    ("maindoor", "[Obj] maindoor", "", 234),
    ("mayors-gears", "[Obj] mayors-gears", "", 235),
    ("miners-fire", "[Obj] miners-fire", "", 236),
    ("oracle-awake", "[Obj] oracle-awake", "", 237),
    ("oracle-sleep", "[Obj] oracle-sleep", "", 238),
    ("pedals", "[Obj] pedals", "", 239),
    ("piston-close", "[Obj] piston-close", "", 240),
    ("piston-open", "[Obj] piston-open", "", 241),
    ("plat-light-off", "[Obj] plat-light-off", "", 242),
    ("plat-light-on", "[Obj] plat-light-on", "", 243),
    ("pontoonten", "[Obj] pontoonten", "", 244),
    ("prec-button1", "[Obj] prec-button1", "", 245),
    ("prec-button2", "[Obj] prec-button2", "", 246),
    ("prec-button3", "[Obj] prec-button3", "", 247),
    ("prec-button4", "[Obj] prec-button4", "", 248),
    ("prec-button6", "[Obj] prec-button6", "", 249),
    ("prec-button7", "[Obj] prec-button7", "", 250),
    ("prec-button8", "[Obj] prec-button8", "", 251),
    ("robo-blue-lp", "[Obj] robo-blue-lp", "", 252),
    ("robo-warning", "[Obj] robo-warning", "", 253),
    ("robotcage-lp", "[Obj] robotcage-lp", "", 254),
    ("robotcage-off", "[Obj] robotcage-off", "", 255),
    ("rounddoor", "[Obj] rounddoor", "", 256),
    ("sagecage-gen", "[Obj] sagecage-gen", "", 257),
    ("sagecage-off", "[Obj] sagecage-off", "", 258),
    ("sages-machine", "[Obj] sages-machine", "", 259),
    ("scrate-break", "[Obj] scrate-break", "", 260),
    ("scrate-nobreak", "[Obj] scrate-nobreak", "", 261),
    ("sidedoor", "[Obj] sidedoor", "", 262),
    ("silo-button", "[Obj] silo-button", "", 263),
    ("snow-pist-cls2", "[Obj] snow-pist-cls2", "", 264),
    ("snow-pist-cls3", "[Obj] snow-pist-cls3", "", 265),
    ("snow-pist-opn2", "[Obj] snow-pist-opn2", "", 266),
    ("snow-pist-opn3", "[Obj] snow-pist-opn3", "", 267),
    ("snow-piston-cls", "[Obj] snow-piston-cls", "", 268),
    ("snow-piston-opn", "[Obj] snow-piston-opn", "", 269),
    ("snw-door", "[Obj] snw-door", "", 270),
    ("split-steps", "[Obj] split-steps", "", 271),
    ("v3-bridge", "[Obj] v3-bridge", "", 272),
    ("v3-cartride", "[Obj] v3-cartride", "", 273),
    ("v3-minecart", "[Obj] v3-minecart", "", 274),
    ("vent-switch", "[Obj] vent-switch", "", 275),
    ("warpgate-act", "[Obj] warpgate-act", "", 276),
    ("warpgate-butt", "[Obj] warpgate-butt", "", 277),
    ("warpgate-loop", "[Obj] warpgate-loop", "", 278),
    ("warpgate-tele", "[Obj] warpgate-tele", "", 279),
    ("wcrate-break", "[Obj] wcrate-break", "", 280),
    ("babak-breathin", "[Enemy] babak-breathin", "", 281),
    ("babak-chest", "[Enemy] babak-chest", "", 282),
    ("babak-dies", "[Enemy] babak-dies", "", 283),
    ("babak-roar", "[Enemy] babak-roar", "", 284),
    ("babak-taunt", "[Enemy] babak-taunt", "", 285),
    ("babk-taunt", "[Enemy] babk-taunt", "", 286),
    ("balloon-dies", "[Enemy] balloon-dies", "", 287),
    ("bigshark-alert", "[Enemy] bigshark-alert", "", 288),
    ("bigshark-bite", "[Enemy] bigshark-bite", "", 289),
    ("bigshark-idle", "[Enemy] bigshark-idle", "", 290),
    ("bigshark-taunt", "[Enemy] bigshark-taunt", "", 291),
    ("blob-explode", "[Enemy] blob-explode", "", 292),
    ("blob-land", "[Enemy] blob-land", "", 293),
    ("bonelurk-roar", "[Enemy] bonelurk-roar", "", 294),
    ("bonelurker-dies", "[Enemy] bonelurker-dies", "", 295),
    ("bonelurker-grunt", "[Enemy] bonelurker-grunt", "", 296),
    ("bully-bounce", "[Enemy] bully-bounce", "", 297),
    ("bully-dies", "[Enemy] bully-dies", "", 298),
    ("bully-dizzy", "[Enemy] bully-dizzy", "", 299),
    ("bully-idle", "[Enemy] bully-idle", "", 300),
    ("bully-jump", "[Enemy] bully-jump", "", 301),
    ("bully-land", "[Enemy] bully-land", "", 302),
    ("bully-spin1", "[Enemy] bully-spin1", "", 303),
    ("bully-spin2", "[Enemy] bully-spin2", "", 304),
    ("caught-eel", "[Enemy] caught-eel", "", 305),
    ("dril-step", "[Enemy] dril-step", "", 306),
    ("flut-land-crwood", "[Enemy] flut-land-crwood", "", 307),
    ("flut-land-dirt", "[Enemy] flut-land-dirt", "", 308),
    ("flut-land-grass", "[Enemy] flut-land-grass", "", 309),
    ("flut-land-pcmeta", "[Enemy] flut-land-pcmeta", "", 310),
    ("flut-land-sand", "[Enemy] flut-land-sand", "", 311),
    ("flut-land-snow", "[Enemy] flut-land-snow", "", 312),
    ("flut-land-stone", "[Enemy] flut-land-stone", "", 313),
    ("flut-land-straw", "[Enemy] flut-land-straw", "", 314),
    ("flut-land-swamp", "[Enemy] flut-land-swamp", "", 315),
    ("flut-land-water", "[Enemy] flut-land-water", "", 316),
    ("flut-land-wood", "[Enemy] flut-land-wood", "", 317),
    ("flylurk-dies", "[Enemy] flylurk-dies", "", 318),
    ("flylurk-idle", "[Enemy] flylurk-idle", "", 319),
    ("flylurk-plane", "[Enemy] flylurk-plane", "", 320),
    ("flylurk-roar", "[Enemy] flylurk-roar", "", 321),
    ("flylurk-taunt", "[Enemy] flylurk-taunt", "", 322),
    ("grunt", "[Enemy] grunt", "", 323),
    ("icelurk-land", "[Enemy] icelurk-land", "", 324),
    ("icelurk-step", "[Enemy] icelurk-step", "", 325),
    ("kermit-loop", "[Enemy] kermit-loop", "", 326),
    ("lurkerfish-swim", "[Enemy] lurkerfish-swim", "", 327),
    ("mother-charge", "[Enemy] mother-charge", "", 328),
    ("mother-fire", "[Enemy] mother-fire", "", 329),
    ("mother-hit", "[Enemy] mother-hit", "", 330),
    ("mother-track", "[Enemy] mother-track", "", 331),
    ("mud-lurk-inhale", "[Enemy] mud-lurk-inhale", "", 332),
    ("ogre-rock", "[Enemy] ogre-rock", "", 333),
    ("ogre-throw", "[Enemy] ogre-throw", "", 334),
    ("ogre-windup", "[Enemy] ogre-windup", "", 335),
    ("ramboss-charge", "[Enemy] ramboss-charge", "", 336),
    ("ramboss-dies", "[Enemy] ramboss-dies", "", 337),
    ("ramboss-fire", "[Enemy] ramboss-fire", "", 338),
    ("ramboss-hit", "[Enemy] ramboss-hit", "", 339),
    ("ramboss-idle", "[Enemy] ramboss-idle", "", 340),
    ("ramboss-land", "[Enemy] ramboss-land", "", 341),
    ("ramboss-roar", "[Enemy] ramboss-roar", "", 342),
    ("ramboss-shield", "[Enemy] ramboss-shield", "", 343),
    ("ramboss-step", "[Enemy] ramboss-step", "", 344),
    ("ramboss-taunt", "[Enemy] ramboss-taunt", "", 345),
    ("ramboss-track", "[Enemy] ramboss-track", "", 346),
    ("robber-dies", "[Enemy] robber-dies", "", 347),
    ("robber-idle", "[Enemy] robber-idle", "", 348),
    ("robber-roar", "[Enemy] robber-roar", "", 349),
    ("robber-taunt", "[Enemy] robber-taunt", "", 350),
    ("sandworm-dies", "[Enemy] sandworm-dies", "", 351),
    ("shark-bite", "[Enemy] shark-bite", "", 352),
    ("shark-dies", "[Enemy] shark-dies", "", 353),
    ("shark-idle", "[Enemy] shark-idle", "", 354),
    ("shark-swim", "[Enemy] shark-swim", "", 355),
    ("shldlurk-breathi", "[Enemy] shldlurk-breathi", "", 356),
    ("shldlurk-chest", "[Enemy] shldlurk-chest", "", 357),
    ("shldlurk-dies", "[Enemy] shldlurk-dies", "", 358),
    ("shldlurk-roar", "[Enemy] shldlurk-roar", "", 359),
    ("shldlurk-taunt", "[Enemy] shldlurk-taunt", "", 360),
    ("temp-enemy-die", "[Enemy] temp-enemy-die", "", 361),
    ("yeti-breathin", "[Enemy] yeti-breathin", "", 362),
    ("yeti-dies", "[Enemy] yeti-dies", "", 363),
    ("yeti-roar", "[Enemy] yeti-roar", "", 364),
    ("yeti-taunt", "[Enemy] yeti-taunt", "", 365),
    ("zoom-hit-crwood", "[Enemy] zoom-hit-crwood", "", 366),
    ("zoom-hit-dirt", "[Enemy] zoom-hit-dirt", "", 367),
    ("zoom-hit-grass", "[Enemy] zoom-hit-grass", "", 368),
    ("zoom-hit-lava", "[Enemy] zoom-hit-lava", "", 369),
    ("zoom-hit-metal", "[Enemy] zoom-hit-metal", "", 370),
    ("zoom-hit-sand", "[Enemy] zoom-hit-sand", "", 371),
    ("zoom-hit-stone", "[Enemy] zoom-hit-stone", "", 372),
    ("zoom-hit-water", "[Enemy] zoom-hit-water", "", 373),
    ("zoom-hit-wood", "[Enemy] zoom-hit-wood", "", 374),
    ("zoom-land-crwood", "[Enemy] zoom-land-crwood", "", 375),
    ("zoom-land-dirt", "[Enemy] zoom-land-dirt", "", 376),
    ("zoom-land-grass", "[Enemy] zoom-land-grass", "", 377),
    ("zoom-land-lava", "[Enemy] zoom-land-lava", "", 378),
    ("zoom-land-metal", "[Enemy] zoom-land-metal", "", 379),
    ("zoom-land-sand", "[Enemy] zoom-land-sand", "", 380),
    ("zoom-land-stone", "[Enemy] zoom-land-stone", "", 381),
    ("zoom-land-water", "[Enemy] zoom-land-water", "", 382),
    ("zoom-land-wood", "[Enemy] zoom-land-wood", "", 383),
    ("buzzer", "[Pick] buzzer", "", 384),
    ("buzzer-pickup", "[Pick] buzzer-pickup", "", 385),
    ("cell-prize", "[Pick] cell-prize", "", 386),
    ("close-orb-cash", "[Pick] close-orb-cash", "", 387),
    ("cursor-l-r", "[Pick] cursor-l-r", "", 388),
    ("cursor-options", "[Pick] cursor-options", "", 389),
    ("cursor-up-down", "[Pick] cursor-up-down", "", 390),
    ("get-all-orbs", "[Pick] get-all-orbs", "", 391),
    ("menu-close", "[Pick] menu-close", "", 392),
    ("menu-stats", "[Pick] menu-stats", "", 393),
    ("money-pickup", "[Pick] money-pickup", "", 394),
    ("open-orb-cash", "[Pick] open-orb-cash", "", 395),
    ("pill-pickup", "[Pick] pill-pickup", "", 396),
    ("powercell-idle", "[Pick] powercell-idle", "", 397),
    ("powercell-out", "[Pick] powercell-out", "", 398),
    ("select-menu", "[Pick] select-menu", "", 399),
    ("select-option", "[Pick] select-option", "", 400),
    ("select-option2", "[Pick] select-option2", "", 401),
    ("start-options", "[Pick] start-options", "", 402),
    ("start-up", "[Pick] start-up", "", 403),
    ("stopwatch", "[Pick] stopwatch", "", 404),
    ("arena", "[Gen] arena", "", 405),
    ("arena-steps", "[Gen] arena-steps", "", 406),
    ("bigswing", "[Gen] bigswing", "", 407),
    ("blue-light", "[Gen] blue-light", "", 408),
    ("bluesage-fires", "[Gen] bluesage-fires", "", 409),
    ("burst-out", "[Gen] burst-out", "", 410),
    ("crab-walk1", "[Gen] crab-walk1", "", 411),
    ("crab-walk2", "[Gen] crab-walk2", "", 412),
    ("crab-walk3", "[Gen] crab-walk3", "", 413),
    ("crystal-on", "[Gen] crystal-on", "", 414),
    ("eng-shut-down", "[Gen] eng-shut-down", "", 415),
    ("eng-start-up", "[Gen] eng-start-up", "", 416),
    ("explosion", "[Gen] explosion", "", 417),
    ("explosion-2", "[Gen] explosion-2", "", 418),
    ("fish-spawn", "[Gen] fish-spawn", "", 419),
    ("get-big-fish", "[Gen] get-big-fish", "", 420),
    ("get-powered", "[Gen] get-powered", "", 421),
    ("get-small-fish", "[Gen] get-small-fish", "", 422),
    ("green-fire", "[Gen] green-fire", "", 423),
    ("greensage-fires", "[Gen] greensage-fires", "", 424),
    ("hand-grab", "[Gen] hand-grab", "", 425),
    ("jng-piston-dwn", "[Gen] jng-piston-dwn", "", 426),
    ("jng-piston-up", "[Gen] jng-piston-up", "", 427),
    ("jngb-eggtop-seq", "[Gen] jngb-eggtop-seq", "", 428),
    ("jungle-part", "[Gen] jungle-part", "", 429),
    ("loop-racering", "[Gen] loop-racering", "", 430),
    ("mayor-step-carp", "[Gen] mayor-step-carp", "", 431),
    ("mayor-step-wood", "[Gen] mayor-step-wood", "", 432),
    ("mud", "[Gen] mud", "", 433),
    ("prec-on-water", "[Gen] prec-on-water", "", 434),
    ("red-fireball", "[Gen] red-fireball", "", 435),
    ("redsage-fires", "[Gen] redsage-fires", "", 436),
    ("robot-arm", "[Gen] robot-arm", "", 437),
    ("shield-zap", "[Gen] shield-zap", "", 438),
    ("shut-down", "[Gen] shut-down", "", 439),
    ("slider2001", "[Gen] slider2001", "", 440),
    ("smack-surface", "[Gen] smack-surface", "", 441),
    ("snw-eggtop-seq", "[Gen] snw-eggtop-seq", "", 442),
    ("sunk-top-falls", "[Gen] sunk-top-falls", "", 443),
    ("sunk-top-lands", "[Gen] sunk-top-lands", "", 444),
    ("sunk-top-rises", "[Gen] sunk-top-rises", "", 445),
    ("touch-pipes", "[Gen] touch-pipes", "", 446),
    ("warning", "[Gen] warning", "", 447),
    ("wood-gears2", "[Gen] wood-gears2", "", 448),
    ("yellsage-fire", "[Gen] yellsage-fire", "", 449),
    ("zoom-boost", "[Gen] zoom-boost", "", 450),
    ("zoom-teleport", "[Gen] zoom-teleport", "", 451),
    ("zoomer-crash-2", "[Gen] zoomer-crash-2", "", 452),
    ("zoomer-explode", "[Gen] zoomer-explode", "", 453),
    ("zoomer-jump", "[Gen] zoomer-jump", "", 454),
    ("zoomer-melt", "[Gen] zoomer-melt", "", 455),
    ("zoomer-rev1", "[Gen] zoomer-rev1", "", 456),
    ("zoomer-rev2", "[Gen] zoomer-rev2", "", 457),
    ("beach-amb2__beach", "[Beach] beach-amb2", "", 458),
    ("bird__beach", "[Beach] bird", "", 459),
    ("cannon-charge__beach", "[Beach] cannon-charge", "", 460),
    ("cannon-shot__beach", "[Beach] cannon-shot", "", 461),
    ("crab-slide__beach", "[Beach] crab-slide", "", 462),
    ("dirt-crumble__beach", "[Beach] dirt-crumble", "", 463),
    ("drip__beach", "[Beach] drip", "", 464),
    ("egg-crack__beach", "[Beach] egg-crack", "", 465),
    ("egg-hit__beach", "[Beach] egg-hit", "", 466),
    ("falling-egg__beach", "[Beach] falling-egg", "", 467),
    ("fuse__beach", "[Beach] fuse", "", 468),
    ("gears-rumble__beach", "[Beach] gears-rumble", "", 469),
    ("grotto-pole-hit__beach", "[Beach] grotto-pole-hit", "", 470),
    ("lurkercrab-dies__beach", "[Beach] lurkercrab-dies", "", 471),
    ("lurkerdog-bite__beach", "[Beach] lurkerdog-bite", "", 472),
    ("lurkerdog-dies__beach", "[Beach] lurkerdog-dies", "", 473),
    ("lurkerdog-idle__beach", "[Beach] lurkerdog-idle", "", 474),
    ("monkey__beach", "[Beach] monkey", "", 475),
    ("pelican-flap__beach", "[Beach] pelican-flap", "", 476),
    ("pelican-gulp__beach", "[Beach] pelican-gulp", "", 477),
    ("puppy-bark__beach", "[Beach] puppy-bark", "", 478),
    ("rope-stretch__beach", "[Beach] rope-stretch", "", 479),
    ("sack-incoming__beach", "[Beach] sack-incoming", "", 480),
    ("sack-land__beach", "[Beach] sack-land", "", 481),
    ("seagull-takeoff__beach", "[Beach] seagull-takeoff", "", 482),
    ("shell-down__beach", "[Beach] shell-down", "", 483),
    ("shell-up__beach", "[Beach] shell-up", "", 484),
    ("snap__beach", "[Beach] snap", "", 485),
    ("telescope__beach", "[Beach] telescope", "", 486),
    ("tower-wind2__beach", "[Beach] tower-wind2", "", 487),
    ("tower-wind3__beach", "[Beach] tower-wind3", "", 488),
    ("tower-winds__beach", "[Beach] tower-winds", "", 489),
    ("vent-rock-break__beach", "[Beach] vent-rock-break", "", 490),
    ("water-lap__beach", "[Beach] water-lap", "", 491),
    ("worm-bite__beach", "[Beach] worm-bite", "", 492),
    ("worm-dies__beach", "[Beach] worm-dies", "", 493),
    ("worm-idle__beach", "[Beach] worm-idle", "", 494),
    ("worm-rise1__beach", "[Beach] worm-rise1", "", 495),
    ("worm-sink__beach", "[Beach] worm-sink", "", 496),
    ("worm-taunt__beach", "[Beach] worm-taunt", "", 497),
    ("assembly-moves__citadel", "[Citad] assembly-moves", "", 498),
    ("bridge-piece-dn__citadel", "[Citad] bridge-piece-dn", "", 499),
    ("bridge-piece-up__citadel", "[Citad] bridge-piece-up", "", 500),
    ("bunny-attack__citadel", "[Citad] bunny-attack", "", 501),
    ("bunny-dies__citadel", "[Citad] bunny-dies", "", 502),
    ("bunny-taunt-1__citadel", "[Citad] bunny-taunt-1", "", 503),
    ("citadel-amb__citadel", "[Citad] citadel-amb", "", 504),
    ("eco-beam__citadel", "[Citad] eco-beam", "", 505),
    ("eco-torch__citadel", "[Citad] eco-torch", "", 506),
    ("elev-button__citadel", "[Citad] elev-button", "", 507),
    ("mushroom-break__citadel", "[Citad] mushroom-break", "", 508),
    ("robot-arm__citadel", "[Citad] robot-arm", "", 509),
    ("rotate-plat__citadel", "[Citad] rotate-plat", "", 510),
    ("sagecage-open__citadel", "[Citad] sagecage-open", "", 511),
    ("snow-bunny1__citadel", "[Citad] snow-bunny1", "", 512),
    ("snow-bunny2__citadel", "[Citad] snow-bunny2", "", 513),
    ("yellow-buzz__citadel", "[Citad] yellow-buzz", "", 514),
    ("yellow-explode__citadel", "[Citad] yellow-explode", "", 515),
    ("yellow-fire__citadel", "[Citad] yellow-fire", "", 516),
    ("yellow-fizzle__citadel", "[Citad] yellow-fizzle", "", 517),
    ("bab-spid-dies__darkcave", "[Darkc] bab-spid-dies", "", 518),
    ("bab-spid-roar__darkcave", "[Darkc] bab-spid-roar", "", 519),
    ("button-1b__darkcave", "[Darkc] button-1b", "", 520),
    ("cavelevator__darkcave", "[Darkc] cavelevator", "", 521),
    ("cavewind__darkcave", "[Darkc] cavewind", "", 522),
    ("crystal-explode__darkcave", "[Darkc] crystal-explode", "", 523),
    ("drill-idle__darkcave", "[Darkc] drill-idle", "", 524),
    ("drill-idle2__darkcave", "[Darkc] drill-idle2", "", 525),
    ("drill-no-start__darkcave", "[Darkc] drill-no-start", "", 526),
    ("drill-start__darkcave", "[Darkc] drill-start", "", 527),
    ("drill-stop__darkcave", "[Darkc] drill-stop", "", 528),
    ("drlurker-dies__darkcave", "[Darkc] drlurker-dies", "", 529),
    ("drlurker-roar__darkcave", "[Darkc] drlurker-roar", "", 530),
    ("eggs-hatch__darkcave", "[Darkc] eggs-hatch", "", 531),
    ("eggs-lands__darkcave", "[Darkc] eggs-lands", "", 532),
    ("lay-eggs__darkcave", "[Darkc] lay-eggs", "", 533),
    ("mom-spid-dies__darkcave", "[Darkc] mom-spid-dies", "", 534),
    ("mom-spid-roar__darkcave", "[Darkc] mom-spid-roar", "", 535),
    ("spatula__darkcave", "[Darkc] spatula", "", 536),
    ("spider-step__darkcave", "[Darkc] spider-step", "", 537),
    ("trapdoor__darkcave", "[Darkc] trapdoor", "", 538),
    ("web-tramp__darkcave", "[Darkc] web-tramp", "", 539),
    ("yellow-buzz__darkcave", "[Darkc] yellow-buzz", "", 540),
    ("yellow-explode__darkcave", "[Darkc] yellow-explode", "", 541),
    ("yellow-fire__darkcave", "[Darkc] yellow-fire", "", 542),
    ("yellow-fizzle__darkcave", "[Darkc] yellow-fizzle", "", 543),
    ("-bfg-buzz__finalboss", "[Final] -bfg-buzz", "", 544),
    ("assembly-moves__finalboss", "[Final] assembly-moves", "", 545),
    ("bfg-buzz__finalboss", "[Final] bfg-buzz", "", 546),
    ("bfg-fire__finalboss", "[Final] bfg-fire", "", 547),
    ("bfg-fizzle__finalboss", "[Final] bfg-fizzle", "", 548),
    ("blob-attack__finalboss", "[Final] blob-attack", "", 549),
    ("blob-dies__finalboss", "[Final] blob-dies", "", 550),
    ("blob-jump__finalboss", "[Final] blob-jump", "", 551),
    ("blob-out__finalboss", "[Final] blob-out", "", 552),
    ("blob-roar__finalboss", "[Final] blob-roar", "", 553),
    ("bomb-spin__finalboss", "[Final] bomb-spin", "", 554),
    ("bridge-piece-dn__finalboss", "[Final] bridge-piece-dn", "", 555),
    ("bridge-piece-up__finalboss", "[Final] bridge-piece-up", "", 556),
    ("charge-loop__finalboss", "[Final] charge-loop", "", 557),
    ("dark-eco-buzz__finalboss", "[Final] dark-eco-buzz", "", 558),
    ("dark-eco-fire__finalboss", "[Final] dark-eco-fire", "", 559),
    ("eco-beam__finalboss", "[Final] eco-beam", "", 560),
    ("eco-torch__finalboss", "[Final] eco-torch", "", 561),
    ("elev-land__finalboss", "[Final] elev-land", "", 562),
    ("explod-bfg__finalboss", "[Final] explod-bfg", "", 563),
    ("explod-bomb__finalboss", "[Final] explod-bomb", "", 564),
    ("explod-eye__finalboss", "[Final] explod-eye", "", 565),
    ("explosion1__finalboss", "[Final] explosion1", "", 566),
    ("explosion2__finalboss", "[Final] explosion2", "", 567),
    ("explosion3__finalboss", "[Final] explosion3", "", 568),
    ("mushroom-break__finalboss", "[Final] mushroom-break", "", 569),
    ("red-buzz__finalboss", "[Final] red-buzz", "", 570),
    ("red-explode__finalboss", "[Final] red-explode", "", 571),
    ("red-fire__finalboss", "[Final] red-fire", "", 572),
    ("robo-hurt__finalboss", "[Final] robo-hurt", "", 573),
    ("robo-servo1__finalboss", "[Final] robo-servo1", "", 574),
    ("robo-servo2__finalboss", "[Final] robo-servo2", "", 575),
    ("robo-servo3__finalboss", "[Final] robo-servo3", "", 576),
    ("robo-servo4__finalboss", "[Final] robo-servo4", "", 577),
    ("robo-servo5__finalboss", "[Final] robo-servo5", "", 578),
    ("robo-servo6__finalboss", "[Final] robo-servo6", "", 579),
    ("robo-servo7__finalboss", "[Final] robo-servo7", "", 580),
    ("robo-servo8__finalboss", "[Final] robo-servo8", "", 581),
    ("robo-servo9__finalboss", "[Final] robo-servo9", "", 582),
    ("robo-taunt__finalboss", "[Final] robo-taunt", "", 583),
    ("robo-yell__finalboss", "[Final] robo-yell", "", 584),
    ("sagecage-open__finalboss", "[Final] sagecage-open", "", 585),
    ("silo-moves__finalboss", "[Final] silo-moves", "", 586),
    ("white-eco-beam__finalboss", "[Final] white-eco-beam", "", 587),
    ("white-eco-lp__finalboss", "[Final] white-eco-lp", "", 588),
    ("yellow-buzz__finalboss", "[Final] yellow-buzz", "", 589),
    ("yellow-explode__finalboss", "[Final] yellow-explode", "", 590),
    ("yellow-fire__finalboss", "[Final] yellow-fire", "", 591),
    ("yellow-fizzle__finalboss", "[Final] yellow-fizzle", "", 592),
    ("bubling-lava__firecanyon", "[Firec] bubling-lava", "", 593),
    ("cool-balloon__firecanyon", "[Firec] cool-balloon", "", 594),
    ("explod-mine__firecanyon", "[Firec] explod-mine", "", 595),
    ("explosion1__firecanyon", "[Firec] explosion1", "", 596),
    ("explosion2__firecanyon", "[Firec] explosion2", "", 597),
    ("lava-amb__firecanyon", "[Firec] lava-amb", "", 598),
    ("lava-steam__firecanyon", "[Firec] lava-steam", "", 599),
    ("magma-rock__firecanyon", "[Firec] magma-rock", "", 600),
    ("zoomer-loop__firecanyon", "[Firec] zoomer-loop", "", 601),
    ("zoomer-start__firecanyon", "[Firec] zoomer-start", "", 602),
    ("zoomer-stop__firecanyon", "[Firec] zoomer-stop", "", 603),
    ("accordian-pump__jungle", "[Jungl] accordian-pump", "", 604),
    ("aphid-dies__jungle", "[Jungl] aphid-dies", "", 605),
    ("aphid-roar__jungle", "[Jungl] aphid-roar", "", 606),
    ("aphid-spike-in__jungle", "[Jungl] aphid-spike-in", "", 607),
    ("aphid-spike-out__jungle", "[Jungl] aphid-spike-out", "", 608),
    ("aphid-step__jungle", "[Jungl] aphid-step", "", 609),
    ("beam-connect__jungle", "[Jungl] beam-connect", "", 610),
    ("bird__jungle", "[Jungl] bird", "", 611),
    ("bug-step__jungle", "[Jungl] bug-step", "", 612),
    ("cascade__jungle", "[Jungl] cascade", "", 613),
    ("darkvine-down__jungle", "[Jungl] darkvine-down", "", 614),
    ("darkvine-move__jungle", "[Jungl] darkvine-move", "", 615),
    ("darkvine-snap__jungle", "[Jungl] darkvine-snap", "", 616),
    ("darkvine-up__jungle", "[Jungl] darkvine-up", "", 617),
    ("eco-tower-rise__jungle", "[Jungl] eco-tower-rise", "", 618),
    ("eco-tower-stop__jungle", "[Jungl] eco-tower-stop", "", 619),
    ("elev-land__jungle", "[Jungl] elev-land", "", 620),
    ("elev-loop__jungle", "[Jungl] elev-loop", "", 621),
    ("fish-miss__jungle", "[Jungl] fish-miss", "", 622),
    ("floating-rings__jungle", "[Jungl] floating-rings", "", 623),
    ("frog-dies__jungle", "[Jungl] frog-dies", "", 624),
    ("frog-idle__jungle", "[Jungl] frog-idle", "", 625),
    ("frog-taunt__jungle", "[Jungl] frog-taunt", "", 626),
    ("frogspeak__jungle", "[Jungl] frogspeak", "", 627),
    ("jungle-river__jungle", "[Jungl] jungle-river", "", 628),
    ("jungle-shores__jungle", "[Jungl] jungle-shores", "", 629),
    ("logtrap1__jungle", "[Jungl] logtrap1", "", 630),
    ("logtrap2__jungle", "[Jungl] logtrap2", "", 631),
    ("lurk-bug__jungle", "[Jungl] lurk-bug", "", 632),
    ("lurkerfish-bite__jungle", "[Jungl] lurkerfish-bite", "", 633),
    ("lurkerfish-dies__jungle", "[Jungl] lurkerfish-dies", "", 634),
    ("lurkerfish-idle__jungle", "[Jungl] lurkerfish-idle", "", 635),
    ("lurkerm-hum__jungle", "[Jungl] lurkerm-hum", "", 636),
    ("lurkerm-squeak__jungle", "[Jungl] lurkerm-squeak", "", 637),
    ("mirror-smash__jungle", "[Jungl] mirror-smash", "", 638),
    ("monkey__jungle", "[Jungl] monkey", "", 639),
    ("pc-bridge__jungle", "[Jungl] pc-bridge", "", 640),
    ("plant-chomp__jungle", "[Jungl] plant-chomp", "", 641),
    ("plant-eye__jungle", "[Jungl] plant-eye", "", 642),
    ("plant-fall__jungle", "[Jungl] plant-fall", "", 643),
    ("plant-laugh__jungle", "[Jungl] plant-laugh", "", 644),
    ("plant-leaf__jungle", "[Jungl] plant-leaf", "", 645),
    ("plant-ouch__jungle", "[Jungl] plant-ouch", "", 646),
    ("plant-recover__jungle", "[Jungl] plant-recover", "", 647),
    ("plant-roar__jungle", "[Jungl] plant-roar", "", 648),
    ("plat-flip__jungle", "[Jungl] plat-flip", "", 649),
    ("site-moves__jungle", "[Jungl] site-moves", "", 650),
    ("snake-bite__jungle", "[Jungl] snake-bite", "", 651),
    ("snake-drop__jungle", "[Jungl] snake-drop", "", 652),
    ("snake-idle__jungle", "[Jungl] snake-idle", "", 653),
    ("snake-rattle__jungle", "[Jungl] snake-rattle", "", 654),
    ("spider-step__jungle", "[Jungl] spider-step", "", 655),
    ("steam-release__jungle", "[Jungl] steam-release", "", 656),
    ("telescope__jungle", "[Jungl] telescope", "", 657),
    ("trampoline__jungle", "[Jungl] trampoline", "", 658),
    ("wind-loop__jungle", "[Jungl] wind-loop", "", 659),
    ("accordian-pump__jungleb", "[Jungl] accordian-pump", "", 660),
    ("beam-connect__jungleb", "[Jungl] beam-connect", "", 661),
    ("bird__jungleb", "[Jungl] bird", "", 662),
    ("bug-step__jungleb", "[Jungl] bug-step", "", 663),
    ("cascade__jungleb", "[Jungl] cascade", "", 664),
    ("darkvine-down__jungleb", "[Jungl] darkvine-down", "", 665),
    ("darkvine-move__jungleb", "[Jungl] darkvine-move", "", 666),
    ("darkvine-snap__jungleb", "[Jungl] darkvine-snap", "", 667),
    ("darkvine-up__jungleb", "[Jungl] darkvine-up", "", 668),
    ("eco-tower-rise__jungleb", "[Jungl] eco-tower-rise", "", 669),
    ("eco-tower-stop__jungleb", "[Jungl] eco-tower-stop", "", 670),
    ("elev-land__jungleb", "[Jungl] elev-land", "", 671),
    ("elev-loop__jungleb", "[Jungl] elev-loop", "", 672),
    ("floating-rings__jungleb", "[Jungl] floating-rings", "", 673),
    ("frog-dies__jungleb", "[Jungl] frog-dies", "", 674),
    ("frog-idle__jungleb", "[Jungl] frog-idle", "", 675),
    ("frog-taunt__jungleb", "[Jungl] frog-taunt", "", 676),
    ("frogspeak__jungleb", "[Jungl] frogspeak", "", 677),
    ("jungle-river__jungleb", "[Jungl] jungle-river", "", 678),
    ("jungle-shores__jungleb", "[Jungl] jungle-shores", "", 679),
    ("logtrap1__jungleb", "[Jungl] logtrap1", "", 680),
    ("logtrap2__jungleb", "[Jungl] logtrap2", "", 681),
    ("lurk-bug__jungleb", "[Jungl] lurk-bug", "", 682),
    ("lurkerfish-bite__jungleb", "[Jungl] lurkerfish-bite", "", 683),
    ("lurkerfish-dies__jungleb", "[Jungl] lurkerfish-dies", "", 684),
    ("lurkerfish-idle__jungleb", "[Jungl] lurkerfish-idle", "", 685),
    ("lurkerm-hum__jungleb", "[Jungl] lurkerm-hum", "", 686),
    ("lurkerm-squeak__jungleb", "[Jungl] lurkerm-squeak", "", 687),
    ("mirror-smash__jungleb", "[Jungl] mirror-smash", "", 688),
    ("monkey__jungleb", "[Jungl] monkey", "", 689),
    ("pc-bridge__jungleb", "[Jungl] pc-bridge", "", 690),
    ("plant-chomp__jungleb", "[Jungl] plant-chomp", "", 691),
    ("plant-eye__jungleb", "[Jungl] plant-eye", "", 692),
    ("plant-fall__jungleb", "[Jungl] plant-fall", "", 693),
    ("plant-laugh__jungleb", "[Jungl] plant-laugh", "", 694),
    ("plant-leaf__jungleb", "[Jungl] plant-leaf", "", 695),
    ("plant-ouch__jungleb", "[Jungl] plant-ouch", "", 696),
    ("plant-recover__jungleb", "[Jungl] plant-recover", "", 697),
    ("plant-roar__jungleb", "[Jungl] plant-roar", "", 698),
    ("plat-flip__jungleb", "[Jungl] plat-flip", "", 699),
    ("site-moves__jungleb", "[Jungl] site-moves", "", 700),
    ("snake-bite__jungleb", "[Jungl] snake-bite", "", 701),
    ("snake-drop__jungleb", "[Jungl] snake-drop", "", 702),
    ("snake-idle__jungleb", "[Jungl] snake-idle", "", 703),
    ("snake-rattle__jungleb", "[Jungl] snake-rattle", "", 704),
    ("spider-step__jungleb", "[Jungl] spider-step", "", 705),
    ("steam-release__jungleb", "[Jungl] steam-release", "", 706),
    ("telescope__jungleb", "[Jungl] telescope", "", 707),
    ("trampoline__jungleb", "[Jungl] trampoline", "", 708),
    ("wind-loop__jungleb", "[Jungl] wind-loop", "", 709),
    ("ball-explode__lavatube", "[Lavat] ball-explode", "", 710),
    ("ball-gen__lavatube", "[Lavat] ball-gen", "", 711),
    ("bubling-lava__lavatube", "[Lavat] bubling-lava", "", 712),
    ("cool-balloon__lavatube", "[Lavat] cool-balloon", "", 713),
    ("lav-dark-eco__lavatube", "[Lavat] lav-dark-eco", "", 714),
    ("lav-mine-chain__lavatube", "[Lavat] lav-mine-chain", "", 715),
    ("lava-amb__lavatube", "[Lavat] lava-amb", "", 716),
    ("lava-steam__lavatube", "[Lavat] lava-steam", "", 717),
    ("yellow-buzz__lavatube", "[Lavat] yellow-buzz", "", 718),
    ("yellow-explode__lavatube", "[Lavat] yellow-explode", "", 719),
    ("yellow-fire__lavatube", "[Lavat] yellow-fire", "", 720),
    ("yellow-fizzle__lavatube", "[Lavat] yellow-fizzle", "", 721),
    ("zoomer-loop__lavatube", "[Lavat] zoomer-loop", "", 722),
    ("zoomer-start__lavatube", "[Lavat] zoomer-start", "", 723),
    ("zoomer-stop__lavatube", "[Lavat] zoomer-stop", "", 724),
    ("bab-spid-dies__maincave", "[Mainc] bab-spid-dies", "", 725),
    ("bab-spid-roar__maincave", "[Mainc] bab-spid-roar", "", 726),
    ("button-1b__maincave", "[Mainc] button-1b", "", 727),
    ("cavelevator__maincave", "[Mainc] cavelevator", "", 728),
    ("cavewind__maincave", "[Mainc] cavewind", "", 729),
    ("crush-click__maincave", "[Mainc] crush-click", "", 730),
    ("crystal-explode__maincave", "[Mainc] crystal-explode", "", 731),
    ("drill-idle2__maincave", "[Mainc] drill-idle2", "", 732),
    ("eggs-hatch__maincave", "[Mainc] eggs-hatch", "", 733),
    ("eggs-lands__maincave", "[Mainc] eggs-lands", "", 734),
    ("gnawer-chew__maincave", "[Mainc] gnawer-chew", "", 735),
    ("gnawer-crawl__maincave", "[Mainc] gnawer-crawl", "", 736),
    ("gnawer-dies__maincave", "[Mainc] gnawer-dies", "", 737),
    ("gnawer-taunt__maincave", "[Mainc] gnawer-taunt", "", 738),
    ("hot-flame__maincave", "[Mainc] hot-flame", "", 739),
    ("lay-eggs__maincave", "[Mainc] lay-eggs", "", 740),
    ("mom-spid-dies__maincave", "[Mainc] mom-spid-dies", "", 741),
    ("mom-spid-grunt__maincave", "[Mainc] mom-spid-grunt", "", 742),
    ("mom-spid-roar__maincave", "[Mainc] mom-spid-roar", "", 743),
    ("spatula__maincave", "[Mainc] spatula", "", 744),
    ("spider-step__maincave", "[Mainc] spider-step", "", 745),
    ("trapdoor__maincave", "[Mainc] trapdoor", "", 746),
    ("web-tramp__maincave", "[Mainc] web-tramp", "", 747),
    ("yellow-buzz__maincave", "[Mainc] yellow-buzz", "", 748),
    ("yellow-explode__maincave", "[Mainc] yellow-explode", "", 749),
    ("yellow-fire__maincave", "[Mainc] yellow-fire", "", 750),
    ("yellow-fizzle__maincave", "[Mainc] yellow-fizzle", "", 751),
    ("barrel-bounce__misty", "[Misty] barrel-bounce", "", 752),
    ("barrel-roll__misty", "[Misty] barrel-roll", "", 753),
    ("bone-bigswing__misty", "[Misty] bone-bigswing", "", 754),
    ("bone-die__misty", "[Misty] bone-die", "", 755),
    ("bone-freehead__misty", "[Misty] bone-freehead", "", 756),
    ("bone-helmet__misty", "[Misty] bone-helmet", "", 757),
    ("bone-smallswing__misty", "[Misty] bone-smallswing", "", 758),
    ("bone-stepl__misty", "[Misty] bone-stepl", "", 759),
    ("bone-stepr__misty", "[Misty] bone-stepr", "", 760),
    ("bonebridge-fall__misty", "[Misty] bonebridge-fall", "", 761),
    ("cage-boom__misty", "[Misty] cage-boom", "", 762),
    ("cannon-charge__misty", "[Misty] cannon-charge", "", 763),
    ("cannon-shot__misty", "[Misty] cannon-shot", "", 764),
    ("falling-bones__misty", "[Misty] falling-bones", "", 765),
    ("fuse__misty", "[Misty] fuse", "", 766),
    ("get-muse__misty", "[Misty] get-muse", "", 767),
    ("keg-conveyor__misty", "[Misty] keg-conveyor", "", 768),
    ("mud-lurk-laugh__misty", "[Misty] mud-lurk-laugh", "", 769),
    ("mud-lurker-idle__misty", "[Misty] mud-lurker-idle", "", 770),
    ("mud-plat__misty", "[Misty] mud-plat", "", 771),
    ("mudlurker-dies__misty", "[Misty] mudlurker-dies", "", 772),
    ("muse-taunt-1__misty", "[Misty] muse-taunt-1", "", 773),
    ("muse-taunt-2__misty", "[Misty] muse-taunt-2", "", 774),
    ("paddle-boat__misty", "[Misty] paddle-boat", "", 775),
    ("propeller__misty", "[Misty] propeller", "", 776),
    ("qsl-breathin__misty", "[Misty] qsl-breathin", "", 777),
    ("qsl-fire__misty", "[Misty] qsl-fire", "", 778),
    ("qsl-popup__misty", "[Misty] qsl-popup", "", 779),
    ("sack-incoming__misty", "[Misty] sack-incoming", "", 780),
    ("sack-land__misty", "[Misty] sack-land", "", 781),
    ("teeter-launch__misty", "[Misty] teeter-launch", "", 782),
    ("teeter-rockland__misty", "[Misty] teeter-rockland", "", 783),
    ("teeter-rockup__misty", "[Misty] teeter-rockup", "", 784),
    ("teeter-wobble__misty", "[Misty] teeter-wobble", "", 785),
    ("telescope__misty", "[Misty] telescope", "", 786),
    ("trade-muse__misty", "[Misty] trade-muse", "", 787),
    ("water-lap__misty", "[Misty] water-lap", "", 788),
    ("water-lap-cl0se__misty", "[Misty] water-lap-cl0se", "", 789),
    ("zoomer-loop__misty", "[Misty] zoomer-loop", "", 790),
    ("zoomer-start__misty", "[Misty] zoomer-start", "", 791),
    ("zoomer-stop__misty", "[Misty] zoomer-stop", "", 792),
    ("bridge-appears__ogre", "[Ogre] bridge-appears", "", 793),
    ("bridge-breaks__ogre", "[Ogre] bridge-breaks", "", 794),
    ("dynomite__ogre", "[Ogre] dynomite", "", 795),
    ("flylurk-plane__ogre", "[Ogre] flylurk-plane", "", 796),
    ("hit-lurk-metal__ogre", "[Ogre] hit-lurk-metal", "", 797),
    ("hits-head__ogre", "[Ogre] hits-head", "", 798),
    ("lava-loop__ogre", "[Ogre] lava-loop", "", 799),
    ("lava-plat__ogre", "[Ogre] lava-plat", "", 800),
    ("ogre-amb__ogre", "[Ogre] ogre-amb", "", 801),
    ("ogre-boulder__ogre", "[Ogre] ogre-boulder", "", 802),
    ("ogre-dies__ogre", "[Ogre] ogre-dies", "", 803),
    ("ogre-explode__ogre", "[Ogre] ogre-explode", "", 804),
    ("ogre-fires__ogre", "[Ogre] ogre-fires", "", 805),
    ("ogre-grunt1__ogre", "[Ogre] ogre-grunt1", "", 806),
    ("ogre-grunt2__ogre", "[Ogre] ogre-grunt2", "", 807),
    ("ogre-grunt3__ogre", "[Ogre] ogre-grunt3", "", 808),
    ("ogre-roar1__ogre", "[Ogre] ogre-roar1", "", 809),
    ("ogre-roar2__ogre", "[Ogre] ogre-roar2", "", 810),
    ("ogre-roar3__ogre", "[Ogre] ogre-roar3", "", 811),
    ("ogre-walk__ogre", "[Ogre] ogre-walk", "", 812),
    ("ogreboss-out__ogre", "[Ogre] ogreboss-out", "", 813),
    ("rock-hits-metal__ogre", "[Ogre] rock-hits-metal", "", 814),
    ("rock-in-lava__ogre", "[Ogre] rock-in-lava", "", 815),
    ("rock-roll__ogre", "[Ogre] rock-roll", "", 816),
    ("yellow-buzz__ogre", "[Ogre] yellow-buzz", "", 817),
    ("yellow-explode__ogre", "[Ogre] yellow-explode", "", 818),
    ("yellow-fire__ogre", "[Ogre] yellow-fire", "", 819),
    ("yellow-fizzle__ogre", "[Ogre] yellow-fizzle", "", 820),
    ("zoomer-loop__ogre", "[Ogre] zoomer-loop", "", 821),
    ("zoomer-start__ogre", "[Ogre] zoomer-start", "", 822),
    ("bab-spid-dies__robocave", "[Roboc] bab-spid-dies", "", 823),
    ("bab-spid-roar__robocave", "[Roboc] bab-spid-roar", "", 824),
    ("button-1b__robocave", "[Roboc] button-1b", "", 825),
    ("cavelevator__robocave", "[Roboc] cavelevator", "", 826),
    ("cavewind__robocave", "[Roboc] cavewind", "", 827),
    ("crush-click__robocave", "[Roboc] crush-click", "", 828),
    ("drill-hit__robocave", "[Roboc] drill-hit", "", 829),
    ("drill-idle__robocave", "[Roboc] drill-idle", "", 830),
    ("drill-idle2__robocave", "[Roboc] drill-idle2", "", 831),
    ("drill-no-start__robocave", "[Roboc] drill-no-start", "", 832),
    ("drill-start__robocave", "[Roboc] drill-start", "", 833),
    ("drill-stop__robocave", "[Roboc] drill-stop", "", 834),
    ("drlurker-dies__robocave", "[Roboc] drlurker-dies", "", 835),
    ("drlurker-roar__robocave", "[Roboc] drlurker-roar", "", 836),
    ("eggs-hatch__robocave", "[Roboc] eggs-hatch", "", 837),
    ("eggs-lands__robocave", "[Roboc] eggs-lands", "", 838),
    ("hot-flame__robocave", "[Roboc] hot-flame", "", 839),
    ("lay-eggs__robocave", "[Roboc] lay-eggs", "", 840),
    ("mom-spid-dies__robocave", "[Roboc] mom-spid-dies", "", 841),
    ("mom-spid-roar__robocave", "[Roboc] mom-spid-roar", "", 842),
    ("spatula__robocave", "[Roboc] spatula", "", 843),
    ("spider-step__robocave", "[Roboc] spider-step", "", 844),
    ("trapdoor__robocave", "[Roboc] trapdoor", "", 845),
    ("web-tramp__robocave", "[Roboc] web-tramp", "", 846),
    ("yellow-buzz__robocave", "[Roboc] yellow-buzz", "", 847),
    ("yellow-explode__robocave", "[Roboc] yellow-explode", "", 848),
    ("yellow-fire__robocave", "[Roboc] yellow-fire", "", 849),
    ("yellow-fizzle__robocave", "[Roboc] yellow-fizzle", "", 850),
    ("close-racering__rolling", "[Rolli] close-racering", "", 851),
    ("darkvine-grow__rolling", "[Rolli] darkvine-grow", "", 852),
    ("darkvine-kill__rolling", "[Rolli] darkvine-kill", "", 853),
    ("darkvine-move__rolling", "[Rolli] darkvine-move", "", 854),
    ("get-mole__rolling", "[Rolli] get-mole", "", 855),
    ("mole-dig__rolling", "[Rolli] mole-dig", "", 856),
    ("mole-taunt-1__rolling", "[Rolli] mole-taunt-1", "", 857),
    ("mole-taunt-2__rolling", "[Rolli] mole-taunt-2", "", 858),
    ("plant-dies__rolling", "[Rolli] plant-dies", "", 859),
    ("plant-move__rolling", "[Rolli] plant-move", "", 860),
    ("robber-flap__rolling", "[Rolli] robber-flap", "", 861),
    ("roling-amb__rolling", "[Rolli] roling-amb", "", 862),
    ("zoomer-loop__rolling", "[Rolli] zoomer-loop", "", 863),
    ("zoomer-start__rolling", "[Rolli] zoomer-start", "", 864),
    ("zoomer-stop__rolling", "[Rolli] zoomer-stop", "", 865),
    ("--snowball-roll__snow", "[Snow] --snowball-roll", "", 866),
    ("bunny-attack__snow", "[Snow] bunny-attack", "", 867),
    ("bunny-dies__snow", "[Snow] bunny-dies", "", 868),
    ("bunny-taunt-1__snow", "[Snow] bunny-taunt-1", "", 869),
    ("flut-coo__snow", "[Snow] flut-coo", "", 870),
    ("flut-death__snow", "[Snow] flut-death", "", 871),
    ("flut-flap__snow", "[Snow] flut-flap", "", 872),
    ("flut-hit__snow", "[Snow] flut-hit", "", 873),
    ("ice-explode__snow", "[Snow] ice-explode", "", 874),
    ("ice-monster1__snow", "[Snow] ice-monster1", "", 875),
    ("ice-monster2__snow", "[Snow] ice-monster2", "", 876),
    ("ice-monster3__snow", "[Snow] ice-monster3", "", 877),
    ("ice-monster4__snow", "[Snow] ice-monster4", "", 878),
    ("ice-spike-in__snow", "[Snow] ice-spike-in", "", 879),
    ("ice-spike-out__snow", "[Snow] ice-spike-out", "", 880),
    ("ice-stop__snow", "[Snow] ice-stop", "", 881),
    ("jak-slide__snow", "[Snow] jak-slide", "", 882),
    ("lodge-close__snow", "[Snow] lodge-close", "", 883),
    ("lodge-door-mov__snow", "[Snow] lodge-door-mov", "", 884),
    ("ramboss-laugh__snow", "[Snow] ramboss-laugh", "", 885),
    ("ramboss-yell__snow", "[Snow] ramboss-yell", "", 886),
    ("set-ram__snow", "[Snow] set-ram", "", 887),
    ("slam-crash__snow", "[Snow] slam-crash", "", 888),
    ("snow-bunny1__snow", "[Snow] snow-bunny1", "", 889),
    ("snow-bunny2__snow", "[Snow] snow-bunny2", "", 890),
    ("snow-engine__snow", "[Snow] snow-engine", "", 891),
    ("snow-spat-long__snow", "[Snow] snow-spat-long", "", 892),
    ("snow-spat-short__snow", "[Snow] snow-spat-short", "", 893),
    ("snowball-land__snow", "[Snow] snowball-land", "", 894),
    ("snowball-roll__snow", "[Snow] snowball-roll", "", 895),
    ("walk-ice1__snow", "[Snow] walk-ice1", "", 896),
    ("walk-ice2__snow", "[Snow] walk-ice2", "", 897),
    ("winter-amb__snow", "[Snow] winter-amb", "", 898),
    ("yellow-buzz__snow", "[Snow] yellow-buzz", "", 899),
    ("yellow-explode__snow", "[Snow] yellow-explode", "", 900),
    ("yellow-fire__snow", "[Snow] yellow-fire", "", 901),
    ("yellow-fizzle__snow", "[Snow] yellow-fizzle", "", 902),
    ("--submerge__sunken", "[Sunke] --submerge", "", 903),
    ("chamber-move__sunken", "[Sunke] chamber-move", "", 904),
    ("dark-plat-rise__sunken", "[Sunke] dark-plat-rise", "", 905),
    ("elev-button__sunken", "[Sunke] elev-button", "", 906),
    ("elev-land__sunken", "[Sunke] elev-land", "", 907),
    ("elev-loop__sunken", "[Sunke] elev-loop", "", 908),
    ("large-splash__sunken", "[Sunke] large-splash", "", 909),
    ("plat-flip__sunken", "[Sunke] plat-flip", "", 910),
    ("puffer-change__sunken", "[Sunke] puffer-change", "", 911),
    ("puffer-wing__sunken", "[Sunke] puffer-wing", "", 912),
    ("slide-loop__sunken", "[Sunke] slide-loop", "", 913),
    ("splita-charge__sunken", "[Sunke] splita-charge", "", 914),
    ("splita-dies__sunken", "[Sunke] splita-dies", "", 915),
    ("splita-idle__sunken", "[Sunke] splita-idle", "", 916),
    ("splita-roar__sunken", "[Sunke] splita-roar", "", 917),
    ("splita-spot__sunken", "[Sunke] splita-spot", "", 918),
    ("splita-taunt__sunken", "[Sunke] splita-taunt", "", 919),
    ("splitb-breathin__sunken", "[Sunke] splitb-breathin", "", 920),
    ("splitb-dies__sunken", "[Sunke] splitb-dies", "", 921),
    ("splitb-roar__sunken", "[Sunke] splitb-roar", "", 922),
    ("splitb-spot__sunken", "[Sunke] splitb-spot", "", 923),
    ("splitb-taunt__sunken", "[Sunke] splitb-taunt", "", 924),
    ("sub-plat-rises__sunken", "[Sunke] sub-plat-rises", "", 925),
    ("sub-plat-sinks__sunken", "[Sunke] sub-plat-sinks", "", 926),
    ("submerge__sunken", "[Sunke] submerge", "", 927),
    ("sunken-amb__sunken", "[Sunke] sunken-amb", "", 928),
    ("sunken-pool__sunken", "[Sunke] sunken-pool", "", 929),
    ("surface__sunken", "[Sunke] surface", "", 930),
    ("wall-plat__sunken", "[Sunke] wall-plat", "", 931),
    ("whirlpool__sunken", "[Sunke] whirlpool", "", 932),
    ("bat-celebrate__swamp", "[Swamp] bat-celebrate", "", 933),
    ("flut-coo__swamp", "[Swamp] flut-coo", "", 934),
    ("flut-death__swamp", "[Swamp] flut-death", "", 935),
    ("flut-flap__swamp", "[Swamp] flut-flap", "", 936),
    ("flut-hit__swamp", "[Swamp] flut-hit", "", 937),
    ("kermit-dies__swamp", "[Swamp] kermit-dies", "", 938),
    ("kermit-letgo__swamp", "[Swamp] kermit-letgo", "", 939),
    ("kermit-shoot__swamp", "[Swamp] kermit-shoot", "", 940),
    ("kermit-speak1__swamp", "[Swamp] kermit-speak1", "", 941),
    ("kermit-speak2__swamp", "[Swamp] kermit-speak2", "", 942),
    ("kermit-stretch__swamp", "[Swamp] kermit-stretch", "", 943),
    ("kermit-taunt__swamp", "[Swamp] kermit-taunt", "", 944),
    ("land-tar__swamp", "[Swamp] land-tar", "", 945),
    ("lurkbat-bounce__swamp", "[Swamp] lurkbat-bounce", "", 946),
    ("lurkbat-dies__swamp", "[Swamp] lurkbat-dies", "", 947),
    ("lurkbat-idle__swamp", "[Swamp] lurkbat-idle", "", 948),
    ("lurkbat-notice__swamp", "[Swamp] lurkbat-notice", "", 949),
    ("lurkbat-wing__swamp", "[Swamp] lurkbat-wing", "", 950),
    ("lurkrat-bounce__swamp", "[Swamp] lurkrat-bounce", "", 951),
    ("lurkrat-dies__swamp", "[Swamp] lurkrat-dies", "", 952),
    ("lurkrat-idle__swamp", "[Swamp] lurkrat-idle", "", 953),
    ("lurkrat-notice__swamp", "[Swamp] lurkrat-notice", "", 954),
    ("lurkrat-walk__swamp", "[Swamp] lurkrat-walk", "", 955),
    ("pole-down__swamp", "[Swamp] pole-down", "", 956),
    ("pole-up__swamp", "[Swamp] pole-up", "", 957),
    ("rat-celebrate__swamp", "[Swamp] rat-celebrate", "", 958),
    ("rat-eat__swamp", "[Swamp] rat-eat", "", 959),
    ("rat-gulp__swamp", "[Swamp] rat-gulp", "", 960),
    ("rock-break__swamp", "[Swamp] rock-break", "", 961),
    ("roll-tar__swamp", "[Swamp] roll-tar", "", 962),
    ("rope-snap__swamp", "[Swamp] rope-snap", "", 963),
    ("rope-stretch__swamp", "[Swamp] rope-stretch", "", 964),
    ("slide-tar__swamp", "[Swamp] slide-tar", "", 965),
    ("swamp-amb__swamp", "[Swamp] swamp-amb", "", 966),
    ("walk-tar1__swamp", "[Swamp] walk-tar1", "", 967),
    ("walk-tar2__swamp", "[Swamp] walk-tar2", "", 968),
    ("yellow-buzz__swamp", "[Swamp] yellow-buzz", "", 969),
    ("yellow-explode__swamp", "[Swamp] yellow-explode", "", 970),
    ("yellow-fire__swamp", "[Swamp] yellow-fire", "", 971),
    ("yellow-fizzle__swamp", "[Swamp] yellow-fizzle", "", 972),
    ("-fire-crackle__village1", "[Villa] -fire-crackle", "", 973),
    ("-water-lap-cls__village1", "[Villa] -water-lap-cls", "", 974),
    ("bird-1__village1", "[Villa] bird-1", "", 975),
    ("bird-2__village1", "[Villa] bird-2", "", 976),
    ("bird-3__village1", "[Villa] bird-3", "", 977),
    ("bird-4__village1", "[Villa] bird-4", "", 978),
    ("bird-house__village1", "[Villa] bird-house", "", 979),
    ("boat-engine__village1", "[Villa] boat-engine", "", 980),
    ("boat-splash__village1", "[Villa] boat-splash", "", 981),
    ("bubbling-still__village1", "[Villa] bubbling-still", "", 982),
    ("cage-bird-2__village1", "[Villa] cage-bird-2", "", 983),
    ("cage-bird-4__village1", "[Villa] cage-bird-4", "", 984),
    ("cage-bird-5__village1", "[Villa] cage-bird-5", "", 985),
    ("cricket-single__village1", "[Villa] cricket-single", "", 986),
    ("crickets__village1", "[Villa] crickets", "", 987),
    ("drip-on-wood__village1", "[Villa] drip-on-wood", "", 988),
    ("fire-bubble__village1", "[Villa] fire-bubble", "", 989),
    ("fly1__village1", "[Villa] fly1", "", 990),
    ("fly2__village1", "[Villa] fly2", "", 991),
    ("fly3__village1", "[Villa] fly3", "", 992),
    ("fly4__village1", "[Villa] fly4", "", 993),
    ("fly5__village1", "[Villa] fly5", "", 994),
    ("fly6__village1", "[Villa] fly6", "", 995),
    ("fly7__village1", "[Villa] fly7", "", 996),
    ("fly8__village1", "[Villa] fly8", "", 997),
    ("fountain__village1", "[Villa] fountain", "", 998),
    ("gear-creak__village1", "[Villa] gear-creak", "", 999),
    ("hammer-tap__village1", "[Villa] hammer-tap", "", 1000),
    ("hover-bike-hum__village1", "[Villa] hover-bike-hum", "", 1001),
    ("ocean-bg__village1", "[Villa] ocean-bg", "", 1002),
    ("seagulls-2__village1", "[Villa] seagulls-2", "", 1003),
    ("snd-__village1", "[Villa] snd-", "", 1004),
    ("temp-enemy-die__village1", "[Villa] temp-enemy-die", "", 1005),
    ("village-amb__village1", "[Villa] village-amb", "", 1006),
    ("water-lap__village1", "[Villa] water-lap", "", 1007),
    ("weld__village1", "[Villa] weld", "", 1008),
    ("welding-loop__village1", "[Villa] welding-loop", "", 1009),
    ("wind-loop__village1", "[Villa] wind-loop", "", 1010),
    ("yakow-1__village1", "[Villa] yakow-1", "", 1011),
    ("yakow-2__village1", "[Villa] yakow-2", "", 1012),
    ("yakow-grazing__village1", "[Villa] yakow-grazing", "", 1013),
    ("yakow-idle__village1", "[Villa] yakow-idle", "", 1014),
    ("yakow-kicked__village1", "[Villa] yakow-kicked", "", 1015),
    ("boulder-splash__village2", "[Villa] boulder-splash", "", 1016),
    ("control-panel__village2", "[Villa] control-panel", "", 1017),
    ("hits-head__village2", "[Villa] hits-head", "", 1018),
    ("rock-roll__village2", "[Villa] rock-roll", "", 1019),
    ("spark__village2", "[Villa] spark", "", 1020),
    ("thunder__village2", "[Villa] thunder", "", 1021),
    ("v2ogre-boulder__village2", "[Villa] v2ogre-boulder", "", 1022),
    ("v2ogre-roar1__village2", "[Villa] v2ogre-roar1", "", 1023),
    ("v2ogre-roar2__village2", "[Villa] v2ogre-roar2", "", 1024),
    ("v2ogre-walk__village2", "[Villa] v2ogre-walk", "", 1025),
    ("village2-amb__village2", "[Villa] village2-amb", "", 1026),
    ("wind-chimes__village2", "[Villa] wind-chimes", "", 1027),
    ("-bubling-lava__village3", "[Villa] -bubling-lava", "", 1028),
    ("cave-wind__village3", "[Villa] cave-wind", "", 1029),
    ("cool-balloon__village3", "[Villa] cool-balloon", "", 1030),
    ("lava-amb__village3", "[Villa] lava-amb", "", 1031),
    ("lava-erupt__village3", "[Villa] lava-erupt", "", 1032),
    ("lava-steam__village3", "[Villa] lava-steam", "", 1033),
    ("sulphur__village3", "[Villa] sulphur", "", 1034),
]

# ---------------------------------------------------------------------------
# SCENE PROPERTIES
# ---------------------------------------------------------------------------

class OGProperties(PropertyGroup):
    level_name:  StringProperty(name="Name", description="Lowercase with dashes", default="my-level")
    entity_type:    EnumProperty(name="Entity Type",    items=ENTITY_ENUM_ITEMS)
    platform_type:  EnumProperty(name="Platform Type",  items=PLATFORM_ENUM_ITEMS)
    crate_type:  EnumProperty(name="Crate Type",  items=CRATE_ITEMS)
    nav_radius:  FloatProperty(name="Nav Sphere Radius (m)", default=6.0, min=0.5, max=50.0,
                               description="Fallback navmesh sphere radius for nav-unsafe enemies")
    base_id:     IntProperty(name="Base Actor ID", default=10000, min=1000, max=60000,
                             description="Starting actor ID for this level. Must be unique across all custom levels to avoid ghost entity spawns.")
    lightbake_samples: IntProperty(name="Sample Count", default=128, min=1, max=4096,
                                   description="Number of Cycles render samples used when baking lighting to vertex colors")
    # Audio
    sound_bank_1:           EnumProperty(name="Bank 1", items=LEVEL_BANKS, default="none",
                                         description="First level sound bank (max 2 total)")
    sound_bank_2:           EnumProperty(name="Bank 2", items=LEVEL_BANKS, default="none",
                                         description="Second level sound bank (max 2 total)")
    music_bank:             EnumProperty(name="Music Bank", items=LEVEL_BANKS, default="none",
                                         description="Music bank to load for this level")
    sfx_sound:              EnumProperty(name="Sound", items=ALL_SFX_ITEMS, default="waterfall",
                                         description="Currently selected sound for emitter placement")
    ambient_default_radius: FloatProperty(name="Default Emitter Radius (m)", default=15.0, min=1.0, max=200.0,
                                          description="Bsphere radius for new sound emitter empties")
    # Level flow
    bottom_height:     FloatProperty(name="Death Plane (m)", default=-20.0, min=-500.0, max=-1.0,
                                     description="Y height below which the player gets an endlessfall death (negative = below level floor)")
    vis_nick_override: StringProperty(name="Vis Nick Override", default="",
                                      description="Override the auto-generated 3-letter vis nickname (leave blank to use auto)")
    # UI collapse state
    show_camera_list:       BoolProperty(name="Show Camera List",       default=True)
    show_volume_list:       BoolProperty(name="Show Volume List",       default=True)
    show_spawn_list:        BoolProperty(name="Show Spawn List",        default=True)
    show_checkpoint_list:   BoolProperty(name="Show Checkpoint List",   default=True)
    show_platform_list:     BoolProperty(name="Show Platform List",     default=True)

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
    _kill_process(f"gk{_EXE}")
    time.sleep(0.5)

def kill_goalc():
    killed_port = GOALC_PORT   # snapshot before kill — GOALC_PORT may update later
    _delete_port_file()
    _kill_process(f"goalc{_EXE}")
    time.sleep(0.5)
    # On Windows, SO_EXCLUSIVEADDRUSE holds the port until fully released.
    # Poll until the port is free so the next launch_goalc() doesn't get
    # "nREPL: DISABLED". Use 127.0.0.1 explicitly — localhost may resolve
    # to ::1 (IPv6) on Windows, causing timeouts instead of clean refusals.
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", killed_port), timeout=0.3):
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
        with socket.create_connection(("127.0.0.1", GOALC_PORT), timeout=10) as s:
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
    """Return True if GOALC's nREPL is reachable on GOALC_PORT.

    On first miss, tries to restore GOALC_PORT from the port file written
    by launch_goalc() — this handles the case where GOALC was already running
    when Blender started (e.g. from a previous session).
    """
    if goalc_send("(+ 1 1)", timeout=3) is not None:
        return True
    # Fast path missed. Try restoring port from file (written at launch time).
    _load_port_file()
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
        return False, f"goalc not found at {exe}"
    # Caller is responsible for kill_goalc() + port-free wait before calling here.
    # Do NOT kill internally — it would reset the port-free polling the caller did.
    # Find a free port starting from the user-configured preference.
    GOALC_PORT = _find_free_nrepl_port()
    _save_port_file(GOALC_PORT)
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
    if _process_running(f"gk{_EXE}"):
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
    """Collect SPAWN_ empties into continue-point data dicts.

    Each dict contains:
      name       — uid string (e.g. "start", "spawn1", or custom SPAWN_<name>)
      x/y/z      — game-space position (metres, Blender→game remap applied)
      qx/qy/qz/qw — game-space facing quaternion from the empty's rotation
      cam_x/cam_y/cam_z — camera-trans position (from linked SPAWN_<uid>_CAM empty,
                          or defaults to spawn pos + 4m up)
      cam_rot    — camera 3x3 row-major matrix as flat list of 9 floats
                   (from linked SPAWN_<uid>_CAM empty, or identity)
      is_checkpoint — True if this is a CHECKPOINT_ empty (auto-assigned mid-level)
    """
    # R_remap: Blender(x,y,z) → game(x,z,-y), stored as a 3×3 row matrix.
    # Used to conjugate Blender rotation matrices into game space:
    #   game_rot = R_remap @ bl_rot @ R_remap^T
    # Verified: identity Blender empty → identity game quat (x:0 y:0 z:0 w:1).
    R_remap = mathutils.Matrix(((1,0,0),(0,0,1),(0,-1,0)))

    out = []
    for o in sorted(scene.objects, key=lambda o: o.name):
        # BUG FIX: _CAM anchor empties share the SPAWN_/CHECKPOINT_ prefix.
        # Skip them here — they are not spawns/checkpoints themselves.
        if o.name.endswith("_CAM"):
            continue

        is_spawn      = o.name.startswith("SPAWN_")      and o.type == "EMPTY"
        is_checkpoint = o.name.startswith("CHECKPOINT_") and o.type == "EMPTY"
        if not (is_spawn or is_checkpoint):
            continue

        if is_spawn:
            uid = o.name[6:] or "start"
        else:
            uid = o.name[11:] or "cp0"

        l = o.location
        gx = round(l.x,  4)
        gy = round(l.z,  4)
        gz = round(-l.y, 4)

        # ── Facing quaternion ────────────────────────────────────────────────
        # Correct remap: game_rot = R_remap @ bl_rot @ R_remap^T
        # This ensures an unrotated Blender empty produces identity game quat (w=1).
        # The engine reads quaternions as the inverse, so we negate x/y/z (conjugate).
        m3      = o.matrix_world.to_3x3()
        game_m3 = R_remap @ m3 @ R_remap.transposed()
        gq      = game_m3.to_quaternion()
        qx   = round(-gq.x, 6)
        qy   = round(-gq.y, 6)
        qz   = round(-gq.z, 6)
        qw   = round( gq.w, 6)

        # ── Camera empty (optional) ──────────────────────────────────────────
        # User can place a SPAWN_<uid>_CAM or CHECKPOINT_<uid>_CAM empty to
        # set the camera position/orientation at respawn.
        # If absent, we default to spawn pos + 4m up, identity rotation.
        cam_suffix = "_CAM"
        cam_name   = o.name + cam_suffix
        cam_obj    = scene.objects.get(cam_name)

        if cam_obj and cam_obj.type == "EMPTY":
            cl = cam_obj.location
            cam_x = round(cl.x,  4)
            cam_y = round(cl.z,  4)
            cam_z = round(-cl.y, 4)
            # Build camera rotation matrix (same conjugate formula as camera system)
            cm3      = cam_obj.matrix_world.to_3x3()
            bl_look  = -cm3.col[2]                            # camera looks along -local_Z
            gl = mathutils.Vector((bl_look.x, bl_look.z, -bl_look.y))
            gl.normalize()
            game_down = mathutils.Vector((0.0, -1.0, 0.0))
            cr = gl.cross(game_down)
            if cr.length < 1e-6:
                cr = mathutils.Vector((1.0, 0.0, 0.0))
            cr.normalize()
            cu = gl.cross(cr)
            cu.normalize()
            # camera-rot is a 3x3 row-major matrix stored as 9 floats
            cam_rot = [
                round(cr.x, 6), round(cr.y, 6), round(cr.z, 6),
                round(cu.x, 6), round(cu.y, 6), round(cu.z, 6),
                round(gl.x, 6), round(gl.y, 6), round(gl.z, 6),
            ]
        else:
            # Default: camera sits 4m above spawn, looks forward (identity-ish)
            cam_x, cam_y, cam_z = gx, gy + 4.0, gz
            cam_rot = [1.0, 0.0, 0.0,  0.0, 1.0, 0.0,  0.0, 0.0, 1.0]

        out.append({
            "name":          uid,
            "x": gx, "y": gy, "z": gz,
            "qx": qx, "qy": qy, "qz": qz, "qw": qw,
            "cam_x": cam_x, "cam_y": cam_y, "cam_z": cam_z,
            "cam_rot":       cam_rot,
            "is_checkpoint": is_checkpoint,
        })
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
        # Platforms handle their own path lump below — skip them here to avoid double-emit
        if (einfo.get("needs_path") or (etype in NAV_UNSAFE_TYPES and path_pts)) and einfo.get("cat") != "Platforms":
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

        # ── Platform: sync lump ───────────────────────────────────────────────
        # plat / plat-eco / side-to-side-plat use a 'sync' res lump to control
        # path timing.  Format: [period_s, phase, ease_out, ease_in]
        # Only emitted when the platform has waypoints — without waypoints the
        # engine ignores sync and the platform spawns idle.
        if einfo.get("needs_sync"):
            period   = float(o.get("og_sync_period",   4.0))
            phase    = float(o.get("og_sync_phase",    0.0))
            ease_out = float(o.get("og_sync_ease_out", 0.15))
            ease_in  = float(o.get("og_sync_ease_in",  0.15))
            if path_pts:
                lump["sync"] = ["float", period, phase, ease_out, ease_in]
                wrap = bool(o.get("og_sync_wrap", False))
                if wrap:
                    # fact-options wrap-phase: bit 3 of the options uint64
                    # GOAL: (defenum fact-options :bitfield #t  (wrap-phase 3))
                    # value = 1 << 3 = 8
                    # Read via: (res-lump-value ent 'options fact-options)
                    lump["options"] = ["uint32", 8]
                log(f"  [sync] {o.name}  period={period}s  phase={phase}  ease={ease_out}/{ease_in}  wrap={wrap}")
            else:
                log(f"  [sync-platform] {o.name}  no waypoints — will spawn idle (add ≥2 waypoints to make it move)")

        # ── Platform: path lump (plat-button) ────────────────────────────────
        # plat-button follows a path when pressed. Requires ≥2 waypoints.
        # Uses needs_path flag and is a Platform, distinguishing from enemy paths.
        if einfo.get("needs_path") and einfo.get("cat") == "Platforms":
            if path_pts:
                lump["path"] = ["vector4m"] + path_pts
                log(f"  [plat-path] {o.name}  {len(path_pts)} points")
            else:
                log(f"  [WARNING] {o.name} (plat-button) needs ≥2 waypoints or it will not move!")

        # ── Platform: sync path (plat / plat-eco) ────────────────────────────
        # When a sync platform has waypoints, also emit the path lump so the
        # engine can evaluate the curve.
        if einfo.get("needs_sync") and path_pts and "path" not in lump:
            lump["path"] = ["vector4m"] + path_pts
            log(f"  [sync-path] {o.name}  {len(path_pts)} points")

        # ── Platform: notice-dist (plat-eco) ─────────────────────────────────
        # Controls how close Jak must be before the platform notices blue eco.
        # Default -1.0 = always active (never needs eco to activate).
        if einfo.get("needs_notice_dist"):
            notice = float(o.get("og_notice_dist", -1.0))
            lump["notice-dist"] = ["meters", notice]
            log(f"  [notice-dist] {o.name}  {notice}m  ({'always active' if notice < 0 else 'eco required'})")

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

    # ── Checkpoint trigger actors ─────────────────────────────────────────────
    # CHECKPOINT_ empties export as two things:
    #   1. A continue-point record in level-info.gc (via collect_spawns) — the
    #      spawn data the engine uses on respawn.
    #   2. A checkpoint-trigger actor in the JSONC (here) — an invisible entity
    #      that calls set-continue! when Jak enters it.
    # Both are needed: the actor does the triggering, the continue-point holds
    # the spawn position. The actor's continue-name lump must match the
    # continue-point name exactly: "{level_name}-{uid}".
    #
    # Volume mode: if a CPVOL_ mesh is linked (og_cp_link = checkpoint name),
    # the actor uses AABB bounds instead of sphere radius. The GOAL code reads
    # a 'has-volume' lump (uint32 1) to choose AABB vs sphere.
    level_name_for_cp = scene.og_props.level_name.strip().lower().replace(" ", "-")

    # Build cp_name → vol_obj map from linked CPVOL_ meshes
    vol_by_cp = {}
    for o in scene.objects:
        if o.type == "MESH" and o.name.startswith("VOL_"):
            link = o.get("og_vol_link", "")
            if link and link.startswith("CHECKPOINT_"):
                vol_by_cp[link] = o

    for o in sorted(scene.objects, key=lambda o: o.name):
        if not (o.name.startswith("CHECKPOINT_") and o.type == "EMPTY"):
            continue
        if o.name.endswith("_CAM"):
            continue
        uid = o.name[11:] or "cp0"
        l   = o.location
        gx  = round(l.x,  4)
        gy  = round(l.z,  4)
        gz  = round(-l.y, 4)
        r   = float(o.get("og_checkpoint_radius", 3.0))
        cp_name = f"{level_name_for_cp}-{uid}"
        lump = {
            "name":          f"checkpoint-trigger-{uid}",
            "continue-name": cp_name,
        }

        vol_obj = vol_by_cp.get(o.name)
        if vol_obj:
            # AABB mode — derive bounds from volume mesh world-space verts
            corners = [vol_obj.matrix_world @ v.co for v in vol_obj.data.vertices]
            gc = [(c.x, c.z, -c.y) for c in corners]  # bl→game remap
            xs = [c[0] for c in gc]; ys = [c[1] for c in gc]; zs = [c[2] for c in gc]
            cx = round((min(xs)+max(xs))/2, 4)
            cy = round((min(ys)+max(ys))/2, 4)
            cz = round((min(zs)+max(zs))/2, 4)
            rad = round(max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))/2 + 2.0, 2)
            lump["has-volume"]  = ["uint32", 1]
            lump["bound-xmin"]  = ["meters", round(min(xs), 4)]
            lump["bound-xmax"]  = ["meters", round(max(xs), 4)]
            lump["bound-ymin"]  = ["meters", round(min(ys), 4)]
            lump["bound-ymax"]  = ["meters", round(max(ys), 4)]
            lump["bound-zmin"]  = ["meters", round(min(zs), 4)]
            lump["bound-zmax"]  = ["meters", round(max(zs), 4)]
            out.append({
                "trans":     [cx, cy, cz],
                "etype":     "checkpoint-trigger",
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [cx, cy, cz, rad],
                "lump":      lump,
            })
            log(f"  [checkpoint] {o.name} → '{cp_name}'  AABB vol={vol_obj.name}")
        else:
            # Sphere mode — use og_checkpoint_radius
            lump["radius"] = ["meters", r]
            out.append({
                "trans":     [gx, gy, gz],
                "etype":     "checkpoint-trigger",
                "game_task": "(game-task none)",
                "quat":      [0, 0, 0, 1],
                "vis_id":    0,
                "bsphere":   [gx, gy, gz, max(r, 3.0)],
                "lump":      lump,
            })
            log(f"  [checkpoint] {o.name} → '{cp_name}'  sphere r={r}m")

    return out

def collect_ambients(scene):
    out = []
    for o in scene.objects:
        if not (o.name.startswith("AMBIENT_") and o.type == "EMPTY"):
            continue
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)

        if o.get("og_sound_name"):
            # Sound emitter — placed via the Audio panel
            radius   = float(o.get("og_sound_radius", 15.0))
            mode     = str(o.get("og_sound_mode", "loop"))
            snd_name = str(o["og_sound_name"]).lower().strip()

            # cycle-speed: ["float", base_secs, random_range_secs]
            # Negative base = looping (ambient-type-sound-loop) — confirmed working
            # Positive base = one-shot interval (ambient-type-sound) — engine bug, crashes
            if mode == "loop":
                cycle_speed = ["float", -1.0, 0.0]
            else:
                cycle_speed = ["float",
                               float(o.get("og_cycle_min", 5.0)),
                               float(o.get("og_cycle_rnd", 2.0))]

            out.append({
                "trans":   [gx, gy, gz, radius],
                "bsphere": [gx, gy, gz, radius],
                "lump": {
                    "name":        o.name[8:].lower() or "ambient",
                    "type":        "'sound",
                    "effect-name": ["symbol", snd_name],
                    "cycle-speed": cycle_speed,
                },
            })
        else:
            # Legacy hint emitter — unchanged behaviour
            out.append({
                "trans":   [gx, gy, gz, 10.0],
                "bsphere": [gx, gy, gz, 15.0],
                "lump": {
                    "name":      o.name[8:].lower() or "ambient",
                    "type":      "'hint",
                    "text-id":   ["enum-uint32", "(text-id fuel-cell)"],
                    "play-mode": "'notice",
                },
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

def write_jsonc(name, actors, ambients, camera_actors=None, base_id=10000):
    d = _ldir(name); d.mkdir(parents=True, exist_ok=True)
    all_actors = list(actors) + (camera_actors or [])
    ags = needed_ags(actors)  # camera-tracker has no art group, so only scan regular actors
    data = {
        "long_name": name, "iso_name": _iso(name), "nickname": _nick(name),
        "gltf_file": f"custom_assets/jak1/levels/{name}/{name}.glb",
        "automatic_wall_detection": True, "automatic_wall_angle": 45.0,
        "double_sided_collide": False, "base_id": base_id,
        "art_groups": [g.replace(".go","") for g in ags],
        "custom_models": [], "textures": [["village1-vis-alpha"]],
        "tex_remap": "village1", "sky": "village1", "tpages": [],
        "ambients": ambients, "actors": all_actors,
    }
    p = d / f"{name}.jsonc"
    new_text = f"// OpenGOAL custom level: {name}\n" + json.dumps(data, indent=2)
    if p.exists() and p.read_text() == new_text:
        log(f"Skipped {p} (unchanged)")
    else:
        p.write_text(new_text)
        log(f"Wrote {p}  ({len(actors)} actors + {len(camera_actors or [])} cameras)")

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
    """Build the GOAL :continues list for level-load-info.

    Each spawn dict carries full quat + camera data from collect_spawns.
    Spawns include both SPAWN_ (primary) and CHECKPOINT_ (auto-assigned) empties.

    :vis-nick is intentionally 'none for all custom-level continues.
    Custom levels have no vis data, so vis?=#f at runtime and this field is never
    acted upon. Matches the test-zone reference implementation in level-info.gc.
    """
    def cp(sp):
        cr = sp.get("cam_rot", [1,0,0, 0,1,0, 0,0,1])
        cr_str = " ".join(str(v) for v in cr)
        return (f"(new 'static 'continue-point\n"
                f"             :name \"{name}-{sp['name']}\"\n"
                f"             :level '{name}\n"
                f"             :trans (new 'static 'vector"
                f" :x (meters {sp['x']:.4f}) :y (meters {sp['y']:.4f}) :z (meters {sp['z']:.4f}) :w 1.0)\n"
                f"             :quat (new 'static 'quaternion"
                f" :x {sp.get('qx',0.0)} :y {sp.get('qy',0.0)} :z {sp.get('qz',0.0)} :w {sp.get('qw',1.0)})\n"
                f"             :camera-trans (new 'static 'vector"
                f" :x (meters {sp.get('cam_x', sp['x']):.4f})"
                f" :y (meters {sp.get('cam_y', sp['y']+4.0):.4f})"
                f" :z (meters {sp.get('cam_z', sp['z']):.4f}) :w 1.0)\n"
                f"             :camera-rot (new 'static 'array float 9 {cr_str})\n"
                f"             :load-commands '()\n"
                f"             :vis-nick 'none\n"
                f"             :lev0 '{name}\n"
                f"             :disp0 'display\n"
                f"             :lev1 #f\n"
                f"             :disp1 #f)")

    if spawns:
        return "'(" + "\n             ".join(cp(s) for s in spawns) + ")"

    # No spawns placed — emit a safe default at origin + 10m up
    return (f"'((new 'static 'continue-point\n"
            f"             :name \"{name}-start\"\n"
            f"             :level '{name}\n"
            f"             :trans (new 'static 'vector :x 0.0 :y (meters 10.) :z 0.0 :w 1.0)\n"
            f"             :quat (new 'static 'quaternion :w 1.0)\n"
            f"             :camera-trans (new 'static 'vector :x 0.0 :y (meters 14.) :z 0.0 :w 1.0)\n"
            f"             :camera-rot (new 'static 'array float 9 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0)\n"
            f"             :load-commands '()\n"
            f"             :vis-nick 'none\n"
            f"             :lev0 '{name}\n"
            f"             :disp0 'display\n"
            f"             :lev1 #f\n"
            f"             :disp1 #f))")

def patch_level_info(name, spawns, scene=None):
    p = _level_info()
    if not p.exists(): log(f"WARNING: {p} not found"); return
    # Audio settings from scene props (if scene provided)
    if scene is not None:
        props = scene.og_props
        _bank = props.music_bank
        _music_val = f"'{_bank}" if _bank and _bank != "none" else "#f"
        _sb_list = [s for s in [props.sound_bank_1, props.sound_bank_2] if s and s != "none"]
        _sbanks = " ".join(s for s in _sb_list)
        _sbanks_val = f"'({_sbanks})" if _sbanks else "'()"
        # Level flow settings
        _bot_h   = float(props.bottom_height)
        _vis_ov  = props.vis_nick_override.strip()
        _vnick   = _vis_ov if _vis_ov else _nick(name)
    else:
        _music_val = "#f"
        _sbanks_val = "'()"
        _bot_h   = -20.0
        _vnick   = _nick(name)
        props = None

    # ── Auto-compute bsphere from spawn positions ────────────────────────────
    # Centre = mean of all spawn XZ positions, Y = mean spawn Y + 2m.
    # Radius = max distance from centre to any spawn + 64m padding so the
    # engine considers the level "nearby" well before the player reaches it.
    # Fallback when no spawns: a very large sphere (40km radius) that always passes.
    if spawns:
        xs  = [s["x"] for s in spawns]
        ys  = [s["y"] for s in spawns]
        zs  = [s["z"] for s in spawns]
        cx  = sum(xs) / len(xs)
        cy  = sum(ys) / len(ys) + 2.0
        cz  = sum(zs) / len(zs)
        r   = max(
            math.sqrt((s["x"]-cx)**2 + (s["y"]-cy)**2 + (s["z"]-cz)**2)
            for s in spawns
        ) + 64.0
        # Convert to game units (4096 per metre) for the sphere :w value
        bsphere_w = round(r * 4096.0, 1)
        bsphere_str = (f"(new 'static 'sphere"
                       f" :x {round(cx*4096.0, 1)} :y {round(cy*4096.0, 1)} :z {round(cz*4096.0, 1)}"
                       f" :w {bsphere_w})")
    else:
        bsphere_str = "(new 'static 'sphere :w 167772160000.0)"  # ~40km radius

    block = (f"\n(define {name}\n"
             f"  (new 'static 'level-load-info\n"
             f"       :index 27\n"
             f"       :name '{name}\n"
             f"       :visname '{name}-vis\n"
             f"       :nickname '{_vnick}\n"
             f"       :packages '()\n"
             f"       :sound-banks {_sbanks_val}\n"
             f"       :music-bank {_music_val}\n"
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
             f"       :bsphere {bsphere_str}\n"
             f"       :bottom-height (meters {_bot_h:.1f})\n"
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



# ---------------------------------------------------------------------------
# LEVEL MANAGER — discover / remove custom levels
# ---------------------------------------------------------------------------

def discover_custom_levels():
    """Scan the filesystem and game.gp to find all custom levels.

    Returns a list of dicts:
      name        - level name (folder name)
      has_glb     - .glb exists
      has_jsonc   - .jsonc exists
      has_obs     - obs.gc exists
      has_gp      - entry found in game.gp
      conflict    - True if multiple levels share the same DGO nick
      nick        - 3-char nickname
      dgo         - DGO filename
    """
    levels_dir = _levels_dir()
    goal_levels = _goal_src() / "levels"
    gp_path = _game_gp()

    # Read game.gp entries
    gp_names = set()
    if gp_path.exists():
        txt = gp_path.read_text(encoding="utf-8")
        for m in re.finditer(r'\(build-custom-level "([^"]+)"\)', txt):
            gp_names.add(m.group(1))

    # Scan custom_assets/jak1/levels/
    found = {}
    if levels_dir.exists():
        for d in sorted(levels_dir.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            nick = _nick(name)
            dgo  = f"{nick.upper()}.DGO"
            found[name] = {
                "name":      name,
                "has_glb":   (d / f"{name}.glb").exists(),
                "has_jsonc": (d / f"{name}.jsonc").exists(),
                "has_gd":    (d / f"{nick}.gd").exists(),
                "has_obs":   (goal_levels / name / f"{name}-obs.gc").exists(),
                "has_gp":    name in gp_names,
                "nick":      nick,
                "dgo":       dgo,
                "conflict":  False,
            }

    # Detect DGO nickname conflicts
    nick_to_names = {}
    for info in found.values():
        nick_to_names.setdefault(info["dgo"], []).append(info["name"])
    for names in nick_to_names.values():
        if len(names) > 1:
            for n in names:
                found[n]["conflict"] = True

    return list(found.values())


def remove_level(name):
    """Remove all files for a custom level and clean game.gp.

    Deletes:
      custom_assets/jak1/levels/<name>/   (entire folder)
      goal_src/jak1/levels/<name>/        (entire folder)

    Removes from game.gp:
      (build-custom-level "<name>")
      (custom-level-cgo ...)
      (goal-src "levels/<name>/...")

    Returns list of log messages.
    """
    import shutil
    msgs = []

    # Delete custom_assets folder
    assets_dir = _levels_dir() / name
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
        msgs.append(f"Deleted {assets_dir}")
    else:
        msgs.append(f"(not found) {assets_dir}")

    # Delete goal_src levels folder
    goal_dir = _goal_src() / "levels" / name
    if goal_dir.exists():
        shutil.rmtree(goal_dir)
        msgs.append(f"Deleted {goal_dir}")
    else:
        msgs.append(f"(not found) {goal_dir}")

    # Patch level-info.gc — strip the define block and cons! entry
    li_path = _level_info()
    if li_path.exists():
        txt = li_path.read_text(encoding="utf-8")
        new_txt = re.sub(
            rf"\n\(define {re.escape(name)}\b.*?\(cons!.*?'{re.escape(name)}\)\n",
            "", txt, flags=re.DOTALL)
        if new_txt != txt:
            li_path.write_text(new_txt, encoding="utf-8")
            msgs.append(f"Cleaned level-info.gc entry for '{name}'")
        else:
            msgs.append(f"level-info.gc had no entry for '{name}'")
    else:
        msgs.append("level-info.gc not found")

    # Patch game.gp — strip all entries for this level
    gp_path = _game_gp()
    if gp_path.exists():
        raw  = gp_path.read_bytes()
        crlf = b"\r\n" in raw
        txt  = raw.decode("utf-8").replace("\r\n", "\n")
        before = txt

        nick = _nick(name)
        txt = re.sub(r'\(build-custom-level "' + re.escape(name) + r'"\)\n', '', txt)
        txt = re.sub(r'\(custom-level-cgo "[^"]*" "' + re.escape(name) + r'/[^"]+\"\)\n', '', txt)
        txt = re.sub(r'\(goal-src "levels/' + re.escape(name) + r'/[^"]+\"[^)]*\)\n', '', txt)

        if txt != before:
            if crlf:
                txt = txt.replace("\n", "\r\n")
            gp_path.write_bytes(txt.encode("utf-8"))
            msgs.append(f"Cleaned game.gp entries for '{name}'")
        else:
            msgs.append(f"game.gp had no entries for '{name}'")
    else:
        msgs.append("game.gp not found")

    return msgs


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
        n   = len([o for o in ctx.scene.objects if o.name.startswith("SPAWN_") and not o.name.endswith("_CAM")])
        uid = "start" if n == 0 else f"spawn{n}"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"SPAWN_{uid}"; o.show_name = True
        o.empty_display_size = 1.0; o.color = (0.0,1.0,0.0,1.0)
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


class OG_OT_SpawnCheckpoint(Operator):
    bl_idname = "og.spawn_checkpoint"
    bl_label  = "Add Checkpoint"
    bl_description = (
        "Place a mid-level checkpoint empty at the 3D cursor. "
        "The engine auto-assigns the nearest zero-flag checkpoint as the player "
        "moves around, so these act as silent progress saves without any trigger actors."
    )
    def execute(self, ctx):
        n   = len([o for o in ctx.scene.objects if o.name.startswith("CHECKPOINT_") and not o.name.endswith("_CAM")])
        uid = f"cp{n}"
        bpy.ops.object.empty_add(type="SINGLE_ARROW", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"CHECKPOINT_{uid}"; o.show_name = True
        o.empty_display_size = 1.2; o.color = (1.0, 0.85, 0.0, 1.0)
        o["og_checkpoint_radius"] = 3.0
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


class OG_OT_SpawnCamAnchor(Operator):
    bl_idname = "og.spawn_cam_anchor"
    bl_label  = "Add Spawn Camera"
    bl_description = (
        "Place a camera-anchor empty linked to the selected SPAWN_ or CHECKPOINT_ empty. "
        "This sets the camera position and orientation used when the player respawns at that point."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if sel is None or sel.type != "EMPTY":
            self.report({"ERROR"}, "Select a SPAWN_ or CHECKPOINT_ empty first")
            return {"CANCELLED"}
        is_spawn = sel.name.startswith("SPAWN_") or sel.name.startswith("CHECKPOINT_")
        if not is_spawn:
            self.report({"ERROR"}, "Selected object must be a SPAWN_ or CHECKPOINT_ empty")
            return {"CANCELLED"}
        cam_name = sel.name + "_CAM"
        if ctx.scene.objects.get(cam_name):
            self.report({"WARNING"}, f"{cam_name} already exists")
            return {"CANCELLED"}
        # Place camera 6m behind and 3m above spawn in Blender space
        offset = mathutils.Vector((0.0, -6.0, 3.0))
        loc    = sel.matrix_world.translation + sel.matrix_world.to_3x3() @ offset
        bpy.ops.object.empty_add(type="ARROWS", location=loc)
        o = ctx.active_object
        o.name = cam_name; o.show_name = True
        o.empty_display_size = 0.8; o.color = (0.2, 0.6, 1.0, 1.0)
        # Point it toward the spawn (face -Z toward spawn so camera looks at it)
        direction = sel.matrix_world.translation - loc
        if direction.length > 1e-4:
            rot_quat = direction.to_track_quat('-Z', 'Y')
            o.rotation_euler = rot_quat.to_euler()
        self.report({"INFO"}, f"Added {cam_name}")
        return {"FINISHED"}







# ── Entity placement ──────────────────────────────────────────────────────────

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
        _clean_orphaned_vol_links(scene)
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)
        collect_nav_mesh_geometry(scene, name)
        cam_actors, trigger_actors = collect_cameras(scene)

        if code_deps:
            state["status"] = f"Injecting code for: {[o for o,_,_ in code_deps]}..."
            log(f"[code-deps] {code_deps}")

        state["status"] = "Writing files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=bool([o for o in scene.objects if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")]))
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns, scene)
        patch_game_gp(name, code_deps)

        if goalc_ok():
            state["status"] = "Running (mi) via nREPL..."
            r = goalc_send("(mi)", timeout=GOALC_TIMEOUT)
            if r is not None:
                state["ok"] = True; state["status"] = "Build complete!"; return

        state["status"] = "Writing startup.gc..."
        write_startup_gc(["(mi)"])
        state["status"] = "Launching GOALC..."
        kill_goalc()
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
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max is 10. Shorten it in Level Settings.")
            return {"CANCELLED"}
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
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
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
        _clean_orphaned_vol_links(scene)
        actors   = collect_actors(scene)
        ambients = collect_ambients(scene)
        spawns   = collect_spawns(scene)
        ags      = needed_ags(actors)
        tpages   = needed_tpages(actors)
        code_deps = needed_code(actors)  # still needed for DGO .o injection
        cam_actors, trigger_actors = collect_cameras(scene)

        state["status"] = "Writing level files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=bool([o for o in scene.objects if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")]))
        patch_level_info(name, spawns, scene)  # update spawn continue-points if moved

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
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max 10"); return {"CANCELLED"}
        if len(name) > 10:
            self.report({"ERROR"}, f"Level name '{name}' is {len(name)} chars — max is 10. Shorten it in Level Settings.")
            return {"CANCELLED"}
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
        _clean_orphaned_vol_links(scene)
        actors    = collect_actors(scene)
        ambients  = collect_ambients(scene)
        spawns    = collect_spawns(scene)
        ags       = needed_ags(actors)
        tpages    = needed_tpages(actors)
        code_deps = needed_code(actors)
        cam_actors, trigger_actors = collect_cameras(scene)

        state["status"] = "Writing level files..."
        base_id = scene.og_props.base_id
        write_jsonc(name, actors, ambients, cam_actors + trigger_actors, base_id)
        write_gd(name, ags, code_deps, tpages)
        navmesh_actors = _collect_navmesh_actors(scene)
        write_gc(name, has_triggers=bool(trigger_actors), has_checkpoints=bool([o for o in scene.objects if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")]))
        patch_entity_gc(navmesh_actors)
        patch_level_info(name, spawns, scene)
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
    return (not info.get("nav_safe", True)    # nav-enemy — optional patrol path
            or info.get("needs_path", False)  # process-drawable that requires path
            or info.get("needs_pathb", False)
            or info.get("needs_sync", False)) # sync platform — path drives movement


def _actor_uses_navmesh(etype):
    """True if this entity type is a nav-enemy and needs entity.gc navmesh patch."""
    info = ENTITY_DEFS.get(etype, {})
    return info.get("ai_type") == "nav-enemy"


def _actor_is_platform(etype):
    """True if this entity is in the Platforms category."""
    return ENTITY_DEFS.get(etype, {}).get("cat") == "Platforms"
# ---------------------------------------------------------------------------


class OG_OT_PickSound(Operator):
    """Open sound picker — choose a sound then click OK to place an emitter"""
    bl_idname   = "og.pick_sound"
    bl_label    = "Pick Sound"
    bl_property = "sfx_sound"

    sfx_sound: bpy.props.EnumProperty(
        name="Sound",
        description="Select a sound to place",
        items=ALL_SFX_ITEMS,
    )

    def execute(self, ctx):
        # Just store the selected sound — emitter is placed separately via Add Emitter
        ctx.scene.og_props.sfx_sound = self.sfx_sound
        snd = self.sfx_sound.split("__")[0] if "__" in self.sfx_sound else self.sfx_sound
        self.report({"INFO"}, f"Sound selected: {snd}")
        return {"FINISHED"}

    def invoke(self, ctx, event):
        self.sfx_sound = ctx.scene.og_props.sfx_sound
        ctx.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

class OG_OT_AddSoundEmitter(Operator):
    """Add a sound emitter empty at the 3D cursor"""
    bl_idname  = "og.add_sound_emitter"
    bl_label   = "Add Sound Emitter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props = ctx.scene.og_props
        snd   = props.sfx_sound.split("__")[0] if "__" in props.sfx_sound else props.sfx_sound
        if not snd:
            snd = "waterfall"
        existing = [o for o in ctx.scene.objects if o.name.startswith("AMBIENT_snd")]
        idx  = len(existing) + 1
        name = f"AMBIENT_snd{idx:03d}"

        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = name
        o.show_name = True
        o.empty_display_size = max(0.3, props.ambient_default_radius * 0.05)
        o.color = (0.2, 0.8, 1.0, 1.0)

        # Stamp editable custom props
        o["og_sound_name"]   = snd
        o["og_sound_radius"] = props.ambient_default_radius
        o["og_sound_mode"]   = "loop"

        self.report({"INFO"}, f"Added '{name}' → {snd}")
        return {"FINISHED"}


class OG_PT_Audio(Panel):
    bl_label       = "🔊  Audio / Ambience"
    bl_idname      = "OG_PT_audio"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        b1     = props.sound_bank_1
        b2     = props.sound_bank_2

        # ── Level Music ──────────────────────────────────────────────────
        box = layout.box()
        box.label(text="Level Music", icon="PLAY")
        box.prop(props, "music_bank", text="Music Bank")

        # ── Sound Banks ──────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Sound Banks  (max 2)", icon="SPEAKER")
        col2 = box2.column(align=True)
        col2.prop(props, "sound_bank_1", text="Bank 1")
        col2.prop(props, "sound_bank_2", text="Bank 2")
        if b1 != "none" and b1 == b2:
            box2.label(text="⚠ Bank 1 and Bank 2 are the same", icon="ERROR")
        n_common = len(SBK_SOUNDS.get("common", []))
        n_level  = len(set(SBK_SOUNDS.get(b1, [])) | set(SBK_SOUNDS.get(b2, [])))
        box2.label(text=f"{n_common} common  +  {n_level} level  =  {n_common + n_level} available", icon="INFO")

        layout.separator(factor=0.4)

        # ── Sound Emitters ───────────────────────────────────────────────
        box3 = layout.box()
        box3.label(text="Sound Emitters", icon="OUTLINER_OB_SPEAKER")
        col3 = box3.column(align=True)
        col3.prop(props, "ambient_default_radius", text="Default Radius (m)")
        col3.separator(factor=0.4)

        # Sound picker — full width button, shows selected sound name
        snd_display = props.sfx_sound.split("__")[0] if "__" in props.sfx_sound else props.sfx_sound
        pick_row = col3.row(align=True)
        pick_row.scale_y = 1.2
        pick_row.operator("og.pick_sound", text=f"🔊  {snd_display}", icon="VIEWZOOM")

        col3.separator(factor=0.4)
        row2 = col3.row()
        row2.scale_y = 1.4
        row2.operator("og.add_sound_emitter", text="Add Emitter at Cursor", icon="ADD")

        # List existing emitters
        emitters = [o for o in ctx.scene.objects
                    if o.name.startswith("AMBIENT_") and o.type == "EMPTY"
                    and o.get("og_sound_name")]
        if emitters:
            layout.separator(factor=0.3)
            sub = layout.box()
            sub.label(text=f"{len(emitters)} emitter(s) in scene:", icon="OUTLINER_OB_EMPTY")
            for o in emitters[:8]:
                row = sub.row(align=True)
                snd  = o.get("og_sound_name", "?")
                mode = o.get("og_sound_mode", "loop")
                icon = "PREVIEW_RANGE" if mode == "loop" else "PLAYER"
                row.label(text=f"{o.name}  →  {snd}  [{mode}]", icon=icon)
            if len(emitters) > 8:
                sub.label(text=f"… and {len(emitters) - 8} more")
        else:
            layout.label(text="No emitters placed yet", icon="INFO")


# ---------------------------------------------------------------------------
# PANELS
# ---------------------------------------------------------------------------
# Panel hierarchy (all under "OpenGOAL" N-panel tab):
#
#  OG_PT_LevelSettings   — Level name, base ID
#  OG_PT_Scene           — Level Flow: spawns, checkpoints, death plane, bsphere
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
            name_clean = name.lower().replace(" ", "-")
            if len(name_clean) > 10:
                warn = layout.row()
                warn.alert = True
                warn.label(text=f"Name too long ({len(name_clean)} chars, max 10)!", icon="ERROR")
            else:
                row = layout.row()
                row.enabled = False
                row.label(text=f"ISO: {_iso(name)}   Nick: {_nick(name)}", icon="INFO")

        layout.separator(factor=0.4)
        col2 = layout.column(align=True)
        col2.prop(props, "bottom_height",    text="Death Plane (m)")
        col2.prop(props, "vis_nick_override", text="Vis Nick Override")


# ── Scene Setup / Level Flow ──────────────────────────────────────────────────

class OG_PT_Scene(Panel):
    bl_label       = "🗺  Level Flow"
    bl_idname      = "OG_PT_scene"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        scene  = ctx.scene

        # ── Spawn points ──────────────────────────────────────────────────────
        layout.label(text="Spawn Points", icon="ARMATURE_DATA")
        col = layout.column(align=True)
        col.operator("og.spawn_player",     text="Add Player Spawn",  icon="ADD")
        col.operator("og.spawn_checkpoint", text="Add Checkpoint",    icon="KEYFRAME")

        spawns      = [o for o in scene.objects if o.name.startswith("SPAWN_")      and o.type == "EMPTY" and not o.name.endswith("_CAM")]
        checkpoints = [o for o in scene.objects if o.name.startswith("CHECKPOINT_") and o.type == "EMPTY" and not o.name.endswith("_CAM")]

        if spawns or checkpoints:
            layout.separator(factor=0.4)

            if spawns:
                # Collapsible spawns
                row = layout.row()
                icon = "TRIA_DOWN" if props.show_spawn_list else "TRIA_RIGHT"
                row.prop(props, "show_spawn_list",
                         text=f"Player Spawns ({len(spawns)})", icon=icon, emboss=False)
                if props.show_spawn_list:
                    box = layout.box()
                    for o in sorted(spawns, key=lambda x: x.name):
                        row = box.row(align=True)
                        row.label(text=o.name, icon="EMPTY_ARROWS")
                        cam_obj = scene.objects.get(o.name + "_CAM")
                        if cam_obj:
                            row.label(text="📷", icon="NONE")
                        else:
                            sub = row.row()
                            sub.alert = True
                            sub.label(text="no cam", icon="NONE")
                        op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                        op.obj_name = o.name
                        op = row.operator("og.delete_object", text="", icon="TRASH")
                        op.obj_name = o.name

            if checkpoints:
                # Collapsible checkpoints
                row = layout.row()
                icon = "TRIA_DOWN" if props.show_checkpoint_list else "TRIA_RIGHT"
                row.prop(props, "show_checkpoint_list",
                         text=f"Checkpoints ({len(checkpoints)})", icon=icon, emboss=False)
                if props.show_checkpoint_list:
                    # Build vol_by_cp map for display
                    vol_by_cp_panel = {}
                    for o in scene.objects:
                        if o.type == "MESH" and o.name.startswith("VOL_"):
                            link = o.get("og_vol_link", "")
                            if link and link.startswith("CHECKPOINT_"):
                                vol_by_cp_panel[link] = o
                    box = layout.box()
                    for o in sorted(checkpoints, key=lambda x: x.name):
                        row = box.row(align=True)
                        row.label(text=o.name, icon="EMPTY_SINGLE_ARROW")
                        vol = vol_by_cp_panel.get(o.name)
                        if vol:
                            row.label(text=f"📦 {vol.name}")
                        else:
                            r = float(o.get("og_checkpoint_radius", 3.0))
                            sub = row.row()
                            sub.alert = True
                            sub.label(text=f"r={r:.1f}m")
                        cam_obj = scene.objects.get(o.name + "_CAM")
                        if cam_obj:
                            row.label(text="📷", icon="NONE")
                        op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
                        op.obj_name = o.name
                        op = row.operator("og.delete_object", text="", icon="TRASH")
                        op.obj_name = o.name

            # ── Camera anchor + volume helpers (context-sensitive) ────────────
            sel = ctx.active_object
            if sel and sel.type == "EMPTY" and (sel.name.startswith("SPAWN_") or sel.name.startswith("CHECKPOINT_")) and not sel.name.endswith("_CAM"):
                is_cp = sel.name.startswith("CHECKPOINT_")
                layout.separator(factor=0.3)
                sub = layout.column(align=True)

                # Camera anchor
                cam_exists = bool(scene.objects.get(sel.name + "_CAM"))
                if not cam_exists:
                    sub.operator("og.spawn_cam_anchor", text=f"Add Camera for {sel.name}", icon="CAMERA_DATA")
                else:
                    row = sub.row()
                    row.enabled = False
                    row.label(text=f"{sel.name}_CAM exists ✓", icon="CHECKMARK")

                # Volume (checkpoints only)
                if is_cp:
                    vol_by_cp_sel = {}
                    for o in scene.objects:
                        if o.type == "MESH" and o.name.startswith("VOL_"):
                            lnk = o.get("og_vol_link", "")
                            if lnk and lnk.startswith("CHECKPOINT_"):
                                vol_by_cp_sel[lnk] = o
                    vol_linked = vol_by_cp_sel.get(sel.name)
                    if vol_linked:
                        row = sub.row()
                        row.enabled = False
                        row.label(text=f"{vol_linked.name} linked ✓", icon="MESH_CUBE")
                        sub.operator("og.unlink_volume", text="Unlink Volume", icon="X")
                    else:
                        op = sub.operator("og.spawn_volume_autolink", text="Add Trigger Volume", icon="MESH_CUBE")
                        op.target_name = sel.name
                        sub.label(text="Or use Triggers panel to link existing", icon="INFO")

        # Bsphere preview
        if spawns or checkpoints:
            all_pts = spawns + checkpoints
            xs = [o.location.x for o in all_pts]
            ys = [o.location.z for o in all_pts]
            zs = [-o.location.y for o in all_pts]
            cx = sum(xs)/len(xs); cy = sum(ys)/len(ys); cz = sum(zs)/len(zs)
            r  = max(
                math.sqrt((o.location.x-cx)**2 + (o.location.z-cy)**2 + (-o.location.y-cz)**2)
                for o in all_pts
            ) + 64.0
            info_row = layout.row()
            info_row.enabled = False
            info_row.label(text=f"Bsphere: r≈{r:.0f}m  centre ({cx:.1f}, {cy:.1f}, {cz:.1f})", icon="SPHERE")


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
    bl_description = (
        "Place a Blender camera at the 3D cursor.\n"
        "Named CAMERA_0, CAMERA_1 etc.\n"
        "Look through it with Numpad-0 to preview the game view.\n"
        "Link a trigger volume mesh with 'Link Trigger Volume'."
    )
    def execute(self, ctx):
        n = len([o for o in ctx.scene.objects
                 if o.name.startswith("CAMERA_") and o.type == "CAMERA"])
        cam_name = f"CAMERA_{n}"
        bpy.ops.object.camera_add(location=ctx.scene.cursor.location)
        o = ctx.active_object
        # Set name twice: Blender resolves duplicate data-block names after the
        # first assignment, so the second set lands the exact name we want.
        o.name      = cam_name
        o.name      = cam_name
        o.data.name = cam_name
        o.show_name = True
        o.color = (0.0, 0.8, 0.9, 1.0)
        # Default custom properties
        o["og_cam_mode"]   = "fixed"
        o["og_cam_interp"] = 1.0
        o["og_cam_fov"]    = 0.0
        o["og_cam_look_at"] = ""
        self.report({"INFO"}, f"Added {o.name}  |  Numpad-0 to look through it")
        return {"FINISHED"}



class OG_OT_SpawnVolume(Operator):
    """Spawn a generic trigger volume (VOL_N wireframe cube).
    If the active object is a linkable target (CAMERA_, SPAWN_, CHECKPOINT_),
    the volume is auto-linked to it immediately on spawn."""
    bl_idname = "og.spawn_volume"
    bl_label  = "Add Trigger Volume"
    bl_description = (
        "Add a box mesh trigger volume at the 3D cursor. "
        "If a camera, spawn, or checkpoint is selected, it auto-links."
    )
    def execute(self, ctx):
        n = len([o for o in ctx.scene.objects
                 if o.type == "MESH" and o.name.startswith("VOL_")])
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=ctx.scene.cursor.location)
        vol = ctx.active_object
        vol.name = f"VOL_{n}"
        vol["og_vol_id"] = n          # remember original number for unlink rename
        vol.show_name = True
        vol.display_type = "WIRE"
        vol.color = (0.0, 0.9, 0.3, 0.4)
        vol.set_invisible = True
        vol.set_collision = True
        vol.ignore        = True

        # Auto-link if the previously active object is a valid target
        prev = ctx.scene.objects.get(getattr(ctx, "_prev_active_name", ""))
        # Re-read: before empty_add the active was our target
        # We stored it in the scene temp prop via the operator invoke
        target_name = vol.get("_auto_link_target", "")
        if target_name:
            target = ctx.scene.objects.get(target_name)
            if target and not _vol_for_target(ctx.scene, target_name):
                vol["og_vol_link"] = target_name
                vol.name = f"VOL_{target_name}"
                del vol["_auto_link_target"]
                self.report({"INFO"}, f"Added and linked {vol.name} → {target_name}")
                return {"FINISHED"}

        self.report({"INFO"}, f"Added {vol.name}  —  select volume + target → Link in Triggers panel")
        return {"FINISHED"}

    def invoke(self, ctx, event):
        # Store active object name before adding geometry changes active
        sel = ctx.active_object
        if sel and _is_linkable(sel):
            # Check not already linked
            existing = _vol_for_target(ctx.scene, sel.name)
            if existing:
                self.report({"WARNING"}, f"{sel.name} already has {existing.name} linked — unlink first")
                return {"CANCELLED"}
            # Temporarily stamp target onto the new vol via a scene prop
            # We use a scene-level string prop as a handoff since active changes after add
            ctx.scene["_pending_vol_target"] = sel.name
        else:
            ctx.scene["_pending_vol_target"] = ""
        return self.execute(ctx)


def _is_linkable(obj):
    """True if this object type can accept a trigger volume."""
    return (obj.type == "CAMERA" and obj.name.startswith("CAMERA_")) or            (obj.type == "EMPTY"  and (obj.name.startswith("SPAWN_") or obj.name.startswith("CHECKPOINT_")) and not obj.name.endswith("_CAM"))


def _vol_for_target(scene, target_name):
    """Return the VOL_ mesh linked to target_name, or None."""
    for o in scene.objects:
        if o.type == "MESH" and o.name.startswith("VOL_") and o.get("og_vol_link") == target_name:
            return o
    return None


def _clean_orphaned_vol_links(scene):
    """Remove og_vol_link from any VOL_ mesh whose target no longer exists.
    Called at export time and available as a panel button.
    Returns list of volume names that were cleaned."""
    cleaned = []
    for o in scene.objects:
        if o.type == "MESH" and o.name.startswith("VOL_"):
            link = o.get("og_vol_link", "")
            if link and not scene.objects.get(link):
                orig_id = o.get("og_vol_id", 0)
                del o["og_vol_link"]
                o.name = f"VOL_{orig_id}"
                cleaned.append(link)
                log(f"  [vol] cleaned orphaned link → '{link}' (target deleted)")
    return cleaned


class OG_OT_SpawnVolumeAutoLink(Operator):
    """Internal: spawn a volume and auto-link to the given target."""
    bl_idname = "og.spawn_volume_autolink"
    bl_label  = "Add & Link Trigger Volume"
    bl_description = "Spawn a trigger volume and immediately link it to the active object"

    target_name: bpy.props.StringProperty()

    def execute(self, ctx):
        target = ctx.scene.objects.get(self.target_name)
        if not target:
            self.report({"ERROR"}, f"Target {self.target_name} not found")
            return {"CANCELLED"}
        existing = _vol_for_target(ctx.scene, self.target_name)
        if existing:
            self.report({"WARNING"}, f"{self.target_name} already linked to {existing.name} — unlink first")
            return {"CANCELLED"}
        n = len([o for o in ctx.scene.objects if o.type == "MESH" and o.name.startswith("VOL_")])
        # Place at target location
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=target.location)
        vol = ctx.active_object
        vol["og_vol_id"] = n
        vol.show_name = True
        vol.display_type = "WIRE"
        vol.set_invisible = True
        vol.set_collision = True
        vol.ignore        = True
        if target.type == "CAMERA":
            vol.color = (0.0, 0.9, 0.3, 0.4)
        else:
            vol.color = (1.0, 0.85, 0.0, 0.4)
        vol["og_vol_link"] = self.target_name
        vol.name = f"VOL_{self.target_name}"
        self.report({"INFO"}, f"Added {vol.name} → {self.target_name}")
        return {"FINISHED"}


class OG_OT_LinkVolume(Operator):
    """Link a VOL_ mesh to a camera, spawn, or checkpoint.
    Select the VOL_ mesh first, then shift-click the target, then click Link."""
    bl_idname   = "og.link_volume"
    bl_label    = "Link Volume"
    bl_description = "Select VOL_ mesh first, then shift-click the target (camera/spawn/checkpoint), then click"

    def execute(self, ctx):
        selected = ctx.selected_objects
        vols    = [o for o in selected if o.type == "MESH" and o.name.startswith("VOL_")]
        targets = [o for o in selected if _is_linkable(o)]

        if not vols:
            self.report({"ERROR"}, "No VOL_ mesh in selection")
            return {"CANCELLED"}
        if len(vols) > 1:
            self.report({"ERROR"}, "Multiple volumes selected — select exactly one")
            return {"CANCELLED"}
        if not targets:
            self.report({"ERROR"}, "No linkable target (CAMERA_/SPAWN_/CHECKPOINT_) in selection")
            return {"CANCELLED"}
        if len(targets) > 1:
            self.report({"ERROR"}, "Multiple targets selected — select exactly one")
            return {"CANCELLED"}

        vol    = vols[0]
        target = targets[0]

        # Check vol not already linked
        existing_link = vol.get("og_vol_link", "")
        if existing_link:
            if existing_link == target.name:
                self.report({"WARNING"}, f"{vol.name} is already linked to {target.name}")
            else:
                self.report({"WARNING"}, f"{vol.name} is already linked to {existing_link} — unlink first")
            return {"CANCELLED"}

        # Check target not already has a vol
        existing_vol = _vol_for_target(ctx.scene, target.name)
        if existing_vol:
            self.report({"WARNING"}, f"{target.name} already has {existing_vol.name} linked — unlink first")
            return {"CANCELLED"}

        vol["og_vol_link"] = target.name
        if "og_vol_id" not in vol:
            vol["og_vol_id"] = int(vol.name.replace("VOL_", "") if vol.name[4:].isdigit() else 0)
        vol.name = f"VOL_{target.name}"
        self.report({"INFO"}, f"Linked {vol.name} → {target.name}")
        return {"FINISHED"}


class OG_OT_UnlinkVolume(Operator):
    """Unlink a VOL_ mesh from its target. Works on selected VOL_ meshes."""
    bl_idname   = "og.unlink_volume"
    bl_label    = "Unlink Volume"
    bl_description = "Remove the link from the selected VOL_ mesh and restore its generic name"

    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if o.type == "MESH" and o.name.startswith("VOL_") and "og_vol_link" in o:
                orig_id = o.get("og_vol_id", 0)
                del o["og_vol_link"]
                o.name = f"VOL_{orig_id}"
                count += 1
        if count:
            self.report({"INFO"}, f"Unlinked {count} volume(s)")
        else:
            self.report({"WARNING"}, "No linked VOL_ meshes in selection")
        return {"FINISHED"}


class OG_OT_SelectAndFrame(Operator):
    """Make an object active, select it, and frame it in the viewport."""
    bl_idname = "og.select_and_frame"
    bl_label  = "View"
    bl_description = "Select this object and frame it in the viewport"

    obj_name: bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.obj_name)
        if not obj:
            self.report({"ERROR"}, f"Object '{self.obj_name}' not found")
            return {"CANCELLED"}
        # Deselect all, select and make active
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        ctx.view_layer.objects.active = obj
        # Frame in viewport
        bpy.ops.view3d.view_selected()
        return {"FINISHED"}


class OG_OT_DeleteObject(Operator):
    """Delete an object by name, also cleaning up any linked volumes."""
    bl_idname = "og.delete_object"
    bl_label  = "Delete"
    bl_description = "Delete this object (volumes linked to it will be unlinked)"

    obj_name: bpy.props.StringProperty()

    def execute(self, ctx):
        obj = ctx.scene.objects.get(self.obj_name)
        if not obj:
            self.report({"ERROR"}, f"Object '{self.obj_name}' not found")
            return {"CANCELLED"}
        # Clean any volumes linked to this object before deleting
        for o in ctx.scene.objects:
            if o.type == "MESH" and o.name.startswith("VOL_"):
                if o.get("og_vol_link") == self.obj_name:
                    orig_id = o.get("og_vol_id", 0)
                    del o["og_vol_link"]
                    o.name = f"VOL_{orig_id}"
        # Also delete associated _CAM, _ALIGN, _PIVOT, _LOOK_AT empties for cameras
        suffixes = ["_CAM", "_ALIGN", "_PIVOT", "_LOOK_AT"]
        for suf in suffixes:
            associated = ctx.scene.objects.get(self.obj_name + suf)
            if associated:
                bpy.data.objects.remove(associated, do_unlink=True)
        # Delete the object itself
        bpy.data.objects.remove(obj, do_unlink=True)
        self.report({"INFO"}, f"Deleted '{self.obj_name}'")
        return {"FINISHED"}


class OG_OT_CleanOrphanedLinks(Operator):
    """Remove og_vol_link from any VOL_ whose target object has been deleted."""
    bl_idname   = "og.clean_orphaned_links"
    bl_label    = "Clean Orphaned Links"
    bl_description = "Remove links from volumes whose target (camera/spawn/checkpoint) has been deleted"

    def execute(self, ctx):
        cleaned = _clean_orphaned_vol_links(ctx.scene)
        if cleaned:
            self.report({"INFO"}, f"Cleaned {len(cleaned)} orphaned link(s): {', '.join(cleaned)}")
        else:
            self.report({"INFO"}, "No orphaned links found")
        return {"FINISHED"}


# ── Entity placement ──────────────────────────────────────────────────────────




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








# ---------------------------------------------------------------------------
# OPERATOR + PANEL — Audio / Ambience
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# PANELS
# ---------------------------------------------------------------------------
# Panel hierarchy (all under "OpenGOAL" N-panel tab):
#
#  OG_PT_LevelSettings   — Level name, base ID
#  OG_PT_Scene           — Level Flow: spawns, checkpoints, death plane, bsphere
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



# ── Scene Setup / Level Flow ──────────────────────────────────────────────────



# ── Place Objects ─────────────────────────────────────────────────────────────



# ── Waypoints ─────────────────────────────────────────────────────────────────



# ── NavMesh ───────────────────────────────────────────────────────────────────










class OG_OT_SpawnCamAlign(Operator):
    bl_idname = "og.spawn_cam_align"
    bl_label  = "Add Player Anchor"
    bl_description = (
        "Add a CAMERA_N_ALIGN empty for standoff (side-scroller) mode.\n"
        "Place this at the player position the camera tracks.\n"
        "The camera stays at a fixed offset from this anchor."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        align_name = sel.name + "_ALIGN"
        if ctx.scene.objects.get(align_name):
            self.report({"WARNING"}, f"{align_name} already exists")
            return {"CANCELLED"}
        bpy.ops.object.empty_add(type="PLAIN_AXES", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = align_name
        o.show_name = True
        o.empty_display_size = 0.5
        o.color = (1.0, 0.6, 0.0, 1.0)
        self.report({"INFO"}, f"Added {align_name}  —  place at player anchor position")
        return {"FINISHED"}


class OG_OT_SpawnCamPivot(Operator):
    bl_idname = "og.spawn_cam_pivot"
    bl_label  = "Add Orbit Pivot"
    bl_description = (
        "Add a CAMERA_N_PIVOT empty for orbit mode.\n"
        "The camera orbits around this world position following the player angle."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        pivot_name = sel.name + "_PIVOT"
        if ctx.scene.objects.get(pivot_name):
            self.report({"WARNING"}, f"{pivot_name} already exists")
            return {"CANCELLED"}
        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = pivot_name
        o.show_name = True
        o.empty_display_size = 0.5
        o.color = (1.0, 0.2, 0.8, 1.0)
        self.report({"INFO"}, f"Added {pivot_name}  —  place at orbit center point")
        return {"FINISHED"}




class OG_OT_SpawnCamLookAt(Operator):
    bl_idname = "og.spawn_cam_look_at"
    bl_label  = "Add Look-At Target"
    bl_description = (
        "Add an empty that the camera will always face.\n"
        "Bypasses quaternion export — just point the camera at a world position.\n"
        "Place the empty on the object / area you want the camera to look at."
    )
    def execute(self, ctx):
        sel = ctx.active_object
        if not sel or not sel.name.startswith("CAMERA_") or sel.type != "CAMERA":
            self.report({"ERROR"}, "Select a CAMERA_N camera first")
            return {"CANCELLED"}
        look_name = sel.name + "_LOOKAT"
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = look_name
        o.show_name = True
        o.empty_display_size = 0.4
        o.color = (1.0, 0.8, 0.0, 1.0)
        sel["og_cam_look_at"] = look_name
        self.report({"INFO"}, f"Added {look_name}  —  move it to where the camera should look")
        return {"FINISHED"}

# ── Triggers ─────────────────────────────────────────────────────────────────

class OG_PT_Triggers(Panel):
    bl_label       = "🔗  Triggers"
    bl_idname      = "OG_PT_triggers"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        scene  = ctx.scene
        sel    = ctx.active_object

        # ── Spawn generic volume ──────────────────────────────────────────
        layout.operator("og.spawn_volume", text="Add Trigger Volume", icon="MESH_CUBE")
        layout.separator(factor=0.3)

        # ── Context: link UI ─────────────────────────────────────────────
        # Works regardless of which object is active — we look at the full
        # selection for a VOL_ + linkable target pair.
        sel_vols    = [o for o in ctx.selected_objects if o.type == "MESH" and o.name.startswith("VOL_")]
        sel_targets = [o for o in ctx.selected_objects if _is_linkable(o)]
        active_vol  = sel if (sel and sel.type == "MESH" and sel.name.startswith("VOL_")) else (sel_vols[0] if sel_vols else None)

        if active_vol:
            box = layout.box()
            box.label(text=active_vol.name, icon="MESH_CUBE")
            link = active_vol.get("og_vol_link", "")
            if link:
                box.label(text=f"Linked → {link}", icon="CHECKMARK")
                box.operator("og.unlink_volume", text="Unlink", icon="X")
            else:
                if sel_targets:
                    tgt = sel_targets[0]
                    existing = _vol_for_target(scene, tgt.name)
                    if existing and existing is not active_vol:
                        row = box.row()
                        row.alert = True
                        row.label(text=f"{tgt.name} already linked to {existing.name}", icon="ERROR")
                    else:
                        box.operator("og.link_volume",
                                     text=f"Link → {tgt.name}", icon="LINKED")
                else:
                    box.label(text="Not linked", icon="ERROR")
                    box.label(text="Shift-select a target to link", icon="INFO")
            layout.separator(factor=0.3)
        elif sel_targets and not sel_vols:
            # Target selected but no vol — show hint
            box = layout.box()
            box.label(text=f"{sel_targets[0].name} selected", icon="INFO")
            box.label(text="Also select a VOL_ to link", icon="INFO")
            layout.separator(factor=0.3)

        # ── All volumes list ──────────────────────────────────────────────
        vols = sorted([o for o in scene.objects
                       if o.type == "MESH" and o.name.startswith("VOL_")],
                      key=lambda o: o.name)
        if not vols:
            box = layout.box()
            box.label(text="No trigger volumes in scene", icon="INFO")
            return

        # Collapsible header
        row = layout.row()
        icon = "TRIA_DOWN" if ctx.scene.og_props.show_volume_list else "TRIA_RIGHT"
        row.prop(ctx.scene.og_props, "show_volume_list",
                 text=f"Volumes ({len(vols)})", icon=icon, emboss=False)
        if not ctx.scene.og_props.show_volume_list:
            return

        box = layout.box()
        for v in vols:
            row = box.row(align=True)
            link = v.get("og_vol_link", "")
            if link:
                target_exists = bool(scene.objects.get(link))
                if target_exists:
                    row.label(text=v.name, icon="CHECKMARK")
                    row.label(text=f"→ {link}")
                else:
                    row.alert = True
                    row.label(text=v.name, icon="ERROR")
                    row.label(text=f"→ {link} (DELETED)")
            else:
                row.alert = True
                row.label(text=v.name, icon="MESH_CUBE")
                row.label(text="unlinked")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = v.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = v.name

        # Orphan cleanup button — only show if any orphans exist
        orphans = [o for o in vols if o.get("og_vol_link") and not scene.objects.get(o.get("og_vol_link", ""))]
        if orphans:
            layout.separator(factor=0.3)
            row = layout.row()
            row.alert = True
            row.operator("og.clean_orphaned_links", text=f"Clean {len(orphans)} Orphaned Link(s)", icon="ERROR")


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
        scene  = ctx.scene
        sel    = ctx.active_object

        # ── Top-level add buttons ─────────────────────────────────────────
        row = layout.row(align=True)
        row.operator("og.spawn_camera", text="Add Camera", icon="CAMERA_DATA")
        # If a camera is active, auto-link the new volume to it
        if sel and sel.type == "CAMERA" and sel.name.startswith("CAMERA_"):
            op = row.operator("og.spawn_volume_autolink", text="Add Volume", icon="CUBE")
            op.target_name = sel.name
        else:
            row.operator("og.spawn_volume", text="Add Volume", icon="CUBE")

        layout.separator()

        # ── Selected-object context section ──────────────────────────────
        # Show context-sensitive controls when a relevant object is active
        if sel and sel.type == "CAMERA" and sel.name.startswith("CAMERA_"):
            self._draw_camera_props(layout, sel, scene)
        elif sel and sel.type == "MESH" and sel.name.startswith("VOL_"):
            self._draw_volume_props(layout, sel, scene)

        layout.separator()

        # ── Full camera list ──────────────────────────────────────────────
        cam_objects = sorted(
            [o for o in scene.objects
             if o.name.startswith("CAMERA_") and o.type == "CAMERA"],
            key=lambda o: o.name,
        )
        if not cam_objects:
            box = layout.box()
            box.label(text="No cameras placed yet", icon="INFO")
            return

        # Collapsible header
        row = layout.row()
        icon = "TRIA_DOWN" if ctx.scene.og_props.show_camera_list else "TRIA_RIGHT"
        row.prop(ctx.scene.og_props, "show_camera_list",
                 text=f"Cameras ({len(cam_objects)})", icon=icon, emboss=False)
        if not ctx.scene.og_props.show_camera_list:
            return

        # Build reverse map: cam_name -> list of linked vol names
        vol_map = {}
        for o in scene.objects:
            if o.type == "MESH" and o.name.startswith("VOL_"):
                link = o.get("og_vol_link", "")
                if link and link.startswith("CAMERA_"):
                    vol_map.setdefault(link, []).append(o.name)

        for cam_obj in cam_objects:
            box = layout.box()
            row = box.row(align=True)
            row.label(text=cam_obj.name, icon="CAMERA_DATA")
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = cam_obj.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = cam_obj.name

            mode   = cam_obj.get("og_cam_mode",   "fixed")
            interp = float(cam_obj.get("og_cam_interp", 1.0))
            fov    = float(cam_obj.get("og_cam_fov",    0.0))

            # Mode
            mrow = box.row(align=True)
            mrow.label(text="Mode:")
            for m, lbl in (("fixed","Fixed"),("standoff","Side-Scroll"),("orbit","Orbit")):
                op = mrow.operator("og.set_cam_prop", text=lbl, depress=(mode == m))
                op.cam_name = cam_obj.name; op.prop_name = "og_cam_mode"; op.str_val = m

            # Blend + FOV
            brow = box.row(align=True)
            brow.label(text=f"Blend: {interp:.1f}s")
            op = brow.operator("og.nudge_cam_float", text="-"); op.cam_name=cam_obj.name; op.prop_name="og_cam_interp"; op.delta=-0.5
            op = brow.operator("og.nudge_cam_float", text="+"); op.cam_name=cam_obj.name; op.prop_name="og_cam_interp"; op.delta=0.5
            frow = box.row(align=True)
            frow.label(text=f"FOV: {'default' if fov<=0 else f'{fov:.0f}°'}")
            op = frow.operator("og.nudge_cam_float", text="-"); op.cam_name=cam_obj.name; op.prop_name="og_cam_fov"; op.delta=-5.0
            op = frow.operator("og.nudge_cam_float", text="+"); op.cam_name=cam_obj.name; op.prop_name="og_cam_fov"; op.delta=5.0

            # Mode helpers
            if mode == "standoff":
                align_name = cam_obj.name + "_ALIGN"
                has_align = bool(scene.objects.get(align_name))
                arow = box.row()
                if has_align:
                    arow.label(text=f"Anchor: {align_name}", icon="CHECKMARK")
                else:
                    arow.label(text="No anchor", icon="ERROR")
                    arow.operator("og.spawn_cam_align", text="Add Anchor")
            elif mode == "orbit":
                pivot_name = cam_obj.name + "_PIVOT"
                has_pivot = bool(scene.objects.get(pivot_name))
                prow = box.row()
                if has_pivot:
                    prow.label(text=f"Pivot: {pivot_name}", icon="CHECKMARK")
                else:
                    prow.label(text="No pivot", icon="ERROR")
                    prow.operator("og.spawn_cam_pivot", text="Add Pivot")

            # Linked volumes
            linked_vols = vol_map.get(cam_obj.name, [])
            vrow = box.row(align=True)
            if linked_vols:
                vrow.label(text=f"Trigger: {', '.join(linked_vols)}", icon="CHECKMARK")
                op = vrow.operator("og.spawn_volume_autolink", text="", icon="ADD")
                op.target_name = cam_obj.name
            else:
                vrow.label(text="No trigger — always active", icon="INFO")
                op = vrow.operator("og.spawn_volume_autolink", text="Add Volume", icon="ADD")
                op.target_name = cam_obj.name

    def _draw_camera_props(self, layout, cam, scene):
        """Context panel when a CAMERA_ object is active."""
        box = layout.box()
        box.label(text=f"Selected: {cam.name}", icon="CAMERA_DATA")
        box.label(text="Numpad-0 to look through camera", icon="INFO")
        # Show the actual world rotation quaternion so user can verify it's not identity
        try:
            q = cam.matrix_world.to_quaternion()
            row = box.row()
            row.label(text=f"Rot (wxyz): {q.w:.2f} {q.x:.2f} {q.y:.2f} {q.z:.2f}")
            if abs(q.w) > 0.99:
                box.label(text="⚠ Camera has no rotation!", icon="ERROR")
                box.label(text="Rotate it to aim, then export.")
        except Exception:
            pass
        # Mode-specific helpers
        mode = cam.get("og_cam_mode", "fixed")
        if mode == "standoff" and not scene.objects.get(cam.name + "_ALIGN"):
            box.operator("og.spawn_cam_align", text="Add Player Anchor")
        if mode == "orbit" and not scene.objects.get(cam.name + "_PIVOT"):
            box.operator("og.spawn_cam_pivot", text="Add Orbit Pivot")
        # Look-at target UI
        look_at_name = cam.get("og_cam_look_at", "").strip()
        look_obj = scene.objects.get(look_at_name) if look_at_name else None
        lbox = layout.box()
        lrow = lbox.row()
        if look_obj:
            lrow.label(text=f"Look at: {look_at_name}", icon="CHECKMARK")
            lrow2 = lbox.row()
            op = lrow2.operator("og.set_cam_prop", text="Clear", icon="X")
            op.cam_name = cam.name; op.prop_name = "og_cam_look_at"; op.str_val = ""
            lbox.label(text="Camera ignores its rotation — aims at target", icon="INFO")
        else:
            lrow.label(text="No Look-At target  (uses camera rotation)", icon="DOT")
            lbox.operator("og.spawn_cam_look_at", text="Add Look-At Target", icon="PIVOT_CURSOR")

    def _draw_volume_props(self, layout, vol, scene):
        """Context panel when a VOL_ mesh is active in Camera panel."""
        box = layout.box()
        box.label(text=f"Selected: {vol.name}", icon="MESH_CUBE")
        link = vol.get("og_vol_link", "")
        if link:
            box.label(text=f"Linked to: {link}", icon="CHECKMARK")
            box.operator("og.unlink_volume", text="Unlink", icon="X")
        else:
            box.label(text="Not linked to any camera", icon="ERROR")
            box.label(text="Use Triggers panel to link", icon="INFO")


class OG_OT_SetCamProp(Operator):
    """Set a string custom property on a CAMERA_ object."""
    bl_idname   = "og.set_cam_prop"
    bl_label    = "Set Camera Property"
    bl_options  = {"REGISTER", "UNDO"}
    cam_name:  bpy.props.StringProperty()
    prop_name: bpy.props.StringProperty()
    str_val:   bpy.props.StringProperty()
    def execute(self, ctx):
        o = ctx.scene.objects.get(self.cam_name)
        if o:
            o[self.prop_name] = self.str_val
        return {"FINISHED"}


class OG_OT_NudgeCamFloat(Operator):
    """Nudge a float custom property on a CAMERA_ object."""
    bl_idname   = "og.nudge_cam_float"
    bl_label    = "Nudge Camera Float"
    bl_options  = {"REGISTER", "UNDO"}
    cam_name:  bpy.props.StringProperty()
    prop_name: bpy.props.StringProperty()
    delta:     bpy.props.FloatProperty()
    def execute(self, ctx):
        o = ctx.scene.objects.get(self.cam_name)
        if o:
            current = float(o.get(self.prop_name, 0.0))
            o[self.prop_name] = round(max(0.0, current + self.delta), 2)
        return {"FINISHED"}




# ── Platform ──────────────────────────────────────────────────────────────────


class OG_OT_NudgeFloatProp(Operator):
    """Nudge a float custom property on the active object by a fixed delta."""
    bl_idname  = "og.nudge_float_prop"
    bl_label   = "Nudge Float Property"
    bl_options = {"REGISTER", "UNDO"}

    prop_name: bpy.props.StringProperty()
    delta:     bpy.props.FloatProperty()
    val_min:   bpy.props.FloatProperty(default=-1e9)
    val_max:   bpy.props.FloatProperty(default=1e9)

    def execute(self, ctx):
        o = ctx.active_object
        if o:
            current = float(o.get(self.prop_name, 0.0))
            o[self.prop_name] = round(max(self.val_min, min(self.val_max, current + self.delta)), 4)
        return {"FINISHED"}


class OG_OT_TogglePlatformWrap(Operator):
    """Toggle wrap-phase (one-way loop vs ping-pong) on the selected platform."""
    bl_idname = "og.toggle_platform_wrap"
    bl_label  = "Toggle Wrap Phase"

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        o["og_sync_wrap"] = 0 if bool(o.get("og_sync_wrap", 0)) else 1
        return {"FINISHED"}


class OG_OT_SetPlatformDefaults(Operator):
    """Reset sync values on the selected platform actor to defaults."""
    bl_idname = "og.set_platform_defaults"
    bl_label  = "Reset Sync Defaults"

    def execute(self, ctx):
        o = ctx.active_object
        if not o:
            return {"CANCELLED"}
        o["og_sync_period"]   = 4.0
        o["og_sync_phase"]    = 0.0
        o["og_sync_ease_out"] = 0.15
        o["og_sync_ease_in"]  = 0.15
        o["og_sync_wrap"]     = 0
        return {"FINISHED"}


class OG_OT_SpawnPlatform(Operator):
    """Place a platform actor empty at the 3D cursor."""
    bl_idname     = "og.spawn_platform"
    bl_label      = "Add Platform"
    bl_description = "Place a platform actor at the 3D cursor"

    def execute(self, ctx):
        etype = ctx.scene.og_props.platform_type
        einfo = ENTITY_DEFS.get(etype, {})

        # Use count of existing same-type actors as uid, matching OG_OT_SpawnEntity pattern
        n   = len([o for o in ctx.scene.objects if o.name.startswith(f"ACTOR_{etype}_")])
        uid = f"{n:04d}"

        bpy.ops.object.empty_add(type=einfo.get("shape", "CUBE"),
                                 location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name               = f"ACTOR_{etype}_{uid}"
        o.show_name          = True
        o.empty_display_size = 0.5
        o.color              = einfo.get("color", (0.5, 0.5, 0.8, 1.0))
        if hasattr(o, "show_in_front"):
            o.show_in_front = True
        self.report({"INFO"}, f"Added {o.name}")
        return {"FINISHED"}


# ── Platforms panel ───────────────────────────────────────────────────────────


def _draw_platform_settings(layout, sel, scene):
    """Draw per-platform settings for the active platform actor."""
    etype = sel.name.split("_", 2)[1]
    einfo = ENTITY_DEFS.get(etype, {})

    layout.label(text=einfo.get("label", etype), icon="CUBE")

    # ── Sync controls (plat, plat-eco, side-to-side-plat) ────────────────────
    if einfo.get("needs_sync"):
        box = layout.box()
        box.label(text="Sync (Path Timing)", icon="TIME")

        wp_prefix = sel.name + "_wp_"
        wp_count  = sum(1 for o in scene.objects
                        if o.name.startswith(wp_prefix) and o.type == "EMPTY")

        if wp_count < 2:
            box.label(text="⚠ Add ≥2 waypoints to enable movement", icon="INFO")
        else:
            box.label(text=f"✓ {wp_count} waypoints — platform will move", icon="CHECKMARK")

        col = box.column(align=True)

        # Period
        row = col.row(align=True)
        row.label(text="Period (s):")
        period = float(sel.get("og_sync_period", 4.0))
        op = row.operator("og.nudge_float_prop", text="-0.5", icon="REMOVE")
        op.prop_name = "og_sync_period"; op.delta = -0.5; op.val_min = 0.5
        row.label(text=f"{period:.1f}s")
        op = row.operator("og.nudge_float_prop", text="+0.5", icon="ADD")
        op.prop_name = "og_sync_period"; op.delta = 0.5; op.val_max = 300.0

        # Phase
        row = col.row(align=True)
        row.label(text="Phase (0–1):")
        phase = float(sel.get("og_sync_phase", 0.0))
        op = row.operator("og.nudge_float_prop", text="-0.1", icon="REMOVE")
        op.prop_name = "og_sync_phase"; op.delta = -0.1; op.val_min = 0.0
        row.label(text=f"{phase:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.1", icon="ADD")
        op.prop_name = "og_sync_phase"; op.delta = 0.1; op.val_max = 0.9

        # Ease out
        row = col.row(align=True)
        row.label(text="Ease Out:")
        ease_out = float(sel.get("og_sync_ease_out", 0.15))
        op = row.operator("og.nudge_float_prop", text="-0.05", icon="REMOVE")
        op.prop_name = "og_sync_ease_out"; op.delta = -0.05; op.val_min = 0.0
        row.label(text=f"{ease_out:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.05", icon="ADD")
        op.prop_name = "og_sync_ease_out"; op.delta = 0.05; op.val_max = 0.5

        # Ease in
        row = col.row(align=True)
        row.label(text="Ease In:")
        ease_in = float(sel.get("og_sync_ease_in", 0.15))
        op = row.operator("og.nudge_float_prop", text="-0.05", icon="REMOVE")
        op.prop_name = "og_sync_ease_in"; op.delta = -0.05; op.val_min = 0.0
        row.label(text=f"{ease_in:.2f}")
        op = row.operator("og.nudge_float_prop", text="+0.05", icon="ADD")
        op.prop_name = "og_sync_ease_in"; op.delta = 0.05; op.val_max = 0.5

        # Wrap phase toggle
        wrap = bool(sel.get("og_sync_wrap", 0))
        row = box.row()
        icon = "CHECKBOX_HLT" if wrap else "CHECKBOX_DEHLT"
        label = "Loop (wrap-phase) ✓" if wrap else "Loop (wrap-phase)"
        row.operator("og.toggle_platform_wrap", text=label, icon=icon)

        box.operator("og.set_platform_defaults", text="Reset to Defaults", icon="LOOP_BACK")

        if wp_count >= 2:
            box.label(text="Tip: phase staggers multiple platforms", icon="INFO")

    # ── plat-button path info ─────────────────────────────────────────────────
    if einfo.get("needs_path") and not einfo.get("needs_sync"):
        box = layout.box()
        box.label(text="Path (Button Travel)", icon="ANIM")
        wp_prefix = sel.name + "_wp_"
        wp_count  = sum(1 for o in scene.objects
                        if o.name.startswith(wp_prefix) and o.type == "EMPTY")
        if wp_count < 2:
            box.label(text="⚠ Needs ≥2 waypoints (start + end)", icon="ERROR")
        else:
            box.label(text=f"✓ {wp_count} waypoints", icon="CHECKMARK")
        box.label(text="Use Waypoints panel to add points ↓", icon="INFO")

    # ── notice-dist (plat-eco) ────────────────────────────────────────────────
    if einfo.get("needs_notice_dist"):
        box = layout.box()
        box.label(text="Eco Notice Distance", icon="RADIOBUT_ON")
        notice = float(sel.get("og_notice_dist", -1.0))
        row = box.row(align=True)
        op = row.operator("og.nudge_float_prop", text="-5m", icon="REMOVE")
        op.prop_name = "og_notice_dist"; op.delta = -5.0; op.val_min = 0.0
        if notice < 0:
            row.label(text="∞ (always active)")
        else:
            row.label(text=f"{notice:.0f}m")
        op = row.operator("og.nudge_float_prop", text="+5m", icon="ADD")
        op.prop_name = "og_notice_dist"; op.delta = 5.0; op.val_max = 500.0
        toggle_row = box.row()
        if notice < 0:
            toggle_row.label(text="Moves without eco — click +5m to set range", icon="INFO")
        else:
            op = toggle_row.operator("og.nudge_float_prop", text="Set Always Active", icon="RADIOBUT_ON")
            op.prop_name = "og_notice_dist"; op.delta = -999.0; op.val_min = -1.0


class OG_PT_Platforms(Panel):
    bl_label       = "🟦  Platforms"
    bl_idname      = "OG_PT_platforms"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_props
        scene  = ctx.scene

        # ── Spawn section (always visible) ───────────────────────────────────
        layout.label(text="Spawn", icon="ADD")
        layout.prop(props, "platform_type", text="")
        layout.operator("og.spawn_platform", text="Add Platform at Cursor", icon="ADD")

        layout.separator(factor=0.5)

        # ── Active platform settings (only when a platform actor is selected) ─
        sel = ctx.active_object
        is_platform_selected = (
            sel is not None
            and sel.name.startswith("ACTOR_")
            and "_wp_" not in sel.name
            and len(sel.name.split("_", 2)) >= 3
            and _actor_is_platform(sel.name.split("_", 2)[1])
        )

        if is_platform_selected:
            layout.separator(factor=0.2)
            layout.label(text="Selected Platform Settings", icon="SETTINGS")
            _draw_platform_settings(layout, sel, scene)
            layout.separator(factor=0.5)

        # ── Scene platform list (collapsible) ────────────────────────────────
        plats = sorted(
            [o for o in scene.objects
             if o.name.startswith("ACTOR_")
             and "_wp_" not in o.name
             and o.type == "EMPTY"
             and len(o.name.split("_", 2)) >= 3
             and _actor_is_platform(o.name.split("_", 2)[1])],
            key=lambda o: o.name
        )

        if not plats:
            box = layout.box()
            box.label(text="No platforms in scene", icon="INFO")
            return

        row = layout.row()
        icon = "TRIA_DOWN" if props.show_platform_list else "TRIA_RIGHT"
        row.prop(props, "show_platform_list",
                 text=f"Platforms ({len(plats)})", icon=icon, emboss=False)

        if not props.show_platform_list:
            return

        box = layout.box()
        for p in plats:
            etype = p.name.split("_", 2)[1]
            einfo = ENTITY_DEFS.get(etype, {})
            label = einfo.get("label", etype)
            is_active = (sel is not None and sel == p)

            row = box.row(align=True)
            if is_active:
                row.alert = False
                row.label(text=f"▶ {label}", icon="CUBE")
            else:
                row.label(text=label, icon="CUBE")
            row.label(text=p.name.split("_", 2)[2])  # uid portion

            # Frame/select button — selecting naturally triggers settings above
            op = row.operator("og.select_and_frame", text="", icon="VIEWZOOM")
            op.obj_name = p.name
            op = row.operator("og.delete_object", text="", icon="TRASH")
            op.obj_name = p.name


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



# ── Developer Tools ───────────────────────────────────────────────────────────

class OG_OT_ReloadAddon(Operator):
    """Hot-reload the OpenGOAL addon from disk — clears all Python module caches.
    Use this after updating the .py file instead of restarting Blender."""
    bl_idname = "og.reload_addon"
    bl_label  = "Reload Addon"
    bl_description = "Reload the OpenGOAL addon from disk without restarting Blender"

    def execute(self, ctx):
        import importlib, sys
        # Find our module name in sys.modules
        mod_name = None
        for name, mod in list(sys.modules.items()):
            if hasattr(mod, "__file__") and mod.__file__ and "opengoal_tools" in mod.__file__:
                mod_name = name
                break
        if mod_name is None:
            self.report({"ERROR"}, "Could not find opengoal_tools in sys.modules")
            return {"CANCELLED"}
        try:
            # Unregister current version
            unregister()
            # Force reload from disk — bypasses all caches
            mod = sys.modules[mod_name]
            importlib.reload(mod)
            # Re-register the freshly loaded version
            mod.register()
            self.report({"INFO"}, f"Reloaded {mod_name} from disk ✓")
        except Exception as e:
            self.report({"ERROR"}, f"Reload failed: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class OG_OT_CleanLevelFiles(Operator):
    """Delete generated files for the current level so the next build writes them fresh.
    Removes: obs.gc, .jsonc, .glb, .gd — forces a clean compile without stale cached data."""
    bl_idname = "og.clean_level_files"
    bl_label  = "Clean Level Files"
    bl_description = "Delete generated level files to force a clean rebuild (obs.gc, jsonc, glb, gd)"

    def execute(self, ctx):
        name = ctx.scene.og_props.level_name.strip().lower().replace(" ", "-")
        if not name:
            self.report({"ERROR"}, "No level name set")
            return {"CANCELLED"}

        deleted = []
        skipped = []

        # goal_src obs.gc — the one that causes stale compile errors
        obs_gc = _goal_src() / "levels" / name / f"{name}-obs.gc"
        # custom_assets files
        assets = _ldir(name)
        targets = [
            obs_gc,
            assets / f"{name}.jsonc",
            assets / f"{name}.glb",
            assets / f"{_nick(name)}.gd",
        ]

        for p in targets:
            if p.exists():
                p.unlink()
                deleted.append(p.name)
            else:
                skipped.append(p.name)

        if deleted:
            self.report({"INFO"}, f"Deleted: {', '.join(deleted)}" +
                        (f"  (not found: {', '.join(skipped)})" if skipped else ""))
        else:
            self.report({"WARNING"}, f"Nothing to delete — files not found for '{name}'")
        return {"FINISHED"}


class OG_PT_DevTools(Panel):
    bl_label       = "🔧  Developer Tools"
    bl_idname      = "OG_PT_dev_tools"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout

        # ── Reload / Clean ───────────────────────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("og.reload_addon",       text="🔄  Reload Addon", icon="FILE_REFRESH")
        row.operator("og.clean_level_files",  text="🗑  Clean Files",  icon="TRASH")
        layout.separator(factor=0.5)

        # Paths
        layout.label(text="Paths", icon="PREFERENCES")
        box = layout.box()
        gk_ok = _gk().exists()
        gc_ok = _goalc().exists()
        gp_ok = _game_gp().exists()
        box.label(text=f"gk{_EXE}:    {'✓ OK' if gk_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gk_ok else "ERROR")
        box.label(text=f"goalc{_EXE}: {'✓ OK' if gc_ok else '✗ NOT FOUND'}", icon="CHECKMARK" if gc_ok else "ERROR")
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



class OG_OT_RemoveLevel(Operator):
    """Remove a custom level and all its files from the project."""
    bl_idname   = "og.remove_level"
    bl_label    = "Remove Level"
    bl_options  = {"REGISTER", "UNDO"}
    level_name: bpy.props.StringProperty()

    def invoke(self, ctx, event):
        return ctx.window_manager.invoke_confirm(self, event)

    def execute(self, ctx):
        if not self.level_name:
            self.report({"ERROR"}, "No level name given")
            return {"CANCELLED"}
        msgs = remove_level(self.level_name)
        for m in msgs:
            log(m)
        self.report({"INFO"}, f"Removed level '{self.level_name}'")
        return {"FINISHED"}


class OG_OT_RefreshLevels(Operator):
    """Refresh the custom levels list."""
    bl_idname = "og.refresh_levels"
    bl_label  = "Refresh"
    def execute(self, ctx):
        return {"FINISHED"}


class OG_PT_LevelManager(Panel):
    bl_label       = "🗂  Level Manager"
    bl_idname      = "OG_PT_level_manager"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout

        try:
            levels = discover_custom_levels()
        except Exception as e:
            layout.label(text=f"Error scanning levels: {e}", icon="ERROR")
            return

        if not levels:
            layout.label(text="No custom levels found", icon="INFO")
            layout.label(text="Set data path in addon preferences")
            return

        for info in levels:
            box  = layout.box()
            row  = box.row()

            # Name + conflict warning
            if info["conflict"]:
                row.alert = True
                row.label(text=f"⚠ {info['name']}", icon="ERROR")
            elif len(info["name"]) > 10:
                row.alert = True
                row.label(text=f"⚠ {info['name']} (name too long!)", icon="ERROR")
            else:
                row.label(text=info["name"], icon="SCENE_DATA")

            # Remove button
            op = row.operator("og.remove_level", text="", icon="TRASH")
            op.level_name = info["name"]

            # Status dots
            srow = box.row(align=True)
            srow.enabled = False
            srow.label(text=f"glb:{'✓' if info['has_glb'] else '✗'}  "
                           f"jsonc:{'✓' if info['has_jsonc'] else '✗'}  "
                           f"obs:{'✓' if info['has_obs'] else '✗'}  "
                           f"gp:{'✓' if info['has_gp'] else '✗'}  "
                           f"DGO:{info['dgo']}")

            if info["conflict"]:
                box.label(text="DGO name conflict — rename this level!", icon="ERROR")
            if not info["has_gp"] and (info["has_glb"] or info["has_obs"]):
                box.label(text="Not registered in game.gp — re-export to fix", icon="ERROR")

        layout.separator()
        layout.operator("og.refresh_levels", text="Refresh List", icon="FILE_REFRESH")


# ---------------------------------------------------------------------------
# REGISTER / UNREGISTER
# ---------------------------------------------------------------------------

classes = (
    OGPreferences, OGProperties,
    OG_OT_ReloadAddon, OG_OT_CleanLevelFiles,
    OG_OT_SpawnPlayer, OG_OT_SpawnCheckpoint, OG_OT_SpawnCamAnchor,
    OG_OT_SpawnVolume, OG_OT_SpawnVolumeAutoLink, OG_OT_LinkVolume, OG_OT_UnlinkVolume, OG_OT_CleanOrphanedLinks,
    OG_OT_SelectAndFrame, OG_OT_DeleteObject,
    OG_OT_SpawnEntity,
    OG_OT_SpawnCamera, OG_OT_SpawnCamAlign, OG_OT_SpawnCamPivot,
    OG_OT_SpawnCamLookAt,
    # OG_OT_LinkCamVolume, OG_OT_UnlinkCamVolume — replaced by generic OG_OT_LinkVolume
    OG_OT_SetCamProp, OG_OT_NudgeCamFloat,
    OG_OT_NudgeFloatProp,
    OG_OT_TogglePlatformWrap, OG_OT_SetPlatformDefaults, OG_OT_SpawnPlatform,
    OG_OT_AddWaypoint, OG_OT_DeleteWaypoint,
    OG_OT_MarkNavMesh, OG_OT_UnmarkNavMesh,
    OG_OT_LinkNavMesh, OG_OT_UnlinkNavMesh,
    OG_OT_PickNavMesh,
    OG_OT_ExportBuild, OG_OT_GeoRebuild, OG_OT_Play, OG_OT_PlayAutoLoad,
    OG_OT_ExportBuildPlay,
    OG_OT_OpenFolder, OG_OT_OpenFile,
    OG_OT_BakeLighting,
    OG_OT_PickSound,
    OG_OT_AddSoundEmitter,
    OG_PT_LevelSettings,
    OG_PT_LevelManager,
    OG_OT_RemoveLevel,
    OG_OT_RefreshLevels,
    OG_PT_Scene,
    OG_PT_PlaceObjects,
    OG_PT_Waypoints,
    OG_PT_Platforms,
    OG_PT_Triggers,
    OG_PT_Camera,
    OG_PT_NavMesh,
    OG_PT_BuildPlay,
    OG_PT_DevTools,
    OG_PT_Collision,
    OG_PT_LightBaking,
    OG_PT_Audio,
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
