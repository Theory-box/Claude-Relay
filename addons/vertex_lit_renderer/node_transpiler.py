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

/* ---- Math-node helpers (match Blender's math utils) ---- */
float _bsmin(float a, float b, float k){ if(k!=0.0){ float h=max(k-abs(a-b),0.0)/k; return min(a,b)-h*h*h*k*(1.0/6.0); } return min(a,b); }
float _bsmax(float a, float b, float k){ return -_bsmin(-a,-b,k); }
float _bwrapf(float v, float mx, float mn){ float r=mx-mn; return (r!=0.0)? v-r*floor((v-mn)/r) : mn; }
vec3  _bwrap3(vec3 v, vec3 mx, vec3 mn){ return vec3(_bwrapf(v.x,mx.x,mn.x),_bwrapf(v.y,mx.y,mn.y),_bwrapf(v.z,mx.z,mn.z)); }
float _bpingpong(float a, float s){ return (s!=0.0)? abs(fract((a-s)/(s*2.0))*s*2.0-s) : 0.0; }
float _btmod(float a, float b){ return (b!=0.0)? a-b*trunc(a/b) : 0.0; }   /* truncated modulo (Blender MODULO) */
float _lut65(float a[65], float x){ x=clamp(x,0.0,1.0)*64.0; int i=int(x); float f=x-float(i); return mix(a[i], a[min(i+1,64)], f); }

/* ===== Blender-exact Perlin noise — ported from Blender's GPL GLSL
 * (gpu_shader_common_hash.glsl + gpu_shader_material_noise.glsl).
 * Adapted for GLSL 330: float3->vec3, stripped 'f' suffixes, renamed the
 * Jenkins macros so they don't shadow the builtin mix(). ===== */
#define HROT(x, k) (((x) << (k)) | ((x) >> (32u - (k))))
#define HFINAL(a, b, c) { c^=b; c-=HROT(b,14u); a^=c; a-=HROT(c,11u); b^=a; b-=HROT(a,25u); c^=b; c-=HROT(b,16u); a^=c; a-=HROT(c,4u); b^=a; b-=HROT(a,14u); c^=b; c-=HROT(b,24u); }
#define HMIX(a, b, c) { a-=c; a^=HROT(c,4u); c+=b; b-=a; b^=HROT(a,6u); a+=c; c-=b; c^=HROT(b,8u); b+=a; a-=c; a^=HROT(c,16u); c+=b; b-=a; b^=HROT(a,19u); a+=c; c-=b; c^=HROT(b,4u); b+=a; }
uint hash_uint(uint kx){ uint a,b,c; a=b=c=0xdeadbeefu+(1u<<2u)+13u; a+=kx; HFINAL(a,b,c); return c; }
uint hash_uint2(uint kx,uint ky){ uint a,b,c; a=b=c=0xdeadbeefu+(2u<<2u)+13u; b+=ky; a+=kx; HFINAL(a,b,c); return c; }
uint hash_uint3(uint kx,uint ky,uint kz){ uint a,b,c; a=b=c=0xdeadbeefu+(3u<<2u)+13u; c+=kz; b+=ky; a+=kx; HFINAL(a,b,c); return c; }
uint hash_uint4(uint kx,uint ky,uint kz,uint kw){ uint a,b,c; a=b=c=0xdeadbeefu+(4u<<2u)+13u; a+=kx; b+=ky; c+=kz; HMIX(a,b,c); a+=kw; HFINAL(a,b,c); return c; }
#undef HROT
#undef HFINAL
#undef HMIX
int _b_int3h(int kx,int ky,int kz){ return int(hash_uint3(uint(kx),uint(ky),uint(kz))); }
float _b_cmod(float x, float m){ return x - m*trunc(x/m); }
vec3  _b_cmod3(vec3 x, float m){ return vec3(_b_cmod(x.x,m),_b_cmod(x.y,m),_b_cmod(x.z,m)); }
float _b_fade(float t){ return t*t*t*(t*(t*6.0-15.0)+10.0); }
float _b_negif(float v, uint c){ return (c!=0u)? -v : v; }
float _b_grad(uint hash, float x, float y, float z){
    uint h=hash&15u; float u=h<8u?x:y; float vt=((h==12u)||(h==14u))?x:z; float v=h<4u?y:vt;
    return _b_negif(u,h&1u)+_b_negif(v,h&2u);
}
float _b_trimix(float v0,float v1,float v2,float v3,float v4,float v5,float v6,float v7,float x,float y,float z){
    float x1=1.0-x,y1=1.0-y,z1=1.0-z;
    return z1*(y1*(v0*x1+v1*x)+y*(v2*x1+v3*x))+z*(y1*(v4*x1+v5*x)+y*(v6*x1+v7*x));
}
float _b_perlin3(vec3 p){
    float xf=floor(p.x); int X=int(xf); float fx=p.x-xf;
    float yf=floor(p.y); int Y=int(yf); float fy=p.y-yf;
    float zf=floor(p.z); int Z=int(zf); float fz=p.z-zf;
    float u=_b_fade(fx), v=_b_fade(fy), w=_b_fade(fz);
    return _b_trimix(
        _b_grad(uint(_b_int3h(X,Y,Z)),         fx,     fy,     fz),
        _b_grad(uint(_b_int3h(X+1,Y,Z)),       fx-1.0, fy,     fz),
        _b_grad(uint(_b_int3h(X,Y+1,Z)),       fx,     fy-1.0, fz),
        _b_grad(uint(_b_int3h(X+1,Y+1,Z)),     fx-1.0, fy-1.0, fz),
        _b_grad(uint(_b_int3h(X,Y,Z+1)),       fx,     fy,     fz-1.0),
        _b_grad(uint(_b_int3h(X+1,Y,Z+1)),     fx-1.0, fy,     fz-1.0),
        _b_grad(uint(_b_int3h(X,Y+1,Z+1)),     fx,     fy-1.0, fz-1.0),
        _b_grad(uint(_b_int3h(X+1,Y+1,Z+1)),   fx-1.0, fy-1.0, fz-1.0),
        u,v,w);
}
float _b_snoise3(vec3 p){ return 0.9820 * _b_perlin3(_b_cmod3(p, 100000.0)); }  /* signed, ~[-1,1] */
/* fractal fbm (Blender NOISE_FBM, normalize=true -> [0,1]) */
float _b_fbm3(vec3 co, float detail, float roughness, float lacunarity){
    vec3 p=co; float fscale=1.0, amp=1.0, maxamp=0.0, sum=0.0; int n=int(detail);
    for(int i=0;i<16;i++){ if(i>n) break;
        sum += amp*_b_snoise3(fscale*p); maxamp += amp; amp *= roughness; fscale *= max(lacunarity,1e-6);
    }
    float rmd = detail - floor(detail);
    if(rmd != 0.0){
        float t = _b_snoise3(fscale*p); float sum2 = sum + t*amp;
        return mix(0.5*sum/maxamp+0.5, 0.5*sum2/(maxamp+amp)+0.5, rmd);
    }
    return 0.5*sum/maxamp+0.5;
}
/* hash->[0,1] variants (verbatim from gpu_shader_common_hash.glsl) for Voronoi/etc. */
float hash_uint3_to_float(uint kx,uint ky,uint kz){ return float(hash_uint3(kx,ky,kz))/float(0xFFFFFFFFu); }
float hash_uint4_to_float(uint kx,uint ky,uint kz,uint kw){ return float(hash_uint4(kx,ky,kz,kw))/float(0xFFFFFFFFu); }
float hash_vec3_to_float(vec3 k){ return hash_uint3_to_float(floatBitsToUint(k.x),floatBitsToUint(k.y),floatBitsToUint(k.z)); }
float hash_vec4_to_float(vec4 k){ return hash_uint4_to_float(floatBitsToUint(k.x),floatBitsToUint(k.y),floatBitsToUint(k.z),floatBitsToUint(k.w)); }
vec3 hash_vec3_to_vec3(vec3 k){ return vec3(hash_vec3_to_float(k), hash_vec4_to_float(vec4(k,1.0)), hash_vec4_to_float(vec4(k,2.0))); }
/* PCG integer hash used by Voronoi (verbatim from Blender hash) */
ivec3 _hash_pcg3d(ivec3 v){
    v = v*1664525 + 1013904223;
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    v = v ^ (v >> 16);
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    return v;
}
vec3 hash_int3_to_vec3(ivec3 k){ ivec3 h=_hash_pcg3d(k); return vec3(h & 0x7fffffff) * (1.0/float(0x7fffffff)); }
float _vor_dist(vec3 a, vec3 b, int m, float e){
    if(m==0) return distance(a,b);
    if(m==1) return abs(a.x-b.x)+abs(a.y-b.y)+abs(a.z-b.z);
    if(m==2) return max(abs(a.x-b.x),max(abs(a.y-b.y),abs(a.z-b.z)));
    if(m==3) return pow(pow(abs(a.x-b.x),e)+pow(abs(a.y-b.y),e)+pow(abs(a.z-b.z),e), 1.0/e);
    return 0.0;
}
void _vor_f1(vec3 coord, float rnd, int m, float e, out float od, out vec3 oc, out vec3 op){
    vec3 cpf=floor(coord); vec3 lp=coord-cpf; ivec3 cp=ivec3(cpf);
    float mind=3.402823466e38; ivec3 toff=ivec3(0); vec3 tpos=vec3(0.0);
    for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){
        ivec3 co=ivec3(i,j,k);
        vec3 pp=vec3(co)+hash_int3_to_vec3(cp+co)*rnd;
        float d=_vor_dist(pp,lp,m,e);
        if(d<mind){ toff=co; mind=d; tpos=pp; }
    }
    od=mind; oc=hash_int3_to_vec3(cp+toff); op=tpos+cpf;
}
void _vor_smooth(vec3 coord, float rnd, float sm, int m, float e, out float od, out vec3 oc, out vec3 op){
    vec3 cpf=floor(coord); vec3 lp=coord-cpf; ivec3 cp=ivec3(cpf);
    float sd=0.0; vec3 sc=vec3(0.0); vec3 sp=vec3(0.0); float h=-1.0;
    for(int k=-2;k<=2;k++)for(int j=-2;j<=2;j++)for(int i=-2;i<=2;i++){
        ivec3 co=ivec3(i,j,k);
        vec3 pp=vec3(co)+hash_int3_to_vec3(cp+co)*rnd;
        float d=_vor_dist(pp,lp,m,e);
        h = (h==-1.0) ? 1.0 : smoothstep(0.0,1.0,0.5+0.5*(sd-d)/sm);
        float cf = sm*h*(1.0-h);
        sd = mix(sd,d,h)-cf; cf /= 1.0+3.0*sm;
        vec3 cc=hash_int3_to_vec3(cp+co);
        sc = mix(sc,cc,h)-cf; sp = mix(sp,pp,h)-cf;
    }
    od=sd; oc=sc; op=cpf+sp;
}
void _vor_f2(vec3 coord, float rnd, int m, float e, out float od, out vec3 oc, out vec3 op){
    vec3 cpf=floor(coord); vec3 lp=coord-cpf; ivec3 cp=ivec3(cpf);
    float d1=3.402823466e38, d2=3.402823466e38; ivec3 o1=ivec3(0),o2=ivec3(0); vec3 p1=vec3(0.0),p2=vec3(0.0);
    for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){
        ivec3 co=ivec3(i,j,k);
        vec3 pp=vec3(co)+hash_int3_to_vec3(cp+co)*rnd;
        float d=_vor_dist(pp,lp,m,e);
        if(d<d1){ d2=d1; d1=d; o2=o1; o1=co; p2=p1; p1=pp; }
        else if(d<d2){ d2=d; o2=co; p2=pp; }
    }
    od=d2; oc=hash_int3_to_vec3(cp+o2); op=p2+cpf;
}
float _vor_edge(vec3 coord, float rnd){
    vec3 cpf=floor(coord); vec3 lp=coord-cpf; ivec3 cp=ivec3(cpf);
    vec3 vtc=vec3(0.0); float mind=3.402823466e38;
    for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){
        vec3 vp=vec3(ivec3(i,j,k))+hash_int3_to_vec3(cp+ivec3(i,j,k))*rnd-lp;
        float d=dot(vp,vp);
        if(d<mind){ mind=d; vtc=vp; }
    }
    mind=3.402823466e38;
    for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){
        vec3 vp=vec3(ivec3(i,j,k))+hash_int3_to_vec3(cp+ivec3(i,j,k))*rnd-lp;
        vec3 pe=vp-vtc;
        if(dot(pe,pe)>0.0001){ float de=dot((vtc+vp)/2.0, normalize(pe)); mind=min(mind,de); }
    }
    return mind;
}
/* integer_noise (verbatim from Blender hash) — used by Brick */
float integer_noise(int n){
    uint nn = (uint(n) + 1013u) & 0x7fffffffu;
    nn = (nn >> 13u) ^ nn;
    nn = (uint(nn * (nn * nn * 60493u + 19990303u)) + 1376312589u) & 0x7fffffffu;
    return 0.5 * (float(nn) / 1073741824.0);
}
/* Blender Brick (calc_brick_texture) -> vec2(tint, fac) */
vec2 _b_brick(vec3 p, float mortar_size, float mortar_smooth, float bias, float brick_width,
              float row_height, float offset_amount, int offset_freq, float squash_amount, int squash_freq){
    int rownum = int(floor(p.y / row_height));
    float offset = 0.0; float bw = brick_width;
    if(offset_freq != 0 && squash_freq != 0){
        bw *= (rownum % squash_freq != 0) ? 1.0 : squash_amount;
        offset = (rownum % offset_freq != 0) ? 0.0 : (bw * offset_amount);
    }
    int bricknum = int(floor((p.x + offset) / bw));
    float x = (p.x + offset) - bw * float(bricknum);
    float y = p.y - row_height * float(rownum);
    float tint = clamp(integer_noise((rownum << 16) + (bricknum & 0xFFFF)) + bias, 0.0, 1.0);
    float md = min(min(x, y), min(bw - x, row_height - y));
    float fac;
    if(md >= mortar_size) fac = 0.0;
    else if(mortar_smooth == 0.0) fac = 1.0;
    else { md = 1.0 - md / mortar_size; fac = smoothstep(0.0, mortar_smooth, md); }
    return vec2(tint, fac);
}
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
        name = out.name
        if name == "UV":        return "vec4(vUV, 0.0, 1.0)"
        if name == "Generated": return "vec4(vGenerated, 1.0)"
        if name == "Object":    return "vec4(vObjPos, 1.0)"
        # Normal/Camera/Window/Reflection need view/normal data not available in
        # every material fragment -> approximate as Generated (visible, non-fatal).
        self.notes.append("TEX_COORD.{} approximated as Generated".format(name))
        return "vec4(vGenerated, 1.0)"

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
            "SMOOTH_MIN": "_bsmin({a},{b},{c})", "SMOOTH_MAX": "_bsmax({a},{b},{c})",
            "ROUND": "floor(({a})+0.5)", "FLOOR": "floor({a})", "CEIL": "ceil({a})",
            "TRUNC": "trunc({a})", "FRACT": "fract({a})",
            "MODULO": "_btmod({a},{b})", "FLOORED_MODULO": "mod({a},{b})",
            "WRAP": "_bwrapf({a},{b},{c})", "SNAP": "floor(_sdiv({a},{b}))*({b})",
            "PINGPONG": "_bpingpong({a},{b})",
            "SINE": "sin({a})", "COSINE": "cos({a})", "TANGENT": "tan({a})",
            "ARCSINE": "asin(clamp({a},-1.0,1.0))", "ARCCOSINE": "acos(clamp({a},-1.0,1.0))",
            "ARCTANGENT": "atan({a})", "ARCTAN2": "atan({a},{b})",
            "SINH": "sinh({a})", "COSH": "cosh({a})", "TANH": "tanh({a})",
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
        c = self.input_expr(node, vs[2] if len(vs) > 2 else None, "vec3")
        scale = self.input_expr(node, node.inputs.get("Scale"), "float") if node.inputs.get("Scale") else "1.0"
        op = getattr(node, "operation", "ADD")
        vec_ops = {
            "ADD": "({a})+({b})", "SUBTRACT": "({a})-({b})",
            "MULTIPLY": "({a})*({b})", "DIVIDE": "({a})/max({b},vec3(1e-6))",
            "MULTIPLY_ADD": "({a})*({b})+({c})",
            "CROSS_PRODUCT": "cross({a},{b})", "PROJECT": "({b})*_sdiv(dot({a},{b}),dot({b},{b}))",
            "REFLECT": "reflect({a},normalize({b}))",
            "REFRACT": "refract({a},normalize({b}),{s})",
            "FACEFORWARD": "faceforward({a},{b},{c})",
            "NORMALIZE": "normalize({a})",
            "ABSOLUTE": "abs({a})", "MINIMUM": "min({a},{b})", "MAXIMUM": "max({a},{b})",
            "FLOOR": "floor({a})", "CEIL": "ceil({a})", "FRACTION": "fract({a})",
            "MODULO": "mod({a},{b})", "SNAP": "floor({a}/{b})*({b})",
            "WRAP": "_bwrap3({a},{b},{c})",
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
            v=var, e=tmpl.format(a=a, b=b, c=c, s=scale)))
        return "vec4({v}, 1.0)".format(v=var)

    # ---- Map Range (linear FLOAT) ----
    def _n_map_range(self, node, out):
        val = self.input_expr(node, node.inputs.get("Value"), "float")
        fmn = self.input_expr(node, node.inputs.get("From Min"), "float")
        fmx = self.input_expr(node, node.inputs.get("From Max"), "float")
        tmn = self.input_expr(node, node.inputs.get("To Min"), "float")
        tmx = self.input_expr(node, node.inputs.get("To Max"), "float")
        interp = getattr(node, "interpolation_type", "LINEAR")
        var = self._new_var("mr")
        self._line("float {v}t = _sdiv(({val})-({fmn}), ({fmx})-({fmn}));".format(
            v=var, val=val, fmn=fmn, fmx=fmx))
        if interp == "SMOOTHSTEP":
            self._line("{v}t = clamp({v}t,0.0,1.0); {v}t = {v}t*{v}t*(3.0-2.0*{v}t);".format(v=var))
        elif interp == "SMOOTHERSTEP":
            self._line("{v}t = clamp({v}t,0.0,1.0); {v}t = {v}t*{v}t*{v}t*({v}t*({v}t*6.0-15.0)+10.0);".format(v=var))
        elif interp == "STEPPED":
            steps = self.input_expr(node, node.inputs.get("Steps"), "float") if node.inputs.get("Steps") else "4.0"
            self._line("{v}t = ({s} > 0.0) ? floor(clamp({v}t,0.0,1.0)*({s}+1.0))/{s} : 0.0;".format(v=var, s=steps))
        expr = "({tmn}) + {v}t*(({tmx})-({tmn}))".format(v=var, tmn=tmn, tmx=tmx)
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

    def _bake_curve(self, mapping, curve, post=None, n=64):
        vals = []
        for i in range(n + 1):
            x = i / float(n)
            y = mapping.evaluate(curve, x)
            if post is not None:
                y = mapping.evaluate(post, y)
            vals.append(y)
        return vals

    def _emit_lut(self, v, name, vals):
        arr = ", ".join(_f(x) for x in vals)
        self._line("float {v}{n}[65] = float[]({arr});".format(v=v, n=name, arr=arr))

    def _n_curve_rgb(self, node, out):
        col = self.input_expr(node, node.inputs.get("Color"), "vec4")
        fac = self.input_expr(node, node.inputs.get("Fac"), "float")
        mp = node.mapping; mp.initialize()
        C = mp.curves[3]
        v = self._new_var("crv")
        self._emit_lut(v, "R", self._bake_curve(mp, mp.curves[0], C))
        self._emit_lut(v, "G", self._bake_curve(mp, mp.curves[1], C))
        self._emit_lut(v, "B", self._bake_curve(mp, mp.curves[2], C))
        self._line("vec3 {v}i = ({c}).rgb;".format(v=v, c=col))
        self._line("vec3 {v}o = vec3(_lut65({v}R,{v}i.r), _lut65({v}G,{v}i.g), _lut65({v}B,{v}i.b));".format(v=v))
        self._line("vec4 {v}c = vec4(mix(({c}).rgb, {v}o, clamp({f},0.0,1.0)), ({c}).a);".format(v=v, c=col, f=fac))
        return v + "c"

    def _n_curve_float(self, node, out):
        val = self.input_expr(node, node.inputs.get("Value"), "float")
        fac = self.input_expr(node, node.inputs.get("Factor"), "float") if node.inputs.get("Factor") else "1.0"
        mp = node.mapping; mp.initialize()
        v = self._new_var("crvf")
        self._emit_lut(v, "L", self._bake_curve(mp, mp.curves[0]))
        self._line("float {v}f = mix({val}, _lut65({v}L, {val}), clamp({fac},0.0,1.0));".format(v=v, val=val, fac=fac))
        self._var_type[v + "f"] = "float"
        return v + "f"

    def _n_curve_vec(self, node, out):
        vec = self.input_expr(node, node.inputs.get("Vector"), "vec3")
        fac = self.input_expr(node, node.inputs.get("Fac"), "float") if node.inputs.get("Fac") else "1.0"
        mp = node.mapping; mp.initialize()
        v = self._new_var("crvv")
        # Vector curves map roughly [-1,1]; _lut65 clamps to [0,1] (X mapped via 0.5+0.5x)
        self._emit_lut(v, "X", self._bake_curve(mp, mp.curves[0]))
        self._emit_lut(v, "Y", self._bake_curve(mp, mp.curves[1]))
        self._emit_lut(v, "Z", self._bake_curve(mp, mp.curves[2]))
        self._line("vec3 {v}i = ({vec})*0.5+0.5;".format(v=v, vec=vec))
        self._line("vec3 {v}o = vec3(_lut65({v}X,{v}i.x),_lut65({v}Y,{v}i.y),_lut65({v}Z,{v}i.z))*2.0-1.0;".format(v=v))
        self._line("vec3 {v}r = mix({vec}, {v}o, clamp({fac},0.0,1.0));".format(v=v, vec=vec, fac=fac))
        return "vec4({v}r, 1.0)".format(v=v)

    def _n_tex_magic(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        dist = self.input_expr(node, node.inputs.get("Distortion"), "float")
        depth = int(getattr(node, "turbulence_depth", 2))
        v = self._new_var("magic")
        d = "{v}d".format(v=v)
        self._line("float {d} = {dist};".format(d=d, dist=dist))
        self._line("vec3 {v}p = mod(({co})*{s}, vec3(6.28318530718));".format(v=v, co=co, s=scale))
        self._line("float {v}x = sin(({v}p.x+{v}p.y+{v}p.z)*5.0);".format(v=v))
        self._line("float {v}y = cos((-{v}p.x+{v}p.y-{v}p.z)*5.0);".format(v=v))
        self._line("float {v}z = -cos((-{v}p.x-{v}p.y+{v}p.z)*5.0);".format(v=v))
        x, y, z = v + "x", v + "y", v + "z"
        if depth > 0:
            self._line("{x} *= {d}; {y} *= {d}; {z} *= {d};".format(x=x, y=y, z=z, d=d))
            self._line("{y} = -cos({x}-{y}+{z}); {y} *= {d};".format(x=x, y=y, z=z, d=d))
        gated = [
            (1, "{x} = cos({x}-{y}-{z}); {x} *= {d};"),
            (2, "{z} = sin(-{x}-{y}-{z}); {z} *= {d};"),
            (3, "{x} = -cos(-{x}+{y}-{z}); {x} *= {d};"),
            (4, "{y} = -sin(-{x}+{y}+{z}); {y} *= {d};"),
            (5, "{y} = -cos(-{x}+{y}+{z}); {y} *= {d};"),
            (6, "{x} = cos({x}+{y}+{z}); {x} *= {d};"),
            (7, "{z} = sin({x}+{y}-{z}); {z} *= {d};"),
            (8, "{x} = -cos(-{x}-{y}+{z}); {x} *= {d};"),
            (9, "{y} = -sin({x}-{y}+{z}); {y} *= {d};"),
        ]
        for thr, stmt in gated:
            if depth > thr:
                self._line(stmt.format(x=x, y=y, z=z, d=d))
        self._line("if(abs({d})>1e-9){{ float {v}dd={d}*2.0; {x}/={v}dd; {y}/={v}dd; {z}/={v}dd; }}"
                   .format(d=d, v=v, x=x, y=y, z=z))
        self._line("vec4 {v}c = vec4(0.5-{x}, 0.5-{y}, 0.5-{z}, 1.0);".format(v=v, x=x, y=y, z=z))
        if out.name == "Fac":
            self._line("float {v}f = ({v}c.x+{v}c.y+{v}c.z)/3.0;".format(v=v))
            self._var_type[v + "f"] = "float"
            return v + "f"
        return v + "c"

    def _n_tex_brick(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        c1 = self.input_expr(node, node.inputs.get("Color1"), "vec4")
        c2 = self.input_expr(node, node.inputs.get("Color2"), "vec4")
        mortar = self.input_expr(node, node.inputs.get("Mortar"), "vec4")
        ms = self.input_expr(node, node.inputs.get("Mortar Size"), "float")
        msm = self.input_expr(node, node.inputs.get("Mortar Smooth"), "float")
        bias = self.input_expr(node, node.inputs.get("Bias"), "float")
        bw = self.input_expr(node, node.inputs.get("Brick Width"), "float")
        rh = self.input_expr(node, node.inputs.get("Row Height"), "float")
        off = _f(getattr(node, "offset", 0.5))
        offf = int(getattr(node, "offset_frequency", 2))
        sq = _f(getattr(node, "squash", 1.0))
        sqf = int(getattr(node, "squash_frequency", 2))
        v = self._new_var("brick")
        self._line("vec2 {v}bf = _b_brick(({co})*{s}, {ms},{msm},{bias},{bw},{rh}, {off},{offf}, {sq},{sqf});"
                   .format(v=v, co=co, s=scale, ms=ms, msm=msm, bias=bias, bw=bw, rh=rh,
                           off=off, offf=offf, sq=sq, sqf=sqf))
        self._line("float {v}tint = {v}bf.x; float {v}f = {v}bf.y;".format(v=v))
        self._var_type[v + "f"] = "float"
        if out.name == "Fac":
            return v + "f"
        self._line("vec4 {v}c1 = {c1};".format(v=v, c1=c1))
        self._line("if({v}f != 1.0){{ {v}c1 = (1.0-{v}tint)*{v}c1 + {v}tint*({c2}); }}".format(v=v, c2=c2))
        self._line("vec4 {v}col = mix({v}c1, {mortar}, {v}f);".format(v=v, mortar=mortar))
        return v + "col"

    def _n_tex_wave(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        dist = self.input_expr(node, node.inputs.get("Distortion"), "float")
        detail = self.input_expr(node, node.inputs.get("Detail"), "float")
        dscale = self.input_expr(node, node.inputs.get("Detail Scale"), "float")
        drough = self.input_expr(node, node.inputs.get("Detail Roughness"), "float")
        phase = self.input_expr(node, node.inputs.get("Phase Offset"), "float")
        wtype = getattr(node, "wave_type", "BANDS")
        bdir = getattr(node, "bands_direction", "X")
        rdir = getattr(node, "rings_direction", "X")
        prof = getattr(node, "wave_profile", "SIN")
        v = self._new_var("wave")
        self._line("vec3 {v}p = (({co})*{s} + 0.000001) * 0.999999;".format(v=v, co=co, s=scale))
        if wtype == "BANDS":
            n = {"X": "{v}p.x*20.0", "Y": "{v}p.y*20.0", "Z": "{v}p.z*20.0",
                 "DIAGONAL": "({v}p.x+{v}p.y+{v}p.z)*10.0"}.get(bdir, "{v}p.x*20.0").format(v=v)
        else:  # RINGS
            rp = {"X": "vec3(0.0,{v}p.y,{v}p.z)", "Y": "vec3({v}p.x,0.0,{v}p.z)",
                  "Z": "vec3({v}p.x,{v}p.y,0.0)", "SPHERICAL": "{v}p"}.get(rdir, "{v}p").format(v=v)
            n = "length({rp})*20.0".format(rp=rp)
        self._line("float {v}n = {n} + ({ph});".format(v=v, n=n, ph=phase))
        self._line("if(abs({d}) > 1e-9){{ {v}n += ({d})*(_b_fbm3({v}p*({ds}),{det},{dr},2.0)*2.0-1.0); }}"
                   .format(v=v, d=dist, ds=dscale, det=detail, dr=drough))
        if prof == "SIN":
            self._line("float {v}f = 0.5 + 0.5*sin({v}n - 1.57079632679);".format(v=v))
        elif prof == "SAW":
            self._line("{v}n /= (2.0*3.14159265359); float {v}f = {v}n - floor({v}n);".format(v=v))
        else:  # TRI
            self._line("{v}n /= (2.0*3.14159265359); float {v}f = abs({v}n - floor({v}n+0.5))*2.0;".format(v=v))
        self._var_type[v + "f"] = "float"
        if out.name == "Color":
            return "vec4(vec3({v}f), 1.0)".format(v=v)
        return v + "f"

    def _n_tex_white_noise(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        if out.name == "Color":
            return "vec4(hash_vec3_to_vec3({co}), 1.0)".format(co=co)
        v = self._new_var("wn")
        self._line("float {v} = hash_vec3_to_float({co});".format(v=v, co=co))
        return v

    def _n_tex_checker(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        c1 = self.input_expr(node, node.inputs.get("Color1"), "vec4")
        c2 = self.input_expr(node, node.inputs.get("Color2"), "vec4")
        v = self._new_var("chk")
        self._line("vec3 {v}p = (({co})*{s} + 0.000001) * 0.999999;".format(v=v, co=co, s=scale))
        self._line("int {v}x=int(floor({v}p.x)); int {v}y=int(floor({v}p.y)); int {v}z=int(floor({v}p.z));".format(v=v))
        self._line("bool {v}c = (({v}x % 2 == {v}y % 2) == ({v}z % 2 == 0));".format(v=v))
        if out.name == "Color":
            return "({v}c ? ({c1}) : ({c2}))".format(v=v, c1=c1, c2=c2)
        self._line("float {v}f = {v}c ? 1.0 : 0.0;".format(v=v))
        self._var_type[v + "f"] = "float"
        return v + "f"

    def _n_tex_gradient(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        gt = getattr(node, "gradient_type", "LINEAR")
        v = self._new_var("grad")
        self._line("vec3 {v}p = {co};".format(v=v, co=co))
        expr = {
            "LINEAR":           "{v}p.x",
            "QUADRATIC":        "max({v}p.x,0.0)*max({v}p.x,0.0)",
            "EASING":           "clamp({v}p.x,0.0,1.0)*clamp({v}p.x,0.0,1.0)*(3.0-2.0*clamp({v}p.x,0.0,1.0))",
            "DIAGONAL":         "({v}p.x+{v}p.y)*0.5",
            "RADIAL":           "atan({v}p.y,{v}p.x)/(2.0*3.14159265)+0.5",
            "SPHERICAL":        "max(1.0-length({v}p),0.0)",
            "QUADRATIC_SPHERE": "max(1.0-length({v}p),0.0)*max(1.0-length({v}p),0.0)",
        }.get(gt, "{v}p.x").format(v=v)
        self._line("float {v}f = {e};".format(v=v, e=expr))
        self._var_type[v + "f"] = "float"
        if out.name == "Color":
            return "vec4(vec3(max({v}f,0.0)), 1.0)".format(v=v)
        return v + "f"

    def _n_tex_voronoi(self, node, out):
        vs = node.inputs.get("Vector")
        co = self.input_expr(node, vs, "vec3") if (vs and vs.is_linked) else "vGenerated"
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        rnd = self.input_expr(node, node.inputs.get("Randomness"), "float") \
            if node.inputs.get("Randomness") else "1.0"
        smooth = self.input_expr(node, node.inputs.get("Smoothness"), "float") \
            if node.inputs.get("Smoothness") else "0.0"
        expo = self.input_expr(node, node.inputs.get("Exponent"), "float") \
            if node.inputs.get("Exponent") else "1.0"
        feat = getattr(node, "feature", "F1")
        metric = {"EUCLIDEAN": 0, "MANHATTAN": 1, "CHEBYCHEV": 2, "MINKOWSKI": 3}.get(
            getattr(node, "distance", "EUCLIDEAN"), 0)
        norm = getattr(node, "normalize", True)
        if getattr(node, "voronoi_dimensions", "3D") != "3D":
            self.notes.append("VORONOI dimensions {} computed as 3D".format(getattr(node, "voronoi_dimensions", "?")))
        detail = self.input_expr(node, node.inputs.get("Detail"), "float") if node.inputs.get("Detail") else "0.0"
        v = self._new_var("vor")
        R = "clamp({},0.0,1.0)".format(rnd)
        self._line("vec3 {v}co = ({c})*{s};".format(v=v, c=co, s=scale))
        self._line("float {v}rnd = {R}; float {v}e = {e};".format(v=v, R=R, e=expo))
        self._line("float {v}d; vec3 {v}c=vec3(0.0); vec3 {v}pos=vec3(0.0);".format(v=v))
        self._var_type[v + "d"] = "float"; self._var_type[v + "c"] = "vec3"; self._var_type[v + "pos"] = "vec3"
        if feat == "DISTANCE_TO_EDGE":
            self._line("{v}d = _vor_edge({v}co, {v}rnd);".format(v=v))
            maxd = "(0.5 + 0.5*{v}rnd)".format(v=v)
        elif feat == "SMOOTH_F1":
            sm = "clamp(({})/2.0, 0.0, 0.5)".format(smooth)
            self._line("_vor_smooth({v}co, {v}rnd, max({sm},1e-5), {m}, {v}e, {v}d, {v}c, {v}pos);".format(
                v=v, sm=sm, m=metric))
            maxd = "_vor_dist(vec3(0.0), vec3(0.5+0.5*{v}rnd), {m}, {v}e)".format(v=v, m=metric)
        elif feat == "F2":
            self._line("_vor_f2({v}co, {v}rnd, {m}, {v}e, {v}d, {v}c, {v}pos);".format(v=v, m=metric))
            maxd = "(_vor_dist(vec3(0.0), vec3(0.5+0.5*{v}rnd), {m}, {v}e)*2.0)".format(v=v, m=metric)
        else:  # F1 (and N_SPHERE_RADIUS approx)
            if feat == "N_SPHERE_RADIUS":
                self.notes.append("VORONOI N_SPHERE_RADIUS approximated as F1 distance")
            self._line("_vor_f1({v}co, {v}rnd, {m}, {v}e, {v}d, {v}c, {v}pos);".format(v=v, m=metric))
            maxd = "_vor_dist(vec3(0.0), vec3(0.5+0.5*{v}rnd), {m}, {v}e)".format(v=v, m=metric)
        if norm and metric != 3:  # Blender doesn't normalise Minkowski cleanly; match default behaviour otherwise
            self._line("{v}d /= max({md}, 1e-8);".format(v=v, md=maxd))
        name = out.name
        if name == "Color":
            return "vec4({v}c, 1.0)".format(v=v)
        if name == "Position":
            return "vec4({v}pos, 1.0)".format(v=v)
        return v + "d"   # Distance / Radius / W

    def _n_tex_noise(self, node, out):
        vs = node.inputs.get("Vector")
        if vs is not None and vs.is_linked:
            co = self.input_expr(node, vs, "vec3")
        else:
            co = "vGenerated"   # unconnected: noise over the UV plane
        scale = self.input_expr(node, node.inputs.get("Scale"), "float")
        detail = self.input_expr(node, node.inputs.get("Detail"), "float")
        rough = self.input_expr(node, node.inputs.get("Roughness"), "float")
        lac = self.input_expr(node, node.inputs.get("Lacunarity"), "float") \
            if node.inputs.get("Lacunarity") else "2.0"
        dist = self.input_expr(node, node.inputs.get("Distortion"), "float")
        v = self._new_var("noise")
        self._line("vec3 {v}p = ({co}) * {s};".format(v=v, co=co, s=scale))
        # distortion: perturb the coordinate by noise of itself
        self._line("{v}p += {d} * vec3(_b_snoise3({v}p+vec3(0.0)), _b_snoise3({v}p+vec3(13.5)), "
                   "_b_snoise3({v}p+vec3(27.1)));".format(v=v, d=dist))
        if out.name == "Color":
            self._line("vec3 {v}c = vec3(_b_fbm3({v}p,{det},{r},{l}), "
                       "_b_fbm3({v}p+vec3(41.0),{det},{r},{l}), "
                       "_b_fbm3({v}p+vec3(97.0),{det},{r},{l}));".format(
                           v=v, det=detail, r=rough, l=lac))
            return "vec4({v}c, 1.0)".format(v=v)
        self._line("float {v} = _b_fbm3({v}p, {det}, {r}, {l});".format(
            v=v, det=detail, r=rough, l=lac))
        return v

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
    elif t == "MAP_RANGE": v = [getattr(n, "interpolation_type", "LINEAR"), str(getattr(n, "clamp", True)), getattr(n, "data_type", "FLOAT")]
    elif t in ("CURVE_RGB", "CURVE_FLOAT", "CURVE_VEC"):
        try:
            for cv in n.mapping.curves:
                for pt in cv.points:
                    v.append("{:.4f}:{:.4f}".format(pt.location[0], pt.location[1]))
        except Exception:
            pass
    elif t == "TEX_MAGIC": v = [str(getattr(n, "turbulence_depth", 2))]
    elif t == "TEX_BRICK": v = [str(getattr(n, "offset", 0.5)), str(getattr(n, "offset_frequency", 2)),
                               str(getattr(n, "squash", 1.0)), str(getattr(n, "squash_frequency", 2))]
    elif t == "TEX_WAVE": v = [getattr(n, "wave_type", "BANDS"), getattr(n, "bands_direction", "X"),
                              getattr(n, "rings_direction", "X"), getattr(n, "wave_profile", "SIN")]
    elif t == "TEX_GRADIENT": v = [getattr(n, "gradient_type", "LINEAR")]
    elif t in ("SEPARATE_COLOR", "COMBINE_COLOR"): v = [getattr(n, "mode", "RGB")]
    elif t == "TEX_VORONOI": v = [getattr(n, "feature", "F1"), getattr(n, "distance", "EUCLIDEAN"),
                                  getattr(n, "voronoi_dimensions", "3D")]
    elif t == "TEX_IMAGE": v = ["img=" + (n.image.name if n.image else "")]
    elif t == "VALTORGB":
        cr = n.color_ramp
        v = [getattr(cr, "interpolation", "LINEAR"), str(len(cr.elements))]
        for e in cr.elements:
            v.append("{:.4f}:{:.3f},{:.3f},{:.3f},{:.3f}".format(
                e.position, e.color[0], e.color[1], e.color[2], e.color[3]))
    return t + "|" + ",".join(v)
