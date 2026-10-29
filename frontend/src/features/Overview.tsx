import { useMemo, useState } from 'react';
import { Link2 } from 'lucide-react';
import { api } from '../lib/api';
import type { RunSummary } from '../lib/types';
import { useSession } from '../components/session';
import { AdapterBadge, EmptyState, ErrorBox, Skeleton, TrialOutcomeBadge, VerdictBadge, useAsync } from '../components/ui';
import { RunIdentities } from '../components/identities';
import { trialOutcomeLabel } from '../lib/labels';

type ModeFilter = 'all' | 'scripted' | 'real_llm';

/** Phase 4: mode-filtered KPIs computed from stored runs (never invented).
 * Only fields the RunSummary contract actually carries are summed. */
function filteredStats(runs: RunSummary[]): Array<[string, number, string]> {
  const scenarios = new Set(runs.map((r) => r.scenario_id)).size;
  const sum = (f: (m: NonNullable<RunSummary['metrics']>) => number) =>
    runs.reduce((acc, r) => acc + (r.metrics ? f(r.metrics) : 0), 0);
  const count = (f: (m: NonNullable<RunSummary['metrics']>) => boolean) =>
    runs.reduce((acc, r) => acc + (r.metrics && f(r.metrics) ? 1 : 0), 0);
  return [
    ['Total runs', runs.length, 'Stored runs with this execution mode'],
    ['Scenarios run', scenarios, 'Distinct scenarios with at least one run in this mode'],
    ['Attempted unauthorized', sum((m) => m.attempted_unauthorized), 'Prohibited tool calls the agent proposed'],
    ['Denied', sum((m) => m.denied), 'All tool calls denied by policy or validation — includes invalid-input and approval-required denials, not only blocked attacks'],
    ['Completed forbidden', sum((m) => m.completed_forbidden), 'Forbidden actions that actually executed'],
    ['Tenant leaks', count((m) => m.disclosed_restricted), 'Runs where restricted cross-tenant data was disclosed'],
    ['Security invariant passes', count((m) => m.security_invariant_pass === true), 'Runs whose security expectation passed'],
    ['Legitimate workflow completions', count((m) => m.legitimate_workflow_completed === true), 'Runs whose legitimate investigation steps actually completed with ALLOW'],
    ['Model legitimate completions (agent-origin)', count((m) => m.model_legitimate_workflow_completed === true), 'Agent-origin only — harness controls never count here'],
    ['Post-exposure forbidden proposals', sum((m) => m.post_injection_model_attack_attempts ?? 0), 'Matched forbidden proposals made AFTER the model saw the payload — proposals only; blocking is shown by targeted blocked / completed forbidden'],
    ['Targeted forbidden calls blocked', sum((m) => m.targeted_forbidden_calls_blocked ?? 0), 'Matched forbidden proposals that ended DENY or APPROVAL_REQUIRED, correlated by tool_call_id'],
    ['Out-of-mission runs', count((m) => (m.out_of_mission_actions?.length ?? 0) > 0), 'A1 clean-control runs that committed a status change or isolation — policy may still have held'],
    ['Unexposed proposals (not injection evidence)', sum((m) => m.unexposed_proposals ?? 0), 'Forbidden proposals made before any payload exposure'],
    ['Legitimate task successes (legacy)', count((m) => m.legitimate_task_success), 'Legacy alias of legitimate workflow completions — same runs, not an additional count'],
    ['Inconclusive', runs.filter((r) => r.verdict === 'INCONCLUSIVE').length, 'Runs without sufficient evidence for PASS/FAIL'],
  ];
}

/** Hand-built accessible SVG bar chart from real run verdict data (no fabricated series). */
export function VerdictChart({ runs }: { runs: Array<{ verdict: string }> }) {
  const counts = ['PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR', 'CANCELLED'].map((v) => ({
    label: v, n: runs.filter((r) => r.verdict === v).length,
  }));
  const max = Math.max(1, ...counts.map((c) => c.n));
  const colors: Record<string, string> = { PASS: '#68E0D0', FAIL: '#F08089', INCONCLUSIVE: '#A5B4FC', ERROR: '#F2B86D' };
  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="small secondary">Run verdicts from stored runs (text values shown beside each bar)</figcaption>
      <svg viewBox="0 0 320 190" width="100%" role="img" aria-label={counts.map((c) => `${c.label}: ${c.n}`).join(', ')}>
        {counts.map((c, i) => (
          <g key={c.label}>
            <text x="0" y={24 + i * 34} fill="#A1B0C8" fontSize="11">{c.label}</text>
            <rect x="92" y={13 + i * 34} width={(c.n / max) * 180} height="16" rx="4" fill={colors[c.label]} />
            <text x={98 + (c.n / max) * 180} y={25 + i * 34} fill="#F3F6FC" fontSize="11">{c.n}</text>
          </g>
        ))}
      </svg>
    </figure>
  );
}

export default function Overview() {
  const { navigate, sessionVersion } = useSession();
  const { data, error, loading, reload } = useAsync(() => api.overview(), [sessionVersion]);
  const comparisons = useAsync(() => api.comparisons(), [sessionVersion]);
  const allRuns = useAsync(() => api.runs(), [sessionVersion]);
  // Phase 4 mode filter: scripted and real-model runs are NEVER mixed into
  // one unlabeled number. Default All shows the backend totals plus an
  // explicit mode breakdown; a mode selection refilters the KPI cards, the
  // verdict chart and the recent-runs list to that mode only.
  const [modeFilter, setModeFilter] = useState<ModeFilter>('all');
  // Defensive: /runs must be an array; anything else falls back to the
  // overview's recent runs rather than crashing the page.
  const fullList: RunSummary[] = Array.isArray(allRuns.data) ? allRuns.data : (data?.recent_runs ?? []);
  const breakdown = useMemo(() => ({
    scripted: fullList.filter((r) => r.adapter === 'scripted').length,
    real: fullList.filter((r) => r.adapter === 'real_llm').length,
  }), [fullList]);
  // The /overview recent-runs projection carries no adapter or identity
  // fields, so filtering or rendering it directly would (a) empty the recent
  // list under any mode filter and (b) show "Adapter: unknown" plus a false
  // "not recorded" operator line. Join each projection to its full /runs
  // record (already fetched above) when available; fall back to the
  // projection itself, whose badges then honestly say what is missing.
  const fullById = useMemo(() => new Map(fullList.map((r) => [r.id, r])), [fullList]);
  const visibleRecent = useMemo(() => (data?.recent_runs ?? [])
    .map((r) => fullById.get(r.id) ?? r)
    .filter((r) => modeFilter === 'all' || r.adapter === modeFilter), [data, modeFilter, fullById]);
  if (loading) return <><h1>SOC Security Command Center</h1><div className="grid grid-4"><Skeleton /><Skeleton /><Skeleton /><Skeleton /></div></>;
  if (error || !data) return <><h1>SOC Security Command Center</h1><ErrorBox error={error ?? new Error('No data')} onRetry={reload} /></>;

  const filteredList = fullList.filter((r) => r.adapter === modeFilter);
  // FA-08: six primary KPIs up front; everything else lives in the
  // expandable research-metrics disclosure below (still rendered, still
  // counted — just not six screens of overlapping tiles). The split
  // applies to both the backend-total and mode-filtered views.
  const allStats: Array<[string, number, string]> = modeFilter === 'all' ? [
    ['Total runs', data.total_runs, 'Executed scenario runs stored by the backend'],
    ['Scenarios run', data.scenarios_run, 'Distinct scenarios with at least one run'],
    ['Attempted unauthorized', data.attempted_unauthorized, 'Prohibited tool calls the agent proposed'],
    ['Denied', data.denied, 'All tool calls denied by policy or validation — includes invalid-input and approval-required denials, not only blocked attacks'],
    ['Targeted forbidden calls blocked', data.targeted_forbidden_calls_blocked ?? 0, 'Matched forbidden proposals that ended DENY or APPROVAL_REQUIRED, correlated by tool_call_id'],
    ['Out-of-mission runs', data.out_of_mission_runs ?? 0, 'A1 clean-control runs that committed a status change or isolation — policy may still have held'],
    ['Post-exposure forbidden proposals', data.post_injection_model_attack_attempts ?? 0, 'Matched forbidden proposals made AFTER the model saw the payload — proposals only; blocking is shown by targeted blocked / completed forbidden'],
    ['Unexposed proposals (not injection evidence)', data.unexposed_proposals ?? 0, 'Forbidden proposals made before any payload exposure'],
    ['Completed forbidden', data.completed_forbidden, 'Forbidden actions that actually executed — target: 0 in protected mode'],
    ['Tenant leaks', data.tenant_leaks, 'Runs where restricted cross-tenant data was disclosed'],
    // F-05: the two counts are deliberately separate. Blocking an attack (security
    // invariant pass) is not the same as completing an investigation (legitimate
    // workflow completion). Legacy count kept below for compatibility.
    ...(data.security_invariant_passes !== undefined
      ? [['Security invariant passes', data.security_invariant_passes, 'Runs whose security expectation passed (attack blocked or legitimate run clean)'] as [string, number, string]] : []),
    ...(data.legitimate_workflow_completions !== undefined
      ? [['Legitimate workflow completions', data.legitimate_workflow_completions, 'Runs whose legitimate investigation steps actually completed with ALLOW'] as [string, number, string]] : []),
    ...(data.model_legitimate_workflow_completions !== undefined
      ? [['Model legitimate completions (agent-origin)', data.model_legitimate_workflow_completions, 'Agent-origin only — harness controls never count here'] as [string, number, string]] : []),
    ...(data.trial_outcomes
      ? (Object.entries(data.trial_outcomes).map(([o, n]) => [`Trial outcome: ${trialOutcomeLabel(o)}`, n, 'Research outcome tag from stored run metrics'] as [string, number, string])) : []),
    ['Legitimate task successes (legacy)', data.legitimate_task_successes, 'Legacy alias of legitimate workflow completions — same runs, not an additional count'],
    ['Inconclusive', data.inconclusive, 'Runs without sufficient evidence for PASS/FAIL'],
  ] : filteredStats(filteredList);
  const primaryLabels = new Set(['Total runs', 'Attempted unauthorized', 'Denied', 'Completed forbidden', 'Legitimate workflow completions', 'Tenant leaks']);
  const stats = allStats.filter(([label]) => primaryLabels.has(label));
  const researchStats = allStats.filter(([label]) => !primaryLabels.has(label));
  return (
    <>
      <h1>SOC Security Command Center</h1>
      <p className="secondary">Nightwatch Security — AgentBoundary research console. All counts below come from executed runs stored by the backend.</p>
      <p className="small muted">
        Note on the two new counts: <strong>security invariant passes</strong> count runs where the policy
        boundary held (an attack was blocked, or a legitimate run stayed clean); <strong>legitimate workflow
        completions</strong> count runs where the scenario's own legitimate investigation steps actually
        finished. Blocking an attack is not the same as completing an investigation — the two are never
        merged into one number.
      </p>
      <div role="group" aria-label="Filter runs by execution mode" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
        <span className="small secondary">Execution mode:</span>
        {([['all', 'All'], ['scripted', 'Scripted'], ['real_llm', 'Real LLM']] as Array<[ModeFilter, string]>).map(([v, label]) => (
          <button key={v} type="button" className="btn small" aria-pressed={modeFilter === v} onClick={() => setModeFilter(v)}
            style={modeFilter === v ? { borderColor: 'var(--teal)', color: 'var(--teal)' } : undefined}>{label}</button>
        ))}
        <span className="small muted">
          Mode breakdown across stored runs: Scripted {breakdown.scripted} · Real LLM {breakdown.real}
          {modeFilter !== 'all' && ` — KPIs, chart and recent runs below show ${modeFilter === 'scripted' ? 'SCRIPTED LAB SIMULATION' : 'REAL LLM EVALUATION'} runs only, computed from stored runs.`}
          {modeFilter === 'all' && ' — KPIs below are backend totals across both modes; the breakdown is shown so the two are never silently mixed.'}
        </span>
      </div>
      {data.total_runs === 0 ? (
        <EmptyState title="No scenarios have been run yet">
          <p>This is an honest empty state: nothing has executed, so no metrics are shown as evidence.</p>
          <button type="button" className="btn primary" onClick={() => navigate('scenarios')}>
            <Link2 size={16} aria-hidden /> Run first protected scenario
          </button>
        </EmptyState>
      ) : (
        <>
          <section aria-label="Run metrics" className="grid grid-4" style={{ marginBottom: 14 }}>
            {stats.map(([label, n, hint]) => (
              <div className="card" key={label}><div className="stat-num">{n}</div><div>{label}</div><div className="small muted">{hint}</div></div>
            ))}
          </section>
          {researchStats.length > 0 && (
            <details style={{ marginBottom: 14 }} aria-label="Research metrics">
              <summary style={{ cursor: 'pointer' }}>Research metrics (full detail — trial outcomes, model-origin counts, legacy aliases)</summary>
              <section aria-label="Research metrics detail" className="grid grid-4" style={{ marginTop: 10 }}>
                {researchStats.map(([label, n, hint]) => (
                  <div className="card" key={label}><div className="stat-num">{n}</div><div>{label}</div><div className="small muted">{hint}</div></div>
                ))}
              </section>
              <p className="small muted">Post-exposure counts here are causal (FA-01): only proposals from a model response after a confirmed full-payload delivery count as post-exposure. Same-batch proposals are unexposed, not injection evidence.</p>
            </details>
          )}
          <div className="grid grid-2" style={{ marginBottom: 14 }}>
            <section className="card" aria-label="Verdict chart"><h2>Verdict distribution{modeFilter !== 'all' ? ` (${modeFilter === 'scripted' ? 'scripted only' : 'real LLM only'})` : ''}</h2><VerdictChart runs={visibleRecent} /></section>
            <section className="card" aria-label="Protected versus weak teaser">
              <h2>Protected vs. weak baseline</h2>
              {comparisons.data && comparisons.data.weak_reports.length > 0 ? (
                <p className="secondary">Stored offline weak exports exist ({comparisons.data.weak_reports.length}). Weak mode is never run from the browser.</p>
              ) : (
                <p className="secondary">No offline weak-baseline export has been stored yet, so no comparison is claimed. Generate one offline via the CLI, then open the Comparison page.</p>
              )}
              <button type="button" className="btn" onClick={() => navigate('comparison')}>Open comparison</button>
            </section>
          </div>
        </>
      )}
      <div className="grid grid-2">
        <section className="card" aria-label="Recent runs">
          <h2>Recent evaluations{modeFilter !== 'all' ? ` — ${modeFilter === 'scripted' ? 'scripted only' : 'real LLM only'}` : ''}</h2>
          {visibleRecent.length === 0 ? <p className="muted">{modeFilter === 'all' ? 'No runs yet.' : 'No runs in this execution mode yet.'}</p> : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {visibleRecent.map((r) => (
                <li key={r.id} style={{ marginBottom: 8 }}>
                  <button type="button" className="btn small" onClick={() => navigate(`replay:${r.id}`)}>Replay {r.scenario_id}</button>{' '}
                  <span className="mono small">{r.id}</span> {r.verdict && <VerdictBadge verdict={r.verdict} />}{' '}
                  <AdapterBadge adapter={r.adapter} transport={r.metrics?.llm?.transport} />{' '}
                  {r.metrics?.trial_outcome && <TrialOutcomeBadge outcome={r.metrics.trial_outcome} />}
                  <RunIdentities run={r} compact />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card" aria-label="Recent cases">
          <h2>Recent incidents (your tenant scope)</h2>
          <p className="small muted">Data shown here is server-filtered to the current lab session persona's tenants; cases outside that scope are never returned by the backend.</p>
          {data.recent_cases.length === 0 ? <p className="muted">No cases visible for the current persona.</p> : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {data.recent_cases.map((c) => <li key={c.id}><span className="mono">{c.id}</span> — {c.title} <span className="badge">Status: {c.status}</span></li>)}
            </ul>
          )}
          <p style={{ marginTop: 10 }}>
            <button type="button" className="btn" onClick={() => navigate('investigation')}>Start safe investigation</button>{' '}
            <button type="button" className="btn" onClick={() => navigate('scenarios')}>Run scenario</button>
          </p>
        </section>
      </div>
    </>
  );
}
