import { useState } from 'react';
import { RefreshCcw } from 'lucide-react';
import { api } from '../lib/api';
import type { ResetResult } from '../lib/types';
import { ApiError } from '../lib/types';
import { useSession } from '../components/session';
import { ErrorBox, Skeleton, useAsync } from '../components/ui';

/** N-03: read a deletion count from wherever the backend puts it; a missing
 * count renders as "unknown" — never an invented number. */
function countOf(r: ResetResult, key: 'runs' | 'events' | 'drafts' | 'isolations'): number | null {
  const v = r.would_delete?.[key] ?? r[key] ?? r.counts?.[key];
  return typeof v === 'number' ? v : null;
}
function fmtCount(n: number | null): string {
  return n === null ? 'unknown' : String(n);
}
function resetErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return 'You do not have permission to reset the lab. Only the Incident Commander lab-admin persona can reset the lab, and nothing was deleted.';
    if (e.status === 400) return 'Reset was not performed: the backend requires an explicit dry-run preview followed by explicit confirmation. Nothing was deleted.';
    if (e.status === 401) return 'Lab session expired — pick a lab persona again. Nothing was deleted.';
    return e.message;
  }
  return e instanceof Error ? e.message : 'Reset failed';
}

export default function LabSettings() {
  const { push, sessionVersion, persona } = useSession();
  const health = useAsync(() => api.health(), [sessionVersion]);
  const settings = useAsync(() => api.settings(), [sessionVersion]);
  const [preview, setPreview] = useState<ResetResult | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetDone, setResetDone] = useState<number | null>(null);

  // N-03: only the incident_commander lab-admin persona may reset. Everyone
  // else gets a disabled control with a plain-language explanation — the
  // backend enforces this too (403), the disabled button is not the control.
  const isAdmin = persona?.id === 'incident_commander';

  const previewReset = async () => {
    setResetting(true); setResetError(null); setResetDone(null);
    try { setPreview(await api.reset({ dryRun: true })); }
    catch (e) { setResetError(resetErrorMessage(e)); }
    finally { setResetting(false); }
  };

  const doReset = async () => {
    setResetting(true); setResetError(null);
    try {
      const r = await api.reset({ confirm: true });
      setResetDone(typeof r.records === 'number' ? r.records : null);
      setPreview(null);
      push(`Lab data reset. Fixtures reseeded${typeof r.records === 'number' ? ` (${r.records} records)` : ''}.`);
      health.reload(); settings.reload();
    } catch (e) { setResetError(resetErrorMessage(e)); }
    finally { setResetting(false); }
  };

  const h = health.data;
  // Phase 4 provider status: model name and base-URL host ONLY. The backend
  // never reports key material, and this page has no key input field —
  // provider setup is server-side environment only (docs/real-llm-evaluation.md).
  const provider = settings.data ?? null;
  const providerConfigured = provider?.real_model_configured ?? h?.real_model_configured ?? false;
  return (
    <>
      <h1>Local Lab Settings / Health</h1>
      <p className="secondary">Local synthetic lab only, bound to localhost. No shell, network-target, or dangerous configuration controls exist on this page.</p>
      {health.loading && <Skeleton />}
      {health.error && <ErrorBox error={health.error} onRetry={health.reload} />}
      {h && (
        <>
        <section className="card" aria-label="Real language model provider status" style={{ marginBottom: 14 }}>
          <h2 style={{ marginTop: 0 }}>Real language model provider status</h2>
          {settings.loading && <Skeleton />}
          {settings.error && <p className="small secondary">Provider status could not be read from the backend; the health row below is the fallback. Real-LLM runs stay disabled until the backend reports the provider configured.</p>}
          <p>
            <span className={`badge ${providerConfigured ? 'teal' : 'salmon'}`}>
              {providerConfigured ? 'CONFIGURED' : 'NOT CONFIGURED — live real-model evaluation is NOT RUN'}
            </span>
          </p>
          <div className="table-wrap"><table><tbody>
            <tr><th scope="row">Model</th><td className="mono">{provider?.real_llm_model ?? h?.real_llm_model ?? '— (none reported)'}</td></tr>
            <tr><th scope="row">Provider base-URL host</th><td className="mono">{provider?.real_llm_base_url_host ?? h?.real_llm_base_url_host ?? '— (none reported)'}</td></tr>
            {(provider?.real_llm_config_error ?? h?.real_llm_config_error) && (
              <tr><th scope="row">Provider configuration problem</th><td className="mono">{provider?.real_llm_config_error ?? h?.real_llm_config_error} — real-model runs are refused until the backend environment is corrected; no key material is shown here.</td></tr>
            )}
          </tbody></table></div>
          <p className="small secondary">
            Setup is server-side environment only (AGENTBOUNDARY_LLM_MODEL and AGENTBOUNDARY_LLM_BASE_URL
            in the backend process environment, plus AGENTBOUNDARY_LLM_API_KEY for remote providers — or
            AGENTBOUNDARY_LLM_LOCAL_OLLAMA=1 for a keyless local Ollama model; see docs/real-llm-evaluation.md).
            No API key is displayed here, no key is ever sent from this browser, and there is no key input field on this page.
            {!providerConfigured && ' Until the backend reports the provider configured, the Scenario Studio real-LLM control stays disabled and no real-model run is claimed.'}
          </p>
        </section>
        <div className="grid grid-2">
          <section className="card" aria-label="Health">
            <h2>Backend health</h2>
            <div className="table-wrap"><table><tbody>
              <tr><th scope="row">Status</th><td>{h.status}</td></tr>
              <tr><th scope="row">Mode</th><td><span className="badge teal">PROTECTED (default)</span></td></tr>
              <tr><th scope="row">Weak mode via API</th><td>{h.weak_mode_available_via_api ? 'Available — unexpected, report this' : 'Not available (offline CLI only) — expected'}</td></tr>
              <tr><th scope="row">Database version</th><td className="mono">{h.db_version}</td></tr>
              <tr><th scope="row">Fixture version</th><td className="mono">{h.fixture_version}</td></tr>
              <tr><th scope="row">Adapter</th><td>{h.adapter} — scripted lab simulation</td></tr>
              <tr><th scope="row">Real language model</th><td>{h.real_model_configured ? 'Configured (see backend)' : 'NOT CONFIGURED — real-model testing NOT RUN'}</td></tr>
              {h.fixture_integrity && (
                <tr><th scope="row">Fixture integrity</th><td>
                  {h.fixture_integrity.ok ? 'OK' : 'DEGRADED — evidence tables were recreated empty; see docs on recovery'}
                  {h.fixture_integrity.backfilled_tables.length > 0 && <> · Reference rows backfilled: {h.fixture_integrity.backfilled_tables.join(', ')}</>}
                  {h.fixture_integrity.degraded_tables.length > 0 && <> · Degraded tables: {h.fixture_integrity.degraded_tables.join(', ')}</>}
                </td></tr>
              )}
            </tbody></table></div>
          </section>
          <section className="card" aria-label="Lab settings">
            <h2>Lab settings (from backend)</h2>
            {settings.loading && <Skeleton />}
            {settings.error && <ErrorBox error={settings.error} onRetry={settings.reload} />}
            {settings.data && <pre className="json mono" tabIndex={0} aria-label="Lab settings JSON">{JSON.stringify(settings.data, null, 2)}</pre>}
            <p className="small secondary">Trial counts are bounded by the backend; this page displays the configured value rather than accepting arbitrary input.</p>
            <h2 style={{ marginTop: 14 }}>Reset lab data</h2>
            <p className="small secondary">Reseeds the synthetic fixtures to their deterministic state. Runs and audit history in the lab database are replaced by the seed. This is a privileged, destructive action: the backend only allows it for the Incident Commander lab-admin persona, and only after a dry-run preview.</p>
            {!isAdmin && (
              <p className="small secondary" role="note">
                Only the Incident Commander lab-admin persona can reset the lab. Switch to the incident_commander persona in the top bar to use this control.
              </p>
            )}
            <button type="button" className="btn danger" disabled={!isAdmin || resetting} onClick={previewReset}
              aria-disabled={!isAdmin} title={!isAdmin ? 'Only the Incident Commander lab-admin persona can reset the lab' : undefined}>
              <RefreshCcw size={15} aria-hidden /> {resetting && !preview ? 'Loading preview…' : 'Preview lab reset'}
            </button>
            {resetError && <p className="badge salmon" role="alert" style={{ marginTop: 8 }}>{resetError}</p>}
            {resetDone !== null && (
              <p className="small secondary" role="status" style={{ marginTop: 8 }}>
                Lab reset complete. Fresh fixture record count: {resetDone}.
              </p>
            )}
            {resetDone === null && preview && (
              <section className="card" aria-label="Reset dry-run summary" style={{ marginTop: 12 }}>
                <h2 style={{ marginTop: 0 }}>Reset preview — nothing has been deleted yet</h2>
                <p className="small secondary">The backend reports the following would be deleted by a confirmed reset. Counts the backend does not report are shown as unknown, never guessed.</p>
                <div className="table-wrap"><table><tbody>
                  <tr><th scope="row">Runs</th><td>{fmtCount(countOf(preview, 'runs'))}</td></tr>
                  <tr><th scope="row">Events</th><td>{fmtCount(countOf(preview, 'events'))}</td></tr>
                  <tr><th scope="row">Drafts</th><td>{fmtCount(countOf(preview, 'drafts'))}</td></tr>
                  <tr><th scope="row">Simulated isolations</th><td>{fmtCount(countOf(preview, 'isolations'))}</td></tr>
                </tbody></table></div>
                <p style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button type="button" className="btn danger" disabled={resetting} onClick={doReset}>{resetting ? 'Resetting…' : 'Yes, reset the lab'}</button>
                  <button type="button" className="btn" onClick={() => setPreview(null)}>Cancel</button>
                </p>
              </section>
            )}
          </section>
        </div>
        </>
      )}
    </>
  );
}
