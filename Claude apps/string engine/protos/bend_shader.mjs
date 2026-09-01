export const WGSL_BEND = `
struct BP { count:u32, pad0:u32, pad1:u32, pad2:u32, };
@group(0) @binding(0) var<storage, read>       pos       : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read_write> posOut    : array<vec4<f32>>;
@group(0) @binding(2) var<storage, read>       nmeta     : array<vec4<f32>>;   // invMass in .x
@group(0) @binding(3) var<storage, read>       nodeRange : array<vec2<u32>>;   // constraint CSR (start,count) - reused
@group(0) @binding(4) var<storage, read>       edgeNbr   : array<u32>;         // neighbor node ids
@group(0) @binding(5) var<storage, read>       bendData  : array<vec4<f32>>;   // (bT, bN, bendFactor=stiff*0.5, curlOff=curl*r*3)
@group(0) @binding(6) var<uniform>             U         : BP;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
  let i=gid.x; if(i>=U.count){ return; }
  let p=pos[i].xyz;
  let bd=bendData[i]; let bend=bd.z;
  let rng=nodeRange[i];
  if(bend<=0.0 || rng.y!=2u || nmeta[i].x==0.0){ posOut[i]=vec4<f32>(p,0.0); return; }  // only movable degree-2 nodes bow
  let a=pos[edgeNbr[rng.x]].xyz; let c=pos[edgeNbr[rng.x+1u]].xyz;
  var tx=c.x-a.x; var ty=c.y-a.y; var tl=sqrt(tx*tx+ty*ty); if(tl<1e-6){ tl=1.0; } tx=tx/tl; ty=ty/tl;
  let nx=-ty; let ny=tx;
  let mx=(a.x+c.x)*0.5; let my=(a.y+c.y)*0.5;
  let nOff=bd.y+bd.w;                                   // rest normal offset + curl
  let gx=mx+tx*bd.x+nx*nOff; let gy=my+ty*bd.x+ny*nOff; // target bow point (matches CPU)
  var np=p;
  np.x=p.x+(gx-p.x)*bend; np.y=p.y+(gy-p.y)*bend;       // pull center toward target (2D, z untouched)
  if(any(np!=np)){ np=p; }
  posOut[i]=vec4<f32>(np,0.0);
}`;
