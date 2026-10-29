import { expect, test } from '@playwright/test';
import { apiRun, apiSession, gotoRoute, resetLab, waitForSession } from './helpers';

// FR-06: horizontal-overflow regression. The previous release shipped
// mobile screenshots that were 537px wide for 320/390 viewports —
// direct evidence of content wider than the viewport. This spec
// measures, on every page at every width, the real layout facts
// (innerWidth, clientWidth, scrollWidth) and names every element whose
// box extends past the viewport's right edge, instead of trusting a
// screenshot's pixel size. No overflow is ever masked with
// overflow-x:hidden on the document.
const PAGES = [
  'overview',
  'investigation',
  'scenarios',
  'policy',
  'comparison',
  'findings',
  'evidence',
  'reports',
  'settings',
] as const;

const VIEWPORTS = [
  { name: '320', width: 320, height: 700 },
  { name: '390x844', width: 390, height: 844 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '1440x900', width: 1440, height: 900 },
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
  test(`no horizontal overflow @ ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto('/');
    await waitForSession(page);
    // Replay needs a real run id for a populated page.
    const runId = await page.evaluate(async () => {
      const res = await fetch('/api/v1/runs', {
        headers: { 'X-Lab-Session': sessionStorage.getItem('agentboundary.labSessionToken') ?? '' },
      });
      const data = await res.json();
      const runs = Array.isArray(data) ? data : (data.runs ?? []);
      return runs[0]?.id as string | undefined;
    });
    const routes: string[] = [...PAGES];
    if (runId) routes.push(`replay:${runId}`);
    for (const route of routes) {
      await gotoRoute(page, route);
      await page.waitForLoadState('networkidle');
      const probe = await page.evaluate(() => {
        const de = document.documentElement;
        const offenders: string[] = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        let node: Element | null;
        while ((node = walker.nextNode() as Element | null)) {
          const el = node as HTMLElement;
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          if (
            rect.width === 0 ||
            rect.height === 0 ||
            style.display === 'none' ||
            style.visibility === 'hidden'
          ) {
            continue;
          }
          // A wide table inside .table-wrap (overflow-x:auto) scrolls
          // within its container — that is intended responsive behavior,
          // not page overflow. Only elements that escape to the document
          // level count as offenders.
          let contained = false;
          let anc: Element | null = el.parentElement;
          while (anc && anc !== document.body) {
            const ox = window.getComputedStyle(anc).overflowX;
            if (ox === 'auto' || ox === 'scroll') {
              contained = true;
              break;
            }
            anc = anc.parentElement;
          }
          if (contained) continue;
          if (rect.right > window.innerWidth + 1) {
            const cls = el.className && typeof el.className === 'string' ? `.${el.className.split(' ').join('.')}` : '';
            offenders.push(
              `${el.tagName.toLowerCase()}${cls} right=${Math.round(rect.right)} left=${Math.round(rect.left)} width=${Math.round(rect.width)} text=${(el.textContent ?? '').trim().slice(0, 60)}`,
            );
          }
        }
        return {
          innerWidth: window.innerWidth,
          clientWidth: de.clientWidth,
          scrollWidth: de.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
          offenders: offenders.slice(0, 12),
        };
      });
      expect(
        probe.scrollWidth,
        `${route} @ ${vp.name}: document scrollWidth ${probe.scrollWidth} > clientWidth ${probe.clientWidth} (innerWidth ${probe.innerWidth}); offenders: ${probe.offenders.join(' | ')}`,
      ).toBeLessThanOrEqual(probe.clientWidth + 1);
      expect(
        probe.bodyScrollWidth,
        `${route} @ ${vp.name}: body scrollWidth ${probe.bodyScrollWidth} > clientWidth ${probe.clientWidth}; offenders: ${probe.offenders.join(' | ')}`,
      ).toBeLessThanOrEqual(probe.clientWidth + 1);
      expect(
        probe.offenders,
        `${route} @ ${vp.name}: elements past the viewport edge`,
      ).toEqual([]);
    }
  });
}
