"""
render_gl_vs.py — same EWA splat render as render_gl.py, but the projection (3D covariance,
Jacobian, 2D conic, eigen-axes, NDC placement) is done IN THE VERTEX SHADER from raw per-splat
data. CPU only does the back-to-front depth sort. This is the exact GLSL the Blender viewer will
use; validated here by diffing against the CPU reference image.
"""
import numpy as np, moderngl
from PIL import Image
from render_gl import look_at   # reuse the same camera basis

VERT = """#version 330
in vec2 corner;
in vec3 iCenter; in vec3 iScale; in vec4 iQuat; in vec3 iCol; in float iOp;
uniform vec3 uRow0, uRow1, uRow2;   // rows of world->view rotation Rv
uniform vec3 uCam;                  // camera position (world)
uniform float uF;                   // focal (px)
uniform vec2  uVP;                  // viewport W,H
uniform float uSigma;               // sigma multiplier (e.g. 3.0)
out vec2 vC; out vec3 vCol; out float vOp;
void main(){
    vC = corner; vCol = iCol; vOp = iOp;
    vec3 d = iCenter - uCam;
    vec3 t = vec3(dot(uRow0,d), dot(uRow1,d), dot(uRow2,d));   // view space (z = depth)
    if (t.z < uF*0.0 + 0.02) { gl_Position = vec4(2.0,2.0,2.0,1.0); return; }  // behind camera

    // 3D covariance Σ = (R·S)(R·S)ᵀ  from quaternion (w,x,y,z) + scale
    float w=iQuat.x, x=iQuat.y, y=iQuat.z, z=iQuat.w;
    vec3 c0 = vec3(1.0-2.0*(y*y+z*z), 2.0*(x*y+w*z),     2.0*(x*z-w*y));
    vec3 c1 = vec3(2.0*(x*y-w*z),     1.0-2.0*(x*x+z*z), 2.0*(y*z+w*x));
    vec3 c2 = vec3(2.0*(x*z+w*y),     2.0*(y*z-w*x),     1.0-2.0*(x*x+y*y));
    mat3 M = mat3(c0*iScale.x, c1*iScale.y, c2*iScale.z);
    mat3 Sig = M * transpose(M);

    // Jacobian of perspective projection (mat3 with zero 3rd row), column-major
    float iz = 1.0/t.z;
    mat3 J = mat3(vec3(uF*iz, 0.0, 0.0),
                  vec3(0.0, uF*iz, 0.0),
                  vec3(-uF*t.x*iz*iz, -uF*t.y*iz*iz, 0.0));
    mat3 Rv = mat3(vec3(uRow0.x,uRow1.x,uRow2.x),
                   vec3(uRow0.y,uRow1.y,uRow2.y),
                   vec3(uRow0.z,uRow1.z,uRow2.z));   // columns = math columns
    mat3 T = J * Rv;
    mat3 cov = T * Sig * transpose(T);
    float a = cov[0][0] + 0.3, b = cov[0][1], c = cov[1][1] + 0.3;   // 2D cov + low-pass

    float tr=a+c, det=a*c-b*b, mid=0.5*tr;
    float disc = sqrt(max(mid*mid-det, 0.0));
    float l1 = mid+disc, l2 = max(mid-disc, 1e-9);
    float r1 = uSigma*sqrt(max(l1,0.0)), r2 = uSigma*sqrt(l2);       // px radii
    vec2 e1 = vec2(b, l1-a);
    e1 = (length(e1) < 1e-6) ? vec2(1.0,0.0) : normalize(e1);
    vec2 e2 = vec2(-e1.y, e1.x);

    vec2 ndc  = vec2((uF*t.x*iz)/(uVP.x*0.5), (uF*t.y*iz)/(uVP.y*0.5));
    vec2 p2n  = vec2(2.0/uVP.x, 2.0/uVP.y);
    vec2 a1 = e1*r1*p2n, a2 = e2*r2*p2n;
    gl_Position = vec4(ndc + corner.x*a1 + corner.y*a2, 0.0, 1.0);
}"""

FRAG = """#version 330
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g;
    if(al<0.003) discard; o=vec4(vCol*al, al); }"""

def render(splat, W=900, H=900, cam=None, target=None, up=(0,-1,0),
           fov_deg=50.0, sigma=3.0, out="/tmp/cactus_gl_vs.png"):
    xyz = splat['xyz']
    bb_min, bb_max = xyz.min(0), xyz.max(0); center=(bb_min+bb_max)*0.5
    ext = float(np.linalg.norm(bb_max-bb_min)); up=np.array(up,np.float32)
    if target is None: target=center
    if cam is None:    cam = center + np.array([0,0,-ext*1.1], np.float32)
    Rv, campos = look_at(np.array(cam,np.float32), np.array(target,np.float32), up)
    f = 0.5*H/np.tan(np.radians(fov_deg)*0.5)

    # CPU: depth-sort only
    tz = (xyz - campos) @ Rv[2]
    order = np.argsort(-tz)
    inst = np.concatenate([xyz[order], splat['scale'][order], splat['quat'][order],
                           splat['color'][order], splat['opacity'][order][:,None]],1).astype('f4')

    try: ctx = moderngl.create_context(standalone=True, backend='egl')
    except Exception: ctx = moderngl.create_standalone_context()
    prog = ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
    prog['uRow0'].value=tuple(Rv[0]); prog['uRow1'].value=tuple(Rv[1]); prog['uRow2'].value=tuple(Rv[2])
    prog['uCam'].value=tuple(campos); prog['uF'].value=float(f)
    prog['uVP'].value=(float(W),float(H)); prog['uSigma'].value=float(sigma)
    quad = ctx.buffer(np.array([-1,-1,1,-1,1,1,-1,1],'f4').tobytes())
    ibuf = ctx.buffer(inst.tobytes())
    vao = ctx.vertex_array(prog, [(quad,'2f','corner'),
        (ibuf,'3f 3f 4f 3f 1f/i','iCenter','iScale','iQuat','iCol','iOp')])
    fbo = ctx.simple_framebuffer((W,H)); fbo.use(); fbo.clear(0.06,0.06,0.07,1.0)
    ctx.enable(moderngl.BLEND); ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
    vao.render(moderngl.TRIANGLE_FAN, instances=len(inst))
    raw = np.frombuffer(fbo.read(components=4), np.uint8).reshape(H,W,4)
    Image.fromarray(raw[::-1]).save(out)
    return out

if __name__ == "__main__":
    import splat_io as S
    d = S.load_ply("/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    out = render(d)
    # diff vs CPU reference
    import os
    ref_p = "/tmp/cactus_gl.png"
    if os.path.exists(ref_p):
        A = np.array(Image.open(out)).astype(np.int16)[...,:3]
        B = np.array(Image.open(ref_p)).astype(np.int16)[...,:3]
        diff = np.abs(A-B)
        print("vertex-shader vs CPU-reference:  mean|Δ|=%.2f  max|Δ|=%d  px>10=%.3f%%"
              % (diff.mean(), diff.max(), 100*(diff.max(2)>10).mean()))
    print("saved", out)
