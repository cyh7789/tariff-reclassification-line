// Every question this batch has put to a person, and what came back.
//
// This is the part of the product a faster model cannot produce. The agent
// reaching a code is impressive; the agent stopping, naming the property it is
// missing and the function that owns it, and the case surviving until somebody
// answers, is the thing a scripted pipeline has no way to fake.
//
// Open ones first, because they are work and the finished ones are evidence.
// A screen that drew only the completed round trips would be describing a
// system that never waits, and waiting is most of what this job is.

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function renderAsked(flow) {
  const rows = flow.roundtrips || [];
  if (!rows.length) return '';
  const open = rows.filter(r => r.open).length;
  const head = open
    ? `${open} question${open === 1 ? '' : 's'} out with a named owner`
    : `${rows.length} question${rows.length === 1 ? '' : 's'} asked and answered`;

  const body = rows.map(r => r.open
    ? `<div class="ask open" data-case="${esc(r.case_id)}">
         <div class="askTop"><strong>${esc(r.item_id)}</strong>
           <span class="askWho">${esc(r.asked_of)}</span>
           <span class="muted">waiting ${esc(r.waiting)}</span></div>
         <div class="askQ">${esc(r.asked)}</div></div>`
    : `<div class="ask done" data-case="${esc(r.case_id)}">
         <div class="askTop"><strong>${esc(r.item_id)}</strong>
           <span class="askWho done">${esc(r.answered_by)}</span>
           <span class="muted">answered after ${esc(r.waited)}</span></div>
         <div class="askQ">${esc(r.asked)}</div>
         <div class="askA">“${esc(r.answered)}”${r.selected_code
           ? ` <span class="muted">→ re-ran and chose</span> <code>${esc(r.selected_code)}</code>`
           : ' <span class="muted">→ the re-run has not finished</span>'}</div></div>`
  ).join('');

  return `<div class="askHead"><strong>Went out to a person</strong>
      <span class="muted">${head}. Nothing moves on a guess.</span></div>${body}`;
}
