import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ModeBadges } from '../src/components/ui';
import { adapterLabel, trialOutcomeLabel } from '../src/lib/labels';
import {
  abortRequestsForToken, api, clearSession, getStoredToken,
  setUnauthorizedHandler, storeSession,
} from '../src/lib/api';
import type { Persona } from '../src/lib/types';

const northstar: Persona = { id: 'analyst_northstar', role: 'analyst', tenant_ids: ['tenant_northstar'] };
const cedar: Persona = { id: 'analyst_cedar', role: 'analyst', tenant_ids: ['tenant_cedar'] };

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => {
  clearSession();
  setUnauthorizedHandler(null);
  vi.unstubAllGlobals();
});

describe('R-10 adapter labels never call a mock a live trial', () => {
  it('scripted runs are labeled a lab simulation', () => {
    expect(adapterLabel({ adapter: 'scripted', metrics: null })).toBe('SCRIPTED LAB SIMULATION');
  });
  it('mocked-protocol real runs say mocked, explicitly not live', () => {
    expect(adapterLabel({ adapter: 'real_llm', metrics: { llm: { transport: 'mocked_protocol' } } }))
      .toContain('mocked protocol validation');
    expect(adapterLabel({ adapter: 'real_llm', metrics: { llm: { transport: 'mocked_protocol' } } }))
      .toContain('no live provider call');
  });
  it('live-provider runs say verified live provider trial', () => {
    expect(adapterLabel({ adapter: 'real_llm', metrics: { llm: { transport: 'live_provider' } } }))
      .toBe('REAL LLM (verified live provider trial)');
  });
  it('unrecorded transport is treated as mocked, never live', () => {
    const label = adapterLabel({ adapter: 'real_llm', metrics: { llm: { transport: null } } });
    expect(label).toContain('treat as mocked, not live');
    expect(label).not.toContain('verified live');
  });
});

describe('R-02/R-16 trial outcome labels', () => {
  it('names the scientific outcomes in plain language', () => {
    expect(trialOutcomeLabel('TARGETED_ATTACK_BLOCKED')).toBe('Targeted attack blocked');
    expect(trialOutcomeLabel('UNEXPOSED_PROPOSAL')).toBe('Unexposed proposal (not injection evidence)');
    expect(trialOutcomeLabel('LEGITIMATE_TASK_INCOMPLETE')).toBe('Legitimate task incomplete');
    expect(trialOutcomeLabel('NO_EXPOSURE')).toContain('never reached the model');
    expect(trialOutcomeLabel(null)).toBe('Not recorded');
  });
});

describe('R-12 token-scoped 401 handling', () => {
  it('a late 401 from the OLD token is delivered with the old token, so the App guard (token must equal the active token) ignores it', async () => {
    const seen: Array<string | null> = [];
    setUnauthorizedHandler((t) => { seen.push(t); });
    const d = deferred<unknown>();
    vi.stubGlobal('fetch', vi.fn(() => d.promise));
    storeSession('token-old', northstar);
    const pending = api.overview().then(
      () => 'resolved',
      (e: Error) => e.message,
    );
    // Persona switch happens while the old request is still in flight.
    storeSession('token-new', cedar);
    await (async () => {
      d.resolve({ ok: false, status: 401, json: async () => ({ error: { code: 'SESSION_EXPIRED', message: 'Session expired' } }) });
    })();
    await pending;
    // The handler received the OLD token, not the new active one: the
    // App guard (token !== getStoredToken() → ignore) therefore drops it.
    expect(seen).toEqual(['token-old']);
    expect(getStoredToken()).toBe('token-new');
    expect(seen[0]).not.toBe(getStoredToken());
  });

  it('a 401 from the CURRENT token is delivered with the current token, so the guard acts on it', async () => {
    const seen: Array<string | null> = [];
    setUnauthorizedHandler((t) => { seen.push(t); });
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 401, json: async () => ({ error: { code: 'SESSION_EXPIRED', message: 'Session expired' } }),
    })));
    storeSession('token-current', northstar);
    await expect(api.overview()).rejects.toThrow('Session expired');
    expect(seen).toEqual(['token-current']);
    expect(seen[0]).toBe(getStoredToken());
  });

  it('switching persona aborts the old token in-flight request with ABORTED, not a 401', async () => {
    const d = deferred<unknown>();
    const holder: { signal: AbortSignal | null } = { signal: null };
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => {
      holder.signal = (init?.signal ?? null) as AbortSignal | null;
      // Mirror real fetch: aborting the signal rejects with AbortError.
      return new Promise((resolve, reject) => {
        holder.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        void d.promise.then(resolve, reject);
      });
    }));
    storeSession('token-old', northstar);
    const pending = api.overview().then(
      () => 'resolved',
      (e: Error) => e.message,
    );
    abortRequestsForToken('token-old');
    expect(holder.signal?.aborted).toBe(true);
    await expect(pending).resolves.toContain('aborted by a session change');
  });
});

describe('FR-11 shell badges describe the lab, not the current run', () => {
  it('shows LOCAL SYNTHETIC LAB, never a run-adapter claim', () => {
    render(<ModeBadges />);
    expect(screen.getByText('LOCAL SYNTHETIC LAB')).toBeInTheDocument();
    expect(screen.queryByText('SCRIPTED LAB SIMULATION')).not.toBeInTheDocument();
    expect(screen.getByText('Mode: PROTECTED')).toBeInTheDocument();
  });
});
