import type { APIRequestContext, Page } from '@playwright/test';
import { expect } from '@playwright/test';

// R-06: the API base comes from the isolated Playwright config, which
// always sets AGENTBOUNDARY_E2E_API_BASE to the test backend's own port.
// The :8000 fallback exists only so helpers stay importable outside a
// Playwright run (e.g. typechecking); no spec may rely on it, and the
// isolated config never leaves it in effect during a test run.
export const API =
  process.env.AGENTBOUNDARY_E2E_API_BASE ?? 'http://127.0.0.1:8000/api/v1';

/** Create a lab session for a persona via the real API; returns its token. */
export async function apiSession(request: APIRequestContext, personaId: string): Promise<string> {
  const res = await request.post(`${API}/lab/session`, { data: { persona_id: personaId } });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return body.session_token as string;
}

/** Privileged reset (incident_commander only) — returns the lab to a fresh seed. */
export async function resetLab(request: APIRequestContext): Promise<void> {
  const token = await apiSession(request, 'incident_commander');
  const res = await request.post(`${API}/lab/reset`, {
    headers: { 'X-Lab-Session': token },
    data: { confirm: true },
  });
  expect(res.ok()).toBeTruthy();
}

/** Run one scenario through the real API as the given persona's session. */
export async function apiRun(
  request: APIRequestContext,
  token: string,
  scenarioId: string,
): Promise<{ id: string; verdict: string }> {
  const res = await request.post(`${API}/runs`, {
    headers: { 'X-Lab-Session': token },
    data: { scenario_id: scenarioId },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  return { id: body.id as string, verdict: body.verdict as string };
}

/** Wait until the app has established a lab session (persona selector populated). */
export async function waitForSession(page: Page): Promise<void> {
  await expect(page.locator('#persona-select')).toBeVisible();
  await page.waitForFunction(() => {
    const sel = document.querySelector<HTMLSelectElement>('#persona-select');
    return !!sel && sel.options.length > 0 && sel.value !== '';
  });
}

/** Switch persona via the top-bar selector and wait for the switch to settle. */
export async function switchPersona(page: Page, personaId: string): Promise<void> {
  await page.selectOption('#persona-select', personaId);
  await expect(page.locator('#persona-select')).toHaveValue(personaId);
  // The app clears old-session state synchronously on switch; wait for the
  // new session's data round-trip to finish before asserting page content.
  await page.waitForLoadState('networkidle');
}

/** Navigate by hash route and wait for the page heading to render. */
export async function gotoRoute(page: Page, route: string): Promise<void> {
  await page.goto(`/#/${route}`);
  await waitForSession(page);
}
