"""
render_gl.py — headless EWA splat renderer on Mesa/llvmpipe software GL.
Validates the covariance-projection + gaussian-falloff + sorted-alpha pipeline on real data,
producing a PNG I can inspect WITHOUT a GPU. The projection math here (done CPU-side for easy
debugging) is the reference the Blender vertex-shader port must match.
"""
import numpy as np, moderngl
from PIL import Image

def quat_to_R(q):
    # q: (N,4) as (w,x,y,z), assumed normalized
    w, x, y, z = q[:,0], q[:,1], q[:,2], q[:,3]
    R = np.empty((len(q), 3, 3), np.float32)
    R[:,0,0]=1-2*(y*y+z*z); R[:,0,1]=2*(x*y-w*z);   R[:,0,2]=2*(x*z+w*y)
    R[:,1,0]=2*(x*y+w*z);   R[:,1,1]=1-2*(x*x+z*z); R[:,1,2]=2*(y*z-w*x)
    R[:,2,0]=2*(x*z-w*y);   R[:,2,1]=2*(y*z+w*x);   R[:,2,2]=1-2*(x*x+y*y)
    return R

def cov3d(scale, quat):
    R = quat_to_R(quat)                       # (N,3,3)
    M = R * scale[:, None, :]                 # R @ diag(scale)  == scale columns
    return M @ M.transpose(0,2,1)             # Σ = M Mᵀ  (N,3,3)

def look_at(cam, target, up):
    f = target - cam; f /= np.linalg.norm(f)
    r = np.cross(f, up); r /= (np.linalg.norm(r)+1e-9)
    u = np.cross(r, f)
    Rv = np.stack([r, u, f], 0).astype(np.float32)   # rows: right, up, forward (z=forward>0)
    return Rv, cam.astype(np.float32)

def render(splat, W=900, H=900, cam=None, target=None, up=(0,-1,0),
           fov_deg=50.0, three_sigma=3.0, out="/tmp/cactus_gl.png"):
    xyz, color, opac, scale, quat = (splat['xyz'], splat['color'], splat['opacity'],
                                     splat['scale'], splat['quat'])
    N = len(xyz)
    bb_min, bb_max = xyz.min(0), xyz.max(0); center = (bb_min+bb_max)*0.5
    ext = float(np.linalg.norm(bb_max-bb_min))
    up = np.array(up, np.float32)
    if target is None: target = center
    if cam is None:    cam = center + np.array([0, 0, -ext*1.1], np.float32)  # in front along -z-ish
    Rv, campos = look_at(np.array(cam,np.float32), np.array(target,np.float32), up)

    # view-space coords: t = Rv @ (world - cam)
    t = (xyz - campos) @ Rv.T                        # (N,3), z = depth (forward, >0 in front)
    front = t[:,2] > ext*0.02
    f = 0.5*H/np.tan(np.radians(fov_deg)*0.5)        # focal in pixels (fx=fy=f)

    Sig = cov3d(scale, quat)                         # (N,3,3)
    tz = t[:,2]; tx = t[:,0]; ty = t[:,1]
    J = np.zeros((N,2,3), np.float32)
    J[:,0,0]=f/tz; J[:,0,2]=-f*tx/(tz*tz)
    J[:,1,1]=f/tz; J[:,1,2]=-f*ty/(tz*tz)
    T = J @ Rv                                       # (N,2,3)  (Rv is the EWA 'W')
    cov2 = T @ Sig @ T.transpose(0,2,1)              # (N,2,2)
    a = cov2[:,0,0]+0.3; b = cov2[:,0,1]; c = cov2[:,1,1]+0.3    # low-pass filter

    # eigen of [[a,b],[b,c]]
    tr = a+c; det = a*c - b*b; mid = 0.5*tr
    disc = np.sqrt(np.maximum(mid*mid - det, 0))
    l1 = mid+disc; l2 = np.maximum(mid-disc, 1e-9)
    r1 = three_sigma*np.sqrt(np.maximum(l1,0)); r2 = three_sigma*np.sqrt(l2)   # px radii
    # eigenvector for l1
    ex = b; ey = l1 - a
    en = np.sqrt(ex*ex+ey*ey)+1e-9
    e1 = np.stack([ex/en, ey/en], 1)
    small = en < 1e-6
    e1[small] = np.array([1.0,0.0], np.float32)
    e2 = np.stack([-e1[:,1], e1[:,0]], 1)

    # NDC center + axes (px -> NDC via 2/W, 2/H)
    ndc = np.stack([(f*tx/tz)/(W*0.5), (f*ty/tz)/(H*0.5)], 1).astype(np.float32)
    px2ndc = np.array([2.0/W, 2.0/H], np.float32)
    axis1 = (e1 * r1[:,None]) * px2ndc               # (N,2) NDC
    axis2 = (e2 * r2[:,None]) * px2ndc

    keep = front & (np.abs(ndc[:,0])<1.5) & (np.abs(ndc[:,1])<1.5) & (r1<W)   # cull
    order = np.argsort(-tz[keep])                     # back-to-front among kept
    idx = np.nonzero(keep)[0][order]
    ndc, axis1, axis2 = ndc[idx], axis1[idx], axis2[idx]
    col, op = color[idx], opac[idx]
    M = len(idx)

    try:
        ctx = moderngl.create_context(standalone=True, backend='egl')
    except Exception:
        ctx = moderngl.create_standalone_context()
    prog = ctx.program(
      vertex_shader="""#version 330
      in vec2 corner;
      in vec2 iNdc; in vec2 iA1; in vec2 iA2; in vec3 iCol; in float iOp;
      out vec2 vC; out vec3 vCol; out float vOp;
      void main(){ vC=corner; vCol=iCol; vOp=iOp;
        vec2 p = iNdc + corner.x*iA1 + corner.y*iA2;
        gl_Position = vec4(p, 0.0, 1.0); }""",
      fragment_shader="""#version 330
      in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
      void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g;
        if(al<0.003) discard; o=vec4(vCol*al, al); }""")   # premultiplied
    quad = ctx.buffer(np.array([-1,-1, 1,-1, 1,1, -1,1],'f4').tobytes())
    inst = np.concatenate([ndc, axis1, axis2, col, op[:,None]],1).astype('f4')
    ibuf = ctx.buffer(inst.tobytes())
    vao = ctx.vertex_array(prog, [(quad,'2f','corner'),
        (ibuf,'2f 2f 2f 3f 1f/i','iNdc','iA1','iA2','iCol','iOp')])
    fbo = ctx.simple_framebuffer((W,H)); fbo.use()
    fbo.clear(0.06,0.06,0.07,1.0)
    ctx.enable(moderngl.BLEND)
    ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA   # premultiplied over
    vao.render(moderngl.TRIANGLE_FAN, instances=M)

    raw = np.frombuffer(fbo.read(components=4), np.uint8).reshape(H,W,4)
    Image.fromarray(raw[::-1]).save(out)              # flip Y for image orientation
    return dict(out=out, drawn=M, total=N, culled=N-M)

if __name__ == "__main__":
    import sys, splat_io as S
    d = S.load_ply(sys.argv[1] if len(sys.argv)>1 else
                   "/mnt/user-data/uploads/cactus_splat3_30kSteps_142k_splats.ply")
    r = render(d)
    print("drawn %d / %d (culled %d) -> %s" % (r['drawn'], r['total'], r['culled'], r['out']))
