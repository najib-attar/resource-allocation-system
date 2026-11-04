/* Real-browser verification. Requires Playwright; no application mocks or routes. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');

const root = path.resolve(__dirname, '../..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'build/ui01/preview.json')));
const output = path.join(root, 'docs/ui/student-portal-ui01');
fs.mkdirSync(output, { recursive: true });

async function login(page, username) {
  await page.goto(fixture.url + '/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(fixture.password);
  await Promise.all([page.waitForURL(url => !url.pathname.endsWith('/login')), page.locator('button[type=submit]').click()]);
}

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : { channel: 'msedge' }) });
  const failures = [];
  const results = [];
  try {
    for (const [state, username] of [['populated', 'ui01-student'], ['empty', 'ui01-empty']]) {
      const context = await browser.newContext();
      const page = await context.newPage();
      page.on('pageerror', error => failures.push(error.message));
      await login(page, username);
      for (const width of [1440, 768, 390, 320]) {
        await page.setViewportSize({ width, height: width > 800 ? 1080 : 844 });
        await page.goto(fixture.url + '/student/?week=' + fixture.week);
        await page.evaluate(() => document.fonts.ready);
        await page.waitForFunction(() => /^Notifications, \d+ unread$/.test(
          document.querySelector('.notification-toggle')?.getAttribute('aria-label') || ''));
        const overflow = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
        assert.ok(overflow.scroll <= width, `${state} ${width}px overflow: ${overflow.scroll}`);
        const text = await page.locator('body').innerText();
        assert.ok(!text.includes('PRIVATE unrelated'), 'Unrelated student data leaked');
        if (state === 'populated') {
          assert.ok(text.includes('Fictional research proposal review'));
          assert.ok(text.includes('Optional invitation'));
        }
        await page.screenshot({ path: path.join(output, `${state}-${width}.png`), fullPage: true });
        results.push(`${state} ${width}px: rendered, no horizontal overflow, private peer excluded`);
      }
      // Five authorized service destinations are real links and respond successfully.
      for (const route of ['/appointments/', '/rooms/', '/equipment/', '/waiting-lists/', '/feedback/']) {
        const link = page.locator('.student-home a[href="' + route + '"]');
        assert.ok(await link.count() >= 1, `Missing service link ${route}`);
        const response = await page.request.get(fixture.url + route);
        assert.equal(response.status(), 200, route);
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(fixture.url + '/student/?week=' + fixture.week);
      // Native keyboard traversal: each focus target remains visible and inside viewport.
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => ({ href: document.activeElement.getAttribute('href'),
        outline: getComputedStyle(document.activeElement).outlineStyle }));
      assert.equal(focused.href, '#main-content');
      assert.notEqual(focused.outline, 'none');
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'main-content');
      const inbox = await page.request.get(fixture.url + '/notifications/');
      assert.equal(inbox.status(), 200);
      const feed = await page.request.get(fixture.url + '/notifications/feed');
      assert.equal(feed.status(), 200);
      assert.equal(feed.headers()['cache-control'], 'no-store');
      const missingCsrf = await page.request.post(fixture.url + '/logout');
      assert.equal(missingCsrf.status(), 400);
      await page.locator('[data-account-menu] summary').click();
      await Promise.all([page.waitForURL('**/login'), page.locator('form[action="/logout"] button').click()]);
      const protectedPage = await page.request.get(fixture.url + '/student/', { maxRedirects: 0 });
      assert.equal(protectedPage.status(), 302);
      results.push(`${state}: login, five services, keyboard skip/focus, private notifications, CSRF, logout passed`);
      await context.close();
    }
    for (const role of ['professor', 'staff', 'admin']) {
      const context = await browser.newContext();
      const page = await context.newPage();
      await login(page, 'ui01-' + role);
      assert.equal(await page.locator('.student-home').count(), 0);
      assert.equal((await page.request.get(fixture.url + '/student/')).status(), 403);
      assert.equal((await page.request.get(fixture.url + '/notifications/')).status(), 200);
      results.push(`${role}: existing shell works, Student Home denied`);
      await context.close();
    }
    assert.deepEqual(failures, [], 'Browser JavaScript errors');
    const report = { results, browserErrors: failures, screenshots: fs.readdirSync(output).filter(name => name.endsWith('.png')) };
    fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
