# Blender 4.4.3 (Linux x64)

Stored as split chunks. To reassemble and extract:

```bash
cat blender-4_4_3-linux-x64.part_aa \
    blender-4_4_3-linux-x64.part_ab \
    blender-4_4_3-linux-x64.part_ac \
    blender-4_4_3-linux-x64.part_ad > blender-4_4_3-linux-x64.tar.xz

tar -xf blender-4_4_3-linux-x64.tar.xz
./blender-4.4.3-linux-x64/blender
```

Tested working: `blender --version` returns 4.4.3 build 802179c51ccc
