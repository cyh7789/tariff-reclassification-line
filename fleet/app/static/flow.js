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

// Three blocks, because there are three answers to "who did this work": a table
// settled it, an agent judged it, or a person signed it. Everything else on this
// screen is detail hanging off that one distinction, so the blocks are the
// biggest thing on the page and the boxes inside them are readable from across a
// room.
//: Positions are the diagram. Left to right is the order work happens in, and a
//: node hanging below another belongs to it: the classifier's four tools are its
//: own, not steps in the chain. No enclosing boxes, because the boxes were doing
//: the job that colour and position do better, and they cost a third of the room.
const KIND = {
  machine: {colour: '#0284c7', tint: '#eff8ff', what: 'done by program, no model call'},
  agent:   {colour: '#059669', tint: '#ecfdf5', what: 'judged by Gemini, with citations'},
  person:  {colour: '#d97706', tint: '#fffbeb', what: 'waiting for a named person'},
};

const OWNER = {
  gate: 'operator', intake: 'operator',
  needs: 'contributor',
  settled: 'approver', ready: 'approver',
};

const ROLE_LABEL = {operator: 'operator', contributor: 'engineering', approver: 'approver'};

//: Default node size. The agent carries its own, because the whole point of this
//: view is that it is not one box among ten.
const W = 176, H = 68;
const wOf = n => n.w || W;
const hOf = n => n.h || H;

//: The corpora the agent can reach into, with what is actually in them. A count
//: is what separates "it has tools" from "it went and read 218,606 rulings":
//: these are row counts from the snapshot manifest, not round numbers.
const CORPUS = {
  get_chapter_notes: {label: 'chapter & section notes', size: '98 chapters'},
  get_tariff_lines:  {label: 'the tariff schedule',     size: '35,791 lines'},
  search_precedents: {label: 'past CBP rulings',        size: '218,606 rulings'},
  get_ruling:        {label: 'what the goods were',     size: '8,581 full texts'},
};

//: What the agent is not allowed to touch. Drawn inside its own box rather than
//: as a footnote, because bounded authority is the claim being made and a claim
//: in a footnote is a claim nobody reads.
const OUT_OF_REACH = [
  'no duty rates, no chapter 99, no money',
  'cannot sign, cannot release a batch',
  'no answer without citations that resolve',
];

const NODES = [
  { id: 'intake', x: 40, y: 336, kind: 'machine', icon: '⇥',
    label: 'Batch in', sub: 'CSV or catalog',
    what: 'The lines to classify, as exported from the ERP: filed code, goods, and '
        + 'whatever else the export carries. Quantity, origin and supplier are picked '
        + 'up when present, because the duty and the screening need them.',
    why:  'Nobody re-files a catalog for fun. The codes sat correct for years and '
        + 'became wrong without anybody touching them.' },

  { id: 'gate', x: 40, y: 452, kind: 'machine', icon: '⛨',
    label: 'Snapshot', sub: 'dated · hashed · gated',
    what: 'A frozen copy of the law, checked before use: 35,791 tariff lines, the '
        + 'notes of all 98 chapters, 218,606 past rulings, 25,939 screening entries. '
        + 'Row counts, sizes, hashes and age are verified before anything reads it.',
    why:  'These government endpoints answer a wrong URL with HTTP 200 and an empty '
        + 'body. An empty screening list passes every party, so the line stops rather '
        + 'than working from a file that only looks fine.' },

  //: The delegation decision, drawn as a decision. "Which of these deserves a
  //: model call" is the question the track asks about delegating to specialists,
  //: and it was previously a blue box indistinguishable from a data loader.
  { id: 'triage', x: 286, y: 322, kind: 'machine', icon: '⋔', w: 200, h: 96,
    label: 'Which deserve', sub: 'a model call?',
    what: 'Set arithmetic against the current schedule: code still valid, code '
        + 'withdrawn, or code valid but its coverage moved. A withdrawn code the '
        + 'official table maps one-to-one is answered here and closed.',
    why:  'This part needs no judgment, so it must not cost a model call. Sending '
        + 'these to a model would pad the autonomy figure with free wins, and it is '
        + 'also what decides what the agent is measured on.' },

  { id: 'settled', x: 286, y: 150, kind: 'machine', icon: '✓',
    label: 'Answered by lookup', sub: 'never reaches the agent',
    what: 'Lines whose code is unchanged, plus withdrawn codes the official table '
        + 'maps one-to-one. Answered by lookup and closed.',
    why:  'Sending these to a model would pad the autonomy figure with free wins.' },

  { id: 'agent', x: 590, y: 288, kind: 'agent', icon: '◇', w: 340, h: 134,
    label: 'Tariff research agent', sub: 'Gemini 3.7 Flash',
    what: 'Reads the chapter and section notes, the tariff lines under each candidate '
        + 'and prior rulings on comparable goods, then chooses one 8-digit code, names '
        + 'the runner-up, and accounts for every candidate it dropped. Measured over '
        + '141 items: 1,034 tool calls, a median of 7 per item, 504 of them searches '
        + 'through past rulings.',
    why:  'The correlation table states that it has "no legal status" and is "a guide '
        + 'only". It says where to look. Deciding needs the notes and the precedents.' },

  { id: 'verify', x: 1024, y: 336, kind: 'machine', icon: '⚖',
    label: 'Citation check', sub: 'every reference re-resolved',
    what: 'A program, not a model. Does the ruling exist, does the note number exist, '
        + 'are the quoted words really in it. The authority behind every candidate the '
        + 'agent ruled out is re-resolved too.',
    why:  'On Vertex the Pro line stops at 3.1, below this project\'s floor, so "have '
        + 'a stronger model check it" is not available. A model that never read the '
        + 'note paraphrases it, and a paraphrase fails a substring check.' },

  { id: 'compliance', x: 1264, y: 336, kind: 'machine', icon: '$',
    label: 'What it costs', sub: 'seven kinds of consequence',
    what: 'What the settled code means for this entry: the gap against what was filed, '
        + 'the chapter 99 add-on, the duty on lines charged by weight, what the choice '
        + 'was worth, whether the eighth digit decided the Section 301 exposure, and '
        + 'any supplier resembling one of 25,939 listed parties.',
    why:  'Money follows arithmetic, so the arithmetic is done. Identity does not: '
        + 'resemblance is constant, so that one is handed over with what matched and '
        + 'what differs, never decided here.' },

  { id: 'ready', x: 1504, y: 336, kind: 'person', icon: '✎',
    label: 'Ready to sign', sub: 'evidence pack attached',
    what: 'Selected code, runner-up, the fact that separates them, what the entry owes '
        + 'and where that came from, the notes and rulings behind it, verified.',
    why:  'The licensed person is signing a legal declaration. What they need is a '
        + 'decision they can check, not a shortlist to work through.' },

  { id: 'approved', x: 1744, y: 336, kind: 'person', icon: '✔',
    label: 'Approved', sub: 'one action, whole batch',
    what: 'One signature releases everything that passed. Anything refused or '
        + 'unverified is held back and named.',
    why:  'Signing row by row is the hand-holding this system exists to remove.' },

  { id: 'needs', x: 1520, y: 528, kind: 'person', icon: '?',
    label: "On somebody's desk", sub: 'the question, and who holds it',
    what: 'Lines the system refused to settle: a property the description never '
        + 'stated, a quantity the entry never carried, a supplier that resembles a '
        + 'listed party. Each says what is missing and which function holds it.',
    why:  'Filing on a guess costs the duty difference plus penalties, and the person '
        + 'who signed owes it. A question with a named owner is cheaper than a queue.' },
];

//: The four corpora, hung on the diagonals around the agent so the picture reads
//: outward from it. Each carries how big the corpus is and how many times this
//: batch went into it.
const SUBS = [
  { of: 'agent', id: 'notes',  x: 545, y: 148, tool: 'get_chapter_notes' },
  { of: 'agent', id: 'lines',  x: 975, y: 148, tool: 'get_tariff_lines' },
  { of: 'agent', id: 'search', x: 545, y: 566, tool: 'search_precedents' },
  { of: 'agent', id: 'ruling', x: 975, y: 566, tool: 'get_ruling' },
];

// from, to, count key, label, routing
const EDGES = [
  ['intake',     'triage',    'received',      'the batch',      'fwd'],
  ['gate',       'triage',    'received',      'law, gated',     'fwd'],
  ['triage',     'settled',   'deterministic', 'no, look it up', 'fwd'],
  ['triage',     'agent',     'agent',         'yes, judgment',  'fwd'],
  ['agent',      'verify',    'classified',    'proposed code',  'fwd'],
  ['verify',     'compliance','verified',      'citations hold', 'fwd'],
  ['compliance', 'ready',     'settledHere',   'costed',         'fwd'],
  ['ready',      'approved',  'approvedAgent', 'sign',           'fwd'],
  ['settled',    'approved',  'approvedDet',   'sign',           'over'],
  ['agent',      'needs',     'refused',       'will not guess', 'down'],
  ['compliance', 'needs',     'forAPerson',    'identity',       'down'],
  ['needs',      'agent',     'requeued',      'answered',       'under'],
  ['verify',     'agent',     'held',          'held back',      'back'],
];

const N = Object.fromEntries(NODES.map(n => [n.id, n]));
const inPort = n => ({x: n.x, y: n.y + hOf(n) / 2});
const outPort = n => ({x: n.x + wOf(n), y: n.y + hOf(n) / 2});

function path(a, b, kind) {
  const A = N[a], B = N[b], p = outPort(A), q = inPort(B);
  switch (kind) {
    case 'fwd': {
      const d = Math.max(40, (q.x - p.x) / 2);
      return `M ${p.x} ${p.y} C ${p.x + d} ${p.y}, ${q.x - d} ${q.y}, ${q.x} ${q.y}`;
    }
    case 'over':   // the lookup half going straight to the signature, over the top
      return `M ${p.x} ${p.y} C ${p.x + 420} ${p.y - 70}, ${q.x + 150} ${q.y - 230}, ${q.x + wOf(B) / 2} ${q.y - hOf(B) / 2 - 6}`;
    case 'down': {  // a refusal dropping to the desk it belongs on, under the row
      const drop = Math.max(p.y, q.y) + 40;
      return `M ${A.x + wOf(A) / 2} ${A.y + hOf(A)} C ${A.x + wOf(A) / 2} ${drop}, ${q.x - 120} ${q.y}, ${q.x} ${q.y}`;
    }
    case 'under':  // the answered question coming back, below everything
      return `M ${A.x} ${A.y + hOf(A) / 2} C ${A.x - 400} ${A.y + 190}, ${B.x - 50} ${B.y + 210}, ${B.x - 6} ${B.y + hOf(B) / 2 + 4}`;
    case 'back':   // a failed citation check going back for another attempt
      return `M ${A.x} ${A.y + 16} C ${A.x - 70} ${A.y - 70}, ${B.x + wOf(B) + 70} ${B.y - 70}, ${B.x + wOf(B)} ${B.y + 16}`;
    default:
      return `M ${p.x} ${p.y} L ${q.x} ${q.y}`;
  }
}

function labelPoint(a, b, kind) {
  const A = N[a], B = N[b], p = outPort(A), q = inPort(B);
  switch (kind) {
    // Above the boxes, not between them: the gap between two nodes is 74px and
    // no useful label is that short.
    case 'fwd':   return {x: (p.x + q.x) / 2, y: Math.min(A.y, B.y) - 12, anchor: 'middle'};
    case 'over':  return {x: (p.x + q.x) / 2 + 120, y: Math.min(p.y, q.y) - 118, anchor: 'middle'};
    case 'down':  return {x: (A.x + wOf(A) / 2 + q.x) / 2, y: Math.max(p.y, q.y) + 34, anchor: 'middle'};
    case 'under': return {x: (A.x + B.x) / 2, y: A.y + 176, anchor: 'middle'};
    case 'back':  return {x: (A.x + B.x + wOf(B)) / 2, y: Math.min(A.y, B.y) - 46, anchor: 'middle'};
    default:      return {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2, anchor: 'middle'};
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
    // Closing a duty question is not a state change, which is exactly why the
    // compliance work was invisible until it was counted from the findings.
    settledHere:   (flow.dispositions || {}).settled_here || 0,
    forAPerson:    (flow.dispositions || {}).for_a_person || 0,
  };
}

const occupancy = f => ({
  gate: f.states.BLOCKED, intake: 0, triage: f.states.RECEIVED,
  settled: f.states.SETTLED, agent: f.states.CLASSIFYING,
  verify: f.states.VERIFY_FAILED, needs: f.states.NEEDS_INPUT,
  ready: f.states.READY, approved: f.states.APPROVED,
  compliance: (f.dispositions || {}).settled_here || 0,
});

//: Cases sitting at a node right now, drawn where they sit. Most of a batch is
//: parked at any moment, and that is the honest picture.
function parkedDots(node, n, colour) {
  if (!n) return '';
  const shown = Math.min(n, 10), gap = 9;
  const y = node.y + hOf(node) - 9;
  let out = '';
  for (let i = 0; i < shown; i++)
    out += `<circle cx="${node.x + 58 + i * gap}" cy="${y}" r="3.2" fill="${colour}" opacity=".5"/>`;
  if (n > shown)
    out += `<text x="${node.x + 58 + shown * gap}" y="${y + 4}" class="ns">+${n - shown}</text>`;
  return out;
}

//: Signed in as the role that owns a gate, it carries your name; as anyone else
//: it is locked. Switching role has to change the picture, because the whole
//: point is that the engineer who answers is not the person who may sign.
function gateBadge(node, role) {
  const owner = OWNER[node.id];
  if (!owner) return '';
  const mine = owner === role;
  //: A stripe down the node's own left edge and a word inside it. The badge used
  //: to be an amber pill with a padlock hanging outside the box, which read as a
  //: mislabelled node: amber is the colour this diagram uses for "waiting for a
  //: person", so an amber tag under a blue box said the wrong thing twice.
  return `<rect x="${node.x}" y="${node.y}" width="4" height="${hOf(node)}"
                fill="#d97706" opacity="${mine ? 1 : .45}"/>
    <text x="${node.x + 11}" y="${node.y + hOf(node) - 7}" class="gb"
          fill="${mine ? '#b45309' : '#a8b0bd'}"
          >${mine ? 'yours' : ROLE_LABEL[owner]}</text>`;
}

//: The rectangle the work occupies. Fitting the view cannot ask the group for its
//: bounding box: the dotted ground is a 12,000px square riding in the same group,
//: so the answer would be the ground and the graph would vanish to a speck.
//: One source for where the legend row sits, so fitting the view cannot crop it.
//: It used to be computed inline and `graphBounds` never knew about it, which
//: put the whole legend outside the fitted viewBox.
const legendY = () => Math.min(...NODES.map(n => n.y)) - 96;

export function graphBounds() {
  const xs = NODES.flatMap(n => [n.x - 10, n.x + wOf(n) + 10]);
  const ys = NODES.flatMap(n => [n.y - 30, n.y + hOf(n) + 34]);
  ys.push(legendY() - 18);
  for (const s of SUBS) { xs.push(s.x - 78, s.x + 78); ys.push(s.y - 30, s.y + 62); }
  const x = Math.min(...xs), y = Math.min(...ys);
  return {x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y};
}

export function renderFlow(svg, flow, onPick, onHover, trace, moves, role) {
  const visited = new Set(trace?.nodes || []);
  const travelled = new Set(trace?.edges || []);
  const t = tally(flow), occ = occupancy(flow), out = [];

  out.push(`<defs>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
      <circle cx="1.5" cy="1.5" r="1.1" fill="#d9e0ea"/></pattern>
    <marker id="tipOff" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"
            markerHeight="6" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#c3ccd8"/></marker>
    <marker id="tipOn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"
            markerHeight="6" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#475569"/></marker>
    <marker id="tipTrace" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
            markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="#7c3aed"/></marker>
  </defs>`);
  out.push(`<rect class="ground" x="-4000" y="-4000" width="12000" height="12000"
                  fill="url(#dots)"/>`);

  // The legend replaces the three boxes that used to enclose everything.
  //: On its own row above everything, because character-count width estimates
  //: put it through the edge labels the moment one string got longer.
  const top = legendY();
  let lx = Math.min(...NODES.map(n => n.x));
  for (const meta of Object.values(KIND)) {
    out.push(`<g><circle cx="${lx}" cy="${top}" r="6" fill="${meta.colour}"/>
      <text x="${lx + 14}" y="${top + 4}" class="lg">${meta.what}</text></g>`);
    lx += meta.what.length * 7.6 + 74;
  }

  for (const [a, b, key, text, kind] of EDGES) {
    const n = key ? (t[key] || 0) : 0;
    const on = n > 0;
    const d = path(a, b, kind);
    const walked = travelled.has(`${a}->${b}`);
    out.push(`<path d="${d}" fill="none"
      stroke="${walked ? '#7c3aed' : on ? '#64748b' : '#cdd5e0'}"
      stroke-width="${walked ? 3 : on ? 2 : 1.4}"
      opacity="${trace && !walked ? .2 : 1}"
      marker-end="url(#${walked ? 'tipTrace' : on ? 'tipOn' : 'tipOff'})"/>`);
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
    out.push(`<text x="${p.x}" y="${p.y}" text-anchor="${p.anchor}"
      class="el ${on ? 'on' : ''}">${text}${n ? ` (${n})` : ''}</text>`);
  }

  // The corpora, on the diagonals around the agent. Each says how big it is and
  // how many times this batch went into it, because "it has tools" and "it read
  // 218,606 rulings 504 times" are not the same claim and only one is checkable.
  for (const sub of SUBS) {
    const parent = N[sub.of];
    const calls = (flow.tools_used || {})[sub.tool] || 0;
    const corpus = CORPUS[sub.tool] || {label: sub.tool, size: ''};
    const colour = KIND[parent.kind].colour;
    const cx = parent.x + wOf(parent) / 2, cy = parent.y + hOf(parent) / 2;
    const below = sub.y > cy;
    out.push(`<path d="M ${cx} ${cy} L ${sub.x} ${sub.y + (below ? -26 : 26)}"
      stroke="${calls ? colour : '#cdd5e0'}" stroke-width="${calls ? 1.8 : 1.2}"
      stroke-dasharray="5 5" fill="none" opacity="${trace ? .2 : 1}"/>
    <g class="sub">
      <circle cx="${sub.x}" cy="${sub.y}" r="26" fill="#fff"
              stroke="${calls ? colour : '#cdd5e0'}" stroke-width="${calls ? 2.4 : 1.4}"/>
      <text x="${sub.x}" y="${sub.y + 6}" text-anchor="middle" class="subn"
            fill="${calls ? colour : '#94a3b8'}">${calls || '·'}</text>
      <text x="${sub.x}" y="${sub.y + (below ? 46 : -38)}" text-anchor="middle"
            class="nl2">${corpus.size}</text>
      <text x="${sub.x}" y="${sub.y + (below ? 61 : -24)}" text-anchor="middle"
            class="ns">${corpus.label}</text>
    </g>`);
  }

  for (const node of NODES) {
    const n = occ[node.id] || 0;
    const meta = KIND[node.kind];
    const here = trace && trace.at === node.id;
    const stood = visited.has(node.id);
    const locked = OWNER[node.id] && OWNER[node.id] !== role;
    out.push(`<g class="node ${n > 0 ? 'on' : ''} ${stood ? 'stood' : ''} ${here ? 'here' : ''}
                 ${locked ? 'locked' : OWNER[node.id] ? 'mine' : ''}"
                 data-id="${node.id}"
                 style="--zc:${meta.colour}; opacity:${trace && !stood ? .4 : 1}">
      ${here ? `<rect x="${node.x - 7}" y="${node.y - 7}" width="${wOf(node) + 14}" height="${hOf(node) + 14}"
                      rx="15" fill="none" stroke="#7c3aed" stroke-width="2.4" opacity=".55">
                  <animate attributeName="opacity" values=".15;.7;.15" dur="1.6s"
                           repeatCount="indefinite"/></rect>` : ''}
      <rect class="box" x="${node.x}" y="${node.y}" width="${wOf(node)}" height="${hOf(node)}" rx="11"/>
      <rect x="${node.x + 10}" y="${node.y + 13}" width="42" height="42" rx="9"
            fill="${meta.tint}" stroke="${meta.colour}" stroke-width="1.2"/>
      <text x="${node.x + 31}" y="${node.y + 41}" text-anchor="middle" class="ni"
            fill="${meta.colour}">${node.icon}</text>
      <text x="${node.x + 60}" y="${node.y + 30}" class="${node.kind === 'agent' ? 'nlBig' : 'nl'}"
            >${node.label}</text>
      <text x="${node.x + 60}" y="${node.y + (node.kind === 'agent' ? 50 : 47)}" class="ns"
            >${node.sub}${node.kind === 'agent' && flow.agent && flow.agent.tool_calls
               ? ` · ${flow.agent.tool_calls} lookups this batch` : ''}</text>
      ${node.kind === 'agent' ? OUT_OF_REACH.map((line, i) =>
          `<text x="${node.x + 16}" y="${node.y + 76 + i * 17}" class="cant">${line}</text>`
        ).join('') : ''}
      ${n > 0 ? `<g><circle cx="${node.x + wOf(node) - 4}" cy="${node.y + 4}" r="15"
                           fill="${meta.colour}"/>
                    <text x="${node.x + wOf(node) - 4}" y="${node.y + 10}" text-anchor="middle"
                          class="nn">${n}</text></g>` : ''}
      <circle cx="${node.x}" cy="${node.y + hOf(node) / 2}" r="4.5" fill="#fff"
              stroke="${meta.colour}" stroke-width="1.6"/>
      <circle cx="${node.x + wOf(node)}" cy="${node.y + hOf(node) / 2}" r="4.5" fill="${meta.colour}"/>
      ${parkedDots(node, n, meta.colour)}
      ${gateBadge(node, role)}
    </g>`);
  }

  // Everything but the marker definitions rides in one group, dotted ground
  // included, so panning and zooming is a transform on that group rather than a
  // redraw, and the ground moves with the work the way a canvas should.
  const defs = out.shift();
  svg.innerHTML = `${defs}<g id="cam">${out.join('')}</g>`;
  svg.querySelectorAll('.node').forEach(g => {
    g.addEventListener('click', () => onPick(g.dataset.id));
    g.addEventListener('mouseenter', () => onHover && onHover(g.dataset.id));
  });
}

//: Metadata for the explanation panel, keyed the same way as the nodes.
export const NODE_INFO = Object.fromEntries(
  NODES.map(n => [n.id, { label: n.label, what: n.what, why: n.why }]));

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
  ready: ['READY'], approved: ['APPROVED'], intake: [], compliance: [],
};
