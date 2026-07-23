# Reference Grid Drop

Blender addon for getting many reference images into the viewport in one action.

Drop any number of image files onto the 3D viewport at once. A small dialog asks
how many images per row, how large each one should be, and how much gap to leave.
The images are then created as reference-image empties, laid out in a centered
grid that faces the current view.

## Requirements

- Blender 4.4 (built on the `FileHandler` API, which needs 4.1 or newer)

## Install

1. Edit > Preferences > Add-ons
2. Top-right dropdown > Install from Disk
3. Select `reference_grid_drop.py`
4. Enable the checkbox

## Usage

**Drag and drop** — select multiple images in your file manager, drag them onto
the 3D viewport, set the options in the popup, confirm.

**Menu fallback** — `Add > Image > Reference Grid (multi-image)...` opens a
multi-select file browser for the same result.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| Images Per Row | 4 | How many images before the layout wraps to a new row |
| Image Size | 2.0 | Longest side of each image, in Blender units |
| Gap | 0.3 | Space between images, in Blender units |

## Behaviour notes

- Each image becomes an image empty, the same object type produced by
  `Shift+A > Image > Reference`.
- Orientation is taken from the viewport rotation at the moment of the drop, so
  the whole grid sits flat in the view plane.
- The grid is centered on the point the view is orbiting around.
- Aspect ratio is preserved: `Image Size` sets the longest side, the short side
  scales down to match the source image.
- Empties are set to display in both perspective and orthographic, with alpha
  enabled and axis-aligned-only display turned off, so they stay visible while
  orbiting.
- Each object is named after its source filename without the extension.
- Newly created empties are left selected, so they can be moved or parented as a
  group straight after the drop.

## Supported formats

png, jpg, jpeg, tif, tiff, exr, hdr, webp, bmp, tga, dds, psd

## Troubleshooting

Failures are printed to the system console (Window > Toggle System Console) with
a `[Reference Grid]` prefix. The operator reports how many images were added and
how many failed.

## Status

Tested in Blender 4.4 and working.
