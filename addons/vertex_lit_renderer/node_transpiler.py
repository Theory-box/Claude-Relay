# vertex_lit_renderer/node_transpiler.py
"""
Node -> GLSL transpiler.

Walks a material node graph back from the surface base colour and emits a GLSL
`computeBaseColor(vec2 vUV)` body, so procedural / mix / UV-distortion materials
preview live in the viewport instead of the single flat texture Workbench (and
the legacy engine path) samples.

Two design pillars:

1. CONSTANTS ARE UNIFORMS, NOT LITERALS.
   Every unlinked input's default_value (Mapping Scale/Location/Rotation, Mix
   factor, colours, Value/RGB nodes...) is emitted as a `uP_N` uniform and
   recorded in `.params`. The engine reads the live value each draw and sets the
   uniform. => dragging a slider changes a uniform, it does NOT recompile the
   shader. The shader only recompiles when graph *structure* changes (see
   topo_signature).

2. STRUCTURE-ONLY SIGNATURE.
   topo_signature(mat) hashes node types + names + operation enums + links +
   image assignments, but NOT tweakable values. The engine reuses the compiled
   program while the signature is unchanged.

Supported nodes:
    TEX_COORD(.UV), MAPPING(POINT), TEX_IMAGE, RGB, VALUE,
    MIX_RGB(blend types), MIX(RGBA), MATH(many ops), VECT_MATH(core ops),
    MAP_RANGE(linear), CLAMP, HUE_SAT, GAMMA, BRIGHTCONTRAST, INVERT,
    SEPARATE/COMBINE (Color/RGB/XYZ), VALTORGB(ColorRamp linear/constant/ease),
    BSDF_PRINCIPLED/EMISSION (read their colour input; never rendered as closures).
Unsupported nodes degrade to magenta (visible, non-fatal) and are noted.

Pure-Python (bpy *data* API only, no gpu) => fully testable headless.
"""

from __future__ import annotations

import re as _re

MAGENTA = "vec4(1.0, 0.0, 1.0, 1.0)"

# GLSL helpers injected once per fragment (cheap; compiler drops unused).
HELPERS = """
vec3 _rgb2hsv(vec3 c){
    vec4 K = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0*d + e)), d / (q.x + e), q.x);
}
vec3 _hsv2rgb(vec3 c){
    vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}
float _sdiv(float a, float b){ return (b == 0.0) ? 0.0 : a / b; }
vec3 _overlay(vec3 a, vec3 b){
    return mix(2.0*a*b, vec3(1.0)-2.0*(vec3(1.0)-a)*(vec3(1.0)-b), step(vec3(0.5), a));
}
vec3 _softlight(vec3 a, vec3 b){
    vec3 lo = 2.0*a*b + a*a*(vec3(1.0)-2.0*b);
    vec3 hi = sqrt(max(a,vec3(0.0)))*(2.0*b-vec3(1.0)) + 2.0*a*(vec3(1.0)-b);
    return mix(lo, hi, step(vec3(0.5), b));
}
vec3 _bl_hue(vec3 a, vec3 b){ vec3 x=_rgb2hsv(a), y=_rgb2hsv(b); return _hsv2rgb(vec3(y.x, x.y, x.z)); }
vec3 _bl_sat(vec3 a, vec3 b){ vec3 x=_rgb2hsv(a), y=_rgb2hsv(b); return _hsv2rgb(vec3(x.x, y.y, x.z)); }
vec3 _bl_col(vec3 a, vec3 b){ vec3 x=_rgb2hsv(a), y=_rgb2hsv(b); return _hsv2rgb(vec3(y.x, y.y, x.z)); }
vec3 _bl_val(vec3 a, vec3 b){ vec3 x=_rgb2hsv(a), y=_rgb2hsv(b); return _hsv2rgb(vec3(x.x, x.y, y.z)); }
"""


class Sampler:
    __slots__ = ("uniform", "image")
    def __init__(self, uniform, image):
        self.uniform = uniform; self.image = image


class Param:
    """A tweakable constant promoted to a uniform, read live from the node tree."""
    __slots__ = ("uniform", "want", "node_name", "kind", "index")
    def __init__(self, uniform, want, node_name, kind, index=-1):
        self.uniform = uniform      # GLSL uniform name
        self.want = want            # 'float'|'vec2'|'vec3'|'vec4'
        self.node_name = node_name
        self.kind = kind            # 'input' | 'rgb' | 'value'
        self.index = index          # input socket index (kind='input')

    def gltype(self):
        return self.want

    def _raw(self, nt):
        node = nt.nodes.get(self.node_name) if nt else None
        if node is None:
            return 0.0
        try:
            if self.kind == "input":
                return node.inputs[self.index].default_value
            if self.kind == "rgb":
                return node.outputs[0].default_value
            if self.kind == "value":
                return node.outputs[0].default_value
        except Exception:
            return 0.0
        return 0.0

    def value(self, nt):
        """Return the value packed to `want` arity (float or tuple)."""
        dv = self._raw(nt)
        seq = hasattr(dv, "__len__")
        def g(i, default=0.0):
            try: return float(dv[i]) if seq else float(dv)
            except Exception: return default
        if self.want == "float":
            return g(0) if seq else float(dv)
        if self.want == "vec2":
            return (g(0), g(1))
        if self.want == "vec3":
            return (g(0), g(1), g(2))
        # vec4
        return (g(0), g(1), g(2), g(3, 1.0))


class TranspileResult:
    def __init__(self):
        self.glsl = ""
        self.samplers = []
        self.params = []
        self.param_decls = []
        self.ok = False
        self.needs_fallback = False   # True => engine should use the legacy texture path
        self.notes = []


# ---------------------------------------------------------------------------
def _f(x):
    s = repr(float(x))
    if "e" in s or "E" in s: s = "{:.8f}".format(float(x))
    if "." not in s: s += ".0"
    return s

_GLTYPE = {"float": "float", "vec2": "vec2", "vec3": "vec3", "vec4": "vec4"}


class _Transpiler:
    def __init__(self):
        self.lines = []
        self.samplers = []
        self.params = []
        self.param_decls = []
        self.notes = []
        self._sock_var = {}
        self._var_type = {}     # glsl var name -> 'float'|'vec2'|'vec3'|'vec4'
        self._param_type = {}   # uniform name  -> same
        self._counter = 0

    _DECL = _re.compile(r'^(vec4|vec3|vec2|float)\s+(n_\w+)\s*=')

    def _line(self, s):
        m = self._DECL.match(s)
        if m:
            self._var_type[m.group(2)] = m.group(1)
        self.lines.append(s)

    def _typeof(self, expr):
        if expr in self._var_type: return self._var_type[expr]
        if expr in self._param_type: return self._param_type[expr]
        for t in ("vec4(", "vec3(", "vec2("):
            if expr.startswith(t): return t[:-1]
        if expr.startswith("float(") or expr.startswith("_sdiv(") or expr.startswith("dot("):
            return "float"
        # bare numeric literal
        try:
            float(expr); return "float"
        except Exception:
            return "vec4"

    def _new_var(self, hint="n"):
        self._counter += 1
        return "n_{}_{}".format(hint, self._counter)

    # -- value of a node INPUT socket -> GLSL expr -------------------------
    def input_expr(self, node, socket, want="vec4"):
        if socket is None:
            return self._zero(want)
        if socket.is_linked:
            link = socket.links[0]
            var = self.emit_node(link.from_node, link.from_socket)
            return self._coerce(var, want)
        return self._uniform_default(node, socket, want)

    def _zero(self, want):
        return {"float": "0.0", "vec2": "vec2(0.0)",
                "vec3": "vec3(0.0)", "vec4": "vec4(0.0,0.0,0.0,1.0)"}[want]

    def _uniform_default(self, node, socket, want):
        name = "uP_{}".format(len(self.params) + 1)
        try:
            idx = list(node.inputs).index(socket)
        except Exception:
            idx = -1
        self.params.append(Param(name, want, node.name, "input", idx))
        self.param_decls.append("uniform {} {};".format(_GLTYPE[want], name))
        self._param_type[name] = want
        return name

    def _coerce(self, expr, want):
        src = self._typeof(expr)
        if src == want:
            return expr
        if want == "vec4":
            if src == "vec3": return "vec4({}, 1.0)".format(expr)
            if src == "vec2": return "vec4({}, 0.0, 1.0)".format(expr)
            if src == "float": return "vec4(vec3({}), 1.0)".format(expr)
            return expr
        if want == "vec3":
            if src == "vec4": return "({}).xyz".format(expr)
            if src == "vec2": return "vec3({}, 0.0)".format(expr)
            if src == "float": return "vec3({})".format(expr)
            return expr
        if want == "vec2":
            if src in ("vec3", "vec4"): return "({}).xy".format(expr)
            if src == "float": return "vec2({})".format(expr)
            return expr
        if want == "float":
            if src in ("vec2", "vec3", "vec4"): return "({}).x".format(expr)
            return expr
        return expr

    # -- emit a NODE -------------------------------------------------------
    def emit_node(self, node, out_socket):
        key = id(out_socket)
        if key in self._sock_var:
            return self._sock_var[key]
        handler = getattr(self, "_n_" + node.type.lower(), None)
        if handler is None:
            self.notes.append("unsupported node: {} ({})".format(node.name, node.type))
            self._sock_var[key] = MAGENTA
            return MAGENTA
        expr = handler(node, out_socket)
        self._sock_var[key] = expr
        return expr

    # =================== node handlers ===================================

    def _n_tex_coord(self, node, out):
        if out.name not in ("UV",):
            self.notes.append("TEX_COORD.{} approximated as UV".format(out.name))
        return "vec4(vUV, 0.0, 1.0)"

    def _n_uvmap(self, node, out):
        return "vec4(vUV, 0.0, 1.0)"

    def _n_mapping(self, node, out):
        vec = self.input_expr(node, node.inputs.get("Vector"), "vec3")
        loc = self.input_expr(node, node.inputs.get("Location"), "vec3")
        rot = self.input_expr(node, node.inputs.get("Rotation"), "vec3")
        scl = self.input_expr(node, node.inputs.get("Scale"), "vec3")
        v = self._new_var("map")
        self._line("vec3 {s} = {scl} * {vec};".format(s=v + "_s", scl=scl, vec=vec))
        self._line("float {c} = cos(({r}).z);".format(c=v + "_c", r=rot))
        self._line("float {s} = sin(({r}).z);".format(s=v + "_sn", r=rot))
        self._line(
            "vec3 {v} = vec3({s}.x*{c} - {s}.y*{sn}, {s}.x*{sn} + {s}.y*{c}, {s}.z) + {loc};"
            .format(v=v, s=v + "_s", c=v + "_c", sn=v + "_sn", loc=loc))
        if getattr(node, "vector_type", "POINT") == "TEXTURE":
            self.notes.append("MAPPING vector_type=TEXTURE approximated as POINT")
        return "vec4({}, 1.0)".format(v)

    def _n_tex_image(self, node, out):
        img = getattr(node, "image", None)
        vsock = node.inputs.get("Vector")
        # An unconnected Vector input on an Image Texture uses the mesh UV map in
        # Blender — NOT the socket's (0,0,0) default. Treating it as a constant
        # samples every fragment at one texel => the whole object looks like a flat
        # colour. Only follow the Vector input when it's actually linked.
        if vsock is not None and vsock.is_linked:
            coords = self.input_expr(node, vsock, "vec2")
        else:
            coords = "vUV"
        if img is None:
            self.notes.append("TEX_IMAGE '{}' has no image".format(node.name))
            return MAGENTA
        uni = "uTx_{}".format(len(self.samplers))
        self.samplers.append(Sampler(uni, img))
        var = self._new_var("img")
        self._line("vec4 {v} = texture({u}, {c});".format(v=var, u=uni, c=coords))
        if out.name == "Alpha":
            return "vec4(vec3({v}.a), 1.0)".format(v=var)
        return var

    def _n_rgb(self, node, out):
        name = "uP_{}".format(len(self.params) + 1)
        self.params.append(Param(name, "vec4", node.name, "rgb"))
        self.param_decls.append("uniform vec4 {};".format(name))
        self._param_type[name] = "vec4"
        return name

    def _n_value(self, node, out):
        name = "uP_{}".format(len(self.params) + 1)
        self.params.append(Param(name, "float", node.name, "value"))
        self.param_decls.append("uniform float {};".format(name))
        self._param_type[name] = "float"
        return "vec4(vec3({0}), 1.0)".format(name) if out.type == "RGBA" else name

    # ---- Mix ----
    def _n_mix_rgb(self, node, out):
        fac = self.input_expr(node, node.inputs.get("Fac"), "float")
        a = self.input_expr(node, node.inputs.get("Color1"), "vec4")
        b = self.input_expr(node, node.inputs.get("Color2"), "vec4")
        return self._blend(getattr(node, "blend_type", "MIX"), fac, a, b,
                           getattr(node, "use_clamp", False))

    def _n_mix(self, node, out):
        if getattr(node, "data_type", "RGBA") != "RGBA":
            self.notes.append("MIX data_type approximated as RGBA")
        col = [s for s in node.inputs if s.type == "RGBA"]
        fac_s = node.inputs.get("Factor")
        a = self.input_expr(node, col[0] if len(col) > 0 else None, "vec4")
        b = self.input_expr(node, col[1] if len(col) > 1 else None, "vec4")
        fac = self.input_expr(node, fac_s, "float")
        return self._blend(getattr(node, "blend_type", "MIX"), fac, a, b,
                           getattr(node, "clamp_result", False))

    def _blend(self, mode, fac, a, b, clamp):
        var = self._new_var("mix")
        # Compute the two colours once into vec3 temporaries (avoids re-sampling
        # if an input is a texture and keeps the blend formulas readable).
        self._line("vec3 {v}a = ({a}).rgb;".format(v=var, a=a))
        self._line("vec3 {v}b = ({b}).rgb;".format(v=var, b=b))
        A = var + "a"; B = var + "b"
        f = "clamp({}, 0.0, 1.0)".format(fac)
        ONE = "vec3(1.0)"
        table = {
            "MIX":          "{B}",
            "ADD":          "{A}+{B}",
            "MULTIPLY":     "{A}*{B}",
            "SUBTRACT":     "{A}-{B}",
            "SCREEN":       ONE+"-("+ONE+"-{A})*("+ONE+"-{B})",
            "DIVIDE":       "{A}/max({B},vec3(1e-6))",
            "DIFFERENCE":   "abs({A}-{B})",
            "DARKEN":       "min({A},{B})",
            "LIGHTEN":      "max({A},{B})",
            "OVERLAY":      "_overlay({A},{B})",
            "SOFT_LIGHT":   "_softlight({A},{B})",
            "LINEAR_LIGHT": "{A}+2.0*{B}-"+ONE,
            "DODGE":        "{A}/max("+ONE+"-{B},vec3(1e-6))",
            "BURN":         ONE+"-("+ONE+"-{A})/max({B},vec3(1e-6))",
            "EXCLUSION":    "{A}+{B}-2.0*{A}*{B}",
            "HUE":          "_bl_hue({A},{B})",
            "SATURATION":   "_bl_sat({A},{B})",
            "COLOR":        "_bl_col({A},{B})",
            "VALUE":        "_bl_val({A},{B})",
        }
        tmpl = table.get(mode)
        if tmpl is None:
            self.notes.append("MIX blend '{}' approximated as MIX".format(mode))
            tmpl = "{B}"
        bl = tmpl.format(A=A, B=B)
        expr = "vec4(mix({A}, {bl}, {f}), ({a}).a)".format(A=A, bl=bl, f=f, a=a)
        if clamp:
            expr = "clamp({}, 0.0, 1.0)".format(expr)
        self._line("vec4 {v} = {e};".format(v=var, e=expr))
        return var

    # ---- Math ----
    def _n_math(self, node, out):
        vals = [s for s in node.inputs if s.type == "VALUE"]
        a = self.input_expr(node, vals[0] if len(vals) > 0 else None, "float")
        b = self.input_expr(node, vals[1] if len(vals) > 1 else None, "float")
        c = self.input_expr(node, vals[2] if len(vals) > 2 else None, "float")
        op = getattr(node, "operation", "ADD")
        m = {
            "ADD": "({a})+({b})", "SUBTRACT": "({a})-({b})",
            "MULTIPLY": "({a})*({b})", "DIVIDE": "_sdiv({a},{b})",
            "MULTIPLY_ADD": "({a})*({b})+({c})",
            "POWER": "pow(max({a},0.0),{b})", "LOGARITHM": "_sdiv(log({a}),log({b}))",
            "SQRT": "sqrt(max({a},0.0))", "INVERSE_SQRT": "inversesqrt(max({a},1e-6))",
            "ABSOLUTE": "abs({a})", "EXPONENT": "exp({a})",
            "MINIMUM": "min({a},{b})", "MAXIMUM": "max({a},{b})",
            "LESS_THAN": "float(({a})<({b}))", "GREATER_THAN": "float(({a})>({b}))",
            "SIGN": "sign({a})", "COMPARE": "float(abs(({a})-({b}))<=({c}))",
            "ROUND": "floor(({a})+0.5)", "FLOOR": "floor({a})", "CEIL": "ceil({a})",
            "TRUNCATE": "trunc({a})", "FRACT": "fract({a})",
            "MODULO": "mod({a},{b})", "SNAP": "floor(_sdiv({a},{b}))*({b})",
            "SINE": "sin({a})", "COSINE": "cos({a})", "TANGENT": "tan({a})",
            "ARCSINE": "asin(clamp({a},-1.0,1.0))", "ARCCOSINE": "acos(clamp({a},-1.0,1.0))",
            "ARCTANGENT": "atan({a})", "ARCTAN2": "atan({a},{b})",
            "RADIANS": "radians({a})", "DEGREES": "degrees({a})",
        }
        tmpl = m.get(op)
        if tmpl is None:
            self.notes.append("MATH op '{}' passthrough".format(op)); tmpl = "({a})"
        expr = tmpl.format(a=a, b=b, c=c)
        if getattr(node, "use_clamp", False): expr = "clamp({}, 0.0, 1.0)".format(expr)
        var = self._new_var("math")
        self._line("float {v} = {e};".format(v=var, e=expr))
        return "vec4(vec3({v}), 1.0)".format(v=var) if out.type == "RGBA" else var

    # ---- Vector Math ----
    def _n_vect_math(self, node, out):
        vs = [s for s in node.inputs if s.type == "VECTOR"]
        a = self.input_expr(node, vs[0] if len(vs) > 0 else None, "vec3")
        b = self.input_expr(node, vs[1] if len(vs) > 1 else None, "vec3")
        scale = self.input_expr(node, node.inputs.get("Scale"), "float") if node.inputs.get("Scale") else "1.0"
        op = getattr(node, "operation", "ADD")
        vec_ops = {
            "ADD": "({a})+({b})", "SUBTRACT": "({a})-({b})",
            "MULTIPLY": "({a})*({b})", "DIVIDE": "({a})/max({b},vec3(1e-6))",
            "CROSS_PRODUCT": "cross({a},{b})", "PROJECT": "({b})*_sdiv(dot({a},{b}),dot({b},{b}))",
            "REFLECT": "reflect({a},normalize({b}))", "NORMALIZE": "normalize({a})",
            "ABSOLUTE": "abs({a})", "MINIMUM": "min({a},{b})", "MAXIMUM": "max({a},{b})",
            "FLOOR": "floor({a})", "CEIL": "ceil({a})", "FRACTION": "fract({a})",
            "MODULO": "mod({a},{b})", "SNAP": "floor({a}/{b})*({b})",
            "SINE": "sin({a})", "COSINE": "cos({a})", "TANGENT": "tan({a})",
            "SCALE": "({a})*({s})",
        }
        scalar_ops = {
            "DOT_PRODUCT": "dot({a},{b})", "DISTANCE": "distance({a},{b})",
            "LENGTH": "length({a})",
        }
        if op in scalar_ops:
            var = self._new_var("vscal")
            self._line("float {v} = {e};".format(
                v=var, e=scalar_ops[op].format(a=a, b=b)))
            return "vec4(vec3({v}),1.0)".format(v=var) if out.type == "RGBA" else var
        tmpl = vec_ops.get(op)
        if tmpl is None:
            self.notes.append("VECT_MATH op '{}' passthrough".format(op)); tmpl = "({a})"
        var = self._new_var("vvec")
        self._line("vec3 {v} = {e};".format(
            v=var, e=tmpl.format(a=a, b=b, s=scale)))
        return "vec4({v}, 1.0)".format(v=var)

    # ---- Map Range (linear FLOAT) ----
    def _n_map_range(self, node, out):
        val = self.input_expr(node, node.inputs.get("Value"), "float")
        fmn = self.input_expr(node, node.inputs.get("From Min"), "float")
        fmx = self.input_expr(node, node.inputs.get("From Max"), "float")
        tmn = self.input_expr(node, node.inputs.get("To Min"), "float")
        tmx = self.input_expr(node, node.inputs.get("To Max"), "float")
        if getattr(node, "interpolation_type", "LINEAR") != "LINEAR":
            self.notes.append("MAP_RANGE interpolation approximated as LINEAR")
        var = self._new_var("mr")
        expr = "({tmn}) + (({val})-({fmn}))*_sdiv(({tmx})-({tmn}),({fmx})-({fmn}))".format(
            val=val, fmn=fmn, fmx=fmx, tmn=tmn, tmx=tmx)
        if getattr(node, "clamp", True):
            expr = "clamp({e}, min({tmn},{tmx}), max({tmn},{tmx}))".format(e=expr, tmn=tmn, tmx=tmx)
        self._line("float {v} = {e};".format(v=var, e=expr))
        return "vec4(vec3({v}),1.0)".format(v=var) if out.type == "RGBA" else var

    # ---- Clamp ----
    def _n_clamp(self, node, out):
        v = self.input_expr(node, node.inputs.get("Value"), "float")
        lo = self.input_expr(node, node.inputs.get("Min"), "float")
        hi = self.input_expr(node, node.inputs.get("Max"), "float")
        var = self._new_var("clamp")
        if getattr(node, "clamp_type", "MINMAX") == "RANGE":
            self._line("float {v} = clamp({x}, min({lo},{hi}), max({lo},{hi}));".format(
                v=var, x=v, lo=lo, hi=hi))
        else:
            self._line("float {v} = clamp({x}, {lo}, {hi});".format(v=var, x=v, lo=lo, hi=hi))
        return var

    # ---- Hue/Sat/Value ----
    def _n_hue_sat(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        h = self.input_expr(node, node.inputs.get("Hue"), "float")
        s = self.input_expr(node, node.inputs.get("Saturation"), "float")
        val = self.input_expr(node, node.inputs.get("Value"), "float")
        fac = self.input_expr(node, node.inputs.get("Fac"), "float")
        var = self._new_var("hsv")
        self._line("vec3 {v}_h = _rgb2hsv(({c}).rgb);".format(v=var, c=col))
        self._line("{v}_h.x = fract({v}_h.x + ({h}) + 0.5);".format(v=var, h=h))
        self._line("{v}_h.y = clamp({v}_h.y * ({s}), 0.0, 1.0);".format(v=var, s=s))
        self._line("{v}_h.z = {v}_h.z * ({val});".format(v=var, val=val))
        self._line("vec3 {v}_rgb = _hsv2rgb({v}_h);".format(v=var))
        self._line("vec4 {v} = vec4(mix(({c}).rgb, {v}_rgb, clamp({f},0.0,1.0)), ({c}).a);".format(
            v=var, c=col, f=fac))
        return var

    # ---- Gamma / Bright-Contrast / Invert ----
    def _n_gamma(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        g = self.input_expr(node, node.inputs.get("Gamma"), "float")
        var = self._new_var("gam")
        self._line("vec4 {v} = vec4(pow(max(({c}).rgb,vec3(0.0)), vec3({g})), ({c}).a);".format(
            v=var, c=col, g=g))
        return var

    def _n_brightcontrast(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        br = self.input_expr(node, node.inputs.get("Bright"), "float")
        co = self.input_expr(node, node.inputs.get("Contrast"), "float")
        var = self._new_var("bc")
        # Blender: a = 1+contrast; b = brightness - contrast*0.5; out = a*col + b
        self._line("float {v}_a = 1.0 + ({co});".format(v=var, co=co))
        self._line("float {v}_b = ({br}) - ({co})*0.5;".format(v=var, br=br, co=co))
        self._line("vec4 {v} = vec4(max(({c}).rgb*{v}_a + {v}_b, 0.0), ({c}).a);".format(
            v=var, c=col))
        return var

    def _n_invert(self, node, out):
        fac = self.input_expr(node, node.inputs.get("Fac"), "float")
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        var = self._new_var("inv")
        self._line("vec4 {v} = vec4(mix(({c}).rgb, vec3(1.0)-({c}).rgb, clamp({f},0.0,1.0)), ({c}).a);".format(
            v=var, c=col, f=fac))
        return var

    # ---- Separate / Combine ----
    def _n_separate_color(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        mode = getattr(node, "mode", "RGB")
        base = "({c}).rgb".format(c=col)
        if mode == "HSV": base = "_rgb2hsv(({c}).rgb)".format(c=col)
        idx = {"Red": 0, "Green": 1, "Blue": 2, "Hue": 0, "Saturation": 1, "Value": 2}.get(out.name, 0)
        return "vec4(vec3(({b})[{i}]), 1.0)".format(b=base, i=idx)

    def _n_seprgb(self, node, out):
        col = self.input_expr(node, node.inputs.get("Image"), "vec4")
        idx = {"R": 0, "G": 1, "B": 2}.get(out.name, 0)
        return "vec4(vec3(({c}).rgb[{i}]),1.0)".format(c=col, i=idx)

    def _n_combine_color(self, node, out):
        r = self.input_expr(node, node.inputs[0] if len(node.inputs) > 0 else None, "float")
        g = self.input_expr(node, node.inputs[1] if len(node.inputs) > 1 else None, "float")
        b = self.input_expr(node, node.inputs[2] if len(node.inputs) > 2 else None, "float")
        if getattr(node, "mode", "RGB") == "HSV":
            return "vec4(_hsv2rgb(vec3({r},{g},{b})), 1.0)".format(r=r, g=g, b=b)
        return "vec4({r},{g},{b},1.0)".format(r=r, g=g, b=b)

    def _n_combrgb(self, node, out):
        return self._n_combine_color(node, out)

    def _n_sepxyz(self, node, out):
        vec = self.input_expr(node, node.inputs.get("Vector"), "vec3")
        idx = {"X": 0, "Y": 1, "Z": 2}.get(out.name, 0)
        return "vec4(vec3(({v})[{i}]),1.0)".format(v=vec, i=idx)

    def _n_combxyz(self, node, out):
        x = self.input_expr(node, node.inputs.get("X"), "float")
        y = self.input_expr(node, node.inputs.get("Y"), "float")
        z = self.input_expr(node, node.inputs.get("Z"), "float")
        return "vec4({x},{y},{z},1.0)".format(x=x, y=y, z=z)

    # ---- Color Ramp (values baked; recompiles on ramp edit — noted) ----
    def _n_valtorgb(self, node, out):
        fac = self.input_expr(node, node.inputs.get("Fac"), "float")
        ramp = node.color_ramp
        els = list(ramp.elements)
        var = self._new_var("ramp")
        self._line("float {v}_t = clamp({f}, 0.0, 1.0);".format(v=var, f=fac))
        if not els:
            self._line("vec4 {v} = vec4(0.0,0.0,0.0,1.0);".format(v=var))
            return var
        # start with first stop colour, then blend toward each subsequent stop
        c0 = els[0].color
        self._line("vec4 {v} = vec4({r},{g},{b},{a});".format(
            v=var, r=_f(c0[0]), g=_f(c0[1]), b=_f(c0[2]), a=_f(c0[3])))
        interp = getattr(ramp, "interpolation", "LINEAR")
        for i in range(1, len(els)):
            p0 = els[i - 1].position; p1 = els[i].position; c1 = els[i].color
            denom = max(p1 - p0, 1e-6)
            if interp == "CONSTANT":
                w = "step({p1}, {v}_t)".format(p1=_f(p1), v=var)
            else:
                w = "clamp(({v}_t-{p0})/{d}, 0.0, 1.0)".format(v=var, p0=_f(p0), d=_f(denom))
                if interp == "EASE":
                    w = "smoothstep(0.0,1.0,{})".format(w)
            self._line("{v} = mix({v}, vec4({r},{g},{b},{a}), {w});".format(
                v=var, r=_f(c1[0]), g=_f(c1[1]), b=_f(c1[2]), a=_f(c1[3]), w=w))
        return var

    def _n_rgbtobw(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        var = self._new_var("bw")
        # Blender's rgb_to_bw luminance weights (Rec.709).
        self._line("float {v} = dot(({c}).rgb, vec3(0.2126729, 0.7151522, 0.0721750));"
                   .format(v=var, c=col))
        return "vec4(vec3({v}), 1.0)".format(v=var) if out.type == "RGBA" else var

    # ---- Shaders: read colour input, never render as closure ----
    def _n_bsdf_principled(self, node, out):
        base = node.inputs.get("Base Color") or node.inputs.get("Color")
        return self.input_expr(node, base, "vec4") if base else "vec4(0.8,0.8,0.8,1.0)"

    def _n_emission(self, node, out):
        col = node.inputs.get("Color")
        return self.input_expr(node, col, "vec4") if col else "vec4(1.0)"

    def _n_bsdf_diffuse(self, node, out):
        return self._n_bsdf_principled(node, out)


# ---------------------------------------------------------------------------
def _find_base_socket(mat):
    nt = getattr(mat, "node_tree", None)
    if not nt: return None
    out = None
    for n in nt.nodes:
        if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True):
            out = n; break
    if out is None:
        for n in nt.nodes:
            if n.type == "OUTPUT_MATERIAL":
                out = n; break
    if out is None: return None
    surf = out.inputs.get("Surface")
    if surf and surf.is_linked:
        src = surf.links[0].from_node
        if src.type == "BSDF_PRINCIPLED":
            return src.inputs.get("Base Color")
        if src.type == "EMISSION":
            return src.inputs.get("Color")
        return src.inputs.get("Base Color") or src.inputs.get("Color")
    return None   # no shader on Surface -> caller falls back to legacy texture path


def transpile_material(mat):
    res = TranspileResult()
    if not mat or not getattr(mat, "use_nodes", False):
        dc = list(getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0))) if mat else [0.8, 0.8, 0.8, 1.0]
        res.glsl = ("vec4 computeBaseColor(vec2 vUV) {{ return vec4({},{},{},{}); }}"
                    .format(_f(dc[0]), _f(dc[1]), _f(dc[2]), _f(dc[3] if len(dc) > 3 else 1.0)))
        res.ok = True
        res.notes.append("material has no nodes")
        return res

    base = _find_base_socket(mat)
    t = _Transpiler()
    if base is None:
        # Surface isn't a shape we can trace to a base colour (Mix Shader, node
        # group, Add Shader, empty surface, ...). Signal the engine to use the
        # legacy texture path instead of rendering flat grey.
        res.needs_fallback = True
        res.notes.append("no base-colour socket; using base-texture fallback")
        body_expr = "vec4(0.8, 0.8, 0.8, 1.0)"
    else:
        body_expr = _resolve_root(t, base)

    body = "\n    ".join(t.lines)
    res.glsl = ("vec4 computeBaseColor(vec2 vUV) {\n"
                + ("    " + body + "\n" if body else "")
                + "    return {};\n".format(body_expr) + "}")
    res.samplers = t.samplers
    res.params = t.params
    res.param_decls = t.param_decls
    res.notes.extend(t.notes)
    res.ok = True
    return res


def _resolve_root(t, base_socket):
    """Resolve the root base-colour socket (may be linked or a bare default)."""
    if base_socket.is_linked:
        link = base_socket.links[0]
        return t._coerce(t.emit_node(link.from_node, link.from_socket), "vec4")
    # unlinked root: promote its default to a uniform too
    owner = None
    # find owning node (the socket belongs to a node's inputs)
    return t._uniform_default(_socket_owner(base_socket), base_socket, "vec4") \
        if _socket_owner(base_socket) else "vec4(0.8,0.8,0.8,1.0)"


def _socket_owner(socket):
    return getattr(socket, "node", None)


# ---------------------------------------------------------------------------
def topo_signature(mat):
    """
    Structure-only signature: node types/names + source-affecting enums + links
    + image assignments + ColorRamp stops. Excludes tweakable default_values
    (those are uniforms). Same signature => the compiled program can be reused.
    """
    nt = getattr(mat, "node_tree", None)
    if not nt:
        return "NONODES"
    parts = []
    for n in nt.nodes:
        parts.append(n.type + ":" + n.name + "|" + _variant(n))
    for l in nt.links:
        try:
            parts.append("{}.{}>{}.{}".format(
                l.from_node.name, l.from_socket.identifier,
                l.to_node.name, l.to_socket.identifier))
        except Exception:
            parts.append("link?")
    return "\n".join(parts)


def _variant(n):
    t = n.type
    v = []
    if t == "MATH": v = [getattr(n, "operation", ""), str(getattr(n, "use_clamp", False))]
    elif t == "MIX_RGB": v = [getattr(n, "blend_type", ""), str(getattr(n, "use_clamp", False))]
    elif t == "MIX": v = [getattr(n, "data_type", ""), getattr(n, "blend_type", ""),
                          str(getattr(n, "clamp_result", False))]
    elif t == "VECT_MATH": v = [getattr(n, "operation", "")]
    elif t == "MAPPING": v = [getattr(n, "vector_type", "POINT")]
    elif t == "CLAMP": v = [getattr(n, "clamp_type", "MINMAX")]
    elif t == "MAP_RANGE": v = [getattr(n, "interpolation_type", "LINEAR"), str(getattr(n, "clamp", True))]
    elif t in ("SEPARATE_COLOR", "COMBINE_COLOR"): v = [getattr(n, "mode", "RGB")]
    elif t == "TEX_IMAGE": v = ["img=" + (n.image.name if n.image else "")]
    elif t == "VALTORGB":
        cr = n.color_ramp
        v = [getattr(cr, "interpolation", "LINEAR"), str(len(cr.elements))]
        for e in cr.elements:
            v.append("{:.4f}:{:.3f},{:.3f},{:.3f},{:.3f}".format(
                e.position, e.color[0], e.color[1], e.color[2], e.color[3]))
    return t + "|" + ",".join(v)
