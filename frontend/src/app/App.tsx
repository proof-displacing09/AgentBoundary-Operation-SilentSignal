import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, BarChart3, BookOpen, FileText, GitCompareArrows, LayoutDashboard,
  Menu, PlaySquare, SearchCheck, Settings2, ShieldCheck, X,
} from 'lucide-react';
import { abortRequestsForToken, api, clearSession, getStoredPersona, getStoredToken, revokeSessionBestEffort, setUnauthorizedHandler, storeSession } from '../lib/api';
import type { Persona } from '../lib/types';
import { SessionContext } from '../components/session';
import { Logo, ModeBadges, ToastRegion, personaLabel, personaTenants, useToasts } from '../components/ui';
import Overview from '../features/Overview';
import Investigation from '../features/Investigation';
import Scenarios from '../features/Scenarios';
import Replay from '../features/Replay';
import Policy from '../features/Policy';
import Comparison from '../features/Comparison';
import Findings from '../features/Findings';
import Evidence from '../features/Evidence';
import Reports from '../features/Reports';
import LabSettings from '../features/LabSettings';

const NAV: Array<{ route: string; label: string; icon: typeof LayoutDashboard }> = [
  { route: 'overview', label: 'Command Center', icon: LayoutDashboard },
  { route: 'investigation', label: 'Investigation Workspace', icon: SearchCheck },
  { route: 'scenarios', label: 'Scenario Studio', icon: PlaySquare },
  { route: 'replay', label: 'Attack Replay', icon: Activity },
  { route: 'policy', label: 'Policy & Tenants', icon: ShieldCheck },
  { route: 'comparison', label: 'Protected vs Weak', icon: GitCompareArrows },
  { route: 'findings', label: 'Findings Casebook', icon: BookOpen },
  { route: 'evidence', label: 'Evidence Explorer', icon: FileText },
  { route: 'reports', label: 'Reporting Center', icon: BarChart3 },
  { route: 'settings', label: 'Lab Settings / Health', icon: Settings2 },
];

function routeFromHash(): string {
  const h = window.location.hash.replace(/^#\/?/, '');
  return h || 'overview';
}

export default function App() {
  const [route, setRoute] = useState(routeFromHash);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState<Persona | null>(getStoredPersona());
  const [sessionVersion, setSessionVersion] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const { toasts, push } = useToasts();

  // F-01 + N-05 + R-12: a 401 clears the session ONLY when the token that
  // produced it is still the active token. A delayed 401 from a previous
  // persona's request arriving after a switch is ignored — it must never
  // destroy the new session or show false expiry. Clearing bumps
  // sessionVersion (remounting page content) and routes back to the picker.
  useEffect(() => {
    setUnauthorizedHandler((token) => {
      if (token && token !== getStoredToken()) return;
      clearSession();
      setPersona(null);
      setSessionVersion((v) => v + 1);
      setSessionExpired(true);
      push('Lab session expired — please pick a lab persona above to sign in to the lab session again.', true);
    });
    return () => setUnauthorizedHandler(null);
  }, [push]);

  const navigate = useCallback((r: string) => {
    window.location.hash = `/${r}`;
    setRoute(r);
    setNavOpen(false);
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const establish = useCallback(async (personaId: string) => {
    const s = await api.createSession(personaId);
    storeSession(s.session_token, s.persona);
    setPersona(s.persona);
    setSessionVersion((v) => v + 1);
    return s.persona;
  }, []);

  // N-05 session restore: a stored session is VALIDATED against the backend
  // (identity endpoint) before any data page renders. An invalid/expired
  // stored session is cleared and the picker state is shown — pages never
  // render with an unvalidated token. If no stored session exists, establish
  // the default northstar analyst lab session as before.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api.personas();
        if (cancelled) return;
        setPersonas(list);
        if (getStoredPersona()) {
          try {
            const me = await api.identity();
            if (cancelled) return;
            setPersona(me);
            setSessionVersion((v) => v + 1);
          } catch {
            if (cancelled) return;
            clearSession();
            setPersona(null);
            setSessionExpired(true);
          }
        } else {
          const def = list.find((p) => p.id === 'analyst_northstar') ?? list[0];
          if (def && !cancelled) await establish(def.id);
        }
      } catch (e) {
        if (!cancelled) setSessionError(e instanceof Error ? e.message : 'Could not reach the backend.');
      } finally {
        if (!cancelled) setSessionReady(true);
      }
    })();
    return () => { cancelled = true; };
  }, [establish]);

  // N-05: switching clears the old session's page state SYNCHRONOUSLY — persona
  // is nulled and sessionVersion bumped before the new session is created, so
  // the old tenant's content unmounts immediately instead of lingering while
  // the new session establishes. R-12: the old token's in-flight requests
  // (including downloads) are aborted first, so their late 401s can never
  // land on the new session.
  const switchPersona = useCallback(async (id: string) => {
    const oldToken = getStoredToken();
    abortRequestsForToken(oldToken);
    revokeSessionBestEffort(oldToken);
    clearSession();
    setPersona(null);
    setSessionExpired(false);
    setSessionVersion((v) => v + 1);
    try {
      const p = await establish(id);
      push(`Lab session switched to ${p.id} (local lab simulation — not real SSO).`);
    } catch (e) {
      push(e instanceof Error ? e.message : 'Persona switch failed', true);
    }
  }, [establish, push]);

  const ctx = useMemo(() => ({ persona, personas, switchPersona, push, navigate, sessionVersion }),
    [persona, personas, switchPersona, push, navigate, sessionVersion]);

  const [page, param] = route.split(':');
  // N-05: page content is keyed by sessionVersion — every session change
  // (switch, logout, 401) remounts the page, discarding all of the previous
  // session's page state. Until the session is validated, no data page renders.
  let content: React.ReactNode;
  if (!sessionReady) {
    content = <><h1>Validating lab session…</h1><p className="secondary">Checking the stored lab session with the backend before showing any lab data.</p></>;
  } else if (!persona) {
    content = (
      <>
        <h1>No active lab session</h1>
        <p className="secondary">Pick a lab persona from the selector in the top bar to start a local lab session. No lab data is shown until a session is established.</p>
      </>
    );
  }
  if (sessionReady && persona) {
    switch (page) {
      case 'investigation': content = <Investigation />; break;
      case 'scenarios': content = <Scenarios />; break;
      case 'replay': content = <Replay runId={param} />; break;
      case 'policy': content = <Policy />; break;
      case 'comparison': content = <Comparison />; break;
      case 'findings': content = <Findings />; break;
      case 'evidence': content = <Evidence />; break;
      case 'reports': content = <Reports />; break;
      case 'settings': content = <LabSettings />; break;
      default: content = <Overview />;
    }
  }

  return (
    <SessionContext.Provider value={ctx}>
      <a className="skip-link" href="#main">Skip to main content</a>
      <div className="shell">
        <nav className={`sidebar${navOpen ? ' open' : ''}`} aria-label="Primary">
          <div className="brand">
            <Logo />
            <div>
              <div className="brand-name">AgentBoundary</div>
              <div className="brand-sub">Nightwatch Security</div>
            </div>
          </div>
          <p className="small muted" style={{ padding: '0 6px' }}>Operation SilentSignal — AI SOC Copilot Security Research &amp; Validation Platform.<br />“Test the agent. Enforce the boundary. Prove the outcome.”</p>
          {NAV.map(({ route: r, label, icon: Icon }) => (
            <a key={r} className="nav-link" href={`#/${r}`} aria-current={page === r ? 'page' : undefined}
              onClick={(e) => { e.preventDefault(); navigate(r); }}>
              <Icon size={17} aria-hidden /> {label}
            </a>
          ))}
          <p className="small muted" style={{ marginTop: 'auto', padding: '0 6px' }}>
            Fictional MDR lab. Synthetic tenants: Northstar Logistics, Cedar Retail Group. No real systems are connected.
          </p>
        </nav>
        <div className="main">
          <header className="topbar">
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
              <button type="button" className="btn small menu-btn" aria-expanded={navOpen} aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
                onClick={() => setNavOpen(!navOpen)}>
                {navOpen ? <X size={16} aria-hidden /> : <Menu size={16} aria-hidden />}
              </button>
              <ModeBadges />
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
              <label className="small secondary" htmlFor="persona-select">
                Lab persona <span className="muted">(local lab simulation — not real SSO)</span>
              </label>
              <select id="persona-select" value={persona?.id ?? ''} disabled={personas.length === 0}
                onChange={(e) => switchPersona(e.target.value)} aria-label="Select local lab persona">
                {personas.filter((p) => p.id !== 'attacker_fixture_author').map((p) => (
                  <option key={p.id} value={p.id}>{personaLabel(p)} ({p.id})</option>
                ))}
                {personas.length === 0 && <option value="">Backend unavailable</option>}
              </select>
              {persona && <span className="badge blue">Tenants: {personaTenants(persona).join(', ') || 'none'}</span>}
            </div>
          </header>
          {sessionExpired && (
            <div className="error-box" role="alert" style={{ margin: '14px 22px 0' }}>
              <strong>Lab session expired — please sign in to the lab session again.</strong>
              <p className="secondary" style={{ marginTop: 4 }}>
                Your stored lab session was rejected by the backend (401). Pick a lab persona from the
                selector in the top bar to start a new local lab session. No data shown below is from the
                expired session.
              </p>
              <button type="button" className="btn small" onClick={() => setSessionExpired(false)}>Dismiss</button>
            </div>
          )}
          {sessionError && (
            <div className="error-box" role="alert" style={{ margin: '14px 22px 0' }}>
              <strong>Lab session could not be established.</strong>
              <p className="secondary" style={{ marginTop: 4 }}>{sessionError} Pages will show their own error states; no data is fabricated.</p>
            </div>
          )}
          <main className="content" id="main" tabIndex={-1} key={sessionVersion}>{content}</main>
        </div>
      </div>
      <ToastRegion toasts={toasts} />
    </SessionContext.Provider>
  );
}
