// What the agent actually asked a corpus, and what came back.
//
// The circles around the agent carry a count, and a count is where a sceptical
// viewer stops: 27 searches is a number anybody can type. What cannot be typed
// is twenty-seven real queries with their results, in the order they happened,
// each attached to the line it was working on.
//
// The material is already recorded. `transcript.py` writes one row per call with
// the arguments spelled out and the result summarised, and the worker stores it
// on the case. Nothing here re-derives or re-words it; it selects.

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

//: How many to show. Past this the panel stops being readable and the point is
//: already made; the rest stay in the case's own transcript.
const SHOWN = 14;

export function callsFor(flow, tool) {
  const out = [];
  for (const c of flow.cases || []) {
    for (const step of c.steps || []) {
      if (step.kind !== 'tool' || !String(step.text || '').startsWith(tool + '(')) continue;
      out.push({item_id: c.item_id, case_id: c.case_id,
                text: step.text, detail: step.detail || ''});
    }
  }
  return out;
}

export function renderCalls(flow, tool, label) {
  const all = callsFor(flow, tool);
  if (!all.length) {
    return `<div class="callsHead"><strong>${esc(label)}</strong>
      <span class="muted">the agent has not gone into this one on this batch</span></div>`;
  }
  const items = new Set(all.map(c => c.item_id));
  const rows = all.slice(0, SHOWN).map(c =>
    `<div class="callRow" data-case="${esc(c.case_id)}">
       <span class="callItem">${esc(c.item_id)}</span>
       <code class="callQ">${esc(c.text)}</code>
       <span class="callR">${esc(c.detail)}</span></div>`).join('');
  const more = all.length > SHOWN
    ? `<div class="muted" style="padding:4px 0 0">${all.length - SHOWN} more, on the cases themselves</div>`
    : '';
  return `<div class="callsHead"><strong>${esc(label)}</strong>
      <span class="muted">${all.length} lookup${all.length === 1 ? '' : 's'} across
      ${items.size} line${items.size === 1 ? '' : 's'}, as they happened</span></div>
    ${rows}${more}`;
}
