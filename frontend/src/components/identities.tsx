import type { RunIdentities } from '../lib/types';

/**
 * F-02 identity display. The operator (logged-in lab session) and the simulated
 * actor (the authority actually under test) are ALWAYS shown as two separate
 * labeled lines. The simulated actor is never presented as the logged-in user.
 * Pre-remediation runs have an actor but no operator field; that is stated,
 * not invented. A payload that carries NO identity fields at all (e.g. the
 * /overview recent-runs projection, or a comparison pair projection) is NOT
 * a pre-remediation run — it is a summary that omits identities — so it
 * must never claim "not recorded". It says where the identities live.
 */
export function RunIdentities({ run, compact }: { run: RunIdentities; compact?: boolean }) {
  const operator = run.operator_persona_id ?? null;
  const simulated = run.simulated_actor_id ?? run.actor_id ?? null;
  const control = run.control_actor_id ?? null;
  const style: React.CSSProperties = compact ? { margin: '4px 0 0' } : { margin: '8px 0' };
  if (operator === null && simulated === null && control === null && !run.fixture_version) {
    return (
      <p className="small secondary" style={style} aria-label="Run identities">
        <span className="badge">Identities not included in this summary — see the run&apos;s replay page.</span>
      </p>
    );
  }
  return (
    <p className="small secondary" style={style} aria-label="Run identities">
      <span className="badge">Operator (logged-in lab session): {operator ?? 'not recorded — run created before identity separation'}</span>{' '}
      <span className="badge violet">Simulated actor (authority under test): {simulated ?? 'unknown'}</span>
      {control && <>{' '}<span className="badge blue">Positive-control actor: {control}</span></>}
      {run.fixture_version && <>{' '}<span className="badge">Fixture: {run.fixture_version}</span></>}
    </p>
  );
}
