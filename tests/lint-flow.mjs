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

//: Points along the path. A cubic has to be evaluated rather than approximated by
//: its chord: the chord of a curve that loops around a box cuts straight through
//: it, and chasing those reported crossings moves lines that were already clear.
function points(d) {
  const out = []; let x=0, y=0;
  const toks = d.replace(/\s+/g, ' ').match(/[MVHLC][^MVHLC]*/g) || [];
  const line = (x1,y1,x2,y2) => {
    for (let t=0; t<=1; t+=0.04) out.push([x1+(x2-x1)*t, y1+(y2-y1)*t]);
  };
  for (const t of toks) {
    const k = t[0], n = t.slice(1).trim().split(/[ ,]+/).filter(Boolean).map(Number);
    if (k==='M') { [x,y] = n; }
    else if (k==='V') { line(x,y,x,n[0]); y = n[0]; }
    else if (k==='H') { line(x,y,n[0],y); x = n[0]; }
    else if (k==='L') { line(x,y,n[0],n[1]); [x,y] = n; }
    else if (k==='C') {
      const [x1,y1,x2,y2,x3,y3] = n;
      for (let u=0; u<=1; u+=0.02) {
        const m = 1-u;
        out.push([m*m*m*x + 3*m*m*u*x1 + 3*m*u*u*x2 + u*u*u*x3,
                  m*m*m*y + 3*m*m*u*y1 + 3*m*u*u*y2 + u*u*u*y3]);
      }
      x=x3; y=y3;
    }
  }
  return out;
}
const inside = (px,py,r) => px > r.x+2 && px < r.x+r.w-2 && py > r.y+2 && py < r.y+r.h-2;
let bad = 0;
for (const d of paths) {
  const pts = points(d);
  // The two endpoints sit on a node's port, so they are inside by design.
  outer: for (const [px, py] of pts.slice(3, -3)) {
    for (const r of nodes) if (inside(px,py,r)) {
      console.log(`穿過 ${r.id}：(${px.toFixed(0)},${py.toFixed(0)})  ${d.slice(0,56)}`);
      bad++; break outer;
    }
  }
}
// Same question for the edge labels: a label behind a box is a label nobody
// reads, and it is invisible to anyone testing by rendering rather than looking.
const labels = [...s.matchAll(/<text x="([\d.-]+)" y="([\d.-]+)"\s*\n?\s*text-anchor="(\w+)"\s*\n?\s*class="el[^"]*">([^<]*)</g)]
  .map(m => [m[0], m[1], m[2], m[3], "", m[4]]);
let hidden = 0;
for (const [, lx, ly, anchor, step, text] of labels) {
  const full = (step + text).trim();
  const w = full.length * 6.4, x = +lx, y = +ly;
  const left = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x;
  for (const r of nodes) {
    const overlap = left < r.x + r.w && left + w > r.x && y > r.y && y - 13 < r.y + r.h;
    if (overlap) { console.log(`標籤「${full}」被 ${r.id} 蓋住`); hidden++; break; }
  }
}
console.log(bad ? `${bad} 條線穿過方框` : '沒有線穿過方框');
console.log(hidden ? `${hidden} 個標籤被方框蓋住` : `${labels.length} 個標籤都沒有被蓋住`);
