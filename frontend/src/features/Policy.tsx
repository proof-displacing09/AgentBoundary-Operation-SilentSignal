import { api } from '../lib/api';
import { useSession } from '../components/session';
import { EmptyState, ErrorBox, Skeleton, personaLabel, personaTenants, useAsync } from '../components/ui';

export default function Policy() {
  const { sessionVersion } = useSession();
  const { data, error, loading, reload } = useAsync(() => api.matrix(), [sessionVersion]);
  if (loading) return <><h1>Policy &amp; Tenant Access Explorer</h1><Skeleton /></>;
  if (error || !data) return <><h1>Policy &amp; Tenant Access Explorer</h1><ErrorBox error={error ?? new Error('No data')} onRetry={reload} /></>;
  const reasonText = (r: string | { code: string; description?: string }) =>
    typeof r === 'string' ? r : `${r.code}${r.description ? ` — ${r.description}` : ''}`;
  return (
    <>
      <h1>Policy &amp; Tenant Access Explorer</h1>
      <p className="secondary">Read-only view of the backend policy matrix. <strong>No web route edits policy or escalates roles</strong> — fixture changes happen only in the isolated developer workflow.</p>
      <div className="grid grid-2" style={{ marginBottom: 14 }}>
        <section className="card" aria-label="Personas">
          <h2>Personas &amp; assignments</h2>
          {data.personas.length === 0 ? <p className="muted">No personas returned.</p> : data.personas.map((p) => (
            <p key={p.id}><span className="mono">{p.id}</span> ({personaLabel(p)}) — role <strong>{p.role}</strong><br />
              <span className="small secondary">Tenants: {personaTenants(p).join(', ') || 'none'}</span></p>
          ))}
        </section>
        <section className="card" aria-label="Tenants">
          <h2>Tenants</h2>
          {data.tenants.map((t, i) => {
            const id = typeof t === 'string' ? t : t.id;
            const name = typeof t === 'string' ? t : (t.name ?? t.id);
            return <p key={id ?? i}><span className="mono">{id}</span> — {name}</p>;
          })}
          <h2 style={{ marginTop: 14 }}>Reason codes</h2>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.reason_codes.map((r, i) => <li key={i} className="mono small">{reasonText(r)}</li>)}
          </ul>
        </section>
      </div>
      <section className="card" aria-label="Access control matrix">
        <h2>Access-control matrix</h2>
        <div className="table-wrap">
          <table>
            <caption className="small muted" style={{ textAlign: 'left', paddingBottom: 6 }}>Effective tool authorization rules as enforced by the backend gateway.</caption>
            <thead><tr><th scope="col">Action</th><th scope="col">Tool</th><th scope="col">Approval required?</th><th scope="col">Allowed roles</th><th scope="col">Tenant rule</th></tr></thead>
            <tbody>
              {data.actions.map((a) => (
                <tr key={`${a.action}-${a.tool}`}>
                  <td className="mono">{a.action}</td><td className="mono">{a.tool}</td>
                  <td>{a.requires_approval ? 'Yes — exact-match approval' : 'No'}</td>
                  <td>{a.allowed_roles.join(', ')}</td><td>{a.tenant_rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.actions.length === 0 && <EmptyState title="No actions in matrix"><p>The backend returned an empty action list.</p></EmptyState>}
      </section>
      <section className="card" style={{ marginTop: 14 }} aria-label="Approval rules">
        <h2>Approval rules (as stored)</h2>
        <pre className="json mono" tabIndex={0} aria-label="Approval rules JSON">{JSON.stringify(data.approval_rules, null, 2)}</pre>
      </section>
    </>
  );
}
