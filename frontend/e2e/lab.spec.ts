import { expect, test } from '@playwright/test';
import { apiRun, apiSession, gotoRoute, resetLab, switchPersona, waitForSession } from './helpers';

// Every test starts from a privileged fresh reset so runs from one test can
// never leak into another test's assertions. R-06: these resets hit ONLY
// the isolated test backend's temp database (see playwright.config.ts);
// the developer's demo DB is never touched. The test DB is reset fresh
// again after the whole file by the final test's teardown (see bottom).
test.beforeEach(async ({ request, page }) => {
  await resetLab(request);
  await page.goto('/');
  await waitForSession(page);
});

test('cold start: privileged reset leaves an honest zero state with a first-run affordance', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'No scenarios have been run yet' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run first protected scenario' })).toBeVisible();
  // Zero state must not fabricate metrics: no verdict chart section renders.
  await expect(page.getByRole('heading', { name: 'Verdict distribution' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Run first protected scenario' }).click();
  await expect(page.getByRole('heading', { name: 'Attack Scenario Studio' })).toBeVisible();
});

test('persona switch: Cedar after Northstar shows no Northstar data, even with a delayed response', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A1');
  // The overview mounted during beforeEach (empty); reload so it refetches
  // after the API-seeded run exists.
  await page.reload();
  await waitForSession(page);
  await expect(page.locator('main')).toContainText(run.id);

  // Delay the next overview response: the old tenant's data must vanish
  // synchronously on switch, before the delayed new response resolves.
  await page.route('**/api/v1/overview', async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.selectOption('#persona-select', 'analyst_cedar');
  await expect(page.locator('#persona-select')).toHaveValue('analyst_cedar');
  // Mid-flight: old Northstar run gone well before the 1.5s response lands.
  await expect(page.locator('main')).not.toContainText(run.id, { timeout: 3000 });
  // After the delayed Cedar response resolves, still no Northstar content.
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).not.toContainText(run.id);
  await expect(page.locator('main')).not.toContainText('INC-2051');
  await page.unroute('**/api/v1/overview');

  // Session restore across reload: Cedar session survives a reload.
  await page.reload();
  await waitForSession(page);
  await expect(page.locator('#persona-select')).toHaveValue('analyst_cedar');
  await expect(page.locator('main')).not.toContainText(run.id);
  await expect(page.locator('main')).not.toContainText('INC-2051');
});

test('run A1 via Scenario Studio and inspect its real events in Replay', async ({ page }) => {
  await gotoRoute(page, 'scenarios');
  const card = page.locator('article', { hasText: 'Scenario A1' }).first();
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Run protected scenario' }).click();
  await expect(card.getByText(/PASS/)).toBeVisible();
  const runId = (await card.locator('.mono').first().innerText()).trim();
  expect(runId).toMatch(/^run-a1-/);

  await gotoRoute(page, `replay:${runId}`);
  await expect(page.getByRole('heading', { name: 'Interactive Agent Attack Replay' })).toBeVisible();
  await expect(page.locator('main')).toContainText(runId);
  // Real stored events, not a badge: the timeline names tools and decisions.
  await expect(page.locator('main')).toContainText('get_alert');
  await expect(page.locator('main')).toContainText('read_case');

  // Overview joins the recent-runs projection to the full /runs record, so
  // identities and adapter are real here — and the Scripted mode filter
  // must keep (not empty) the scripted run in the recent list.
  await gotoRoute(page, 'overview');
  await expect(page.locator('main')).toContainText('Operator (logged-in lab session): analyst_northstar');
  await expect(page.locator('main')).toContainText('Simulated actor (authority under test): analyst_northstar');
  await expect(page.locator('main')).toContainText('SCRIPTED LAB SIMULATION');
  await page.getByRole('button', { name: 'Scripted', exact: true }).click();
  await expect(page.locator('main')).toContainText(runId);
});

test('run A2: INC-2048 stays investigating on the Investigation page', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A2');
  expect(run.verdict).toBe('PASS');

  await gotoRoute(page, 'investigation');
  await expect(page.locator('select[aria-label="Choose a case"]')).toHaveValue('INC-2048');
  // The authoritative check is the case status from the backend, rendered here.
  await expect(page.locator('main')).toContainText('Status: investigating');
});

test('A6 approval flow: event sequence APPROVAL_REQUIRED, ALLOW, then APPROVAL_USED denial', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A6');
  expect(run.verdict).toBe('PASS');

  await gotoRoute(page, `replay:${run.id}`);
  const text = await page.locator('main').innerText();
  const iRequired = text.indexOf('APPROVAL_REQUIRED');
  const iAllow = text.indexOf('ALLOW');
  const iUsed = text.indexOf('APPROVAL_USED');
  expect(iRequired).toBeGreaterThan(-1);
  expect(iAllow).toBeGreaterThan(iRequired);
  expect(iUsed).toBeGreaterThan(iAllow);
  // The approved isolation executed exactly once as a synthetic-lab action.
  await expect(page.locator('main')).toContainText('Executed tool (synthetic lab only)');
  await expect(page.locator('main')).toContainText('Completed: yes');
});

test('cross-tenant case view: Cedar requesting INC-2048 gets denial handling, never the case body', async ({ page }) => {
  await switchPersona(page, 'analyst_cedar');
  await gotoRoute(page, 'investigation');
  await page.locator('select[aria-label="Choose a case"]').selectOption('INC-2048');
  // Denial surfaces as an error region; the case detail never renders.
  await expect(page.getByRole('alert').first()).toBeVisible();
  await expect(page.locator('main')).not.toContainText('Status: investigating');
  await expect(page.locator('main')).not.toContainText('Status: closed');
  await expect(page.locator('main')).not.toContainText('CEDAR-CONFIDENTIAL-SENTINEL-7F3A');
});

test('comparison page with unmatched exports is honestly NOT comparable', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  await apiRun(request, token, 'A1'); // A1 has no matching weak export.
  await gotoRoute(page, 'comparison');
  await expect(page.getByRole('heading', { name: 'Not comparable — no matched pairs' })).toBeVisible();
  await expect(page.locator('main')).toContainText('Unmatched protected runs');
});

test('report downloads parse: JSON contains run id + verdict, Markdown contains scenario id', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A1');
  await gotoRoute(page, `reports`);

  const [jsonDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download JSON report' }).click(),
  ]);
  const jsonPath = await jsonDownload.path();
  const json = JSON.parse((await import('node:fs')).readFileSync(jsonPath!, 'utf-8'));
  expect(json.run.id).toBe(run.id);
  expect(json.run.verdict).toBe('PASS');

  const [mdDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download Markdown report' }).click(),
  ]);
  const mdPath = await mdDownload.path();
  const md = (await import('node:fs')).readFileSync(mdPath!, 'utf-8');
  expect(md).toContain('A1');
  expect(md).toContain(run.id);
});

test('expired session: an invalidated token shows the expired-session UI, never stale data', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A1');
  // Reload so the overview refetches after the API-seeded run exists.
  await page.reload();
  await waitForSession(page);
  await expect(page.locator('main')).toContainText(run.id);

  // Invalidate the stored token, then reload: the app validates the stored
  // session against the backend and must show the expired banner, not data.
  await page.addInitScript(() => {
    sessionStorage.setItem('agentboundary.labSessionToken', 'bogus-expired-token');
    sessionStorage.setItem('agentboundary.labPersona', JSON.stringify({ id: 'analyst_northstar' }));
  });
  await page.reload();
  await expect(page.getByText('Lab session expired — please sign in to the lab session again.')).toBeVisible();
  await expect(page.locator('main')).not.toContainText(run.id);
});

test('privileged reset: analyst sees it disabled with an explanation; commander dry-run + confirm works', async ({ page, request }) => {
  // Analyst (default session) cannot reset.
  await gotoRoute(page, 'settings');
  const previewBtn = page.getByRole('button', { name: 'Preview lab reset' });
  await expect(previewBtn).toBeDisabled();
  await expect(page.locator('main')).toContainText('Only the Incident Commander lab-admin persona can reset the lab');

  // Seed a run so the dry-run preview has something to count.
  const token = await apiSession(request, 'analyst_northstar');
  await apiRun(request, token, 'A1');

  await switchPersona(page, 'incident_commander');
  await gotoRoute(page, 'settings');
  await expect(page.getByRole('button', { name: 'Preview lab reset' })).toBeEnabled();
  await page.getByRole('button', { name: 'Preview lab reset' }).click();
  await expect(page.getByRole('heading', { name: 'Reset preview — nothing has been deleted yet' })).toBeVisible();
  // Nothing deleted by the preview: the run is still visible on overview.
  await gotoRoute(page, 'overview');
  await expect(page.locator('main')).toContainText('run-a1-');
  await gotoRoute(page, 'settings');
  await page.getByRole('button', { name: 'Preview lab reset' }).click();
  await page.getByRole('button', { name: 'Yes, reset the lab' }).click();
  await expect(page.getByText(/Lab reset complete/)).toBeVisible();
  await gotoRoute(page, 'overview');
  await expect(page.getByRole('heading', { name: 'No scenarios have been run yet' })).toBeVisible();
});

test('keyboard-only: Tab to a Run button, focus-visible ring present, Enter runs A1', async ({ page }) => {
  await gotoRoute(page, 'scenarios');
  await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => {});
  let focusedRunButton = false;
  for (let i = 0; i < 60 && !focusedRunButton; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return { tag: '', text: '' };
      const cs = getComputedStyle(el);
      return {
        tag: el.tagName,
        text: (el.textContent ?? '').trim().slice(0, 40),
        outlineStyle: cs.outlineStyle,
        outlineWidth: cs.outlineWidth,
      };
    });
    if (info.tag === 'BUTTON' && info.text.includes('Run protected scenario')) {
      focusedRunButton = true;
      // Focus-visible ring must actually render (design token: info-blue ring).
      expect(info.outlineStyle).not.toBe('none');
      expect(info.outlineWidth).not.toBe('0px');
    }
  }
  expect(focusedRunButton).toBeTruthy();
  await page.keyboard.press('Enter');
  await expect(page.locator('article', { hasText: 'Scenario A1' }).first().getByText(/PASS/)).toBeVisible();
});

test.afterAll(async ({ request }) => {
  // Leave the TEST database fresh, regardless of test runs above.
  // (R-06: this reset is scoped to the isolated test backend only.)
  await resetLab(request);
});
