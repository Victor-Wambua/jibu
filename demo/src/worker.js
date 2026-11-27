'use strict';
// Runs the real Jibu engine (Python, under self-hosted Pyodide) off the main thread.
// Protocol: the page sends {id, fn, args}; this replies {id, result} or {id, error}.
// Every `fn` is a function of demo/py/jibu_demo.py and returns a JSON string.

let bridge = null;
const post = (message) => self.postMessage(message);

async function boot() {
  const started = performance.now();
  post({ type: 'progress', text: 'Reading the file list' });
  const manifest = await (await fetch('manifest.json')).json();

  post({ type: 'progress', text: 'Starting Python (WebAssembly)' });
  importScripts('vendor/pyodide/pyodide.js');
  const py = await self.loadPyodide({ indexURL: new URL('vendor/pyodide/', self.location.href).href });

  post({ type: 'progress', text: 'Loading pydantic and PyYAML' });
  await py.loadPackage(['pydantic', 'pyyaml']);

  post({ type: 'progress', text: 'Loading the Jibu engine, knowledge bases and evaluation sets' });
  const wanted = manifest.files.filter((f) => ['python', 'kb', 'eval'].includes(f.role));
  const bodies = await Promise.all(wanted.map(async (f) => [f, await (await fetch(f.path)).text()]));
  for (const [f, text] of bodies) {
    const target = '/app/' + f.path.replace(/^engine\//, '');
    py.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')));
    py.FS.writeFile(target, text);
  }
  py.runPython("import sys, os\nsys.path.insert(0, '/app')\nos.chdir('/app')");
  bridge = py.pyimport('jibu_demo');

  post({ type: 'progress', text: 'Validating the knowledge bases' });
  const catalogue = bridge.init('kb', 'eval');
  const info = JSON.parse(py.runPython(
    "import json, sys, pydantic, yaml\n" +
    "json.dumps({'python': sys.version.split()[0], 'pydantic': pydantic.VERSION, 'yaml': yaml.__version__})"
  ));
  info.pyodide = py.version;
  info.bootMs = Math.round(performance.now() - started);
  post({ type: 'ready', catalogue: JSON.parse(catalogue), info, manifest });
}

self.onmessage = async ({ data }) => {
  const { id, fn, args = [] } = data;
  try {
    if (!bridge) throw new Error('The engine is not ready yet');
    const t = performance.now();
    const result = bridge[fn](...args);
    post({ id, result: JSON.parse(result), ms: Math.round(performance.now() - t) });
  } catch (err) {
    const lines = String(err && err.message ? err.message : err).trim().split('\n');
    post({ id, error: lines[lines.length - 1] });
  }
};

boot().catch((err) => {
  const lines = String(err && err.message ? err.message : err).trim().split('\n');
  post({ type: 'error', text: lines[lines.length - 1] });
});
