bl_info = {
    "name": "Mesh to Splat",
    "author": "Claude Relay",
    "version": (0, 1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Splat",
    "description": "Convert the active mesh into a 3D gaussian-splat cloud (sampled from its texture) and view it live.",
    "category": "Object",
}

import bpy, gpu, numpy as np, time
from gpu.types import GPUShader, GPUTexture, Buffer
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

# =====================================================================================
# sampling core (pure numpy — validated headless)
# =====================================================================================
def _sample_triangles(tri_pos, count, seed=0):
    rng = np.random.default_rng(seed)
    e1 = tri_pos[:,1]-tri_pos[:,0]; e2 = tri_pos[:,2]-tri_pos[:,0]
    area = 0.5*np.linalg.norm(np.cross(e1,e2), axis=1)
    tot = float(area.sum())
    p = area/(area.sum()+1e-12)
    idx = rng.choice(len(tri_pos), size=count, p=p)
    u = rng.random(count); v = rng.random(count)
    over = u+v > 1; u[over] = 1-u[over]; v[over] = 1-v[over]
    bary = np.stack([1-u-v, u, v], 1).astype(np.float32)
    return idx, bary, tot

def _bilinear(img, uv):
    h, w = img.shape[:2]
    u = (uv[:,0] % 1.0)*(w-1); v = (uv[:,1] % 1.0)*(h-1)
    x0 = np.floor(u).astype(int); y0 = np.floor(v).astype(int)
    x1 = np.minimum(x0+1, w-1); y1 = np.minimum(y0+1, h-1)
    fx = (u-x0)[:,None]; fy = (v-y0)[:,None]
    return (img[y0,x0]*(1-fx)*(1-fy)+img[y0,x1]*fx*(1-fy)
            +img[y1,x0]*(1-fx)*fy+img[y1,x1]*fx*fy)[:,:3]

def _lin2srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c*12.92, 1.055*np.power(c, 1/2.4)-0.055)

def _frames_to_quat(n):
    n = n/(np.linalg.norm(n,axis=1,keepdims=True)+1e-9)
    up = np.tile(np.array([0,0,1],np.float32),(len(n),1))
    bad = np.abs((n*up).sum(1)) > 0.99
    up[bad] = np.array([1,0,0],np.float32)
    t = np.cross(up,n); t/=(np.linalg.norm(t,axis=1,keepdims=True)+1e-9)
    b = np.cross(n,t)
    R = np.stack([t,b,n],axis=2)                 # columns [t,b,n]
    m=R; N=len(m); tr=m[:,0,0]+m[:,1,1]+m[:,2,2]; q=np.zeros((N,4),np.float32)
    s0=tr>0; S=np.sqrt(np.maximum(tr[s0]+1,1e-9))*2
    q[s0,0]=0.25*S; q[s0,1]=(m[s0,2,1]-m[s0,1,2])/S; q[s0,2]=(m[s0,0,2]-m[s0,2,0])/S; q[s0,3]=(m[s0,1,0]-m[s0,0,1])/S
    rest=~s0
    if rest.any():
        idx=np.nonzero(rest)[0]
        d0=m[rest,0,0]; d1=m[rest,1,1]; d2=m[rest,2,2]
        c0=(d0>=d1)&(d0>=d2); c1=(~c0)&(d1>=d2); c2=(~c0)&(~c1)
        def fill(mask,a,bx,c):
            ii=idx[mask]; M=m[ii]; S=np.sqrt(np.maximum(1+M[:,a,a]-M[:,bx,bx]-M[:,c,c],1e-9))*2
            q[ii,0]=(M[:,c,bx]-M[:,bx,c])/S; q[ii,1+a]=0.25*S
            q[ii,1+bx]=(M[:,bx,a]+M[:,a,bx])/S; q[ii,1+c]=(M[:,c,a]+M[:,a,c])/S
        if c0.any(): fill(c0,0,1,2)
        if c1.any(): fill(c1,1,2,0)
        if c2.any(): fill(c2,2,0,1)
    q/=(np.linalg.norm(q,axis=1,keepdims=True)+1e-9)
    return q.astype(np.float32)

# =====================================================================================
# bpy extraction
# =====================================================================================
def _find_basecolor_image(bsdf):
    """Walk back from the Base Color input to find an Image Texture node (through Mapping/Mix/etc.)."""
    bc = bsdf.inputs.get('Base Color')
    if bc is None or not bc.is_linked:
        return None
    seen = set(); stack = [bc.links[0].from_node]
    while stack:
        n = stack.pop()
        if n is None or n.as_pointer() in seen:
            continue
        seen.add(n.as_pointer())
        if n.type == 'TEX_IMAGE' and n.image is not None:
            return n.image
        for inp in n.inputs:
            if inp.is_linked:
                stack.append(inp.links[0].from_node)
    return None

def _material_color(mat):
    """Return (image_np or None, basecolor_rgb) for one material."""
    base = np.array([0.8, 0.8, 0.8], np.float32)
    if mat is None:
        return None, base
    if not mat.use_nodes:
        try: base = np.array(mat.diffuse_color[:3], np.float32)
        except Exception: pass
        return None, base
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        return None, base
    bc = bsdf.inputs.get('Base Color')
    if bc is not None:
        base = np.array(bc.default_value[:3], np.float32)
    img = _find_basecolor_image(bsdf)
    if img is not None and tuple(img.size) != (0, 0):
        w, h = img.size
        try:
            px = np.empty(w*h*4, np.float32); img.pixels.foreach_get(px)
            return px.reshape(h, w, 4), base
        except Exception:
            pass
    return None, base

def _extract_samples(obj, count, color_source, seed):
    """Sample the evaluated mesh surface -> (points, normals, colors, area, diag) in world space."""
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    nv = len(me.vertices)
    verts = np.empty(nv*3, np.float32); me.vertices.foreach_get('co', verts); verts = verts.reshape(-1,3)
    vn = np.empty(nv*3, np.float32); me.vertices.foreach_get('normal', vn); vn = vn.reshape(-1,3)
    nt = len(me.loop_triangles)
    if nt == 0:
        ev.to_mesh_clear(); return None
    tv = np.empty(nt*3, np.int32); me.loop_triangles.foreach_get('vertices', tv); tv = tv.reshape(-1,3)
    tl = np.empty(nt*3, np.int32); me.loop_triangles.foreach_get('loops', tl); tl = tl.reshape(-1,3)
    tmat = np.empty(nt, np.int32); me.loop_triangles.foreach_get('material_index', tmat)
    uv_ok = me.uv_layers.active is not None
    if uv_ok:
        nl = len(me.loops); uvf = np.empty(nl*2, np.float32)
        me.uv_layers.active.data.foreach_get('uv', uvf); loop_uv = uvf.reshape(-1,2)
    vcol = None; vcol_per_loop = False
    if color_source == 'VERTEX' and len(me.color_attributes):
        ca = me.color_attributes.active_color or me.color_attributes[0]
        n = len(ca.data); cf = np.empty(n*4, np.float32); ca.data.foreach_get('color', cf); vcol = cf.reshape(-1,4)
        vcol_per_loop = (ca.domain == 'CORNER')

    mw = np.array(obj.matrix_world, np.float32)
    verts_w = verts @ mw[:3,:3].T + mw[:3,3]
    nmat = np.linalg.inv(mw[:3,:3]).T
    vn_w = vn @ nmat.T; vn_w /= (np.linalg.norm(vn_w, axis=1, keepdims=True)+1e-9)

    tri_pos = verts_w[tv]
    idx, bary, area = _sample_triangles(tri_pos, count, seed)
    pts = (bary[:,:,None]*tri_pos[idx]).sum(1)
    nrm = (bary[:,:,None]*vn_w[tv][idx]).sum(1); nrm /= (np.linalg.norm(nrm,axis=1,keepdims=True)+1e-9)
    smi = tmat[idx]                                   # material slot per sample
    uv = (bary[:,:,None]*loop_uv[tl][idx]).sum(1) if uv_ok else None

    # per-material colour data (+ diagnostics)
    slots = list(obj.material_slots)
    if not slots:
        slot_data = [(None, np.array([0.6,0.6,0.6], np.float32))]
        diag = ["no material slots -> grey"]
    else:
        slot_data = []; diag = []
        for si, sl in enumerate(slots):
            img, base = _material_color(sl.material)
            slot_data.append((img, base))
            mn = sl.material.name if sl.material else "None"
            if img is not None: diag.append("slot%d '%s': texture %dx%d" % (si, mn, img.shape[1], img.shape[0]))
            else:               diag.append("slot%d '%s': flat base %.2f,%.2f,%.2f" % (si, mn, *base))
    diag.append("uv=%s  color_source=%s" % (uv_ok, color_source))

    color = np.full((len(pts),3), 0.6, np.float32)
    for si,(img,base) in enumerate(slot_data):
        mask = (smi == si)
        if not mask.any(): continue
        if color_source == 'TEXTURE' and img is not None and uv is not None:
            color[mask] = _lin2srgb(_bilinear(img, uv[mask]))
        elif color_source == 'VERTEX' and vcol is not None:
            src = vcol[tl][idx] if vcol_per_loop else vcol[tv][idx]
            color[mask] = _lin2srgb((bary[:,:,None]*src[...,:3]).sum(1)[mask])
        else:
            color[mask] = _lin2srgb(base)
    ev.to_mesh_clear()
    return pts.astype(np.float32), nrm.astype(np.float32), np.clip(color,0,1).astype(np.float32), area, diag

def _make_cloud(obj, s):
    res = _extract_samples(obj, s.splat_count, s.color_source, s.seed)
    if res is None: return None, None
    pts, nrm, color, area, diag = res
    N = len(pts)
    spacing = float(np.sqrt(area/max(N,1)))
    r = spacing * s.size_scale
    scale = np.tile(np.array([r, r, r*s.flatness], np.float32), (N,1))
    quat = _frames_to_quat(nrm)
    if s.bake_lighting:
        key = np.array([0.4,0.5,0.8],np.float32); key/=np.linalg.norm(key)
        ndl = np.clip(nrm@key,0,1); hemi = 0.4+0.25*(nrm[:,2]*0.5+0.5)
        color = np.clip(color*(hemi[:,None]+0.7*ndl[:,None]),0,1).astype(np.float32)
    return dict(count=N, xyz=pts, color=color,
                opacity=np.full(N, s.opacity, np.float32), scale=scale.astype(np.float32), quat=quat), diag

# =====================================================================================
# GL viewer (validated EWA shader + optimised draw handler)
# =====================================================================================
TW = 4096
VERT = """
uniform sampler2D uData; uniform sampler2D uIndex; uniform int uTW; uniform int uITW;
uniform vec3 uRow0,uRow1,uRow2; uniform vec3 uCam; uniform vec2 uF; uniform vec2 uVP; uniform float uSigma;
in vec2 corner; out vec2 vC; out vec3 vCol; out float vOp;
ivec2 at(int lin,int w){ return ivec2(lin % w, lin / w); }
void main(){
  int sid=int(texelFetch(uIndex,at(gl_InstanceID,uITW),0).r+0.5); int base=sid*4;
  vec4 d0=texelFetch(uData,at(base,uTW),0); vec4 d1=texelFetch(uData,at(base+1,uTW),0);
  vec4 d2=texelFetch(uData,at(base+2,uTW),0); vec4 d3=texelFetch(uData,at(base+3,uTW),0);
  vec3 ic=d0.xyz; vec3 is=vec3(d0.w,d1.x,d1.y); vec4 iq=vec4(d1.z,d1.w,d2.x,d2.y);
  vec3 icol=vec3(d2.z,d2.w,d3.x); float iop=d3.y;
  vC=corner; vCol=icol; vOp=iop;
  vec3 dp=ic-uCam; vec3 t=vec3(dot(uRow0,dp),dot(uRow1,dp),dot(uRow2,dp));
  if(t.z<0.02){ gl_Position=vec4(2.0,2.0,2.0,1.0); return; }
  float w=iq.x,x=iq.y,y=iq.z,z=iq.w;
  vec3 c0=vec3(1.0-2.0*(y*y+z*z),2.0*(x*y+w*z),2.0*(x*z-w*y));
  vec3 c1=vec3(2.0*(x*y-w*z),1.0-2.0*(x*x+z*z),2.0*(y*z+w*x));
  vec3 c2=vec3(2.0*(x*z+w*y),2.0*(y*z-w*x),1.0-2.0*(x*x+y*y));
  mat3 M=mat3(c0*is.x,c1*is.y,c2*is.z); mat3 Sig=M*transpose(M);
  float iz=1.0/t.z;
  mat3 J=mat3(vec3(uF.x*iz,0,0),vec3(0,uF.y*iz,0),vec3(-uF.x*t.x*iz*iz,-uF.y*t.y*iz*iz,0));
  mat3 Rv=mat3(vec3(uRow0.x,uRow1.x,uRow2.x),vec3(uRow0.y,uRow1.y,uRow2.y),vec3(uRow0.z,uRow1.z,uRow2.z));
  mat3 cov=(J*Rv)*Sig*transpose(J*Rv);
  float a=cov[0][0]+0.3,b=cov[0][1],c=cov[1][1]+0.3;
  float tr=a+c,det=a*c-b*b,mid=0.5*tr,disc=sqrt(max(mid*mid-det,0.0));
  float l1=mid+disc,l2=max(mid-disc,1e-9);
  float r1=uSigma*sqrt(max(l1,0.0)),r2=uSigma*sqrt(l2);
  vec2 e1=vec2(b,l1-a); e1=(length(e1)<1e-6)?vec2(1,0):normalize(e1); vec2 e2=vec2(-e1.y,e1.x);
  vec2 ndc=vec2((uF.x*t.x*iz)/(uVP.x*0.5),(uF.y*t.y*iz)/(uVP.y*0.5));
  vec2 p2n=vec2(2.0/uVP.x,2.0/uVP.y);
  gl_Position=vec4(ndc+corner.x*e1*r1*p2n+corner.y*e2*r2*p2n,0.0,1.0);
}"""
FRAG = """
in vec2 vC; in vec3 vCol; in float vOp; out vec4 o;
void main(){ float g=exp(-4.5*dot(vC,vC)); float al=vOp*g; if(al<0.003) discard; o=vec4(vCol*al,al); }"""

_S = {"clouds": [], "handle": None}

def _mkbuf(arr):
    n=len(arr)
    try:
        buf=Buffer('FLOAT', n); np.frombuffer(buf, dtype=np.float32)[:]=arr; return buf
    except Exception: pass
    try: return Buffer('FLOAT', n, arr)
    except Exception: return Buffer('FLOAT', n, arr.tolist())

def _pack(d):
    N=d['count']; xyz=d['xyz']; sc=d['scale']; q=d['quat']; cl=d['color']; op=d['opacity']
    tex=np.zeros((N*4,4),'f4')
    tex[0::4]=np.column_stack([xyz,sc[:,0]]); tex[1::4]=np.column_stack([sc[:,1],sc[:,2],q[:,0],q[:,1]])
    tex[2::4]=np.column_stack([q[:,2],q[:,3],cl[:,0],cl[:,1]]); tex[3::4]=np.column_stack([cl[:,2],op,np.zeros(N,'f4'),np.zeros(N,'f4')])
    TH=(N*4+TW-1)//TW; full=np.zeros((TH*TW,4),'f4'); full[:N*4]=tex
    return full.reshape(TH,TW,4), TH

def _rebuild():
    """Merge all clouds, (re)build the static data texture."""
    clouds=_S["clouds"]
    if not clouds:
        _S.pop("data",None); _S.pop("datatex",None); return
    d=dict(count=sum(c['count'] for c in clouds),
           xyz=np.concatenate([c['xyz'] for c in clouds]),
           color=np.concatenate([c['color'] for c in clouds]),
           opacity=np.concatenate([c['opacity'] for c in clouds]),
           scale=np.concatenate([c['scale'] for c in clouds]),
           quat=np.concatenate([c['quat'] for c in clouds]))
    texdata,TH=_pack(d)
    _S["data"]=d
    _S["datatex"]=GPUTexture((TW,TH),format='RGBA32F',data=_mkbuf(texdata.ravel()))
    _S["itw"]=4096
    ext=float(np.linalg.norm(d['xyz'].max(0)-d['xyz'].min(0)))
    _S["move_eps"]=ext*0.02; _S.pop("idxtex",None)

def _draw():
    if "data" not in _S: return
    ctx=bpy.context; region=ctx.region; rv3d=ctx.region_data
    if rv3d is None or not rv3d.is_perspective: return
    W,H=region.width,region.height; vm=rv3d.view_matrix; pm=rv3d.window_matrix
    right=Vector(vm[0][:3]); up=Vector(vm[1][:3]); fwd=-Vector(vm[2][:3]); cam=vm.inverted().translation
    fx=0.5*W*pm[0][0]; fy=0.5*H*pm[1][1]
    d=_S["data"]; fwd_np=np.array(fwd,'f4'); cam_np=np.array(cam,'f4')
    need=("idxtex" not in _S)
    if not need:
        need=(float(np.dot(fwd_np,_S["last_fwd"]))<0.9994 or float(np.linalg.norm(cam_np-_S["last_cam"]))>_S["move_eps"])
    if need:
        depth=(d['xyz']-cam_np)@fwd_np; lo=float(depth.min()); hi=float(depth.max())
        q=65535-((depth-lo)*(65535.0/(hi-lo+1e-9))).astype(np.uint16)
        order=np.argsort(q,kind='stable').astype(np.float32)
        itw=_S["itw"]; ith=(len(order)+itw-1)//itw
        ibuf=np.zeros(itw*ith,'f4'); ibuf[:len(order)]=order
        _S["idxtex"]=GPUTexture((itw,ith),format='R32F',data=_mkbuf(ibuf))
        _S["last_fwd"]=fwd_np; _S["last_cam"]=cam_np
    itw=_S["itw"]; sh=_S["shader"]
    gpu.state.blend_set('ALPHA_PREMULT'); gpu.state.depth_test_set('NONE'); sh.bind()
    sh.uniform_sampler('uData',_S["datatex"]); sh.uniform_sampler('uIndex',_S["idxtex"])
    sh.uniform_int('uTW',TW); sh.uniform_int('uITW',itw)
    sh.uniform_float('uRow0',right); sh.uniform_float('uRow1',up); sh.uniform_float('uRow2',fwd)
    sh.uniform_float('uCam',cam); sh.uniform_float('uF',(fx,fy)); sh.uniform_float('uVP',(float(W),float(H)))
    sh.uniform_float('uSigma',bpy.context.scene.mesh2splat.render_sigma)
    _S["batch"].draw_instanced(sh, instance_count=d['count'])
    gpu.state.blend_set('NONE')

def _ensure_handler():
    if _S.get("handle") is None:
        _S["shader"]=GPUShader(VERT,FRAG)
        _S["batch"]=batch_for_shader(_S["shader"],'TRI_FAN',{"corner":[(-1,-1),(1,-1),(1,1),(-1,1)]})
        _S["handle"]=bpy.types.SpaceView3D.draw_handler_add(_draw,(),'WINDOW','POST_VIEW')

def _remove_handler():
    if _S.get("handle") is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_S["handle"],'WINDOW'); _S["handle"]=None

def _redraw():
    for a in bpy.context.screen.areas:
        if a.type=='VIEW_3D': a.tag_redraw()

# =====================================================================================
# properties / operators / panel
# =====================================================================================
class Mesh2SplatSettings(bpy.types.PropertyGroup):
    splat_count: bpy.props.IntProperty(name="Splat Count", default=200000, min=1000, max=5000000,
        description="Number of splats to sample from the mesh surface")
    size_scale: bpy.props.FloatProperty(name="Splat Size", default=0.9, min=0.1, max=4.0,
        description="Disk radius relative to mean sample spacing (bigger = smoother/blobbier)")
    flatness: bpy.props.FloatProperty(name="Flatness", default=0.15, min=0.02, max=1.0,
        description="Thickness of each splat along the surface normal (lower = flatter disks)")
    opacity: bpy.props.FloatProperty(name="Opacity", default=0.9, min=0.05, max=1.0)
    color_source: bpy.props.EnumProperty(name="Color", default='TEXTURE',
        items=[('TEXTURE',"Texture","Sample the material's Base Color texture"),
               ('BASECOLOR',"Base Color","Flat material Base Color"),
               ('VERTEX',"Vertex Color","Active color attribute")])
    bake_lighting: bpy.props.BoolProperty(name="Bake Simple Lighting", default=False,
        description="Bake a hemisphere+key diffuse into the splat colors (cheap 'lit' look)")
    hide_original: bpy.props.BoolProperty(name="Hide Original Mesh", default=True)
    seed: bpy.props.IntProperty(name="Seed", default=0, min=0)
    render_sigma: bpy.props.FloatProperty(name="Gaussian Extent", default=2.6, min=1.0, max=4.0,
        description="How many sigmas each splat quad covers (visual softness)")

class MESH2SPLAT_OT_convert(bpy.types.Operator):
    bl_idname="mesh2splat.convert"; bl_label="Convert to Splats"; bl_options={'REGISTER','UNDO'}
    def execute(self, context):
        obj=context.active_object
        if obj is None or obj.type!='MESH':
            self.report({'ERROR'},"Select a mesh object first"); return {'CANCELLED'}
        s=context.scene.mesh2splat
        t=time.perf_counter()
        cloud, diag=_make_cloud(obj, s)
        if cloud is None:
            self.report({'ERROR'},"Mesh has no faces to sample"); return {'CANCELLED'}
        print("[Mesh2Splat] %s color diagnostics:" % obj.name)
        for line in diag: print("   ", line)
        _S["clouds"].append(cloud); _rebuild(); _ensure_handler()
        if s.hide_original: obj.hide_set(True)
        _redraw()
        self.report({'INFO'}, "Splatted %s: %d splats | %s" %
                    (obj.name, cloud['count'], " | ".join(diag[:len(obj.material_slots) or 1])))
        return {'FINISHED'}

class MESH2SPLAT_OT_clear(bpy.types.Operator):
    bl_idname="mesh2splat.clear"; bl_label="Clear Splats"
    def execute(self, context):
        _S["clouds"].clear(); _rebuild(); _remove_handler(); _redraw()
        self.report({'INFO'},"Cleared splats"); return {'FINISHED'}

class MESH2SPLAT_PT_panel(bpy.types.Panel):
    bl_label="Mesh to Splat"; bl_idname="MESH2SPLAT_PT_panel"
    bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category="Splat"
    def draw(self, context):
        s=context.scene.mesh2splat; L=self.layout
        col=L.column(align=True)
        col.prop(s,"splat_count"); col.prop(s,"color_source")
        box=L.box(); box.label(text="Splat shape")
        box.prop(s,"size_scale"); box.prop(s,"flatness"); box.prop(s,"opacity"); box.prop(s,"render_sigma")
        row=L.row(); row.prop(s,"bake_lighting"); row.prop(s,"hide_original")
        L.prop(s,"seed")
        L.separator()
        L.operator("mesh2splat.convert", icon='OUTLINER_OB_POINTCLOUD')
        L.operator("mesh2splat.clear", icon='TRASH')
        if _S.get("data"):
            L.label(text="Showing %d splats (%d objects)" % (_S["data"]["count"], len(_S["clouds"])), icon='INFO')

_classes=(Mesh2SplatSettings, MESH2SPLAT_OT_convert, MESH2SPLAT_OT_clear, MESH2SPLAT_PT_panel)

def register():
    for c in _classes: bpy.utils.register_class(c)
    bpy.types.Scene.mesh2splat=bpy.props.PointerProperty(type=Mesh2SplatSettings)

def unregister():
    _remove_handler(); _S["clouds"].clear()
    del bpy.types.Scene.mesh2splat
    for c in reversed(_classes): bpy.utils.unregister_class(c)

if __name__=="__main__":
    register()
