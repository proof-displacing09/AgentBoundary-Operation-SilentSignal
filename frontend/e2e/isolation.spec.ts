import { expect, test } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename } from 'node:path';
import { API, apiRun, apiSession, resetLab } from './helpers';

/**
 * R-06: proves the E2E run exercises an isolated test backend, never the
 * developer's demo backend.
 *
 * (a) After a privileged reset inside the TEST database, the overview
 *     starts at total_runs 0.
 * (b) Creating a run in the test DB is visible there, and a second reset
 *     returns it to 0 — resets stay inside the test database.
 * (c) The backend's database file is the run's temp file: it lives under
 *     os.tmpdir() with an `agentboundary-e2e-` name, and it is not under
 *     the repo (so it cannot be backend/data/agentboundary.db). The API
 *     base the helpers use is the one the isolated config published.
 *
 * HONEST LIMIT, stated not hidden: a browser spec cannot inspect the
 * developer's demo database — it has no access to it, and claiming to
 * check it from here would be theatre. The proof that the demo DB is
 * untouched (hash + row counts before/after, including a forced-failure
 * run) lives in backend/tests/security/test_e2e_isolation.py, which
 * hashes a copy of the demo DB around a real Playwright invocation.
 */
function testDbPath(): string {
  const fromEnv = process.env.AGENTBOUNDARY_E2E_DB_PATH;
  if (fromEnv) return fromEnv;
  const manifest = process.env.AGENTBOUNDARY_E2E_MANIFEST;
  if (manifest && existsSync(manifest)) {
    const parsed = JSON.parse(readFileSync(manifest, 'utf-8')) as {
      dbPath?: unknown;
    };
    if (typeof parsed.dbPath === 'string') return parsed.dbPath;
  }
  throw new Error('isolated E2E config did not publish AGENTBOUNDARY_E2E_DB_PATH');
}

test('e2e backend is isolated: own temp DB, own ports, resets stay inside it', async ({ request }) => {
  const dbPath = testDbPath();

  // (c) The database under test is a temp file, never the repo demo DB.
  expect(dbPath.startsWith(tmpdir())).toBeTruthy();
  expect(basename(dbPath).startsWith('agentboundary-e2e-')).toBeTruthy();
  expect(dbPath).not.toContain('/workspace/agentboundary/backend/data');
  expect(existsSync(dbPath)).toBeTruthy();
  // Helpers must be talking to the config-published test backend.
  expect(process.env.AGENTBOUNDARY_E2E_API_BASE).toBeTruthy();
  expect(API).toBe(process.env.AGENTBOUNDARY_E2E_API_BASE);

  // (a) Fresh reset inside the test DB -> honest zero state.
  await resetLab(request);
  const commander = await apiSession(request, 'incident_commander');
  const fresh = await request.get(`${API}/overview`, {
    headers: { 'X-Lab-Session': commander },
  });
  expect(fresh.ok()).toBeTruthy();
  expect((await fresh.json()).total_runs).toBe(0);

  // (b) A run created via the test API is visible in the test overview,
  // and a second reset removes it again — all inside the test DB.
  const northstar = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, northstar, 'A1');
  const after = await request.get(`${API}/overview`, {
    headers: { 'X-Lab-Session': commander },
  });
  const afterBody = await after.json();
  expect(afterBody.total_runs).toBe(1);
  expect(JSON.stringify(afterBody.recent_runs)).toContain(run.id);

  await resetLab(request);
  // Reset preserves only the resetting session, so the earlier commander
  // token is gone by design — mint a fresh one before re-checking.
  const commander2 = await apiSession(request, 'incident_commander');
  const reset = await request.get(`${API}/overview`, {
    headers: { 'X-Lab-Session': commander2 },
  });
  expect(reset.ok()).toBeTruthy();
  expect((await reset.json()).total_runs).toBe(0);
});
