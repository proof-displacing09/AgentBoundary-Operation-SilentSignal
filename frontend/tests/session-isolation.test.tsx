import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import App from '../src/app/App';
import Overview from '../src/features/Overview';
import LabSettings from '../src/features/LabSettings';
import Replay from '../src/features/Replay';
import { SessionContext, type SessionCtx } from '../src/components/session';
import { api, clearSession, storeSession } from '../src/lib/api';
import { groupEvents } from '../src/components/ui';
import type { Persona } from '../src/lib/types';

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function okJson(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

const northstar: Persona = { id: 'analyst_northstar', role: 'analyst', tenant_ids: ['tenant_northstar'] };
const cedar: Persona = { id: 'analyst_cedar', role: 'analyst', tenant_ids: ['tenant_cedar'] };
const commander: Persona = { id: 'incident_commander', role: 'incident_commander', tenant_ids: ['tenant_northstar', 'tenant_cedar'] };

function ctx(persona: Persona | null, sessionVersion: number): SessionCtx {
  return {
    persona, personas: [northstar, cedar, commander],
    switchPersona: async () => {}, push: () => {}, navigate: () => {}, sessionVersion,
  };
}

const overviewA = {
  scenarios_run: 1, total_runs: 1, attempted_unauthorized: 0, denied: 0,
  completed_forbidden: 0, tenant_leaks: 0, legitimate_task_successes: 1,
  security_invariant_passes: 1, legitimate_workflow_completions: 1, inconclusive: 0,
  recent_runs: [], recent_cases: [{ id: 'INC-2048', title: 'Northstar shipment anomaly', status: 'investigating', tenant_id: 'tenant_northstar' }],
};
const overviewB = {
  ...overviewA,
  recent_cases: [{ id: 'INC-3307', title: 'Cedar checkout anomaly', status: 'investigating', tenant_id: 'tenant_cedar' }],
};
const emptyComparisons = { protected_runs: [], weak_reports: [], comparable: false, notes: '' };

beforeEach(() => {
  clearSession();
  try { sessionStorage.clear(); } catch { /* ignore */ }
  vi.unstubAllGlobals();
});

describe('N-05 stale session data', () => {
  it('(a) a delayed persona-A response resolving AFTER the switch never displays A data', async () => {
    const dA = deferred<unknown>();
    const dB = deferred<unknown>();
    let overviewCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/overview')) return ++overviewCalls === 1 ? dA.promise : dB.promise;
      return okJson(emptyComparisons);
    }));
    const { rerender } = render(
      <SessionContext.Provider value={ctx(northstar, 0)}><Overview /></SessionContext.Provider>,
    );
    // Switch session before either overview response resolves.
    rerender(<SessionContext.Provider value={ctx(cedar, 1)}><Overview /></SessionContext.Provider>);
    await act(async () => { dA.resolve(okJson(overviewA)); });
    // Case titles render split across elements, so assert on page text.
    expect(document.body.textContent).not.toContain('Northstar shipment anomaly');
    await act(async () => { dB.resolve(okJson(overviewB)); });
    await waitFor(() => expect(document.body.textContent).toContain('Cedar checkout anomaly'));
  });

  it('(b) switching persona clears previously rendered tenant content immediately, before the new fetch resolves', async () => {
    const dB = deferred<unknown>();
    let overviewCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/overview')) return ++overviewCalls === 1 ? okJson(overviewA) : dB.promise;
      return okJson(emptyComparisons);
    }));
    const { rerender } = render(
      <SessionContext.Provider value={ctx(northstar, 0)}><Overview /></SessionContext.Provider>,
    );
    await waitFor(() => expect(document.body.textContent).toContain('Northstar shipment anomaly'));
    // Switch: the old tenant's case must vanish at once, while the new fetch is still pending.
    rerender(<SessionContext.Provider value={ctx(cedar, 1)}><Overview /></SessionContext.Provider>);
    expect(document.body.textContent).not.toContain('Northstar shipment anomaly');
    expect(screen.queryAllByLabelText('Loading…').length).toBeGreaterThan(0);
    await act(async () => { dB.resolve(okJson(overviewB)); });
    await waitFor(() => expect(document.body.textContent).toContain('Cedar checkout anomaly'));
  });

  it('(c) a 401 during a page fetch routes to the expired-session state with no stale data', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes('/lab/personas')) return okJson([northstar, cedar, commander]);
      if (u.includes('/lab/session') && init?.method === 'POST') {
        return okJson({ session_token: 'tok-1', persona: northstar, expires_at: '2099-01-01T00:00:00Z' });
      }
      if (u.includes('/overview')) {
        return { ok: false, status: 401, json: async () => ({ error: { code: 'SESSION_EXPIRED', message: 'Session expired' } }) };
      }
      return okJson(emptyComparisons);
    }));
    render(<App />);
    // The expired-session text appears in both the banner and the toast; the
    // banner's exact wording is unique.
    expect(await screen.findByText('Lab session expired — please sign in to the lab session again.')).toBeInTheDocument();
    expect(screen.getByText('No active lab session')).toBeInTheDocument();
    expect(screen.getByLabelText('Select local lab persona')).toBeInTheDocument();
    expect(screen.queryByText('SOC Security Command Center')).not.toBeInTheDocument();
    expect(sessionStorage.getItem('agentboundary.labSessionToken')).toBeNull();
  });
});

describe('Report downloads use the current session token', () => {
  it('reads the stored token at click time, not at page load', async () => {
    const seen: Array<Record<string, string>> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      seen.push((init?.headers ?? {}) as Record<string, string>);
      return { ok: true, status: 200, blob: async () => new Blob(['{}']) };
    }));
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() });
    storeSession('token-old', northstar);
    await api.downloadReport('run-x', 'json');
    storeSession('token-new', northstar);
    await api.downloadReport('run-x', 'json');
    expect(seen[0]?.['X-Lab-Session']).toBe('token-old');
    expect(seen[1]?.['X-Lab-Session']).toBe('token-new');
  });
});

describe('N-03 reset API contract', () => {
  it('sends dry_run / confirm / empty bodies exactly as specified', async () => {
    const bodies: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(String(init?.body ?? ''));
      return okJson({ reset: true, records: 48 });
    }));
    await api.reset();
    await api.reset({ dryRun: true });
    await api.reset({ confirm: true });
    expect(bodies).toEqual(['{}', '{"dry_run":true}', '{"confirm":true}']);
  });

  it('disables reset for non-admin personas with a plain explanation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/health')) return okJson({ status: 'ok', mode: 'protected', weak_mode_available_via_api: false, db_version: '1', fixture_version: '1.0.0', adapter: 'scripted', real_model_configured: false });
      return okJson({});
    }));
    render(<SessionContext.Provider value={ctx(northstar, 0)}><LabSettings /></SessionContext.Provider>);
    const btn = await screen.findByRole('button', { name: /Preview lab reset/i });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/Only the Incident Commander lab-admin persona can reset the lab/i)).toBeInTheDocument();
  });

  it('incident_commander previews counts, then confirms, then sees the fresh record count', async () => {
    const bodies: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes('/lab/reset')) {
        bodies.push(String(init?.body ?? ''));
        return okJson(String(init?.body ?? '').includes('dry_run')
          ? { dry_run: true, would_delete: { runs: 3, events: 42, drafts: 1, isolations: 2 } }
          : { reset: true, records: 48 });
      }
      if (u.includes('/health')) return okJson({ status: 'ok', mode: 'protected', weak_mode_available_via_api: false, db_version: '1', fixture_version: '1.0.0', adapter: 'scripted', real_model_configured: false });
      return okJson({});
    }));
    render(<SessionContext.Provider value={ctx(commander, 0)}><LabSettings /></SessionContext.Provider>);
    fireEvent.click(await screen.findByRole('button', { name: /Preview lab reset/i }));
    expect(await screen.findByText('Reset preview — nothing has been deleted yet')).toBeInTheDocument();
    expect(screen.getByText('Nothing has been deleted yet', { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Yes, reset the lab/i }));
    expect(await screen.findByText(/Fresh fixture record count: 48/)).toBeInTheDocument();
    expect(bodies).toEqual(['{"dry_run":true}', '{"confirm":true}']);
  });
});

describe('Logical tool calls and control-only evidence', () => {
  it('groups ATTEMPT + terminal rows sharing a tool_call_id into one logical call', () => {
    const base = {
      event_id: 'e', run_id: 'r', scenario_id: 'A5', seq: 1, timestamp: '2026-01-01T00:00:00Z',
      actor_id: 'analyst_northstar', tenant_id: 'tenant_northstar', adapter: 'scripted', tool: 'read_case',
      args_sanitized: null, source_provenance: null, trust_label: null, reason_code: null,
      approval_status: null, disclosed_restricted: false, before_state: null, after_state: null, detail: null,
    };
    const groups = groupEvents([
      { ...base, event_id: 'e1', seq: 1, attempted: true, completed: false, decision: 'INFO', tool_call_id: 'tc-1' },
      { ...base, event_id: 'e2', seq: 2, attempted: false, completed: true, decision: 'ALLOW', tool_call_id: 'tc-1' },
      { ...base, event_id: 'e3', seq: 3, attempted: false, completed: false, decision: 'INFO', tool_call_id: null },
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]?.attempt?.event_id).toBe('e1');
    expect(groups[0]?.terminal?.event_id).toBe('e2');
  });

  const controlRun = {
    id: 'run-a5-test', scenario_id: 'A5', status: 'complete', verdict: 'PASS' as const,
    adapter: 'scripted', mode: 'protected', started_at: '', finished_at: null,
    metrics: { attempted_unauthorized: 0, completed_forbidden: 0, denied: 0, disclosed_restricted: false, legitimate_task_success: false },
    operator_persona_id: 'analyst_northstar', simulated_actor_id: 'analyst_northstar', control_actor_id: 'analyst_cedar',
    events: [
      {
        event_id: 'c1', run_id: 'run-a5-test', scenario_id: 'A5', tool_call_id: 'tc-c1', evidence_scope: 'control_only',
        seq: 1, timestamp: '2026-01-01T00:00:00Z', actor_id: 'analyst_cedar', tenant_id: 'tenant_cedar',
        adapter: 'scripted', tool: 'read_case', args_sanitized: { case_id: 'INC-3307', marker: 'CEDAR-CONTROL-MARKER' },
        source_provenance: null, trust_label: null, decision: 'INFO' as const, reason_code: null, approval_status: null,
        attempted: true, completed: false, disclosed_restricted: false, before_state: null, after_state: null,
        detail: 'Proposed read_case of INC-3307',
      },
      {
        event_id: 'c2', run_id: 'run-a5-test', scenario_id: 'A5', tool_call_id: 'tc-c1', evidence_scope: 'control_only',
        seq: 2, timestamp: '2026-01-01T00:00:01Z', actor_id: 'analyst_cedar', tenant_id: 'tenant_cedar',
        adapter: 'scripted', tool: 'read_case', args_sanitized: { case_id: 'INC-3307' },
        source_provenance: null, trust_label: null, decision: 'ALLOW' as const, reason_code: null, approval_status: null,
        attempted: false, completed: true, disclosed_restricted: false, before_state: null, after_state: null,
        detail: 'Positive control read allowed',
      },
    ],
  };

  it('non-admin viewers see only the control reference line, never control args or case identifiers', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).endsWith('/runs')) return okJson([{ id: 'run-a5-test', scenario_id: 'A5', verdict: 'PASS' }]);
      return okJson(controlRun);
    }));
    render(<SessionContext.Provider value={ctx(northstar, 0)}><Replay /></SessionContext.Provider>);
    expect(await screen.findByText(/Positive-control evidence — available to experiment admin/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('CEDAR-CONTROL-MARKER');
    expect(document.body.textContent).not.toContain('INC-3307');
    expect(document.body.textContent).not.toContain('Positive control read allowed');
  });

  it('the incident_commander admin sees full control evidence', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).endsWith('/runs')) return okJson([{ id: 'run-a5-test', scenario_id: 'A5', verdict: 'PASS' }]);
      return okJson(controlRun);
    }));
    render(<SessionContext.Provider value={ctx(commander, 0)}><Replay /></SessionContext.Provider>);
    fireEvent.click(await screen.findByRole('button', { name: /Inspect sanitized event JSON/i }));
    expect(document.body.textContent).toContain('CEDAR-CONTROL-MARKER');
  });
});
