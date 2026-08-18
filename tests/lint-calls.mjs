// The panel claims these are real lookups, so it has to select rather than invent.
import { callsFor, renderCalls } from '../fleet/app/static/calls.js';
import { readFileSync } from 'fs';

const fail = [];
const check = (ok, why) => { if (!ok) fail.push(why); };
const flow = JSON.parse(readFileSync('/tmp/realflow.json', 'utf8'));

for (const [tool, expected] of Object.entries(flow.tools_used)) {
  const got = callsFor(flow, tool).length;
  check(got === expected,
        `${tool}: 面板列出 ${got} 次，圖上的計數是 ${expected}`);
}

// A prefix must not swallow a different tool: get_ruling and get_tariff_lines
// both begin with "get_", and a naive includes() would mix them.
const ruling = callsFor(flow, 'get_ruling');
check(ruling.every(c => c.text.startsWith('get_ruling(')),
      'get_ruling picked up a call belonging to another tool');

// Every row carries the line it was working on, or the panel is a wall of
// queries with nothing to attach them to.
check(ruling.every(c => c.item_id && c.case_id), 'a row lost its item');

const html = renderCalls(flow, 'search_precedents', 'past CBP rulings');
check(/27 lookups/.test(html), `header lost the total: ${html.slice(0, 120)}`);
check(/search_precedents\(/.test(html), 'the query text never reached the panel');
check(!/undefined/.test(html), 'a field rendered as undefined');

const empty = renderCalls({cases: []}, 'get_ruling', 'what the goods were');
check(/has not gone into this one/.test(empty), 'an unused corpus must say so');

if (fail.length) { console.error('calls lint:\n  ' + fail.join('\n  ')); process.exit(1); }
console.log(`calls lint ok: ${Object.entries(flow.tools_used).map(([t,n]) => t.replace(/^(get|search)_/,'') + ' ' + n).join(' | ')}`);
