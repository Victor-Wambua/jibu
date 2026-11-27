// Builds the static demo into demo/dist.
//
// The Python engine, the knowledge bases and the evaluation sets are COPIED from the repo
// (src/jibu, kb, eval) at build time, so the demo cannot drift from the code it demonstrates.
import { createHash } from 'node:crypto';
import { execSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..');
const dist = join(here, 'dist');

// Modules the demo needs. api.py, cli.py and whatsapp.py need FastAPI/httpx and stay out.
const PYTHON_MODULES = [
  '__init__', 'bm25', 'config', 'engine', 'evalreport', 'evaluation', 'kb', 'lang',
  'privacy', 'service', 'sessions', 'text', 'unanswered',
];

const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const files = [];
function copy(from, to, role) {
  const dest = join(dist, to);
  mkdirSync(dirname(dest), { recursive: true });
  cpSync(from, dest);
  const buf = readFileSync(dest);
  files.push({ path: to.split(sep).join('/'), role, bytes: buf.length, sha256: sha(buf) });
}

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

let commit = process.env.GITHUB_SHA || '';
if (!commit) {
  try { commit = execSync('git rev-parse HEAD', { cwd: repo }).toString().trim(); } catch { commit = 'unknown'; }
}

// 1. Page: src/* (html, css, js, worker, favicon)
for (const f of readdirSync(join(here, 'src'))) {
  if (f === 'sw.js') continue;
  copy(join(here, 'src', f), f, 'page');
}
// 2. The real engine, KBs and eval sets, straight from the repo
for (const m of PYTHON_MODULES) copy(join(repo, 'src', 'jibu', `${m}.py`), `engine/jibu/${m}.py`, 'python');
copy(join(here, 'py', 'jibu_demo.py'), 'engine/jibu_demo.py', 'python');
for (const f of readdirSync(join(repo, 'kb')).filter((x) => x.endsWith('.yaml'))) copy(join(repo, 'kb', f), `engine/kb/${f}`, 'kb');
for (const f of readdirSync(join(repo, 'eval')).filter((x) => x.endsWith('.yaml'))) copy(join(repo, 'eval', f), `engine/eval/${f}`, 'eval');
// 3. Vendored Pyodide runtime and wheels
const vendor = join(here, 'vendor', 'pyodide');
for (const f of readdirSync(vendor)) copy(join(vendor, f), `vendor/pyodide/${f}`, 'runtime');

const lock = JSON.parse(readFileSync(join(vendor, 'pyodide-lock.json'), 'utf8'));
const manifest = {
  commit,
  runtime: { pyodide: lock.info.version, python: lock.info.python, packages: Object.values(lock.packages).map((p) => `${p.name} ${p.version}`).sort() },
  files,
};
const manifestText = JSON.stringify(manifest, null, 1);
writeFileSync(join(dist, 'manifest.json'), manifestText);

// 4. Service worker: precache every file so the demo works offline after one visit.
const version = sha(Buffer.from(manifestText)).slice(0, 12);
const precache = ['./', 'manifest.json', ...files.map((f) => f.path)];
const sw = readFileSync(join(here, 'src', 'sw.js'), 'utf8')
  .replace('__VERSION__', version)
  .replace('__PRECACHE__', JSON.stringify(precache));
if (sw.includes('__VERSION__') || sw.includes('__PRECACHE__')) throw new Error('sw.js placeholders not filled');
writeFileSync(join(dist, 'sw.js'), sw);

const total = files.reduce((n, f) => n + f.bytes, 0);
console.log(`demo built: ${files.length} files, ${(total / 1048576).toFixed(1)} MB, commit ${commit.slice(0, 7)}, cache ${version}`);
if (!existsSync(join(dist, 'index.html'))) throw new Error('index.html missing');
