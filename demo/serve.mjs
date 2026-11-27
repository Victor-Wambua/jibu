// Tiny static server for the built demo. Serves demo/dist under /jibu/ (like GitHub Pages) and /.
import { createServer } from 'node:http';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), 'dist');
const port = Number(process.env.PORT || 8960);
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.wasm': 'application/wasm', '.zip': 'application/zip', '.whl': 'application/octet-stream',
  '.svg': 'image/svg+xml', '.yaml': 'text/yaml; charset=utf-8', '.py': 'text/x-python; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
};

createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (p.startsWith('/jibu/')) p = p.slice(5); else if (p === '/jibu') { res.writeHead(301, { location: '/jibu/' }); return res.end(); }
  if (p.endsWith('/')) p += 'index.html';
  const file = normalize(join(root, p));
  if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) { res.writeHead(404); return res.end('not found'); }
  res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream', 'cache-control': 'no-cache' });
  createReadStream(file).pipe(res);
}).listen(port, () => console.log(`http://localhost:${port}/jibu/`));
