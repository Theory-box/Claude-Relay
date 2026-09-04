# tests/test_gl_nodes.py — per-node OUTPUT verification on the CPU GL harness.
# Grows as nodes are ported. Each check renders real GLSL and asserts pixel values.
import bpy, sys, os, importlib.util
_here=os.path.dirname(os.path.realpath(__file__))
spec=importlib.util.spec_from_file_location("gl_harness", os.path.join(_here,"gl_harness.py"))
H=importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
F=[]
def check(c,m): print(("  PASS " if c else "  FAIL ")+m); (F.append(m) if not c else None)

def base(name):
    m=bpy.data.materials.new(name); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled')
    t.links.new(b.outputs['BSDF'],o.inputs['Surface']); return m,t,b
def rgb(t, col):
    n=t.nodes.new('ShaderNodeRGB'); n.outputs[0].default_value=col; return n

# --- RGB to BW (Rec.709 luminance) ---
def bw(col):
    m,t,b=base('bw'); src=rgb(t,col); n=t.nodes.new('ShaderNodeRGBToBW')
    t.links.new(src.outputs[0], n.inputs['Color']); t.links.new(n.outputs[0], b.inputs['Base Color'])
    px,_=H.render_material(m,size=4); return px[...,0].mean()
check(abs(bw((1,1,1,1))-1.0)<0.02, "RGBtoBW white = 1.0")
check(abs(bw((1,0,0,1))-0.2127)<0.02, "RGBtoBW red = 0.213")
check(abs(bw((0,1,0,1))-0.7152)<0.02, "RGBtoBW green = 0.715")
check(abs(bw((0,0,1,1))-0.0722)<0.02, "RGBtoBW blue = 0.072")

# --- Noise (coherent, varies across UVs, in 0..1) ---
def noise_stats(scale=6.0, detail=3.0, color=False):
    m,t,b=base('noise'); n=t.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value=scale; n.inputs['Detail'].default_value=detail
    out='Color' if color else 'Fac'
    t.links.new(n.outputs[out], b.inputs['Base Color'])
    px,_=H.render_material(m,size=32); return px
np_px=noise_stats()
check(np_px[...,0].std()>0.05, "Noise varies across the surface")
check(np_px[...,0].min()>=0.0 and np_px[...,0].max()<=1.0, "Noise output in 0..1")
# higher scale -> finer detail -> more local variation (more high-freq)
lo=noise_stats(scale=2.0)[...,0]; hi=noise_stats(scale=20.0)[...,0]
import numpy as np
def hf(a): return np.abs(np.diff(a,axis=1)).mean()
check(hf(hi)>hf(lo), "higher Noise scale = higher spatial frequency")

# --- Voronoi F1 (Distance varies, in range; Color varies) ---
def vor(outn, scale=5.0):
    m,t,b=base('vor'); n=t.nodes.new('ShaderNodeTexVoronoi'); n.inputs['Scale'].default_value=scale
    t.links.new(n.outputs[outn], b.inputs['Base Color']); px,_=H.render_material(m,size=32); return px
vd=vor('Distance')
check(vd[...,0].std()>0.05 and vd[...,0].min()>=0.0, "Voronoi Distance varies, >=0")
check(vor('Color')[...,0].std()>0.03, "Voronoi Color varies per cell")

# --- Checker (exact binary) ---
def checker():
    m,t,b=base('ck'); n=t.nodes.new('ShaderNodeTexChecker'); n.inputs['Scale'].default_value=4.0
    t.links.new(n.outputs['Fac'], b.inputs['Base Color']); px,_=H.render_material(m,size=32); return px[...,0]
u=set(np.unique(np.round(checker(),2)))
check(u.issubset({0.0,1.0}) and len(u)==2, "Checker Fac is exactly binary {0,1}")

# --- Gradient LINEAR == UV.x ---
def grad():
    m,t,b=base('gr'); n=t.nodes.new('ShaderNodeTexGradient')
    t.links.new(n.outputs['Fac'], b.inputs['Base Color']); px,_=H.render_material(m,size=16); return px[...,0]
g=grad()
check(g[0,-1]>g[0,0]+0.5 and abs(g[0,0])<0.1, "Gradient LINEAR ramps with U (0->1)")

# --- Math: all ops handled + exact arithmetic ---
def mathop(op,a=0.6,b=0.2,c=0.5):
    m,t,bb=base('m'); n=t.nodes.new('ShaderNodeMath'); n.operation=op
    n.inputs[0].default_value=a; n.inputs[1].default_value=b
    if len(n.inputs)>2: n.inputs[2].default_value=c
    t.links.new(n.outputs[0], bb.inputs['Base Color']); px,r=H.render_material(m,size=2)
    return px[...,0].mean(), any('passthrough' in x for x in r.notes)
_MATH=['ADD','SUBTRACT','MULTIPLY','DIVIDE','MULTIPLY_ADD','POWER','LOGARITHM','SQRT','INVERSE_SQRT','ABSOLUTE','EXPONENT','MINIMUM','MAXIMUM','LESS_THAN','GREATER_THAN','SIGN','COMPARE','SMOOTH_MIN','SMOOTH_MAX','ROUND','FLOOR','CEIL','TRUNC','FRACT','MODULO','FLOORED_MODULO','WRAP','SNAP','PINGPONG','SINE','COSINE','TANGENT','ARCSINE','ARCCOSINE','ARCTANGENT','ARCTAN2','SINH','COSH','TANH','RADIANS','DEGREES']
check(not any(mathop(op)[1] for op in _MATH), "all {} Math ops handled (no passthrough)".format(len(_MATH)))
check(abs(mathop('ADD')[0]-0.8)<0.02 and abs(mathop('MULTIPLY')[0]-0.12)<0.02, "Math ADD/MULTIPLY exact")
check(abs(mathop('TRUNC',0.6)[0]-0.0)<0.02, "Math TRUNC(0.6)=0 (fixes TRUNCATE typo)")

# --- Vector Math: all ops handled ---
def vop(op):
    m,t,bb=base('vm'); n=t.nodes.new('ShaderNodeVectorMath'); n.operation=op
    for i,s in enumerate([s for s in n.inputs if s.type=='VECTOR']): s.default_value=(0.5+0.1*i,0.3,0.7)
    out='Value' if op in ('DOT_PRODUCT','DISTANCE','LENGTH') else 'Vector'
    t.links.new(n.outputs[out], bb.inputs['Base Color']); px,r=H.render_material(m,size=2)
    return any('passthrough' in x for x in r.notes)
_VM=['ADD','SUBTRACT','MULTIPLY','DIVIDE','MULTIPLY_ADD','CROSS_PRODUCT','PROJECT','REFLECT','REFRACT','FACEFORWARD','DOT_PRODUCT','DISTANCE','LENGTH','SCALE','NORMALIZE','ABSOLUTE','MINIMUM','MAXIMUM','FLOOR','CEIL','FRACTION','MODULO','WRAP','SNAP','SINE','COSINE','TANGENT']
check(not any(vop(op) for op in _VM), "all {} Vector Math ops handled".format(len(_VM)))

# --- White Noise ---
def wn():
    m,t,bb=base('wn'); tc=t.nodes.new('ShaderNodeTexCoord'); mp=t.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value=(50,50,50); n=t.nodes.new('ShaderNodeTexWhiteNoise')
    t.links.new(tc.outputs['UV'],mp.inputs['Vector']); t.links.new(mp.outputs['Vector'],n.inputs['Vector'])
    t.links.new(n.outputs['Value'], bb.inputs['Base Color']); px,_=H.render_material(m,size=32); return px[...,0]
check(wn().std()>0.1, "White Noise is high-frequency random")

# --- Wave (all 6 combos vary) ---
def wave(wt,prof):
    m,t,bb=base('wv'); n=t.nodes.new('ShaderNodeTexWave'); n.wave_type=wt; n.wave_profile=prof
    n.inputs['Scale'].default_value=3.0; t.links.new(n.outputs['Fac'], bb.inputs['Base Color'])
    px,_=H.render_material(m,size=32); return px[...,0].std()
check(all(wave(wt,pr)>0.05 for wt in ('BANDS','RINGS') for pr in ('SIN','SAW','TRI')), "Wave: all 6 band/ring x profile combos vary")

# --- Brick (mortar + brick regions) ---
def brick():
    m,t,bb=base('bk'); n=t.nodes.new('ShaderNodeTexBrick'); n.inputs['Scale'].default_value=3.0
    n.inputs['Mortar Size'].default_value=0.1; t.links.new(n.outputs['Fac'], bb.inputs['Base Color'])
    px,_=H.render_material(m,size=64); return set(np.unique(np.round(px[...,0],1)))
_bk=brick(); check(0.0 in _bk and 1.0 in _bk, "Brick Fac has brick(0) + mortar(1) regions")

# --- Magic (varies, channels differ) ---
def magic():
    m,t,bb=base('mg'); n=t.nodes.new('ShaderNodeTexMagic'); n.inputs['Scale'].default_value=4.0
    t.links.new(n.outputs['Color'], bb.inputs['Base Color']); px,_=H.render_material(m,size=32); return px
_mg=magic(); check(_mg[...,:3].std()>0.05 and abs(_mg[...,0].mean()-_mg[...,1].mean())>0.005, "Magic varies with distinct channels")

# --- Voronoi: all features + metrics ---
def vorf(feat, outn='Distance', metric='EUCLIDEAN'):
    m,t,bb=base('vf'); n=t.nodes.new('ShaderNodeTexVoronoi'); n.feature=feat; n.distance=metric
    n.inputs['Scale'].default_value=5.0; t.links.new(n.outputs[outn], bb.inputs['Base Color'])
    px,_=H.render_material(m,size=32); return px[...,0]
check(all(vorf(f).std()>0.05 for f in ('F1','F2','SMOOTH_F1','DISTANCE_TO_EDGE')), "Voronoi F1/F2/Smooth/Edge all vary")
check(all(vorf('F1','Distance',mm).std()>0.03 for mm in ('EUCLIDEAN','MANHATTAN','CHEBYCHEV','MINKOWSKI')), "Voronoi all 4 metrics work")

# --- RGB Curves (identity passthrough + darken) ---
def rgbcurve(dark=False):
    m,t,bb=base('rc'); im=t.nodes.new('ShaderNodeTexImage'); im.image=bpy.data.images.new('gc',16,16)
    cv=t.nodes.new('ShaderNodeRGBCurve'); cv.mapping.initialize()
    if dark:
        cv.mapping.curves[3].points[1].location=(1.0,0.5); cv.mapping.update()
    t.links.new(im.outputs['Color'], cv.inputs['Color']); t.links.new(cv.outputs['Color'], bb.inputs['Base Color'])
    px,_=H.render_material(m,size=16); return px[...,0]
_id=rgbcurve(False); _dk=rgbcurve(True)
check(abs(_id.mean()-0.5)<0.05, "RGB Curve identity passes gradient unchanged")
check(_dk.mean() < _id.mean()-0.1, "RGB Curve darken lowers output")

# --- Texture Coordinate Generated/Object/UV ---
def texco(outn):
    m,t,bb=base('tc'); n=t.nodes.new('ShaderNodeTexCoord')
    t.links.new(n.outputs[outn], bb.inputs['Base Color']); px,_=H.render_material(m,size=16); return px[...,0]
check(all(texco(o)[0,-1]>texco(o)[0,0]+0.4 for o in ('Generated','Object','UV')), "Tex Coord Generated/Object/UV map coordinates")

# --- Vector Rotate (identity at 0; transforms at 90deg) ---
def vrot(angle):
    m,t,bb=base('vr'); tc=t.nodes.new('ShaderNodeTexCoord'); r=t.nodes.new('ShaderNodeVectorRotate')
    r.rotation_type='Z_AXIS'; r.inputs['Angle'].default_value=angle; gr=t.nodes.new('ShaderNodeTexGradient')
    t.links.new(tc.outputs['UV'], r.inputs['Vector']); t.links.new(r.outputs['Vector'], gr.inputs['Vector'])
    t.links.new(gr.outputs['Color'], bb.inputs['Base Color']); px,_=H.render_material(m,size=16); return px[...,0]
_v0=vrot(0.0)
check(abs(_v0[0,-1]-_v0[0,0])>0.4, "Vector Rotate angle 0 = identity (horizontal gradient)")
check(abs(vrot(1.5708)[0,-1]-vrot(1.5708)[0,0]) < abs(_v0[0,-1]-_v0[0,0]), "Vector Rotate 90deg transforms coords")

# --- Principled Alpha (opacity) folds into output alpha ---
def palpha(a):
    m=bpy.data.materials.new('pa'); m.use_nodes=True; t=m.node_tree; t.nodes.clear()
    o=t.nodes.new('ShaderNodeOutputMaterial'); b=t.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value=(1,0,0,1); b.inputs['Alpha'].default_value=a
    t.links.new(b.outputs['BSDF'],o.inputs['Surface']); px,_=H.render_material(m,size=2); return px[0,0,3]
check(abs(palpha(0.4)-0.4)<0.05, "Principled Alpha 0.4 -> output alpha 0.4")
check(abs(palpha(1.0)-1.0)<0.05, "Principled Alpha 1.0 -> opaque")

print("SUMMARY: " + ("FAILED "+", ".join(F) if F else "ALL CHECKS PASSED"))
