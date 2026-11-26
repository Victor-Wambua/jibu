/*!
 * Jibu chat widget - one file, no dependencies, Shadow DOM.
 *
 * Embed:
 *   <script src="https://your-jibu-host/widget.js" data-kb="umoja-sacco" defer></script>
 *
 * Optional data attributes: data-api, data-kb, data-lang (en|sw), data-theme (light|dark),
 * data-position (right|left), data-primary, data-accent (hex colours), data-open (true).
 * JS API: Jibu.open(), Jibu.close(), Jibu.ask(text), Jibu.init(options), Jibu.destroy().
 * Every reply is also dispatched as a "jibu:response" CustomEvent on window.
 */
(() => {
  'use strict';
  if (window.Jibu && window.Jibu.loaded) return;

  const script = document.currentScript;

  const STRINGS = {
    en: {
      open: 'Open chat',
      close: 'Close chat',
      title: 'Ask Jibu',
      subtitle: 'Answers from approved information',
      placeholder: 'Type your question',
      send: 'Send',
      label: 'Your question',
      searching: 'Looking for an answer',
      suggested: 'Suggested questions',
      helpful: 'Helpful',
      notHelpful: 'Not helpful',
      thanks: 'Thanks for the feedback',
      source: 'Approved answer',
      handoff: 'Passed to our team',
      call: 'Call',
      whatsapp: 'WhatsApp',
      error: 'Something went wrong. Please try again.',
      retry: 'Try again',
      busy: 'Too many messages. Please wait',
      seconds: 'seconds.',
      foot: 'Jibu answers only from this organisation’s approved FAQ and hands over to staff when unsure.',
      you: 'You',
      bot: 'Jibu',
      langName: 'SW',
    },
    sw: {
      open: 'Fungua gumzo',
      close: 'Funga gumzo',
      title: 'Uliza Jibu',
      subtitle: 'Majibu ya taarifa rasmi',
      placeholder: 'Andika swali lako',
      send: 'Tuma',
      label: 'Swali lako',
      searching: 'Natafuta jibu',
      suggested: 'Maswali yanayopendekezwa',
      helpful: 'Imesaidia',
      notHelpful: 'Haijasaidia',
      thanks: 'Asante kwa maoni yako',
      source: 'Jibu rasmi',
      handoff: 'Imepelekwa kwa timu yetu',
      call: 'Piga simu',
      whatsapp: 'WhatsApp',
      error: 'Kuna hitilafu. Tafadhali jaribu tena.',
      retry: 'Jaribu tena',
      busy: 'Ujumbe mwingi sana. Tafadhali subiri',
      seconds: 'sekunde.',
      foot: 'Jibu hujibu kutoka kwenye maswali na majibu rasmi ya shirika hili pekee, na humpa mfanyakazi pale asipokuwa na uhakika.',
      you: 'Wewe',
      bot: 'Jibu',
      langName: 'EN',
    },
  };

  const CSS = `
:host { all: initial; }
*, *::before, *::after { box-sizing: border-box; }
.root {
  --primary: #14213d; --on-primary: #ffffff; --accent: #fca311; --on-accent: #14213d;
  --bg: #ffffff; --surface: #f5f2ea; --bot: #f1eee6; --ink: #14213d; --muted: #566074;
  --line: #e2ddd0; --ring: #14213d; --danger: #9b2c2c; --shadow: 0 12px 40px rgba(20,33,61,.22);
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 24px;
  --radius: 20px; --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-family: var(--font); color: var(--ink); font-size: 15px; line-height: 1.45;
  position: fixed; bottom: var(--space-4); z-index: 2147483000;
  right: var(--space-4);
}
.root.left { right: auto; left: var(--space-4); }
.root[data-theme="dark"] { color-scheme: dark; }
@media (prefers-color-scheme: dark) {
  .root:not([data-theme="light"]) { color-scheme: dark; }
}
.root[data-theme="dark"], .root[data-theme="auto"].dark {
  --primary: #fca311; --on-primary: #14213d; --accent: #fca311; --on-accent: #14213d;
  --bg: #121a2e; --surface: #182139; --bot: #1f2a45; --ink: #f3f1ea; --muted: #a8b0c2;
  --line: #2c3858; --ring: #fca311; --danger: #ff9b9b; --shadow: 0 12px 40px rgba(0,0,0,.55);
}
button { font: inherit; color: inherit; cursor: pointer; }
:focus-visible { outline: 3px solid var(--ring); outline-offset: 2px; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.launcher {
  width: 60px; height: 60px; border-radius: 50%; border: 0; display: grid; place-items: center;
  background: var(--primary); color: var(--accent); box-shadow: var(--shadow);
  transition: transform .18s ease, box-shadow .18s ease;
}
.root[data-theme="dark"] .launcher, .root.dark .launcher { color: var(--on-primary); }
.launcher:hover { transform: translateY(-2px) scale(1.03); }
.launcher svg { width: 30px; height: 30px; }
.root.is-open .launcher { display: none; }

.panel {
  width: min(400px, calc(100vw - 32px)); height: min(640px, calc(100dvh - 32px));
  background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius);
  box-shadow: var(--shadow); display: flex; flex-direction: column; overflow: hidden;
  animation: pop .2s ease-out;
}
.panel[hidden] { display: none; }
@keyframes pop { from { opacity: 0; transform: translateY(10px) scale(.98); } to { opacity: 1; transform: none; } }

header {
  display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
  background: var(--primary); color: var(--on-primary);
}
.mark { width: 36px; height: 36px; flex: none; color: var(--accent); }
.root[data-theme="dark"] .mark, .root.dark .mark { color: var(--on-primary); }
.mark path:nth-child(2), .launcher svg path:nth-child(2) { stroke: var(--primary); }
.titles { flex: 1; min-width: 0; }
.titles h2 { margin: 0; font-size: 16px; font-weight: 650; letter-spacing: .01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.titles p { margin: 0; font-size: 12.5px; opacity: .85; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hbtn {
  min-width: 44px; min-height: 44px; border-radius: 12px; border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
  background: transparent; color: inherit; display: grid; place-items: center; font-size: 13px; font-weight: 600; padding: 0 var(--space-2);
}
.hbtn:hover { background: color-mix(in srgb, currentColor 14%, transparent); }
.hbtn.icon { border-color: transparent; }
.hbtn svg { width: 20px; height: 20px; }
header :focus-visible { outline-color: var(--on-primary); }

.log {
  flex: 1; overflow-y: auto; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3);
  background: var(--surface); overscroll-behavior: contain; scroll-behavior: smooth;
}
.msg { max-width: 88%; display: flex; flex-direction: column; gap: var(--space-1); }
.msg.user { align-self: flex-end; align-items: flex-end; }
.bubble { padding: 10px 14px; border-radius: 18px; white-space: pre-wrap; overflow-wrap: anywhere; }
.bot .bubble { background: var(--bot); border: 1px solid var(--line); border-bottom-left-radius: 6px; }
.user .bubble { background: var(--primary); color: var(--on-primary); border-bottom-right-radius: 6px; }
.bot.handoff .bubble { border-left: 4px solid var(--accent); }
.meta { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; padding: 0 var(--space-1); }
.meta .tag { display: inline-flex; align-items: center; gap: 4px; }
.meta svg { width: 13px; height: 13px; }
.fb { margin-left: auto; display: inline-flex; gap: 2px; }
.fb button { min-width: 36px; min-height: 36px; border-radius: 10px; border: 0; background: transparent; color: var(--muted); display: grid; place-items: center; }
.fb button:hover { background: var(--line); color: var(--ink); }
.fb svg { width: 16px; height: 16px; }
.actions { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-1); }
.actions a, .actions button {
  min-height: 44px; display: inline-flex; align-items: center; gap: 6px; padding: 0 14px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--bg); color: var(--ink); text-decoration: none; font-weight: 600; font-size: 14px;
}
.actions a.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.actions a:hover, .actions button:hover { filter: brightness(.96); }
.err { color: var(--danger); }

.typing { display: inline-flex; gap: 5px; padding: 14px 16px; }
.typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite ease-in-out; }
.typing i:nth-child(2) { animation-delay: .15s; } .typing i:nth-child(3) { animation-delay: .3s; }
@keyframes blink { 0%, 80%, 100% { opacity: .25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-3px); } }

.chips { display: flex; gap: var(--space-2); padding: var(--space-2) var(--space-4) var(--space-3); flex-wrap: wrap; background: var(--surface); border-top: 1px solid var(--line); }
.chips:empty { display: none; }
.chip {
  min-height: 44px; padding: 8px 14px; border-radius: 999px; border: 1px solid var(--line); background: var(--bg);
  color: var(--ink); text-align: left; font-size: 14px; line-height: 1.25; max-width: 100%;
}
.chip:hover { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }

form { display: flex; gap: var(--space-2); padding: var(--space-3) var(--space-3) var(--space-2); background: var(--bg); border-top: 1px solid var(--line); }
input[type="text"] {
  flex: 1; min-width: 0; min-height: 48px; border-radius: 14px; border: 1.5px solid var(--line); background: var(--surface);
  color: var(--ink); padding: 0 var(--space-4); font: inherit; font-size: 16px;
}
input[type="text"]::placeholder { color: var(--muted); opacity: 1; }
input[type="text"]:focus-visible { outline-offset: 0; border-color: var(--ring); }
.send {
  width: 48px; min-height: 48px; border-radius: 14px; border: 0; background: var(--accent); color: var(--on-accent);
  display: grid; place-items: center;
}
.send:disabled { opacity: .5; cursor: not-allowed; }
.send svg { width: 22px; height: 22px; }
.foot { margin: 0; padding: 0 var(--space-4) calc(var(--space-3) + env(safe-area-inset-bottom, 0px)); font-size: 11.5px; color: var(--muted); background: var(--bg); line-height: 1.35; }

@media (max-width: 480px) {
  .root { right: 0; left: 0; bottom: 0; }
  .root:not(.is-open) { left: auto; right: var(--space-4); bottom: var(--space-4); }
  .root.left:not(.is-open) { left: var(--space-4); right: auto; }
  .panel { width: 100vw; height: 100dvh; border-radius: 0; border: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .panel { animation: none; } .launcher { transition: none; } .log { scroll-behavior: auto; }
  .typing i { animation: none; opacity: .6; }
}
`;

  const ICON = {
    mark: '<svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M6 4h20a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4H16l-6.5 5.2c-.6.5-1.5 0-1.5-.8V24H6a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4z" fill="currentColor"/><path d="M9.5 14.2l4.3 4.2 8.7-8.6" stroke="#14213d" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6"/></svg>',
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 11v9H4v-9h3zM7 11l4-8c1.5 0 2.5 1 2.2 2.6L12.7 9H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 13V4h3v9h-3zM17 13l-4 8c-1.5 0-2.5-1-2.2-2.6l.5-3.4H5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.2 4H17"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="18" height="18"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/></svg>',
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="18" height="18"><path d="M4 5h16v11H9l-5 4V5z"/></svg>',
  };

  const svg = (html) => {
    const t = document.createElement('template');
    t.innerHTML = html;
    return t.content.firstElementChild;
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  /** Server text is only ever added as text nodes. *bold* and newlines are built as elements. */
  function renderText(container, text) {
    String(text).split('\n').forEach((line, i) => {
      if (i) container.append(document.createElement('br'));
      line.split(/(\*[^*\n]+\*)/g).forEach((part) => {
        if (/^\*[^*\n]+\*$/.test(part)) {
          const b = document.createElement('strong');
          b.textContent = part.slice(1, -1);
          container.append(b);
        } else if (part) container.append(document.createTextNode(part));
      });
    });
  }

  const PHONE = /^\+?[0-9 ()-]{7,20}$/;
  const digits = (s) => String(s).replace(/\D/g, '');

  function randomId() {
    const a = new Uint8Array(12);
    crypto.getRandomValues(a);
    return btoa(String.fromCharCode(...a)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function safeStore(kind, key, value) {
    try {
      const s = window[kind];
      if (value === undefined) return s.getItem(key);
      s.setItem(key, value);
    } catch (_) { /* storage may be blocked */ }
    return null;
  }

  let instance = null;

  function init(options = {}) {
    if (instance) instance.destroy();
    const data = script ? script.dataset : {};
    const cfg = {
      api: options.api || data.api || (script && script.src ? new URL(script.src).origin : location.origin),
      kb: options.kb || data.kb || '',
      lang: options.lang || data.lang || ((navigator.language || '').toLowerCase().startsWith('sw') ? 'sw' : 'en'),
      theme: options.theme || data.theme || 'auto',
      position: options.position || data.position || 'right',
      primary: options.primary || data.primary || '',
      accent: options.accent || data.accent || '',
      open: String(options.open ?? data.open ?? 'false') === 'true',
    };
    cfg.api = cfg.api.replace(/\/+$/, '');

    const host = document.createElement('div');
    host.id = 'jibu-widget';
    const shadow = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = CSS;
    shadow.append(style);

    const root = el('div', 'root' + (cfg.position === 'left' ? ' left' : ''));
    root.dataset.theme = cfg.theme;
    if (/^#[0-9a-f]{6}$/i.test(cfg.primary)) root.style.setProperty('--primary', cfg.primary);
    if (/^#[0-9a-f]{6}$/i.test(cfg.accent)) root.style.setProperty('--accent', cfg.accent);
    const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const applyTheme = () => root.classList.toggle('dark', cfg.theme === 'auto' && darkQuery.matches);
    applyTheme();
    darkQuery.addEventListener?.('change', applyTheme);

    let lang = cfg.lang === 'sw' ? 'sw' : 'en';
    let langExplicit = Boolean(options.lang || data.lang);
    let meta = null;
    let busy = false;
    let welcomed = false;
    let sessionId = safeStore('sessionStorage', 'jibu:session:' + cfg.kb) || randomId();
    safeStore('sessionStorage', 'jibu:session:' + cfg.kb, sessionId);
    const t = (k) => STRINGS[lang][k];

    // ---- skeleton
    const launcher = el('button', 'launcher');
    launcher.type = 'button';
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-controls', 'jibu-panel');
    launcher.append(svg(ICON.mark));

    const panel = el('section', 'panel');
    panel.id = 'jibu-panel';
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');

    const header = el('header');
    const mark = svg(ICON.mark);
    mark.classList.add('mark');
    const titles = el('div', 'titles');
    const h2 = el('h2');
    const sub = el('p');
    titles.append(h2, sub);
    const langBtn = el('button', 'hbtn');
    langBtn.type = 'button';
    const closeBtn = el('button', 'hbtn icon');
    closeBtn.type = 'button';
    closeBtn.append(svg(ICON.close));
    header.append(mark, titles, langBtn, closeBtn);

    const log = el('div', 'log');
    log.setAttribute('role', 'log');
    log.setAttribute('aria-live', 'polite');
    log.tabIndex = 0;
    const status = el('div', 'sr');
    status.setAttribute('role', 'status');
    const chips = el('div', 'chips');
    chips.setAttribute('role', 'group');

    const form = el('form');
    form.noValidate = true;
    const label = el('label', 'sr');
    label.htmlFor = 'jibu-input';
    const input = el('input');
    input.type = 'text';
    input.id = 'jibu-input';
    input.maxLength = 500;
    input.autocomplete = 'off';
    input.enterKeyHint = 'send';
    const sendBtn = el('button', 'send');
    sendBtn.type = 'submit';
    sendBtn.append(svg(ICON.send));
    form.append(label, input, sendBtn);
    const foot = el('p', 'foot');

    panel.append(header, log, status, chips, form, foot);
    root.append(launcher, panel);
    shadow.append(root);
    document.body.append(host);

    function applyStrings() {
      h2.textContent = (meta && meta.name) || t('title');
      sub.textContent = t('subtitle');
      panel.setAttribute('aria-label', (meta && meta.name) || t('title'));
      launcher.setAttribute('aria-label', t('open'));
      closeBtn.setAttribute('aria-label', t('close'));
      langBtn.textContent = t('langName');
      langBtn.setAttribute('lang', lang === 'sw' ? 'en' : 'sw');
      langBtn.setAttribute('aria-label', (lang === 'sw' ? 'Switch to English' : 'Badili kwenda Kiswahili'));
      label.textContent = t('label');
      input.placeholder = t('placeholder');
      sendBtn.setAttribute('aria-label', t('send'));
      chips.setAttribute('aria-label', t('suggested'));
      foot.textContent = t('foot');
    }

    function scroll() {
      log.scrollTop = log.scrollHeight;
    }

    function addUser(text) {
      const m = el('div', 'msg user');
      m.append(el('div', 'bubble', text));
      log.append(m);
      scroll();
    }

    function addBot(text, kind) {
      const m = el('div', 'msg bot' + (kind === 'handoff' ? ' handoff' : ''));
      const b = el('div', 'bubble');
      renderText(b, text);
      m.append(b);
      log.append(m);
      scroll();
      return m;
    }

    function setChips(items) {
      chips.replaceChildren();
      (items || []).slice(0, 4).forEach((s) => {
        const c = el('button', 'chip', s.question);
        c.type = 'button';
        c.addEventListener('click', () => ask(s.question));
        chips.append(c);
      });
    }

    function contactActions(contact) {
      const wrap = el('div', 'actions');
      if (contact && contact.phone && PHONE.test(contact.phone)) {
        const a = el('a', 'primary');
        a.href = 'tel:' + (contact.phone.trim().startsWith('+') ? '+' : '') + digits(contact.phone);
        a.append(svg(ICON.phone), document.createTextNode(t('call') + ' ' + contact.phone));
        wrap.append(a);
      }
      if (contact && contact.whatsapp && PHONE.test(contact.whatsapp)) {
        const a = el('a');
        a.href = 'https://wa.me/' + digits(contact.whatsapp);
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.append(svg(ICON.chat), document.createTextNode(t('whatsapp')));
        wrap.append(a);
      }
      return wrap;
    }

    function feedbackControls(replyId) {
      const fb = el('span', 'fb');
      const mk = (helpful, icon, key) => {
        const b = el('button');
        b.type = 'button';
        b.setAttribute('aria-label', t(key));
        b.title = t(key);
        b.append(svg(icon));
        b.addEventListener('click', async () => {
          fb.replaceChildren(el('span', '', t('thanks')));
          try {
            await fetch(cfg.api + '/feedback', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ reply_id: replyId, helpful }),
            });
          } catch (_) { /* feedback is best-effort */ }
        });
        return b;
      };
      fb.append(mk(true, ICON.up, 'helpful'), mk(false, ICON.down, 'notHelpful'));
      return fb;
    }

    function showTyping() {
      const m = el('div', 'msg bot');
      const b = el('div', 'bubble typing');
      b.append(el('i'), el('i'), el('i'));
      m.append(b);
      log.append(m);
      status.textContent = t('searching');
      scroll();
      return m;
    }

    function addError(message, retryText) {
      const m = el('div', 'msg bot');
      const b = el('div', 'bubble err', message);
      m.append(b);
      if (retryText) {
        const actions = el('div', 'actions');
        const r = el('button', '', t('retry'));
        r.type = 'button';
        r.addEventListener('click', () => { m.remove(); ask(retryText, true); });
        actions.append(r);
        m.append(actions);
      }
      log.append(m);
      scroll();
    }

    async function ask(text, isRetry) {
      text = String(text).trim();
      if (!text || busy) return;
      busy = true;
      sendBtn.disabled = true;
      if (!isRetry) addUser(text);
      setChips([]);
      const typing = showTyping();
      try {
        const body = { message: text.slice(0, 500), session_id: sessionId };
        if (cfg.kb) body.kb = cfg.kb;
        if (langExplicit) body.lang = lang;
        const res = await fetch(cfg.api + '/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        typing.remove();
        status.textContent = '';
        if (res.status === 429) {
          const wait = res.headers.get('Retry-After') || '30';
          addError(t('busy') + ' ' + wait + ' ' + t('seconds'));
          return;
        }
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (!langExplicit && (data.language === 'en' || data.language === 'sw')) {
          lang = data.language;
          applyStrings();
        }
        const handoff = data.status === 'handoff';
        const m = addBot(data.answer, handoff ? 'handoff' : 'answer');
        const metaRow = el('div', 'meta');
        const tag = el('span', 'tag');
        tag.append(svg(ICON.check), document.createTextNode(handoff ? t('handoff') : t('source')));
        metaRow.append(tag);
        if (data.status === 'answered') metaRow.append(feedbackControls(data.reply_id));
        m.append(metaRow);
        if (handoff) m.append(contactActions(data.handoff));
        setChips(data.suggestions);
        window.dispatchEvent(new CustomEvent('jibu:response', { detail: { request: text, response: data } }));
      } catch (_) {
        typing.remove();
        status.textContent = '';
        addError(t('error'), text);
      } finally {
        busy = false;
        sendBtn.disabled = false;
        scroll();
      }
    }

    async function loadMeta() {
      try {
        const q = cfg.kb ? '?kb=' + encodeURIComponent(cfg.kb) : '';
        const res = await fetch(cfg.api + '/meta' + q);
        if (res.ok) meta = await res.json();
      } catch (_) { /* header falls back to the generic title */ }
      applyStrings();
      if (panel.hidden === false) welcome();
    }

    function welcome() {
      if (welcomed) return;
      welcomed = true;
      addBot((meta && meta.welcome && meta.welcome[lang]) || t('subtitle'));
      setChips(meta && meta.starters ? meta.starters[lang] : []);
    }

    function open() {
      panel.hidden = false;
      root.classList.add('is-open');
      launcher.setAttribute('aria-expanded', 'true');
      welcome();
      input.focus();
    }
    function close() {
      panel.hidden = true;
      root.classList.remove('is-open');
      launcher.setAttribute('aria-expanded', 'false');
      launcher.focus();
    }

    launcher.addEventListener('click', open);
    closeBtn.addEventListener('click', close);
    panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
    langBtn.addEventListener('click', () => {
      lang = lang === 'sw' ? 'en' : 'sw';
      langExplicit = true;
      applyStrings();
      if (log.children.length <= 1) {
        log.replaceChildren();
        welcomed = false;
        welcome();
      } else if (meta && meta.starters) setChips(meta.starters[lang]);
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = input.value;
      input.value = '';
      ask(v);
      input.focus();
    });

    applyStrings();
    loadMeta();
    if (cfg.open) open();

    instance = {
      open,
      close,
      ask: (text) => { open(); return ask(text); },
      destroy() {
        darkQuery.removeEventListener?.('change', applyTheme);
        host.remove();
        instance = null;
      },
    };
    return instance;
  }

  window.Jibu = {
    loaded: true,
    init,
    open: () => instance && instance.open(),
    close: () => instance && instance.close(),
    ask: (text) => instance && instance.ask(text),
    destroy: () => instance && instance.destroy(),
  };

  const start = () => { if (!script || script.dataset.autoinit !== 'false') init(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
