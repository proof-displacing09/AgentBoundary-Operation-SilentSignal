import { api } from '../lib/api';
import { useSession } from '../components/session';
import type { ComparisonPair, RunSummary, UnmatchedComparison } from '../lib/types';
import { EmptyState, ErrorBox, Skeleton, VerdictBadge, useAsync } from '../components/ui';
import { RunIdentities } from '../components/identities';

function pairProtected(p: ComparisonPair): RunSummary | null {
  return p.protected ?? p.protected_run ?? null;
}
function pairWeak(p: ComparisonPair): (RunSummary & { omissions?: string[] }) | null {
  return p.weak ?? p.weak_run ?? p.weak_report ?? null;
}

function MetricLine({ r }: { r: RunSummary }) {
  if (!r.metrics) return null;
  const m = r.metrics;
  return (
    <p className="small secondary" style={{ margin: '4px 0 0' }}>
      <span className="mono">{r.id}</span>
      {' '}· Attempted unauthorized: {m.attempted_unauthorized} · Completed forbidden: {m.completed_forbidden} ·
      Denied: {m.denied} · Restricted disclosed: {m.disclosed_restricted ? 'yes' : 'no'}
      {m.security_invariant_pass !== undefined && <> · Security invariant pass: {m.security_invariant_pass ? 'yes' : 'no'}</>}
      {m.legitimate_workflow_completed !== undefined && <> · Legitimate workflow completed: {m.legitimate_workflow_completed ? 'yes' : 'no'}</>}
      {(m.out_of_mission_actions?.length ?? 0) > 0 && <> · Out-of-mission actions: {(m.out_of_mission_actions ?? []).map((a) => `${a.tool}${a.new_status ? `→${a.new_status}` : ''}`).join(', ')}</>}
    </p>
  );
}

function PairCard({ pair }: { pair: ComparisonPair }) {
  const prot = pairProtected(pair);
  const weak = pairWeak(pair);
  return (
    <section className="card" aria-label={`Matched comparison for scenario ${pair.scenario_id}`}>
      <h2>Scenario {pair.scenario_id} — matched pair</h2>
      {pair.fixture_version && <p className="small muted">Fixture version: {pair.fixture_version} · Adapter: scripted (both sides){pair.fixture_variant ? <> · Fixture variant (model-visible evidence surface): <span className="mono">{pair.fixture_variant}</span></> : ' · Fixture variant: not recorded (legacy) — pair only valid if backend matched it'}{pair.policy_version ? <> · Policy version: {pair.policy_version}</> : null}</p>}
      <div className="split">
        <div>
          <h3>Protected run (live backend, stored)</h3>
          {prot ? (
            <>
              <p style={{ margin: 0 }}><VerdictBadge verdict={prot.verdict} /> <span className="badge">Mode: {prot.mode ?? 'protected'}</span></p>
              <MetricLine r={prot} />
              <RunIdentities run={prot} compact />
            </>
          ) : <p className="muted">No protected run in this pair.</p>}
        </div>
        <div>
          <h3>Weak baseline (stored offline export only)</h3>
          <p><span className="badge salmon">INTENTIONALLY VULNERABLE OFFLINE LAB</span></p>
          {weak ? (
            <>
              <p style={{ margin: 0 }}><VerdictBadge verdict={weak.verdict} /> <span className="badge">Mode: weak</span></p>
              {weak.omissions && <p className="small secondary">Deliberate omissions: {weak.omissions.join(', ')}</p>}
              <MetricLine r={weak} />
              <RunIdentities run={weak} compact />
            </>
          ) : <p className="muted">No weak export in this pair.</p>}
        </div>
      </div>
      {pair.alternative_protected_runs && pair.alternative_protected_runs.length > 0 && (
        <p className="small muted">Also eligible for this pair (not double-counted): {pair.alternative_protected_runs.join(', ')}</p>
      )}
    </section>
  );
}

function UnmatchedList({ title, items }: { title: string; items: UnmatchedComparison[] }) {
  if (items.length === 0) return null;
  return (
    <section className="card" aria-label={title}>
      <h2>{title}</h2>
      <p className="small muted">These results are NOT part of any comparison — they have no matched counterpart under the pairing rules (same scenario, fixture version, scripted adapter).</p>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {items.map((u, i) => (
          <li key={u.id ?? `${u.scenario_id ?? 'unknown'}-${i}`} style={{ marginBottom: 6 }}>
            <span className="mono">{u.scenario_id ?? u.id ?? 'unknown'}</span>
            {u.reason ? <> — {u.reason}</> : <> — no matching counterpart</>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Comparison() {
  const { sessionVersion } = useSession();
  const { data, error, loading, reload } = useAsync(() => api.comparisons(), [sessionVersion]);
  if (loading) return <><h1>Protected vs. Weak Security Comparison</h1><Skeleton /></>;
  if (error || !data) return <><h1>Protected vs. Weak Security Comparison</h1><ErrorBox error={error ?? new Error('No data')} onRetry={reload} /></>;

  // F-04: pairs are the ONLY comparable rows. Legacy columns are shown only
  // when the backend predates pairing (pairs field absent) — and then the page
  // says plainly that comparability is not established.
  const pairsKnown = Array.isArray(data.pairs);
  const pairs = data.pairs ?? [];
  const hasWeakLegacy = data.weak_reports.length > 0;

  return (
    <>
      <h1>Protected vs. Weak Security Comparison</h1>
      <p className="secondary">
        Weak results come only from <strong>stored offline CLI exports</strong>. There is no “run vulnerable mode” control in the browser, by design.
        A pair counts as comparable only when the protected run and the weak export share the same scenario, fixture version, and scripted adapter.
      </p>
      {data.notes && <p className="small muted">{data.notes}</p>}

      {pairsKnown && pairs.length === 0 && (
        <EmptyState title="Not comparable — no matched pairs">
          <p>
            No protected run and stored weak export share a scenario, fixture version, and adapter, so no
            side-by-side claim is made. {data.unmatched_protected?.length ?? 0} unmatched protected run(s) and{' '}
            {data.unmatched_weak?.length ?? 0} unmatched weak export(s) are listed below with their reasons.
          </p>
        </EmptyState>
      )}
      {!pairsKnown && (
        <p className="badge amber" role="note">
          The backend did not return matched pairs, so comparability is not established by this page. Update the backend to the remediation API for pair-based comparison.
        </p>
      )}
      {pairsKnown && pairs.length > 0 && (
        <div style={{ display: 'grid', gap: 14, marginTop: 14 }}>
          {pairs.map((p) => {
            // E8-02: one scenario can now yield several pairs (one per
            // weak export), so the key must include the protected run.
            const prot = pairProtected(p);
            return <PairCard key={`${p.scenario_id}-${prot?.id ?? 'none'}`} pair={p} />;
          })}
        </div>
      )}
      {pairsKnown && (
        <div style={{ display: 'grid', gap: 14, marginTop: 14 }}>
          <UnmatchedList title="Unmatched protected runs (not compared)" items={data.unmatched_protected ?? []} />
          <UnmatchedList title="Unmatched weak exports (not compared)" items={data.unmatched_weak ?? []} />
        </div>
      )}
      {!pairsKnown && (
        <div className="split" style={{ marginTop: 14 }}>
          <section className="card" aria-label="Protected runs (legacy, unpaired)">
            <h2>Protected runs (legacy view — not claimed as matched)</h2>
            {data.protected_runs.length === 0 ? <p className="muted">No protected runs.</p> : data.protected_runs.map((r) => (
              <div key={r.id} style={{ borderBottom: '1px solid var(--border)', padding: '8px 0' }}>
                <p style={{ margin: 0 }}><span className="badge blue">Scenario {r.scenario_id}</span> <VerdictBadge verdict={r.verdict} /></p>
                <MetricLine r={r} />
              </div>
            ))}
          </section>
          <section className="card" aria-label="Weak baseline (legacy, unpaired)">
            <h2>Weak baseline (legacy view — not claimed as matched)</h2>
            <p><span className="badge salmon">INTENTIONALLY VULNERABLE OFFLINE LAB</span></p>
            {!hasWeakLegacy && <p className="muted">No offline weak export yet.</p>}
            {data.weak_reports.map((r) => (
              <div key={r.id} style={{ borderBottom: '1px solid var(--border)', padding: '8px 0' }}>
                <p style={{ margin: 0 }}><span className="badge blue">Scenario {r.scenario_id}</span> <VerdictBadge verdict={r.verdict} /></p>
                <MetricLine r={r} />
              </div>
            ))}
          </section>
        </div>
      )}
    </>
  );
}
