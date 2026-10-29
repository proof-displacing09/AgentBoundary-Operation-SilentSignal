import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import Overview from '../src/features/Overview';
import { trialOutcomeLabel } from '../src/lib/labels';

// S7-05: mocked API responses only — no network, no provider, no keys.

const populated = {
  scenarios_run: 3, total_runs: 4, attempted_unauthorized: 3, denied: 5,
  completed_forbidden: 0, tenant_leaks: 0, security_invariant_passes: 3,
  legitimate_workflow_completions: 1, model_legitimate_workflow_completions: 1,
  trial_outcomes: { OUT_OF_MISSION: 1, TARGETED_ATTACK_BLOCKED: 1 },
  legitimate_task_successes: 1, inconclusive: 1,
  targeted_forbidden_calls_blocked: 2, out_of_mission_runs: 1,
  post_injection_model_attack_attempts: 2, unexposed_proposals: 0,
  recent_runs: [{ id: 'run-a1-x', scenario_id: 'A1', verdict: 'INCONCLUSIVE' }],
  recent_cases: [],
};

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (String(url).includes('/api/v1/runs')
      ? []
      : String(url).includes('/comparisons')
        ? { protected_runs: [], weak_reports: [], comparable: false, notes: '' }
        : populated),
  })));
});

describe('S7-05: denial and post-exposure labels must not overstate what a metric proves', () => {
  it('labels denied as all denials and post-exposure counts as proposals, with a separate blocked count', async () => {
    const { container, findByText } = render(<Overview />);
    await findByText('Total runs');
    const text = container.textContent ?? '';
    expect(text).toContain('All tool calls denied by policy or validation');
    expect(text).toContain('Post-exposure forbidden proposals');
    expect(text).toContain('Targeted forbidden calls blocked');
    expect(text).toContain('Out-of-mission runs');
    expect(text).not.toContain('Prohibited calls blocked by the policy gate');
    expect(text).not.toContain('Post-exposure attacks blocked');
  });
});

describe('S7-01: the new trial outcome has a plain-language label', () => {
  it('names OUT_OF_MISSION as a clean-control deviation, not a bypass', () => {
    expect(trialOutcomeLabel('OUT_OF_MISSION')).toBe(
      'Out of mission (clean-control deviation)',
    );
  });
});
