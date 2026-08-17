// Does any connector run through a box it does not connect? A line crossing a box
// reads as a line into it, and the diagram would be saying something untrue.
const mod = await import('../fleet/app/static/flow.js');
// Occupancy does not change the geometry, so a batch with one case at every
// node exercises every lane, parked dot and badge the real screen can draw.
const states = {RECEIVED:1, SETTLED:2, CLASSIFYING:2, NEEDS_INPUT:1, VERIFY_FAILED:1,
                READY:3, APPROVED:2, BLOCKED:1};
const edges = Object.fromEntries(['RECEIVED->SETTLED','RECEIVED->CLASSIFYING',
  'CLASSIFYING->READY','CLASSIFYING->VERIFY_FAILED','CLASSIFYING->NEEDS_INPUT',
  'NEEDS_INPUT->CLASSIFYING','VERIFY_FAILED->CLASSIFYING','SETTLED->APPROVED',
  'READY->APPROVED'].map(k => [k, 1]));
const flow = {states, edges, agent:{}, tools_used:{}, active:[], cases:[]};
const svg = {innerHTML:'', querySelectorAll:()=>[]};
mod.renderFlow(svg, flow, ()=>{}, null, null, [], 'operator');
const s = svg.innerHTML;

// node rects: from the <g class="node" ...><rect x= y= width= height=
const nodes = [...s.matchAll(/data-id="([a-z]+)"[\s\S]*?<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/g)]
  .map(m => ({id:m[1], x:+m[2], y:+m[3], w:+m[4], h:+m[5]}));
const paths = [...s.matchAll(/<path d="([^"]+)" fill="none"/g)].map(m => m[1]);

function segments(d) {
  const out = []; let x=0,y=0;
  const toks = d.match(/[MVHLC][^MVHLC]*/g) || [];
  for (const t of toks) {
    const k = t[0], n = t.slice(1).trim().split(/[ ,]+/).map(Number);
    if (k==='M') { [x,y] = n; }
    else if (k==='V') { out.push([x,y,x,n[0]]); y = n[0]; }
    else if (k==='H') { out.push([x,y,n[0],y]); x = n[0]; }
    else if (k==='L') { out.push([x,y,n[0],n[1]]); [x,y] = n; }
    else if (k==='C') { out.push([x,y,n[4],n[5]]); x=n[4]; y=n[5]; }
  }
  return out;
}
const inside = (px,py,r) => px > r.x+2 && px < r.x+r.w-2 && py > r.y+2 && py < r.y+r.h-2;
let bad = 0;
for (const d of paths) {
  for (const [x1,y1,x2,y2] of segments(d)) {
    for (let t=0.05; t<1; t+=0.05) {
      const px = x1+(x2-x1)*t, py = y1+(y2-y1)*t;
      for (const r of nodes) if (inside(px,py,r)) {
        console.log(`穿過 ${r.id}：(${px.toFixed(0)},${py.toFixed(0)})  ${d.slice(0,58)}`);
        bad++; t = 1; break;
      }
    }
  }
}
console.log(bad ? `${bad} 條線穿過方框` : '沒有線穿過方框');
