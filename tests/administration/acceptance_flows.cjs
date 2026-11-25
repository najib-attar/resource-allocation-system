/* Live beta acceptance using distinct authenticated browser contexts. */
const assert = require('node:assert/strict');
const {go, login, submit, ids} = require('../professor/browser_review.cjs');

async function meeting(browser) {
  const {page: student, context: studentSession} = await login(browser, 1);
  const {page: professor, context: professorSession} = await login(browser, 2);
  const purpose = 'Supervisor consultation';
  try {
    await go(student, '/appointments/new');
    await student.locator('[name=facultyId]').selectOption(String(ids.faculty));
    await student.locator('[data-picker=professorIds] summary').click();
    await student.locator('[name=professorIds][value="2"]').check();
    await student.locator('[name=purpose]').fill(purpose);
    await student.locator('[name=appointmentDate]').fill('2030-01-14');
    await student.locator('[name=appointmentDate]').press('Tab');
    await student.locator('.appointment-choice').first().click();
    await submit(student, student.locator('#submit-appointment'));
    assert.match(await student.locator('#approval-progress').innerText(), /0 of 1/);
    const appointment = new URL(student.url()).pathname;
    assert.match(appointment, /^\/appointments\/\d+$/);
    await go(professor, '/notifications/');
    const notice = professor.locator('main .is-unread a').filter({hasText: purpose});
    assert.equal(await notice.getAttribute('href'), appointment);
    await notice.click();
    await professor.waitForURL(url => url.pathname === appointment);
    await submit(professor, professor.locator('button[name=decision][value=approve]'));
    assert.match(await professor.locator('#approval-progress').innerText(), /1 of 1/);
    for (const page of [student, professor]) {
      await go(page, '/calendar/?view=day&date=2030-01-14');
      const event = page.locator('.calendar-agenda a.calendar-event').filter({hasText: purpose});
      assert.equal(await event.getAttribute('href'), appointment);
      assert.match(await event.innerText(), /Personal commitment/);
      assert.match(await event.locator('.calendar-state').innerText(), /Confirmed/i);
    }
  } finally {
    await studentSession.close();
    await professorSession.close();
  }
}

async function exam(browser, admin) {
  const {page: professor, context} = await login(browser, 2);
  const title = 'Synthetic systems examination';
  const day = '/calendar/?view=day&date=2030-01-08&scope=published';
  try {
    await go(professor, '/professor/requests/new?type=Exam');
    for (const [name, value] of Object.entries({
      title, purpose:'Course examination', courseCode:'SYN101', courseName:'Systems',
      participantCount:'5', startTime:'13:00', endTime:'14:00'
    })) await professor.locator('[name=' + name + ']').fill(value);
    await professor.locator('[name=examType]').selectOption('Final');
    await professor.locator('[name=spaceId]').selectOption('302');
    await professor.locator('[name=day]').selectOption('2');
    await submit(professor, professor.locator('main form button[type=submit]'));
    const detail = new URL(professor.url()).pathname;
    assert.match(detail, /^\/professor\/requests\/\d+$/);
    const key = detail.split('/').at(-1);
    assert.match(await professor.locator('main').innerText(), /Pending Eligibility Review/);
    await go(admin, '/academic-eligibility/' + key);
    await admin.locator('[name=reason]').fill('Examination declaration reviewed');
    await submit(admin, admin.locator('button[value=approve]'));
    await go(professor, detail);
    assert.match(await professor.locator('main').innerText(), /Examination declaration reviewed/);
    assert.equal(await professor.locator('article.academic-allocation').count(), 0);
    async function allocate() {
      await go(admin, '/');
      await submit(admin, admin.locator('form[action="/run-allocation"] button'));
      return new URL(admin.url()).searchParams;
    }
    const unbound = await allocate();
    assert.equal(unbound.get('run_status'), 'error');
    assert.match(unbound.get('run_message'), /unresolved calendar dates/);
    await go(admin, '/appointments/calendar-setup');
    await admin.locator('[name=periodName]').fill('Exam week');
    await admin.locator('[name=fromDate]').fill('2030-01-07');
    await admin.locator('[name=untilDate]').fill('2030-01-13');
    await admin.locator('[name=requestId]').selectOption(key);
    await admin.locator('[name=weekStart]').fill('2030-01-07');
    await submit(admin, admin.locator('main form button'));
    const outcome = await allocate();
    assert.equal(outcome.get('run_status'), 'success', outcome.get('run_message'));
    await go(professor, detail);
    assert.equal(await professor.locator('article.academic-allocation h3').innerText(), 'Study Studio');
    await go(professor, day);
    assert.equal(await professor.locator('.calendar-event').filter({hasText:title}).count(), 0);
    await go(admin, '/calendar/publications');
    const form = admin.locator('main form').filter({has:admin.locator('[name=id][value="' + key + '"]')});
    await form.locator('[name=visibility]').selectOption('published');
    await form.locator('[name=instructor]').selectOption('2');
    await submit(admin, form.locator('button'));
    await go(professor, day);
    const event = professor.locator('.calendar-agenda a.calendar-event').filter({hasText:title});
    assert.match(await event.innerText(), /Study Studio/);
    await event.click();
    await professor.waitForURL(url => url.pathname === '/calendar/academic/' + key);
    assert.match(await professor.locator('main').innerText(), /2030-01-08 13:00/);
    assert.match(await professor.locator('main').innerText(), /Study Studio/);
  } finally {
    await context.close();
  }
}

module.exports = {meeting, exam};
