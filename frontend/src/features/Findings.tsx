import { api } from '../lib/api';
import { useSession } from '../components/session';
import { EmptyState, ErrorBox, Skeleton, useAsync } from '../components/ui';

const sevClass = (s: string) => (s.toLowerCase().includes('crit') || s.toLowerCase().includes('high') ? 'salmon' : s.toLowerCase().includes('med') ? 'amber' : 'blue');

export default function Findings() {
  const { sessionVersion } = useSession();
  const { data, error, loading, reload } = useAsync(() => api.findings(), [sessionVersion]);
  if (loading) return <><h1>Findings &amp; Investigation Casebook</h1><Skeleton /></>;
  if (error) return <><h1>Findings &amp; Investigation Casebook</h1><ErrorBox error={error} onRetry={reload} /></>;
  const findings = data ?? [];
  return (
    <>
      <h1>Findings &amp; Investigation Casebook</h1>
      <p className="secondary">Findings are generated from stored run evidence only. An attempted tool call is never inflated into a “critical compromise” — severity reflects verified synthetic impact.</p>
      {findings.length === 0 ? (
        <EmptyState title="No findings yet"><p>Findings appear after scenarios execute and produce evidence. Run A1–A6 from the Scenario Studio.</p></EmptyState>
      ) : (
        <div className="grid grid-2">
          {findings.map((f) => (
            <article className="card" key={f.id}>
              <p><span className={`badge ${sevClass(f.severity)}`}>Severity: {f.severity}</span>{' '}
                {f.scenario_id && <span className="badge blue">Scenario {f.scenario_id}</span>}{' '}
                {f.confidence && <span className="badge">Confidence: {f.confidence}</span>}</p>
              <h2>{f.title}</h2>
              {(f.trust_boundary ?? f.boundary) && <p className="small"><strong>Trust boundary:</strong> <span className="secondary">{f.trust_boundary ?? f.boundary}</span></p>}
              {f.evidence && <p className="small"><strong>Evidence:</strong> <span className="secondary">{f.evidence}</span></p>}
              {f.reproduction && <p className="small"><strong>Reproduction:</strong> <span className="secondary">{f.reproduction}</span></p>}
              {f.impact && <p className="small"><strong>Observed impact (synthetic lab):</strong> <span className="secondary">{f.impact}</span></p>}
              {f.root_cause && <p className="small"><strong>Root cause:</strong> <span className="secondary">{f.root_cause}</span></p>}
              {f.remediation && <p className="small"><strong>Remediation:</strong> <span className="secondary">{f.remediation}</span></p>}
              <p className="small muted"><strong>Limitations:</strong> {f.limitations ?? 'Synthetic lab only; not evidence about any production system.'}</p>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
