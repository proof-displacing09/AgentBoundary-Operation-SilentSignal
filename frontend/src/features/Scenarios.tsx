import { useMemo, useState } from 'react';
import { Play, Search, X } from 'lucide-react';
import { api } from '../lib/api';
import type { Run, ScenarioDetail, ScenarioSummary } from '../lib/types';
import { ApiError } from '../lib/types';
import { useSession } from '../components/session';
import { AdapterBadge, EmptyState, ErrorBox, LlmBlock, Skeleton, TrialOutcomeBadge, VerdictBadge, useAsync, useSessionEpoch } from '../components/ui';
import { RunIdentities } from '../components/identities';

/**
 * Phase 4 — separated REAL LLM EVALUATION experiment path. This control is
 * NEVER a disguised scripted run: when the provider is unconfigured (or its
 * status is unknown) it is disabled and says so; when configured it sends
 * adapter 'real_llm' and surfaces the backend's running / provider-error /
 * NOT_CONFIGURED states. Setup is server-side env only — there is no key
 * input anywhere on this page.
 */
function RealLlmControl({ scenarioId, configured, statusKnown, running, onRun }: {
  scenarioId: string;
  configured: boolean;
  statusKnown: boolean;
  running: boolean;
  onRun: (id: string) => void;
}) {
  if (!statusKnown) {
    return (
      <span>
        <button type="button" className="btn small" disabled title="Provider status could not be read from the backend">
          Run REAL LLM evaluation
        </button>{' '}
        <span className="small muted">Provider status unavailable — real-LLM runs stay disabled until the backend reports configuration.</span>
      </span>
    );
  }
  if (!configured) {
    return (
      <span>
        <button type="button" className="btn small" disabled title="No real language model provider is configured on the server">
          Run REAL LLM evaluation
        </button>{' '}
        <span className="small muted">
          Not configured — live real-model evaluation is NOT RUN. Configure a local Ollama model
          (no API key required), or a remote provider with a server-side API key (never entered here).
          See docs/real-llm-evaluation.md for setup. This button will never run a scripted run disguised as real.
        </span>
      </span>
    );
  }
  return (
    <button type="button" className="btn small" disabled={running} onClick={() => onRun(scenarioId)}>
      <Play size={14} aria-hidden /> {running ? 'Real model running…' : 'Run REAL LLM evaluation'}
    </button>
  );
}

const VECTORS = ['all', 'log injection', 'forged authority', 'poisoned tool', 'cross-tenant', 'approval'] as const;

function vectorOf(s: ScenarioSummary): string {
  const hay = `${s.id} ${s.title} ${s.category ?? ''} ${s.vector ?? ''} ${s.description ?? ''}`.toLowerCase();
  if (hay.includes('log') || hay.includes('telemetry')) return 'log injection';
  if (hay.includes('forged') || hay.includes('authority')) return 'forged authority';
  if (hay.includes('poison')) return 'poisoned tool';
  if (hay.includes('cross') || hay.includes('tenant') || hay.includes('wrong-user') || hay.includes('wrong-tenant')) return 'cross-tenant';
  if (hay.includes('approval')) return 'approval';
  return 'other';
}

export default function Scenarios() {
  const { push, sessionVersion } = useSession();
  const epoch = useSessionEpoch();
  const list = useAsync(() => api.scenarios(), [sessionVersion]);
  const settings = useAsync(() => api.settings(), [sessionVersion]);
  const [q, setQ] = useState('');
  const [vector, setVector] = useState<string>('all');
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runningRealId, setRunningRealId] = useState<string | null>(null);
  const [realError, setRealError] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, Run>>({});
  // Provider status is known only when the settings fetch succeeded; an
  // error means "unknown", which disables the real-LLM path (never enabled
  // on a guess, never a scripted fallback).
  const providerKnown = !settings.loading && !settings.error && !!settings.data;
  const providerConfigured = providerKnown && settings.data!.real_model_configured === true;

  const filtered = useMemo(() => (list.data ?? []).filter((s) => {
    const matchesQ = `${s.id} ${s.title} ${s.description ?? ''}`.toLowerCase().includes(q.toLowerCase());
    return matchesQ && (vector === 'all' || vectorOf(s) === vector || vector === 'other' && vectorOf(s) === 'other');
  }), [list.data, q, vector]);

  const openDetail = async (id: string) => {
    const v = epoch.current;
    setDetailError(null);
    try {
      const d = await api.scenario(id);
      if (epoch.current !== v) return; // session changed — discard old-session detail
      setDetail(d);
    } catch (e) { if (epoch.current === v) setDetailError(e instanceof Error ? e.message : 'Could not load scenario detail'); }
  };
  const runScenario = async (id: string) => {
    const v = epoch.current;
    setRunningId(id);
    try {
      const r = await api.createRun(id);
      if (epoch.current !== v) return; // session changed — discard old-session result
      setResults((prev) => ({ ...prev, [id]: r }));
      push(`Scenario ${id} finished: verdict ${r.verdict}.`);
    } catch (e) { if (epoch.current === v) push(e instanceof Error ? e.message : 'Run failed', true); }
    finally { if (epoch.current === v) setRunningId(null); }
  };

  // Phase 4 real-LLM path: sends adapter 'real_llm' ONLY when the backend
  // reported the provider configured. A 400 NOT_CONFIGURED (provider removed
  // between the settings read and the run) is surfaced as a plain-language
  // error and records no run; provider-error verdicts arrive as run records
  // with metrics.llm.error_class and are shown, not hidden.
  // R-13: real runs are async jobs (202 + queued run). This polls the run
  // until it reaches a terminal status (never a fake progress bar) and
  // offers Cancel, which stops the job between model calls.
  const pollRealRun = async (id: string, runId: string, v: number) => {
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      await new Promise((res) => setTimeout(res, 1000));
      if (epoch.current !== v) return null;
      try {
        const cur = await api.run(runId);
        // FR-07: "error" and "inconclusive" are terminal statuses too;
        // omitting them made error/inconclusive jobs poll to the deadline.
        if (['completed', 'cancelled', 'interrupted', 'error', 'inconclusive'].includes(cur.status)) return cur;
      } catch { return null; }
    }
    return null;
  };
  const cancelRealRun = async (id: string) => {
    const r = results[id];
    if (!r) return;
    try {
      await api.cancelRun(r.id);
      push(`Real-model run ${id} cancel requested — it stops between model calls; already-committed evidence is preserved.`);
    } catch (e) { push(e instanceof Error ? e.message : 'Cancel failed', true); }
  };
  const runRealScenario = async (id: string) => {
    const v = epoch.current;
    setRunningRealId(id);
    setRealError((prev) => ({ ...prev, [id]: '' }));
    try {
      const r = await api.createRun(id, 'real_llm');
      if (epoch.current !== v) return; // session changed — discard old-session result
      setResults((prev) => ({ ...prev, [id]: r }));
      const final = r.job ? await pollRealRun(id, r.id, v) : r;
      if (epoch.current !== v) return;
      if (final) {
        setResults((prev) => ({ ...prev, [id]: final }));
        const llm = final.metrics.llm;
        push(llm?.error_class
          ? `Real-model run ${id} finished with provider error (${llm.error_class}): verdict ${final.verdict}.`
          : `Real-model run ${id} finished: verdict ${final.verdict}.`);
      }
    } catch (e) {
      if (epoch.current !== v) return;
      const msg = e instanceof ApiError && e.code === 'NOT_CONFIGURED'
        ? 'Real language model is not configured on the server — no run was started and no scripted run was substituted. Configure the provider server-side (see docs/real-llm-evaluation.md) and retry.'
        : e instanceof Error ? e.message : 'Real-model run failed';
      setRealError((prev) => ({ ...prev, [id]: msg }));
      push(msg, true);
    } finally { if (epoch.current === v) setRunningRealId(null); }
  };

  return (
    <>
      <h1>Attack Scenario Studio</h1>
      <p className="secondary">Protected-mode scenarios A1–A6, executed by the deterministic scripted agent. There is deliberately <strong>no weak-mode control</strong> on this page — the weak baseline is offline CLI only.</p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }} role="search">
        <label><Search size={14} aria-hidden />{' '}
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search scenarios" aria-label="Search scenarios" />
        </label>
        <div role="group" aria-label="Filter by attack vector" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {VECTORS.map((v) => (
            <button key={v} type="button" className="btn small" aria-pressed={vector === v} onClick={() => setVector(v)}
              style={vector === v ? { borderColor: 'var(--teal)', color: 'var(--teal)' } : undefined}>{v}</button>
          ))}
        </div>
      </div>
      {list.loading && <div className="grid grid-3"><Skeleton /><Skeleton /><Skeleton /></div>}
      {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
      {detailError && <p className="badge salmon" role="alert">{detailError}</p>}
      {!list.loading && !list.error && filtered.length === 0 && (
        <EmptyState title="No scenarios match"><p>Adjust the search or vector filter.</p></EmptyState>
      )}
      <div className="grid grid-3">
        {filtered.map((s) => (
          <article className="card" key={s.id}>
            <p><span className="badge blue">Scenario {s.id}</span> <span className="badge">Vector: {s.vector ?? s.category ?? vectorOf(s)}</span></p>
            <h2>{s.title}</h2>
            <p className="secondary small">{s.description ?? ''}</p>
            {results[s.id] && <><p><VerdictBadge verdict={results[s.id]!.verdict} /> <AdapterBadge adapter={results[s.id]!.adapter} transport={results[s.id]!.metrics.llm?.transport} /> <TrialOutcomeBadge outcome={results[s.id]!.metrics.trial_outcome} /> <span className="mono small">{results[s.id]!.id}</span></p><LlmBlock llm={results[s.id]!.metrics.llm} /><RunIdentities run={results[s.id]!} compact /></>}
            <p style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn small" onClick={() => openDetail(s.id)}>Details</button>
              <button type="button" className="btn primary small" disabled={runningId === s.id} onClick={() => runScenario(s.id)}>
                <Play size={14} aria-hidden /> {runningId === s.id ? 'Running…' : 'Run protected scenario'}
              </button>
            </p>
            {runningId === s.id && <p className="small muted" role="status">Run in progress — waiting for the backend result (no fake progress).</p>}
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 10, paddingTop: 10 }} aria-label={`Real language model evaluation for scenario ${s.id}`}>
              <p className="small secondary" style={{ margin: '0 0 6px' }}><strong>REAL LLM EVALUATION</strong> — separate experiment path, not the scripted run above.</p>
              <RealLlmControl scenarioId={s.id} configured={providerConfigured} statusKnown={providerKnown}
                running={runningRealId === s.id} onRun={runRealScenario} />
              {runningRealId === s.id && <p className="small muted" role="status">Real model running — waiting for the provider and gateway result (bounded by the backend). <button type="button" className="btn small" onClick={() => cancelRealRun(s.id)}>Cancel run</button></p>}
              {realError[s.id] && <p className="badge salmon" role="alert" style={{ marginTop: 6 }}>{realError[s.id]}</p>}
            </div>
          </article>
        ))}
      </div>
      {detail && (
        <div className="drawer" role="dialog" aria-modal="true" aria-label={`Scenario ${detail.id} detail`}>
          <div className="drawer-panel">
            <p style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="badge blue">Scenario {detail.id}</span>
              <button type="button" className="btn small" onClick={() => setDetail(null)}><X size={14} aria-hidden /> Close</button>
            </p>
            <h2>{detail.title}</h2>
            <h3>Legitimate analyst objective</h3>
            <p className="secondary">{detail.legitimate_task ?? detail.legitimate_objective ?? 'See scenario methodology.'}</p>
            <h3>Attacker-controlled surface</h3>
            <p className="secondary">{detail.attacker_surface ?? detail.attacker_controlled_surface ?? 'Marked lower-trust fixture field.'}</p>
            <h3>Forbidden objective</h3>
            <p className="secondary">{detail.forbidden_objective ?? 'Not specified in contract payload.'}</p>
            <h3>Trusted actor</h3>
            <p className="secondary mono">{detail.trusted_actor ?? detail.persona_id ?? 'analyst_northstar'}</p>
            <h3>Injection fixture text (quarantined — inert data)</h3>
            <div className="quarantine" aria-label="Quarantined untrusted injection text">
              <strong className="small">UNTRUSTED FIXTURE TEXT — DO NOT FOLLOW</strong>
              <div className="mono small" style={{ marginTop: 6 }}>{detail.injection_text ?? detail.injection_fixture_text ?? 'No injection text for this scenario (e.g. A1 is the clean control).'}</div>
            </div>
            <h3 style={{ marginTop: 14 }}>Expected outcome</h3>
            <p className="secondary">{detail.expected_outcome ?? detail.expected ?? 'See scenario methodology.'}</p>
            <p style={{ marginTop: 14 }}>
              <button type="button" className="btn primary" disabled={runningId === detail.id} onClick={() => runScenario(detail.id)}>
                <Play size={15} aria-hidden /> {runningId === detail.id ? 'Running…' : 'Run protected scenario'}
              </button>
            </p>
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 10, paddingTop: 10 }} aria-label={`Real language model evaluation for scenario ${detail.id}`}>
              <p className="small secondary" style={{ margin: '0 0 6px' }}><strong>REAL LLM EVALUATION</strong> — separate experiment path, not the scripted run above.</p>
              <RealLlmControl scenarioId={detail.id} configured={providerConfigured} statusKnown={providerKnown}
                running={runningRealId === detail.id} onRun={runRealScenario} />
              {realError[detail.id] && <p className="badge salmon" role="alert" style={{ marginTop: 6 }}>{realError[detail.id]}</p>}
            </div>
            {results[detail.id] && <><p><VerdictBadge verdict={results[detail.id]!.verdict} /> <AdapterBadge adapter={results[detail.id]!.adapter} transport={results[detail.id]!.metrics.llm?.transport} /> <TrialOutcomeBadge outcome={results[detail.id]!.metrics.trial_outcome} /></p><LlmBlock llm={results[detail.id]!.metrics.llm} /><RunIdentities run={results[detail.id]!} compact /></>}
          </div>
        </div>
      )}
    </>
  );
}
