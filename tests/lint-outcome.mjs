// The first number on the page is the one a judge checks against the data
// underneath it, so it has to be impossible to overstate.
import { outcome } from '../fleet/app/static/outcome.js';

const fail = [];
const check = (ok, why) => { if (!ok) fail.push(why); };
const states = o => ({RECEIVED:0, SETTLED:0, CLASSIFYING:0, NEEDS_INPUT:0,
                      VERIFY_FAILED:0, READY:0, APPROVED:0, BLOCKED:0, ...o});

// The batch this demo actually runs: nothing signed yet.
const live = outcome({states: states({SETTLED:10, READY:8, NEEDS_INPUT:2}),
                      agent: {cases:10, tool_calls:63, seconds:598.6}});
const words = live.cards.map(c => `${c.n} ${c.label}`);

check(live.total === 20, `total ${live.total}, expected 20`);
check(words.some(w => w === '18 ready for one signature'),
      `no "18 ready for one signature" in ${JSON.stringify(words)}`);
check(!words.some(w => /signed off/.test(w)),
      'a batch nobody has signed must not say anything is signed off');
check(words.some(w => w === '2 held back'), `no "2 held back" in ${JSON.stringify(words)}`);
check(/63 lookups/.test(live.cost), `cost line lost the lookups: ${live.cost}`);

// Once it is signed, it says so, and stops claiming the same lines are waiting.
const done = outcome({states: states({APPROVED:18, NEEDS_INPUT:2}), agent: {cases:10}});
const dwords = done.cards.map(c => `${c.n} ${c.label}`);
check(dwords.some(w => w === '18 signed off'), `no "18 signed off" in ${JSON.stringify(dwords)}`);
check(!dwords.some(w => /^\d+ ready for one signature/.test(w) && !/^0 /.test(w)),
      'nothing is still waiting once it is all signed');

// An untouched batch claims nothing.
const fresh = outcome({states: states({RECEIVED: 20}), agent: {}});
check(fresh.total === 20, 'a fresh batch still counts what came in');
check(fresh.cards.every(c => !/signed/.test(c.label)), 'a fresh batch has signed nothing');
check(fresh.cost === '', 'no agent time to report before the agent has run');

// The headline never invents work: totals come from the states, nowhere else.
const partial = outcome({states: states({CLASSIFYING: 3, READY: 1}), agent: {cases:3}});
check(partial.total === 4, `total ${partial.total}, expected 4`);
check(partial.cards.some(c => c.label === 'still moving' && c.n === 3),
      'cases in flight are their own line');
// The overstatement worth guarding: a line still inside the agent has no
// evidence pack and nobody can sign it, so it must not be counted as ready.
const readyCard = partial.cards.find(c => c.label === 'ready for one signature');
check(readyCard && readyCard.n === 1,
      `ready counted ${readyCard && readyCard.n}, expected 1 with three still in flight`);

if (fail.length) { console.error('outcome lint:\n  ' + fail.join('\n  ')); process.exit(1); }
console.log(`outcome lint ok: ${words.join(' | ')}`);
