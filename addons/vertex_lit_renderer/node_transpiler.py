# vertex_lit_renderer/node_transpiler.py
"""
Node -> GLSL transpiler  (SPIKE scope).

Purpose
-------
Walk a Blender material node graph backwards from the surface's base colour
and emit a GLSL function body that computes that colour per fragment, so the
viewport shows procedural / mix / UV-distortion materials *live* instead of the
single flat texture Workbench (and the current engine) samples.

This is the "step-2 spike": prove that a small chain
    Tex Coord (UV) -> Mapping -> Image Texture -> Base Color
transpiles to GLSL in which the Mapping transform is applied to the UVs
*before* the image is sampled. If Mapping scale/location changes the sampled
coordinates, UV distortion shows live and the whole approach is proven.

Supported node subset (spike):
    TEX_COORD           .UV output              -> vUV varying
    MAPPING (POINT)     Location / Rotation.Z / Scale
    TEX_IMAGE           .Color / .Alpha         (sampler bound by engine)
    MIX_RGB / MIX(RGBA) BLEND mode              -> mix(a, b, fac)
    unconnected inputs  -> the socket's default_value as a GLSL literal

Anything unsupported degrades to a visible magenta so the graph never
hard-fails and the unhandled node is obvious on screen.

Output
------
transpile_material(mat) -> TranspileResult:
    .glsl        str          body of `vec4 computeBaseColor(vec2 vUV)`
    .samplers    list[Sampler] (uniform_name, image) the engine must bind
    .ok          bool
    .notes       list[str]    per-node messages (unsupported types, fallbacks)

The module is pure-Python and needs only the bpy *data* API (node trees); it
does NOT import gpu and does NOT need a GPU context, so it is fully testable
headless. Compiling/*displaying* the result is the engine's job (needs a GPU).
"""

from __future__ import annotations

MAGENTA = "vec4(1.0, 0.0, 1.0, 1.0)"


class Sampler:
    __slots__ = ("uniform", "image")

    def __init__(self, uniform, image):
        self.uniform = uniform
        self.image = image


class TranspileResult:
    def __init__(self):
        self.glsl = ""
        self.samplers = []
        self.ok = False
        self.notes = []


# ---------------------------------------------------------------------------
# GLSL literal helpers
# ---------------------------------------------------------------------------

def _f(x):
    """Format a Python float as a GLSL float literal (always has a dot)."""
    s = repr(float(x))
    if "e" in s or "E" in s:          # avoid GLSL-illegal exponent-only forms
        s = "{:.8f}".format(float(x))
    if "." not in s:
        s += ".0"
    return s


def _vec3(seq):
    return "vec3({}, {}, {})".format(_f(seq[0]), _f(seq[1]), _f(seq[2]))


def _vec4_from_rgba(seq):
    a = seq[3] if len(seq) > 3 else 1.0
    return "vec4({}, {}, {}, {})".format(_f(seq[0]), _f(seq[1]), _f(seq[2]), _f(a))


# ---------------------------------------------------------------------------
# Transpiler
# ---------------------------------------------------------------------------

class _Transpiler:
    def __init__(self):
        self.lines = []          # GLSL statement lines (in dependency order)
        self.samplers = []       # Sampler objects
        self.notes = []
        self._sock_var = {}      # id(socket) -> glsl var name holding its value
        self._counter = 0

    def _new_var(self, hint="n"):
        self._counter += 1
        return "n_{}_{}".format(hint, self._counter)

    # -- resolve a node INPUT socket to a GLSL expression ------------------
    def input_expr(self, socket, want="vec4"):
        """Return a GLSL expression (str) for the value arriving at `socket`."""
        if socket.is_linked:
            link = socket.links[0]
            var = self.emit_node(link.from_node, link.from_socket)
            return self._coerce(var, want)
        # unlinked: use the default value
        return self._default_expr(socket, want)

    def _default_expr(self, socket, want):
        val = getattr(socket, "default_value", None)
        try:
            if hasattr(val, "__len__"):
                if len(val) >= 4:
                    lit = _vec4_from_rgba(val)
                elif len(val) == 3:
                    lit = "vec4({}, 1.0)".format(_vec3(val))
                else:
                    lit = "vec4({}, {}, 0.0, 1.0)".format(_f(val[0]), _f(val[1]))
            else:
                f = _f(val if val is not None else 0.0)
                lit = "vec4({}, {}, {}, 1.0)".format(f, f, f)
        except Exception:
            lit = MAGENTA
        return self._coerce(lit, want)

    def _coerce(self, expr, want):
        if want == "vec4":
            return expr
        if want == "vec3":
            return "({}).xyz".format(expr)
        if want == "vec2":
            return "({}).xy".format(expr)
        if want == "float":
            return "({}).x".format(expr)
        return expr

    # -- emit a NODE, return a GLSL var/expr for `out_socket` --------------
    def emit_node(self, node, out_socket):
        key = id(out_socket)
        if key in self._sock_var:
            return self._sock_var[key]

        ntype = node.type
        handler = getattr(self, "_n_" + ntype.lower(), None)
        if handler is None:
            self.notes.append("unsupported node: {} ({})".format(node.name, ntype))
            self._sock_var[key] = MAGENTA
            return MAGENTA

        expr = handler(node, out_socket)
        self._sock_var[key] = expr
        return expr

    # ---- node handlers --------------------------------------------------

    def _n_tex_coord(self, node, out_socket):
        # Spike: only the UV output is meaningful in a raster forward pass.
        name = out_socket.name
        if name == "UV":
            return "vec4(vUV, 0.0, 1.0)"
        # Generated / Object / etc. approximated by UV for now.
        self.notes.append("TEX_COORD.{} approximated as UV".format(name))
        return "vec4(vUV, 0.0, 1.0)"

    def _n_mapping(self, node, out_socket):
        vec = self.input_expr(node.inputs.get("Vector"), "vec3")
        loc = self.input_expr(node.inputs.get("Location"), "vec3")
        rot = self.input_expr(node.inputs.get("Rotation"), "vec3")
        scl = self.input_expr(node.inputs.get("Scale"), "vec3")
        vt = getattr(node, "vector_type", "POINT")

        v = self._new_var("map")
        # POINT: p' = R(rot) * (scale * p) + location   (TEXTURE inverts; spike does POINT)
        # Rotation about Z only for the spike (UV plane); X/Y rot rarely used on UVs.
        self.lines.append("vec3 {sc} = {scl} * {vec};".format(sc=v + "_s", scl=scl, vec=vec))
        self.lines.append("float {c} = cos(({rot}).z);".format(c=v + "_c", rot=rot))
        self.lines.append("float {s} = sin(({rot}).z);".format(s=v + "_sn", rot=rot))
        self.lines.append(
            "vec3 {v} = vec3("
            "{sc}.x*{c} - {sc}.y*{s}, "
            "{sc}.x*{s} + {sc}.y*{c}, "
            "{sc}.z) + {loc};".format(
                v=v, sc=v + "_s", c=v + "_c", s=v + "_sn", loc=loc)
        )
        if vt == "TEXTURE":
            self.notes.append("MAPPING vector_type=TEXTURE approximated as POINT")
        return "vec4({}, 1.0)".format(v)

    def _n_tex_image(self, node, out_socket):
        img = getattr(node, "image", None)
        coords = self.input_expr(node.inputs.get("Vector"), "vec2") \
            if node.inputs.get("Vector") else "vUV"
        if img is None:
            self.notes.append("TEX_IMAGE '{}' has no image".format(node.name))
            return MAGENTA
        uni = "uTx_{}".format(len(self.samplers))
        self.samplers.append(Sampler(uni, img))
        var = self._new_var("img")
        self.lines.append("vec4 {v} = texture({u}, {c});".format(v=var, u=uni, c=coords))
        if out_socket.name == "Alpha":
            return "vec4(vec3({v}.a), 1.0)".format(v=var)
        return var

    def _n_mix_rgb(self, node, out_socket):
        return self._mix_common(node, fac_in="Fac", a_in="Color1", b_in="Color2")

    def _n_mix(self, node, out_socket):
        # New unified Mix node (RGBA data type)
        if getattr(node, "data_type", "RGBA") != "RGBA":
            self.notes.append("MIX data_type={} approximated as RGBA".format(
                getattr(node, "data_type", "?")))
        # New node socket names: Factor, A, B  (may be indexed duplicates)
        a_in = "A" if node.inputs.get("A") else "Color1"
        b_in = "B" if node.inputs.get("B") else "Color2"
        return self._mix_common(node, fac_in="Factor", a_in=a_in, b_in=b_in)

    def _mix_common(self, node, fac_in, a_in, b_in):
        fac = self.input_expr(node.inputs.get(fac_in), "float") if node.inputs.get(fac_in) else "1.0"
        a = self.input_expr(node.inputs.get(a_in), "vec4")
        b = self.input_expr(node.inputs.get(b_in), "vec4")
        var = self._new_var("mix")
        self.lines.append("vec4 {v} = mix({a}, {b}, clamp({f}, 0.0, 1.0));".format(
            v=var, a=a, b=b, f=fac))
        return var

    def _n_bsdf_principled(self, node, out_socket):
        # We never render the BSDF itself; we read its Base Color input.
        base = node.inputs.get("Base Color") or node.inputs.get("Color")
        if base is None:
            return "vec4(0.8, 0.8, 0.8, 1.0)"
        return self.input_expr(base, "vec4")

    def _n_emission(self, node, out_socket):
        col = node.inputs.get("Color")
        return self.input_expr(col, "vec4") if col else "vec4(1.0)"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _find_base_socket(mat):
    """Return the socket whose value is the surface base colour, or None."""
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return None
    out = None
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True):
            out = n
            break
    if out is None:
        for n in nt.nodes:
            if n.type == "OUTPUT_MATERIAL":
                out = n
                break
    if out is None:
        return None
    surf = out.inputs.get("Surface")
    if surf and surf.is_linked:
        src = surf.links[0].from_node
        if src.type == "BSDF_PRINCIPLED":
            bc = src.inputs.get("Base Color")
            return bc if bc else None
        if src.type == "EMISSION":
            return src.inputs.get("Color")
        # Unknown surface shader: try a 'Color'/'Base Color' input on it.
        return src.inputs.get("Base Color") or src.inputs.get("Color")
    return surf


def transpile_material(mat):
    res = TranspileResult()
    if not mat or not getattr(mat, "use_nodes", False):
        res.notes.append("material has no nodes")
        res.glsl = "vec4 computeBaseColor(vec2 vUV) {{ return {}; }}".format(
            _vec4_from_rgba(list(getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0)))
                            ) if mat else "vec4(0.8,0.8,0.8,1.0)")
        res.ok = True
        return res

    base = _find_base_socket(mat)
    t = _Transpiler()
    if base is None:
        res.notes.append("no base-colour socket found; using grey")
        body_expr = "vec4(0.8, 0.8, 0.8, 1.0)"
    else:
        body_expr = t.input_expr(base, "vec4")

    body = "\n    ".join(t.lines)
    res.glsl = (
        "vec4 computeBaseColor(vec2 vUV) {\n"
        + ("    " + body + "\n" if body else "")
        + "    return {};\n".format(body_expr)
        + "}"
    )
    res.samplers = t.samplers
    res.notes.extend(t.notes)
    res.ok = True
    return res
