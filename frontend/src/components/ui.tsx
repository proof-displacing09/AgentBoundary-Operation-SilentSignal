import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Decision, LabEvent, Verdict } from '../lib/types';
import { useSession } from './session';
import { trialOutcomeLabel } from '../lib/labels';

/** Original AgentBoundary mark: a shield outline split by a boundary line. No vendor imitation. */
export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="AgentBoundary logo">
      <path d="M20 3 34 8v11c0 9-6.2 15-14 18C12.2 34 6 28 6 19V8L20 3z" fill="none" stroke="#68E0D0" strokeWidth="2.4" />
      <path d="M6.5 19h27" stroke="#79B8F2" strokeWidth="2" strokeDasharray="4 3" />
      <circle cx="20" cy="19" r="3.2" fill="#A5B4FC" />
    </svg>
  );
}

/** Verdict badge — color is always paired with the text label (never color-only). */
export function VerdictBadge({ verdict }: { verdict: Verdict | string }) {
  const cls = verdict === 'PASS' ? 'teal' : verdict === 'FAIL' ? 'salmon' : verdict === 'ERROR' ? 'amber' : 'violet';
  return <span className={`badge ${cls}`}>Verdict: {verdict}</span>;
}

export function DecisionBadge({ decision }: { decision: Decision | string }) {
  const cls = decision === 'ALLOW' ? 'teal' : decision === 'DENY' ? 'salmon' : decision === 'APPROVAL_REQUIRED' ? 'amber' : 'blue';
  return <span className={`badge ${cls}`}>Decision: {decision}</span>;
}

export function TrustBadge({ label }: { label: string | null | undefined }) {
  if (!label) return <span className="badge">Trust: unknown</span>;
  const lower = label.toLowerCase();
  const untrusted = lower.includes('untrust') || lower.includes('lower') || lower.includes('attacker');
  return (
    <span className={`badge ${untrusted ? 'amber' : 'blue'}`}>
      {untrusted ? 'UNTRUSTED — lower-trust content' : `Trust: ${label}`}
    </span>
  );
}

/**
 * Phase 4 execution badge — the ONLY labels used for run provenance anywhere
 * in the UI. Scripted runs are violet, real-model runs are amber (caution:
 * a live provider was involved); color is always paired with the text label.
 * Unknown adapters render their raw value rather than being guessed.
 */
export function AdapterBadge({ adapter, transport }: { adapter: string | null | undefined; transport?: string | null }) {
  if (adapter === 'real_llm') {
    if (transport === 'mocked_protocol') return <span className="badge amber">REAL LLM — MOCKED PROTOCOL (NOT LIVE)</span>;
    if (transport === 'live_provider') return <span className="badge amber">REAL LLM — LIVE PROVIDER TRIAL</span>;
    return <span className="badge amber">REAL LLM EVALUATION</span>;
  }
  if (adapter === 'scripted') return <span className="badge violet">SCRIPTED LAB SIMULATION</span>;
  return <span className="badge">Adapter: {adapter ?? 'unknown'}</span>;
}

export function TrialOutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <span className="badge">Trial outcome: not recorded</span>;
  const good = ['CLEAN_TASK_SUCCESS', 'RESISTED_AFTER_EXPOSURE', 'TARGETED_ATTACK_BLOCKED', 'SCRIPTED_BOUNDARY_HELD'].includes(outcome);
  const bad = ['FORBIDDEN_COMPLETED', 'SCRIPTED_BOUNDARY_FAILED'].includes(outcome);
  const cls = good ? 'teal' : bad ? 'salmon' : 'violet';
  return <span className={`badge ${cls}`}>Trial: {trialOutcomeLabel(outcome)}</span>;
}

/**
 * Phase 4 real-LLM metadata line. Renders only fields the backend reports
 * (host-only provider, model, outcome, error class, call counts) — there is
 * no key field in the contract and none is ever rendered.
 */
export function LlmBlock({ llm }: { llm: import('../lib/types').LlmMetrics | null | undefined }) {
  if (!llm) return null;
  return (
    <p className="small secondary" style={{ margin: '4px 0 0' }} aria-label="Real language model execution details">
      <span className="badge amber">REAL LLM EVALUATION</span>{' '}
      {llm.model && <>Model: <span className="mono">{llm.model}</span> · </>}
      {llm.provider_base_url_host && <>Provider host: <span className="mono">{llm.provider_base_url_host}</span> · </>}
      {llm.outcome && <>Outcome: <span className="mono">{llm.outcome}</span> · </>}
      {llm.error_class && <>Error: <span className="mono">{llm.error_class}</span> · </>}
      {typeof llm.model_calls === 'number' && <>Model calls: {llm.model_calls} · </>}
      {typeof llm.tool_calls_made === 'number' && <>Tool calls made: {llm.tool_calls_made}</>}
    </p>
  );
}

export function ModeBadges() {
  // FR-11: the shell badges describe the LABORATORY environment, never
  // the current run's adapter — the old unconditional "SCRIPTED LAB
  // SIMULATION" badge mislabeled real-model pages. Per-run adapter is
  // shown by AdapterBadge on run pages (Replay, Reports, recent runs).
  return (
    <>
      <span className="badge teal">Mode: PROTECTED</span>
      <span className="badge violet">LOCAL SYNTHETIC LAB</span>
      <span className="badge">Synthetic data only</span>
    </>
  );
}

export function Skeleton({ label = 'Loading…' }: { label?: string }) {
  return <div className="skeleton" role="status" aria-label={label} />;
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <strong>Something could not be loaded.</strong>
      <p className="secondary" style={{ marginTop: 6 }}>{error.message}</p>
      {onRetry && <button type="button" className="btn small" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

/** Minimal toast system: real outcomes only (run finished, download done/failed). */
export interface Toast { id: number; text: string; error?: boolean }
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, error }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }, []);
  return { toasts, push };
}
export function ToastRegion({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toast-region" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.error ? ' error' : ''}`} role={t.error ? 'alert' : 'status'}>{t.text}</div>
      ))}
    </div>
  );
}

/**
 * N-05 central data-layer fix. Every session-scoped fetch goes through this
 * hook, and it is keyed on SessionContext.sessionVersion in addition to the
 * caller's deps:
 *  - When the session changes, reload() runs again and synchronously clears
 *    the previous session's data (data=null, loading=true) — stale tenant
 *    content is never rendered while the new fetch is in flight.
 *  - A generation token guards every in-flight request: if a newer reload has
 *    started (session switch, filter change, re-navigation), the older
 *    promise's resolution is ignored and can never write old-tenant data.
 *  - Cancellation has two layers: the API client tracks a per-token
 *    AbortController for every request and switchPersona() aborts the old
 *    token's in-flight requests, while the generation token additionally
 *    guards state writes (a late resolution from a superseded fetch is
 *    discarded, never rendered).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const { sessionVersion } = useSession();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const reload = useCallback(() => {
    const gen = ++generation.current;
    // Synchronous clear: the moment a refetch starts, old data is gone.
    setData(null); setError(null); setLoading(true);
    fn()
      .then((v) => { if (generation.current === gen) setData(v); })
      .catch((e: unknown) => { if (generation.current === gen) setError(e instanceof Error ? e : new Error(String(e))); })
      .finally(() => { if (generation.current === gen) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, sessionVersion]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload };
}

/**
 * Epoch guard for imperative (non-useAsync) handlers such as "run scenario"
 * or "load run". Capture `epoch.current` before awaiting; after awaiting,
 * abandon the result if the epoch moved — the session changed meanwhile and
 * the result belongs to the previous tenant's session.
 */
export function useSessionEpoch() {
  const { sessionVersion } = useSession();
  const ref = useRef(sessionVersion);
  ref.current = sessionVersion;
  return ref;
}

/** One logical tool call: all lifecycle rows sharing a tool_call_id (or, for
 * pre-correlation events, a single event on its own). ATTEMPT rows are never
 * counted or displayed as separate completed actions. */
export interface LogicalCall {
  key: string;
  tool_call_id: string | null;
  events: LabEvent[];
  attempt: LabEvent | null;
  terminal: LabEvent | null;
}

export function groupEvents(events: LabEvent[]): LogicalCall[] {
  const groups = new Map<string, LabEvent[]>();
  for (const ev of events) {
    const key = ev.tool_call_id ?? `event:${ev.event_id}`;
    const list = groups.get(key);
    if (list) list.push(ev); else groups.set(key, [ev]);
  }
  return [...groups.values()].map((list) => {
    const sorted = [...list].sort((a, b) => a.seq - b.seq);
    // Terminal outcome: the last row carrying a real decision or a completion.
    // A denied ATTEMPT row may itself be that row; then attempt === terminal
    // and it is rendered once, never double-counted as two logical calls.
    const terminal = [...sorted].reverse().find((e) =>
      e.completed || e.decision === 'ALLOW' || e.decision === 'DENY' || e.decision === 'APPROVAL_REQUIRED' || e.decision === 'ERROR',
    ) ?? sorted[sorted.length - 1] ?? null;
    const attempt = sorted.find((e) => e.attempted) ?? null;
    return { key: sorted[0]?.tool_call_id ?? sorted[0]?.event_id ?? '', tool_call_id: sorted[0]?.tool_call_id ?? null, events: sorted, attempt, terminal };
  });
}

/** Control-only evidence (N-04): a positive-control record whose actor, tenant
 * and case identifiers must not reach a non-admin viewer. */
export function isControlOnly(ev: LabEvent): boolean {
  return ev.evidence_scope === 'control_only';
}
export function isControlOnlyGroup(group: LogicalCall): boolean {
  return group.events.length > 0 && group.events.every(isControlOnly);
}

export function personaLabel(p: { id: string; display_name?: string; name?: string }): string {
  return p.display_name ?? p.name ?? p.id;
}
export function personaTenants(p: { tenant_ids?: string[]; tenants?: string[] }): string[] {
  return p.tenant_ids ?? p.tenants ?? [];
}
