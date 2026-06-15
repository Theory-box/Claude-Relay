# Phase 1b — Shared-Memory + Control-Socket Contract

This is the **language-neutral keystone**. The Blender add-on (Python 3.11) and the
helper (cefpython spike now; native C++ CEF later) agree only on this contract — neither
side knows the other's language. Get this right and the C++ helper drops in later without
touching the Blender side.

## Ownership & lifecycle (Windows)
- **Blender add-on CREATES and OWNS** the shared-memory segment
  (`multiprocessing.shared_memory.SharedMemory(create=True, ...)`). It holds the reference
  for the whole session, so the mapping survives helper restarts.
- **Helper ATTACHES by name** (`create=False`). On crash, the segment persists (Blender
  still holds it); the watchdog respawns the helper and it re-attaches the same name.
- Segment name: `blndr_browser_<uuid4hex>`, passed to the helper as a launch arg.
- On Windows the OS frees the mapping when the last handle closes — no manual unlink.

## Memory layout (little-endian)
```
HEADER (64 bytes, at offset 0)
  off  type    field        notes
  0    char[4] magic        b"BLBR"
  4    u32     version      = 1
  8    u32     width        pixels
  12   u32     height       pixels
  16   u32     stride       = width * 4
  20   u32     pix_format   0 = BGRA8 (CEF OnPaint native order)
  24   u32     active       0 or 1 — slot holding the latest COMPLETE frame
  28   u32     sequence     incremented when a new complete frame is published
  32   u32     dirty_x
  36   u32     dirty_y
  40   u32     dirty_w
  44   u32     dirty_h
  48   u32     slot_bytes   = width * height * 4
  52   u32[3]  reserved
SLOT 0  at offset 64
SLOT 1  at offset 64 + slot_bytes
TOTAL size = 64 + 2 * slot_bytes
```
Double-buffered: two slots so the producer writes one while the consumer reads the other.

## Frame protocol (producer = helper, consumer = Blender)
**Producer (helper OnPaint), per frame:**
1. `write = 1 - active`  (the slot NOT currently being read)
2. copy the BGRA buffer into SLOT[write]
3. set dirty_x/y/w/h
4. **publish last:** set `active = write`, then `sequence += 1`
   (write `active` before bumping `sequence` so a consumer that sees the new sequence
   always reads the just-finished slot).

**Consumer (Blender frame pump), per timer tick:**
1. read `sequence`; if unchanged since last tick, do nothing
2. read `active`, then read SLOT[active] (width*height*4 BGRA bytes)
3. record the sequence as "last seen"

This is a single-producer/single-consumer scheme; the publish order makes it tear-free
without a mutex for the spike. (If a race ever shows up under load, add a 1-byte
per-slot "writing" flag; not expected to be needed.)

## Resize
For the spike, width/height are FIXED at browser-open time. A resize = tear down the
segment + helper and recreate at the new size. (Dynamic in-place resize is a Phase-2
nicety, not needed to prove the pipe.)

## Pixel format note
Helper writes **BGRA8** (CEF's native OnPaint order). Blender must present RGBA. For the
spike the add-on reorders BGRA→RGBA on the CPU during the mandatory uint8→float32 convert
(4.4 forces FLOAT upload — see architecture.md §15/§17). Optimization (later): keep BGRA
and swizzle `.bgra` in a custom shader to avoid the CPU reorder.

## Control socket (events/commands)
- Transport: localhost TCP (`127.0.0.1:<port>`), port passed to helper as a launch arg.
- Framing: 4-byte big-endian length prefix + UTF-8 JSON body.
- **Blender → helper:** `{"t":"navigate","url":...}`, `{"t":"mouse_move","x":,"y":}`,
  `{"t":"mouse_button","x":,"y":,"button":"left|right|middle","down":bool,"clicks":1}`,
  `{"t":"wheel","x":,"y":,"dx":,"dy":}`, `{"t":"key","down":bool,"vk":int,"char":str|null,"mods":int}`,
  `{"t":"focus","on":bool}`, `{"t":"set_clipboard","text":...}`, `{"t":"get_clipboard"}`,
  `{"t":"reload"}`, `{"t":"back"}`, `{"t":"forward"}`, `{"t":"shutdown"}`.
- **Helper → Blender:** `{"t":"title","text":...}`, `{"t":"url","text":...}`,
  `{"t":"loading","state":bool}`, `{"t":"cursor","kind":...}`, `{"t":"clipboard","text":...}`,
  `{"t":"ack"}` / `{"t":"error","msg":...}`.
- `mods` bitfield matches CEF EVENTFLAG_*: SHIFT=1<<1, CONTROL=1<<2, ALT=1<<3, COMMAND=1<<7
  (values per cef; confirm against the cefpython constants in the helper).
- Mouse/key calls MUST be marshalled onto CEF's UI thread in the helper (post a task);
  do not call them directly from the socket thread.
