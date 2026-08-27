# String Engine — Node Canvas & Interaction

How nodes render, how you add/move/wire them, and how the graph shares the existing
canvas. Blender's Shader Editor + Geometry Nodes are the reference throughout.

## 1. Merged canvas & coordinate space

One infinite world plane, one camera (`view.ox/oy/z` — already exists).
- The **sim box** occupies a fixed world rect (`0..S.W , 0..S.H`), rendered as today.
- **Nodes live outside the box** (default: to the right / below). Node positions are
  world coordinates, so they pan and zoom with everything else.
- Zoom out -> box + graph both visible. Pan -> focus either. No separate editor window.

### Hit-testing (the free interaction split)
At the TOP of the existing pointer handler, branch on where the pointer-down landed:
- inside the sim box -> existing sim tools (draw / grab / cut / pan) — unchanged.
- outside the box -> graph interaction (node/socket/wire/pan).
Middle-mouse / space-drag = pan everywhere (shared). This means the graph adds a second
handler path, not a mode switch. Wheel = zoom everywhere.

Edge case: nodes should not be draggable INTO the sim box (or if they are, they are just
visually over it — never interpreted as geometry). Keep a small dead-margin around the
box so you can't accidentally start a stroke when aiming at a node near the edge.

## 2. Node rendering (a node "card")

Rounded rect, drawn in world space (scales with zoom; clamp label legibility with a
min font size so zoomed-out nodes stay readable or collapse to a dot).

```
+-----------------------------+   <- header: category colour + title (+ collapse caret)
| (o) in A        Material    |
| (o) in B     colour [#tea]  |   <- body: input sockets (left), inline widgets,
|              radius [==o==]  |      output sockets (right)
|              stiff  [=o===]  |
|                     out (o) |
+-----------------------------+
```

- **Header** carries the category colour (Generators / Modifiers / Attributes /
  Simulation / Utility / Input each get a hue) + the node title. Click-drag header = move.
- **Sockets**: small dots on the vertical edges — inputs left, outputs right. Colour =
  wire type (teal geo / grey value / blue behaviour). Shape encodes structure, following
  Blender's 2025 socket-shape pass: circle = single value/geometry; **diamond = field**;
  diamond-with-hole = accepts field OR literal. A param with no wire shows its inline
  widget; wire it and the widget hides.
- **Inline widgets**: sliders, number fields, colour swatches, toggles, dropdowns — the
  same controls as today's panel, just hosted on the node. Reuse existing widget code.
- **Collapse**: caret hides unconnected sockets/widgets (Blender's node collapse), so a
  finished graph reads as clean boxes.
- **Selection**: click = select (highlight border); box-drag on empty canvas = rubber-band
  select; Delete/X removes; drag moves the selection.

## 3. Sockets & wires (noodles)

- **Noodle** = bezier from output socket to input socket. Colour = source socket's type.
  **Dashed** when it carries a field (Blender's convention for field vs data flow).
- **Create**: press on an output socket, drag, release on a compatible input -> connect.
  Release on empty canvas -> open the Add menu filtered to nodes that accept this type
  (Blender "link-drag-search"). Type-incompatible targets are dimmed while dragging.
- **Single-input rule**: an input socket holds one wire (new drop replaces old); an output
  fans out to many. Exceptions: **multi-input** sockets (Merge geometry, Output
  behaviours) accept many and show a stacked connector, like Blender's Join Geometry.
- **Reroute**: drop a Reroute node on a noodle to bend it; 1 in / many out.
- **Disconnect**: drag a wire off its input to empty, or Ctrl-drag across noodles to cut
  (Blender's cut-links gesture).

## 4. Add menu (Shift+A)

- **Shift+A** at cursor opens the Add menu; the node is placed where the menu opened.
- **Search-as-you-type**: the menu starts in search; typing filters across all nodes by
  name (Blender behaviour: type two letters, Enter places the top hit). Fast path for
  power users.
- **Categorised submenus** for browsing: Generators / Modifiers / Attributes / Simulation
  / Utility / Input / (later) Groups. Mirrors Blender's Shader/Geo add menu.
- **Link-drag-search**: dragging a wire to empty opens the same menu pre-filtered to
  compatible nodes, and auto-connects the placed node.

## 5. Organisation (later, but design-compatible now)

- **Node groups** (Ctrl+G): collapse a selection into one node with auto group-input /
  group-output sockets; appears under a "Groups" menu; Tab to enter/exit. This is how
  demo-scene presets and reusable sub-graphs happen. Keep the socket model group-ready
  from day one even if grouping ships late.
- **Frames**: labelled coloured background boxes to group nodes visually.
- **Labels/colours** per node (Blender N-panel) for readability.

## 6. Rendering & perf notes (vanilla, single-file)

- Draw nodes on the SAME 2D canvas pass as the sim overlays (they share the camera).
  Node bodies are cheap rects+text; noodles are cheap beziers. Redraw only on
  dirty (pan/zoom/drag/edit) — the engine already gates render on `window.RD`.
- Hit-testing: keep an array of node rects in world space; for pointer events, transform
  the cursor to world coords (existing `canvasXY`) and test. Sockets get a small hit
  radius. For large graphs, a coarse spatial bucket (already used for collision) can
  accelerate, but not needed early.
- Text legibility across zoom: clamp font to a screen-space min; below a zoom threshold,
  render nodes as coloured dots with just the title (Blender-like LOD).

## 7. What NOT to reinvent

- Camera/pan/zoom: reuse `view` + `canvasXY`.
- Widgets: reuse the existing slider/toggle/colour controls; host them on nodes.
- Dirty-render gating: reuse `window.RD`.
- Serialization: extend the existing scene JSON with a `graph` block (nodes + wires +
  positions). Demo scenes ship as graph JSON presets.
