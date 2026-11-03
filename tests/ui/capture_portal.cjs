/* Real browser checks. No application routes or responses are mocked. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'build/student-portal/preview.json')));
const phase = process.argv[2];
const output = path.join(root, 'docs/ui/student-portal', phase);
fs.mkdirSync(output, { recursive: true });
const widths = [1440, 768, 390, 320];
const id = fixture.ids;
const groups = {
  'UI-03': [['appointments', '/appointments/'], ['appointment-new', '/appointments/new'],
    ['appointment-detail', '/appointments/' + id.pending], ['appointment-invitation', '/appointments/' + id.invitation],
    ['appointment-private', '/appointments/' + id.private, 403], ['appointment-invalid', '/appointments/999999999', 409]],
  'UI-04': [['rooms', '/rooms/'], ['room-new', '/rooms/new'], ['room-detail', '/rooms/' + id.room],
    ['room-pending', '/rooms/' + id.roomPending], ['room-revise', '/rooms/' + id.roomPending + '/revise'],
    ['room-series', '/rooms/' + id.roomSeries], ['room-availability', '/rooms/availability/302?date=2030-01-08'],
    ['room-invalid', '/rooms/availability/302?date=invalid', 409], ['room-forbidden', '/rooms/configuration', 403]],
  'UI-05': [['equipment', '/equipment/'], ['equipment-catalog', '/equipment/catalog?start=2030-01-07T10:00&due=2030-01-09T10:00'],
    ['equipment-loan', '/equipment/' + id.loan], ['equipment-request', '/equipment/' + id.borrowPending],
    ['equipment-series', '/equipment/' + id.equipmentSeries]],
  'UI-06': [['waiting', '/waiting-lists/'], ['waiting-detail', '/waiting-lists/' + id.queue], ['waiting-policy', '/waiting-lists/policy']],
  'UI-07': [['feedback', '/feedback/'], ['feedback-new', '/feedback/new/equipment/' + id.loan], ['feedback-detail', '/feedback/' + id.report]],
  'UI-08': [['calendar-month', '/calendar/?view=month&date=2030-01-07'], ['calendar-week', '/calendar/?view=week&date=2030-01-07'],
    ['calendar-day', '/calendar/?view=day&date=2030-01-07'], ['schedule', '/appointments/calendar?month=2030-01&week=2030-01-07'],
    ['inbox', '/notifications/']],
};
async function login(page, role = 'student') {
  const username = role === 'student' ? fixture.users['1'] : role === 'empty' ? fixture.users['5'] :
    role === 'professor' ? fixture.users['2'] : role === 'staff' ? fixture.users['7'] : fixture.users['6'];
  await page.goto(fixture.url + '/login');
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(fixture.password);
  await Promise.all([page.waitForURL(url => !url.pathname.endsWith('/login')),
    page.locator('button[type=submit]').click()]);
}
async function geometry(page, width, name) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), width, name + ': horizontal overflow');
  assert.equal(await page.locator('h1').count(), 1, name + ': primary heading');
  await page.locator('a[href="#main-content"]').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'main-content');
  for (let step = 0; step < 10; step++) {
    await page.keyboard.press('Tab');
    const focus = await page.evaluate(() => {
      const target = document.activeElement;
      const box = target.getBoundingClientRect();
      const fragments = Array.from(target.getClientRects());
      return { tag: target.tagName, text: target.textContent.trim().slice(0, 70), x:box.x, w:box.width, h:box.height,
        outline: getComputedStyle(target).outlineStyle,
        visible: fragments.every(fragment => {
          const hit = document.elementFromPoint(fragment.x + fragment.width/2, fragment.y + fragment.height/2);
          return hit === target || target.contains(hit);
        }) };
    });
    if (focus.tag === 'BODY') continue;
    assert.ok(focus.w > 0 && focus.h > 0, name + ': hidden focus ' + JSON.stringify(focus));
    assert.ok(focus.x >= -1 && focus.x + focus.w <= width + 1, name + ': focus bounds ' + JSON.stringify(focus));
    assert.notEqual(focus.outline, 'none', name + ': focus outline ' + JSON.stringify(focus));
    assert.ok(focus.visible, name + ': obscured focus ' + JSON.stringify(focus));
  }
  await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
}
async function capture(page, name, url, width, expected = 200) {
  await page.setViewportSize({ width, height: 900 });
  const response = await page.goto(fixture.url + url);
  assert.equal(response.status(), expected, name + ': status');
  assert.ok(!(await page.locator('body').innerText()).includes('PRIVATE unrelated'), name + ': privacy');
  await geometry(page, width, name);
  await page.screenshot({ path:path.join(output, `${name}-${width}.png`), fullPage:true });
}
async function loginPhase(browser, errors, results) {
  const page = await browser.newPage();
  page.on('pageerror', error => errors.push(error.message));
  for (const width of widths) {
    await capture(page, 'login', '/login', width);
    await page.locator('button[type=submit]').click();
    assert.ok(await page.locator('[name=username]').evaluate(el => !el.validity.valid));
    await page.locator('[name=username]').fill('fictional-unknown-account');
    await page.locator('[name=password]').fill('wrong-credentials');
    await page.locator('#show-password').check();
    assert.equal(await page.locator('[name=password]').getAttribute('type'), 'text');
    await page.locator('#show-password').uncheck();
    const response = await Promise.all([page.waitForResponse(res => res.url().includes('/login') && res.request().method() === 'POST'),
      page.locator('button[type=submit]').click()]);
    assert.equal(response[0].status(), 401);
    await page.locator('[role=alert]').waitFor();
    await page.waitForFunction(() => document.activeElement.id === 'sign-in-error');
    assert.equal(await page.locator('[name=password]').inputValue(), '');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'sign-in-error');
    await geometry(page, width, 'login-error');
    await page.screenshot({ path:path.join(output, `login-error-${width}.png`), fullPage:true });
    assert.equal((await page.request.post(fixture.url + '/login', {form:{username:'missing',password:'missing'}})).status(), 400);
    results.push(`${width}px: empty/invalid/server-error, show password, escaped values, CSRF, keyboard focus and overflow passed`);
  }
  await page.close();
  for (const role of ['student', 'professor', 'staff', 'admin']) {
    const context = await browser.newContext();
    const member = await context.newPage();
    await login(member, role);
    const expected = role === 'student' ? '/student/' : role === 'admin' ? '/' : '/appointments/';
    assert.equal(new URL(member.url()).pathname, expected, role + ': redirect');
    assert.equal((await member.request.post(fixture.url + '/logout')).status(), 400);
    await member.locator('[data-account-menu] summary').click();
    await Promise.all([member.waitForURL('**/login'), member.locator('form[action="/logout"] button').click()]);
    assert.equal((await member.request.get(fixture.url + '/student/', { maxRedirects:0 })).status(), 302);
    results.push(role + ': real authentication, role redirect, protected CSRF logout and session cleared');
    await context.close();
  }
}
(async () => {
  const browser = await chromium.launch({ headless:true, ...(process.env.CHROMIUM_EXECUTABLE ?
    {executablePath:process.env.CHROMIUM_EXECUTABLE} : {channel:'msedge'}) });
  const errors = [], results = [];
  try {
    if (phase === 'UI-02') await loginPhase(browser, errors, results);
    else {
      assert.ok(groups[phase], 'Unknown phase');
      for (const role of ['student', 'empty']) {
        const context = await browser.newContext();
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(error.message));
        await login(page, role);
        const pages = role === 'empty' ? groups[phase].filter(([name]) =>
          ['appointments','rooms','equipment','waiting','feedback','calendar-month','inbox'].includes(name)) : groups[phase];
        for (const [name, url, expected] of pages) {
          for (const width of widths) await capture(page, (role === 'empty' ? 'empty-' : '') + name, url, width, expected || 200);
          const forms = await page.locator('form[method=post]').evaluateAll(forms => forms.map(form => ({
            action:new URL(form.getAttribute('action') || location.href, location.href).href,
            csrf:form.querySelector('[name=csrf_token]')?.value })));
          for (const form of forms) {
            assert.ok(form.csrf, name + ': missing CSRF input');
            assert.equal((await page.request.post(form.action)).status(), 400, name + ': missing CSRF rejected');
          }
          results.push(`${role}/${name}: 1440/768/390/320px, status, privacy, keyboard, focus, overflow, POST CSRF passed`);
        }
        await context.close();
      }
    }
    assert.deepEqual(errors, [], 'Browser JavaScript errors');
    const report = {phase, results, browserErrors:errors, screenshots:fs.readdirSync(output).filter(name => name.endsWith('.png'))};
    fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
