import { expect, test } from '@playwright/test';
import { apiRun, apiSession, gotoRoute, resetLab, switchPersona, waitForSession } from './helpers';

// T10-03: the report download must not outlive a persona switch.
// The gate below is installed with addInitScript (fetch-level), because
// route interception cannot split "headers arrived" from "body still
// streaming": the patched fetch returns the real response headers at
// once, then holds the body until the test releases it. That is the
// exact window the old code left unprotected (it untracked the
// download on headers, before blob()).
const GATE_SCRIPT = `(() => {
  const origFetch = window.fetch.bind(window);
  let release = null;
  window.__reportBodyGate = new Promise((r) => { release = r; });
  window.__releaseReportBody = () => { if (release) release(); };
  window.fetch = async (...args) => {
    const res = await origFetch(...args);
    const url = String(args[0]);
    if (!url.includes('/reports/') || !res.body) return res;
    const reader = res.body.getReader();
    const stream = new ReadableStream({
      async pull(controller) {
        await window.__reportBodyGate;
        const { done, value } = await reader.read();
        if (done) controller.close();
        else controller.enqueue(value);
      },
    });
    return new Response(stream, { status: res.status, headers: res.headers });
  };
})();`;

test('T10-03: a Northstar report held mid-body is discarded on switch to Cedar, and a fresh Northstar download still works', async ({ page, request }) => {
  await resetLab(request);
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A1');

  await page.addInitScript(GATE_SCRIPT);
  await page.goto('/');
  await waitForSession(page);
  await gotoRoute(page, 'reports');
  await expect(page.getByRole('button', { name: 'Download JSON report' })).toBeVisible();
  await expect(page.locator('main')).toContainText(run.id);

  // Listen BEFORE clicking: a download event after the switch is the failure.
  const noDownload = page.waitForEvent('download', { timeout: 5000 }).then(
    () => 'downloaded',
    () => 'none',
  );
  // Register before the click: the local request fires within
  // milliseconds, and a waitForRequest registered after it would miss it.
  const requestPromise = page.waitForRequest('**/api/v1/reports/**');
  await page.getByRole('button', { name: 'Download JSON report' }).click();
  // The report request has started and its headers have arrived; the
  // body is parked on the gate. Switch personas in exactly that window.
  await requestPromise;
  await page.waitForTimeout(300);
  await switchPersona(page, 'analyst_cedar');
  await expect(page.locator('#persona-select')).toHaveValue('analyst_cedar');
  // Release the OLD body: it must not download under the new persona.
  await page.evaluate(() => (window as unknown as { __releaseReportBody: () => void }).__releaseReportBody());
  await expect.poll(async () => noDownload, { timeout: 6000 }).toBe('none');
  expect(await noDownload).toBe('none');
  await expect(page.locator('main')).not.toContainText('Downloaded agentboundary-run');
  await expect(page.locator('#persona-select')).toHaveValue('analyst_cedar');

  // Rapid Northstar -> Cedar -> Northstar: back as Northstar, the same
  // run's report downloads normally (the gate is already released, so
  // the fresh download streams without delay).
  await switchPersona(page, 'analyst_northstar');
  await gotoRoute(page, 'reports');
  await expect(page.getByRole('button', { name: 'Download JSON report' })).toBeVisible();
  const downloadPromise = page.waitForEvent('download', { timeout: 10000 });
  await page.getByRole('button', { name: 'Download JSON report' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^agentboundary-run-.*\.json$/);

  await resetLab(request);
});
