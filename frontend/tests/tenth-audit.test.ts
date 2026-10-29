import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  api,
  abortRequestsForToken,
  clearSession,
  setUnauthorizedHandler,
  storeSession,
} from '../src/lib/api';
import type { Persona } from '../src/lib/types';

const northstar: Persona = { id: 'analyst_northstar', role: 'analyst', tenant_ids: ['tenant_northstar'] };
const cedar: Persona = { id: 'analyst_cedar', role: 'analyst', tenant_ids: ['tenant_cedar'] };

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

/** Report fetch mock: headers resolve at once, the body waits on a gate
 * and honors the AbortSignal — the closest unit-level model of a
 * response whose headers arrived but whose body is still streaming. */
function delayedReportFetch() {
  const gate = deferred<void>();
  let signal: AbortSignal | null = null;
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    signal = (init?.signal as AbortSignal | undefined) ?? null;
    return {
      ok: true,
      status: 200,
      blob: async () => {
        await gate.promise;
        if (signal?.aborted) {
          throw new DOMException('The operation was aborted.', 'AbortError');
        }
        return new Blob(['{"report": true}'], { type: 'application/json' });
      },
    };
  });
  return { fetchMock, gate };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  clearSession();
  try { sessionStorage.clear(); } catch { /* ignore */ }
  vi.unstubAllGlobals();
  // This jsdom build has no URL.createObjectURL; the download path
  // needs it to exist so tests can spy on (not bypass) it.
  if (typeof URL.createObjectURL !== 'function') {
    (URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(() => 'blob:test');
    (URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn();
  }
});

afterEach(() => {
  vi.restoreAllMocks();
  setUnauthorizedHandler(null);
});

describe('T10-03 report download persona-switch race', () => {
  it('(a) switching persona while the body streams discards the old report: no file, no success', async () => {
    const { fetchMock, gate } = delayedReportFetch();
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL');
    storeSession('old-token', northstar);
    const p = api.downloadReport('run-x', 'json');
    await flush(); // fetch resolved; downloadReport is parked in blob()
    storeSession('new-token', cedar); // the persona switch (no abort here: isolates the recheck)
    gate.resolve();
    await expect(p).rejects.toThrow('session change');
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it('(b) aborting the old token while the body streams rejects as ABORTED, with no file', async () => {
    const { fetchMock, gate } = delayedReportFetch();
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL');
    storeSession('old-token', northstar);
    const p = api.downloadReport('run-x', 'json');
    await flush();
    abortRequestsForToken('old-token'); // what the real switch does
    gate.resolve();
    await expect(p).rejects.toThrow('aborted by a session change');
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it('(c) control: without a switch, the download succeeds and triggers a file', async () => {
    const { fetchMock, gate } = delayedReportFetch();
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL');
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    storeSession('old-token', northstar);
    const p = api.downloadReport('run-x', 'json');
    await flush();
    gate.resolve();
    await expect(p).resolves.toBe('agentboundary-run-run-x.json');
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it('(d) a late 401 on an old token still reports through the token-scoped handler', async () => {
    const seen: Array<string | null> = [];
    setUnauthorizedHandler((token) => { seen.push(token); });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 })));
    storeSession('old-token', northstar);
    await expect(api.downloadReport('run-x', 'json')).rejects.toThrow('Report download failed (401)');
    expect(seen).toEqual(['old-token']);
  });
});
