import { useState } from 'react';
import { Play } from 'lucide-react';
import { api } from '../lib/api';
import type { LabEvent, Run } from '../lib/types';
import { useSession } from '../components/session';
import { AdapterBadge, DecisionBadge, EmptyState, ErrorBox, LlmBlock, Skeleton, TrustBadge, VerdictBadge, useAsync, useSessionEpoch, TrialOutcomeBadge } from '../components/ui';

export default function Investigation() {
  const { sessionVersion, push } = useSession();
  const epoch = useSessionEpoch();
  const cases = useAsync(() => api.cases(), [sessionVersion]);
  const [selected, setSelected] = useState('INC-2048');
  const detail = useAsync(() => api.caseById(selected), [selected, sessionVersion]);
  const [run, setRun] = useState<Run | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const runA1 = async () => {
    const v = epoch.current;
    setRunning(true); setRunError(null);
    try {
      const r = await api.createRun('A1');
      if (epoch.current !== v) return; // session changed — discard old-session run
      setRun(r);
      push(`Scenario A1 finished with verdict ${r.verdict}.`);
    } catch (e) {
      if (epoch.current !== v) return;
      const msg = e instanceof Error ? e.message : 'Run failed';
      setRunError(msg); push(msg, true);
    } finally { if (epoch.current === v) setRunning(false); }
  };

  const timeline = detail.data?.timeline ?? detail.data?.events ?? [];
  return (
    <>
      <h1>SOC Investigation Workspace</h1>
      <p className="secondary">Investigate a synthetic case inside your trusted tenant scope. Lower-trust fields are badged — they are data, never instructions.</p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <label>Case{' '}
          <select value={selected} onChange={(e) => setSelected(e.target.value)} aria-label="Choose a case">
            {(cases.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.id} — {c.title}</option>)}
            {(cases.data ?? []).every((c) => c.id !== 'INC-2048') && <option value="INC-2048">INC-2048</option>}
          </select>
        </label>
        <button type="button" className="btn primary" onClick={runA1} disabled={running}>
          <Play size={16} aria-hidden /> {running ? 'Running A1…' : 'Run A1 — legitimate investigation'}
        </button>
      </div>
      {cases.error && <ErrorBox error={cases.error} onRetry={cases.reload} />}
      <div className="split">
        <section className="card" aria-label="Case evidence">
          <h2>Case evidence</h2>
          {detail.loading && <Skeleton />}
          {detail.error && <ErrorBox error={detail.error} onRetry={detail.reload} />}
          {detail.data && (
            <>
              <p><span className="mono">{detail.data.id}</span> · Tenant <span className="mono">{detail.data.tenant_id}</span></p>
              <p>{detail.data.title}</p>
              <p>
                <span className="badge">Status: {detail.data.status}</span>{' '}
                {(detail.data.severity ?? detail.data.priority) && <span className="badge amber">Severity: {detail.data.severity ?? detail.data.priority}</span>}
              </p>
              {detail.data.summary && <p className="secondary">{detail.data.summary}</p>}
              <h3>Timeline</h3>
              {timeline.length === 0 ? <p className="muted">No timeline events returned for this case.</p> : (
                <ol className="timeline">
                  {timeline.map((ev, i) => (
                    <li key={String(ev.id ?? i)}>
                      <div className="small muted">{ev.timestamp} · {ev.source_type ?? 'event'}</div>
                      <div>{ev.text ?? ev.content ?? ev.title ?? 'Event'}</div>
                      <TrustBadge label={ev.trust_label ?? ev.classification ?? null} />
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </section>
        <section className="card" aria-label="Copilot investigation trace">
          <h2>Copilot investigation trace</h2>
          {runError && <p className="badge salmon" role="alert">Run error: {runError}</p>}
          {!run && !runError && (
            <EmptyState title="No investigation run yet in this view">
              <p>Run A1 to execute the scripted investigation end-to-end and see the real tool trace here.</p>
            </EmptyState>
          )}
          {run && (
            <>
              <p><VerdictBadge verdict={run.verdict} /> <AdapterBadge adapter={run.adapter} transport={run.metrics.llm?.transport} /> <TrialOutcomeBadge outcome={run.metrics.trial_outcome} /> <span className="mono small">{run.id}</span></p>
              <LlmBlock llm={run.metrics.llm} />
              <p className="small secondary">
                Attempted unauthorized: {run.metrics.attempted_unauthorized} · Denied: {run.metrics.denied} ·
                Completed forbidden: {run.metrics.completed_forbidden}
                {run.metrics.legitimate_workflow_completed !== undefined && <> · Legitimate workflow completed: {run.metrics.legitimate_workflow_completed ? 'yes' : 'no'}</>}
                {(run.metrics.out_of_mission_actions?.length ?? 0) > 0 && <> · Out-of-mission actions: {(run.metrics.out_of_mission_actions ?? []).map((a) => `${a.tool}${a.new_status ? `→${a.new_status}` : ''}`).join(', ')}</>}
              </p>
              <ol className="timeline">
                {run.events.map((ev: LabEvent) => (
                  <li key={ev.event_id} className={ev.attempted && !ev.completed && ev.decision !== 'ALLOW' ? 'stopped' : undefined}>
                    <div className="small muted">#{ev.seq} · {ev.timestamp}</div>
                    <div><span className="mono">{ev.tool ?? 'narrative'}</span> — {ev.detail ?? ev.reason_code ?? ''}</div>
                    <DecisionBadge decision={ev.decision} /> <TrustBadge label={ev.trust_label} />
                  </li>
                ))}
              </ol>
              <p className="small muted">Approval-required response actions are simulation-only. Unauthorized execution is blocked by the backend policy gate, not by this page.</p>
            </>
          )}
        </section>
      </div>
    </>
  );
}
