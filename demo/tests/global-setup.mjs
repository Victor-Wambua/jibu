// Writes demo/golden.json with the numbers `jibu eval` computes natively (needs uv).
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export default function globalSetup() {
  const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
  const r = spawnSync('uv', ['run', 'python', 'demo/tools/golden.py'], { cwd: repo, stdio: 'inherit' });
  if (r.status !== 0) throw new Error('could not compute the native reference numbers (uv run python demo/tools/golden.py)');
}
