# ---------------------------------------------------------------------------
# data.py — OpenGOAL Level Tools
# Pure data tables, enums, and derived constants.
# No bpy imports — safe to import anywhere.
# ---------------------------------------------------------------------------

# --- PAT enums + ENTITY_DEFS + CRATE_ITEMS + ENTITY_WIKI ---

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
    "babak":            {"label":"Babak (Lurker)",       "cat":"Enemies",   "tpage_group":"Beach",    "ag":"babak-ag.go",             "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(1.0,0.1,0.1,1.0), "shape":"SPHERE", "glb": "levels/beach/babak-lod0.glb"},
    "lurkercrab":       {"label":"Lurker Crab",          "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkercrab-ag.go",        "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.8,0.4,0.0,1.0), "shape":"SPHERE", "glb": "levels/beach/lurkercrab-lod0.glb"},
    "lurkerpuppy":      {"label":"Lurker Puppy",         "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkerpuppy-ag.go",       "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.5,0.1,1.0), "shape":"SPHERE", "glb": "levels/beach/lurkerpuppy-lod0.glb"},
    # Jungle group (tpages: 385, 531, 386, 388)
    "hopper":           {"label":"Hopper",               "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"hopper-ag.go",            "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(1.0,0.2,0.1,1.0), "shape":"SPHERE", "glb": "levels/jungle/hopper-lod0.glb"},
    # Swamp group (tpages: 358, 659, 629, 630)
    "swamp-rat":        {"label":"Swamp Rat",            "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"swamp-rat-ag.go",         "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.5,0.35,0.1,1.0),"shape":"SPHERE", "glb": "levels/swamp/swamp-rat-lod0.glb"},
    "kermit":           {"label":"Kermit (Lurker)",      "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"kermit-ag.go",            "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.2,0.7,0.2,1.0), "shape":"SPHERE", "glb": "levels/swamp/kermit-lod0.glb"},
    # Snow group (tpages: 710, 842, 711, 712)
    "snow-bunny":       {"label":"Snow Bunny",           "cat":"Enemies",   "tpage_group":"Snow",     "ag":"snow-bunny-ag.go",        "nav_safe":False, "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.9,1.0,1.0), "shape":"SPHERE", "glb": "levels/snow/snow-bunny-lod0.glb"},
    # Sunken group (tpages: 661, 663, 714, 662)
    "double-lurker":    {"label":"Double Lurker",        "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"double-lurker-ag.go",     "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.7,0.15,0.15,1.0),"shape":"SPHERE", "glb": ["levels/sunken/double-lurker-lod0.glb", "levels/sunken/double-lurker-top-lod0.glb"]},
    # Misty group (tpages: 516, 521, 518, 520)
    "bonelurker":       {"label":"Bone Lurker",          "cat":"Enemies",   "tpage_group":"Misty",    "ag":"bonelurker-ag.go",        "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.8,0.7,0.5,1.0), "shape":"SPHERE", "glb": "levels/misty/bonelurker-lod0.glb"},
    "muse":             {"label":"Muse",                 "cat":"Enemies",   "tpage_group":"Misty",    "ag":"muse-ag.go",              "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.9,0.6,0.9,1.0), "shape":"SPHERE", "glb": "levels/misty/muse-lod0.glb"},
    # Maincave group (tpages: 1313, 1315, 1314, 1312)
    "baby-spider":      {"label":"Baby Spider",          "cat":"Enemies",   "tpage_group":"Maincave", "ag":"baby-spider-ag.go",       "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.5,0.2,0.1,1.0), "shape":"SPHERE", "glb": "levels/darkcave/baby-spider-lod0.glb"},
    # Final group (tpages: varies)
    "green-eco-lurker": {"label":"Green Eco Lurker",     "cat":"Enemies",   "tpage_group":"Final",    "ag":"green-eco-lurker-ag.go",  "nav_safe":False, "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"nav-enemy",        "color":(0.2,0.8,0.2,1.0), "shape":"SPHERE", "glb": "levels/finalboss/green-eco-lurker-lod0.glb"},

    # ---- PROCESS-DRAWABLE ENEMIES — nav_safe=True, no navmesh, may need path ----
    # Grouped by tpage source level.
    # Beach group
    "lurkerworm":       {"label":"Lurker Worm",          "cat":"Enemies",   "tpage_group":"Beach",    "ag":"lurkerworm-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.6,0.1,1.0), "shape":"SPHERE", "glb": "levels/beach/lurkerworm-lod0.glb"},
    # Jungle group
    "junglesnake":      {"label":"Jungle Snake",         "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"junglesnake-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.2,0.6,0.2,1.0), "shape":"SPHERE", "glb": "levels/jungle/junglesnake-lod0.glb"},
    # Swamp group
    "swamp-bat":        {"label":"Swamp Bat",            "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"swamp-bat-ag.go",         "nav_safe":True,  "needs_path":True,  "needs_pathb":True,  "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.2,0.5,1.0), "shape":"SPHERE", "glb": "levels/swamp/swamp-bat-lod0.glb"},
    # Snow group
    "yeti":             {"label":"Yeti",                 "cat":"Enemies",   "tpage_group":"Snow",     "ag":"yeti-ag.go",              "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.95,1.0,1.0),"shape":"SPHERE", "glb": "levels/snow/yeti-lod0.glb"},
    # Sunken group
    "bully":            {"label":"Bully",                "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"bully-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.9,1.0), "shape":"SPHERE", "glb": "levels/sunken/bully-lod0.glb"},
    "puffer":           {"label":"Puffer",               "cat":"Enemies",   "tpage_group":"Sunken",   "ag":"puffer-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.4,0.9,1.0), "shape":"SPHERE", "glb": "levels/sunken/puffer-main-lod0.glb"},
    # Ogre group (tpages: 875, 967, 884, 1117)
    "flying-lurker":    {"label":"Flying Lurker",        "cat":"Enemies",   "tpage_group":"Ogre",     "ag":"flying-lurker-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.2,0.8,1.0), "shape":"SPHERE", "glb": "levels/ogre/flying-lurker-lod0.glb"},
    "plunger-lurker":   {"label":"Plunger Lurker",       "cat":"Enemies",   "tpage_group":"Ogre",     "ag":"plunger-lurker-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.8,0.3,0.3,1.0), "shape":"SPHERE", "glb": "levels/ogre/plunger-lurker-lod0.glb"},
    # Maincave group
    "mother-spider":    {"label":"Mother Spider",        "cat":"Enemies",   "tpage_group":"Maincave", "ag":"mother-spider-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.2,0.1,1.0), "shape":"SPHERE", "glb": "levels/darkcave/mother-spider-lod0.glb"},
    "gnawer":           {"label":"Gnawer",               "cat":"Enemies",   "tpage_group":"Maincave", "ag":"gnawer-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.3,0.1,1.0), "shape":"SPHERE", "glb": "levels/maincave/gnawer-lod0.glb"},
    "driller-lurker":   {"label":"Driller Lurker",       "cat":"Enemies",   "tpage_group":"Maincave", "ag":"driller-lurker-ag.go",    "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.5,0.5,1.0), "shape":"SPHERE", "glb": "levels/maincave/driller-lurker-lod0.glb"},
    "dark-crystal":     {"label":"Dark Crystal",         "cat":"Enemies",   "tpage_group":"Maincave", "ag":"dark-crystal-ag.go",      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.0,0.6,1.0), "shape":"SPHERE", "glb": "levels/darkcave/dark-crystal-lod0.glb"},
    # Robocave group (tpages: 1318, 1319, 1317, 1316)
    "cavecrusher":      {"label":"Cave Crusher",         "cat":"Enemies",   "tpage_group":"Robocave", "ag":"cavecrusher-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.6,1.0), "shape":"SPHERE", "glb": "levels/robocave/cavecrusher-lod0.glb"},
    # Misty group
    "quicksandlurker":  {"label":"Quicksand Lurker",     "cat":"Enemies",   "tpage_group":"Misty",    "ag":"quicksandlurker-ag.go",   "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.8,0.3,1.0), "shape":"SPHERE", "glb": "levels/misty/quicksandlurker-lod0.glb"},
    # Village1 group (always loaded — free)
    "ram":              {"label":"Ram",                  "cat":"Enemies",   "tpage_group":"Village1", "ag":"ram-ag.go",               "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.4,0.2,1.0), "shape":"SPHERE", "glb": "levels/snow/ram-lod0.glb"},
    # Rolling group (tpages: rol.gd — rolling-lightning-mole.o, lightning-mole-ag.go)
    "lightning-mole":   {"label":"Lightning Mole",       "cat":"Enemies",   "tpage_group":"Rolling",  "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.7,0.9,1.0), "shape":"SPHERE", "glb": None},
    # Snow group (ice-cube uses snow-vis-pris: icecube-eye/ice-01/ice-corner/nails/pendant)
    "ice-cube":         {"label":"Ice Cube",             "cat":"Enemies",   "tpage_group":"Snow",     "ag":None,                      "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.9,1.0,1.0), "shape":"CUBE", "glb": None},
    # Village2 group (fireboulder-ag.go is in vi2.gd — globally loaded, always free)
    "fireboulder":      {"label":"Fire Boulder",         "cat":"Enemies",   "tpage_group":"Village2", "ag":"fireboulder-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(1.0,0.4,0.0,1.0), "shape":"SPHERE", "glb": "levels/village2/fireboulder-lod0.glb"},

    # ---- PROPS — is_prop=True, idle animation only, no AI/combat ----
    # evilplant: process-drawable with ONE state (idle loop). No attack, no chase.
    # Listed under Props not Enemies to avoid confusion.
    "evilplant":        {"label":"Evil Plant (Prop)",    "cat":"Props",     "ag":"evilplant-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.5,0.1,1.0), "shape":"SPHERE", "glb": "levels/village1/evilplant-lod0.glb"},
    "dark-plant":       {"label":"Dark Plant (Prop)",    "cat":"Props",     "ag":"dark-plant-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.3,0.1,0.5,1.0), "shape":"SPHERE", "glb": "levels/rolling/dark-plant-lod0.glb"},

    # ---- BOSSES ----
    "ogreboss":         {"label":"Klaww (Ogre Boss)",    "cat":"Bosses",    "ag":"ogreboss-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(1.0,0.3,0.0,1.0), "shape":"SPHERE", "glb": "levels/ogre/ogreboss-lod0.glb"},
    "plant-boss":       {"label":"Plant Boss",           "cat":"Bosses",    "ag":"plant-boss-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.1,0.7,0.1,1.0), "shape":"SPHERE", "glb": "levels/finalboss/plant-boss-main-lod0.glb"},
    "robotboss":        {"label":"Metal Head Boss",      "cat":"Bosses",    "ag":"robotboss-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.6,0.8,1.0), "shape":"SPHERE", "glb": "levels/citadel/robotboss-basic-lod0.glb"},
    # ---- NPCs ----
    "yakow":            {"label":"Yakow",                "cat":"NPCs",      "ag":"yakow-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.8,0.5,1.0), "shape":"SPHERE", "glb": "levels/village1/yakow-lod0.glb"},
    "flutflut":         {"label":"Flut Flut",            "cat":"NPCs",      "ag":"flutflut-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.7,1.0,1.0), "shape":"SPHERE", "glb": "levels/beach/flutflut-lod0.glb"},
    "mayor":            {"label":"Mayor",                "cat":"NPCs",      "ag":"mayor-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.7,0.2,1.0), "shape":"SPHERE", "glb": "levels/beach/mayor-lod0.glb"},
    "farmer":           {"label":"Farmer",               "cat":"NPCs",      "ag":"farmer-ag.go",            "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.5,0.2,1.0), "shape":"SPHERE", "glb": "levels/village1/farmer-lod0.glb"},
    "fisher":           {"label":"Fisher",               "cat":"NPCs",      "ag":"fisher-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.5,0.7,1.0), "shape":"SPHERE", "glb": "levels/jungle/fisher-lod0.glb"},
    "explorer":         {"label":"Explorer",             "cat":"NPCs",      "ag":"explorer-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.5,0.3,1.0), "shape":"SPHERE", "glb": "levels/village1/explorer-lod0.glb"},
    "geologist":        {"label":"Geologist",            "cat":"NPCs",      "ag":"geologist-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.4,0.3,1.0), "shape":"SPHERE", "glb": "levels/village2/geologist-lod0.glb"},
    "warrior":          {"label":"Warrior",              "cat":"NPCs",      "ag":"warrior-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.3,0.3,1.0), "shape":"SPHERE", "glb": "levels/village2/warrior-lod0.glb"},
    "gambler":          {"label":"Gambler",              "cat":"NPCs",      "ag":"gambler-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.7,0.4,1.0), "shape":"SPHERE", "glb": "levels/village2/gambler-lod0.glb"},
    "sculptor":         {"label":"Sculptor",             "cat":"NPCs",      "ag":"sculptor-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.6,0.5,1.0), "shape":"SPHERE", "glb": "levels/beach/sculptor-lod0.glb"},
    "billy":            {"label":"Billy",                "cat":"NPCs",      "ag":"billy-ag.go",             "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.7,0.9,1.0), "shape":"SPHERE", "glb": "levels/swamp/billy-lod0.glb"},
    "pelican":          {"label":"Pelican",              "cat":"NPCs",      "ag":"pelican-ag.go",           "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.9,0.7,1.0), "shape":"SPHERE", "glb": "levels/beach/pelican-lod0.glb"},
    "seagull":          {"label":"Seagull",              "cat":"NPCs",      "ag":"seagull-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.9,0.9,1.0), "shape":"SPHERE", "glb": "levels/beach/seagull-lod0.glb"},
    "robber":           {"label":"Robber (Lurker)",      "cat":"NPCs",      "ag":"robber-ag.go",            "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.3,0.7,1.0), "shape":"SPHERE", "glb": "levels/rolling/robber-lod0.glb"},
    # ---- PICKUPS ----
    "fuel-cell":        {"label":"Power Cell",           "cat":"Pickups",   "ag":"fuel-cell-ag.go",         "nav_safe":True,  "color":(1.0,0.9,0.0,1.0), "shape":"ARROWS", "glb": "levels/common/fuel-cell-lod0.glb"},
    "money":            {"label":"Orb (Precursor)",      "cat":"Pickups",   "ag":"money-ag.go",             "nav_safe":True,  "color":(0.8,0.8,0.0,1.0), "shape":"PLAIN_AXES", "glb": "levels/common/money-lod0.glb"},
    "buzzer":           {"label":"Scout Fly",            "cat":"Pickups",   "ag":"buzzer-ag.go",            "nav_safe":True,  "color":(0.9,0.9,0.2,1.0), "shape":"PLAIN_AXES", "glb": "levels/common/buzzer-lod0.glb"},
    "crate":            {"label":"Crate",                "cat":"Pickups",   "ag":"crate-ag.go",             "nav_safe":True,  "color":(0.8,0.5,0.1,1.0), "shape":"CUBE", "glb": "levels/common/crate-wood-lod0.glb"},
    "orb-cache-top":    {"label":"Orb Cache",            "cat":"Pickups",   "ag":"orb-cache-top-ag.go",     "nav_safe":True,  "color":(0.9,0.7,0.1,1.0), "shape":"CUBE", "glb": "levels/beach/orb-cache-top-lod0.glb"},
    "powercellalt":     {"label":"Power Cell (alt)",     "cat":"Pickups",   "ag":"powercellalt-ag.go",      "nav_safe":True,  "color":(1.0,0.85,0.0,1.0),"shape":"ARROWS", "glb": "levels/finalboss/powercellalt-lod0.glb"},
    "eco-yellow":       {"label":"Yellow Eco Vent",      "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(1.0,0.9,0.0,1.0), "shape":"PLAIN_AXES"},
    "eco-red":          {"label":"Red Eco Vent",         "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(1.0,0.2,0.1,1.0), "shape":"PLAIN_AXES"},
    "eco-blue":         {"label":"Blue Eco Vent",        "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(0.2,0.4,1.0,1.0), "shape":"PLAIN_AXES"},
    "eco-green":        {"label":"Green Eco Vent",       "cat":"Pickups",   "ag":None,                      "nav_safe":True,  "color":(0.1,0.9,0.2,1.0), "shape":"PLAIN_AXES"},
    # ---- PLATFORMS ----
    # needs_sync       : True = reads 'sync' res lump (period/phase/easing) for path movement
    # needs_path       : True = reads 'path' res lump (waypoints drive movement directly, e.g. plat-button)
    # needs_notice_dist: True = reads 'notice-dist' lump (plat-eco activation range)
    "plat":             {"label":"Floating Platform",    "cat":"Platforms", "ag":"plat-ag.go",              "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":False, "color":(0.5,0.5,0.8,1.0), "shape":"CUBE", "glb": "levels/maincave/plat-lod0.glb"},
    "plat-eco":         {"label":"Eco Platform",         "cat":"Platforms", "ag":"plat-eco-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":True,  "color":(0.3,0.7,0.9,1.0), "shape":"CUBE", "glb": "levels/jungle/plat-eco-lod0.glb"},
    "plat-button":      {"label":"Button Platform",      "cat":"Platforms", "ag":"plat-button-ag.go",       "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.6,0.7,1.0), "shape":"CUBE", "glb": "levels/jungle/plat-button-geo.glb"},
    "plat-flip":        {"label":"Flip Platform",        "cat":"Platforms", "ag":"plat-flip-ag.go",         "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.5,0.7,1.0), "shape":"CUBE", "glb": "levels/jungleb/plat-flip-geo.glb"},
    "wall-plat":        {"label":"Wall Platform",        "cat":"Platforms", "ag":"wall-plat-ag.go",         "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.4,0.5,0.7,1.0), "shape":"CUBE", "glb": "levels/sunken/wall-plat-lod0.glb"},
    "balance-plat":     {"label":"Balance Platform",     "cat":"Platforms", "ag":"balance-plat-ag.go",      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.6,0.8,1.0), "shape":"CUBE", "glb": "levels/swamp/balance-plat-lod0.glb"},
    "teetertotter":     {"label":"Teeter Totter",        "cat":"Platforms", "ag":"teetertotter-ag.go",      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.5,0.4,1.0), "shape":"CUBE", "glb": "levels/misty/teetertotter-lod0.glb"},
    "side-to-side-plat":{"label":"Side-to-Side Plat",   "cat":"Platforms", "ag":"side-to-side-plat-ag.go", "nav_safe":True,  "needs_path":False, "needs_sync":True,  "needs_notice_dist":False, "color":(0.4,0.5,0.8,1.0), "shape":"CUBE", "glb": "levels/sunken/side-to-side-plat-lod0.glb"},
    "wedge-plat":       {"label":"Wedge Platform",       "cat":"Platforms", "ag":"wedge-plat-ag.go",        "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.5,0.7,1.0), "shape":"CUBE", "glb": "levels/sunken/wedge-plat-lod0.glb"},
    "tar-plat":         {"label":"Tar Platform",         "cat":"Platforms", "ag":"tar-plat-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.2,0.2,0.2,1.0), "shape":"CUBE", "glb": "levels/swamp/tar-plat-lod0.glb"},
    "revcycle":         {"label":"Rotating Platform",    "cat":"Platforms", "ag":"revcycle-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.4,0.6,1.0), "shape":"CUBE", "glb": "levels/village1/revcycle-geo.glb"},
    "launcher":         {"label":"Launcher",             "cat":"Platforms", "ag":"floating-launcher-ag.go", "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.9,0.6,0.1,1.0), "shape":"CONE", "glb": "levels/sunkenb/floating-launcher-lod0.glb"},
    "warpgate":         {"label":"Warp Gate",            "cat":"Platforms", "ag":"warpgate-ag.go",          "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.3,0.8,0.9,1.0), "shape":"CIRCLE", "glb": "levels/citadel/warpgate-lod0.glb"},
    # ---- OBJECTS / INTERACTABLES ----
    "cavecrystal":      {"label":"Cave Crystal",         "cat":"Objects",   "ag":"cavecrystal-ag.go",       "nav_safe":True,  "color":(0.7,0.4,0.9,1.0), "shape":"SPHERE", "glb": "levels/darkcave/cavecrystal-lod0.glb"},
    "cavegem":          {"label":"Cave Gem",             "cat":"Objects",   "ag":"cavegem-ag.go",           "nav_safe":True,  "color":(0.8,0.2,0.8,1.0), "shape":"SPHERE"},
    "tntbarrel":        {"label":"TNT Barrel",           "cat":"Objects",   "ag":"tntbarrel-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(1.0,0.4,0.0,1.0), "shape":"CUBE", "glb": "levels/ogre/tntbarrel-lod0.glb"},
    "shortcut-boulder": {"label":"Shortcut Boulder",     "cat":"Objects",   "ag":"shortcut-boulder-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.6,0.5,0.4,1.0), "shape":"SPHERE"},
    "spike":            {"label":"Spike",                "cat":"Objects",   "ag":"spike-ag.go",             "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.8,0.2,0.2,1.0), "shape":"CONE", "glb": "levels/firecanyon/spike-lod0.glb"},
    "steam-cap":        {"label":"Steam Cap",            "cat":"Objects",   "ag":"steam-cap-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.8,0.8,0.8,1.0), "shape":"CUBE"},
    "windmill-one":     {"label":"Windmill",             "cat":"Objects",   "ag":"windmill-one-ag.go",      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.7,0.7,0.5,1.0), "shape":"CUBE", "glb": "levels/beach/windmill-one-lod0.glb"},
    "ecoclaw":          {"label":"Eco Claw",             "cat":"Objects",   "ag":"ecoclaw-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.8,0.3,1.0), "shape":"CUBE", "glb": "levels/finalboss/ecoclaw-lod0.glb"},
    "ecovalve":         {"label":"Eco Valve",            "cat":"Objects",   "ag":"ecovalve-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.3,0.7,0.3,1.0), "shape":"CUBE", "glb": "levels/beach/ecovalve-geo.glb"},
    "swamp-rock":       {"label":"Swamp Rock",           "cat":"Objects",   "ag":"swamp-rock-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.4,0.4,0.3,1.0), "shape":"SPHERE"},
    "gondola":          {"label":"Gondola",              "cat":"Objects",   "ag":"gondola-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.3,1.0), "shape":"CUBE", "glb": "levels/village2/gondola-lod0.glb"},
    "swamp-blimp":      {"label":"Swamp Blimp",          "cat":"Objects",   "ag":"swamp-blimp-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.6,0.5,0.3,1.0), "shape":"SPHERE"},
    "swamp-rope":       {"label":"Swamp Rope",           "cat":"Objects",   "ag":"swamp-rope-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.2,1.0), "shape":"CUBE"},
    "swamp-spike":      {"label":"Swamp Spike",          "cat":"Objects",   "ag":"swamp-spike-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.7,0.3,0.2,1.0), "shape":"CONE"},
    "whirlpool":        {"label":"Whirlpool",            "cat":"Objects",   "ag":"whirlpool-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.4,0.8,1.0), "shape":"CIRCLE", "glb": "levels/sunken/whirlpool-lod0.glb"},
    "warp-gate":        {"label":"Warp Gate Switch",     "cat":"Objects",   "ag":"warp-gate-switch-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.2,0.7,0.8,1.0), "shape":"CIRCLE"},
    # ---- ENEMIES (NEW) — process-drawable, no navmesh needed ----
    # Misty group
    "balloonlurker":    {"label":"Balloon Lurker",       "cat":"Enemies",   "tpage_group":"Misty",    "ag":"balloonlurker-ag.go",     "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.5,0.8,1.0), "shape":"SPHERE", "glb": "levels/misty/balloonlurker-lod0.glb"},
    # Jungle group
    "darkvine":         {"label":"Dark Vine",            "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"darkvine-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.2,0.5,0.1,1.0), "shape":"SPHERE"},
    "junglefish":       {"label":"Jungle Fish",          "cat":"Enemies",   "tpage_group":"Jungle",   "ag":"junglefish-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.6,0.5,1.0), "shape":"SPHERE"},
    # Rolling group
    "peeper":           {"label":"Peeper",               "cat":"Enemies",   "tpage_group":"Rolling",  "ag":"lightning-mole-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.8,0.8,0.3,1.0), "shape":"SPHERE"},
    # Robocave group
    "cave-trap":        {"label":"Cave Trap",            "cat":"Enemies",   "tpage_group":"Robocave", "ag":None,                      "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.2,0.1,1.0), "shape":"SPHERE"},
    "spider-egg":       {"label":"Spider Egg",           "cat":"Enemies",   "tpage_group":"Robocave", "ag":"spider-egg-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.5,0.3,1.0), "shape":"SPHERE"},
    "spider-vent":      {"label":"Spider Vent",          "cat":"Enemies",   "tpage_group":"Robocave", "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.3,0.1,1.0), "shape":"SPHERE"},
    # Swamp group
    "swamp-rat-nest":   {"label":"Swamp Rat Nest",       "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"swamp-rat-nest-ag.go",    "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.3,0.1,1.0), "shape":"SPHERE"},
    # Sunken group
    "sunkenfisha":      {"label":"Sunken Fish School",   "cat":"Enemies",   "tpage_group":"Sunken",   "ag":None,                      "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.2,0.5,0.7,1.0), "shape":"SPHERE"},
    "sharkey":          {"label":"Lurker Shark",         "cat":"Enemies",   "tpage_group":"Swamp",    "ag":"sharkey-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.3,0.1,1.0), "shape":"SPHERE"},
    # Village1 group
    "villa-starfish":   {"label":"Villa Starfish",       "cat":"Enemies",   "tpage_group":"Village1", "ag":None,                      "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(1.0,0.6,0.5,1.0), "shape":"SPHERE"},

    # ---- PICKUPS (NEW) ----
    "eco-pill":         {"label":"Eco Pill (Health)",    "cat":"Pickups",   "ag":"eco-pill-ag.go",          "nav_safe":True,  "color":(0.3,0.9,0.3,1.0), "shape":"PLAIN_AXES"},
    "ecovent":          {"label":"Blue Eco Vent",        "cat":"Pickups",   "ag":"vent-ag.go",              "nav_safe":True,  "color":(0.2,0.4,1.0,1.0), "shape":"PLAIN_AXES"},
    "ventblue":         {"label":"Blue Eco Vent (alt)",  "cat":"Pickups",   "ag":"vent-ag.go",              "nav_safe":True,  "color":(0.2,0.4,1.0,1.0), "shape":"PLAIN_AXES"},
    "ventred":          {"label":"Red Eco Vent",         "cat":"Pickups",   "ag":"vent-ag.go",              "nav_safe":True,  "color":(1.0,0.2,0.1,1.0), "shape":"PLAIN_AXES"},
    "ventyellow":       {"label":"Yellow Eco Vent",      "cat":"Pickups",   "ag":"vent-ag.go",              "nav_safe":True,  "color":(1.0,0.9,0.0,1.0), "shape":"PLAIN_AXES"},
    "ecoventrock":      {"label":"Eco Vent (Rock)",      "cat":"Pickups",   "tpage_group":"Beach",    "ag":"ecoventrock-ag.go",       "nav_safe":True,  "color":(0.3,0.7,0.3,1.0), "shape":"PLAIN_AXES"},

    # ---- PLATFORMS (NEW) ----
    "orbit-plat":       {"label":"Orbit Platform",       "cat":"Platforms", "tpage_group":"Sunken",   "ag":"orbit-plat-ag.go",        "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.4,0.6,0.9,1.0), "shape":"CUBE", "glb": "levels/sunken/orbit-plat-lod0.glb"},
    "square-platform":  {"label":"Square Platform",      "cat":"Platforms", "tpage_group":"Sunken",   "ag":"square-platform-ag.go",   "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.4,0.6,0.8,1.0), "shape":"CUBE", "glb": "levels/sunken/square-platform-lod0.glb"},
    "ropebridge":       {"label":"Rope Bridge",          "cat":"Platforms", "tpage_group":"Jungle",   "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.4,0.2,1.0), "shape":"CUBE"},
    "lavaballoon":      {"label":"Lava Balloon",         "cat":"Platforms", "tpage_group":"Lavatube", "ag":"lavaballoon-ag.go",       "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(1.0,0.5,0.1,1.0), "shape":"SPHERE", "glb": "levels/lavatube/lavaballoon-lod0.glb"},
    "darkecobarrel":    {"label":"Dark Eco Barrel",      "cat":"Platforms", "tpage_group":"Lavatube", "ag":"darkecobarrel-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(0.3,0.0,0.5,1.0), "shape":"CUBE", "glb": "levels/lavatube/darkecobarrel-lod0.glb"},
    "caveelevator":     {"label":"Cave Elevator",        "cat":"Platforms", "tpage_group":"Maincave", "ag":"caveelevator-ag.go",      "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.3,1.0), "shape":"CUBE", "glb": "levels/darkcave/caveelevator-lod0.glb"},
    "caveflamepots":    {"label":"Cave Flame Pots",      "cat":"Platforms", "tpage_group":"Maincave", "ag":"caveflamepots-ag.go",     "nav_safe":True,  "needs_path":True,  "needs_sync":False, "needs_notice_dist":False, "color":(1.0,0.3,0.0,1.0), "shape":"CUBE"},
    "cavetrapdoor":     {"label":"Cave Trap Door",       "cat":"Platforms", "tpage_group":"Maincave", "ag":"cavetrapdoor-ag.go",      "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.4,0.3,0.2,1.0), "shape":"CUBE"},
    "cavespatula":      {"label":"Cave Spatula Plat",    "cat":"Platforms", "tpage_group":"Maincave", "ag":"cavespatula-ag.go",       "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.2,1.0), "shape":"CUBE"},
    "cavespatulatwo":   {"label":"Cave Spatula Plat 2",  "cat":"Platforms", "tpage_group":"Maincave", "ag":"cavespatulatwo-ag.go",    "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.3,1.0), "shape":"CUBE"},
    "ogre-bridge":      {"label":"Ogre Drawbridge",      "cat":"Platforms", "tpage_group":"Ogre",     "ag":"ogre-bridge-ag.go",       "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.2,1.0), "shape":"CUBE", "glb": "levels/ogre/ogre-bridge-lod0.glb"},
    "ogre-bridgeend":   {"label":"Ogre Bridge End",      "cat":"Platforms", "tpage_group":"Ogre",     "ag":"ogre-bridgeend-ag.go",    "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.3,1.0), "shape":"CUBE"},
    "pontoon":          {"label":"Pontoon (Village2)",   "cat":"Platforms", "tpage_group":"Village2", "ag":"pontoon-ag.go",           "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.2,1.0), "shape":"CUBE"},
    "tra-pontoon":      {"label":"Pontoon (Training)",   "cat":"Platforms", "tpage_group":"Training", "ag":"tra-pontoon-ag.go",       "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.5,0.4,0.3,1.0), "shape":"CUBE"},
    "mis-bone-bridge":  {"label":"Bone Bridge",          "cat":"Platforms", "tpage_group":"Misty",    "ag":"mis-bone-bridge-ag.go",   "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.7,0.6,0.4,1.0), "shape":"CUBE", "glb": "levels/misty/mis-bone-bridge-lod0.glb"},
    "breakaway-left":   {"label":"Breakaway Plat (L)",   "cat":"Platforms", "tpage_group":"Misty",    "ag":"breakaway-left-ag.go",    "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.5,0.3,1.0), "shape":"CUBE"},
    "breakaway-mid":    {"label":"Breakaway Plat (M)",   "cat":"Platforms", "tpage_group":"Misty",    "ag":"breakaway-mid-ag.go",     "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.5,0.3,1.0), "shape":"CUBE"},
    "breakaway-right":  {"label":"Breakaway Plat (R)",   "cat":"Platforms", "tpage_group":"Misty",    "ag":"breakaway-right-ag.go",   "nav_safe":True,  "needs_path":False, "needs_sync":False, "needs_notice_dist":False, "color":(0.6,0.5,0.3,1.0), "shape":"CUBE"},

    # ---- OBJECTS / INTERACTABLES (NEW) ----
    "water-vol":        {"label":"Water Volume (legacy)", "cat":"Hidden",    "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.2,0.4,0.9,0.6), "shape":"CUBE"},
    "swingpole":        {"label":"Swing Pole",           "cat":"Objects",   "ag":None,                      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.8,0.6,0.2,1.0), "shape":"PLAIN_AXES"},
    "springbox":        {"label":"Bounce Pad (Bouncer)", "cat":"Objects",   "tpage_group":"Jungle",   "ag":"bouncer-ag.go",           "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.7,0.1,1.0), "shape":"CUBE"},
    "oracle":           {"label":"Oracle",               "cat":"NPCs",      "tpage_group":"Village1", "ag":"oracle-ag.go",            "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.9,0.8,0.5,1.0), "shape":"SPHERE", "glb": "levels/village1/oracle-lod0.glb"},
    "minershort":       {"label":"Miner (Short)",        "cat":"NPCs",      "tpage_group":"Village3", "ag":"minershort-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.5,0.3,1.0), "shape":"SPHERE", "glb": "levels/village3/minershort-lod0.glb"},
    "minertall":        {"label":"Miner (Tall)",         "cat":"NPCs",      "tpage_group":"Village3", "ag":"minertall-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.45,0.3,1.0),"shape":"SPHERE", "glb": "levels/village3/minertall-lod0.glb"},
    # eco-door is an ABSTRACT base type — no art group of its own.
    # Use a concrete subclass: jng-iris-door (jungle), tra-iris-door (training), sidedoor, rounddoor.
    # eco-door entity def kept for export/lump logic but ag is set to a subclass default.
    "eco-door":         {"label":"Eco Door (iris)",      "cat":"Objects",   "ag":"jng-iris-door-ag.go",     "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.6,0.8,1.0), "shape":"CUBE"},
    "jng-iris-door":    {"label":"Iris Door (Jungle)",   "cat":"Objects",   "ag":"jng-iris-door-ag.go",     "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.3,0.7,0.5,1.0), "shape":"CUBE"},
    "sidedoor":         {"label":"Side Door (Jungle)",   "cat":"Objects",   "ag":"sidedoor-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.6,0.4,1.0), "shape":"CUBE"},
    "rounddoor":        {"label":"Round Door (Misty)",   "cat":"Objects",   "ag":"rounddoor-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.4,0.3,1.0), "shape":"CUBE"},
    "launcherdoor":     {"label":"Launcher Door",        "cat":"Objects",   "ag":"launcherdoor-ag.go",      "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.5,0.7,1.0), "shape":"CUBE"},
    "sun-iris-door":    {"label":"Iris Door (Sunken)",   "cat":"Objects",   "ag":"sun-iris-door-ag.go",     "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.5,0.2,1.0), "shape":"CUBE"},
    "basebutton":       {"label":"Wall Button",          "cat":"Objects",   "ag":"generic-button-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.7,0.3,0.3,1.0), "shape":"CUBE"},
    "shover":           {"label":"Shover Platform",      "cat":"Objects",   "tpage_group":"Sunken",   "ag":"shover-ag.go",            "nav_safe":True,  "needs_path":True,  "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.5,0.7,1.0), "shape":"CUBE"},
    "swampgate":        {"label":"Swamp Spike Gate",     "cat":"Objects",   "tpage_group":"Swamp",    "ag":"swamp-spike-gate-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.4,0.5,0.2,1.0), "shape":"CUBE"},
    "ceilingflag":      {"label":"Ceiling Flag",         "cat":"Objects",   "tpage_group":"Village2", "ag":"ceilingflag-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.8,0.6,0.2,1.0), "shape":"SPHERE"},
    "windturbine":      {"label":"Wind Turbine",         "cat":"Objects",   "tpage_group":"Misty",    "ag":"windturbine-ag.go",       "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.6,0.6,0.7,1.0), "shape":"SPHERE"},
    "boatpaddle":       {"label":"Boat Paddle",          "cat":"Objects",   "tpage_group":"Misty",    "ag":"boatpaddle-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.2,1.0), "shape":"SPHERE"},
    "accordian":        {"label":"Accordian Obstacle",   "cat":"Objects",   "tpage_group":"Jungle",   "ag":"accordian-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.5,0.3,1.0), "shape":"CUBE"},
    "lavafall":         {"label":"Lava Fall",            "cat":"Objects",   "tpage_group":"Lavatube", "ag":"lavafall-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(1.0,0.3,0.0,1.0), "shape":"CUBE"},
    "lavafallsewera":   {"label":"Lava Fall Sewer A",    "cat":"Objects",   "tpage_group":"Lavatube", "ag":"lavafallsewera-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(1.0,0.3,0.0,1.0), "shape":"CUBE"},
    "lavafallsewerb":   {"label":"Lava Fall Sewer B",    "cat":"Objects",   "tpage_group":"Lavatube", "ag":"lavafallsewerb-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(1.0,0.35,0.0,1.0),"shape":"CUBE"},
    "lavabase":         {"label":"Lava Base",            "cat":"Objects",   "tpage_group":"Lavatube", "ag":"lavabase-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.9,0.2,0.0,1.0), "shape":"CUBE"},
    "lavayellowtarp":   {"label":"Lava Yellow Tarp",     "cat":"Objects",   "tpage_group":"Lavatube", "ag":"lavayellowtarp-ag.go",    "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.9,0.8,0.1,1.0), "shape":"CUBE"},
    "chainmine":        {"label":"Chain Mine",           "cat":"Objects",   "tpage_group":"Lavatube", "ag":"chainmine-ag.go",         "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.6,0.1,0.1,1.0), "shape":"SPHERE"},
    "balloon":          {"label":"Balloon Obstacle",     "cat":"Objects",   "tpage_group":"Firecanyon","ag":"balloon-ag.go",          "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.9,0.4,0.1,1.0), "shape":"SPHERE"},
    "crate-darkeco-cluster": {"label":"Dark Eco Crate Cluster","cat":"Objects","tpage_group":"Firecanyon","ag":"crate-darkeco-cluster-ag.go","nav_safe":True,"needs_path":False,"needs_pathb":False,"is_prop":False,"ai_type":"process-drawable","color":(0.3,0.0,0.5,1.0),"shape":"CUBE"},
    "swamp-tetherrock": {"label":"Swamp Tether Rock",    "cat":"Objects",   "tpage_group":"Village2", "ag":"swamp-tetherrock-ag.go",  "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"process-drawable", "color":(0.5,0.4,0.3,1.0), "shape":"SPHERE"},
    "fishermans-boat":  {"label":"Fisherman's Boat",     "cat":"Objects",   "tpage_group":"Village1", "ag":"fishermans-boat-ag.go",   "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":True,  "ai_type":"prop",             "color":(0.5,0.4,0.2,1.0), "shape":"CUBE"},

    # ---- DEBUG ----
    "test-actor":       {"label":"Test Actor",           "cat":"Debug",     "ag":"test-actor-ag.go",        "nav_safe":True,  "needs_path":False, "needs_pathb":False, "is_prop":False, "ai_type":"prop",             "color":(0.8,0.8,0.8,1.0), "shape":"PLAIN_AXES"},
}

CRATE_ITEMS = [
    ("steel",   "Steel",    "", 0, 0),
    ("wood",    "Wood",     "", 0, 1),
    ("iron",    "Iron",     "", 0, 2),
    ("darkeco", "Dark Eco", "", 0, 3),
    ("barrel",  "Barrel",   "", 0, 4),
    ("bucket",  "Bucket",   "", 0, 5),
]

# Pickup types valid inside a crate. Maps (ui_id, label, pickup-type string, icon).
# amount=1 is locked for scout fly; fuel-cell omitted (needs task lump — not yet supported).
CRATE_PICKUP_ITEMS = [
    ("none",        "Empty",        "(pickup-type none)",       "X",             False),
    ("money",       "Orbs",         "(pickup-type money)",      "SOLO",          True),
    ("eco-yellow",  "Yellow Eco",   "(pickup-type eco-yellow)", "COLORSET_03_VEC", False),
    ("eco-red",     "Red Eco",      "(pickup-type eco-red)",    "COLORSET_01_VEC", False),
    ("eco-blue",    "Blue Eco",     "(pickup-type eco-blue)",   "COLORSET_04_VEC", False),
    ("eco-green",   "Green Eco",    "(pickup-type eco-green)",  "COLORSET_08_VEC", False),
    ("buzzer",      "Scout Fly",    "(pickup-type buzzer)",     "GP_SELECT",     False),
]
# (ui_id, label, engine pickup-type string, blender icon, supports_multi_amount)


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


# --- _build_entity_enum through needed_tpages ---

def _build_entity_enum():
    # Tpage group display order — enemies are grouped so users know which share heap budget.
    # Mixing more than 2 groups in one scene risks OOM crash on level load.
    TPAGE_GROUP_ORDER = ["Beach", "Jungle", "Swamp", "Snow", "Sunken", "Ogre",
                         "Misty", "Maincave", "Robocave", "Rolling", "Lavatube", "Firecanyon",
                         "Village1", "Village2", "Village3", "Training", "Final"]
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
                g = info.get("tpage_group", "Other")
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

# ---------------------------------------------------------------------------
# Per-category enums — used by Spawn sub-panels so each dropdown only shows
# types relevant to that sub-panel.
# ---------------------------------------------------------------------------
def _build_cat_enum(cats):
    """Return sorted enum items for the given category set."""
    items = []
    for i, (etype, info) in enumerate(
        sorted(
            [(e, inf) for e, inf in ENTITY_DEFS.items() if inf.get("cat") in cats],
            key=lambda x: (x[1].get("tpage_group", ""), x[1]["label"])
        )
    ):
        warn = ""
        if not info.get("nav_safe", True): warn += " [nav]"
        if info.get("needs_path"):         warn += " [path]"
        group = info.get("tpage_group", "")
        prefix = f"[{group}] " if group else f"[{info.get('cat','')}] "
        tip = ENTITY_WIKI.get(etype, {}).get("desc", "") or etype
        items.append((etype, f"{prefix}{info['label']}{warn}", tip, i))
    return items

ENEMY_ENUM_ITEMS  = _build_cat_enum({"Enemies", "Bosses"})
PROP_ENUM_ITEMS   = _build_cat_enum({"Props", "Objects", "Debug"})
NPC_ENUM_ITEMS    = _build_cat_enum({"NPCs"})
PICKUP_ENUM_ITEMS = _build_cat_enum({"Pickups"})

# ---------------------------------------------------------------------------
# Tpage filter — groups selectable in the Limit Search panel.
# Global groups (Village1/2/3, Training) are always free — excluded from the
# filter list since the user never needs to "allow" them.
# ---------------------------------------------------------------------------
GLOBAL_TPAGE_GROUPS = {"Village1", "Village2", "Village3", "Training"}

def _build_tpage_filter_items():
    # Collect groups that actually have heap cost (not global, not absent)
    seen = set()
    for info in ENTITY_DEFS.values():
        g = info.get("tpage_group")
        if g and g not in GLOBAL_TPAGE_GROUPS:
            seen.add(g)
    order = ["Beach", "Jungle", "Swamp", "Snow", "Sunken", "Ogre",
             "Misty", "Maincave", "Robocave", "Rolling", "Lavatube",
             "Firecanyon", "Final"]
    ordered = [g for g in order if g in seen]
    ordered += sorted(seen - set(ordered))  # any future groups appended
    items = [("NONE", "— None —", "No filter")]
    for i, g in enumerate(ordered, 1):
        items.append((g, g, f"Show only {g} tpage group", i))
    return items

TPAGE_FILTER_ITEMS = _build_tpage_filter_items()


def _tpage_filter_passes(etype, g1, g2, enabled):
    """Core filter logic — importable for use in panels without circular deps."""
    if not enabled:
        return True
    info  = ENTITY_DEFS.get(etype, {})
    grp   = info.get("tpage_group")
    if grp is None:
        return True
    if grp in GLOBAL_TPAGE_GROUPS:
        return True
    allowed = {g for g in (g1, g2) if g != "NONE"}
    if not allowed:
        return True
    return grp in allowed


def _make_filtered_enum(base_items, cats):
    """Return a Blender dynamic enum callback that filters base_items by tpage."""
    def _callback(self, context):
        if context is None:
            return base_items
        try:
            props   = context.scene.og_props
            enabled = props.tpage_limit_enabled
            g1      = props.tpage_filter_1
            g2      = props.tpage_filter_2
        except Exception:
            return base_items
        if not enabled:
            return base_items
        allowed = {g for g in (g1, g2) if g != "NONE"}
        if not allowed:
            return base_items
        result = []
        for item in base_items:
            etype = item[0]
            info  = ENTITY_DEFS.get(etype, {})
            grp   = info.get("tpage_group")
            if grp is None or grp in GLOBAL_TPAGE_GROUPS:
                result.append(item)
            elif grp in allowed:
                result.append(item)
        # Blender requires at least one item
        return result if result else [("__none__", "— No matches —", "", 0)]
    return _callback


# Dynamic filtered enum callbacks — assigned to EnumProperty items= in properties.py
_enemy_enum_cb    = _make_filtered_enum(ENEMY_ENUM_ITEMS,   {"Enemies", "Bosses"})
_prop_enum_cb     = _make_filtered_enum(PROP_ENUM_ITEMS,    {"Props", "Objects", "Debug"})
_npc_enum_cb      = _make_filtered_enum(NPC_ENUM_ITEMS,     {"NPCs"})
_pickup_enum_cb   = _make_filtered_enum(PICKUP_ENUM_ITEMS,  {"Pickups"})

# ---------------------------------------------------------------------------
# Quick Search results enum — dynamic, cached to avoid per-redraw rebuilds.
# Blender dynamic enums can crash if the list changes between the items=
# callback and the get/set calls, so we cache by (query, g1, g2, enabled)
# and only rebuild when that tuple changes.
# ---------------------------------------------------------------------------
_search_enum_cache: dict = {"key": None, "items": [("__empty__", "Type to search…", "", 0)]}

def _search_results_cb(self, context):
    if context is None:
        return _search_enum_cache["items"]
    try:
        props   = context.scene.og_props
        query   = props.entity_search.strip().lower()
        enabled = props.tpage_limit_enabled
        g1      = props.tpage_filter_1
        g2      = props.tpage_filter_2
    except Exception:
        return _search_enum_cache["items"]

    key = (query, enabled, g1, g2)
    if key == _search_enum_cache["key"]:
        return _search_enum_cache["items"]

    if not query:
        items = [("__empty__", "Type to search…", "", 0)]
    else:
        allowed = None
        if enabled:
            allowed = {g for g in (g1, g2) if g != "NONE"} or None

        matches = []
        for etype, info in ENTITY_DEFS.items():
            lbl = info["label"]
            if query not in lbl.lower() and query not in etype.lower():
                continue
            grp = info.get("tpage_group")
            if allowed is not None and grp is not None and grp not in GLOBAL_TPAGE_GROUPS:
                if grp not in allowed:
                    continue
            matches.append((etype, info))
        matches.sort(key=lambda x: x[1]["label"].lower())

        if matches:
            items = [
                (etype, f"{info['label']}  [{info.get('cat','')}]",
                 ENTITY_WIKI.get(etype, {}).get("desc", "") or etype, i)
                for i, (etype, info) in enumerate(matches)
            ]
        else:
            items = [("__empty__", "No results found", "", 0)]

    _search_enum_cache["key"]   = key
    _search_enum_cache["items"] = items
    return items
# _platform_enum_cb is defined after PLATFORM_ENUM_ITEMS below


# ---------------------------------------------------------------------------
# Vertex-export whitelist — entity types that need NO settings beyond position.
# Used by the "Export As" mesh panel: each vertex becomes one actor of this type.
# Excludes: crate (needs crate-type), fuel-cell (needs eco-info/task),
#           orb-cache-top (needs settings), powercellalt (task-gated).
# ---------------------------------------------------------------------------
_VERTEX_EXPORT_EXCLUDE = {"crate", "fuel-cell", "orb-cache-top", "powercellalt"}

VERTEX_EXPORT_TYPES = {
    etype: info
    for etype, info in ENTITY_DEFS.items()
    if (
        info.get("cat") in ("Pickups", "Props", "Objects")
        and etype not in _VERTEX_EXPORT_EXCLUDE
        and (info.get("is_prop", False) or info.get("cat") == "Pickups")
    )
}


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
_platform_enum_cb = _make_filtered_enum(PLATFORM_ENUM_ITEMS, {"Platforms"})

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
    # New enemies
    "balloonlurker":   {"o": "balloonlurker.o",   "o_only": True},
    "darkvine":        {"o": "darkvine.o",         "o_only": True},
    "junglefish":      {"o": "junglefish.o",       "o_only": True},
    "peeper":          {"o": "rolling-lightning-mole.o", "o_only": True},
    "cave-trap":       {"o": "cave-trap.o",        "o_only": True},
    "spider-egg":      {"o": "spider-egg.o",       "o_only": True},
    "spider-vent":     {"o": "cave-trap.o",        "o_only": True},  # spider-vent is in cave-trap.gc
    "swamp-rat-nest":  {"o": "swamp-rat-nest.o",   "o_only": True},
    "sunkenfisha":     {"o": "sunken-fish.o",      "o_only": True},
    "sharkey":         {"o": "sharkey.o",          "o_only": True},
    "villa-starfish":  {"o": "village-obs.o",      "o_only": True},  # villa-starfish is in village-obs.gc
    # New pickups
    "eco-pill":        {"o": "collectables.o",     "o_only": True},
    "ecovent":         {"o": "collectables.o",     "o_only": True},
    "ventblue":        {"o": "collectables.o",     "o_only": True},
    "ventred":         {"o": "collectables.o",     "o_only": True},
    "ventyellow":      {"o": "collectables.o",     "o_only": True},
    "ecoventrock":     {"o": "beach-obs.o",        "o_only": True},
    # New platforms
    "orbit-plat":      {"o": "orbit-plat.o",       "o_only": True},
    "square-platform": {"o": "square-platform.o",  "o_only": True},
    "ropebridge":      {"o": "ropebridge.o",       "o_only": True},
    "lavaballoon":     {"o": "lavatube-obs.o",     "o_only": True},
    "darkecobarrel":   {"o": "lavatube-obs.o",     "o_only": True},
    "caveelevator":    {"o": "maincave-obs.o",     "o_only": True},
    "caveflamepots":   {"o": "maincave-obs.o",     "o_only": True},
    "cavetrapdoor":    {"o": "maincave-obs.o",     "o_only": True},
    "cavespatula":     {"o": "maincave-obs.o",     "o_only": True},
    "cavespatulatwo":  {"o": "maincave-obs.o",     "o_only": True},
    "ogre-bridge":     {"o": "ogre-obs.o",         "o_only": True},
    "ogre-bridgeend":  {"o": "ogre-obs.o",         "o_only": True},
    "pontoon":         {"o": "village2-obs.o",     "o_only": True},
    "tra-pontoon":     {"o": "training-obs.o",     "o_only": True},
    "mis-bone-bridge": {"o": "misty-obs.o",        "o_only": True},
    "breakaway-left":  {"o": "misty-obs.o",        "o_only": True},
    "breakaway-mid":   {"o": "misty-obs.o",        "o_only": True},
    "breakaway-right": {"o": "misty-obs.o",        "o_only": True},
    # New objects / interactables
    "water-vol":       {"in_game_cgo": True},  # water.o is in GAME.CGO, always loaded
    "swingpole":       {"o": "generic-obs.o",      "o_only": True},
    "springbox":       {"o": "bouncer.o",          "o_only": True},
    # eco-door base class is in baseplat.o (GAME.CGO, always loaded).
    # Concrete subclasses need their level DGOs injected for the art .go file.
    "eco-door":        {"o": "baseplat.o",         "o_only": True},   # abstract base, art via subclass
    "jng-iris-door":   {"o": "jungleb-obs.o",      "o_only": True},   # art: jng-iris-door-ag.go in JUB.DGO / TRA.DGO
    "sidedoor":        {"o": "jungle-obs.o",        "o_only": True},   # art: sidedoor-ag.go in JUN.DGO
    "rounddoor":       {"o": "misty-warehouse.o",   "o_only": True},   # art: rounddoor-ag.go in MIS.DGO
    "launcherdoor":    {"o": "launcherdoor.o",      "o_only": True},   # art: launcherdoor-ag.go in JUN/MAI/SUN.DGO
    "sun-iris-door":   {"o": "sun-iris-door.o",     "o_only": True},   # art: sun-iris-door-ag.go in SUN.DGO
    "basebutton":      {"o": "basebutton.o",        "o_only": True},   # GAME.CGO always loaded; art: generic-button-ag.go in SUN.DGO
    "shover":          {"o": "shover.o",           "o_only": True},
    "swampgate":       {"o": "swamp-obs.o",        "o_only": True},
    "ceilingflag":     {"o": "village2-obs.o",     "o_only": True},
    "windturbine":     {"o": "misty-obs.o",        "o_only": True},
    "boatpaddle":      {"o": "misty-obs.o",        "o_only": True},
    "accordian":       {"o": "jungle-obs.o",       "o_only": True},
    "lavafall":        {"o": "lavatube-obs.o",     "o_only": True},
    "lavafallsewera":  {"o": "lavatube-obs.o",     "o_only": True},
    "lavafallsewerb":  {"o": "lavatube-obs.o",     "o_only": True},
    "lavabase":        {"o": "lavatube-obs.o",     "o_only": True},
    "lavayellowtarp":  {"o": "lavatube-obs.o",     "o_only": True},
    "chainmine":       {"o": "lavatube-obs.o",     "o_only": True},
    "balloon":         {"o": "firecanyon-obs.o",   "o_only": True},
    "crate-darkeco-cluster": {"o": "firecanyon-obs.o", "o_only": True},
    "swamp-tetherrock":{"o": "swamp-blimp.o",      "o_only": True},
    "fishermans-boat": {"o": "fishermans-boat.o",  "o_only": True},
    # New NPCs
    "oracle":          {"o": "oracle.o",           "o_only": True},
    "minershort":      {"o": "miners.o",           "o_only": True},
    "minertall":       {"o": "miners.o",           "o_only": True},

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

    # ── Quick fix: missing from previous batch ──────────────────────────────
    "baby-spider":     {"o": "baby-spider.o",      "o_only": True},
    "cavecrusher":     {"o": "maincave-obs.o",     "o_only": True},
    "dark-crystal":    {"o": "dark-crystal.o",     "o_only": True},
    "mother-spider":   {"o": "mother-spider.o",    "o_only": True},

    # ── Old eco-placeholder types — map to always-loaded collectables.o ─────
    # These are legacy entries superseded by ecovent/ventblue/red/yellow.
    # Keeping them alive so old scenes don't break.
    "eco-blue":        {"in_game_cgo": True},  # collectables.o always loaded
    "eco-red":         {"in_game_cgo": True},
    "eco-yellow":      {"in_game_cgo": True},
    "eco-green":       {"in_game_cgo": True},

    # ── warp-gate / warpgate — in game.gd / villagep-obs.gd ─────────────────
    "warp-gate":       {"in_game_cgo": True},  # basebutton.o in game.gd
    "warpgate":        {"o": "villagep-obs.o",     "o_only": True},

    # ── Enemies needing both .o + tpages ────────────────────────────────────
    "fireboulder":     {"o": "village2-obs.o",     "o_only": True},
    "green-eco-lurker":{"o": "green-eco-lurker.o", "o_only": True},
    "ice-cube":        {"o": "ice-cube.o",         "o_only": True},
    "lightning-mole":  {"o": "rolling-lightning-mole.o", "o_only": True},
    "plunger-lurker":  {"o": "flying-lurker.o",    "o_only": True},
    "ram":             {"o": "snow-ram.o",          "o_only": True},

    # ── Bosses ───────────────────────────────────────────────────────────────
    "plant-boss":      {"o": "plant-boss.o",       "o_only": True},
    "robotboss":       {"o": "robotboss-h.o",      "o_only": True},

    # ── NPCs ─────────────────────────────────────────────────────────────────
    "pelican":         {"o": "pelican.o",          "o_only": True},
    "robber":          {"o": "rolling-robber.o",   "o_only": True},
    "seagull":         {"o": "seagull.o",          "o_only": True},

    # ── Pickups ──────────────────────────────────────────────────────────────
    "powercellalt":    {"o": "final-door.o",       "o_only": True},

    # ── Platforms ────────────────────────────────────────────────────────────
    "balance-plat":    {"o": "swamp-obs.o",        "o_only": True},
    "launcher":        {"o": "floating-launcher.o","o_only": True},
    "plat-flip":       {"o": "plat-flip.o",        "o_only": True},
    "revcycle":        {"o": "village-obs.o",      "o_only": True},
    "side-to-side-plat":{"o": "sunken-obs.o",     "o_only": True},
    "tar-plat":        {"o": "swamp-obs.o",        "o_only": True},
    "teetertotter":    {"o": "misty-teetertotter.o","o_only": True},
    "wall-plat":       {"o": "wall-plat.o",        "o_only": True},
    "wedge-plat":      {"o": "wedge-plats.o",      "o_only": True},

    # ── Objects ──────────────────────────────────────────────────────────────
    "cavecrystal":     {"o": "darkcave-obs.o",     "o_only": True},
    "cavegem":         {"o": "miners.o",           "o_only": True},
    "ecoclaw":         {"o": "robotboss-misc.o",   "o_only": True},
    "gondola":         {"o": "village3-obs.o",     "o_only": True},
    "shortcut-boulder":{"o": "ogre-obs.o",         "o_only": True},
    "spike":           {"o": "firecanyon-obs.o",   "o_only": True},
    "steam-cap":       {"o": "steam-cap.o",        "o_only": True},
    "swamp-blimp":     {"o": "swamp-blimp.o",      "o_only": True},
    "swamp-rock":      {"o": "swamp-obs.o",        "o_only": True},
    "swamp-rope":      {"o": "swamp-blimp.o",      "o_only": True},
    "swamp-spike":     {"o": "swamp-obs.o",        "o_only": True},
    "tntbarrel":       {"o": "ogre-obs.o",         "o_only": True},
    "whirlpool":       {"o": "whirlpool.o",        "o_only": True},
    "windmill-one":    {"o": "beach-obs.o",        "o_only": True},

    # ── Props ─────────────────────────────────────────────────────────────────
    "dark-plant":      {"o": "rolling-obs.o",      "o_only": True},
    "evilplant":       {"o": "village-obs.o",      "o_only": True},
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
LAVATUBE_TPAGES= ["tpage-1119.go", "tpage-1338.go", "tpage-1340.go", "tpage-1339.go", "tpage-1337.go"] # lav.gd
FIRECANYON_TPAGES=["tpage-1119.go","tpage-815.go",  "tpage-822.go",  "tpage-854.go",  "tpage-1123.go"] # fic.gd
VILLAGE1_TPAGES= ["tpage-398.go",  "tpage-400.go",  "tpage-399.go",  "tpage-401.go",  "tpage-1470.go"] # vi1.gd
VILLAGE2_TPAGES= ["tpage-919.go",  "tpage-922.go",  "tpage-920.go",  "tpage-921.go",  "tpage-1476.go"] # vi2.gd
VILLAGE3_TPAGES= ["tpage-1208.go", "tpage-1210.go", "tpage-1209.go", "tpage-1194.go"]                  # vi3.gd
ROLLING_TPAGES = ["tpage-1119.go", "tpage-923.go",  "tpage-926.go",  "tpage-924.go",  "tpage-925.go",  "tpage-1353.go"] # rol.gd
TRAINING_TPAGES= ["tpage-1309.go", "tpage-1311.go", "tpage-1310.go", "tpage-1308.go", "tpage-775.go"]  # tra.gd
JUNGLEB_TPAGES = ["tpage-485.go",  "tpage-510.go",  "tpage-507.go",  "tpage-966.go"]                   # jub.gd  (plant-boss, plat-flip)
FINALBOSS_TPAGES=["tpage-1419.go", "tpage-1420.go", "tpage-634.go",  "tpage-1418.go", "tpage-545.go"]  # fin.gd  (robotboss, green-eco-lurker, ecoclaw)
CITADEL_TPAGES = ["tpage-1415.go", "tpage-1417.go", "tpage-1416.go", "tpage-1414.go"]                  # cit.gd

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
    "mis-bone-bridge": MISTY_TPAGES,
    "breakaway-left":  MISTY_TPAGES,
    "breakaway-mid":   MISTY_TPAGES,
    "breakaway-right": MISTY_TPAGES,
    "windturbine":     MISTY_TPAGES,
    "boatpaddle":      MISTY_TPAGES,
    # Jungle (jun.gd) — new
    "darkvine":        JUNGLE_TPAGES,
    "junglefish":      JUNGLE_TPAGES,
    "springbox":       JUNGLE_TPAGES,
    "ropebridge":      JUNGLE_TPAGES,
    "accordian":       JUNGLE_TPAGES,
    # Swamp (swa.gd) — new
    "swamp-rat-nest":  SWAMP_TPAGES,
    "sharkey":         SWAMP_TPAGES,
    "swampgate":       SWAMP_TPAGES,
    # Sunken (sun.gd) — new
    "sunkenfisha":     SUNKEN_TPAGES,
    "orbit-plat":      SUNKEN_TPAGES,
    "square-platform": SUNKEN_TPAGES,
    "shover":          SUNKEN_TPAGES,
    # Maincave (mai.gd) — new
    "cave-trap":       CAVE_TPAGES,
    "spider-egg":      CAVE_TPAGES,
    "spider-vent":     CAVE_TPAGES,
    "caveelevator":    CAVE_TPAGES,
    "caveflamepots":   CAVE_TPAGES,
    "cavetrapdoor":    CAVE_TPAGES,
    "cavespatula":     CAVE_TPAGES,
    "cavespatulatwo":  CAVE_TPAGES,
    # Lavatube (lav.gd) — new
    "lavafall":        LAVATUBE_TPAGES,
    "lavafallsewera":  LAVATUBE_TPAGES,
    "lavafallsewerb":  LAVATUBE_TPAGES,
    "lavabase":        LAVATUBE_TPAGES,
    "lavayellowtarp":  LAVATUBE_TPAGES,
    "chainmine":       LAVATUBE_TPAGES,
    "lavaballoon":     LAVATUBE_TPAGES,
    "darkecobarrel":   LAVATUBE_TPAGES,
    # Firecanyon (fic.gd) — new
    "balloon":         FIRECANYON_TPAGES,
    "crate-darkeco-cluster": FIRECANYON_TPAGES,
    # Village1 (vi1.gd) — new
    "villa-starfish":  VILLAGE1_TPAGES,
    "oracle":          VILLAGE1_TPAGES,
    "fishermans-boat": VILLAGE1_TPAGES,
    "ecoventrock":     BEACH_TPAGES,
    # Village2 (vi2.gd) — new
    "pontoon":         VILLAGE2_TPAGES,
    "swamp-tetherrock":VILLAGE2_TPAGES,
    "ceilingflag":     VILLAGE2_TPAGES,
    # Village3 (vi3.gd) — new
    "minershort":      VILLAGE3_TPAGES,
    "minertall":       VILLAGE3_TPAGES,
    # Rolling (rol.gd) — new
    "peeper":          ROLLING_TPAGES,
    # Training (tra.gd) — new
    "tra-pontoon":     TRAINING_TPAGES,
    # Ogre (ogr.gd) — new
    "ogre-bridge":     OGRE_TPAGES,
    "ogre-bridgeend":  OGRE_TPAGES,

    # ── Quick fix: NPCs missing tpages ────────────────────────────────────
    # Village1 NPCs
    "farmer":          VILLAGE1_TPAGES,
    "mayor":           VILLAGE1_TPAGES,
    "yakow":           VILLAGE1_TPAGES,
    "explorer":        VILLAGE1_TPAGES,
    "evilplant":       VILLAGE1_TPAGES,
    "revcycle":        VILLAGE1_TPAGES,
    # Village2 NPCs
    "gambler":         VILLAGE2_TPAGES,
    "geologist":       VILLAGE2_TPAGES,
    "warrior":         VILLAGE2_TPAGES,
    "fireboulder":     VILLAGE2_TPAGES,
    "warpgate":        VILLAGE2_TPAGES,
    # Jungle NPCs
    "fisher":          JUNGLE_TPAGES,
    # Swamp NPC
    "billy":           SWAMP_TPAGES,
    "flutflut":        SWAMP_TPAGES,
    # Beach NPCs
    "sculptor":        BEACH_TPAGES,
    "pelican":         BEACH_TPAGES,
    "seagull":         BEACH_TPAGES,
    "windmill-one":    BEACH_TPAGES,
    # Rolling (rol.gd)
    "robber":          ROLLING_TPAGES,
    "lightning-mole":  ROLLING_TPAGES,
    "dark-plant":      ROLLING_TPAGES,
    # Ogre boss
    "ogreboss":        OGRE_TPAGES,
    "tntbarrel":       OGRE_TPAGES,
    "shortcut-boulder":OGRE_TPAGES,
    "plunger-lurker":  OGRE_TPAGES,

    # ── Needs Both — tpages now added ────────────────────────────────────
    # Snow (sno.gd)
    "ice-cube":        SNOW_TPAGES,
    "ram":             SNOW_TPAGES,
    # Swamp (swa.gd)
    "balance-plat":    SWAMP_TPAGES,
    "tar-plat":        SWAMP_TPAGES,
    "swamp-rock":      SWAMP_TPAGES,
    "swamp-spike":     SWAMP_TPAGES,
    # Village2 (vi2.gd)
    "swamp-blimp":     VILLAGE2_TPAGES,
    "swamp-rope":      VILLAGE2_TPAGES,
    # Village3 (vi3.gd)
    "cavegem":         VILLAGE3_TPAGES,
    "gondola":         VILLAGE3_TPAGES,
    # Sunken (sun.gd)
    "launcher":        SUNKEN_TPAGES,
    "side-to-side-plat": SUNKEN_TPAGES,
    "wall-plat":       SUNKEN_TPAGES,
    "wedge-plat":      SUNKEN_TPAGES,
    "steam-cap":       SUNKEN_TPAGES,
    "whirlpool":       SUNKEN_TPAGES,
    # Jungleb (jub.gd)
    "plant-boss":      JUNGLEB_TPAGES,
    "plat-flip":       JUNGLEB_TPAGES,
    # Finalboss (fin.gd)
    "green-eco-lurker":FINALBOSS_TPAGES,
    "robotboss":       FINALBOSS_TPAGES,
    "ecoclaw":         FINALBOSS_TPAGES,
    "powercellalt":    FINALBOSS_TPAGES,
    # Darkcave (dar.gd)
    "cavecrystal":     DARK_TPAGES,
    # Misty (mis.gd)
    "teetertotter":    MISTY_TPAGES,
    # Firecanyon (fic.gd)
    "spike":           FIRECANYON_TPAGES,
}

# ---------------------------------------------------------------------------
# Music flava table — maps music bank → list of flava variant names.
# Sourced from *flava-table* in goal_src/jak1/engine/sound/sound.gc
# ---------------------------------------------------------------------------
MUSIC_FLAVA_TABLE = {
    "village1":   ["default", "sage", "assistant", "birdlady", "farmer", "mayor",
                   "sculptor", "explorer", "dock", "sage-hut"],
    "jungle":     ["default", "jungle-temple-exit", "jungle-lurkerm", "jungle-temple-top"],
    "firecanyon": ["default", "racer"],
    "jungleb":    ["default", "jungleb-eggtop"],
    "beach":      ["default", "birdlady", "beach-sentinel", "beach-cannon", "beach-grotto"],
    "misty":      ["default", "racer", "misty-boat", "misty-battle"],
    "village2":   ["default", "sage", "assistant", "warrior", "geologist", "gambler", "levitator"],
    "swamp":      ["default", "flutflut", "swamp-launcher", "swamp-battle"],
    "rolling":    ["default", "rolling-gorge"],
    "ogre":       ["default", "ogre-middle", "ogre-end"],
    "village3":   ["default", "to-maincave", "to-snow", "sage", "assistant", "miners"],
    "maincave":   ["default", "robocave", "robocave-top", "maincave", "darkcave"],
    "snow":       ["default", "flutflut", "snow-battle", "snow-cave", "snow-fort", "snow-balls"],
    "lavatube":   ["default", "lavatube-middle", "lavatube-end"],
    "citadel":    ["default", "sage", "assistant", "sage-yellow", "sage-red", "sage-blue", "citadel-center"],
    "finalboss":  ["default", "finalboss-middle", "finalboss-end"],
    "darkcave":   ["default"],
    "robocave":   ["default"],
    "sunken":     ["default"],
}

def _music_flava_items_cb(self, context):
    """Dynamic enum callback: returns flava variants for the selected music bank."""
    bank = getattr(self, "og_music_amb_bank", "none") if self else "none"
    flavas = MUSIC_FLAVA_TABLE.get(bank, ["default"])
    return [(f, f, "", i) for i, f in enumerate(flavas)]


def needed_tpages(actors):
    """Return de-duplicated ordered list of tpage .go files needed for placed entities."""
    seen, r = set(), []
    for a in actors:
        for tp in ETYPE_TPAGES.get(a["etype"], []):
            if tp not in seen:
                seen.add(tp)
                r.append(tp)
    return r


# --- LEVEL_BANKS + SBK_SOUNDS + ALL_SFX_ITEMS ---

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


# --- LUMP_REFERENCE + ACTOR_LINK_DEFS + LUMP_TYPE_ITEMS ---

LUMP_REFERENCE = {
    # ── Enemies (universal to all enemies/bosses) ─────────────────────────
    # Applied via _actor_is_enemy check in the panel draw, not listed per-type.
    # Listed here under a special sentinel key "_enemy" for draw logic.
    "_enemy": [
        ("nav-mesh-sphere", "vector4m", "Fallback nav sphere: 'x y z radius_m'. Auto-injected for nav-unsafe enemies."),
        ("nav-max-users",   "int32",    "Max nav-control users sharing this navmesh. Default 32."),
    ],

    # ── Nav-unsafe enemies (specific) ─────────────────────────────────────
    "babak":          [],
    "lurkercrab":     [],
    "lurkerpuppy":    [],
    "hopper":         [],
    "swamp-rat":      [],
    "kermit":         [],
    "snow-bunny":     [
        ("mode", "uint32", "Variant selector — controls snow-bunny behaviour variant."),
    ],
    "double-lurker":  [],
    "bonelurker":     [],
    "muse":           [],
    "baby-spider":    [],
    "green-eco-lurker":[],

    # ── Process-drawable enemies ───────────────────────────────────────────
    "lurkerworm":     [],
    "junglesnake":    [],
    "swamp-bat": [
        ("num-lurkers", "int32",  "Number of bat slaves spawned. Range 2–8, default 6."),
    ],
    "yeti": [
        ("num-lurkers",  "int32",  "Number of yeti children. Default = path vertex count."),
        ("notice-dist",  "meters", "Distance at which yeti notices player. Default 50m."),
    ],
    "bully":          [],
    "puffer": [
        ("distance", "float", "Min/max notice distance in internal units: 'min max'. e.g. '40960 81920' = 10–20m."),
        ("options",  "enum-uint32", "Use '(fact-options instant-collect)' for instant-kill puffer."),
    ],
    "flying-lurker":  [],
    "plunger-lurker": [],
    "mother-spider":  [],
    "gnawer": [
        ("extra-count",  "int32", "Two values: gnawer spawn counts."),
        ("gnawer",       "int32", "Bitmask controlling gnawer behaviour variants."),
        ("trans-offset", "float", "Position offset from base trans: 'dx dy dz' internal units."),
    ],
    "driller-lurker": [],
    "dark-crystal": [
        ("mode",     "int32", "1 = underwater dark crystal variant."),
        ("extra-id", "int32", "Crystal number / identifier."),
        ("extra-radius", "float", "Collision/activation radius override."),
    ],
    "cavecrusher":    [],
    "quicksandlurker":[],
    "ram":            [],
    "lightning-mole": [],
    "ice-cube":       [],
    "fireboulder":    [],

    # ── Bosses ─────────────────────────────────────────────────────────────
    "ogreboss":       [],
    "plant-boss":     [],
    "robotboss":      [],

    # ── NPCs ───────────────────────────────────────────────────────────────
    "yakow": [
        ("alt-vector", "vector3m", "Yakow wander target position: 'x y z'."),
    ],
    "flutflut":  [],
    "mayor":     [],
    "farmer":    [],
    "fisher":    [],
    "explorer":  [],
    "geologist": [],
    "warrior":   [],
    "gambler":   [],
    "sculptor":  [],
    "billy":     [],
    "pelican":   [],
    "seagull":   [],
    "robber":    [],

    # ── Pickups ────────────────────────────────────────────────────────────
    "fuel-cell": [
        ("movie-pos", "movie-pos", "Cutscene landing position: 'x y z rot_deg'."),
    ],
    "money":         [],
    "buzzer":        [],
    "crate": [
        ("crate-type", "string", "Crate variant: steel / wood / metal / darkeco / iron."),
        ("eco-info",   "eco-info","Pickup contents: '(pickup-type money) amount'."),
    ],
    "orb-cache-top": [
        ("orb-cache-count", "int32", "Number of orbs the cache releases when activated."),
    ],
    "powercellalt":  [],
    "eco-yellow":    [],
    "eco-red":       [],
    "eco-blue":      [],
    "eco-green":     [],

    # ── Platforms ──────────────────────────────────────────────────────────
    "plat": [
        ("sync", "float", "Path timing: 'period_sec phase [ease_out ease_in]'. e.g. '4.0 0.0 0.15 0.15'."),
    ],
    "plat-eco": [
        ("sync",        "float",  "Path timing: 'period_sec phase [ease_out ease_in]'."),
        ("notice-dist", "meters", "Blue eco activation range. -1 = always active."),
    ],
    "plat-button": [
        ("camera-name",   "string", "Name of camera to activate when button pressed."),
        ("bidirectional", "symbol", "Set to 'true' to allow platform to return."),
    ],
    "plat-flip": [
        ("delay",        "float", "Two values: 'before_down_sec before_up_sec'."),
        ("sync-percent", "float", "Phase offset for sync."),
    ],
    "wall-plat":        [],
    "balance-plat":     [],
    "teetertotter":     [],
    "side-to-side-plat":[
        ("sync", "float", "Path timing: 'period_sec phase [ease_out ease_in]'."),
    ],
    "wedge-plat":   [],
    "tar-plat":     [],
    "revcycle":     [],
    "launcher": [
        ("spring-height", "meters", "Launch height. Default from art."),
        ("alt-vector",    "vector3m", "Override launch direction: 'x y z'."),
        ("mode",          "int32",  "Camera mode selector."),
        ("art-name",      "symbol", "Art group override."),
    ],
    "warpgate": [],

    # ── Objects / Interactables ────────────────────────────────────────────
    "cavecrystal": [],
    "cavegem":     [],
    "tntbarrel":   [],
    "shortcut-boulder": [],
    "spike":       [],
    "steam-cap": [
        ("percent", "float", "Completion percentage threshold."),
    ],
    "windmill-one": [],
    "ecoclaw":      [],
    "ecovalve":     [],
    "swamp-rock":   [],
    "gondola":      [],
    "swamp-blimp":  [],
    "swamp-rope":   [],
    "swamp-spike":  [],
    "whirlpool": [
        ("speed", "float", "Two values: 'base_speed random_range' in internal units."),
    ],
    "warp-gate":    [],
    # ── New enemies ────────────────────────────────────────────────────────
    "balloonlurker": [],  # no lumps; alt-actor 0 = partner entity for kill-state check
    "darkvine":      [],  # no lumps
    "junglefish": [
        ("water-height", "float", "Y-coordinate of water surface in raw game units (not meters). Fish positions itself 1m below. Required."),
    ],
    "peeper":        [],  # no lumps; shares lightning-mole art group
    "cave-trap": [
        # alt-actor links to spider-egg entities are set via Waypoints (path) + actor links in JSONC
        ("path", "vector3m", "Patrol path for spawned spiders. Required — export at least 2 waypoints."),
    ],
    "spider-egg": [
        # alt-actor 0 = optional notify-actor (set via actor link, not a lump)
    ],
    "spider-vent":   [],  # no lumps; invisible spawner, just a position
    "swamp-rat-nest": [
        ("num-lurkers", "uint32", "Max rats active at once. Range 1–4. Default 3. Needs 'path' waypoints set."),
    ],
    "sunkenfisha": [
        ("count",            "uint32", "Number of fish in the school (spawns count-1 extra children). Default 1."),
        ("speed",            "float",  "Speed range in game units/frame: 'lo hi'. Defaults: '8192 26624' (2–6.5 m/s)."),
        ("path-max-offset",  "float",  "Max wander from path: 'x_units y_units'. Defaults: '16384 28672' (4m, 7m)."),
        ("path-trans-offset","float",  "Offset the entire path: 'x y z' in raw game units. Default 0 0 0."),
    ],
    "sharkey": [
        ("scale",        "float",  "Uniform scale multiplier. Affects size and collision. Default 1.0."),
        ("water-height", "float",  "Y-coordinate of water surface in raw game units. Required (defaults to 0)."),
        ("delay",        "float",  "Seconds before shark re-engages after losing player. Default 1.0."),
        ("distance",     "meters", "Player trigger radius — how far away shark can spawn. Default 30m."),
        ("speed",        "meters", "Chase speed in meters/sec. Default ~12m/s."),
    ],
    "villa-starfish": [
        ("num-lurkers", "uint32", "Number of starfish children. Range 1–8. Default 3. Needs path waypoints."),
    ],

    # ── New pickups ────────────────────────────────────────────────────────
    "eco-pill":  [],  # no lumps; type/amount hardcoded
    "ecovent":   [
        # alt-actor 0 = optional blocker entity (set via actor link in JSONC, not a lump key)
    ],
    "ventblue":  [],  # identical to ecovent
    "ventred":   [],  # type hardcoded to eco-red
    "ventyellow":[],  # type hardcoded to eco-yellow
    "ecoventrock":[],  # no lumps
    "water-vol": [
        ("water-height", "water-height", "Water surface definition: 'water_m wade_m swim_m [flags] [bottom_m]'. Required."),
        ("attack-event", "symbol",       "Event fired when player drowns. Default 'drown. Bare string: \"'drown\"."),
    ],

    # ── New platforms ──────────────────────────────────────────────────────
    "orbit-plat": [
        ("scale",   "float", "Uniform scale of the platform mesh. Default 1.0."),
        ("timeout", "float", "Seconds to wait before starting orbit. Default 10.0."),
        # alt-actor 0 = center entity to orbit around (required — set via actor link)
    ],
    "square-platform": [
        ("distance", "float", "Travel range: 'down_units up_units'. Defaults '-8192 16384' (-2m down, +4m up). Raw units."),
        # alt-actor 0 = optional water-entity for splash effects
    ],
    "ropebridge": [
        ("art-name", "string", "Bridge variant. Values: ropebridge-32, ropebridge-36, ropebridge-52, ropebridge-70, snow-bridge-36, vil3-bridge-36. Default: ropebridge-32."),
    ],
    "lavaballoon": [
        ("speed", "meters", "Movement speed along path. Default ~3m/s."),
    ],
    "darkecobarrel": [
        ("speed", "meters", "Movement speed along path. Default ~15m/s."),
        ("delay", "float",  "Optional: array of spawn delay times in seconds. Replaces the 4 hardcoded defaults when set."),
    ],
    "caveelevator": [
        ("trans-offset", "float",   "Position offset applied after placement: 'x y z' raw units. Default 0 0 0."),
        ("rotoffset",    "degrees", "Y-axis rotation offset in degrees. Default 0."),
        ("mode",         "uint32",  "Elevator mode variant selector. Default 0."),
    ],
    "caveflamepots": [
        ("shove",       "meters",  "Upward launch force when player touches flame. Default 2m."),
        ("rotoffset",   "degrees", "Y-axis rotation for flame direction. Default 0."),
        ("cycle-speed", "float",   "Three floats: 'period_sec phase_fraction pause_sec'. Defaults: '4.0 0.0 2.0'. Phase offsets multiple pots."),
    ],
    "cavetrapdoor":   [],  # no lumps
    "cavespatula":    [],  # no lumps; art group switches by level name automatically
    "cavespatulatwo": [],  # no lumps
    "ogre-bridge": [
        # alt-actor 0 = ogre-bridgeend entity (required — set via actor link)
    ],
    "ogre-bridgeend": [],  # no lumps
    "pontoon": [
        ("alt-task", "uint32", "Second task ID gate — if this task is complete, pontoon sinks. Default 0 (unused). Main task from entity perm."),
    ],
    "tra-pontoon":    [],  # same as pontoon but no alt-task in training context
    "mis-bone-bridge": [
        ("animation-select", "uint32", "Selects bone bridge variant and particle group. Values: 1, 2, 3, 7. Default 0 (no particles)."),
    ],
    "breakaway-left": [
        ("height-info", "float", "Two floats controlling fall height offsets: 'h1 h2'. Default 0 0."),
    ],
    "breakaway-mid":  [
        ("height-info", "float", "Two floats controlling fall height offsets: 'h1 h2'. Default 0 0."),
    ],
    "breakaway-right":[
        ("height-info", "float", "Two floats controlling fall height offsets: 'h1 h2'. Default 0 0."),
    ],

    # ── New objects / interactables ────────────────────────────────────────
    "swingpole":  [],  # no art, no lumps; position+rotation from entity transform only. Y-axis = pole axis.
    "springbox": [
        ("spring-height", "meters", "Launch height in meters. Default ~11m."),
    ],
    # All eco-door subclasses share the same lump schema as the base type.
    "eco-door": [
        ("scale", "float",   "Uniform scale. Default 1.0."),
        ("flags", "uint32",  "Behaviour flags bitfield. auto-close=4, one-way=8. Managed by Door Settings panel."),
        # state-actor = entity whose perm-complete status locks/unlocks the door (set via actor link UI)
    ],
    "jng-iris-door": [
        ("scale", "float",   "Uniform scale. Default 1.0."),
        ("flags", "uint32",  "Behaviour flags bitfield. auto-close=4, one-way=8. Managed by Door Settings panel."),
    ],
    "sidedoor": [
        ("scale", "float",   "Uniform scale. Default 1.0."),
        ("flags", "uint32",  "Behaviour flags bitfield. auto-close=4, one-way=8. Managed by Door Settings panel."),
    ],
    "rounddoor": [
        # auto-close and one-way are hardcoded in eco-door-method-25; flags lump is ignored.
    ],
    "launcherdoor": [
        ("continue-name", "string", "Level continue point name set when door is passed through. e.g. \"village1-hut\"."),
    ],
    "sun-iris-door": [
        ("proximity",    "uint32", "Set to 1 to open by proximity (Jak walks near). Default 0 = event-triggered only."),
        ("timeout",      "float",  "Seconds before door auto-closes after opening. 0 = stay open. Default 0."),
        ("scale-factor", "float",  "Uniform scale multiplier. Default 1.0."),
    ],
    "basebutton": [
        ("timeout", "float", "Seconds before button resets after being pressed. 0 = stays pressed. Default 0."),
        # alt-actor = entity to send 'trigger event to (set via actor link UI)
    ],
    "shover": [
        ("shove",              "meters",  "Upward launch force when platform hits player. Default 3m."),
        ("collision-mesh-id",  "uint32",  "Collision mesh index. Default 0."),
        ("trans-offset",       "float",   "Position offset: 'x y z' raw units. Default 0 0 0."),
        ("rotoffset",          "degrees", "Y-axis rotation. Default 0."),
    ],
    "swampgate":  [],  # no lumps; open/close driven by entity perm status
    "ceilingflag":[],  # no lumps; pure prop
    "windturbine": [
        ("particle-select", "uint32", "Set to 1 to enable particle effects. Default 0 (off)."),
    ],
    "boatpaddle":  [],  # no lumps; ambient animation only
    "accordian": [
        # alt-actor 0 = optional task gate entity (entity link, not a lump)
    ],
    "lavafall":        [],  # no lumps; pure prop animation
    "lavafallsewera":  [],  # no lumps
    "lavafallsewerb":  [],  # no lumps
    "lavabase":        [],  # no lumps
    "lavayellowtarp":  [],  # no lumps
    "chainmine":       [],  # no lumps; auto-kills on contact
    "balloon":         [],  # no lumps; ambient prop
    "crate-darkeco-cluster": [],  # no lumps; standard dark eco crate cluster
    "swamp-tetherrock": [],  # no lumps; task-gated breakable rock
    "fishermans-boat":  [],  # no lumps; state depends on current-continue level name

    # ── New NPCs ───────────────────────────────────────────────────────────
    "oracle": [
        ("alt-task", "uint32", "Second orb task ID (game-task enum value). For two-orb oracle. Default 0 (one orb only). First task from entity perm."),
    ],
    "minershort": [
        # alt-actor 0 = minertall partner (required — must be paired; set via actor link)
    ],
    "minertall":  [],  # no lumps; pair link held by minershort

    "test-actor":   [],

    # ── Props ──────────────────────────────────────────────────────────────
    "dark-plant":   [],  # no lumps; idle animation, task-gated state
    "evilplant":    [],  # no lumps; idle animation only

    # ── Newly-wired enemies ────────────────────────────────────────────────
    "baby-spider":     [],  # no lumps; self-aligns to ground, alt-actor optional
    "cavecrusher":     [],  # no lumps
    "dark-crystal": [
        ("mode",         "int32",  "1 = underwater variant. Default 0."),
        ("extra-id",     "int32",  "Crystal identifier/number."),
        ("extra-radius", "float",  "Collision/activation radius override."),
    ],
    "mother-spider":   [],  # no lumps; path-driven
    "fireboulder": [
        ("alt-task", "uint32", "Second task gate ID. Door stays closed until this task is complete."),
    ],
    "green-eco-lurker":[],  # no lumps
    "ice-cube": [
        ("mode", "uint32", "Variant selector. Default -1 (standard). 0 = alternate behaviour."),
    ],
    "lightning-mole":  [],  # no lumps
    "plunger-lurker":  [],  # no lumps
    "ram": [
        ("extra-id", "int32",  "Ram identifier — which ram this is in the sequence (0-based)."),
        ("mode",     "uint32", "1 = boss-fight mode. Default 0 (normal patrol mode)."),
    ],

    # ── Newly-wired bosses ─────────────────────────────────────────────────
    "plant-boss":   [],  # no lumps; level-scripted
    "robotboss":    [],  # no lumps; level-scripted

    # ── Newly-wired NPCs ───────────────────────────────────────────────────
    "pelican":      [],  # no lumps; path-driven
    "robber": [
        ("initial-spline-pos", "float",  "Starting position along the spline path (0.0–1.0)."),
        ("water-height",       "float",  "Y-coordinate of water surface in raw units."),
        ("timeout",            "float",  "Seconds before robber despawns. Default 10.0s."),
    ],
    "seagull":      [],  # no lumps

    # ── Newly-wired pickups ────────────────────────────────────────────────
    "powercellalt":    [],  # no lumps; standard fuel-cell alt art
    "eco-blue":        [],  # legacy; use ecovent instead
    "eco-red":         [],  # legacy; use ventred instead
    "eco-yellow":      [],  # legacy; use ventyellow instead
    "eco-green":       [],  # legacy; no standard replacement

    # ── Newly-wired platforms ──────────────────────────────────────────────
    "balance-plat": [
        ("distance", "meters", "Vertical travel range. Default ~5m."),
    ],
    "launcher": [
        ("spring-height",  "meters", "Launch height. Default ~40m."),
        ("trigger-height", "meters", "Height above launcher base where Jak gets launched."),
    ],
    "plat-flip": [
        ("delay", "float", "Two floats: 'before_down_sec before_up_sec'. e.g. '2.0 3.0'."),
        ("sync-percent", "float", "Phase offset as fraction of cycle (0.0–1.0)."),
    ],
    "revcycle": [
        ("sync", "float", "Path timing: 'period_sec phase [ease_out ease_in]'. Period hardcoded ~16s if not set."),
    ],
    "side-to-side-plat": [
        ("sync", "float", "Path timing: 'period_sec phase [ease_out ease_in]'."),
    ],
    "tar-plat": [
        ("scale-factor", "float", "Uniform scale multiplier. Default 1.0."),
    ],
    "teetertotter":    [],  # no lumps; physics-driven
    "wall-plat": [
        ("tunemeters", "meters", "Z-offset tuning for wall alignment. Default 0."),
    ],
    "warpgate":        [],  # no lumps; invisible process-hidden (teleporter activation zone)
    "wedge-plat": [
        ("rotspeed",  "degrees", "Rotation speed in degrees/sec."),
        ("rotoffset", "degrees", "Initial rotation offset."),
        ("distance",  "meters",  "Travel distance from origin. Default ~9m or ~17m depending on variant."),
    ],

    # ── Newly-wired objects ────────────────────────────────────────────────
    "cavecrystal": [
        ("timeout", "float", "Seconds before crystal deactivates. Default 8.0s."),
    ],
    "cavegem":         [],  # no lumps; ambient decoration
    "ecoclaw":         [],  # no lumps; level-scripted prop
    "gondola":         [],  # no lumps; animated path prop
    "shortcut-boulder":[],  # no lumps; destructible boulder
    "spike": [
        # spike lumps checked: none found
    ],
    "steam-cap": [
        ("percent", "float", "Completion percentage threshold for cap behaviour."),
    ],
    "swamp-blimp":     [],  # no lumps; ambient decoration
    "swamp-rock": [
        ("scale-factor", "float", "Uniform scale. Default 1.0."),
    ],
    "swamp-rope":      [],  # no lumps
    "swamp-spike":     [],  # no lumps; static hazard
    "tntbarrel":       [],  # no lumps; explodes on contact
    "warp-gate":       [],  # no lumps (basebutton subtype; task-gated automatically)
    "whirlpool": [
        ("speed", "float", "Two floats: 'base_speed_units random_range'. Controls spin rate."),
    ],
    "windmill-one":    [],  # no lumps; animated decoration

    "test-actor":   [],
}


UNIVERSAL_LUMPS = [
    ("vis-dist",      "meters",  "Distance at which entity stays active/visible. Enemies default 200m."),
    ("idle-distance", "meters",  "Player must be closer than this to wake the enemy. Default 80m."),
    ("shadow-mask",   "uint32",  "Which shadow layers render for this entity. e.g. 255 = all."),
    ("light-index",   "uint32",  "Index into the level's light array. Controls entity illumination."),
    ("lod-dist",      "meters",  "Distance threshold for LOD switching. Array of floats per LOD level."),
    ("texture-bucket","int32",   "Texture bucket for draw calls. Default 1."),
    ("options",       "enum-uint32", "fact-options bitfield e.g. '(fact-options has-power-cell)'."),
    ("visvol",        "vector4m","Visibility bounding box — two vector4m entries (min corner, max corner)."),
]

def _lump_ref_for_etype(etype):
    """Return (universal_lumps, actor_lumps) for a given etype.

    universal_lumps — always shown for every actor
    actor_lumps     — specific to this etype, plus shared enemy lumps if applicable
    """
    actor_entries = list(LUMP_REFERENCE.get(etype, []))
    einfo = ENTITY_DEFS.get(etype, {})
    # Inject enemy-universal lumps for enemies and bosses
    if einfo.get("cat") in ("Enemies", "Bosses"):
        actor_entries = list(LUMP_REFERENCE.get("_enemy", [])) + actor_entries
    return UNIVERSAL_LUMPS, actor_entries


# ===========================================================================
# ACTOR ENTITY LINK SYSTEM
# ---------------------------------------------------------------------------
# Many actors reference other actors at runtime via entity-actor-lookup, which
# reads a named lump key (e.g. "alt-actor", "water-actor", "state-actor") and
# resolves it to an entity-actor pointer.
#
# The engine supports two formats for these references:
#   - string array:  ["string", "orbit-plat-center-0"]   → entity-by-name
#   - uint32 array:  ["uint32", <aid>]                    → entity-by-aid
#
# We use string format (entity name).  The level builder always assigns names
# as "{etype}-{uid}", matching what collect_actors writes into lump["name"].
#
# ACTOR_LINK_DEFS maps etype → list of slot definitions:
#   (lump_key, slot_index, label, accepted_etypes, required)
#
#   lump_key      — the res-lump key the engine reads (e.g. "alt-actor")
#   slot_index    — 0-based index within that key's array
#   label         — human-readable description shown in the panel
#   accepted_etypes — list of valid target etype strings, or ["any"] for any ACTOR_
#   required      — True = export warns if unset; False = optional
#
# At export, all slots for the same lump_key are collected in slot_index order
# and written as a single string array lump.
# ===========================================================================

ACTOR_LINK_DEFS = {
    # ── Enemies ──────────────────────────────────────────────────────────────
    "cave-trap": [
        ("alt-actor", 0, "Spider Egg 0",  ["spider-egg"], False),
        ("alt-actor", 1, "Spider Egg 1",  ["spider-egg"], False),
        ("alt-actor", 2, "Spider Egg 2",  ["spider-egg"], False),
        ("alt-actor", 3, "Spider Egg 3",  ["spider-egg"], False),
    ],
    "spider-egg": [
        ("alt-actor", 0, "Notify actor (messaged on hatch)", ["any"], False),
    ],
    "quicksandlurker": [
        ("water-actor", 0, "Mud surface entity", ["any"], False),
    ],
    "balloonlurker": [
        ("water-actor", 0, "Water surface entity", ["any"], False),
    ],
    "swamp-rat-nest": [
        # No alt-actor — communicates via path + proximity
    ],
    "villa-starfish": [
        # No alt-actor — path-driven
    ],

    # ── Platforms ─────────────────────────────────────────────────────────────
    "orbit-plat": [
        ("alt-actor", 0, "Center entity to orbit around", ["any"], True),
    ],
    "square-platform": [
        ("alt-actor", 0, "Water entity (for splash effects)", ["water-vol"], False),
    ],
    "snow-log": [
        ("alt-actor", 0, "Snow log master controller", ["any"], True),
    ],
    "snow-log-button": [
        ("alt-actor", 0, "Snow log to activate", ["snow-log"], True),
    ],
    "ogre-bridge": [
        ("alt-actor", 0, "Ogre bridge end piece", ["ogre-bridgeend"], True),
    ],
    "lavaballoon": [
        # path-driven; no actor links
    ],
    "darkecobarrel": [
        # path-driven; no actor links
    ],

    # ── Interactables / Doors ─────────────────────────────────────────────────
    "eco-door": [
        # state-actor: optional entity whose perm-complete status controls lock state.
        # If the state-actor's task is complete the door unlocks (ecdf01 path).
        # If not complete it stays locked (ecdf00 path).  Leave unset for blue-eco only.
        ("state-actor", 0, "Lock controller (door unlocks when this entity is activated)", ["basebutton", "any"], False),
    ],
    "jng-iris-door": [
        ("state-actor", 0, "Lock controller (door unlocks when this entity is activated)", ["basebutton", "any"], False),
    ],
    "sidedoor": [
        ("state-actor", 0, "Lock controller (door unlocks when this entity is activated)", ["basebutton", "any"], False),
    ],
    "rounddoor": [
        # no actor links — auto-close/one-way hardcoded; no state-actor support needed
    ],
    "sun-iris-door": [
        # No actor links — opens by proximity or 'trigger event from a trigger volume.
    ],
    "basebutton": [
        # basebutton controls eco-door via the door's state-actor link (door polls
        # button's perm-complete each frame — no event needed from button side).
        # alt-actor ('trigger dispatch) is only useful for sun-iris-door which
        # actually opens on 'trigger. Add that slot when sun-iris-door is wired.
    ],
    "helix-water": [
        ("alt-actor", 0, "Helix button 0",  ["helix-button"], True),
        ("alt-actor", 1, "Helix button 1",  ["helix-button"], False),
        ("alt-actor", 2, "Helix button 2",  ["helix-button"], False),
        ("alt-actor", 3, "Helix button 3",  ["helix-button"], False),
    ],
    "helix-button": [
        ("alt-actor", 0, "Helix water controller",  ["helix-water"],      True),
        ("alt-actor", 1, "Helix slide door",         ["helix-slide-door"], True),
    ],
    "accordian": [
        ("alt-actor", 0, "Task gate entity (optional)", ["any"], False),
    ],
    "swamp-tetherrock": [
        ("alt-actor", 0, "Master blimp entity (optional)", ["swamp-blimp"], False),
    ],

    # ── Pickups / Eco ─────────────────────────────────────────────────────────
    "ecovent": [
        ("alt-actor", 0, "Blocker entity (vent blocked until this task completes)", ["any"], False),
    ],
    "ventblue": [
        ("alt-actor", 0, "Blocker entity", ["any"], False),
    ],
    "ventred": [
        ("alt-actor", 0, "Blocker entity", ["any"], False),
    ],
    "ventyellow": [
        ("alt-actor", 0, "Blocker entity", ["any"], False),
    ],

    # ── NPCs ──────────────────────────────────────────────────────────────────
    "minershort": [
        ("alt-actor", 0, "Paired minertall (required)", ["minertall"], True),
    ],
}


def _actor_link_slots(etype):
    """Return the list of link slot defs for this etype, or []."""
    return ACTOR_LINK_DEFS.get(etype, [])


def _actor_has_links(etype):
    """True if this etype has any defined entity link slots."""
    return bool(_actor_link_slots(etype))


def _actor_links(obj):
    """Return the og_actor_links CollectionProperty on an actor empty."""
    return getattr(obj, "og_actor_links", None)


def _actor_get_link(obj, lump_key, slot_index):
    """Return the OGActorLink entry for (lump_key, slot_index), or None."""
    links = _actor_links(obj)
    if not links:
        return None
    for entry in links:
        if entry.lump_key == lump_key and entry.slot_index == slot_index:
            return entry
    return None


def _actor_set_link(obj, lump_key, slot_index, target_name):
    """Set or update a link entry. Creates if missing."""
    links = _actor_links(obj)
    if links is None:
        return
    for entry in links:
        if entry.lump_key == lump_key and entry.slot_index == slot_index:
            entry.target_name = target_name
            return
    entry = links.add()
    entry.lump_key    = lump_key
    entry.slot_index  = slot_index
    entry.target_name = target_name


def _actor_remove_link(obj, lump_key, slot_index):
    """Remove a link entry. Returns True if found."""
    links = _actor_links(obj)
    if links is None:
        return False
    for i, entry in enumerate(links):
        if entry.lump_key == lump_key and entry.slot_index == slot_index:
            links.remove(i)
            return True
    return False


def _build_actor_link_lumps(obj, etype):
    """Build dict of lump_key → ["string", name0, name1, ...] for all set links.

    Gaps in the index sequence are skipped (sparse arrays not supported by engine).
    Returns a dict of lump entries to merge into the actor's lump dict at export.
    """
    slots = _actor_link_slots(etype)
    if not slots:
        return {}

    # Group slots by lump_key, collect target names in slot_index order
    from collections import defaultdict
    by_key = defaultdict(dict)  # lump_key → {slot_index: target_name}
    for (lkey, sidx, _label, _accepted, _required) in slots:
        by_key[lkey]  # ensure key exists even if no links set

    links = _actor_links(obj)
    if links:
        for entry in links:
            if entry.target_name and entry.lump_key in by_key:
                # target_name is the Blender object name (e.g. "ACTOR_basebutton_0").
                # The engine resolves links by the entity's lump 'name field, which
                # the addon sets as "{etype}-{uid}" (e.g. "basebutton-0").
                # Convert: strip "ACTOR_" prefix, replace first "_" with "-".
                raw = entry.target_name
                if raw.startswith("ACTOR_"):
                    raw = raw[6:]           # strip "ACTOR_"
                    raw = raw.replace("_", "-", 1)  # first _ → - : "basebutton-0"
                by_key[entry.lump_key][entry.slot_index] = raw

    result = {}
    for lkey, slot_map in by_key.items():
        if not slot_map:
            continue
        # Build ordered list: slot 0, 1, 2... skipping missing
        max_idx = max(slot_map.keys())
        names = []
        for i in range(max_idx + 1):
            if i in slot_map:
                names.append(slot_map[i])
        if names:
            result[lkey] = ["string"] + names
    return result


# ===========================================================================
# LUMP ROW SYSTEM
# ---------------------------------------------------------------------------
# ACTOR_ empties can hold a CollectionProperty of OGLumpRow entries.
# Each row is a (key, ltype, value) triplet that gets injected into the lump
# dict at export time. The assisted panel is the primary UI for this.
#
# Type strings map 1:1 to the 18 valid JSONC lump type strings understood by
# the C++ level builder (goalc/build_level/common/Entity.cpp).
#
# Value field is space-separated for multi-value types:
#   meters    → "50.0"           → ["meters", 50.0]
#   float     → "4.0 0.0 0.15"  → ["float", 4.0, 0.0, 0.15]
#   vector3m  → "1.5 2.0 -3.0"  → ["vector3m", [1.5, 2.0, -3.0]]
#   symbol    → "thunder"        → ["symbol", "thunder"]
#   int32     → "3"              → ["int32", 3]
#
# Export priority (highest wins per key):
#   1. Hardcoded addon values (name, path, sync, eco-info, etc.)  — lowest
#   2. Assisted lump rows (this system)
# Conflicts are logged as warnings in the export log.
# ===========================================================================

LUMP_TYPE_ITEMS = [
    # Numeric scalars / arrays
    ("float",        "float",        "Raw float array — space-separate multiple values e.g. '4.0 0.0 0.15 0.15'"),
    ("meters",       "meters",       "Single float, scaled × 4096. Use for distances in metres"),
    ("degrees",      "degrees",      "Single float, scaled × 182.044. Use for angles in degrees"),
    ("int32",        "int32",        "Signed 32-bit int array — space-separate multiple values"),
    ("uint32",       "uint32",       "Unsigned 32-bit int array — space-separate multiple values"),
    # Enum helpers
    ("enum-int32",   "enum-int32",   "GOAL enum resolved to int32 e.g. '(game-task village1-yakow)'"),
    ("enum-uint32",  "enum-uint32",  "GOAL enum resolved to uint32 e.g. '(fact-options has-power-cell)'"),
    # Vectors
    ("vector4m",     "vector4m",     "4-component vector, each × 4096 — 'x y z w'"),
    ("vector3m",     "vector3m",     "3-component vector, each × 4096, w=1 — 'x y z'"),
    ("vector-vol",   "vector-vol",   "Volume vector: 'x y z radius_m' (xyz raw, w × 4096)"),
    ("vector",       "vector",       "4-component raw vector — 'x y z w' (no unit scaling)"),
    ("movie-pos",    "movie-pos",    "Cutscene position: 'x y z rot_deg' (xyz × 4096, w × degrees)"),
    # Compound
    ("water-height", "water-height", "Water volumes: 'water wade swim flags [bottom]' (4-5 values)"),
    ("eco-info",     "eco-info",     "Pickup encoding — use the dedicated eco-info / cell-info / buzzer-info formats"),
    ("cell-info",    "cell-info",    "Fuel cell: '(game-task none)' — encodes task ID"),
    ("buzzer-info",  "buzzer-info",  "Scout fly: '(game-task none) index'"),
    # String-likes
    ("symbol",       "symbol",       "GOAL symbol reference e.g. 'thunder'"),
    ("string",       "string",       "Plain string value"),
    ("type",         "type",         "GOAL type reference e.g. 'process-drawable'"),
]

# Keys that the hardcoded export system always sets.
# Lump rows that target these keys will emit a warning but are NOT blocked —
# the row value takes priority, letting power users override defaults.
_LUMP_HARDCODED_KEYS = frozenset({
    "name", "path", "pathb", "sync", "options",
    "eco-info", "cell-info", "buzzer-info", "crate-type",
    "nav-mesh-sphere", "idle-distance", "vis-dist", "notice-dist",
})


def _parse_lump_row(key, ltype, value_str):
    """Parse an OGLumpRow into a JSONC lump value, or return None on error.

    Returns (jsonc_value, error_str) where error_str is None on success.
    """
    s = value_str.strip()
    if not s:
        return None, "empty value"
    if not key.strip():
        return None, "empty key"

    try:
        # Types that take a single string / enum value
        if ltype in ("symbol", "string", "type", "enum-int32", "enum-uint32",
                     "cell-info"):
            return [ltype, s], None

        if ltype == "buzzer-info":
            parts = s.split()
            if len(parts) == 1:
                return ["buzzer-info", parts[0], 1], None
            return ["buzzer-info", parts[0], int(parts[1])], None

        if ltype == "eco-info":
            # Value format: "(pickup-type money) 3" — split on closing paren
            # so the GOAL expression isn't broken by internal spaces.
            s_stripped = s.strip()
            if ")" in s_stripped:
                paren_end = s_stripped.index(")") + 1
                pickup_type = s_stripped[:paren_end].strip()
                remainder = s_stripped[paren_end:].strip()
                if not remainder:
                    return None, "eco-info needs '(pickup-type ...) amount'"
                return ["eco-info", pickup_type, int(remainder)], None
            else:
                parts = s_stripped.split()
                if len(parts) < 2:
                    return None, "eco-info needs 'pickup-type amount'"
                return ["eco-info", parts[0], int(parts[1])], None

        # Numeric scalar types
        if ltype in ("meters", "degrees"):
            return [ltype, float(s)], None

        # Multi-float / multi-int types
        if ltype == "float":
            nums = [float(x) for x in s.split()]
            return ["float"] + nums, None

        if ltype == "int32":
            nums = [int(x) for x in s.split()]
            return ["int32"] + nums, None

        if ltype == "uint32":
            nums = [int(x) for x in s.split()]
            return ["uint32"] + nums, None

        # Vector types — nested list format
        if ltype == "vector3m":
            nums = [float(x) for x in s.split()]
            if len(nums) != 3:
                return None, f"vector3m needs 3 values, got {len(nums)}"
            return ["vector3m", nums], None

        if ltype in ("vector4m", "vector", "movie-pos", "vector-vol"):
            nums = [float(x) for x in s.split()]
            if len(nums) != 4:
                return None, f"{ltype} needs 4 values, got {len(nums)}"
            return [ltype, nums], None

        if ltype == "water-height":
            parts = s.split()
            if len(parts) < 4:
                return None, "water-height needs at least 4 values"
            return ["water-height"] + [float(p) if i != 3 else p
                                       for i, p in enumerate(parts)], None

    except (ValueError, IndexError) as e:
        return None, str(e)

    return None, f"unknown type '{ltype}'"



# --- AGGRO_TRIGGER_EVENTS + AGGRO_EVENT_ENUM_ITEMS + _aggro_event_id ---

AGGRO_TRIGGER_EVENTS = [
    ("cue-chase",       "Aggro (chase player)",                  "Wake enemy and start chasing player"),
    ("cue-patrol",      "Patrol",                                 "Return enemy to patrol state"),
    ("go-wait-for-cue", "Wait for cue (freeze)",                  "Freeze enemy until next cue event"),
]

AGGRO_EVENT_ENUM_ITEMS = [(n, lbl, desc) for n, lbl, desc in AGGRO_TRIGGER_EVENTS]


def _aggro_event_id(name):
    """Return the integer enum (0/1/2) for an event name. Default 0."""
    for i, (n, _, _) in enumerate(AGGRO_TRIGGER_EVENTS):
        if n == name:
            return i
    return 0


