import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import Overview from '../src/features/Overview';
import { DecisionBadge, VerdictBadge } from '../src/components/ui';
import { RunIdentities } from '../src/components/identities';

// Overview empty state + honest counts come from the real /overview payload shape.
const emptyOverview = {
  scenarios_run: 0, total_runs: 0, attempted_unauthorized: 0, denied: 0,
  completed_forbidden: 0, tenant_leaks: 0, legitimate_task_successes: 0,
  inconclusive: 0, recent_runs: [], recent_cases: [],
};

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (String(url).includes('/overview') ? emptyOverview
      : { protected_runs: [], weak_reports: [], comparable: false, notes: '' }),
  })));
});

describe('Overview empty state', () => {
  it('shows the honest empty state and CTA when total_runs is 0', async () => {
    render(<Overview />);
    expect(await screen.findByText(/No scenarios have been run yet/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Run first protected scenario/i })).toBeInTheDocument();
  });
});

describe('FA-08 Overview shows six primary KPIs plus research detail', () => {
  it('renders primary KPIs up front and keeps secondary metrics in a disclosure', async () => {
    const populated = {
      scenarios_run: 2, total_runs: 3, attempted_unauthorized: 2, denied: 2,
      completed_forbidden: 0, tenant_leaks: 0, security_invariant_passes: 3,
      legitimate_workflow_completions: 1, model_legitimate_workflow_completions: 1,
      trial_outcomes: { TARGETED_ATTACK_BLOCKED: 1 },
      legitimate_task_successes: 1, inconclusive: 0,
      recent_runs: [{ id: 'run-a1-x', scenario_id: 'A1', verdict: 'PASS' }],
      recent_cases: [],
    };
    const runs = [{
      id: 'run-a1-x', scenario_id: 'A1', verdict: 'PASS', adapter: 'scripted',
      metrics: { attempted_unauthorized: 0, completed_forbidden: 0, denied: 0, disclosed_restricted: false, legitimate_task_success: true },
    }];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (String(url).includes('/api/v1/runs') ? runs
        : String(url).includes('/comparisons') ? { protected_runs: [], weak_reports: [], comparable: false, notes: '' }
        : populated),
    })));
    const { container } = render(<Overview />);
    expect(await screen.findByText('Total runs')).toBeInTheDocument();
    expect(screen.getByText('Completed forbidden')).toBeInTheDocument();
    expect(screen.getByText('Legitimate workflow completions')).toBeInTheDocument();
    // Secondary metrics stay in the DOM inside the disclosure, not as
    // headline tiles: the disclosure element and its content exist.
    expect(container.querySelector('details')).not.toBeNull();
    expect(screen.getByText(/Research metrics \(full detail/)).toBeInTheDocument();
    expect(container.textContent).toContain('Legitimate task successes (legacy)');
    expect(container.textContent).toContain('Security invariant passes');
  });
});

describe('F-02 run identities are never conflated', () => {
  it('shows operator and simulated actor as separate labeled lines, plus the A5 control actor', () => {
    render(<RunIdentities run={{ operator_persona_id: 'analyst_cedar', simulated_actor_id: 'analyst_northstar', control_actor_id: 'analyst_cedar' }} />);
    expect(screen.getByText(/Operator \(logged-in lab session\): analyst_cedar/)).toBeInTheDocument();
    expect(screen.getByText(/Simulated actor \(authority under test\): analyst_northstar/)).toBeInTheDocument();
    expect(screen.getByText(/Positive-control actor: analyst_cedar/)).toBeInTheDocument();
  });
  it('states plainly when a pre-remediation run has no recorded operator', () => {
    render(<RunIdentities run={{ actor_id: 'analyst_northstar' }} />);
    expect(screen.getByText(/not recorded — run created before identity separation/)).toBeInTheDocument();
    expect(screen.getByText(/Simulated actor \(authority under test\): analyst_northstar/)).toBeInTheDocument();
  });
  it('never claims "not recorded" for a summary projection that simply omits identities', () => {
    render(<RunIdentities run={{}} />);
    expect(screen.queryByText(/not recorded/)).not.toBeInTheDocument();
    expect(screen.getByText(/Identities not included in this summary/)).toBeInTheDocument();
  });
});

describe('Badges pair color with text labels', () => {
  it('verdict badge includes the word Verdict and the value', () => {
    render(<VerdictBadge verdict="PASS" />);
    expect(screen.getByText('Verdict: PASS')).toBeInTheDocument();
  });
  it('decision badge includes the word Decision and the value', () => {
    render(<DecisionBadge decision="DENY" />);
    expect(screen.getByText('Decision: DENY')).toBeInTheDocument();
  });
});
