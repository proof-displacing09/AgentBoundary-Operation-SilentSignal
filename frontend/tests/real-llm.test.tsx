import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import Scenarios from '../src/features/Scenarios';
import Overview from '../src/features/Overview';
import { AdapterBadge, LlmBlock } from '../src/components/ui';
import { api } from '../src/lib/api';

// Phase 4: mocked API responses only — no network, no provider, no keys.

const scenarioList = [
  { id: 'A1', title: 'Legitimate investigation', description: 'Clean control run' },
  { id: 'A2', title: 'Poisoned telemetry', description: 'Log injection close attempt' },
];

const scriptedRun = {
  id: 'run-a1-scripted', scenario_id: 'A1', verdict: 'PASS', adapter: 'scripted', mode: 'protected',
  metrics: { attempted_unauthorized: 0, completed_forbidden: 0, denied: 0, disclosed_restricted: false,
    legitimate_task_success: true, security_invariant_pass: true, legitimate_workflow_completed: true },
};
const realRun = {
  id: 'run-a2-real', scenario_id: 'A2', verdict: 'PASS', adapter: 'real_llm', mode: 'protected',
  metrics: { attempted_unauthorized: 1, completed_forbidden: 0, denied: 1, disclosed_restricted: false,
    legitimate_task_success: false, security_invariant_pass: true, legitimate_workflow_completed: false,
    llm: { provider_base_url_host: 'api.example.com', model: 'gpt-4o-mini', outcome: 'completed',
      error_class: null, model_calls: 3, tool_calls_made: 3 } },
};

const overviewPayload = {
  scenarios_run: 2, total_runs: 2, attempted_unauthorized: 1, denied: 1,
  completed_forbidden: 0, tenant_leaks: 0, legitimate_task_successes: 1,
  security_invariant_passes: 2, legitimate_workflow_completions: 1, inconclusive: 0,
  recent_runs: [scriptedRun, realRun], recent_cases: [],
};

function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => ({
    ok: true, status: 200, json: async () => handler(url, init),
  }));
}

describe('Phase 4: real-LLM experiment path in Scenario Studio', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', stubFetch((url) => {
      if (url.includes('/settings')) return { real_model_configured: false, real_llm_model: null, real_llm_base_url_host: null };
      if (url.includes('/scenarios')) return scenarioList;
      return {};
    }));
  });

  it('disables the real-LLM button and states NOT RUN when the provider is unconfigured', async () => {
    render(<Scenarios />);
    // Cards render once the scenario list resolves.
    expect(await screen.findByText('Legitimate investigation')).toBeInTheDocument();
    const buttons = screen.getAllByRole('button', { name: /Run REAL LLM evaluation/i });
    expect(buttons.length).toBeGreaterThan(0);
    buttons.forEach((b) => expect(b).toBeDisabled());
    // Plain-language not-configured copy; nothing here may claim a run happened.
    expect(screen.getAllByText(/live real-model evaluation is NOT RUN/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/never entered here/i).length).toBeGreaterThan(0);
    // The scripted path stays available and separate.
    expect(screen.getAllByRole('button', { name: /Run protected scenario/i }).length).toBeGreaterThan(0);
  });

  it('never sends a scripted run through the real-LLM control (no POST on disabled click)', async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    render(<Scenarios />);
    expect(await screen.findByText('Legitimate investigation')).toBeInTheDocument();
    const before = fetchMock.mock.calls.length;
    const realButton = screen.getAllByRole('button', { name: /Run REAL LLM evaluation/i })[0]!;
    fireEvent.click(realButton);
    const posts = fetchMock.mock.calls.slice(before).filter((c) => (c[1] as RequestInit | undefined)?.method === 'POST');
    expect(posts).toHaveLength(0);
  });
});

describe('Phase 4: adapter badges and LLM metadata', () => {
  it('labels scripted and real runs with distinct explicit badges', () => {
    const { rerender } = render(<AdapterBadge adapter="scripted" />);
    expect(screen.getByText('SCRIPTED LAB SIMULATION')).toBeInTheDocument();
    rerender(<AdapterBadge adapter="real_llm" />);
    expect(screen.getByText('REAL LLM EVALUATION')).toBeInTheDocument();
    expect(screen.queryByText('SCRIPTED LAB SIMULATION')).not.toBeInTheDocument();
  });

  it('shows host-only provider metadata and never key material', () => {
    render(<LlmBlock llm={realRun.metrics.llm} />);
    expect(screen.getByText(/api\.example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/gpt-4o-mini/)).toBeInTheDocument();
    expect(screen.getByText(/completed/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sk-[A-Za-z0-9]/);
  });
});

describe('Phase 4: createRun adapter parameter', () => {
  it('omits adapter for scripted runs and sends real_llm only when explicitly requested', async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal('fetch', stubFetch((_url, init) => {
      bodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      return { id: 'run-x', scenario_id: 'A1', verdict: 'PASS', adapter: 'scripted', metrics: {} };
    }));
    await api.createRun('A1');
    await api.createRun('A2', 'real_llm');
    expect(bodies[0]).toEqual({ scenario_id: 'A1' });
    expect(bodies[1]).toEqual({ scenario_id: 'A2', adapter: 'real_llm' });
  });
});

describe('Phase 4: Overview mode filter', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', stubFetch((url) => {
      if (url.includes('/overview')) return overviewPayload;
      if (url.includes('/runs')) return [scriptedRun, realRun];
      if (url.includes('/comparisons')) return { protected_runs: [], weak_reports: [], pairs: [], comparable: false, notes: '' };
      return {};
    }));
  });

  it('shows both modes by default and refilters the run list when a mode is picked', async () => {
    render(<Overview />);
    expect(await screen.findByText('run-a1-scripted')).toBeInTheDocument();
    expect(screen.getByText('run-a2-real')).toBeInTheDocument();
    // Mode breakdown is visible on the default All view.
    expect(screen.getByText(/Mode breakdown across stored runs/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Real LLM' }));
    expect(screen.getByText('run-a2-real')).toBeInTheDocument();
    expect(screen.queryByText('run-a1-scripted')).not.toBeInTheDocument();
    expect(screen.getByText(/REAL LLM EVALUATION runs only/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Scripted' }));
    expect(screen.getByText('run-a1-scripted')).toBeInTheDocument();
    expect(screen.queryByText('run-a2-real')).not.toBeInTheDocument();
  });
});
