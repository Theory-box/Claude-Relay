export const WGSL_AFFINITY = `
// per-node long-range affinity (attraction/repulsion) — second coarser grid, vmat interaction matrix
struct AP { count:u32, gx:u32, gy:u32, cap:u32, cell:f32, ox:f32, oy:f32, nObj:u32, base:f32, pad0:f32, pad1:f32, pad2:f32, };
@group(0) @binding(0) var<storage, read>       pos       : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> posOut    : array<vec4<f32>>;
@group(0) @binding(2) var<storage, read>       nodeRange : array<vec2<u32>>;   // reuse collision node->seg CSR
@group(0) @binding(3) var<storage, read>       nodeList  : array<u32>;
@group(0) @binding(4) var<storage, read>       segI      : array<vec4<u32>>;   // a,b,strand,packed (obj in >>3)
@group(0) @binding(5) var<storage, read>       affF      : array<vec4<f32>>;   // (effR, pad, affRange, tagged 1/0)
@group(0) @binding(6) var<storage, read>       segCellA  : array<vec4<u32>>;   // affinity-grid cell bounds
@group(0) @binding(7) var<storage, read>       cellBinsA : array<u32>;         // affinity-grid bins (0xffffffff sentinel)
@group(0) @binding(8) var<storage, read>       nmeta     : array<vec4<f32>>;   // invMass in .x
@group(0) @binding(9) var<storage, read>       vmat      : array<f32>;         // nObj*nObj interaction values
@group(0) @binding(10) var<uniform>            U         : AP;
struct CP { s:f32, t:f32, nrm:vec3<f32>, dist:f32, };
fn closestSeg(p1:vec3<f32>, q1:vec3<f32>, p2:vec3<f32>, q2:vec3<f32>) -> CP {
  let d1=q1-p1; let d2=q2-p2; let r=p1-p2;
  let a=dot(d1,d1); let e=dot(d2,d2); let ff=dot(d2,r); let lenEps=1e-9;
  var s=0.0; var t=0.0;
  if(a<=lenEps && e<=lenEps){ s=0.0; t=0.0; }
  else if(a<=lenEps){ s=0.0; t=clamp(ff/e,0.0,1.0); }
  else{ let c=dot(d1,r);
    if(e<=lenEps){ t=0.0; s=clamp(-c/a,0.0,1.0); }
    else{ let b=dot(d1,d2); let den=a*e-b*b;
      if(den > 1e-6*a*e){ s=clamp((b*ff-c*e)/den,0.0,1.0); } else { s=0.0; }
      t=(b*s+ff)/e;
      if(t<0.0){ t=0.0; s=clamp(-c/a,0.0,1.0); } else if(t>1.0){ t=1.0; s=clamp((b-c)/a,0.0,1.0); } } }
  let c1=p1+d1*s; let c2=p2+d2*t; let nn=c1-c2; var o:CP; o.s=s; o.t=t; o.nrm=nn; o.dist=max(length(nn),1e-6); return o;
}
fn shareEndpoint(A:vec4<u32>, B:vec4<u32>) -> bool { return A.x==B.x || A.x==B.y || A.y==B.x || A.y==B.y; }
fn ownerCell(ca:vec4<u32>, cb:vec4<u32>) -> u32 { let xlo=max(ca.x,cb.x); let ylo=max(ca.z,cb.z); return ylo*U.gx + xlo; }
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
  let i=gid.x; if(i>=U.count){ return; }
  let p=pos[i].xyz; let invI=nmeta[i].x;
  if(invI==0.0){ posOut[i]=vec4<f32>(p,0.0); return; }
  var accum=vec3<f32>(0.0);
  let rng=nodeRange[i]; let ns=rng.x; let nc=rng.y;
  for(var xi:u32=0u; xi<nc; xi=xi+1u){
    let X=nodeList[ns+xi]; let sxI=segI[X]; let sxC=segCellA[X]; let sxF=affF[X];
    if(sxF.w<0.5){ continue; }                            // X untagged
    let objX=sxI.w>>3u; let arX=sxF.z;
    for(var cy:u32=sxC.z; cy<=sxC.w; cy=cy+1u){
      for(var cx:u32=sxC.x; cx<=sxC.y; cx=cx+1u){
        let cellId=cy*U.gx+cx; let base=cellId*U.cap;
        for(var k:u32=0u; k<U.cap; k=k+1u){
          let Y=cellBinsA[base+k];
          if(Y==0xffffffffu){ break; }
          if(Y==X){ continue; }
          let syI=segI[Y]; let syC=segCellA[Y]; let syF=affF[Y];
          if(syF.w<0.5){ continue; }                      // Y untagged
          if(ownerCell(sxC,syC) != cellId){ continue; }
          if(shareEndpoint(sxI,syI)){ continue; }
          let objY=syI.w>>3u;
          let va=vmat[objX*U.nObj+objY];
          if(va==0.0){ continue; }                        // no interaction from X's side
          let cp=closestSeg(pos[sxI.x].xyz, pos[sxI.y].xyz, pos[syI.x].xyz, pos[syI.y].xyz);
          if(cp.dist>=arX){ continue; }
          let tgt=sxF.x+syF.x+max(sxF.y,syF.y);            // contact distance
          let u=cp.nrm/cp.dist;                            // points Y-closest -> X-closest
          let gate=clamp((cp.dist-tgt)/10.0, 0.0, 1.0);
          let fallA=1.0 - clamp((cp.dist-tgt)/max(1.0, arX-tgt), 0.0, 1.0);
          var g=1.0; if(va>0.0){ g=gate; }                // attraction fades inside contact; repulsion doesn't
          let mA=va*U.base*fallA*g;
          var w=cp.s; if(i==sxI.x){ w=1.0-cp.s; }          // barycentric slot for node i on X
          accum=accum - u*mA*w*invI;                       // -u: attraction (va>0) pulls X toward Y
        }
      }
    }
  }
  posOut[i]=vec4<f32>(p+accum, 0.0);
}`;
