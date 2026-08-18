// The batch against a clock: what was worked, and what was waited out.
//
// A flow diagram says where work goes. It cannot say how long anything sat
// there, and the track asks for context held `across weeks of asynchronous
// operations`, which is a claim about duration. So this view has one job: put
// the machine's minutes and the people's days on one axis, where the difference
// between them is impossible to miss.
//
// Two inks, and a third for what the log cannot settle. Solid is the agent
// working. Hollow is a case on somebody's desk, drawn as a gap with an owner
// because waiting is the absence of work rather than another kind of it.
// Hatched is a run the event log cannot tell apart from one a dead worker left
// behind, so it claims neither.
//
// Every bar comes from a timestamp in the audit trail. Nothing is scaled or
// compressed to make a batch look like it took longer than it did.
//
// Returns strings rather than touching the document, so the geometry can be
// checked without a browser. `flow.js` is a module for the same reason.

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const STOPPED = new Set(['BLOCKED', 'VERIFY_FAILED']);

//: Narrower than a pixel is still part of the story: a two-second refusal is
//: the whole point of the case it belongs to.
const MIN_WIDTH_PCT = 0.4;

//: A batch that ran in one burst would otherwise divide by zero and stack every
//: segment on the same pixel.
const MIN_WINDOW_MS = 60000;

export function ink(seg) {
  if (STOPPED.has(seg.state)) return 'stop';
  if (seg.holder === 'done') return 'done';
  if (seg.holder === 'machine') return seg.open ? 'unknown' : 'work';
  return 'wait';
}

//: Coarsest honest unit, the same rule the round-trip card uses. On an axis of
//: days nobody reads "173,940 seconds", and rounding up would overstate a wait.
export function forHumans(seconds) {
  for (const [size, unit] of [[86400, 'day'], [3600, 'hour'], [60, 'minute']]) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${unit}${n > 1 ? 's' : ''}`;
    }
  }
  return seconds > 0 ? 'under a minute' : '';
}

function held(last) {
  if (last.holder === 'done') return 'signed';
  if (last.holder === 'machine') return last.open ? 'in the agent' : 'moving';
  return `${last.holder} · ${forHumans(last.seconds)}`;
}

export function renderBand(band) {
  if (!band.lanes.length) {
    return {empty: true, lanes: '', axis: '', span: '', totals: '', note: '',
            body: '<div class="idleNote">Nothing has happened in this batch yet.</div>'};
  }
  const from = Date.parse(band.from), to = Date.parse(band.to);
  const width = Math.max(to - from, MIN_WINDOW_MS);
  const pct = ms => (ms / width) * 100;

  const body = band.lanes.map(lane => {
    const last = lane.spans[lane.spans.length - 1];
    const segs = lane.spans.map(s => {
      const start = Date.parse(s.start);
      const span = s.end ? Date.parse(s.end) - start : to - start;
      const w = Math.max(pct(span), MIN_WIDTH_PCT);
      return `<div class="seg ${ink(s)}" style="left:${pct(start - from).toFixed(3)}%;`
           + `width:${w.toFixed(3)}%" title="${esc(s.state)} · ${esc(s.holder)} · `
           + `${esc(forHumans(s.seconds))}"></div>`;
    }).join('');
    return `<div class="lane" data-case="${esc(lane.case_id)}">`
         + `<span class="id">${esc(lane.item_id)}</span>`
         + `<span class="track">${segs}</span>`
         + `<span class="now">${esc(held(last))}</span></div>`;
  }).join('');

  const days = width / 86400000;
  const ticks = Math.min(8, Math.max(2, Math.round(days > 1 ? days : width / 3600000)));
  const axis = Array.from({length: ticks}, (_, i) => {
    const at = new Date(from + (width * i) / ticks);
    return `<span>${days > 1 ? `${at.getMonth() + 1}/${at.getDate()}`
      : at.toTimeString().slice(0, 5)}</span>`;
  }).join('') + '<span></span>';

  return {
    empty: false, body, axis,
    span: `${new Date(from).toLocaleString()} → now`,
    // Summed across cases, and said so: the axis below spans five hours while
    // these can read five days, and a total that looks like wall-clock time
    // would be the one misleading number on an otherwise literal screen.
    totals: `<span class="bandKey"><i style="background:#0284c7"></i>agent `
          + `${forHumans(band.working) || '—'}</span>`
          + `<span class="bandKey"><i style="background:#fff8ec;border:1px solid #f0c078">`
          + `</i>waiting on people ${forHumans(band.waiting) || '—'}</span>`
          + `<span class="bandKey">summed across ${band.lanes.length} case`
          + `${band.lanes.length > 1 ? 's' : ''}</span>`,
    note: 'Every bar is a real timestamp from the audit trail. Solid is the agent '
        + 'working; hollow is a case sitting with the person named on the right. '
        + 'Hatched is a run the log cannot tell apart from one a dead worker left '
        + 'behind, so it counts as neither.',
  };
}
