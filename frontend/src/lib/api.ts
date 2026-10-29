import {
  ApiError, type AlertRecord, type CaseRecord, type Comparisons, type EventsPage,
  type Finding, type Health, type LabEvent, type Overview, type Persona,
  type PolicyMatrix, type ResetResult, type Run, type RunSummary, type ScenarioDetail,
  type ScenarioSummary, type SessionResponse, type Settings,
} from './types';

const BASE = '/api/v1';
const TOKEN_KEY = 'agentboundary.labSessionToken';
const PERSONA_KEY = 'agentboundary.labPersona';

/**
 * F-01: every data request goes through request(), which always attaches the
 * stored lab-session token when one exists. When the backend answers 401
 * (missing/expired session), the registered handler routes the user back to
 * the persona picker instead of letting pages render empty data as if real.
 *
 * R-12: the handler is TOKEN-SCOPED. request() captures the token it sent;
 * the handler receives that token and must only invalidate the session if
 * it still equals the active token. A delayed 401 from an old persona's
 * request arriving after a switch to a new persona must NOT destroy the
 * new session. Session switches also abort in-flight requests of the old
 * token (abortRequestsForToken), including report downloads.
 */
type UnauthorizedHandler = (token: string | null) => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

const inFlight = new Map<string, Set<AbortController>>();
function track(token: string | null, controller: AbortController): void {
  if (!token) return;
  let set = inFlight.get(token);
  if (!set) { set = new Set(); inFlight.set(token, set); }
  set.add(controller);
}
function untrack(token: string | null, controller: AbortController): void {
  if (!token) return;
  const set = inFlight.get(token);
  if (!set) return;
  set.delete(controller);
  if (set.size === 0) inFlight.delete(token);
}
export function abortRequestsForToken(token: string | null): void {
  if (!token) return;
  const set = inFlight.get(token);
  if (!set) return;
  set.forEach((c) => { try { c.abort(); } catch { /* ignore */ } });
  inFlight.delete(token);
}

export function getStoredToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function storeSession(token: string, persona: Persona): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(PERSONA_KEY, JSON.stringify(persona));
  } catch { /* sessionStorage unavailable — session stays in memory only */ }
}
export function getStoredPersona(): Persona | null {
  try {
    const raw = sessionStorage.getItem(PERSONA_KEY);
    return raw ? (JSON.parse(raw) as Persona) : null;
  } catch { return null; }
}
export function clearSession(): void {
  try { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(PERSONA_KEY); } catch { /* ignore */ }
}

export function revokeSessionBestEffort(token: string | null): void {
  // A-C03: persona switch revokes the previous token so it cannot be
  // replayed after the switch. Fire-and-forget on purpose: the switch
  // itself already discarded the token client-side, and a failed
  // revoke (backend down, token already dead) must never block it.
  // Raw fetch, NOT request(): request() would attach the old token's
  // abort controller, which the switch just aborted.
  if (!token) return;
  try {
    fetch(`${BASE}/lab/session/revoke`, { method: 'POST', headers: { 'X-Lab-Session': token } }).catch(() => {});
  } catch { /* ignore */ }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['X-Lab-Session'] = token;
  const controller = new AbortController();
  track(token, controller);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, signal: controller.signal, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  } catch (e) {
    untrack(token, controller);
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, 'ABORTED', 'Request aborted by a session change.');
    }
    throw new ApiError(0, 'NETWORK_ERROR', 'Backend unreachable. Start the local API on 127.0.0.1:8000 and retry.');
  }
  untrack(token, controller);
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { error?: { code: string; message: string } };
      if (body.error) { code = body.error.code; message = body.error.message; }
    } catch { /* non-JSON error body — keep defaults */ }
    // R-12: pass the token THIS request used; the handler decides whether
    // it is still the active session before invalidating anything.
    if (res.status === 401 && unauthorizedHandler) unauthorizedHandler(token);
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>('/health'),
  settings: () => request<Settings>('/settings'),
  personas: () => request<Persona[]>('/lab/personas'),
  createSession: (personaId: string) =>
    request<SessionResponse>('/lab/session', { method: 'POST', body: JSON.stringify({ persona_id: personaId }) }),
  identity: () => request<Persona>('/lab/identity'),
  /**
   * N-03: privileged reset. Only incident_commander sessions may reset (others
   * get 403, nothing deleted). { dryRun: true } returns a deletion summary
   * without deleting; { confirm: true } performs the reset; neither sends an
   * empty body and the backend answers 400, deleting nothing.
   */
  reset: (opts?: { dryRun?: boolean; confirm?: boolean }): Promise<ResetResult> => {
    const body = opts?.dryRun ? { dry_run: true } : opts?.confirm ? { confirm: true } : {};
    return request<ResetResult>('/lab/reset', { method: 'POST', body: JSON.stringify(body) });
  },
  overview: () => request<Overview>('/overview'),
  scenarios: () => request<ScenarioSummary[]>('/scenarios'),
  scenario: (id: string) => request<ScenarioDetail>(`/scenarios/${encodeURIComponent(id)}`),
  /**
   * Phase 4: adapter is sent ONLY when explicitly 'real_llm'. Any other value
   * (including undefined) omits the field, so the backend defaults to the
   * scripted adapter — a real-LLM request can never silently fall back to
   * scripted, and a scripted request can never be mislabeled as real.
   */
  createRun: (scenarioId: string, adapter?: 'real_llm') =>
    request<Run>('/runs', {
      method: 'POST',
      body: JSON.stringify(adapter === 'real_llm' ? { scenario_id: scenarioId, adapter: 'real_llm' } : { scenario_id: scenarioId }),
    }),
  runs: () => request<RunSummary[]>('/runs'),
  run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
  runEvents: (id: string) => request<LabEvent[]>(`/runs/${encodeURIComponent(id)}/events`),
  events: (params: { run_id?: string; decision?: string; tool?: string; q?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)); });
    return request<EventsPage>(`/events?${qs.toString()}`);
  },
  alerts: () => request<AlertRecord[]>('/alerts'),
  alert: (id: string) => request<AlertRecord>(`/alerts/${encodeURIComponent(id)}`),
  cases: () => request<CaseRecord[]>('/cases'),
  caseById: (id: string) => request<CaseRecord>(`/cases/${encodeURIComponent(id)}`),
  matrix: () => request<PolicyMatrix>('/policy/matrix'),
  findings: () => request<Finding[]>('/findings'),
  comparisons: () => request<Comparisons>('/comparisons'),
  /** Cancel a queued/running real-mode job (R-13). */
  cancelRun: (runId: string) =>
    request<{ cancelled: boolean; run_id: string; status: string }>(`/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),
  /** Real blob download for report endpoints; returns the suggested filename. */
  downloadReport: async (runId: string, format: 'json' | 'markdown'): Promise<string> => {
    const token = getStoredToken();
    const headers: Record<string, string> = {};
    if (token) headers['X-Lab-Session'] = token;
    const controller = new AbortController();
    track(token, controller);
    let res: Response;
    try {
      res = await fetch(`${BASE}/reports/${encodeURIComponent(runId)}/${format}`, { headers, signal: controller.signal });
    } catch (e) {
      untrack(token, controller);
      if (e instanceof DOMException && e.name === 'AbortError') {
        throw new ApiError(0, 'ABORTED', 'Download aborted by a session change.');
      }
      throw new ApiError(0, 'NETWORK_ERROR', 'Backend unreachable while downloading report.');
    }
    // T10-03: stay tracked until the body is fully consumed. The old
    // code untracked here, on headers — so a persona switch during
    // blob streaming could no longer abort this download, and the
    // previous tenant's report could finish under the new persona.
    // Cleanup lives in the finally below, never before blob().
    let blob: Blob;
    try {
      // R-12: a late 401 on an old token's download must not clear the new session.
      if (res.status === 401 && unauthorizedHandler) unauthorizedHandler(token);
      if (!res.ok) throw new ApiError(res.status, `HTTP_${res.status}`, `Report download failed (${res.status})`);
      blob = await res.blob();
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        throw new ApiError(0, 'ABORTED', 'Download aborted by a session change.');
      }
      throw e;
    } finally {
      untrack(token, controller);
    }
    // T10-03: recheck immediately before triggering the download. If
    // the session changed while the body streamed (or the abort raced
    // blob completion), discard the stale blob: no file, no success
    // result, no previous-tenant artifact in the new persona's view.
    if (getStoredToken() !== token) {
      throw new ApiError(0, 'ABORTED', 'Download discarded after a session change.');
    }
    const filename = `agentboundary-run-${runId}.${format === 'json' ? 'json' : 'md'}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    // T10-03: do not revoke before the browser has captured the file;
    // a short deferral is the safe pattern (immediate revocation can
    // cancel the download in some browsers).
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return filename;
  },
};
