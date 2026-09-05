"""
vertex_lit_renderer/splat_gen.py
--------------------------------
Generate a gaussian-splat cloud from a Blender mesh, in-engine. Ported from the validated
mesh-to-splat addon: Surfel (uniform sample + local-grid-PCA anisotropy; default, topology-
independent), Per-Triangle (Steiner inellipse via Blender Decimate), and Uniform (round).
Colour is sampled per-face/per-sample from the material's Base Color texture. numpy-only.
"""
import bpy, numpy as np

SH_C0 = 0.28209479177387814

# ---------------------------------------------------------------- helpers
# The engine's G-buffer is LINEAR and the view transform is applied on blit (like meshes), so splat
# colours must be linear. sRGB textures -> linearise; Principled Base Color / vertex colours are
# already linear -> keep as-is.
def _srgb2lin(c):
    c = np.clip(c, 0, 1); return np.where(c <= 0.04045, c/12.92, np.power((c+0.055)/1.055, 2.4))

def _bilinear(img, uv):
    h, w = img.shape[:2]
    u = (uv[:,0] % 1.0)*(w-1); v = (uv[:,1] % 1.0)*(h-1)
    x0 = np.floor(u).astype(int); y0 = np.floor(v).astype(int)
    x1 = np.minimum(x0+1, w-1); y1 = np.minimum(y0+1, h-1)
    fx = (u-x0)[:,None]; fy = (v-y0)[:,None]
    return (img[y0,x0]*(1-fx)*(1-fy)+img[y0,x1]*fx*(1-fy)+img[y1,x0]*(1-fx)*fy+img[y1,x1]*fx*fy)[:,:3]

def _batch_quat(R):
    m=R; N=len(m); tr=m[:,0,0]+m[:,1,1]+m[:,2,2]; q=np.zeros((N,4),np.float32)
    s0=tr>0; S=np.sqrt(np.maximum(tr[s0]+1,1e-9))*2
    q[s0,0]=0.25*S; q[s0,1]=(m[s0,2,1]-m[s0,1,2])/S; q[s0,2]=(m[s0,0,2]-m[s0,2,0])/S; q[s0,3]=(m[s0,1,0]-m[s0,0,1])/S
    rest=~s0
    if rest.any():
        idx=np.nonzero(rest)[0]; d0=m[rest,0,0]; d1=m[rest,1,1]; d2=m[rest,2,2]
        c0=(d0>=d1)&(d0>=d2); c1=(~c0)&(d1>=d2); c2=(~c0)&(~c1)
        def fill(mask,a,bx,c):
            ii=idx[mask]; M=m[ii]; S=np.sqrt(np.maximum(1+M[:,a,a]-M[:,bx,bx]-M[:,c,c],1e-9))*2
            q[ii,0]=(M[:,c,bx]-M[:,bx,c])/S; q[ii,1+a]=0.25*S
            q[ii,1+bx]=(M[:,bx,a]+M[:,a,bx])/S; q[ii,1+c]=(M[:,c,a]+M[:,a,c])/S
        if c0.any(): fill(c0,0,1,2)
        if c1.any(): fill(c1,1,2,0)
        if c2.any(): fill(c2,2,0,1)
    q/=(np.linalg.norm(q,axis=1,keepdims=True)+1e-9); return q.astype(np.float32)

def _frames_to_quat(n):
    n=n/(np.linalg.norm(n,axis=1,keepdims=True)+1e-9)
    up=np.tile(np.array([0,0,1],np.float32),(len(n),1)); bad=np.abs((n*up).sum(1))>0.99
    up[bad]=np.array([1,0,0],np.float32)
    t=np.cross(up,n); t/=(np.linalg.norm(t,axis=1,keepdims=True)+1e-9); b=np.cross(n,t)
    return _batch_quat(np.stack([t,b,n],axis=2))

def _any_perp(n):
    ref=np.tile(np.array([0,0,1.0]),(len(n),1)); bad=np.abs((n*ref).sum(1))>0.9
    ref[bad]=np.array([1,0,0.0]); p=np.cross(n,ref); return p/(np.linalg.norm(p,axis=1,keepdims=True)+1e-12)

# ---------------------------------------------------------------- material colour
def _find_basecolor_image(bsdf):
    bc=bsdf.inputs.get('Base Color')
    if bc is None or not bc.is_linked: return None
    seen=set(); stack=[bc.links[0].from_node]
    while stack:
        nd=stack.pop()
        if nd is None or nd.as_pointer() in seen: continue
        seen.add(nd.as_pointer())
        if nd.type=='TEX_IMAGE' and nd.image is not None: return nd.image
        for inp in nd.inputs:
            if inp.is_linked: stack.append(inp.links[0].from_node)
    return None

def _material_color(mat):
    base=np.array([0.8,0.8,0.8],np.float32)
    if mat is None: return None, base
    if not mat.use_nodes:
        try: base=np.array(mat.diffuse_color[:3],np.float32)
        except Exception: pass
        return None, base
    bsdf=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
    if bsdf is None: return None, base
    bc=bsdf.inputs.get('Base Color')
    if bc is not None: base=np.array(bc.default_value[:3],np.float32)
    img=_find_basecolor_image(bsdf)
    if img is not None and tuple(img.size)!=(0,0):
        w,h=img.size
        try:
            px=np.empty(w*h*4,np.float32); img.pixels.foreach_get(px); a=px.reshape(h,w,4)
            # sRGB texture -> linearise (Non-Color/Raw/Linear stay as stored)
            cs=getattr(getattr(img,'colorspace_settings',None),'name','sRGB')
            if cs not in ('Non-Color','Raw','Linear','Linear Rec.709','Linear FilmLight E-Gamut'):
                a=a.copy(); a[...,:3]=_srgb2lin(a[...,:3])
            return a, base
        except Exception: pass
    return None, base

# ---------------------------------------------------------------- surface sampling (uniform / surfel)
def _sample_triangles(tri_pos, count, seed):
    rng=np.random.default_rng(seed)
    e1=tri_pos[:,1]-tri_pos[:,0]; e2=tri_pos[:,2]-tri_pos[:,0]
    area=0.5*np.linalg.norm(np.cross(e1,e2),axis=1); tot=float(area.sum())
    idx=rng.choice(len(tri_pos), size=count, p=area/(area.sum()+1e-12))
    u=rng.random(count); v=rng.random(count); over=u+v>1; u[over]=1-u[over]; v[over]=1-v[over]
    return idx, np.stack([1-u-v,u,v],1).astype(np.float32), tot

def _extract_samples(obj, count, color_source, seed):
    deps=bpy.context.evaluated_depsgraph_get(); ev=obj.evaluated_get(deps); me=ev.to_mesh()
    me.calc_loop_triangles()
    nv=len(me.vertices); verts=np.empty(nv*3,np.float32); me.vertices.foreach_get('co',verts); verts=verts.reshape(-1,3)
    vn=np.empty(nv*3,np.float32); me.vertices.foreach_get('normal',vn); vn=vn.reshape(-1,3)
    nt=len(me.loop_triangles)
    if nt==0: ev.to_mesh_clear(); return None
    tv=np.empty(nt*3,np.int32); me.loop_triangles.foreach_get('vertices',tv); tv=tv.reshape(-1,3)
    tl=np.empty(nt*3,np.int32); me.loop_triangles.foreach_get('loops',tl); tl=tl.reshape(-1,3)
    tmat=np.empty(nt,np.int32); me.loop_triangles.foreach_get('material_index',tmat)
    uv_ok=me.uv_layers.active is not None
    if uv_ok:
        nl=len(me.loops); uvf=np.empty(nl*2,np.float32); me.uv_layers.active.data.foreach_get('uv',uvf); loop_uv=uvf.reshape(-1,2)
    mw=np.array(obj.matrix_world,np.float32); verts_w=verts@mw[:3,:3].T+mw[:3,3]
    nmat=np.linalg.inv(mw[:3,:3]).T; vn_w=vn@nmat.T; vn_w/=(np.linalg.norm(vn_w,axis=1,keepdims=True)+1e-9)
    tri_pos=verts_w[tv]; idx,bary,area=_sample_triangles(tri_pos,count,seed)
    pts=(bary[:,:,None]*tri_pos[idx]).sum(1)
    nrm=(bary[:,:,None]*vn_w[tv][idx]).sum(1); nrm/=(np.linalg.norm(nrm,axis=1,keepdims=True)+1e-9)
    smi=tmat[idx]; uv=(bary[:,:,None]*loop_uv[tl][idx]).sum(1) if uv_ok else None
    slots=list(obj.material_slots); diag=[]
    if not slots: slot_data=[(None,np.array([0.6,0.6,0.6],np.float32))]; diag=["no material slots -> grey"]
    else:
        slot_data=[]
        for si,sl in enumerate(slots):
            img,base=_material_color(sl.material); slot_data.append((img,base))
            mn=sl.material.name if sl.material else "None"
            diag.append("slot%d '%s': %s"%(si,mn,("texture %dx%d"%(img.shape[1],img.shape[0])) if img is not None else "flat %.2f,%.2f,%.2f"%tuple(base)))
    diag.append("uv=%s samples=%d"%(uv_ok,len(pts)))
    color=np.full((len(pts),3),0.6,np.float32)
    for si,(img,base) in enumerate(slot_data):
        mask=(smi==si)
        if not mask.any(): continue
        if color_source=='TEXTURE' and img is not None and uv is not None: color[mask]=_bilinear(img,uv[mask])
        else: color[mask]=base
    ev.to_mesh_clear()
    return pts.astype(np.float32),nrm.astype(np.float32),np.clip(color,0,1).astype(np.float32),area,diag

def _surfels_grid(pts,nrm,colors,spacing,cover,thin_ratio,opacity):
    N=len(pts); P=pts.astype(np.float64); n=nrm.astype(np.float64); n/=(np.linalg.norm(n,axis=1,keepdims=True)+1e-12)
    mn=P.min(0); h=max(float(spacing)*2.2,1e-6)
    ci=np.floor((P-mn)/h).astype(np.int64); dims=ci.max(0)+2
    cid=ci[:,0]+ci[:,1]*dims[0]+ci[:,2]*dims[0]*dims[1]
    uniq,inv,counts=np.unique(cid,return_inverse=True,return_counts=True); nc=len(uniq)
    sp=np.zeros((nc,3)); np.add.at(sp,inv,P); mean=sp/counts[:,None]
    so=np.zeros((nc,3,3)); np.add.at(so,inv,np.einsum('ni,nj->nij',P,P))
    cov=so/counts[:,None,None]-np.einsum('ci,cj->cij',mean,mean); w,V=np.linalg.eigh(cov); Wp=w[inv]; Vp=V[inv]
    longv=Vp[:,:,2]; longv=longv-(np.einsum('ni,ni->n',longv,n))[:,None]*n
    ln=np.linalg.norm(longv,axis=1,keepdims=True)
    longv=np.where(ln>1e-6,longv/np.maximum(ln,1e-12),_any_perp(n)); midv=np.cross(n,longv)
    s_long=cover*np.sqrt(np.maximum(Wp[:,2],1e-12)); s_mid=cover*np.sqrt(np.maximum(Wp[:,1],1e-12))
    few=counts[inv]<4; iso=cover*float(spacing)*0.6
    s_long=np.where(few,iso,s_long); s_mid=np.where(few,iso,s_mid); thin=thin_ratio*np.maximum(s_long,s_mid)
    R=np.stack([n,midv,longv],axis=2); det=np.linalg.det(R); R[det<0,:,1]*=-1   # flip a TANGENT, keep normal outward
    scale=np.stack([thin,s_mid,s_long],1).astype(np.float32)
    return dict(count=N,xyz=P.astype(np.float32),color=np.clip(colors,0,1).astype(np.float32),
                opacity=np.full(N,opacity,np.float32),scale=scale,quat=_batch_quat(R.astype(np.float32)))

# ---------------------------------------------------------------- per-triangle (Steiner inellipse)
def _tri_splats(V,F,face_colors,face_normals,cover,thin_ratio,opacity,bake):
    V=V.astype(np.float64); tri=V[F]; a,b,c=tri[:,0],tri[:,1],tri[:,2]
    e1=b-a; e2=c-a; centroid=(a+b+c)/3.0; C11=1.0/18.0; C12=-1.0/36.0
    def outer(x,y): return np.einsum('ni,nj->nij',x,y)
    Sig=C11*(outer(e1,e1)+outer(e2,e2))+C12*(outer(e1,e2)+outer(e2,e1))
    w,Vec=np.linalg.eigh(Sig)
    # orient the normal axis (smallest eigenvalue, column 0) outward to match the face normal
    fl=np.sign(np.einsum('ni,ni->n',Vec[:,:,0],face_normals)); fl[fl==0]=1; Vec[:,:,0]*=fl[:,None]
    det=np.linalg.det(Vec); Vec[det<0,:,1]*=-1.0     # fix handedness via a tangent, keep normal outward
    std=np.sqrt(np.maximum(w,0.0)); sc=(cover*std); inplane=np.maximum(sc[:,1],sc[:,2]); sc[:,0]=np.maximum(sc[:,0],thin_ratio*inplane)
    n=len(F); col=np.clip(face_colors,0,1).astype(np.float32)
    if bake:
        key=np.array([0.4,0.5,0.8],np.float32); key/=np.linalg.norm(key)
        ndl=np.clip(np.abs(face_normals@key),0,1); hemi=0.4+0.25*(np.abs(face_normals[:,2])*0.5+0.5)
        col=np.clip(col*(hemi[:,None]+0.7*ndl[:,None]),0,1).astype(np.float32)
    return dict(count=n,xyz=centroid.astype(np.float32),color=col,opacity=np.full(n,opacity,np.float32),
                scale=sc.astype(np.float32),quat=_batch_quat(Vec.astype(np.float32)))

def _extract_triangles(obj,count,color_source,size,flatness,opacity,bake):
    added=None; base_faces=max(len(obj.data.polygons),1)
    if count<base_faces:
        added=obj.modifiers.new('_vlr_dec','DECIMATE'); added.decimate_type='COLLAPSE'
        added.ratio=max(min(count/base_faces,1.0),0.0005)
    deps=bpy.context.evaluated_depsgraph_get(); ev=obj.evaluated_get(deps); me=ev.to_mesh(); me.calc_loop_triangles()
    nt=len(me.loop_triangles)
    if nt==0:
        ev.to_mesh_clear()
        if added: obj.modifiers.remove(added)
        return None,None
    nv=len(me.vertices); verts=np.empty(nv*3,np.float32); me.vertices.foreach_get('co',verts); verts=verts.reshape(-1,3)
    tv=np.empty(nt*3,np.int32); me.loop_triangles.foreach_get('vertices',tv); tv=tv.reshape(-1,3)
    tl=np.empty(nt*3,np.int32); me.loop_triangles.foreach_get('loops',tl); tl=tl.reshape(-1,3)
    tmat=np.empty(nt,np.int32); me.loop_triangles.foreach_get('material_index',tmat)
    uv_ok=me.uv_layers.active is not None
    if uv_ok:
        nl=len(me.loops); uvf=np.empty(nl*2,np.float32); me.uv_layers.active.data.foreach_get('uv',uvf); loop_uv=uvf.reshape(-1,2); cuv=loop_uv[tl].mean(1)
    mw=np.array(obj.matrix_world,np.float32); verts_w=verts@mw[:3,:3].T+mw[:3,3]
    tri=verts_w[tv]; fn=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]); fn/=(np.linalg.norm(fn,axis=1,keepdims=True)+1e-9)
    slots=list(obj.material_slots); diag=[]
    if not slots: slot_data=[(None,np.array([0.6,0.6,0.6],np.float32))]; diag=["no material slots -> grey"]
    else:
        slot_data=[]
        for si,sl in enumerate(slots):
            img,base=_material_color(sl.material); slot_data.append((img,base))
            mn=sl.material.name if sl.material else "None"
            diag.append("slot%d '%s': %s"%(si,mn,("texture %dx%d"%(img.shape[1],img.shape[0])) if img is not None else "flat %.2f,%.2f,%.2f"%tuple(base)))
    diag.append("uv=%s tris=%d"%(uv_ok,nt))
    color=np.full((nt,3),0.6,np.float32)
    for si,(img,base) in enumerate(slot_data):
        mask=(tmat==si)
        if not mask.any(): continue
        if color_source=='TEXTURE' and img is not None and uv_ok: color[mask]=_bilinear(img,cuv[mask])
        else: color[mask]=base
    cloud=_tri_splats(verts_w,tv,color,fn,size*2.6,flatness,opacity,bake)
    ev.to_mesh_clear()
    if added: obj.modifiers.remove(added)
    return cloud,diag

# ---------------------------------------------------------------- entry point
def generate(obj, method, count, color_source, size, flatness, opacity, bake, seed):
    """Return (splat_dict, diag list) for the active mesh, per the chosen method."""
    if method=='TRIANGLE':
        return _extract_triangles(obj,count,color_source,size,flatness,opacity,bake)
    res=_extract_samples(obj,count,color_source,seed)
    if res is None: return None,None
    pts,nrm,color,area,diag=res; N=len(pts); spacing=float(np.sqrt(area/max(N,1)))
    if bake:
        key=np.array([0.4,0.5,0.8],np.float32); key/=np.linalg.norm(key)
        ndl=np.clip(nrm@key,0,1); hemi=0.4+0.25*(nrm[:,2]*0.5+0.5)
        color=np.clip(color*(hemi[:,None]+0.7*ndl[:,None]),0,1).astype(np.float32)
    if method=='SURFEL':
        return _surfels_grid(pts,nrm,color,spacing,cover=size*2.6,thin_ratio=flatness,opacity=opacity),diag
    r=spacing*size; scale=np.tile(np.array([r,r,r*flatness],np.float32),(N,1))
    return dict(count=N,xyz=pts,color=color,opacity=np.full(N,opacity,np.float32),
                scale=scale.astype(np.float32),quat=_frames_to_quat(nrm)),diag
