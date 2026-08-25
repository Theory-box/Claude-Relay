// Endpoint grid build: insert each free endpoint into its home cell (one insertion each)
export const WGSL_ENDGRID = `
struct EG { count:u32, gx:u32, gy:u32, cap:u32, cell:f32, ox:f32, oy:f32, pad:f32, };
@group(0) @binding(0) var<storage, read>       pos       : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read>       endList   : array<u32>;
@group(0) @binding(2) var<storage, read_write> cellCount : array<atomic<u32>>;
@group(0) @binding(3) var<storage, read_write> cellBins  : array<u32>;
@group(0) @binding(4) var<storage, read_write> overflow  : array<atomic<u32>>;
@group(0) @binding(5) var<uniform>             U         : EG;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
  let ei=gid.x; if(ei>=U.count){ return; }
  let n=endList[ei]; let p=pos[n];
  let gxi=i32(U.gx)-1; let gyi=i32(U.gy)-1;
  let cx=clamp(i32(floor((p.x-U.ox)/U.cell)),0,gxi);
  let cy=clamp(i32(floor((p.y-U.oy)/U.cell)),0,gyi);
  let c=u32(cy)*U.gx+u32(cx);
  let slot=atomicAdd(&cellCount[c],1u);
  if(slot<U.cap){ cellBins[c*U.cap+slot]=ei; } else { atomicAdd(&overflow[0],1u); }
}`;

// Bond detection: for each free endpoint, scan 3x3 cells, emit candidate pairs (n1<n2) within ER^2
export const WGSL_BONDDETECT = `
struct BD { count:u32, gx:u32, gy:u32, cap:u32, cell:f32, ox:f32, oy:f32, margin:f32, candCap:u32, p0:u32, p1:u32, p2:u32, };
@group(0) @binding(0) var<storage, read>       pos       : array<vec4<f32>>;
@group(0) @binding(1) var<storage, read>       endList   : array<u32>;
@group(0) @binding(2) var<storage, read>       cellBins  : array<u32>;
@group(0) @binding(3) var<storage, read>       cellCount : array<u32>;
@group(0) @binding(4) var<storage, read_write> candCount : array<atomic<u32>>;
@group(0) @binding(5) var<storage, read_write> cand      : array<vec2<u32>>;
@group(0) @binding(6) var<storage, read_write> candOver  : array<atomic<u32>>;
@group(0) @binding(7) var<storage, read>       endMeta   : array<vec2<f32>>;   // (effR, maxSnap) per endpoint
@group(0) @binding(8) var<uniform>             U         : BD;
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid:vec3<u32>){
  let ei=gid.x; if(ei>=U.count){ return; }
  let n1=endList[ei]; let p1=pos[n1]; let m1=endMeta[ei];
  let gxi=i32(U.gx)-1; let gyi=i32(U.gy)-1;
  let cx=clamp(i32(floor((p1.x-U.ox)/U.cell)),0,gxi);
  let cy=clamp(i32(floor((p1.y-U.oy)/U.cell)),0,gyi);
  for(var dy:i32=-1; dy<=1; dy=dy+1){ let yy=cy+dy; if(yy<0||yy>gyi){continue;}
    for(var dx:i32=-1; dx<=1; dx=dx+1){ let xx=cx+dx; if(xx<0||xx>gxi){continue;}
      let c=u32(yy)*U.gx+u32(xx); let cnt=min(cellCount[c],U.cap); let base=c*U.cap;
      for(var k:u32=0u; k<cnt; k=k+1u){
        let ej=cellBins[base+k]; let n2=endList[ej];
        if(n2<=n1){ continue; }
        let p2=pos[n2]; let m2=endMeta[ej];
        let ddx=p2.x-p1.x; let ddy=p2.y-p1.y; let d2=ddx*ddx+ddy*ddy;
        let bondRest=m1.x+m2.x; let snapR=max(m1.y,m2.y); let thr=snapR*bondRest*U.margin;   // snap-distance pre-filter
        if(d2 < thr*thr && d2>1e-6){
          let slot=atomicAdd(&candCount[0],1u);
          if(slot<U.candCap){ cand[slot]=vec2<u32>(n1,n2); } else { atomicAdd(&candOver[0],1u); }
        }
      }
    }
  }
}`;
