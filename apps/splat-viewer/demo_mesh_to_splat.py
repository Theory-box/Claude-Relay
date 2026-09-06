"""Build a detailed rock, convert to splats, render 3 comparison panels: mesh / albedo-splats / lit-splats."""
import numpy as np, trimesh, moderngl
from PIL import Image, ImageDraw
from mesh_to_splat import mesh_to_splats
from render_gl import look_at, render as render_splats

rng = np.random.default_rng(3)

# ---- fractal 3D noise (sum of sinusoids) ----
DIRS = rng.normal(size=(8,3)); DIRS/=np.linalg.norm(DIRS,axis=1,keepdims=True)
FREQ = np.array([1.3,2.1,3.7,5.9,8.3,11.0,15.0,21.0]); PH=rng.uniform(0,6.28,8); AMP=0.7**np.arange(8)
def fnoise(P):  # P:(N,3)->(N,) in ~[-1,1]
    s=np.zeros(len(P))
    for k in range(8): s+=AMP[k]*np.sin(FREQ[k]*(P@DIRS[k])+PH[k])
    return s/np.sum(AMP)

# ---- build the rock ----
m = trimesh.creation.icosphere(subdivisions=5)
V = np.asarray(m.vertices, np.float64)
disp = fnoise(V*1.5)
V *= (1.0 + 0.28*disp)[:,None]            # displace radius
m = trimesh.Trimesh(vertices=V, faces=m.faces); m.fix_normals()
ext = float(np.linalg.norm(m.bounds[1]-m.bounds[0])); ctr = m.bounds.mean(0)
print("rock: %d verts  %d faces  extent %.2f" % (len(m.vertices), len(m.faces), ext))

# ---- procedural rock albedo ----
def albedo_fn(P, Nn):
    t = np.clip(fnoise(P*4.0)*0.5+0.5, 0, 1)             # mottling
    dark = np.array([0.16,0.14,0.12]); light = np.array([0.62,0.57,0.5])
    base = dark[None]+(light-dark)[None]*t[:,None]
    grit = (rng.random((len(P),1))-0.5)*0.06
    return base+grit

# ---- lit colour (hemisphere ambient + key diffuse) baked into splats ----
KEY = np.array([0.5,0.8,0.35]); KEY/=np.linalg.norm(KEY)
def lit(colors, normals):
    ndl = np.clip(normals@KEY, 0, 1)
    hemi = 0.35+0.25*(normals[:,1]*0.5+0.5)              # sky brighter on top
    return np.clip(colors*(hemi[:,None]+0.75*ndl[:,None]), 0, 1)

sp = mesh_to_splats(m, n=70000, albedo_fn=albedo_fn)
sp_lit = dict(sp); sp_lit['color'] = lit(sp['color'], sp['normal']).astype(np.float32)

# ---- shared camera ----
W=H=760
cam = ctr + np.array([ext*0.55, ext*0.35, -ext*1.15], np.float32)
up  = np.array([0,1,0], np.float32)
fov = 45.0

# ---- mesh reference render (triangles, same lit shading, same camera) ----
def render_mesh(mesh, out):
    Rv, campos = look_at(cam.astype(np.float32), ctr.astype(np.float32), up)
    f = 0.5*H/np.tan(np.radians(fov)*0.5); near,far = ext*0.05, ext*6
    try: ctx=moderngl.create_context(standalone=True, backend='egl')
    except Exception: ctx=moderngl.create_standalone_context()
    a = (far+0*near)/(far-near); b = (2*far*near)/(near-far)  # depth remap coeffs (z-fwd-positive)
    prog=ctx.program(
      vertex_shader="""#version 330
      in vec3 pos; in vec3 nrm; out vec3 vN;
      uniform vec3 R0,R1,R2,uCam; uniform float uF; uniform vec2 uVP; uniform float uA,uB;
      void main(){ vN=nrm; vec3 d=pos-uCam; vec3 t=vec3(dot(R0,d),dot(R1,d),dot(R2,d));
        vec2 ndc=vec2((uF*t.x/t.z)/(uVP.x*0.5),(uF*t.y/t.z)/(uVP.y*0.5));
        gl_Position=vec4(ndc*t.z, uA*t.z+uB, t.z); }""",
      fragment_shader="""#version 330
      in vec3 vN; out vec4 o; uniform vec3 uKey;
      void main(){ vec3 n=normalize(vN); float ndl=clamp(dot(n,uKey),0.0,1.0);
        float hemi=0.35+0.25*(n.y*0.5+0.5); float s=hemi+0.75*ndl;
        vec3 base=vec3(0.42,0.38,0.34); o=vec4(base*s,1.0); }""")
    prog['R0'].value=tuple(Rv[0]);prog['R1'].value=tuple(Rv[1]);prog['R2'].value=tuple(Rv[2])
    prog['uCam'].value=tuple(campos);prog['uF'].value=float(f);prog['uVP'].value=(float(W),float(H))
    prog['uA'].value=float(a);prog['uB'].value=float(b);prog['uKey'].value=tuple(KEY)
    vbo=ctx.buffer(np.asarray(mesh.vertices,'f4').tobytes())
    nbo=ctx.buffer(np.asarray(mesh.vertex_normals,'f4').tobytes())
    ibo=ctx.buffer(np.asarray(mesh.faces,'i4').tobytes())
    vao=ctx.vertex_array(prog,[(vbo,'3f','pos'),(nbo,'3f','nrm')],ibo)
    fbo=ctx.simple_framebuffer((W,H)); fbo.use(); fbo.clear(0.06,0.06,0.07,1.0)
    ctx.enable(moderngl.DEPTH_TEST)
    vao.render(moderngl.TRIANGLES)
    raw=np.frombuffer(fbo.read(components=4),np.uint8).reshape(H,W,4)
    Image.fromarray(raw[::-1]).save(out); return out

render_mesh(m, "/tmp/panel_mesh.png")
render_splats(sp,     W,H, cam=cam, target=ctr, up=up, fov_deg=fov, three_sigma=2.6, out="/tmp/panel_alb.png")
render_splats(sp_lit, W,H, cam=cam, target=ctr, up=up, fov_deg=fov, three_sigma=2.6, out="/tmp/panel_lit.png")

# ---- combine ----
labels=["1. SOURCE MESH (lit)","2. SPLATS raw albedo","3. SPLATS lit (baked)"]
imgs=[Image.open(p).convert("RGB") for p in ["/tmp/panel_mesh.png","/tmp/panel_alb.png","/tmp/panel_lit.png"]]
pad=10; combo=Image.new("RGB",(W*3+pad*4, H+50+pad*2),(20,20,22)); dr=ImageDraw.Draw(combo)
for i,(im,lb) in enumerate(zip(imgs,labels)):
    x=pad+i*(W+pad); combo.paste(im,(x,50)); dr.text((x+8,18),lb,fill=(230,230,230))
combo.save("/tmp/splat_compare.png")
print("splats:", sp['count'], "-> /tmp/splat_compare.png")
