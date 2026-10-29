// Starts the app for the Playwright E2E suite (docs/UI.md §7): a fresh
// temporary DATA_DIR, `mdt db upgrade` and `mdt seed`, then `mdt serve`, which
// serves /api and the built frontend (frontend/dist) on one port.
//
//   node e2e/start-server.mjs <port>
//
// playwright.config.ts runs this as its webServer and passes a free port. The
// temporary directory (under TMPDIR) is removed when the server stops (SIGTERM
// or SIGINT; Playwright sends SIGTERM to the process group at the end).
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const frontendDist = join(repoRoot, 'frontend', 'dist');
const port = process.argv[2] ?? '';

if (!/^[0-9]{1,5}$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
  console.error('usage: node e2e/start-server.mjs <port>');
  process.exit(1);
}
if (!existsSync(join(frontendDist, 'index.html'))) {
  console.error(`e2e server: ${frontendDist} has no build; run \`npm run build\` first (\`make e2e\` builds it).`);
  process.exit(1);
}

const dataDir = mkdtempSync(join(tmpdir(), 'mdt-e2e-'));

// Every setting the suite depends on is set here, so a local .env (read by the
// backend for anything not in the environment) cannot redirect the database
// or change the behaviour under test. The values of FOCAL_ORG_SEED_KEY and
// MAX_COMMENT_CHARS are the backend defaults (backend/src/mdt/config.py).
const env = {
  ...process.env,
  HOST: '127.0.0.1',
  PORT: port,
  DATA_DIR: dataDir,
  DATABASE_URL: `sqlite:///${join(dataDir, 'app.db')}`,
  CODEBOOK_DIR: join(repoRoot, 'codebook'),
  SEED_DIR: join(repoRoot, 'seed'),
  FRONTEND_DIST: frontendDist,
  ALLOWED_HOSTS: '127.0.0.1,localhost',
  TEAM_MEMBERS: 'E2E Alice,E2E Bob',
  MAX_COMMENT_CHARS: '10000',
  FOCAL_ORG_SEED_KEY: 'ministry-of-digital-transformation',
  LOG_LEVEL: 'WARNING',
};

let child = null;
let stopping = false;

/** Runs `mdt <args>`; resolves with its exit code (or signal name). */
function mdt(args) {
  return new Promise((done, failed) => {
    child = spawn('uv', ['run', '--project', join(repoRoot, 'backend'), 'mdt', ...args], {
      cwd: repoRoot,
      env,
      stdio: 'inherit',
    });
    child.on('error', failed);
    child.on('exit', (code, signal) => {
      done(code ?? signal);
    });
  });
}

async function main() {
  for (const step of [['db', 'upgrade'], ['seed']]) {
    const result = await mdt(step);
    if (stopping) return 0;
    if (result !== 0) {
      console.error(`e2e server: \`mdt ${step.join(' ')}\` failed (${result}).`);
      return 1;
    }
  }
  const result = await mdt(['serve', '--host', '127.0.0.1', '--port', port]);
  if (stopping) return 0;
  console.error(`e2e server: \`mdt serve\` exited unexpectedly (${result}).`);
  return 1;
}

function stop() {
  if (stopping) return;
  stopping = true;
  child?.kill('SIGTERM');
  // uvicorn stops within a second; do not leave a process behind if it hangs.
  setTimeout(() => child?.kill('SIGKILL'), 5000).unref();
}
process.on('SIGTERM', stop);
process.on('SIGINT', stop);

main().then(
  (code) => {
    rmSync(dataDir, { recursive: true, force: true });
    process.exit(code);
  },
  (error) => {
    rmSync(dataDir, { recursive: true, force: true });
    console.error(`e2e server: could not run mdt: ${error.message}`);
    process.exit(1);
  },
);
