import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { apiRun, apiSession, gotoRoute, resetLab, waitForSession } from './helpers';

test.beforeEach(async ({ request, page }) => {
  await resetLab(request);
  await page.goto('/');
  await waitForSession(page);
});

test.afterAll(async ({ request }) => {
  await resetLab(request);
});

// Zero critical/serious axe violations on ALL TEN pages (R-18). Minor
// violations, if any appear, must be reported honestly — never suppressed
// via rule disabling in this file. investigation/policy/comparison/
// findings/evidence/reports render their empty/populated states here;
// replay is covered separately with a real run below.
const PAGES = ['overview', 'investigation', 'scenarios', 'policy', 'comparison', 'findings', 'evidence', 'reports', 'settings'] as const;

for (const route of PAGES) {
  test(`axe: ${route} has no critical or serious violations`, async ({ page }) => {
    await gotoRoute(page, route);
    const results = await new AxeBuilder({ page }).analyze();
    const bad = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
    expect(bad, JSON.stringify(bad, null, 2)).toEqual([]);
  });
}

// N9-06: keyboard operability is not covered by axe. Tabbing from the
// top of the Overview page must land on real interactive controls
// (persona selector, nav links, buttons) — never trap focus on a
// non-interactive element, and focus must stay visible (no outline:none
// without a replacement is checked by the axe run above).
test('keyboard: tab reaches interactive controls on overview', async ({ page }) => {
  await gotoRoute(page, 'overview');
  await page.keyboard.press('Tab');
  const tags: string[] = [];
  for (let i = 0; i < 12; i++) {
    const tag = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? el.tagName.toLowerCase() : 'none';
    });
    tags.push(tag);
    await page.keyboard.press('Tab');
  }
  const interactive = tags.filter((t) =>
    ['a', 'button', 'select', 'input', 'textarea'].includes(t),
  );
  expect(interactive.length).toBeGreaterThan(2);
  expect(tags).not.toContain('none');
});

test('axe: replay page with a real run has no critical or serious violations', async ({ page, request }) => {
  const token = await apiSession(request, 'analyst_northstar');
  const run = await apiRun(request, token, 'A1');
  await gotoRoute(page, `replay:${run.id}`);
  const results = await new AxeBuilder({ page }).analyze();
  const bad = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
  expect(bad, JSON.stringify(bad, null, 2)).toEqual([]);
});
