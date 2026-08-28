const { chromium } = require('/Users/liaowang/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const consoleProblems = [];
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) consoleProblems.push(`${message.type()}: ${message.text()}`);
  });
  await context.request.post('http://127.0.0.1:8765/api/auth/dev-login', { data: { account: 'local-admin' } });
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });
  await page.locator('[data-workspace-tab="competitor"]').click();
  await page.locator('[data-competitor-company][value="3HK"]').check({ force: true });
  await page.locator('[data-competitor-metric]').selectOption('5g_population_coverage');
  await page.locator('[name="competitor-years"][value="99"]').check({ force: true });
  await page.waitForTimeout(500);
  const geometry = await page.evaluate(() => ({
    viewport: innerWidth,
    bodyWidth: document.body.scrollWidth,
    panelWidth: document.querySelector('[data-workspace-panel="competitor"]')?.scrollWidth || 0,
    rendered: (document.querySelector('#competitorResult')?.innerText || '').includes('99'),
  }));
  await page.screenshot({ path: 'artifacts/ui-qa/competitor-3hk-single-year-mobile.png', fullPage: true });
  console.log(JSON.stringify({ ...geometry, consoleProblems }));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
