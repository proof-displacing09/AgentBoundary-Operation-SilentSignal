import { test } from '@playwright/test';
import { apiRun, apiSession, gotoRoute, resetLab, waitForSession } from './helpers';

// Screenshot evidence for manual visual inspection (the parent reviews the
// PNGs; this spec only captures them deterministically). One seeded A1 run
// so replay/scenarios pages show real data instead of empty states.
const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
  { name: '320', width: 320, height: 700 },
] as const;

test.beforeAll(async ({ request }) => {
  await resetLab(request);
  const token = await apiSession(request, 'analyst_northstar');
  await apiRun(request, token, 'A1');
});

test.afterAll(async ({ request }) => {
  await resetLab(request);
});

for (const vp of VIEWPORTS) {
  test(`screenshots @ ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('/');
    await waitForSession(page);
    await page.waitForLoadState('networkidle');

    await gotoRoute(page, 'overview');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `e2e/screenshots/overview-${vp.name}.png`, fullPage: true });

    await gotoRoute(page, 'scenarios');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `e2e/screenshots/scenarios-${vp.name}.png`, fullPage: true });

    await gotoRoute(page, 'replay');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `e2e/screenshots/replay-${vp.name}.png`, fullPage: true });
  });
}
