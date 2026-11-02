/* Keyboard, privacy, and shared-shell checks against the real preview app. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'build/ui01/preview.json')));

async function login(page, username) {
  await page.goto(fixture.url + '/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(fixture.password);
  await Promise.all([page.waitForURL(url => !url.pathname.endsWith('/login')),
    page.locator('button[type=submit]').click()]);
}

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : { channel: 'msedge' }) });
  const results = [];
  try {
    const page = await browser.newPage();
    await login(page, 'ui01-student');
    for (const width of [1440, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(fixture.url + '/student/?week=' + fixture.week);
      const navigation = page.locator('.app-navigation');
      assert.equal(await navigation.locator('a').count(), 4);
      await page.locator('.notification-toggle').click();
      await page.locator('.notification-status').filter({ hasText: /unread updates|caught up/ }).waitFor();
      const box = await page.locator('#notification-panel').boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width + 1, 'Notification horizontal bounds ' + width);
      assert.ok(box.y + box.height <= 844, 'Notification vertical bounds ' + width);
      if (width <= 800) {
        const navbox = await navigation.boundingBox();
        assert.ok(box.y + box.height <= navbox.y, 'Notification covered by bottom nav ' + width);
      }
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(() => document.activeElement.className), 'notification-toggle');
      assert.equal(await page.locator('#notification-panel').isVisible(), false);
      await page.locator('[data-account-menu] summary').click();
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('[data-account-menu]').getAttribute('open'), null);
      assert.equal(await page.evaluate(() => document.activeElement.tagName), 'SUMMARY');
      await navigation.locator('a[href$="#my-activity"]').focus();
      await Promise.all([page.waitForURL('**/student/#my-activity', { waitUntil: 'domcontentloaded' }),
        page.keyboard.press('Enter')]);
      assert.equal(await page.evaluate(() => document.activeElement.id), 'my-activity');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width);
      results.push(width + 'px: four navigation links, notification bounds/Escape, account Escape, keyboard Activity anchor passed');
    }
    await page.goto(fixture.url + '/student/?week=' + fixture.week);
    await page.locator('.notification-toggle').click();
    const mark = page.locator('[data-mark-all]');
    await page.locator('.notification-status').filter({ hasText: /unread updates|caught up/ }).waitFor();
    if (await mark.isEnabled()) {
      await mark.click();
      await page.locator('.notification-status').filter({ hasText: 'You are all caught up.' }).waitFor();
    }
    await page.reload();
    const feed = await (await page.request.get(fixture.url + '/notifications/feed')).json();
    assert.equal(feed.unreadCount, 0);
    assert.equal((await page.request.get(fixture.url + '/appointments/availability')).status(), 403);
    await page.goto(fixture.url + '/student/?week=' + fixture.week);
    await page.locator('.skip-link').focus();
    for (let index = 0; index < 38; index++) {
      const focus = await page.evaluate(() => {
        const target = document.activeElement;
        const bounds = target.getBoundingClientRect();
        // Wrapped inline links have blank space in their union bounding box.
        // Hit-test a painted line fragment, not that inter-line whitespace.
        const fragments = Array.from(target.getClientRects());
        const unobscured = fragments.every(fragment => {
          const hit = document.elementFromPoint(fragment.x + fragment.width / 2, fragment.y + fragment.height / 2);
          return target === hit || target.contains(hit);
        });
        return { tag: target.tagName, cls: target.className, href: target.getAttribute('href'),
          text: target.textContent.trim(), x: bounds.x, y: bounds.y,
          w: bounds.width, h: bounds.height, outline: getComputedStyle(target).outlineStyle,
          unobscured };
      });
      if (focus.tag !== 'BODY') {
        assert.ok(focus.w > 0 && focus.h > 0, 'Focused hidden target ' + JSON.stringify(focus));
        assert.ok(focus.x >= -1 && focus.x + focus.w <= 321, 'Focus horizontal bounds ' + JSON.stringify(focus));
        assert.notEqual(focus.outline, 'none', 'Missing keyboard focus ' + JSON.stringify(focus));
        assert.ok(focus.unobscured, 'Keyboard focus obscured by another element ' + JSON.stringify(focus));
      }
      await page.keyboard.press('Tab');
    }
    results.push('Mark-all-read persists; private professor availability denied; 38 keyboard focus steps have visible outlines and unobscured line fragments');
    await page.close();
    for (const role of ['professor', 'staff', 'admin']) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const other = await context.newPage();
      await login(other, 'ui01-' + role);
      assert.equal(await other.locator('.student-shell').count(), 0);
      await other.locator('[data-navigation-toggle]').click();
      assert.equal(await other.locator('#app-sidebar').getAttribute('role'), 'dialog');
      await other.keyboard.press('Escape');
      assert.equal(await other.locator('#app-sidebar').isVisible(), false);
      assert.equal(await other.evaluate(() => document.activeElement.hasAttribute('data-navigation-toggle')), true);
      results.push(role + ': original mobile drawer/Escape/focus works');
      await context.close();
    }
    const report = JSON.stringify({ results }, null, 2) + '\n';
    fs.writeFileSync(path.join(root, 'docs/ui/student-portal-ui01/controls-results.json'), report);
    console.log(report);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
