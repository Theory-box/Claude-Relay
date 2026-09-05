"""
render_gl_tex.py — same EWA projection, but per-splat data is read from a 2D-TILED texture via
gl_InstanceID (texelFetch), NOT instance attributes. This mirrors Blender's gpu module, which has
no per-instance attribute divisors: the Blender viewer must pack splats into a texture and index by
gl_InstanceID. 4 RGBA32F texels per splat; texture width is a multiple of 4 so a splat never straddles
a row; both texture dims stay < 16384. Validated by diffing against the CPU reference image.
"""
import numpy as np, moderngl
from PIL import Image
from render_gl import look_at

TW = 4096  # texture width in texels (multiple of 4)

VERT = """#version 330
in vec2 corner;
uniform sampler2D uData; uniform int uTW;
uniform vec3 uRow0, uRow1, uRow2; uniform vec3 uCam;
uniform float uF; uniform vec2 uVP; uniform float uSigma;
out vec2 vC; out vec3 vCol; out float vOp;
ivec2 texat(int lin){ return ivec2(lin % uTW, lin / uTW); }
void main(){
    int base = gl_InstanceID*4;
    vec4 d0 = texelFetch(uData, texat(base+0), 0);   // cx cy cz sx
    vec4 d1 = texelFetch(uData, texat(base+1), 0);   // sy sz qw qx
    vec4 d2 = texelFetch(uData, texat(base+2), 0);   // qy qz cr cg
    vec4 d3 = texelFetch(uData, texat(base+3), 0);   // cb op . .
    vec3 iCenter = d0.xyz; vec3 iScale = vec3(d0.w, d1.x, d1.y);
    vec4 iQuat = vec4(d1.z, d1.w, d2.x, d2.y);        // w x y z
    vec3 iCol = vec3(d2.z, d2.w, d3.x); float iOp = d3.y;

    vC = corner; vCol = iCol; vOp = iOp;
    vec3 dp = iCenter - uCam;
    vec3 t = vec3(dot(uRow0,dp), dot(uRow1,dp), dot(uRow2,dp));
    if (t.z < 0.02) { gl_Position = vec4(2.0,2.0,2.0,1.0); return; }

    float w=iQuat.x, x=iQuat.y, y=iQuat.z, z=iQuat.w;
    vec3 c0 = vec3(1.0-2.0*(y*y+z*z), 2.0*(x*y+w*z),     2.0*(x*z-w*y));
    vec3 c1 = vec3(2.0*(x*y-w*z),     1.0-2.0*(x*x+z*z), 2.0*(y*z+w*x));
    vec3 c2 = vec3(2.0*(x*z+w*y),     2.0*(y*z-w*x),     1.0-2.0*(x*x+y*y));
    mat3 M = mat3(c0*iScale.x, c1*iScale.y, c2*iScale.z);
    mat3 Sig = M * transpose(M);
    float iz = 1.0/t.z;
    mat3 J = mat3(vec3(uF*iz,0,0), vec3(0,uF*iz,0), vec3(-uF*t.x*iz*iz, -uF*t.y*iz*iz, 0));
    mat3 Rv = mat3(vec3(uRow0.x,uRow1.x,uRow2.x), vec3(uRow0.y,uRow1.y,uRow2.y), vec3(uRow0.z,uRow1.z,uRow2.z));
    mat3 cov = (J*Rv) * Sig * transpose(J*Rv);
    float a=cov[0][0]+0.3, b=cov[0][1], c=cov[1][1]+0.3;
    float tr=a+c, det=a*c-b*b, mid=0.5*tr, disc=sqrt(max(mid*mid-det,0.0));
    float l1=mid+disc, l2=max(mid-disc,1e-9);
    float r1=uSigma*sqrt(max(l1,0.0)), r2=uSigma*sqrt(l2);
    vec2 e1 = vec2(b, l1-a); e1 = (length(e1)<1e-6)? vec2(1,0):normalize(e1);
    vec2 e2 = vec2(-e1.y, e1.x);
    vec2 ndc = vec2((uF*t.x*iz)/(uVP.x*0.5), (uF*t.y*iz)/(uVP.y*0.5));
    vec2 p2n = vec2(2.0/uVP.x, 2.0/uVP.y);
    gl_Position = vec4(ndc + corner.x*e1*r1*p2n + corner.y*e2*r2*p2n, 0.0, 1.0);
}"""
FRAG = """#version 330
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.003) discard; o=vec4(vCol*al,al); }"""

def pack(splat, order):
    """Pack sorted splats into a (TH,TW,4) float32 texture; 4 texels/splat."""
    N = len(order)
    xyz=splat['xyz'][order]; sc=splat['scale'][order]; q=splat['quat'][order]
    cl=splat['color'][order]; op=splat['opacity'][order]
    tex = np.zeros((N*4, 4), np.float32)
    tex[0::4] = np.column_stack([xyz, sc[:,0]])
    tex[1::4] = np.column_stack([sc[:,1], sc[:,2], q[:,0], q[:,1]])
    tex[2::4] = np.column_stack([q[:,2], q[:,3], cl[:,0], cl[:,1]])
    tex[3::4] = np.column_stack([cl[:,2], op, np.zeros(N,np.float32), np.zeros(N,np.float32)])
    TH = (N*4 + TW - 1)//TW
    full = np.zeros((TH*TW,4), np.float32); full[:N*4]=tex
    return full.reshape(TH,TW,4), TH

def render(splat, W=900,H=900, cam=None, target=None, up=(0,-1,0), fov_deg=50.0, sigma=3.0,
           out="/tmp/cactus_gl_tex.png"):
    xyz=splat['xyz']; bb_min,bb_max=xyz.min(0),xyz.max(0); center=(bb_min+bb_max)*0.5
    ext=float(np.linalg.norm(bb_max-bb_min)); up=np.array(up,np.float32)
    if target is None: target=center
    if cam is None: cam=center+np.array([0,0,-ext*1.1],np.float32)
    Rv,campos = look_at(np.array(cam,np.float32),np.array(target,np.float32),up)
    f = 0.5*H/np.tan(np.radians(fov_deg)*0.5)
    tz = (xyz-campos) @ Rv[2]; order = np.argsort(-tz)
    texdata, TH = pack(splat, order); N=len(order)

    try: ctx=moderngl.create_context(standalone=True, backend='egl')
    except Exception: ctx=moderngl.create_standalone_context()
    prog=ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
    tex=ctx.texture((TW,TH),4,texdata.tobytes(),dtype='f4'); tex.filter=(moderngl.NEAREST,moderngl.NEAREST)
    tex.use(0); prog['uData'].value=0; prog['uTW'].value=TW
    prog['uRow0'].value=tuple(Rv[0]); prog['uRow1'].value=tuple(Rv[1]); prog['uRow2'].value=tuple(Rv[2])
    prog['uCam'].value=tuple(campos); prog['uF'].value=float(f); prog['uVP'].value=(float(W),float(H))
    prog['uSigma'].value=float(sigma)
    quad=ctx.buffer(np.array([-1,-1,1,-1,1,1,-1,1],'f4').tobytes())
    vao=ctx.vertex_array(prog,[(quad,'2f','corner')])
    fbo=ctx.simple_framebuffer((W,H)); fbo.use(); fbo.clear(0.06,0.06,0.07,1.0)
    ctx.enable(moderngl.BLEND); ctx.blend_func=moderngl.ONE,moderngl.ONE_MINUS_SRC_ALPHA
    vao.render(moderngl.TRIANGLE_FAN, instances=N)
    raw=np.frombuffer(fbo.read(components=4),np.uint8).reshape(H,W,4)
    Image.fromarray(raw[::-1]).save(out)
    return out, TH

if __name__=="__main__":
    import splat_io as S, os
    d=S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    out,TH=render(d)
    print("packed into %dx%d texture (%d texels/splat, both < 16384)"%(TW,TH,4))
    ref="/tmp/cactus_gl.png"
    if os.path.exists(ref):
        A=np.array(Image.open(out)).astype(np.int16)[...,:3]; B=np.array(Image.open(ref)).astype(np.int16)[...,:3]
        diff=np.abs(A-B); print("texture-fed vs CPU-reference:  mean|d|=%.2f  max|d|=%d  px>10=%.4f%%"%(diff.mean(),diff.max(),100*(diff.max(2)>10).mean()))
    print("saved",out)
