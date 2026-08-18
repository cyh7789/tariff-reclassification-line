// What the batch came to, in the officer's terms, before any diagram.
//
// The screen could say how the work flows and how many lookups it took, and
// still not say the one thing the person in the chair cares about: how much of
// this is off my desk. Those figures existed nowhere on the page. This is not a
// rearrangement of what was already shown.
//
// Every number is derived from the live batch. Nothing here is written down in
// advance, because a headline figure that disagrees with the data underneath it
// is worse than no headline at all, and this project has already shipped one
// screen quoting counts from a different run.
//
// The wording follows the state rather than the hope: a batch nobody has signed
// says "ready for one signature", never "signed". Overstating the first number
// on the page is the cheapest way to lose the argument that the rest of the
// screen is trying to make.

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

//: States a signature would release, and states it would not.
const RELEASABLE = ['SETTLED', 'READY'];
const HELD = ['NEEDS_INPUT', 'VERIFY_FAILED', 'BLOCKED'];
const WORKING = ['RECEIVED', 'CLASSIFYING'];

const sum = (states, keys) => keys.reduce((n, k) => n + (states[k] || 0), 0);

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

export function outcome(flow) {
  const states = flow.states || {};
  const total = Object.values(states).reduce((a, b) => a + b, 0);
  const signed = states.APPROVED || 0;
  const ready = sum(states, RELEASABLE);
  const held = sum(states, HELD);
  const working = sum(states, WORKING);
  const agent = flow.agent || {};

  const cards = [
    {n: total, label: total === 1 ? 'line came in' : 'lines came in',
     note: agent.cases ? `${agent.cases} needed judgment` : 'none needed judgment yet',
     tone: 'plain'},
  ];

  // Signed and ready are different claims and the screen must not blur them: a
  // batch where nobody has signed anything says so.
  if (signed) {
    cards.push({n: signed, label: signed === 1 ? 'signed off' : 'signed off',
                note: 'one action, whole batch', tone: 'good'});
  }
  if (ready || !signed) {
    cards.push({n: ready, label: 'ready for one signature',
                note: ready ? 'evidence pack attached to each' : 'nothing waiting on a signature',
                tone: ready ? 'good' : 'plain'});
  }
  cards.push({n: held, label: held === 1 ? 'held back' : 'held back',
              note: held ? 'each one names who owes the answer' : 'nothing is stuck',
              tone: held ? 'warn' : 'plain'});
  if (working) {
    cards.push({n: working, label: 'still moving', note: 'no one is waiting on these',
                tone: 'plain'});
  }

  //: The cost half of the same sentence. Stated next to what it bought, because
  //: "the agent ran" and "the agent read 63 things to settle ten lines" are not
  //: the same claim and only the second one is checkable.
  const cost = agent.tool_calls
    ? `${plural(agent.cases || 0, 'line', 'lines')} needed judgment · `
      + `${plural(agent.tool_calls, 'lookup', 'lookups')} · `
      + `${agent.seconds}s of agent time`
    : '';

  return {cards, cost, total};
}

export function renderOutcome(flow) {
  const {cards, cost} = outcome(flow);
  const body = cards.map(c =>
    `<div class="oc ${c.tone}"><div class="ocn">${c.n}</div>` +
    `<div class="ocl">${esc(c.label)}</div>` +
    `<div class="ocs">${esc(c.note)}</div></div>`).join('');
  return {body, cost};
}
