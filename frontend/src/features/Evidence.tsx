import { Fragment, useState } from 'react';
import { Copy } from 'lucide-react';
import { api } from '../lib/api';
import { useSession } from '../components/session';
import { AdapterBadge, DecisionBadge, EmptyState, ErrorBox, LlmBlock, Skeleton, TrustBadge, isControlOnly, useAsync, useSessionEpoch, TrialOutcomeBadge } from '../components/ui';
import { RunIdentities } from '../components/identities';
import type { Run } from '../lib/types';

const PAGE = 20;
const TOOLS = ['', 'get_alert', 'search_runbooks', 'read_case', 'draft_response', 'change_case_status', 'simulate_isolation'];
const DECISIONS = ['', 'ALLOW', 'DENY', 'APPROVAL_REQUIRED', 'ERROR', 'INFO'];

export default function Evidence() {
  const { push, sessionVersion, persona } = useSession();
  // N-04: full control-only evidence (including event args JSON) is visible
  // only to the experiment admin; other viewers get a reference line.
  const isAdmin = persona?.id === 'incident_commander';
  const epoch = useSessionEpoch();
  const [decision, setDecision] = useState('');
  const [tool, setTool] = useState('');
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runLookup, setRunLookup] = useState('');
  const [runDetail, setRunDetail] = useState<Run | null>(null);
  const [runLookupError, setRunLookupError] = useState<string | null>(null);
  const { data, error, loading, reload } = useAsync(
    () => api.events({ decision, tool, q, limit: PAGE, offset }),
    [decision, tool, q, offset, sessionVersion],
  );
  const loadRun = async () => {
    const v = epoch.current;
    setRunLookupError(null);
    setRunDetail(null);
    try {
      const r = await api.run(runLookup.trim());
      if (epoch.current !== v) return; // session changed — discard old-session run
      setRunDetail(r);
    } catch (e) { if (epoch.current === v) setRunLookupError(e instanceof Error ? e.message : 'Could not load run'); }
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); push('Sanitized event JSON copied.'); }
    catch { push('Clipboard unavailable in this browser context.', true); }
  };
  const total = data?.total ?? 0;
  return (
    <>
      <h1>Evidence / Event Explorer</h1>
      <p className="secondary">Structured audit events from stored runs. Search and filters run server-side; restricted tenant metadata is not exposed to unauthorized personas. Events shown are server-filtered to runs in the current lab session persona's tenants.</p>
      <section className="card" aria-label="Run identity lookup" style={{ marginBottom: 14 }}>
        <h2 style={{ marginTop: 0 }}>Run identities</h2>
        <p className="small muted">Look up a run to see who operated it versus whose authority was under test (F-02) — the two are never the same field.</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input type="text" value={runLookup} onChange={(e) => setRunLookup(e.target.value)} placeholder="run id, e.g. run-a2-…" aria-label="Run id to look up" />
          <button type="button" className="btn" disabled={!runLookup.trim()} onClick={loadRun}>Load run identities</button>
        </div>
        {runLookupError && <p className="badge salmon" role="alert" style={{ marginTop: 8 }}>{runLookupError}</p>}
        {runDetail && (
          <div style={{ marginTop: 10 }}>
            <p style={{ margin: 0 }}><span className="mono">{runDetail.id}</span> — Scenario {runDetail.scenario_id} · Verdict: {runDetail.verdict} <AdapterBadge adapter={runDetail.adapter} transport={runDetail.metrics.llm?.transport} /> <TrialOutcomeBadge outcome={runDetail.metrics.trial_outcome} /></p>
            <LlmBlock llm={runDetail.metrics.llm} />
            <RunIdentities run={runDetail} />
          </div>
        )}
      </section>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <label>Decision{' '}
          <select value={decision} onChange={(e) => { setDecision(e.target.value); setOffset(0); }} aria-label="Filter by decision">
            {DECISIONS.map((d) => <option key={d} value={d}>{d || 'All decisions'}</option>)}
          </select>
        </label>
        <label>Tool{' '}
          <select value={tool} onChange={(e) => { setTool(e.target.value); setOffset(0); }} aria-label="Filter by tool">
            {TOOLS.map((t) => <option key={t} value={t}>{t || 'All tools'}</option>)}
          </select>
        </label>
        <label>Search{' '}
          <input type="search" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="run, reason, detail…" aria-label="Search events" />
        </label>
      </div>
      {loading && <Skeleton />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.items.length === 0 && <EmptyState title="No events match"><p>Events appear after scenario runs execute.</p></EmptyState>}
      {data && data.items.length > 0 && (
        <>
          <div className="table-wrap card">
            <table>
              <thead><tr><th scope="col">Seq</th><th scope="col">Timestamp (UTC)</th><th scope="col">Run / Scenario</th><th scope="col">Tool</th><th scope="col">Decision</th><th scope="col">Reason</th><th scope="col">Trust</th><th scope="col">Actions</th></tr></thead>
              <tbody>
                {data.items.map((ev) => {
                  const controlOnly = isControlOnly(ev) && !isAdmin;
                  return (
                    <Fragment key={ev.event_id}>
                      <tr>
                        <td>{ev.seq}</td><td className="mono small">{ev.timestamp}</td>
                        <td className="mono small">{ev.run_id}<br />{ev.scenario_id}<br /><span className="small muted">{ev.adapter === 'real_llm' ? 'REAL LLM EVALUATION' : 'SCRIPTED LAB SIMULATION'}</span></td>
                        <td className="mono">{ev.tool ?? '—'}{ev.tool_call_id && <><br /><span className="small muted">Call: {ev.tool_call_id}</span></>}</td>
                        <td><DecisionBadge decision={ev.decision} /></td>
                        <td className="mono small">{ev.reason_code ?? '—'}</td>
                        <td><TrustBadge label={ev.trust_label} /></td>
                        <td>
                          {controlOnly ? (
                            <span className="small muted">Positive-control evidence — available to experiment admin</span>
                          ) : (
                            <>
                              <button type="button" className="btn small" aria-expanded={expanded === ev.event_id}
                                onClick={() => setExpanded(expanded === ev.event_id ? null : ev.event_id)}>
                                {expanded === ev.event_id ? 'Hide' : 'Expand'}
                              </button>{' '}
                              <button type="button" className="btn small" onClick={() => copy(JSON.stringify(ev, null, 2))}>
                                <Copy size={13} aria-hidden /> Copy JSON
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                      {!controlOnly && expanded === ev.event_id && (
                        <tr><td colSpan={8}><pre className="json mono" tabIndex={0} aria-label="Event JSON">{JSON.stringify(ev, null, 2)}</pre></td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12 }}>
            <button type="button" className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous page</button>
            <span className="small secondary">Showing {offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <button type="button" className="btn small" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next page</button>
          </p>
        </>
      )}
    </>
  );
}
