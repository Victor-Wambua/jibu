(() => {
  'use strict';
  const SITES = {
    'umoja-sacco': {
      name: 'Umoja Sacco',
      title: 'Save together. Borrow with confidence.',
      lead: 'Membership, savings and loans for people who build things together. Questions about joining, rates or opening hours? Ask Jibu in the chat corner, in English or Kiswahili.',
      cards: [['Membership', 'Individuals, youth and registered groups can join.'], ['Savings', 'Long-term deposits, flexible savings and fixed deposits.'], ['Loans', 'Development, emergency, school fees and business loans.']],
      examples: ['Mnafungua saa ngapi?', 'How do I apply for a loan?', 'Nataka kujiunga, nifanye nini?', 'How much is the membership fee?', 'and for students?', 'Can I get a mortgage?', 'What is the weather in Nairobi?'],
    },
    'afya-clinic': {
      name: 'Afya Bora Clinic',
      title: 'Care close to home.',
      lead: 'Outpatient consultations, lab tests, vaccinations and a pharmacy under one roof. Ask Jibu about hours, fees or appointments. It will not give medical advice.',
      cards: [['Consultations', 'General and specialist doctors, by appointment or walk-in.'], ['Lab and pharmacy', 'Tests, results and prescriptions in one place.'], ['Child vaccination', 'Weekday immunisation clinics for children.']],
      examples: ['Do you accept SHA?', 'Naweza kuweka miadi vipi?', 'How much is a consultation?', 'Is the child vaccination free?', 'I have a headache, what should I take?'],
    },
  };

  const $ = (id) => document.getElementById(id);
  const result = $('result');
  let current = 'umoja-sacco';

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function show(detail) {
    const r = detail.response;
    const pct = Math.round(r.confidence * 100);
    const threshold = window.__jibuThreshold || 0.5;
    result.replaceChildren();
    const label = { answered: 'Answered', handoff: 'Handed off to staff', smalltalk: 'Greeting' }[r.status];
    result.append(el('span', 'chip ' + r.status, label));
    if (r.status !== 'smalltalk') {
      const meter = el('div', 'meter' + (r.confidence < threshold ? ' low' : ''));
      meter.setAttribute('role', 'img');
      meter.setAttribute('aria-label', `Confidence ${pct} percent, threshold ${Math.round(threshold * 100)} percent`);
      const fill = el('div', 'fill');
      fill.style.width = Math.max(2, pct) + '%';
      const tick = el('div', 'tick');
      tick.style.left = threshold * 100 + '%';
      meter.append(fill, tick);
      const small = el('div', 'small');
      small.append(el('span', '', 'confidence ' + pct + '%'), el('span', '', 'threshold ' + Math.round(threshold * 100) + '%'));
      result.append(meter, small);
    }
    const dl = el('dl');
    const row = (k, v) => { dl.append(el('dt', '', k), el('dd', '', v)); };
    row('matched entry', r.entry_id || 'none (handoff)');
    row('detected language', r.detected_language + ' (replied in ' + r.language + ')');
    row('used previous topic', r.used_context ? 'yes' : 'no');
    row('queued for staff', r.unanswered_id ? 'yes (' + r.unanswered_id + ')' : 'no');
    result.append(dl);
  }

  async function loadThreshold() {
    try {
      const res = await fetch('/meta?kb=' + encodeURIComponent(current));
      if (res.ok) window.__jibuThreshold = (await res.json()).threshold;
    } catch (_) { /* keep default */ }
  }

  function renderSite() {
    const s = SITES[current];
    $('siteName').textContent = s.name;
    $('heroTitle').textContent = s.title;
    $('heroLead').textContent = s.lead;
    s.cards.forEach(([t, p], i) => { $('c' + (i + 1) + 't').textContent = t; $('c' + (i + 1) + 'p').textContent = p; });
    document.title = s.name + ' (sample) with Jibu';
    const ex = $('examples');
    ex.replaceChildren();
    s.examples.forEach((q) => {
      const b = el('button', '', q);
      b.type = 'button';
      b.addEventListener('click', () => window.Jibu.ask(q));
      ex.append(b);
    });
    result.replaceChildren(el('p', 'empty', 'Send a message and the matching details appear here: whether it was answered or handed off, how confident the match was against the threshold, and which approved entry it came from.'));
    window.Jibu.init({ kb: current });
    loadThreshold();
  }

  document.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => {
    current = b.dataset.kb;
    document.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    renderSite();
  }));
  $('openChat').addEventListener('click', () => window.Jibu.open());
  window.addEventListener('jibu:response', (e) => show(e.detail));
  renderSite();
})();
