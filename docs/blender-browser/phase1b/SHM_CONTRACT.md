# Phase 1b — Shared-Memory + Control-Socket Contract (v2: helper-side FLOAT convert)

Language-neutral keystone. Blender add-on (Py 3.11) and helper (cefpython spike / C++ CEF
later) agree only on this. **v2 change (architecture.md §18.1):** the helper now does the
uint8→FLOAT convert (and BGRA→RGBA swap) and writes **normalized FLOAT RGBA** into shared
memory, so Blender's main thread only wraps + uploads + draws. This keeps Blender
responsive (the convert is 24–43% of a core during video — must not sit on the main thread)
and distributes load across processes. Cost: SHM is FLOAT (4× size; fine ≤1440p).

## Ownership & lifecycle (Windows)
- **Blender add-on CREATES and OWNS** the segment (`shared_memory.SharedMemory(create=True)`);
  holds the reference for the whole session so it survives helper restarts.
- **Helper ATTACHES by name** (`create=False`). On helper crash the segment persists;
  watchdog respawns the helper and it re-attaches the same name.
- Name: `blndr_browser_<uuid4hex>`, passed as a launch arg. Windows frees the mapping when
  the last handle closes — no manual unlink (Blender holds it).

## Memory layout (little-endian)
```
HEADER (64 bytes, offset 0)
  0    char[4] magic        b"BLBR"
  4    u32     version      = 2
  8    u32     width        pixels
  12   u32     height       pixels
  16   u32     stride       = width * 16   (RGBA32F = 16 bytes/pixel)
  20   u32     pix_format   1 = RGBA32F normalized (helper converts; see §18.1)
  24   u32     active       0/1 — slot holding the latest COMPLETE frame
  28   u32     sequence     bumped when a new complete frame is published
  32   u32     dirty_x
  36   u32     dirty_y
  40   u32     dirty_w
  44   u32     dirty_h
  48   u32     slot_bytes   = width * height * 16   (RGBA32F: 4 floats/pixel)
  52   u32[3]  reserved
SLOT 0  at offset 64
SLOT 1  at offset 64 + slot_bytes
TOTAL = 64 + 2 * slot_bytes
```
Double-buffered: producer writes one slot while consumer reads the other.

## Frame protocol
**Producer (helper OnPaint), per frame:**
1. `write = 1 - active`
2. **convert:** OnPaint gives BGRA uint8 → reorder to RGBA + normalize to float32 (0..1)
3. write the FLOAT RGBA bytes (width*height*16) into SLOT[write]
4. set dirty rect
5. **publish last:** set `active = write`, then `sequence += 1`

**Consumer (Blender frame pump), per timer tick:**
1. read `sequence`; if unchanged, do nothing
2. read `active`; take a float view of SLOT[active] (`np.frombuffer(buf, float32, count=w*h*4,
   offset=...)` — no copy, no convert), wrap as `gpu.types.Buffer('FLOAT', ...)`, upload to a
   `GPUTexture(format='RGBA8')`, draw. **No CPU convert on the main thread.**
3. record the sequence as last-seen.

Single-producer/single-consumer; publishing `active` before bumping `sequence` makes it
tear-free without a mutex for the spike.

## Resize
Spike: width/height FIXED at open. Resize = tear down + recreate at new size. (Dynamic
resize is Phase 2.)

## Control socket
- Transport: localhost TCP (`127.0.0.1:<port>`). Framing: 4-byte big-endian length + UTF-8 JSON.
- **Blender→helper:** `navigate{url}`, `mouse_move{x,y}`, `mouse_button{x,y,button,down,clicks}`,
  `wheel{x,y,dx,dy}`, `key{down,vk,char,mods}`, `focus{on}`, `set_clipboard{text}`,
  `get_clipboard`, `reload`, `back`, `forward`, `shutdown`.
- **Helper→Blender:** `title{text}`, `url{text}`, `loading{state}`, `cursor{kind}`,
  `clipboard{text}`, `ack` / `error{msg}`.
- `mods` = CEF EVENTFLAG bits: SHIFT 1<<1, CONTROL 1<<2, ALT 1<<3, COMMAND 1<<7.
- Mouse/key calls MUST be posted to CEF's UI thread in the helper, not called from the
  socket thread.
