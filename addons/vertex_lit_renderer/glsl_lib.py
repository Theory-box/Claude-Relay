# vertex_lit_renderer/glsl_lib.py
"""
Modular GLSL helper library for the node transpiler.

Each helper group is a named CHUNK: (glsl_code, [provided_function_names]).
`collect(body_glsl)` scans the generated shader body and pulls in ONLY the chunks
whose functions are actually referenced — transitively (a chunk's own code is
scanned too, so e.g. Perlin drags in the hash chunk automatically). Chunks are
emitted in dependency order (a function is always defined before it is used).

This keeps every material shader lean (a plain image material no longer compiles
the whole noise/voronoi/brick library) and keeps the GLSL easy to edit: to tweak
a node's math, edit its chunk here; to add a node, add a chunk + wire a handler.

Adding a chunk:
  1. write the GLSL as a triple-quoted constant,
  2. register it in CHUNKS with the function names it defines,
  3. put its name in CHUNK_ORDER after anything it depends on.
"""

# ---- colour space -----------------------------------------------------------
_HSV = """
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
"""

# ---- safe divide ------------------------------------------------------------
_SDIV = """
float _sdiv(float a, float b){ return (b == 0.0) ? 0.0 : a / b; }
"""

# ---- Mix-node blend modes (Overlay/Soft-Light + HSV modes; needs _HSV) -------
_BLEND = """
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

# ---- Math-node helpers ------------------------------------------------------
_MATHX = """
float _bsmin(float a, float b, float k){ if(k!=0.0){ float h=max(k-abs(a-b),0.0)/k; return min(a,b)-h*h*h*k*(1.0/6.0); } return min(a,b); }
float _bsmax(float a, float b, float k){ return -_bsmin(-a,-b,k); }
float _bwrapf(float v, float mx, float mn){ float r=mx-mn; return (r!=0.0)? v-r*floor((v-mn)/r) : mn; }
vec3  _bwrap3(vec3 v, vec3 mx, vec3 mn){ return vec3(_bwrapf(v.x,mx.x,mn.x),_bwrapf(v.y,mx.y,mn.y),_bwrapf(v.z,mx.z,mn.z)); }
float _bpingpong(float a, float s){ return (s!=0.0)? abs(fract((a-s)/(s*2.0))*s*2.0-s) : 0.0; }
float _btmod(float a, float b){ return (b!=0.0)? a-b*trunc(a/b) : 0.0; }
"""

# ---- Curve lookup -----------------------------------------------------------
_LUT = """
float _lut65(float a[65], float x){ x=clamp(x,0.0,1.0)*64.0; int i=int(x); float f=x-float(i); return mix(a[i], a[min(i+1,64)], f); }
"""

# ---- Blender hash (Jenkins lookup3 + float variants), verbatim --------------
_HASH = """
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
float hash_uint_to_float(uint kx){ return float(hash_uint(kx))/float(0xFFFFFFFFu); }
float hash_uint2_to_float(uint kx,uint ky){ return float(hash_uint2(kx,ky))/float(0xFFFFFFFFu); }
float hash_uint3_to_float(uint kx,uint ky,uint kz){ return float(hash_uint3(kx,ky,kz))/float(0xFFFFFFFFu); }
float hash_uint4_to_float(uint kx,uint ky,uint kz,uint kw){ return float(hash_uint4(kx,ky,kz,kw))/float(0xFFFFFFFFu); }
float hash_float_to_float(float k){ return hash_uint_to_float(floatBitsToUint(k)); }
float hash_vec2_to_float(vec2 k){ return hash_uint2_to_float(floatBitsToUint(k.x),floatBitsToUint(k.y)); }
float hash_vec3_to_float(vec3 k){ return hash_uint3_to_float(floatBitsToUint(k.x),floatBitsToUint(k.y),floatBitsToUint(k.z)); }
float hash_vec4_to_float(vec4 k){ return hash_uint4_to_float(floatBitsToUint(k.x),floatBitsToUint(k.y),floatBitsToUint(k.z),floatBitsToUint(k.w)); }
vec3 hash_vec3_to_vec3(vec3 k){ return vec3(hash_vec3_to_float(k), hash_vec4_to_float(vec4(k,1.0)), hash_vec4_to_float(vec4(k,2.0))); }
"""

# ---- Blender Perlin noise + fbm + random offsets (needs _HASH) --------------
_PERLIN = """
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
float _b_snoise3(vec3 p){ return 0.9820 * _b_perlin3(_b_cmod3(p, 100000.0)); }
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
/* random coord offset seed (verbatim Blender: components in [100,200]) */
vec3 _b_rvec3(float seed){
    return vec3(100.0 + hash_vec2_to_float(vec2(seed, 0.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 1.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 2.0)) * 100.0);
}
"""

# ---- PCG integer hash (Voronoi) ---------------------------------------------
_PCG = """
ivec3 _hash_pcg3d(ivec3 v){
    v = v*1664525 + 1013904223;
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    v = v ^ (v >> 16);
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    return v;
}
vec3 hash_int3_to_vec3(ivec3 k){ ivec3 h=_hash_pcg3d(k); return vec3(h & 0x7fffffff) * (1.0/float(0x7fffffff)); }
"""

# ---- Blender Voronoi 3D (needs _PCG) ----------------------------------------
_VORONOI = """
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
"""

# ---- integer_noise (Brick) --------------------------------------------------
_INTNOISE = """
float integer_noise(int n){
    uint nn = (uint(n) + 1013u) & 0x7fffffffu;
    nn = (nn >> 13u) ^ nn;
    nn = (uint(nn * (nn * nn * 60493u + 19990303u)) + 1376312589u) & 0x7fffffffu;
    return 0.5 * (float(nn) / 1073741824.0);
}
"""

# ---- Blender Brick (needs _INTNOISE) ----------------------------------------
_BRICK = """
vec2 _b_brick(vec3 p, float mortar_size, float mortar_smooth, float bias, float brick_width,
              float row_height, float offset_amount, int offset_freq, float squash_amount, int squash_freq){
    float rh = max(row_height, 1e-4);
    int rownum = int(floor(p.y / rh));
    float offset = 0.0; float bw = max(brick_width, 1e-4);
    if(offset_freq != 0 && squash_freq != 0){
        bw *= (rownum % squash_freq != 0) ? 1.0 : squash_amount;
        bw = max(bw, 1e-4);
        offset = (rownum % offset_freq != 0) ? 0.0 : (bw * offset_amount);
    }
    int bricknum = int(floor((p.x + offset) / bw));
    float x = (p.x + offset) - bw * float(bricknum);
    float y = p.y - rh * float(rownum);
    float tint = clamp(integer_noise((rownum << 16) + (bricknum & 0xFFFF)) + bias, 0.0, 1.0);
    float md = min(min(x, y), min(bw - x, rh - y));
    float fac;
    if(md >= mortar_size) fac = 0.0;
    else if(mortar_smooth == 0.0) fac = 1.0;
    else { md = 1.0 - md / max(mortar_size, 1e-6); fac = smoothstep(0.0, mortar_smooth, md); }
    return vec2(tint, fac);
}
"""

# name -> (code, [function names it defines])
CHUNKS = {
    "hsv":       (_HSV,      ["_rgb2hsv", "_hsv2rgb"]),
    "sdiv":      (_SDIV,     ["_sdiv"]),
    "blend":     (_BLEND,    ["_overlay", "_softlight", "_bl_hue", "_bl_sat", "_bl_col", "_bl_val"]),
    "mathx":     (_MATHX,    ["_bsmin", "_bsmax", "_bwrapf", "_bwrap3", "_bpingpong", "_btmod"]),
    "lut":       (_LUT,      ["_lut65"]),
    "hash":      (_HASH,     ["hash_uint", "hash_vec2_to_float", "hash_vec3_to_float",
                              "hash_vec4_to_float", "hash_vec3_to_vec3", "hash_float_to_float",
                              "hash_uint2_to_float", "hash_uint3_to_float", "hash_uint4_to_float"]),
    "perlin":    (_PERLIN,   ["_b_fbm3", "_b_snoise3", "_b_perlin3", "_b_int3h", "_b_grad",
                              "_b_trimix", "_b_fade", "_b_cmod", "_b_negif", "_b_rvec3"]),
    "pcg":       (_PCG,      ["_hash_pcg3d", "hash_int3_to_vec3"]),
    "voronoi":   (_VORONOI,  ["_vor_dist", "_vor_f1", "_vor_smooth", "_vor_f2", "_vor_edge"]),
    "intnoise":  (_INTNOISE, ["integer_noise"]),
    "brick":     (_BRICK,    ["_b_brick"]),
}

# emission order: a chunk must come AFTER every chunk it depends on
CHUNK_ORDER = ["sdiv", "lut", "mathx", "hsv", "blend",
               "hash", "perlin", "pcg", "voronoi", "intnoise", "brick"]


def collect(body_glsl):
    """Return the concatenation of only the helper chunks `body_glsl` needs
    (transitively), in dependency order."""
    included = set()
    combined = body_glsl
    # iterate until stable (chunks reference other chunks' functions)
    for _ in range(len(CHUNKS) + 1):
        added = False
        for name, (code, provides) in CHUNKS.items():
            if name in included:
                continue
            if any(fn in combined for fn in provides):
                included.add(name)
                combined += "\n" + code
                added = True
        if not added:
            break
    return "\n".join(CHUNKS[n][0] for n in CHUNK_ORDER if n in included)


# Full library (every chunk) — used only as a fallback / for debugging.
ALL = "\n".join(CHUNKS[n][0] for n in CHUNK_ORDER)
