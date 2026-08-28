const { chromium } = require('/Users/liaowang/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const consoleProblems = [];
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) consoleProblems.push(`${message.type()}: ${message.text()}`);
  });
  page.on('pageerror', (error) => consoleProblems.push(`pageerror: ${error.message}`));
  const login = await context.request.post('http://127.0.0.1:8765/api/auth/dev-login', {
    data: { account: 'local-admin' },
  });
  if (!login.ok()) throw new Error(`dev login failed: ${login.status()}`);
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });
  await page.locator('[data-workspace-tab="competitor"]').click();
  await page.locator('[data-competitor-company][value="3HK"]').check({ force: true });
  await page.locator('[data-competitor-metric]').selectOption('5g_population_coverage');
  await page.locator('[name="competitor-years"][value="99"]').check({ force: true });
  await page.waitForTimeout(400);
  await page.locator('#competitorResult details').evaluate((element) => { element.open = true; });
  const singleYearText = await page.locator('#competitorResult').innerText();
  if (!singleYearText.includes('99') || !singleYearText.includes('2021')) {
    throw new Error(`single-year official value not rendered: ${singleYearText.slice(0, 800)}`);
  }
  if (await page.locator('#competitorResult a', { hasText: '官方来源' }).count() < 1) {
    throw new Error('single-year official source link not rendered');
  }
  await page.screenshot({ path: 'artifacts/ui-qa/competitor-3hk-single-year.png', fullPage: true });

  await page.locator('[data-competitor-clear]').click();
  await page.waitForTimeout(700);
  await page.locator('[data-competitor-company][value="NTT Group"]').check({ force: true });
  await page.locator('[data-competitor-metric]').selectOption('adjusted_ebitda');
  await page.locator('[name="competitor-years"][value="99"]').check({ force: true });
  await page.waitForTimeout(400);
  await page.locator('#competitorResult details').evaluate((element) => { element.open = true; });
  const nttText = await page.locator('#competitorResult').innerText();
  if (!nttText.includes('3,183.3') || !nttText.includes('3,423.3') || !nttText.includes('2016') || !nttText.includes('2025')) {
    throw new Error(`NTT official series not rendered: ${nttText.slice(0, 1200)}`);
  }
  await page.screenshot({ path: 'artifacts/ui-qa/competitor-ntt-ebitda.png', fullPage: true });

  await page.locator('[data-workspace-tab="ai"]').click();
  await page.locator('#chatInput').fill('中国联通 FY2016 EBITDA和净利润是多少？请说明来源数量。');
  await page.locator('#chatSubmitButton').click();
  await page.waitForFunction(() => {
    const text = document.querySelector('#messages')?.innerText || '';
    const submit = document.querySelector('#chatSubmitButton');
    return submit?.getAttribute('aria-label') === '发送' && !text.includes('正在回复');
  }, null, { timeout: 120000 }).catch(() => {});
  const aiText = await page.locator('#messages').innerText();
  await page.screenshot({ path: 'artifacts/ui-qa/xiaojing-unicom-2016.png', fullPage: true });
  console.log(JSON.stringify({
    singleYearRendered: true,
    nttTenYearRendered: true,
    xiaojingAnswered: aiText.includes('794.98') && aiText.includes('6.25'),
    xiaojingSourceCountMentioned: /1个来源|单一官方来源|1 个来源/.test(aiText),
    xiaojingText: aiText.slice(-2400),
    consoleProblems,
  }));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
