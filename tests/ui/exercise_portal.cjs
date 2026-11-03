/* Mutating acceptance flows against synthetic records in the owned review schema. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'build/student-portal/preview.json')));
const phase = process.argv[2];
const output = path.join(root, 'docs/ui/student-portal', phase);
const results = [];
async function login(page, actor=1) {
  await page.goto(fixture.url + '/login');
  await page.locator('[name=username]').fill(fixture.users[String(actor)]);
  await page.locator('[name=password]').fill(fixture.password);
  await Promise.all([page.waitForNavigation(), page.locator('button[type=submit]').click()]);
}
async function submit(page, locator) {
  const [response] = await Promise.all([page.waitForNavigation(), locator.click()]);
  assert.ok(response.status() < 400, 'Form submission failed: ' + response.status());
}
async function screenshot(page, name) {
  await page.screenshot({path:path.join(output, name + '-workflow.png'), fullPage:true});
}
async function appointments(page, context) {
  await page.goto(fixture.url + '/appointments/new');
  await page.locator('[name=facultyId]').selectOption(String(fixture.ids.faculty));
  await page.locator('[data-picker=professorIds] summary').click();
  await page.locator('[name=professorIds][value="2"]').check();
  await page.locator('[name=professorIds][value="3"]').check();
  await page.locator('[data-picker=invitedIds] summary').click();
  await page.locator('[name=invitedIds][value="4"]').check();
  await page.locator('[name=purpose]').fill('Fictional browser appointment acceptance');
  await page.locator('[name=appointmentDate]').fill('2030-01-14');
  await page.locator('[name=appointmentDate]').press('Tab');
  await page.locator('.appointment-choice').first().waitFor();
  await page.locator('.appointment-choice').first().click();
  assert.ok(await page.locator('[name=start]').inputValue());
  await page.locator('[name=duration]').fill('45');
  assert.equal(await page.locator('[name=start]').inputValue(), '');
  assert.ok(await page.locator('#submit-appointment').isDisabled());
  await page.locator('.appointment-choice').first().waitFor();
  await screenshot(page, 'available-times');
  await context.setOffline(true);
  await page.locator('#find-times').click();
  await page.locator('#times-message[role=alert]').waitFor();
  assert.equal(await page.locator('[name=start]').inputValue(), '');
  assert.ok(await page.locator('#submit-appointment').isDisabled());
  await screenshot(page, 'availability-offline');
  await context.setOffline(false);
  await page.locator('.manual-time summary').click();
  await page.locator('#manual-time').fill('13:00');
  await submit(page, page.locator('#submit-appointment'));
  assert.match(await page.locator('#approval-progress').innerText(), /0 of 2/);
  assert.match(await page.locator('main').innerText(), /Student Noor/);
  await screenshot(page, 'appointment-submitted');
  const appointmentUrl = page.url();
  const reschedule = page.locator('form[action$="/reschedule"]');
  await reschedule.locator('[name=start]').fill('2030-01-14T14:00');
  await submit(page, reschedule.locator('button'));
  assert.equal(await page.locator('[name=revision]').first().inputValue(), '2');
  assert.match(await page.locator('#approval-progress').innerText(), /0 of 2/);
  await submit(page, page.locator('form[action$="/cancel"] button'));
  assert.match(await page.locator('main').innerText(), /Cancelled/);
  assert.equal(await page.locator('form[action$="/reschedule"]').count(), 0);
  await page.goto(fixture.url + '/appointments/' + fixture.ids.invitation);
  assert.equal(await page.locator('form[action$="/cancel"]').count(), 0);
  assert.equal(await page.locator('form[action$="/reschedule"]').count(), 0);
  await submit(page, page.locator('form[action$="/decline-invitation"] button'));
  assert.match(await page.locator('main').innerText(), /Declined/);
  await page.goto(fixture.url + '/appointments/' + fixture.ids.pending);
  const existing = page.locator('form[action$="/reschedule"]');
  await existing.locator('[name=start]').fill('2030-01-07T11:00');
  await submit(page, existing.locator('button'));
  assert.match(await page.locator('#approval-progress').innerText(), /0 of 2/);
  assert.equal((await page.request.get(fixture.url + '/appointments/availability')).status(), 403);
  const csrf = await page.locator('[name=csrf_token]').first().inputValue();
  const invalid = await page.request.post(fixture.url + '/appointments/new', {form:{csrf_token:csrf,
    facultyId:String(fixture.ids.faculty), professorIds:'2', purpose:'Invalid outside hours', duration:'30',
    appointmentDate:'2030-01-14', start:'2030-01-14T18:00'}});
  assert.equal(invalid.status(), 409);
  results.push('Multiple professors and optional student invitation submitted through real form; recommendations loaded; changed input cleared selection; offline error disabled submission; manual proposal accepted; reschedule reset approvals; cancellation persisted; invitee decline preserved organizer controls; mandatory office hours and private availability access enforced.');
  results.push('Synthetic browser-created appointment: ' + new URL(appointmentUrl).pathname);
}
async function rooms(page, context) {
  await page.goto(fixture.url + '/rooms/new');
  await page.locator('[name=purpose]').fill('Fictional browser room acceptance');
  await page.locator('[name=start]').fill('2030-01-09T13:00');
  await page.locator('details summary').filter({hasText:'Register student participants'}).click();
  await page.locator('[name=participantIds][value="4"]').check();
  await page.locator('details summary').filter({hasText:'Invite professors'}).click();
  await page.locator('[name=professorIds][value="2"]').check();
  await page.locator('.room-candidate').first().waitFor();
  await page.locator('[name=count]').fill('6');
  assert.equal(await page.locator('[name=roomId]').inputValue(), '');
  assert.ok(await page.locator('#submit-room').isDisabled());
  await page.locator('.room-candidate').first().waitFor();
  const calendarUrl = await page.locator('.room-candidate-option > a').first().getAttribute('href');
  const availability = await page.request.get(calendarUrl);
  assert.equal(availability.status(), 200);
  assert.ok(!(await availability.text()).includes('PRIVATE unrelated'));
  await screenshot(page, 'ranked-room-candidates');
  await context.setOffline(true);
  await page.locator('#find-rooms').click();
  await page.locator('#room-message[role=alert]').waitFor();
  assert.equal(await page.locator('[name=roomId]').inputValue(), '');
  assert.ok(await page.locator('#submit-room').isDisabled());
  await screenshot(page, 'room-offline');
  await context.setOffline(false);
  await page.locator('#find-rooms').click();
  await page.locator('.room-candidate').first().waitFor();
  await submit(page, page.locator('#submit-room'));
  assert.match(await page.locator('main').innerText(), /Pending Faculty Approval/);
  assert.match(await page.locator('main').innerText(), /Student Noor/);
  assert.match(await page.locator('main').innerText(), /Professor Ada/);
  assert.equal(await page.locator('form[action$="/decision"]').count(), 0);
  await screenshot(page, 'room-submitted');
  const requestUrl = page.url();
  await page.locator('a[href$="/revise"]').click();
  await page.locator('[name=purpose]').fill('Fictional browser room revised');
  await page.locator('.room-candidate').first().waitFor();
  await submit(page, page.locator('#submit-room'));
  assert.match(await page.locator('main').innerText(), /Revision 2/i);
  await submit(page, page.locator('form[action$="/cancel"] button'));
  assert.match(await page.locator('main').innerText(), /Cancelled/);
  await page.goto(fixture.url + '/rooms/new');
  await page.locator('[name=purpose]').fill('Fictional impossible room size');
  await page.locator('[name=start]').fill('2030-01-09T15:00');
  await page.locator('[name=count]').fill('1000');
  await page.locator('#find-rooms').click();
  await page.waitForFunction(() => document.querySelector('#room-candidates').getAttribute('aria-busy') === 'false' &&
    !document.querySelector('#room-message').textContent.includes('Checking'));
  assert.equal(await page.locator('.room-candidate').count(), 0);
  assert.ok(await page.locator('#submit-room').isDisabled());
  await screenshot(page, 'room-unavailable');
  await page.goto(fixture.url + '/rooms/' + fixture.ids.roomSeries);
  const occurrenceForm = page.locator('form[action*="/occurrences/"]').last();
  await submit(page, occurrenceForm.locator('button'));
  assert.match(await page.locator('main').innerText(), /Cancelled/);
  results.push('Real ranked-room form with actual registered student and optional professor; busy/free link; changed input cleared candidate; offline error blocked stale submission; submit/revise/cancel preserved review and revision; unavailable capacity blocked submission; future recurring occurrence cancelled through authorized form.');
  results.push('Synthetic browser-created room request: ' + new URL(requestUrl).pathname);
}
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ?
    {executablePath:process.env.CHROMIUM_EXECUTABLE} : {channel:'msedge'})});
  const errors = [];
  try {
    const context = await browser.newContext({viewport:{width:390,height:900}});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await login(page);
    if (phase === 'UI-03') await appointments(page, context);
    else if (phase === 'UI-04') await rooms(page, context);
    else throw new Error('Unknown workflow phase ' + phase);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'workflow-results.json'), JSON.stringify({phase, results, browserErrors:errors}, null, 2) + '\n');
    console.log(JSON.stringify({phase, results, browserErrors:errors}, null, 2));
    await context.close();
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
