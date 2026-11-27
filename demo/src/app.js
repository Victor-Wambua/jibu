'use strict';
/* Jibu demo page. All answers, scores and metrics come from the real Python engine running in
   worker.js; this file only sends questions to it and draws what comes back. */

const REPO = 'https://github.com/Victor-Wambua/jibu';
const VIEWS = {
  ask: 'Ask a question',
  kb: 'Knowledge base',
  eval: 'Evaluation',
  how: 'How this demo works',
};

// Questions to try, per knowledge base. tests/ checks that each one still behaves as labelled.
const TRIES = {
  'umoja-sacco': [
    { label: 'English', turns: ['How do I apply for a loan?'] },
    { label: 'Kiswahili', turns: ['Mnafungua saa ngapi?'] },
    { label: 'Mixed', turns: ['Nataka kujua how to apply for a loan'] },
    { label: 'Typos', turns: ['who can becom a membr of the sacco'] },
    { label: 'Follow-up, two questions', turns: ['How much is the membership fee?', 'and for students?'] },
    { label: 'Not in the FAQ', turns: ['Give me a recipe for pilau'] },
    { label: 'No word matches', turns: ['Tell me a joke'] },
    { label: 'Expiry: sets the date to 1 Apr 2026', date: '2026-04-01', turns: ['When is the AGM?'] },
    { label: 'A known miss: it answers, it should not', turns: ['How do I reset my Safaricom PIN?'] },
  ],
  'afya-clinic': [
    { label: 'English', turns: ['What time does the clinic close?'] },
    { label: 'Kiswahili', turns: ['Nawezaje kuweka miadi?'] },
    { label: 'Insurance', turns: ['Do you take SHA?'] },
    { label: 'Medical advice: hands off', turns: ['I have a headache, what should I take?'] },
    { label: 'Medical advice, Kiswahili', turns: ['Nina homa na kikohozi, nifanye nini?'] },
  ],
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const num = (x, d = 3) => (x == null ? 'n/a' : Number(x).toFixed(d));
const pct = (x) => (x == null ? 'n/a' : `${(100 * x).toFixed(1)}%`);
const code = (t) => h('code', { text: t });
const localISO = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// ---------------------------------------------------------------- state

const state = {
  ready: false,
  kbs: [],
  kb: null,
  threshold: {}, // kb id -> current threshold
  today: localISO(),
  turns: [], // {user, text, reply}
  selected: null,
  busy: false,
  evalRun: null, // last evaluation result
  evalFilter: { show: 'wrong', kind: 'all' },
  sweepRun: null,
  kbDetail: null,
  kbFilter: '',
  info: null,
  manifest: null,
  view: 'ask',
};
const kbInfo = () => state.kbs.find((k) => k.id === state.kb);

// ---------------------------------------------------------------- engine (worker)

let worker = null;
let nextId = 1;
const pending = new Map();

function call(fn, ...args) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, fn, args });
  });
}

function startWorker() {
  if (!window.Worker || !window.WebAssembly) {
    bootError('This browser cannot run WebAssembly in a Web Worker, which the engine needs. Try a current version of Firefox, Chrome, Edge or Safari.');
    return;
  }
  worker = new Worker('worker.js');
  worker.onmessage = ({ data }) => {
    if (data.type === 'progress') $('#boot-text').textContent = `${data.text}...`;
    else if (data.type === 'ready') onReady(data);
    else if (data.type === 'error') bootError(`The engine did not start: ${data.text}`);
    else if (data.id) {
      const p = pending.get(data.id);
      pending.delete(data.id);
      if (data.error) p.reject(new Error(data.error));
      else p.resolve(data);
    }
  };
  worker.onerror = () => bootError('The engine did not start. Check that the page was opened from a web server, not from a file.');
}

function bootError(text) {
  const boot = $('#boot');
  boot.setAttribute('role', 'alert');
  boot.classList.add('failed');
  boot.replaceChildren(h('p', {}, text));
}

async function onReady({ catalogue, info, manifest }) {
  state.kbs = catalogue.kbs;
  state.info = info;
  state.manifest = manifest;
  for (const k of state.kbs) state.threshold[k.id] = k.threshold;
  state.kb = state.kbs.find((k) => k.id === 'umoja-sacco') ? 'umoja-sacco' : state.kbs[0].id;
  await call('set_today', state.today);
  state.ready = true;

  const sel = $('#kb-select');
  sel.replaceChildren(...state.kbs.map((k) => h('option', { value: k.id, text: k.name })));
  sel.value = state.kb;
  $('#as-of').value = state.today;
  syncThreshold();
  for (const id of ['kb-select', 'threshold', 'as-of', 'reset']) $('#' + id).disabled = false;
  $('#q').disabled = false;
  $('#send').disabled = false;
  $('#run-eval').disabled = false;
  $('#run-sweep').disabled = false;

  const boot = $('#boot');
  boot.classList.add('done');
  boot.replaceChildren(h('p', {}, `Engine ready. Python ${info.python} running in your browser; started in ${(info.bootMs / 1000).toFixed(1)} s. `, h('a', { href: '#how' }, 'What was loaded')));
  renderTries();
  welcome();
  renderView();
}

// ---------------------------------------------------------------- context bar

function syncThreshold() {
  const t = state.threshold[state.kb];
  $('#threshold').value = t;
  $('#threshold-out').textContent = num(t, 2);
}

function bindContext() {
  $('#kb-select').addEventListener('change', async (e) => {
    state.kb = e.target.value;
    syncThreshold();
    await newConversation(`Switched to ${kbInfo().name}.`);
    state.evalRun = null;
    state.sweepRun = null;
    state.kbDetail = null;
    renderTries();
    renderView();
  });
  $('#threshold').addEventListener('input', (e) => {
    $('#threshold-out').textContent = num(e.target.value, 2);
  });
  $('#threshold').addEventListener('change', async (e) => {
    state.threshold[state.kb] = Number(e.target.value);
    await call('set_threshold', state.kb, state.threshold[state.kb]);
    if (state.view === 'eval') renderEval();
    if (state.view === 'kb') loadKb();
  });
  $('#as-of').addEventListener('change', async (e) => {
    if (!e.target.value) {
      e.target.value = state.today;
      return;
    }
    state.today = e.target.value;
    await call('set_today', state.today);
    if (state.view === 'kb') loadKb();
  });
  $('#reset').addEventListener('click', async () => {
    const cat = (await call('init')).result;
    state.kbs = cat.kbs;
    for (const k of state.kbs) state.threshold[k.id] = k.threshold;
    state.today = localISO();
    await call('set_today', state.today);
    $('#as-of').value = state.today;
    syncThreshold();
    state.evalRun = null;
    state.sweepRun = null;
    state.kbDetail = null;
    await newConversation('Demo reset: threshold, date and hand-off queue are back to their defaults.');
    renderView();
  });
}

// ---------------------------------------------------------------- routing

function parseHash() {
  const [view, rest] = location.hash.replace(/^#/, '').split('/');
  return { view: VIEWS[view] ? view : 'ask', rest: rest ? decodeURIComponent(rest) : null };
}

function renderView(focus = false) {
  const { view, rest } = parseHash();
  state.view = view;
  for (const s of $$('[data-view]')) s.hidden = s.dataset.view !== view;
  for (const a of $$('[data-nav]')) {
    if (a.dataset.nav === view) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  document.title = `${VIEWS[view]} - Jibu demo`;
  const dateInput = $('#as-of');
  dateInput.disabled = !state.ready || view === 'eval';
  if (state.ready) {
    if (view === 'kb') loadKb(rest);
    if (view === 'eval') renderEval();
    if (view === 'how') renderHow();
  }
  if (focus) $(`#h-${view}`).focus({ preventScroll: false });
}

// ---------------------------------------------------------------- ask

function renderTries() {
  const list = $('#try-list');
  list.replaceChildren(
    ...(TRIES[state.kb] || []).map((t) =>
      h('li', {},
        h('button', { type: 'button', class: 'try-btn', onclick: () => runTry(t) },
          h('span', { class: 'try-label', text: t.label }),
          h('span', { class: 'try-q', text: t.turns.join('  then  ') })))
    )
  );
}

async function runTry(t) {
  if (t.date) {
    state.today = t.date;
    $('#as-of').value = t.date;
    await call('set_today', t.date);
  }
  if (location.hash !== '#ask' && location.hash !== '') location.hash = '#ask';
  $('#log').scrollIntoView({ block: 'nearest' });
  for (const q of t.turns) await sendQuestion(q);
}

function welcome() {
  const k = kbInfo();
  const log = $('#log');
  log.replaceChildren(
    h('div', { class: 'turn bot note' },
      h('p', { class: 'who', text: 'Jibu' }),
      h('p', { class: 'text', text: k.welcome.en }),
      h('p', { class: 'text', lang: 'sw', text: k.welcome.sw }))
  );
}

async function newConversation(note) {
  await call('reset_session');
  state.turns = [];
  state.selected = null;
  welcome();
  if (note) $('#log').append(h('p', { class: 'system', text: note }));
  renderWhy();
  await renderQueue();
}

function statusLabel(r) {
  return { answered: 'Answered', handoff: 'Handed to staff', smalltalk: 'Small talk' }[r.status];
}

function addTurn(turn) {
  const i = state.turns.push(turn) - 1;
  const log = $('#log');
  if (turn.user) {
    log.append(h('div', { class: 'turn you' }, h('p', { class: 'who', text: 'You' }), h('p', { class: 'text', text: turn.text })));
  } else {
    const r = turn.reply;
    const meta = h('p', { class: 'meta' }, h('strong', { class: 'tag', text: statusLabel(r) }));
    if (r.status === 'answered') {
      meta.append(' ', h('span', {}, 'Source: ', h('a', { href: `#kb/${encodeURIComponent(r.entry_id)}` }, r.entry_id)));
    } else if (r.status === 'handoff' && r.closest_entry) {
      meta.append(' ', h('span', {}, 'Closest entry (not used): ', code(r.closest_entry)));
    } else if (r.status === 'smalltalk') {
      meta.append(' ', h('span', {}, 'No entry used'));
    }
    if (r.status !== 'smalltalk') meta.append(' ', h('span', { class: 'num' }, `confidence ${confText(r)}`));
    meta.append(' ', h('button', { type: 'button', class: 'linkbtn', onclick: () => select(i, true) }, 'Why this reply'));
    const el = h('div', { class: `turn bot ${r.status}`, 'data-i': i },
      h('p', { class: 'who', text: 'Jibu' }),
      h('p', { class: 'text', lang: r.language, text: r.text }),
      meta);
    if (r.suggestions.length) {
      el.append(h('div', { class: 'suggest' },
        h('p', { class: 'help', text: r.status === 'handoff' ? 'You could ask about:' : 'You could ask next:' }),
        h('ul', {}, r.suggestions.map(([, q]) =>
          h('li', {}, h('button', { type: 'button', class: 'linkbtn', onclick: () => sendQuestion(q) }, q))))));
    }
    log.append(el);
    turn.el = el;
  }
  log.scrollTop = log.scrollHeight;
  return i;
}

// Show 3 decimals; if that would hide which side of the threshold a score is on, show 4.
function confText(r) {
  let s = num(r.confidence, 3);
  const t = num(r.threshold, 3);
  if (s === t && (r.confidence >= r.threshold) !== (r.status === 'answered')) s = num(r.confidence, 4);
  return s;
}

async function sendQuestion(text) {
  text = text.trim();
  const err = $('#q-error');
  if (!state.ready) return;
  if (!text) {
    err.textContent = 'Type a question first, for example "Mnafungua saa ngapi?" or "How do I apply for a loan?".';
    err.hidden = false;
    $('#q').setAttribute('aria-invalid', 'true');
    $('#q').focus();
    return;
  }
  err.hidden = true;
  $('#q').removeAttribute('aria-invalid');
  if (state.busy) return;
  state.busy = true;
  try {
    addTurn({ user: true, text });
    const { result } = await call('ask', state.kb, text);
    const i = addTurn({ reply: result, text });
    select(i, false);
    await renderQueue();
  } catch (e) {
    $('#log').append(h('p', { class: 'system', role: 'alert', text: `The engine reported an error: ${e.message}` }));
  } finally {
    state.busy = false;
  }
}

function select(i, moveFocus) {
  state.selected = i;
  for (const t of state.turns) if (t.el) t.el.classList.toggle('selected', t === state.turns[i]);
  renderWhy();
  if (moveFocus) {
    const why = $('#why');
    why.scrollIntoView({ block: 'nearest' });
    why.focus({ preventScroll: true });
  }
}

function matchText(t) {
  switch (t.kind) {
    case 'question': return 'In the entry’s questions or tags';
    case 'answer': return 'Only in its answer text';
    case 'synonym': return `Synonym “${t.via}” is in its questions`;
    case 'synonym-answer': return `Synonym “${t.via}” is in its answer text`;
    default: return 'Not found in this entry';
  }
}

function renderWhy() {
  const body = $('#why-body');
  const turn = state.turns[state.selected];
  if (!turn) {
    body.replaceChildren(h('p', { class: 'empty', text: 'Ask a question and this panel shows how Jibu decided: which words matched, which entry won, how far ahead of the runner-up it was, and whether the confidence cleared the threshold.' }));
    return;
  }
  const r = turn.reply;
  const out = [];

  // verdict + gauge
  const verdict = {
    answered: 'Answered from the knowledge base',
    handoff: 'Handed to staff',
    smalltalk: 'Greeting or thanks: canned reply',
  }[r.status];
  out.push(h('p', { class: `verdict ${r.status}` }, h('strong', { text: verdict })));
  out.push(h('p', { class: 'asked' }, 'Question: ', h('q', { text: turn.text })));

  if (r.status === 'smalltalk') {
    out.push(h('p', { text: 'The message was only a greeting, thanks or goodbye, so Jibu used the canned reply from the knowledge base and searched no entry.' }));
  } else {
    out.push(gauge(r));
    out.push(h('p', { class: 'because' }, because(r)));
  }

  // source / closest
  if (r.status !== 'smalltalk') {
    const dl = h('dl', { class: 'facts' });
    const add = (k, v) => dl.append(h('dt', { text: k }), h('dd', {}, v));
    if (r.status === 'answered') {
      add('Source entry', h('a', { href: `#kb/${encodeURIComponent(r.entry_id)}` }, r.entry_id));
    } else {
      add('Closest entry, not used', r.closest_entry ? h('a', { href: `#kb/${encodeURIComponent(r.closest_entry)}` }, r.closest_entry) : 'none');
    }
    if (r.closest_question) add('Closest example question', h('span', { text: r.closest_question }));
    if (r.source && (r.source.valid_from || r.source.valid_until)) {
      add('Valid', `${r.source.valid_from || 'always'} to ${r.source.valid_until || 'no end'} (date used: ${r.as_of})`);
    }
    add('Language', `detected ${langName(r.detected)}, replied in ${langName(r.language)}`);
    if (r.used_context) add('Follow-up', 'The previous answer’s topic was added, because the question was short or began like a follow-up.');
    out.push(dl);
  }

  // tokens
  if (r.status !== 'smalltalk' && r.closest_entry) {
    out.push(h('h3', { text: 'Words and what they matched' }));
    out.push(h('p', { class: 'help' }, 'Compared with entry ', code(r.closest_entry), '. Rarer words weigh more.'));
    const rows = r.tokens.map((t) =>
      h('tr', {},
        h('th', { scope: 'row' }, h('span', { text: t.word }), t.corrected ? h('span', { class: 'sub', text: `fixed to “${t.corrected}”` }) : null),
        h('td', { text: t.repeat ? 'Same search key as an earlier word' : matchText(t) }),
        h('td', { class: 'n', text: num(t.rarity, 2) }),
        h('td', { class: 'n', text: t.repeat ? '' : `${num(t.credit, 2)}` })));
    if (rows.length) {
      out.push(tableWrap('Words in the question, with the match against the closest entry',
        ['Word', 'Match', 'Rarity', 'Credit'], rows, ['', '', 'n', 'n']));
    } else {
      out.push(h('p', { text: 'No searchable words were left after removing common words.' }));
    }
    if (r.ignored.length) out.push(h('p', { class: 'help' }, 'Ignored as common words: ', r.ignored.join(', '), '.'));
    out.push(h('p', { class: 'help' }, `Coverage ${num(r.coverage, 3)}: the share of the question’s weighted words this entry explains.`));
  } else if (r.status !== 'smalltalk') {
    out.push(h('p', { text: r.tokens.length ? 'None of the question’s words appear in the knowledge base.' : 'No searchable words were left after removing common words.' }));
  }

  // candidates
  if (r.candidates.length) {
    out.push(h('h3', { text: 'Winner and runner-up' }));
    const rows = r.candidates.map((c, i) =>
      h('tr', {},
        h('th', { scope: 'row' }, h('span', { text: c.id }), h('span', { class: 'sub', text: i === 0 ? 'highest score' : `rank ${i + 1}` })),
        h('td', { class: 'n', text: num(c.score, 2) }),
        h('td', { class: 'n', text: num(c.coverage, 2) }),
        h('td', { class: 'n', text: num(c.confidence, 3) })));
    out.push(tableWrap('Top entries by score', ['Entry', 'Score', 'Coverage', 'Confidence'], rows, ['', 'n', 'n', 'n']));
    out.push(h('p', { class: 'help' }, 'Score is BM25 over the entry’s questions, tags and answer text. Higher is a closer match.'));
    out.push(lead(r));
    out.push(formula(r));
  }

  // hand-off
  if (r.status === 'handoff') {
    out.push(h('h3', { text: 'What happens next' }));
    out.push(h('p', { text: 'Jibu sends the organisation’s hand-off message and adds the question to the staff queue. The queue record holds the time, language, confidence and closest entry. It does not keep the words you typed.' }));
    if (r.queued) {
      out.push(h('dl', { class: 'facts' },
        h('dt', { text: 'Queue record' }), h('dd', { class: 'num', text: r.queued.id }),
        h('dt', { text: 'Language' }), h('dd', { text: langName(r.queued.language) }),
        h('dt', { text: 'Confidence' }), h('dd', { class: 'num', text: num(r.queued.confidence, 3) }),
        h('dt', { text: 'Closest entry' }), h('dd', { text: r.queued.best_guess || 'none' })));
    }
  }

  // try again
  if (r.status !== 'smalltalk') {
    out.push(h('div', { class: 'again' },
      h('p', { class: 'help', text: 'Change the hand-off threshold above, then ask the same question again to see whether the decision flips.' }),
      h('button', { type: 'button', class: 'btn', onclick: () => sendQuestion(turn.text) }, 'Ask this again')));
  }
  body.replaceChildren(...out);
}

function langName(l) {
  return { en: 'English', sw: 'Kiswahili', mixed: 'mixed', und: 'unclear' }[l] || l;
}

function gauge(r) {
  const ok = r.confidence >= r.threshold;
  return h('div', { class: `gauge ${ok ? 'pass' : 'fail'}` },
    h('p', { class: 'gauge-fig' },
      h('span', { class: 'big num', text: confText(r) }),
      h('span', { class: 'num', text: ` confidence, threshold ${num(r.threshold, 2)}` })),
    h('div', {
      class: 'meter', role: 'meter', 'aria-label': 'Confidence', 'aria-valuemin': '0', 'aria-valuemax': '1',
      'aria-valuenow': String(r.confidence),
      'aria-valuetext': `${confText(r)}, ${ok ? 'at or above' : 'below'} the threshold ${num(r.threshold, 2)}`,
    },
      h('span', { class: 'fill', style: `width:${Math.min(100, r.confidence * 100)}%` }),
      h('span', { class: 'tick', style: `left:${r.threshold * 100}%` })),
    h('p', { class: 'scale' }, h('span', { text: '0' }), h('span', { text: '1' })));
}

function because(r) {
  if (r.status === 'answered') {
    return `Confidence ${confText(r)} is at or above the threshold ${num(r.threshold, 2)}, so Jibu used the approved answer word for word.`;
  }
  if (r.reason === 'no_overlap') {
    return 'No word of the question appears in any active entry, so there is nothing close to offer. This is the out-of-scope case.';
  }
  const f = r.formula;
  let why = `Confidence ${confText(r)} is below the threshold ${num(r.threshold, 2)}, so Jibu did not answer. `;
  if (f && f.coverage < r.threshold) {
    why += `The closest entry explains only ${Math.round(f.coverage * 100)}% of the question’s weighted words.`;
  } else if (f && f.margin_factor < 1) {
    why += `The closest entry covers the question, but it leads the runner-up by too little (${Math.round(f.margin * 100)}%; ${Math.round(f.margin_scale * 100)}% or more is needed for full confidence).`;
  }
  return why;
}

function lead(r) {
  const f = r.formula;
  if (r.gap == null) {
    return h('p', { text: 'No runner-up: only one entry shared a word with the question.' });
  }
  return h('p', {},
    `Margin to the runner-up (${r.runner_up}): ${num(r.gap, 2)} score points, ${Math.round(f.margin * 100)}% of the winner’s score. `,
    f.margin_factor >= 1
      ? `A margin of ${Math.round(f.margin_scale * 100)}% or more counts fully.`
      : `Below ${Math.round(f.margin_scale * 100)}% the confidence is scaled down.`);
}

function formula(r) {
  const f = r.formula;
  const parts = `${num(f.coverage, 3)} × (${f.base} + ${f.w_rel} × ${num(f.relative, 3)} + ${f.w_margin} × ${num(f.margin_factor, 3)})`;
  return h('details', { class: 'formula' },
    h('summary', { text: 'How confidence is computed' }),
    h('p', {}, 'confidence = coverage × (', f.base, ' + ', f.w_rel, ' × relative score + ', f.w_margin, ' × margin factor)'),
    h('p', { class: 'num' }, `${parts} = ${num(r.confidence, 3)}`),
    h('p', { class: 'help', text: 'Relative score is how much of the best possible score for these words the entry reaches. Margin factor is the margin to the runner-up divided by the margin that counts fully, capped at 1.' }));
}

function tableWrap(caption, heads, rows, aligns = []) {
  return h('div', { class: 'scroll', role: 'region', tabindex: '0', 'aria-label': caption },
    h('table', {},
      h('caption', { class: 'sr', text: caption }),
      h('thead', {}, h('tr', {}, heads.map((x, i) => h('th', { scope: 'col', class: aligns[i] || null, text: x })))),
      h('tbody', {}, rows)));
}

async function renderQueue() {
  const { result } = await call('queue');
  const body = $('#queue-body');
  if (!result.length) {
    body.replaceChildren(h('p', { class: 'empty', text: 'Nothing handed off yet. Ask something the FAQ does not cover, such as the recipe question above.' }));
    return;
  }
  const rows = result.map((i) =>
    h('tr', {},
      h('td', { class: 'num', text: new Date(i.ts).toLocaleTimeString() }),
      h('td', { text: i.kb }),
      h('td', { text: langName(i.language) }),
      h('td', { class: 'n', text: num(i.confidence, 3) }),
      h('td', { text: i.best_guess || 'none' })));
  body.replaceChildren(tableWrap('Open hand-offs, newest first', ['Time', 'Knowledge base', 'Language', 'Confidence', 'Closest entry'], rows, ['', '', '', 'n', '']));
}

// ---------------------------------------------------------------- knowledge base view

const fold = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

async function loadKb(open) {
  const { result } = await call('kb_detail', state.kb);
  state.kbDetail = result;
  renderKb(open ?? parseHash().rest);
}

let kbRefs = null;

function filteredEntries() {
  const q = fold(state.kbFilter.trim());
  return state.kbDetail.entries.filter((e) =>
    !q || fold([e.id, ...e.tags, ...e.questions.en, ...e.questions.sw, e.answer.en, e.answer.sw].join(' ')).includes(q));
}

function updateEntries(open) {
  const d = state.kbDetail;
  const shown = filteredEntries();
  kbRefs.entries.replaceChildren(
    ...(shown.length ? shown.map((e) => entryEl(e, open)) : [h('p', { class: 'empty', text: 'No entry matches that filter. Try a shorter word, or clear the box.' })]));
  kbRefs.count.textContent = `${shown.length} of ${d.entries.length} entries`;
}

function renderKb(open) {
  const d = state.kbDetail;
  if (!d) return;
  const k = kbInfo();
  $('#kb-lead').textContent = `${k.name}: ${d.entries.length} entries and ${d.synonyms.length} synonym groups, read from ${k.file}. Everything Jibu may say to a customer is on this page; nothing else is ever generated.`;
  const root = $('#kb-body');

  const warn = d.warnings;
  const validator = h('section', { 'aria-labelledby': 'validator-h', class: 'validator' },
    h('h2', { id: 'validator-h', text: 'Validator' }),
    h('p', {}, `Checked by the repository\u2019s validator when the page loaded: 0 errors, ${warn.length} ${warn.length === 1 ? 'warning' : 'warnings'}.`,
      warn.length ? ' It warns about questions the retriever cannot tell apart; they are kept as written.' : ''),
    warn.length ? h('details', {}, h('summary', { text: 'Show warnings' }), h('ul', { class: 'warns' }, warn.map((w) => h('li', { class: 'num', text: w })))) : null);

  const count = h('p', { class: 'help', id: 'kb-count', role: 'status' });
  const entries = h('div', { class: 'entries' });
  kbRefs = { entries, count };
  const filter = h('div', { class: 'kb-tools' },
    h('div', { class: 'field' },
      h('label', { for: 'kb-filter', text: 'Filter entries' }),
      h('input', { id: 'kb-filter', type: 'search', value: state.kbFilter, placeholder: 'loan, mkopo, guarantor', autocomplete: 'off',
        oninput: (e) => { state.kbFilter = e.target.value; updateEntries(null); } })),
    count);

  const hand = h('section', { 'aria-labelledby': 'handoff-h' },
    h('h2', { id: 'handoff-h', text: 'Hand-off message' }),
    h('p', { class: 'help', text: 'Sent when confidence is below the threshold. The phone, WhatsApp and hours are filled in from the knowledge base.' }),
    h('p', { lang: 'en', text: d.handoff.en }),
    h('p', { lang: 'sw', text: d.handoff.sw }));

  const syn = h('section', { 'aria-labelledby': 'syn-h' },
    h('h2', { id: 'syn-h', text: 'Synonym groups' }),
    h('p', { class: 'help', text: 'Words in a group count as one idea when scoring. This is where slang such as \u201cdoh\u201d or \u201cmulla\u201d is taught.' }),
    h('ul', { class: 'syns' }, d.synonyms.map((g) => h('li', { text: g.join(', ') }))));

  root.replaceChildren(validator, h('section', { 'aria-labelledby': 'entries-h' }, h('h2', { id: 'entries-h', text: 'Entries' }), filter, entries), hand, syn);
  updateEntries(open);
  if (open) {
    const el = document.getElementById('entry-' + open);
    if (el) {
      el.open = true;
      el.scrollIntoView({ block: 'start' });
      $('summary', el).focus({ preventScroll: true });
      document.title = `${open} - ${VIEWS.kb} - Jibu demo`;
    }
  }
}

function entryEl(e, open) {
  const notYet = e.valid_from && e.valid_from > state.today;
  const state_ = e.active ? null : h('span', { class: 'inactive', text: notYet ? `Not active until ${e.valid_from}` : `Expired ${e.valid_until}` });
  return h('details', { class: 'entry', id: 'entry-' + e.id, open: open === e.id },
    h('summary', {},
      h('span', { class: 'eid num', text: e.id }),
      h('span', { class: 'eq', text: e.questions.en[0] }),
      state_),
    h('div', { class: 'entry-body' },
      h('div', { class: 'cols' },
        h('div', { lang: 'en' }, h('h3', { text: 'English' }),
          h('p', { class: 'answer', text: e.answer.en }),
          h('p', { class: 'help', text: 'Example questions' }),
          h('ul', {}, e.questions.en.map((q) => h('li', { text: q })))),
        h('div', { lang: 'sw' }, h('h3', { text: 'Kiswahili' }),
          h('p', { class: 'answer', text: e.answer.sw }),
          h('p', { class: 'help', text: 'Maswali ya mfano' }),
          h('ul', {}, e.questions.sw.map((q) => h('li', { text: q }))))),
      h('dl', { class: 'facts' },
        h('dt', { text: 'Tags' }), h('dd', { text: e.tags.join(', ') || 'none' }),
        e.follow_ups.length ? [h('dt', { text: 'Suggests next' }), h('dd', {}, e.follow_ups.map((f, i) => [i ? ', ' : '', h('a', { href: `#kb/${encodeURIComponent(f)}` }, f)]))] : null,
        e.valid_from || e.valid_until ? [h('dt', { text: 'Valid' }), h('dd', { class: 'num', text: `${e.valid_from || 'always'} to ${e.valid_until || 'no end'}` })] : null)));
}

// ---------------------------------------------------------------- evaluation view

const METRIC_ROWS = [
  ['n', 'Questions', 'Labelled questions in the split', (m) => `${m.n}`],
  ['scope', 'In scope / out of scope', 'Answerable by an entry / should be handed off', (m) => `${m.n_in_scope} / ${m.n_oos}`],
  ['top1_accuracy', 'Top-1 accuracy', 'Answerable questions answered by the right entry', (m) => pct(m.top1_accuracy)],
  ['wrong_answer_rate', 'Confidently wrong', 'Answerable questions answered by the wrong entry', (m) => pct(m.wrong_answer_rate)],
  ['missed_rate', 'Answerable but handed off', 'Answerable questions sent to staff', (m) => pct(m.missed_rate)],
  ['handoff_precision', 'Hand-off precision', 'Hand-offs that were really out of scope', (m) => pct(m.handoff_precision)],
  ['handoff_recall', 'Hand-off recall', 'Out-of-scope questions that were handed off', (m) => pct(m.handoff_recall)],
  ['oos_answered', 'Out-of-scope answered', 'Questions the FAQ does not cover that got an answer', (m) => `${m.oos_answered}`],
];

async function runEval() {
  const status = $('#eval-status');
  const t = state.threshold[state.kb];
  $('#run-eval').disabled = true;
  status.textContent = 'Running...';
  try {
    const { result, ms } = await call('run_eval', state.kb, t);
    state.evalRun = { ...result, ms, kb: state.kb };
    status.textContent = `Done in ${ms} ms in your browser.`;
  } catch (e) {
    status.textContent = `The engine reported an error: ${e.message}`;
  } finally {
    $('#run-eval').disabled = false;
  }
  renderEval();
}

function renderEval() {
  const body = $('#eval-body');
  const k = kbInfo();
  const run = state.evalRun && state.evalRun.kb === state.kb ? state.evalRun : null;
  if (!k.eval) {
    body.replaceChildren(h('p', { class: 'empty', text: 'This knowledge base has no labelled question set.' }));
    return;
  }
  if (!run) {
    $('#eval-status').textContent = '';
    body.replaceChildren(h('p', { class: 'empty' }, `${k.name} has ${k.eval.cases} labelled questions, fixed to the date ${k.eval.as_of} so results repeat. Press Run evaluation to answer them all at threshold ${num(state.threshold[state.kb], 2)}.`));
    return;
  }
  const stale = run.threshold !== state.threshold[state.kb];
  const out = [];
  out.push(h('p', { class: 'run-line' }, `${k.name}: ${run.splits.all.n} questions, as of ${run.as_of}, threshold ${num(run.threshold, 2)}.`,
    stale ? ` The threshold control now says ${num(state.threshold[state.kb], 2)}; press Run to use it.` : ''));

  const head = ['Measure', 'Development', 'Held-out test', 'All'];
  const rows = METRIC_ROWS.map(([, label, desc, f]) =>
    h('tr', {},
      h('th', { scope: 'row' }, h('span', { text: label }), h('span', { class: 'sub', text: desc })),
      h('td', { class: 'n', text: f(run.splits.dev) }),
      h('td', { class: 'n', text: f(run.splits.test) }),
      h('td', { class: 'n strong', text: f(run.splits.all) })));
  out.push(h('h2', { text: 'Results' }));
  out.push(tableWrap('Evaluation results by split', head, rows, ['', 'n', 'n', 'n']));
  out.push(h('p', { class: 'help', text: 'The threshold was tuned on the development split. The held-out test split is the fairer guide to unseen questions.' }));

  out.push(h('h2', { text: 'By kind of question' }));
  const kindRows = Object.values(run.by_kind).filter((x) => x.n).map((x) =>
    h('tr', {}, h('th', { scope: 'row', text: x.label }), h('td', { class: 'n', text: `${x.correct} of ${x.n}` }), h('td', { class: 'n', text: pct(x.correct / x.n) })));
  out.push(tableWrap('Correct outcomes by kind of question', ['Kind', 'Correct', 'Share'], kindRows, ['', 'n', 'n']));

  out.push(h('h2', { text: 'When Jibu answers, how often is it right?' }));
  const rel = run.reliability.filter((b) => b.n);
  out.push(tableWrap('Accuracy of answered replies by confidence band',
    ['Confidence', 'Answered', 'Correct', 'Accuracy'],
    rel.map((b) => h('tr', {}, h('th', { scope: 'row', class: 'num', text: `${num(b.lo, 1)} to ${num(b.hi, 1)}` }), h('td', { class: 'n', text: b.n }), h('td', { class: 'n', text: b.correct }), h('td', { class: 'n', text: pct(b.correct / b.n) }))),
    ['', 'n', 'n', 'n']));

  out.push(h('h2', { text: 'Every question' }));
  out.push(questionTable(run));
  body.replaceChildren(...out);
}

function questionTable(run) {
  const f = state.evalFilter;
  const kinds = [...new Set(run.rows.map((r) => r.kind))];
  const label = Object.fromEntries(Object.entries(run.by_kind).map(([k, v]) => [k, v.label]));
  const keep = (r) =>
    (f.kind === 'all' || r.kind === f.kind) &&
    (f.show === 'all' || (f.show === 'wrong' && !r.correct) || (f.show === 'handoff' && r.status === 'handoff'));
  const rows = run.rows.filter(keep);
  const wrap = h('div', {});
  const controls = h('div', { class: 'row-tools' },
    h('div', { class: 'field' }, h('label', { for: 'ev-show', text: 'Show' }),
      h('select', { id: 'ev-show', onchange: (e) => { f.show = e.target.value; renderEval(); $('#ev-show').focus(); } },
        ...[['wrong', 'Wrong outcomes only'], ['handoff', 'Hand-offs only'], ['all', 'All questions']].map(([v, t]) => h('option', { value: v, selected: f.show === v, text: t })))),
    h('div', { class: 'field' }, h('label', { for: 'ev-kind', text: 'Kind' }),
      h('select', { id: 'ev-kind', onchange: (e) => { f.kind = e.target.value; renderEval(); $('#ev-kind').focus(); } },
        h('option', { value: 'all', text: 'All kinds' }), ...kinds.map((k) => h('option', { value: k, selected: f.kind === k, text: label[k] })))),
    h('p', { class: 'help', role: 'status', text: `${rows.length} of ${run.rows.length} questions` }));
  const trs = rows.map((r) =>
    h('tr', {},
      h('td', { class: 'n', text: r.n }),
      h('td', { text: r.split === 'dev' ? 'dev' : 'test' }),
      h('td', { text: label[r.kind] }),
      h('th', { scope: 'row' }, h('span', { text: r.question }), r.after ? h('span', { class: 'sub', text: `after: ${r.after}` }) : null),
      h('td', { text: r.expected === '@smalltalk' ? 'greeting' : r.expected || 'hand off' }),
      h('td', { text: r.got === '<handoff>' ? 'hand off' : r.got === '<smalltalk>' ? 'greeting' : r.got }),
      h('td', { class: 'n', text: num(r.confidence, 2) }),
      h('td', { class: r.correct ? 'ok' : 'bad', text: r.correct ? 'Correct' : 'Wrong' })));
  wrap.append(controls, rows.length
    ? tableWrap('Every labelled question and what Jibu did', ['#', 'Split', 'Kind', 'Question', 'Expected', 'Got', 'Conf.', 'Result'], trs, ['n', '', '', '', '', '', 'n', ''])
    : h('p', { class: 'empty', text: 'Nothing matches those filters.' }));
  return wrap;
}

async function runSweep() {
  const status = $('#sweep-status');
  const btn = $('#run-sweep');
  btn.disabled = true;
  status.textContent = 'Running the sweep. This builds the engine 13 times and takes a few seconds...';
  try {
    const { result, ms } = await call('run_sweep', state.kb, $('#sweep-split').value);
    state.sweepRun = { ...result, ms };
    status.textContent = `Done in ${(ms / 1000).toFixed(1)} s in your browser.`;
    renderSweep();
  } catch (e) {
    status.textContent = `The engine reported an error: ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

function renderSweep() {
  const s = state.sweepRun;
  const body = $('#sweep-body');
  if (!s || s.kb !== state.kb) {
    body.replaceChildren();
    return;
  }
  const cur = state.threshold[state.kb];
  const rows = s.rows.map((r) =>
    h('tr', { 'aria-current': Math.abs(r.threshold - cur) < 1e-9 ? 'true' : null },
      h('th', { scope: 'row', class: 'num' }, num(r.threshold, 2),
        r.threshold === s.recommended ? h('span', { class: 'sub', text: 'lowest with no out-of-scope answered' }) : null,
        Math.abs(r.threshold - cur) < 1e-9 ? h('span', { class: 'sub', text: 'current setting' }) : null),
      h('td', { class: 'n', text: pct(r.top1) }),
      h('td', { class: 'n', text: pct(r.wrong) }),
      h('td', { class: 'n', text: pct(r.missed) }),
      h('td', { class: 'n', text: pct(r.precision) }),
      h('td', { class: 'n', text: pct(r.recall) }),
      h('td', { class: 'n', text: r.oos_answered })));
  body.replaceChildren(
    tableWrap(`Metrics by threshold on the ${s.split} questions`,
      ['Threshold', 'Top-1 accuracy', 'Confidently wrong', 'Answerable but handed off', 'Hand-off precision', 'Hand-off recall', 'Out-of-scope answered'],
      rows, ['', 'n', 'n', 'n', 'n', 'n', 'n']));
}

// ---------------------------------------------------------------- how it works

function renderHow() {
  const root = $('#how-runtime');
  const i = state.info;
  const m = state.manifest;
  const short = m.commit && m.commit !== 'unknown' ? m.commit.slice(0, 7) : null;
  const total = m.files.reduce((n, f) => n + f.bytes, 0);
  const mb = (b) => (b / 1048576).toFixed(1);
  const facts = h('dl', { class: 'facts' },
    h('dt', { text: 'Python' }), h('dd', { text: `${i.python}, in Pyodide ${i.pyodide}` }),
    h('dt', { text: 'Libraries' }), h('dd', { text: `pydantic ${i.pydantic}, PyYAML ${i.yaml}` }),
    h('dt', { text: 'Build' }), h('dd', {}, short ? h('a', { href: `${REPO}/tree/${m.commit}` }, `commit ${short}`) : 'local build'),
    h('dt', { text: 'Download' }), h('dd', { text: `${m.files.length} files, ${mb(total)} MB, on first visit` }),
    h('dt', { text: 'Started in' }), h('dd', { text: `${(i.bootMs / 1000).toFixed(1)} s on this device` }));
  const roleLabel = { python: 'Python (engine)', kb: 'Knowledge base', eval: 'Evaluation set', runtime: 'Runtime', page: 'Page' };
  const source = (f) => {
    if (!short) return f.path;
    const repoPath = f.path.startsWith('engine/jibu/') ? 'src/jibu/' + f.path.slice(12)
      : f.path.startsWith('engine/kb/') ? 'kb/' + f.path.slice(10)
      : f.path.startsWith('engine/eval/') ? 'eval/' + f.path.slice(12)
      : f.path === 'engine/jibu_demo.py' ? 'demo/py/jibu_demo.py' : null;
    return repoPath ? h('a', { href: `${REPO}/blob/${m.commit}/${repoPath}` }, f.path) : f.path;
  };
  const rows = m.files.filter((f) => f.role !== 'page').map((f) =>
    h('tr', {}, h('th', { scope: 'row', class: 'num' }, source(f)), h('td', { text: roleLabel[f.role] }), h('td', { class: 'n', text: f.bytes.toLocaleString('en') }), h('td', { class: 'num', text: f.sha256.slice(0, 12) })));
  root.replaceChildren(facts,
    h('p', { class: 'help', text: 'Engine, knowledge base and evaluation files are copied from the repository when the page is built, so they cannot drift from the code. Each hash is the start of the file’s SHA-256.' }),
    tableWrap('Files the engine loads', ['File', 'Kind', 'Bytes', 'SHA-256'], rows, ['', '', 'n', '']));
}

// ---------------------------------------------------------------- start

function init() {
  bindContext();
  $('#composer').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('#q');
    const text = input.value;
    if (text.trim()) input.value = '';
    sendQuestion(text);
    input.focus();
  });
  $('#q').addEventListener('input', () => {
    $('#q-error').hidden = true;
    $('#q').removeAttribute('aria-invalid');
  });
  $('#new-conv').addEventListener('click', () => newConversation());
  $('#run-eval').addEventListener('click', runEval);
  $('#run-sweep').addEventListener('click', runSweep);
  $('#sweep-split').addEventListener('change', () => { state.sweepRun = null; renderSweep(); $('#sweep-status').textContent = ''; });
  window.addEventListener('hashchange', () => renderView(true));
  renderView();
  startWorker();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
  }
}

document.addEventListener('DOMContentLoaded', init);
