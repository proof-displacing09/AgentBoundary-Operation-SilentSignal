import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig } from '@playwright/test';

/**
 * AgentBoundary E2E config — ISOLATED BY DESIGN (R-06).
 *
 * Earlier versions used `reuseExistingServer: true` against the demo ports
 * (:8000/:5173) while specs POST /lab/reset, so `npm run test:e2e` could
 * globally wipe a developer's live demo database. That must never happen
 * again, so this config:
 *
 *  1. Starts its OWN backend + frontend on run-specific loopback ports
 *     (never the demo ports by construction — ports are picked free at
 *     config load, or taken from AGENTBOUNDARY_E2E_API_PORT /
 *     AGENTBOUNDARY_E2E_WEB_PORT when a harness supplies them).
 *  2. Points ONLY the test backend at a fresh temp SQLite file under
 *     os.tmpdir() via AGENTBOUNDARY_DB_PATH in that subprocess's env.
 *     The demo DB (backend/data/agentboundary.db) is never referenced.
 *  3. Sets reuseExistingServer: false, so Playwright never attaches to an
 *     unrelated process: if a chosen port is occupied, the test server
 *     fails to bind (vite uses --strictPort) and the run fails loudly
 *     instead of silently testing the wrong server.
 *  4. Publishes the chosen endpoints to test workers via process.env
 *     (AGENTBOUNDARY_E2E_API_BASE / _WEB_BASE / _DB_PATH / _MANIFEST) and
 *     writes the same values to a manifest file under tmpdir(), so specs
 *     can assert which database they are actually exercising.
 *  5. Deletes the run's temp DB + manifest in global teardown, even when
 *     specs fail — unless AGENTBOUNDARY_E2E_KEEP_DB=1 (used by the
 *     backend regression test that inspects the temp DB after the run).
 *
 * Browser binary: use Playwright's own stock Chromium headless shell
 * (revision 1248, Chrome for Testing 156) from ~/.cache/ms-playwright.
 * The sandbox's managed Chromium at /opt/meta-chromium/chrome is only a
 * fallback: its build force-enables Local Network Access checks and blocks
 * EVERY loopback navigation with ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS,
 * even with --disable-features=LocalNetworkAccessChecks. The stock binary
 * does not have that policy and loads loopback pages normally.
 * Set PLAYWRIGHT_CHROMIUM_PATH to override the binary explicitly.
 */

// Allocate one genuinely free loopback port, synchronously, by binding
// port 0 in a short-lived node child and reading the assigned port back.
// The bind-then-close leaves a small race window; it is closed by (3)
// above: a server that cannot bind fails the run instead of attaching
// to whatever took the port.
function freePort(): number {
  const script =
    'const s=require("net").createServer();' +
    's.on("error",()=>process.exit(1));' +
    's.listen(0,"127.0.0.1",()=>{process.stdout.write(String(s.address().port));s.close();});';
  const r = spawnSync(process.execPath, ['-e', script], { encoding: 'utf-8' });
  if (r.status !== 0 || !r.stdout) {
    throw new Error(`playwright config: could not allocate a free loopback port: ${r.stderr ?? ''}`);
  }
  const port = Number(r.stdout);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`playwright config: invalid free port allocated: ${r.stdout}`);
  }
  return port;
}

function envPort(name: string): number | undefined {
  const raw = process.env[name];
  if (!raw) return undefined;
  const port = Number(raw);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`playwright config: ${name} must be a valid port, got ${JSON.stringify(raw)}`);
  }
  return port;
}

// Playwright evaluates this config TWICE per invocation: once in the
// main process (which starts the webServers) and once in each worker
// process (whose env the specs see). Generating fresh ports/paths on
// every evaluation would silently split the run: the backend would serve
// one temp DB while specs asserted about another. Empirically, workers
// do NOT inherit the main process's env, so env-based reuse does not
// work. Instead, evaluations share a manifest file, and a later
// evaluation reuses it only when the manifest's pid equals its own
// parent pid — i.e. it was written by the main process that spawned
// this worker. A stale manifest from an earlier run has a different
// (dead) pid, so it is never reused; the reusing evaluation must NOT
// rewrite the manifest, or it would orphan the main process's values.
// (Verified: without reuse, the worker's temp-DB path never existed
// because the backend had created the main process's path.)
// FR-09: the manifest is named PER MAIN PROCESS
// (agentboundary-e2e-manifest-<mainPid>.json), so two concurrent
// suites can never overwrite each other's manifest: a worker finds its
// own run's manifest via its parent pid (its ppid IS the main pid),
// and global teardown finds it the same way (its ppid, or the env var
// the main evaluation published). There is no shared manifest anymore.
interface RunManifest { dbPath: string; apiPort: number; webPort: number; pid: number }
function readManifest(path: string): RunManifest | undefined {
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf-8')) as Partial<RunManifest>;
    if (
      typeof parsed.dbPath === 'string' &&
      Number.isInteger(parsed.apiPort) &&
      Number.isInteger(parsed.webPort)
    ) {
      return parsed as RunManifest;
    }
  } catch {
    // Missing/corrupt manifest: fall through to fresh allocation.
  }
  return undefined;
}

const parentManifestPath = join(tmpdir(), `agentboundary-e2e-manifest-${process.ppid}.json`);
const shared = readManifest(parentManifestPath);

let apiPort: number;
let webPort: number;
let dbPath: string;
let manifestPath: string;
if (shared && shared.pid === process.ppid) {
  // Worker re-evaluation: adopt the main process's run. Do not rewrite
  // the manifest — it must keep pointing at the main process's run.
  ({ apiPort, webPort, dbPath } = shared);
  manifestPath = parentManifestPath;
} else {
  apiPort = envPort('AGENTBOUNDARY_E2E_API_PORT') ?? freePort();
  webPort = envPort('AGENTBOUNDARY_E2E_WEB_PORT') ?? freePort();
  if (webPort === apiPort) webPort = freePort();
  const runTag = `${process.pid}-${randomBytes(6).toString('hex')}`;
  dbPath = join(tmpdir(), `agentboundary-e2e-${runTag}.db`);
  manifestPath = join(tmpdir(), `agentboundary-e2e-manifest-${process.pid}.json`);
  writeFileSync(
    manifestPath,
    JSON.stringify({ dbPath, apiPort, webPort, pid: process.pid }, null, 2),
  );
}
process.env.AGENTBOUNDARY_E2E_API_BASE = `http://127.0.0.1:${apiPort}/api/v1`;
process.env.AGENTBOUNDARY_E2E_WEB_BASE = `http://127.0.0.1:${webPort}`;
process.env.AGENTBOUNDARY_E2E_DB_PATH = dbPath;
process.env.AGENTBOUNDARY_E2E_MANIFEST = manifestPath;

const stockShell = join(homedir(), '.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell');
const chromiumPath = process.env.PLAYWRIGHT_CHROMIUM_PATH
  ?? (existsSync(stockShell) ? undefined : '/opt/meta-chromium/chrome');

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  globalTeardown: './e2e/global-teardown.ts',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    launchOptions: {
      ...(chromiumPath ? { executablePath: chromiumPath } : {}),
      // --no-proxy-server: the sandbox egress proxy must never sit between
      // the test browser and the loopback app servers.
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server'],
    },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `../backend/.venv/bin/uvicorn agentboundary.api.app:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${apiPort}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      // The ONLY database this backend may open. The demo DB path is the
      // backend default when this variable is absent, so it must be set.
      env: { AGENTBOUNDARY_DB_PATH: dbPath },
    },
    {
      // --strictPort: never silently bind a different port than the one
      // the tests address; fail loudly instead.
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: `http://127.0.0.1:${webPort}/`,
      reuseExistingServer: false,
      timeout: 60_000,
      // Vite reads this in vite.config.ts to proxy /api at the TEST
      // backend; without it the browser UI would reach the demo backend.
      env: { AGENTBOUNDARY_E2E_API_PORT: String(apiPort) },
    },
  ],
});
