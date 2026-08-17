// The pipeline drawn the way an explainer diagram draws one: coloured zones with
// dashed borders, numbered steps along the arrows, and plenty of air.
//
// A table says where each item ended up. It cannot say which link absorbed the
// work, and that is the only question worth asking here: the deterministic layer
// takes the easy half with no model at all, the agent takes the half that needs
// judgment, and the verifier refuses whatever it cannot stand behind. Step
// numbers make that readable in one pass, live counts make it true.
//
// Edge traffic comes from the event log rather than current state, so a case that
// was refused, answered by engineering and re-run leaves its whole path visible
// instead of only its destination.

const ZONES = [
  { id: 'z-src',   x:  26, y:  96, w: 224, h: 350, label: 'Official sources',
    note: 'fetched, hashed, gated',      colour: '#64748b', tint: '#f1f5f9' },
  { id: 'z-det',   x: 286, y:  96, w: 248, h: 350, label: 'Deterministic layer',
    note: 'no model is involved here',   colour: '#0284c7', tint: '#eff8ff' },
  { id: 'z-agent', x: 570, y:  58, w: 336, h: 424, label: 'Agent fleet',
    note: 'judgment, with citations',    colour: '#059669', tint: '#ecfdf5' },
  { id: 'z-human', x: 942, y:  58, w: 300, h: 424, label: 'People',
    note: 'one approval, one exception', colour: '#d97706', tint: '#fffbeb' },
];

const NODES = [
  { id: 'sources', x: 58, y: 176, w: 160, h: 68, zone: 'z-src',
    label: 'Snapshot', sub: 'HTS · notes · rulings',
    what: 'A dated, frozen copy of the law: the 35,791-line tariff schedule, the '
        + 'legal notes of all 98 chapters, 218,606 past customs rulings, and the '
        + 'official correlation table.',
    why:  'Classifications have to be reproducible months later. A snapshot means '
        + 'the same batch re-run tomorrow gets the same answer, and every citation '
        + 'points at a version that still exists.' },

  { id: 'gate', x: 58, y: 314, w: 160, h: 68, zone: 'z-src',
    label: 'Health gate', sub: 'halts on a bad source',
    what: 'Checks row counts, byte sizes, hashes and age before anything is allowed '
        + 'to read the snapshot.',
    why:  'These government endpoints answer a wrong URL with HTTP 200 and an empty '
        + 'body. An empty screening list means every party passes screening, so the '
        + 'line stops rather than working from a file that only looks fine.' },

  { id: 'intake', x: 312, y: 152, w: 196, h: 66, zone: 'z-det',
    label: 'Catalog batch', sub: 'codes filed in 2017',
    what: 'The product lines as the company filed them, before the nomenclature '
        + 'revision.',
    why:  'Nobody re-files a catalog for fun. The codes sat correct for years and '
        + 'became wrong without anybody touching them.' },

  { id: 'triage', x: 312, y: 280, w: 196, h: 66, zone: 'z-det',
    label: 'Triage', sub: 'survived · dead · scope',
    what: 'Plain set arithmetic against the current schedule. Sorts every item into '
        + 'code still valid, code withdrawn, or code valid but its coverage changed.',
    why:  'This is the part that needs no judgment at all, so it must not cost a '
        + 'model call. It also decides what the agent is measured on.' },

  { id: 'settled', x: 312, y: 382, w: 196, h: 50, zone: 'z-det',
    label: 'Settled by lookup', sub: 'never reaches an agent',
    what: 'Items whose code is unchanged, plus dead codes the official table maps '
        + 'one-to-one. Answered by table lookup and closed.',
    why:  'Sending these to a model would pad the autonomy figure with free wins. '
        + 'Keeping them out is what makes the remaining number mean something.' },

  { id: 'agent', x: 602, y: 152, w: 272, h: 84, zone: 'z-agent',
    label: 'Classifier agent', sub: 'reads notes, lines, precedents',
    what: 'Gemini reading the chapter and section notes, the tariff lines under each '
        + 'candidate, and prior rulings on comparable goods, then choosing one '
        + '8-digit code and saying what separates it from the runner-up.',
    why:  'The correlation table states that it "has no legal status" and is "a '
        + 'guide only". It says where to look. Deciding needs the notes, the '
        + 'precedents, and the product in front of you.' },

  { id: 'verify', x: 602, y: 298, w: 272, h: 68, zone: 'z-agent',
    label: 'Citation check', sub: 'every reference re-resolved',
    what: 'A program, not a model. Takes each citation the agent produced and goes '
        + 'and looks: does the ruling exist, does the note number exist, are the '
        + 'quoted words really in it.',
    why:  'On Vertex the Pro line stops at 3.1, below this project\'s floor, so '
        + '"have a stronger model check it" is not available. Trust has to come from '
        + 'something that cannot be talked round. A model that never read the note '
        + 'paraphrases it, and a paraphrase fails a substring check.' },

  { id: 'needs', x: 602, y: 402, w: 272, h: 62, zone: 'z-agent',
    label: 'Refused', sub: 'names the fact and the department',
    what: 'The agent stops instead of choosing, and states which property is missing '
        + 'and who inside the company holds it.',
    why:  'Filing on a guess costs the duty difference plus penalties, and the person '
        + 'who signed owes it. Asking is cheaper than being wrong.' },

  { id: 'ready', x: 970, y: 152, w: 244, h: 68, zone: 'z-human',
    label: 'Ready to sign', sub: 'evidence pack attached',
    what: 'Selected code, runner-up, the fact that separates them, the duty rate and '
        + 'where it came from, chapter notes and rulings, all verified.',
    why:  'The licensed person is signing a legal declaration. What they need is not '
        + 'a shortlist to work through but a decision they can check.' },

  { id: 'approved', x: 970, y: 298, w: 244, h: 68, zone: 'z-human',
    label: 'Approved', sub: 'one action, whole batch',
    what: 'One deliberate signature releases everything that passed. Anything refused '
        + 'or unverified is held back and named.',
    why:  'Signing row by row is the hand-holding this system exists to remove. '
        + 'Deciding to sign at all is the part that cannot be delegated.' },

  { id: 'dept', x: 970, y: 402, w: 244, h: 62, zone: 'z-human',
    label: 'Engineering', sub: 'answers, cannot approve',
    what: 'Whoever holds the missing fact answers the one question, and the case '
        + 're-runs with it.',
    why:  'The answer comes from a different department than the signature, and the '
        + 'roles are enforced: a contributor can supply a fact and cannot approve.' },
];

//: Metadata for the explanation panel, keyed the same way as the nodes.
export const NODE_INFO = Object.fromEntries(
  NODES.map(n => [n.id, { label: n.label, what: n.what, why: n.why }]));

// from, to, count key, step, label, routing
// Return paths run below every zone, because a loop drawn through a zone reads as
// a line into it. The two approval edges are numbered apart so they do not print
// the same label twice in the same place.
const EDGES = [
  ['sources', 'gate',    null,            '1',  'verify',            'v'],
  ['gate',    'triage',  'received',      '2',  'release snapshot',  'h'],
  ['intake',  'triage',  'received',      '3',  'set difference',    'v'],
  ['triage',  'settled', 'deterministic', '4a', 'code unchanged',    'v'],
  ['triage',  'agent',   'agent',         '4b', 'needs judgment',    'h'],
  ['agent',   'verify',  'classified',    '5',  'proposed code',     'v'],
  ['agent',   'needs',   'refused',       '5b', 'will not guess',    'skirtR'],
  ['verify',  'ready',   'verified',      '6',  'citations resolve', 'h'],
  ['verify',  'agent',   'held',          '6b', 'held back',         'loopL'],
  ['needs',   'dept',    'refused',       '7',  'asks',              'h'],
  ['dept',    'agent',   'requeued',      '8',  'fact supplied',     'loopB'],
  ['ready',   'approved','approvedAgent', '9a', 'sign',              'v'],
  ['settled', 'approved','approvedDet',   '9b', 'sign',              'baseline'],
];

const N = Object.fromEntries(NODES.map(n => [n.id, n]));
const c = n => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });

const LOOP_Y = 512;   // return traffic, clear of every zone
const BASE_Y = 556;   // the deterministic path to approval, lower still

function path(a, b, kind) {
  const A = N[a], B = N[b], ca = c(A), cb = c(B);
  switch (kind) {
    case 'v':
      return `M ${ca.x} ${A.y + A.h} L ${cb.x} ${B.y}`;
    case 'h': {
      const x1 = A.x + A.w, x2 = B.x, m = (x1 + x2) / 2;
      return `M ${x1} ${ca.y} C ${m} ${ca.y}, ${m} ${cb.y}, ${x2} ${cb.y}`;
    }
    case 'skirtR':   // agent -> refused, down the right-hand side of the zone
      return `M ${A.x + A.w - 26} ${A.y + A.h} V ${B.y - 20} H ${B.x + B.w - 26} V ${B.y}`;
    case 'loopL':    // verify -> agent, a short retry hop on the left
      return `M ${A.x + 26} ${A.y} V ${B.y + B.h + 16} H ${B.x + 26} V ${B.y + B.h}`;
    case 'loopB':    // engineering -> agent, the long way back underneath
      return `M ${ca.x} ${A.y + A.h} V ${LOOP_Y} H ${B.x + 44} V ${B.y + B.h}`;
    case 'baseline': // settled -> approved, along the very bottom
      return `M ${ca.x} ${A.y + A.h} V ${BASE_Y} H ${cb.x} V ${B.y + B.h}`;
    default:
      return `M ${ca.x} ${ca.y} L ${cb.x} ${cb.y}`;
  }
}

function tally(flow) {
  const s = flow.states, e = k => flow.edges[k] || 0;
  return {
    received: s.RECEIVED + s.SETTLED + s.CLASSIFYING + s.NEEDS_INPUT +
              s.VERIFY_FAILED + s.READY + s.APPROVED,
    deterministic: e('RECEIVED->SETTLED'),
    agent:         e('RECEIVED->CLASSIFYING'),
    classified:    e('CLASSIFYING->READY') + e('CLASSIFYING->VERIFY_FAILED'),
    refused:       e('CLASSIFYING->NEEDS_INPUT'),
    requeued:      e('NEEDS_INPUT->CLASSIFYING'),
    verified:      e('CLASSIFYING->READY'),
    held:          e('VERIFY_FAILED->CLASSIFYING'),
    approvedDet:   e('SETTLED->APPROVED'),
    approvedAgent: e('READY->APPROVED'),
  };
}

const occupancy = f => ({
  sources: 0, gate: f.states.BLOCKED, intake: 0, triage: f.states.RECEIVED,
  settled: f.states.SETTLED, agent: f.states.CLASSIFYING,
  verify: f.states.VERIFY_FAILED, needs: f.states.NEEDS_INPUT,
  ready: f.states.READY, approved: f.states.APPROVED, dept: 0,
});

function labelPoint(a, b, kind) {
  const A = N[a], B = N[b], ca = c(A), cb = c(B);
  switch (kind) {
    case 'v':
      return { x: ca.x + 10, y: (A.y + A.h + B.y) / 2 + 4, anchor: 'start' };
    case 'h':
      return { x: (A.x + A.w + B.x) / 2, y: Math.min(ca.y, cb.y) - 14, anchor: 'middle' };
    case 'skirtR':
      return { x: A.x + A.w - 34, y: B.y - 28, anchor: 'end' };
    case 'loopL':
      return { x: A.x + 36, y: B.y + B.h + 30, anchor: 'start' };
    case 'loopB':
      return { x: (ca.x + B.x) / 2, y: LOOP_Y - 10, anchor: 'middle' };
    case 'baseline':
      return { x: (ca.x + cb.x) / 2, y: BASE_Y - 10, anchor: 'middle' };
    default:
      return { x: (ca.x + cb.x) / 2, y: (ca.y + cb.y) / 2, anchor: 'middle' };
  }
}

//: Cases sitting at a node right now, drawn where they are sitting. Most of a
//: batch is parked at any moment, and that is the honest picture: waiting for a
//: signature is not the same as being in transit.
function parkedDots(node, n, colour) {
  if (!n) return '';
  const shown = Math.min(n, 12), r = 3.4, gap = 9;
  const y = node.y + node.h - 10;
  let out = '';
  for (let i = 0; i < shown; i++) {
    out += `<circle cx="${node.x + 14 + i * gap}" cy="${y}" r="${r}"
                    fill="${colour}" opacity=".55"/>`;
  }
  if (n > shown) out += `<text x="${node.x + 14 + shown * gap}" y="${y + 4}"
                               class="ns">+${n - shown}</text>`;
  return out;
}

export function renderFlow(svg, flow, onPick, onHover, trace, moves) {
  // `trace` follows one item: the nodes it has stood at, and where it is now.
  const visited = new Set(trace?.nodes || []);
  const travelled = new Set(trace?.edges || []);
  const t = tally(flow), occ = occupancy(flow), out = [];

  out.push(`<defs>
    <marker id="tipOff" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5"
            markerHeight="6.5" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#b6bfcc"/></marker>
    <marker id="tipOn" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5"
            markerHeight="6.5" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#0f172a"/></marker>
    <marker id="tipTrace" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7"
            markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#7c3aed"/></marker>
  </defs>`);

  for (const z of ZONES) {
    out.push(`<g class="zone">
      <rect x="${z.x}" y="${z.y}" width="${z.w}" height="${z.h}" rx="14"
            fill="${z.tint}" stroke="${z.colour}" stroke-width="1.6"
            stroke-dasharray="7 5" opacity=".95"/>
      <text x="${z.x + 16}" y="${z.y + 24}" class="zl"
            fill="${z.colour}">${z.label}</text>
      <text x="${z.x + 16}" y="${z.y + 41}" class="zn">${z.note}</text>
    </g>`);
  }

  for (const [a, b, key, step, text, kind] of EDGES) {
    const n = key ? (t[key] || 0) : (t.received > 0 ? 1 : 0);
    const on = n > 0;
    const d = path(a, b, kind);
    const walked = travelled.has(`${a}->${b}`);
    out.push(`<path d="${d}" fill="none"
      stroke="${walked ? '#7c3aed' : on ? '#334155' : '#cbd5e1'}"
      stroke-width="${walked ? 3.2 : on ? 1.9 : 1.3}"
      stroke-dasharray="${walked ? 'none' : '6 4'}"
      opacity="${trace && !walked ? .25 : 1}"
      marker-end="url(#${walked ? 'tipTrace' : on ? 'tipOn' : 'tipOff'})"/>`);
    // Motion is reserved for transitions that actually happened since the last
    // look. An edge that carried work an hour ago is drawn thicker; it is not
    // drawn moving, because nothing is moving along it.
    for (const m of (moves || [])) {
      if (`${STATE_NODE[m.from] || 'intake'}->${STATE_NODE[m.to]}` !== `${a}->${b}`) continue;
      out.push(`<circle r="5" fill="#0ea5e9">
        <animateMotion dur="1.4s" repeatCount="1" fill="freeze" path="${d}"/>
        <animate attributeName="opacity" values="0;1;1;0" dur="1.4s" repeatCount="1"
                 fill="freeze"/></circle>`);
    }
    if (walked) out.push(`<circle r="5.5" fill="#7c3aed">
      <animateMotion dur="3s" repeatCount="indefinite" path="${d}"/></circle>`);

    const p = labelPoint(a, b, kind);
    const count = key && t[key] ? `  (${t[key]})` : '';
    out.push(`<text x="${p.x}" y="${p.y}" text-anchor="${p.anchor}"
      class="el ${on ? 'on' : ''}"><tspan class="es">${step}.</tspan> ${text}${count}</text>`);
  }

  for (const node of NODES) {
    const n = occ[node.id] || 0;
    const zone = ZONES.find(z => z.id === node.zone);
    const here = trace && trace.at === node.id;
    const stood = visited.has(node.id);
    out.push(`<g class="node ${n > 0 ? 'on' : ''} ${stood ? 'stood' : ''} ${here ? 'here' : ''}"
                 data-id="${node.id}"
                 style="--zc:${zone.colour}; opacity:${trace && !stood ? .45 : 1}">
      ${here ? `<rect x="${node.x - 7}" y="${node.y - 7}" width="${node.w + 14}"
                      height="${node.h + 14}" rx="14" fill="none" stroke="#7c3aed"
                      stroke-width="2.4" opacity=".55">
                  <animate attributeName="opacity" values=".15;.7;.15" dur="1.6s"
                           repeatCount="indefinite"/></rect>` : ''}
      <rect x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="10"/>
      <text x="${node.x + 14}" y="${node.y + (node.sub ? 27 : 28)}" class="nl">${node.label}</text>
      ${node.sub ? `<text x="${node.x + 14}" y="${node.y + 45}" class="ns">${node.sub}</text>` : ''}
      ${n > 0 ? `<text x="${node.x + node.w - 13}" y="${node.y + 30}" class="nn"
                       fill="${zone.colour}">${n}</text>` : ''}
      ${parkedDots(node, n, zone.colour)}
    </g>`);
  }

  svg.innerHTML = out.join('');
  svg.querySelectorAll('.node').forEach(g => {
    g.addEventListener('click', () => onPick(g.dataset.id));
    g.addEventListener('mouseenter', () => onHover && onHover(g.dataset.id));
  });
}

export function flowSummary(flow) {
  const a = flow.agent || {};
  if (!a.cases) return '';
  const used = Object.entries(flow.tools_used || {})
    .sort((x, y) => y[1] - x[1])
    .map(([k, v]) => `${k.replace(/^(get|search)_/, '')} ${v}`).join(' · ');
  return `${a.cases} case(s) needed judgment · ${a.tool_calls} tool calls, ` +
         `hardest took ${a.worst_case_tools} · ${a.seconds}s of agent time` +
         (used ? ` · ${used}` : '');
}

//: The node a case sits at, given its state. The inverse of NODE_STATES.
export const STATE_NODE = {
  RECEIVED: 'triage', SETTLED: 'settled', CLASSIFYING: 'agent',
  VERIFY_FAILED: 'verify', NEEDS_INPUT: 'needs', READY: 'ready',
  APPROVED: 'approved', BLOCKED: 'gate',
};

//: What has to happen for a case in this state to move, and who has to do it.
//: "automatic" matters as much as the rest: it is the answer to "am I waiting on
//: something", and for most of the batch the answer is no.
export const NEXT_STEP = {
  RECEIVED:      { who: 'automatic', text: 'triage picks it up next' },
  CLASSIFYING:   { who: 'automatic', text: 'an agent is working on it now' },
  VERIFY_FAILED: { who: 'automatic', text: 'citations did not resolve; it goes back to the agent' },
  NEEDS_INPUT:   { who: 'engineering', text: 'blocked until someone answers the question' },
  SETTLED:       { who: 'approver',    text: 'waiting for the batch signature' },
  READY:         { who: 'approver',    text: 'waiting for the batch signature' },
  APPROVED:      { who: 'nobody',      text: 'signed off; nothing further' },
  BLOCKED:       { who: 'operator',    text: 'a data source failed its health check' },
};

//: Which cases sit at each node, for the click-through filter.
export const NODE_STATES = {
  gate: ['BLOCKED'], triage: ['RECEIVED'], settled: ['SETTLED'],
  agent: ['CLASSIFYING'], verify: ['VERIFY_FAILED'], needs: ['NEEDS_INPUT'],
  ready: ['READY'], approved: ['APPROVED'], sources: [], intake: [], dept: [],
};
