import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { api } from '../lib/api';
import { useSession } from '../components/session';
import type { LabEvent } from '../lib/types';
import { AdapterBadge, DecisionBadge, EmptyState, ErrorBox, LlmBlock, Skeleton, TrustBadge, VerdictBadge, groupEvents, isControlOnlyGroup, useAsync, TrialOutcomeBadge } from '../components/ui';
import { RunIdentities } from '../components/identities';

function stageOf(ev: LabEvent, isLast: boolean): string {
  if (isLast && (ev.tool === null || ev.decision === 'INFO')) return 'Evaluator verdict / final narrative';
  if (ev.decision === 'APPROVAL_REQUIRED') return 'Authorization & approval gate';
  if (ev.decision === 'DENY') return 'Authorization — forbidden action stopped here';
  if (ev.decision === 'ALLOW' && ev.completed) return 'Executed tool (synthetic lab only)';
  if (ev.attempted) return 'Agent proposed action';
  if (ev.trust_label) return 'Retrieved source & provenance';
  return 'Trusted user request / validation';
}

export default function Replay({ runId }: { runId?: string }) {
  const { sessionVersion, persona } = useSession();
  // N-04: full control-only evidence is visible only to the experiment admin.
  const isAdmin = persona?.id === 'incident_commander';
  const runs = useAsync(() => api.runs(), [sessionVersion]);
  const [selected, setSelected] = useState(runId ?? '');
  const activeId = selected || runId || runs.data?.[0]?.id || '';
  const run = useAsync(() => (activeId ? api.run(activeId) : Promise.reject(new Error('No run selected'))), [activeId, sessionVersion]);
  const [step, setStep] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const events = useMemo(() => [...(run.data?.events ?? [])].sort((a, b) => a.seq - b.seq), [run.data]);
  // FA-01/FA-06: hoisted so TS narrowing survives the map callbacks below.
  const causalLedger = run.data?.metrics.causal_ledger ?? null;
  // N-08: one timeline node per LOGICAL tool call (tool_call_id groups the
  // ATTEMPT row and its terminal outcome together — never two calls).
  const groups = useMemo(() => groupEvents(events), [events]);
  const stoppedIdx = groups.findIndex((g) => {
    const t = g.terminal;
    return !!t && !t.completed && (t.decision === 'DENY' || t.decision === 'APPROVAL_REQUIRED');
  });
  const clamped = Math.min(step, Math.max(0, groups.length - 1));
  const current = groups[clamped];

  return (
    <>
      <h1>Interactive Agent Attack Replay</h1>
      <p className="secondary">Step through the <strong>stored</strong> event sequence of a real run. Nothing here is simulated playback — each node is a backend audit event.</p>
      <label>Run{' '}
        <select value={activeId} onChange={(e) => { setSelected(e.target.value); setStep(0); }} aria-label="Choose a run to replay">
          {(runs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.scenario_id} — {r.id} ({r.verdict}, {r.adapter === 'real_llm' ? 'REAL LLM' : 'scripted'})</option>)}
        </select>
      </label>
      {runs.data && runs.data.length === 0 && (
        <div style={{ marginTop: 14 }}><EmptyState title="No runs to replay yet"><p>Run a scenario first; its stored events will appear here.</p></EmptyState></div>
      )}
      {run.loading && activeId && <Skeleton />}
      {run.error && activeId && <ErrorBox error={run.error} onRetry={run.reload} />}
      {run.data && groups.length > 0 && (
        <section className="card" style={{ marginTop: 14 }} aria-label="Replay">
          <p>
            <VerdictBadge verdict={run.data.verdict} />{' '}
            <span className="badge">Mode: {run.data.mode}</span>{' '}
            <AdapterBadge adapter={run.data.adapter} transport={run.data.metrics.llm?.transport} /> <TrialOutcomeBadge outcome={run.data.metrics.trial_outcome} />
          </p>
          <LlmBlock llm={run.data.metrics.llm} />
          <RunIdentities run={run.data} />
          <p className="small secondary" aria-label="Exposure and attribution">
            Exposure: {run.data.metrics.exposure?.exposed ? <>payload reached the model (markers: <span className="mono">{(run.data.metrics.exposure.markers_seen ?? []).join(', ') || 'none listed'}</span>{run.data.metrics.exposure.first_exposure_tool ? <> via <span className="mono">{run.data.metrics.exposure.first_exposure_tool}</span></> : null})</> : 'no confirmed full attack payload reached the model in this trial'}
            {run.data.metrics.exposure?.exposure_state ? <> · Exposure state: {run.data.metrics.exposure.exposure_state}</> : null} ·{' '}
            Post-exposure forbidden proposals: {run.data.metrics.post_injection_model_attack_attempts ?? '—'} · Targeted forbidden calls blocked: {run.data.metrics.targeted_forbidden_calls_blocked ?? '—'} · Unexposed proposals: {run.data.metrics.unexposed_proposals ?? '—'} ·{' '}
            {(run.data.metrics.out_of_mission_actions?.length ?? 0) > 0 ? <>Out-of-mission actions (clean control violated, not a bypass): {(run.data.metrics.out_of_mission_actions ?? []).map((a) => `${a.tool}${a.new_status ? `→${a.new_status}` : ''}`).join(', ')} ·{' '}</> : null}
            {(run.data.metrics.discarded_proposals?.length ?? 0) > 0 ? <>Discarded proposals (never dispatched — cancel/budget): {(run.data.metrics.discarded_proposals ?? []).map((d) => `${d.tool} (${d.reason})`).join(', ')} ·{' '}</> : null}
            Harness control: {run.data.metrics.harness_control?.ran ? `ran, completed=${String(run.data.metrics.harness_control.completed)} (counted separately, never as model work)` : 'did not run in this trial'} ·{' '}
            Policy boundary held: {String(run.data.metrics.policy_boundary_held ?? '—')} · Experiment valid: {String(run.data.metrics.experiment_valid ?? '—')}
            {run.data.metrics.origin_counts ? <> · Call origins: scripted_agent {run.data.metrics.origin_counts.scripted_agent ?? 0}, real_model {run.data.metrics.origin_counts.real_model ?? 0}, harness_control {run.data.metrics.origin_counts.harness_control ?? 0}</> : null}
            {typeof run.data.metrics.harness_matched_proposals === 'number' ? <> · Harness-matched proposals: {run.data.metrics.harness_matched_proposals}</> : null}
            {typeof run.data.metrics.authorized_state_changes === 'number' && run.data.metrics.authorized_state_changes > 0 ? <> · Authorized state changes (not bypasses): {run.data.metrics.authorized_state_changes}</> : null}
          </p>
          {causalLedger ? (
            <section className="card" aria-label="Causal timeline" style={{ marginTop: 10 }}>
              <h2>Causal timeline (model responses, not dispatcher order)</h2>
              <p className="small secondary">
                A model response can only be caused by observations from an
                earlier response: every call in one response was proposed
                before any of that response's results existed. Exposure
                state: <strong>{causalLedger.exposure_state ?? run.data.metrics.exposure?.exposure_state ?? '—'}</strong>
                {causalLedger.confirmed_full_exposure_turn != null && <> — full payload first confirmed in the request behind model response {causalLedger.confirmed_full_exposure_turn}</>}.
                Only proposals from that response onward count as post-exposure.
              </p>
              <ol style={{ margin: 0, paddingLeft: 18 }}>
                {(causalLedger.batches ?? []).map((b) => (
                  <li key={b.batch_id ?? `turn-${b.proposal_turn}`} style={{ marginBottom: 6 }}>
                    <span className="mono">Model response {b.proposal_turn}</span> proposed: {(b.tools ?? []).join(', ') || '—'}
                    <ul style={{ margin: '4px 0 0 0', paddingLeft: 18 }}>
                      {(causalLedger?.delivered_observations ?? [])
                        .filter((d) => d.proposal_turn === b.proposal_turn)
                        .map((d, i) => (
                          <li key={`${d.tool}-${i}`} className="small muted">
                            {d.tool} observation — delivery: {d.delivery_state}
                            {d.confirmed_response_turn != null && <> (confirmed by model response {d.confirmed_response_turn})</>}
                            {d.truncated ? ' · truncated' : ''}
                            {d.markers && d.markers.length > 0 && <> · markers: {d.markers.join(', ')}</>}
                            {d.payload_coverage && Object.entries(d.payload_coverage).map(([m, c]) => (
                              <span key={m}> · payload {m}: {c.coverage}{c.payload_source ? ` (${c.payload_source})` : ''}</span>
                            ))}
                          </li>
                        ))}
                    </ul>
                  </li>
                ))}
              </ol>
              {run.data.metrics.draft_grounding_detail && (
                <p className="small secondary">
                  Draft grounding: {run.data.metrics.draft_grounding_detail.grounded ? 'grounded' : 'not grounded'}
                  {run.data.metrics.draft_grounding_detail.cited_source && <> — cited {run.data.metrics.draft_grounding_detail.cited_source} (confirmed in response {run.data.metrics.draft_grounding_detail.citation_confirmed_turn}, draft in response {run.data.metrics.draft_grounding_detail.draft_turn})</>}
                  {run.data.metrics.draft_grounding_detail.reasons && run.data.metrics.draft_grounding_detail.reasons.length > 0 && <> — reasons: {run.data.metrics.draft_grounding_detail.reasons.join(', ')}</>}
                </p>
              )}
            </section>
          ) : (
            <p className="small muted">Scripted run: proposals below are predetermined by the harness, not caused by model observations — dispatcher chronology here is execution order, not model reasoning.</p>
          )}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0' }}>
            <button type="button" className="btn small" disabled={clamped === 0} onClick={() => setStep(clamped - 1)}>
              <ChevronLeft size={15} aria-hidden /> Previous step
            </button>
            <span aria-live="polite">Step {clamped + 1} of {groups.length}</span>
            <button type="button" className="btn small" disabled={clamped >= groups.length - 1} onClick={() => setStep(clamped + 1)}>
              Next step <ChevronRight size={15} aria-hidden />
            </button>
          </div>
          <ol className="timeline">
            {groups.map((g, i) => {
              const ev = g.terminal ?? g.attempt ?? g.events[0]!;
              const controlOnly = isControlOnlyGroup(g) && !isAdmin;
              const firstSeq = g.events[0]?.seq;
              const lastSeq = g.events[g.events.length - 1]?.seq;
              return (
                <li key={g.key} className={i === stoppedIdx ? 'stopped' : undefined}
                  style={i === clamped ? { background: 'var(--raised)', borderRadius: 8, paddingLeft: 22 } : undefined}>
                  <div className="small muted">
                    #{firstSeq}{lastSeq !== firstSeq ? `–${lastSeq}` : ''} · {ev.timestamp} · {stageOf(ev, i === groups.length - 1)}
                    {g.events.length > 1 && ' · Logical tool call — ATTEMPT + terminal outcome together'}
                    {g.tool_call_id && <> · <span className="mono">Tool call: {g.tool_call_id}</span></>}
                  </div>
                  {controlOnly ? (
                    <div>
                      <span className="mono">{ev.tool ?? '—'}</span>{' '}
                      <span className="small muted">Positive-control evidence — available to experiment admin</span>
                    </div>
                  ) : (
                    <div>
                      <span className="mono">{ev.tool ?? '—'}</span> {ev.detail ?? ''}
                      {i === stoppedIdx && <strong> — forbidden action was stopped at this node.</strong>}
                    </div>
                  )}
                  <p style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                    <DecisionBadge decision={ev.decision} />
                    {!controlOnly && <TrustBadge label={ev.trust_label} />}
                    <span className="badge">Reason: {ev.reason_code ?? '—'}</span>
                    <span className="badge">Attempted: {g.attempt || ev.attempted ? 'yes' : 'no'} · Completed: {ev.completed ? 'yes' : 'no'}</span>
                    {!controlOnly && (
                      <button type="button" className="btn small" aria-expanded={expanded === g.key}
                        onClick={() => setExpanded(expanded === g.key ? null : g.key)}>
                        {expanded === g.key ? 'Hide' : 'Inspect'} sanitized event JSON
                      </button>
                    )}
                  </p>
                  {!controlOnly && expanded === g.key && <pre className="json mono" tabIndex={0} aria-label="Sanitized event JSON">{JSON.stringify(g.events, null, 2)}</pre>}
                </li>
              );
            })}
          </ol>
          {current && <p className="small muted">Current step: {current.tool_call_id ? `tool call ${current.tool_call_id}` : `#${current.events[0]?.seq}`} — {stageOf(current.terminal ?? current.events[0]!, clamped === groups.length - 1)}</p>}
        </section>
      )}
    </>
  );
}
