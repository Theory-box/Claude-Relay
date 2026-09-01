# =============================================================================
# AUDIO / AMBIENCE PANEL — DRAFT
# scratch/audio_panel_draft.py
#
# HOW TO INTEGRATE:
#   1. Add the new props to OGProperties (Section A)
#   2. Replace collect_ambients() with the new version (Section B)
#   3. Update patch_level_info() to read the new props (Section C)
#   4. Add the operator + panel classes (Section D)
#   5. Add OG_OT_AddSoundEmitter and OG_PT_Audio to the classes tuple in register()
# =============================================================================


# ─────────────────────────────────────────────────────────────────────────────
# SECTION A — OGProperties additions
# Add these lines inside OGProperties (after lightbake_samples)
# ─────────────────────────────────────────────────────────────────────────────

MUSIC_BANK_ITEMS = [
    ("none",         "None",            "", 0),
    ("menu",         "menu",            "", 1),
    ("village1",     "village1",        "", 2),
    ("beach",        "beach",           "", 3),
    ("jungle",       "jungle",          "", 4),
    ("misty",        "misty",           "", 5),
    ("firecanyon",   "firecanyon",      "", 6),
    ("village2",     "village2",        "", 7),
    ("sunken",       "sunken",          "", 8),
    ("swamp",        "swamp",           "", 9),
    ("rolling",      "rolling",         "", 10),
    ("ogre",         "ogre",            "", 11),
    ("village3",     "village3",        "", 12),
    ("snow",         "snow",            "", 13),
    ("maincave",     "maincave",        "", 14),
    ("darkcave",     "darkcave",        "", 15),
    ("robocave",     "robocave",        "", 16),
    ("lavatube",     "lavatube",        "", 17),
    ("citadel",      "citadel",         "", 18),
    ("finalboss",    "finalboss",       "", 19),
    ("custom",       "Custom (type below)", "", 20),
]

# Props to add inside OGProperties:
#
#   music_bank:        EnumProperty(name="Music Bank", items=MUSIC_BANK_ITEMS, default="none")
#   music_bank_custom: StringProperty(name="Custom Bank Name", default="")
#   sound_banks:       StringProperty(name="Sound Banks",
#                          description="Space-separated list e.g. 'common village1'",
#                          default="")
#   ambient_default_radius: FloatProperty(name="Default Emitter Radius (m)",
#                          default=15.0, min=1.0, max=200.0,
#                          description="Bsphere radius for new sound emitters")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION B — Replacement for collect_ambients()
# Reads og_sound_name, og_sound_radius, og_sound_volume, og_sound_mode
# from each AMBIENT_ empty's custom properties.
# Falls back to the old hint behaviour if og_sound_name is absent.
# ─────────────────────────────────────────────────────────────────────────────

def collect_ambients(scene):
    out = []
    for o in scene.objects:
        if not (o.name.startswith("AMBIENT_") and o.type == "EMPTY"):
            continue
        l = o.location
        gx, gy, gz = round(l.x, 4), round(l.z, 4), round(-l.y, 4)

        # Custom sound emitter path
        if o.get("og_sound_name"):
            radius   = float(o.get("og_sound_radius",  15.0))
            volume   = float(o.get("og_sound_volume",   1.0))
            mode     = str(o.get("og_sound_mode",  "auto"))
            snd_name = str(o["og_sound_name"]).lower().strip()
            out.append({
                "trans":   [gx, gy, gz, radius],
                "bsphere": [gx, gy, gz, radius],
                "lump": {
                    "name":      o.name[8:].lower() or "ambient",
                    "type":      "'ambient-sound",
                    "sound-name": snd_name,
                    "volume":    volume,
                    "play-mode": f"'{mode}",
                },
            })
        else:
            # Legacy hint emitter — unchanged from original
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


# ─────────────────────────────────────────────────────────────────────────────
# SECTION C — patch_level_info() replacement lines
# Replace the three hardcoded sound lines in the f-string with these:
#
#   props = scene.og_props
#   _bank = props.music_bank_custom.strip() if props.music_bank == "custom" \
#           else props.music_bank
#   _music_val = f"'{_bank}" if _bank and _bank != "none" else "#f"
#   _sbanks = " ".join(f"'{s}" for s in props.sound_banks.split() if s)
#   _sbanks_val = f"'({_sbanks})" if _sbanks else "'()"
#
# Then in the block f-string:
#   f"       :sound-banks {_sbanks_val}\n"
#   f"       :music-bank {_music_val}\n"
#   f"       :ambient-sounds '()\n"   ← unchanged for now; ambient sounds list
#                                        is driven by the JSONC ambients array
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# SECTION D — Operator + Panel (drop in before register())
# ─────────────────────────────────────────────────────────────────────────────

import bpy
from bpy.types import Panel, Operator

SOUND_MODE_ITEMS = [
    ("auto",    "Auto",    "Play automatically when player is in range", 0),
    ("notice",  "Notice",  "One-shot on player enter",                   1),
    ("ambient", "Ambient", "Looping ambient track",                      2),
]


class OG_OT_AddSoundEmitter(Operator):
    """Add a sound emitter empty at the 3D cursor"""
    bl_idname  = "og.add_sound_emitter"
    bl_label   = "Add Sound Emitter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        props = ctx.scene.og_props

        # Count existing emitters for a unique name
        existing = [o for o in ctx.scene.objects if o.name.startswith("AMBIENT_snd")]
        idx = len(existing) + 1
        name = f"AMBIENT_snd{idx:03d}"

        bpy.ops.object.empty_add(type="SPHERE", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = name
        o.empty_display_size = props.ambient_default_radius * 0.1  # visual hint

        # Stamp custom props — user edits these in the N-panel or Properties
        o["og_sound_name"]   = "silence"          # replace with actual sound ID
        o["og_sound_radius"] = props.ambient_default_radius
        o["og_sound_volume"] = 1.0
        o["og_sound_mode"]   = "ambient"

        self.report({"INFO"}, f"Added sound emitter '{name}' — edit og_sound_name in Object Properties")
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

        # ── Level-wide Music ──────────────────────────────────────────────
        box = layout.box()
        box.label(text="Level Music", icon="PLAY")
        col = box.column(align=True)
        col.prop(props, "music_bank", text="Music Bank")
        if props.music_bank == "custom":
            col.prop(props, "music_bank_custom", text="Bank Name")

        # ── Sound Banks ───────────────────────────────────────────────────
        box2 = layout.box()
        box2.label(text="Sound Banks", icon="SPEAKER")
        box2.prop(props, "sound_banks", text="")
        box2.label(text="Space-separated  e.g.  common village1", icon="INFO")

        layout.separator(factor=0.4)

        # ── Sound Emitters ────────────────────────────────────────────────
        box3 = layout.box()
        box3.label(text="Sound Emitters", icon="OUTLINER_OB_SPEAKER")
        col3 = box3.column(align=True)
        col3.prop(props, "ambient_default_radius", text="Default Radius (m)")
        col3.operator("og.add_sound_emitter", text="Add Emitter at Cursor", icon="ADD")

        # List existing emitters in scene
        emitters = [o for o in ctx.scene.objects if o.name.startswith("AMBIENT_") and o.type == "EMPTY"]
        if emitters:
            layout.separator(factor=0.3)
            sub = layout.box()
            sub.label(text=f"{len(emitters)} emitter(s) in scene:", icon="OUTLINER_OB_EMPTY")
            for o in emitters[:8]:
                row = sub.row(align=True)
                snd = o.get("og_sound_name", "hint")
                row.label(text=f"{o.name}  →  {snd}", icon="DOT")
                # Click to select
                op = row.operator("object.select_all", text="", icon="RESTRICT_SELECT_OFF")
            if len(emitters) > 8:
                sub.label(text=f"… and {len(emitters) - 8} more")
        else:
            layout.label(text="No emitters placed yet", icon="INFO")

# ─────────────────────────────────────────────────────────────────────────────
# Register additions (add these to the existing classes tuple):
#   OG_OT_AddSoundEmitter,
#   OG_PT_Audio,
# ─────────────────────────────────────────────────────────────────────────────
