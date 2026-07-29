# SPDX-License-Identifier: GPL-3.0-or-later
#
# Preferences Migrator  —  v1.0.0  (Blender 4.2+ extension)
# -------------------------------------------------------------------------
# Copies user preferences (userpref.blend) from one installed Blender
# version INTO the currently running one, so you don't have to hunt through
# the config folders by hand.
#
# DIRECTION (important): this add-on always copies preferences INTO the
# Blender you are running it from. To move your 4.4 settings to 4.2, run it
# from *inside Blender 4.2* and pick 4.4 as the source.
#
# HOW IT FINDS VERSIONS:
#   bpy.utils.resource_path('USER') returns THIS version's user folder, e.g.
#   .../Blender/4.4. Its parent (.../Blender) holds every installed version
#   as a sibling folder. We scan those, keeping only ones that actually have
#   a config/userpref.blend, and list them in a dropdown.
#
# SAFETY:
#   Before overwriting, the current userpref.blend (and startup.blend, if you
#   opt in) is copied to a timestamped ".bak-YYYYmmdd-HHMMSS" file in the same
#   config folder, so a bad migration is always reversible by hand.
#
# APPLYING:
#   Blender holds preferences in memory while running and has no stable
#   cross-version operator to hot-reload userpref.blend, so the add-on copies
#   the file and asks you to RESTART Blender.
#
# CONTROLS  (Edit > Preferences > Add-ons > expand "Preferences Migrator"):
#   * "Copy From" dropdown -> pick a source version.
#   * "Also copy startup file" -> include your custom default scene/layout.
#   * Copy button -> back up + copy, then restart.
#
# CAVEAT: copying from a NEWER version into an OLDER one is a downgrade of the
# preference format and may not fully apply. Tested case (4.4 -> 4.2) loaded
# cleanly, but settings that only exist in the newer version are ignored.
# -------------------------------------------------------------------------

import bpy
import os
import re
import shutil
import datetime
from bpy.types import Operator, AddonPreferences
from bpy.props import EnumProperty, BoolProperty

# Keep enum items referenced globally: Blender can garbage-collect
# Python-built enum strings otherwise, which causes UI glitches/crashes.
_enum_cache = []


def _versions_root():
    """Folder that contains every installed version's subfolder."""
    return os.path.dirname(bpy.utils.resource_path('USER'))


def _current_version_name():
    """e.g. '4.4' for the running Blender."""
    return os.path.basename(bpy.utils.resource_path('USER'))


def _version_folders():
    """Return (name, full_path, has_userpref) for each version folder found."""
    root = _versions_root()
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full) and re.match(r"^\d+\.\d+$", name):
            userpref = os.path.join(full, "config", "userpref.blend")
            out.append((name, full, os.path.isfile(userpref)))
    return out


def _source_items(self, context):
    """Dropdown items: other versions that actually have a userpref.blend."""
    global _enum_cache
    current = _current_version_name()
    items = []
    for name, _full, has_pref in _version_folders():
        if name == current or not has_pref:
            continue
        items.append((name, "Blender %s" % name, "Copy preferences from Blender %s" % name))
    if not items:
        items = [("NONE", "No other versions with saved preferences found", "")]
    _enum_cache = items
    return items


class PREFMIG_OT_migrate(Operator):
    bl_idname = "prefmig.migrate"
    bl_label = "Copy Preferences Into This Version"
    bl_description = "Back up the current preferences, then copy them from the chosen version"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        source = prefs.source_version
        if not source or source == "NONE":
            self.report({'ERROR'}, "No source version selected")
            return {'CANCELLED'}

        root = _versions_root()
        src_config = os.path.join(root, source, "config")
        dst_config = os.path.join(bpy.utils.resource_path('USER'), "config")
        src_pref = os.path.join(src_config, "userpref.blend")

        if not os.path.isfile(src_pref):
            self.report({'ERROR'}, "userpref.blend not found in Blender %s" % source)
            return {'CANCELLED'}

        os.makedirs(dst_config, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

        def _copy_with_backup(src_file, filename):
            dst_file = os.path.join(dst_config, filename)
            if os.path.isfile(dst_file):
                shutil.copy2(dst_file, dst_file + ".bak-" + stamp)
            shutil.copy2(src_file, dst_file)

        copied = []
        try:
            _copy_with_backup(src_pref, "userpref.blend")
            copied.append("userpref.blend")
            if prefs.include_startup:
                src_start = os.path.join(src_config, "startup.blend")
                if os.path.isfile(src_start):
                    _copy_with_backup(src_start, "startup.blend")
                    copied.append("startup.blend")
        except Exception as exc:
            self.report({'ERROR'}, "Copy failed: %s" % exc)
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            "Copied %s from Blender %s into %s. Restart Blender to apply (backup saved with .bak- suffix)."
            % (", ".join(copied), source, _current_version_name()),
        )
        return {'FINISHED'}


class PREFMIG_Preferences(AddonPreferences):
    bl_idname = __package__

    source_version: EnumProperty(
        name="Copy From",
        description="Which installed Blender version to copy preferences from",
        items=_source_items,
    )
    include_startup: BoolProperty(
        name="Also copy startup file (startup.blend)",
        description="Include your custom default scene/layout, not just preferences",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(
            text="Copies preferences INTO this version (Blender %s)." % _current_version_name()
        )
        layout.prop(self, "source_version")
        layout.prop(self, "include_startup")
        layout.operator("prefmig.migrate", icon='DUPLICATE')
        box = layout.box()
        box.label(text="Current preferences are backed up automatically (.bak- suffix).", icon='INFO')
        box.label(text="Restart Blender after copying for changes to take effect.", icon='FILE_REFRESH')
        box.label(text="Newer-into-older is a downgrade and may not fully apply.", icon='ERROR')


classes = (PREFMIG_OT_migrate, PREFMIG_Preferences)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
