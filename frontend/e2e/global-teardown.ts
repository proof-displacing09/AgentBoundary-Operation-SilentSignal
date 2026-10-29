import { existsSync, readFileSync, rmSync } from 'node:fs';
import { basename } from 'node:path';

/**
 * R-06 cleanup: delete ONLY this run's temp database + manifest, even
 * when specs failed. The basename guard means a corrupt or foreign
 * manifest can never make teardown delete an unrelated file (in
 * particular, never anything under the repo — the temp DB always lives
 * under os.tmpdir() with an `agentboundary-e2e-` prefix).
 *
 * AGENTBOUNDARY_E2E_KEEP_DB=1 skips deletion so a harness (the backend
 * regression test) can inspect the temp DB after the run; that harness
 * owns cleanup in that case.
 */
export default async function globalTeardown(): Promise<void> {
  if (process.env.AGENTBOUNDARY_E2E_KEEP_DB === '1') return;
  // FR-09: manifests are per main process (see playwright.config.ts),
  // so teardown must find ONLY its own run's manifest — never another
  // concurrent run's. Discovery order: (1) the env manifest the main
  // evaluation published (visible when teardown shares the main
  // process); (2) the ppid-derived path — teardown is spawned by the
  // main process, so its parent pid IS the main pid; (3) the legacy
  // fixed path, for manifests written by older configs. The basename
  // guard below still prevents deleting anything foreign.
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const ppidManifest = join(tmpdir(), `agentboundary-e2e-manifest-${process.ppid}.json`);
  const manifestPath =
    (process.env.AGENTBOUNDARY_E2E_MANIFEST &&
      existsSync(process.env.AGENTBOUNDARY_E2E_MANIFEST) &&
      process.env.AGENTBOUNDARY_E2E_MANIFEST) ||
    (existsSync(ppidManifest) && ppidManifest) ||
    join(tmpdir(), 'agentboundary-e2e-manifest.json');
  if (!existsSync(manifestPath)) return;
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8')) as {
      dbPath?: unknown;
    };
    const dbPath = manifest.dbPath;
    if (typeof dbPath === 'string' && basename(dbPath).startsWith('agentboundary-e2e-')) {
      for (const suffix of ['', '-wal', '-shm', '-journal']) {
        rmSync(`${dbPath}${suffix}`, { force: true });
      }
    }
  } finally {
    rmSync(manifestPath, { force: true });
  }
}
