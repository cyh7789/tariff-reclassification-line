// Does the band draw what the data says? Three ways it could lie and one way it
// could disappear, checked against a payload with a real ten-day wait in it.
import { renderBand, ink, forHumans } from '../fleet/app/static/band.js';

const fail = [];
const check = (ok, why) => { if (!ok) fail.push(why); };

const band = {
  from: '2026-08-18T09:00:00+00:00',
  to:   '2026-08-28T09:00:00+00:00',
  working: 480, waiting: 622800 + 6720,
  lanes: [{
    case_id: 'C-1', item_id: 'SKU-1013',
    spans: [
      {state:'RECEIVED',    holder:'machine',     start:'2026-08-18T09:00:00+00:00', end:'2026-08-18T09:02:00+00:00', seconds:120,    working:true,  open:false},
      {state:'CLASSIFYING', holder:'machine',     start:'2026-08-18T09:02:00+00:00', end:'2026-08-18T09:05:00+00:00', seconds:180,    working:true,  open:false},
      {state:'NEEDS_INPUT', holder:'contributor', start:'2026-08-18T09:05:00+00:00', end:'2026-08-25T14:05:00+00:00', seconds:622800, working:false, open:false},
      {state:'CLASSIFYING', holder:'machine',     start:'2026-08-25T14:05:00+00:00', end:'2026-08-25T14:08:00+00:00', seconds:180,    working:true,  open:false},
      {state:'READY',       holder:'approver',    start:'2026-08-25T14:08:00+00:00', end:null,                        seconds:6720,   working:false, open:true},
    ],
  }, {
    case_id: 'C-2', item_id: 'SKU-1099',
    spans: [
      {state:'RECEIVED',    holder:'machine', start:'2026-08-18T09:00:00+00:00', end:'2026-08-18T09:02:00+00:00', seconds:120, working:true,  open:false},
      {state:'CLASSIFYING', holder:'machine', start:'2026-08-18T09:02:00+00:00', end:null,                        seconds:864000, working:false, open:true},
    ],
  }],
};

const view = renderBand(band);

// 1. Every span reaches the screen. A segment silently dropped would make a case
//    look like it went straight from refusal to signature.
const segs = [...view.body.matchAll(/class="seg ([a-z]+)"/g)].map(m => m[1]);
check(segs.length === 7, `segments drawn ${segs.length}, expected 7`);

// 2. The ten-day wait is the widest thing on its lane. If work and waiting were
//    drawn to different scales, the one comparison this view exists for is gone.
const lane1 = view.body.split('data-case="C-2"')[0];
const widths = [...lane1.matchAll(/width:([\d.]+)%/g)].map(m => +m[1]);
const inks = [...lane1.matchAll(/class="seg ([a-z]+)"/g)].map(m => m[1]);
const widest = widths.indexOf(Math.max(...widths));
check(inks[widest] === 'wait', `widest segment is ${inks[widest]}, expected the wait`);
check(widths[widest] > 70, `the ten-day wait covers ${widths[widest].toFixed(1)}%, expected >70`);

// 3. Nothing runs off the end of its track, which would draw a case as still
//    open when it is not.
for (const m of view.body.matchAll(/left:([\d.]+)%;width:([\d.]+)%/g))
  check(+m[1] + +m[2] <= 100.5, `segment ends at ${(+m[1] + +m[2]).toFixed(1)}%`);

// 4. A three-minute run on a ten-day axis is 0.02% wide, so without a floor it
//    is invisible and the agent looks like it never ran.
check(widths.every(w => w >= 0.4), `a segment shrank to ${Math.min(...widths)}%`);

// 5. The stranded run claims neither ink.
check(ink(band.lanes[1].spans[1]) === 'unknown', 'an open machine span must be hatched');
check(ink({state:'BLOCKED', holder:'operator', open:true}) === 'stop', 'BLOCKED must read as stopped');

// 6. Durations round down. Reporting 7 days as 8 would overstate the wait.
check(forHumans(622800) === '7 days', `forHumans(622800) = ${forHumans(622800)}`);
check(forHumans(0) === '', 'zero is not a duration');

// 7. An untouched batch says so rather than rendering an empty frame.
check(renderBand({from:null, to:null, lanes:[], working:0, waiting:0}).empty === true,
      'an empty band must announce itself');

if (fail.length) { console.error('band lint:\n  ' + fail.join('\n  ')); process.exit(1); }
console.log(`band lint ok: ${segs.length} segments, wait covers ${widths[widest].toFixed(1)}% of its lane`);
