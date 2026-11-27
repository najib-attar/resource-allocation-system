/* Browser acceptance for the owned, opt-in group meeting pilot. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright-core');

const range = [1440, 1024, 768, 390, 320];
const scenarios = [
    { actor: 1, role: 'Student', required: [4], cohosts: [], optional: [2] },
    { actor: 3, role: 'Instructor', required: [1, 4], cohosts: [], optional: [2] },
    { actor: 5, role: 'Research Assistant', required: [4], cohosts: [1], optional: [2] },
    { actor: 6, role: 'Staff', required: [3, 4], cohosts: [1], optional: [2] },
];
const onlinePurpose = 'Pilot browser online group';
const flexiblePurpose = 'Pilot browser flexible original';
const refusedPurpose = 'Pilot browser declined replacement';
const movedPurpose = 'Pilot browser accepted move';
const physicalPurpose = 'Pilot browser physical group';
const instructorRoomPurpose = 'Pilot browser instructor room group';

async function visit(page, url, expected = 200) {
    const response = await page.goto(url);
    assert.equal(response.status(), expected, url);
    return response;
}

async function click(page, locator, status = 200, keyboard = false) {
    if (keyboard) await locator.focus();
    const [response] = await Promise.all([
        page.waitForNavigation(), keyboard ? page.keyboard.press('Enter') : locator.click(),
    ]);
    assert.equal(response.status(), status, page.url());
    return response;
}

async function login(browser, fixture, id) {
    const account = fixture.accounts.find(entry => entry.id === id);
    assert.ok(account, 'Missing fictional account ' + id);
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await visit(page, fixture.url + '/login');
    await page.locator('#username').fill(account.username);
    await page.locator('#password').fill(account.password);
    await click(page, page.getByRole('button', { name: 'Sign in' }));
    assert.notEqual(new URL(page.url()).pathname, '/login');
    return { context, page, errors };
}

async function choosePeople(page, name, ids) {
    for (const id of ids) {
        const choice = page.locator('input[name="' + name + '"][value="' + id + '"]');
        if (!await choice.isVisible()) {
            const summary = choice.locator('xpath=ancestor::details').locator('summary');
            await summary.focus();
            await page.keyboard.press('Enter');
        }
        assert.ok(await choice.isVisible());
        await choice.focus();
        await page.keyboard.press('Space');
        assert.ok(await choice.isChecked());
    }
}

function localDate(fixture, days = 0) {
    return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Istanbul' })
        .format(new Date(new Date(fixture.starts).getTime() + days * 86400000));
}

async function plan(page, fixture, { required, cohosts = [], optional = [], date, room, facilities = [] }) {
    const pageResult = await visit(page, fixture.url + '/meetings/new');
    assert.equal(pageResult.headers()['cache-control'], 'private, no-store');
    await choosePeople(page, 'requiredIds', required);
    await choosePeople(page, 'cohostIds', cohosts);
    await choosePeople(page, 'optionalIds', optional);
    if (date) {
        await page.getByLabel('First date').fill(date);
        await page.getByLabel('Last date').fill(date);
    }
    if (room) await page.getByLabel('Location').selectOption(String(room));
    for (const facility of facilities) await page.getByRole('checkbox', { name: facility }).check();
    await click(page, page.getByRole('button', { name: 'Find times' }), 200, true);
    for (const [name, ids] of [['requiredIds', required], ['cohostIds', cohosts], ['optionalIds', optional]]) {
        const values = await page.locator('input[name="' + name + '"]:checked').evaluateAll(
            nodes => nodes.map(node => Number(node.value)).sort((a, b) => a - b));
        assert.deepEqual(values, [...ids].sort((a, b) => a - b), name);
    }
}

async function measure(page) {
    const observed = {};
    for (const width of range) {
        await page.setViewportSize({ width, height: 1000 });
        const view = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth,
            cramped: [...document.querySelectorAll('.meeting-choice')].some(choice =>
                choice.querySelector('.meeting-choice-text').getBoundingClientRect().width
                    < choice.getBoundingClientRect().width * 0.7) }));
        assert.equal(view.viewport, width);
        assert.ok(view.content <= width, 'Horizontal overflow at ' + width + ': ' + view.content);
        assert.ok(!view.cramped, 'Meeting option text is squeezed at ' + width);
        observed[width] = view.content;
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    return observed;
}

async function submitPlan(page, purpose, { conditional = false, flexible = false, join } = {}) {
    const options = page.getByRole('region', { name: conditional ? 'Options requiring one move' : 'Direct options' });
    const selection = options.getByRole('radio').first();
    assert.ok(await selection.isVisible(), 'Expected a verified option for ' + purpose);
    await selection.check();
    await options.getByLabel('Purpose').fill(purpose);
    if (flexible) await options.getByRole('checkbox', { name: /considered for a move/ }).check();
    if (join) await options.getByLabel('HTTPS join link').fill(join);
    await click(page, options.getByRole('button', { name: 'Request meeting' }));
    const route = new URL(page.url()).pathname;
    assert.match(route, /^\/meetings\/\d+$/);
    const content = page.locator('#main-content');
    assert.match(await page.locator('body').innerText(), /Pending Approval/);
    return { route, content };
}

async function response(page, fixture, route, button) {
    await visit(page, fixture.url + route);
    await click(page, page.getByRole('button', { name: button, exact: true }));
}

async function verifyCalendar(page, fixture, route, date, purpose) {
    await visit(page, fixture.url + '/calendar/?view=day&date=' + date);
    await page.locator('a[href="' + route + '"]:visible').filter({ hasText: purpose }).first().waitFor();
}

async function verifyPreferences(page, fixture, output, record = false) {
    const result = await visit(page, fixture.url + '/meetings/preferences');
    assert.equal(result.headers()['cache-control'], 'private, no-store');
    if (record) {
        await page.locator('input[name=desired_gap]').fill('33');
        await click(page, page.getByRole('button', {name: 'Save preferences'}));
        assert.equal(await page.locator('input[name=desired_gap]').inputValue(), '33');
    }
    await page.locator('input[name=allow_relocation]').check();
    await click(page, page.getByRole('button', {name: 'Save availability'}));
    assert.ok(await page.locator('input[name=allow_relocation]').isChecked());
    if (record) {
        const widths = await measure(page);
        await page.setViewportSize({ width: 390, height: 1000 });
        await page.screenshot({ path: path.join(output, 'group-meeting-preferences-mobile.png') });
        await page.setViewportSize({ width: 1440, height: 1000 });
        return widths;
    }
}

async function verifyOnline(users, fixture, output, checks) {
    const organizer = users.get(6).page;
    const date = localDate(fixture);
    await plan(organizer, fixture, { required: [3, 4], cohosts: [1], optional: [2], date });
    const direct = organizer.getByRole('region', { name: 'Direct options' });
    const ticket = await direct.getByRole('radio').first().inputValue();
    const outsider = users.get(7);
    await visit(outsider.page, fixture.url + '/meetings/new');
    const csrf = await outsider.page.locator('input[name=csrf_token]').first().inputValue();
    const forged = await outsider.context.request.post(fixture.url + '/meetings/submit', {
        form: { csrf_token: csrf, ticket, purpose: 'Forged meeting' },
    });
    assert.equal(forged.status(), 403);
    const { route } = await submitPlan(organizer, onlinePurpose, { join: 'https://example.invalid/group-meeting' });
    assert.equal(await organizer.getByRole('link', { name: 'Open the organizer\'s join link' }).count(), 0);
    const recipient = users.get(3).page;
    await visit(recipient, fixture.url + '/notifications/?kind=group_meeting');
    const notice = recipient.getByRole('link').filter({ hasText: onlinePurpose }).first();
    assert.equal(await notice.getAttribute('href'), route);
    await recipient.screenshot({ path: path.join(output, 'group-meeting-inbox-desktop.png') });
    await click(recipient, notice);
    await click(recipient, recipient.getByRole('button', { name: 'Approve revision' }));
    assert.match(await recipient.locator('body').innerText(), /Pending Approval/);
    const optional = users.get(2);
    await visit(optional.page, fixture.url + route);
    const optionalCsrf = await optional.page.locator('input[name=csrf_token]').first().inputValue();
    const optionalApproval = await optional.context.request.post(fixture.url + route + '/response', {
        form: { csrf_token: optionalCsrf, revision: '1', action: 'approve' },
    });
    assert.equal(optionalApproval.status(), 403);
    await click(optional.page, optional.page.getByRole('button', { name: 'Decline invitation' }));
    await response(users.get(1).page, fixture, route, 'Approve revision');
    await response(users.get(4).page, fixture, route, 'Approve revision');
    await visit(organizer, fixture.url + route);
    assert.match(await organizer.locator('body').innerText(), /Confirmed/);
    assert.equal(await organizer.getByRole('link', { name: 'Open the organizer\'s join link' }).getAttribute('href'),
        'https://example.invalid/group-meeting');
    await organizer.screenshot({ path: path.join(output, 'confirmed-group-meeting-desktop.png') });
    await visit(outsider.page, fixture.url + route, 403);
    await visit(outsider.page, fixture.url + '/notifications/?kind=group_meeting');
    assert.equal(await outsider.page.getByText(onlinePurpose).count(), 0);
    for (const id of [6, 3, 4, 1]) await verifyCalendar(users.get(id).page, fixture, route, date, onlinePurpose);
    checks.online = { route, members: [6, 3, 4, 1], optional: 2, forgedTicket: 403, unauthorizedDetail: 403,
        optionalApproval: 403, privateInbox: true, confirmedCalendar: date };
}

async function verifyRelocation(users, fixture, output, checks) {
    const organizer = users.get(1).page;
    const guest = users.get(4).page;
    const date = localDate(fixture, 1);
    checks.preferenceWidths = await verifyPreferences(users.get(6).page, fixture, output, true);
    await verifyPreferences(organizer, fixture, output);
    await verifyPreferences(guest, fixture, output);
    await plan(organizer, fixture, { required: [4], date });
    const original = await submitPlan(organizer, flexiblePurpose, { flexible: true });
    await response(guest, fixture, original.route, 'Approve revision');
    await visit(organizer, fixture.url + original.route);
    const originalTime = await organizer.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
    await plan(organizer, fixture, { required: [4], date });
    const refused = await submitPlan(organizer, refusedPurpose, { conditional: true });
    await visit(guest, fixture.url + '/meetings/preferences');
    await guest.locator('input[name=allow_relocation]').uncheck();
    await click(guest, guest.getByRole('button', { name: 'Save availability' }));
    await visit(guest, fixture.url + refused.route);
    assert.match(await guest.locator('#main-content').innerText(), /original meeting or its availability changed/);
    assert.equal(await guest.getByRole('button', { name: 'Consent to replacement', exact: true }).count(), 0);
    await response(guest, fixture, refused.route, 'Refuse relocation');
    assert.match(await guest.locator('#main-content').innerText(), /original meeting remains in place/);
    await verifyPreferences(guest, fixture, output);
    await visit(organizer, fixture.url + original.route);
    assert.equal(await organizer.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText(), originalTime);
    await visit(organizer, fixture.url + refused.route);
    await click(organizer, organizer.getByRole('link', { name: 'Find another arrangement' }));
    assert.equal(new URL(organizer.url()).searchParams.get('retry'), refused.route.split('/').at(-1));
    assert.ok(await organizer.locator('input[name="requiredIds"][value="4"]').isChecked());
    await plan(organizer, fixture, { required: [4], optional: [5], date });
    const conditional = organizer.getByRole('region', { name: 'Options requiring one move' });
    await conditional.screenshot({ path: path.join(output, 'group-meeting-relocation-options.png') });
    const moved = await submitPlan(organizer, movedPurpose, { conditional: true });
    const originalLink = moved.content.getByRole('link', { name: flexiblePurpose, exact: true });
    assert.equal(await originalLink.getAttribute('href'), original.route);
    assert.match(await moved.content.innerText(), /Replacement time \d{4}-\d{2}-\d{2} \d{2}:\d{2} – \d{4}-\d{2}-\d{2} \d{2}:\d{2}/);
    assert.ok((await moved.content.innerText()).includes(originalTime));
    const optional = users.get(5).page;
    await visit(optional, fixture.url + moved.route);
    assert.match(await optional.locator('#main-content').innerText(), /A separate relocation decision/i);
    assert.equal(await optional.locator('#main-content').getByText(flexiblePurpose, { exact: true }).count(), 0);
    assert.equal(await optional.getByRole('button', { name: 'Consent to replacement', exact: true }).count(), 0);
    await response(organizer, fixture, moved.route, 'Consent to replacement');
    await response(guest, fixture, moved.route, 'Approve revision');
    assert.match(await guest.locator('body').innerText(), /Pending Approval/);
    await visit(organizer, fixture.url + original.route);
    assert.equal(await organizer.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText(), originalTime);
    await response(guest, fixture, moved.route, 'Consent to replacement');
    assert.match(await guest.locator('body').innerText(), /Confirmed/);
    await guest.screenshot({ path: path.join(output, 'confirmed-relocation-desktop.png') });
    await visit(organizer, fixture.url + original.route);
    const movedTime = await organizer.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
    assert.notEqual(movedTime, originalTime);
    assert.match(await organizer.locator('#main-content').innerText(), /Meeting moved with all affected required consents/);
    await verifyCalendar(organizer, fixture, moved.route, date, movedPurpose);
    await verifyCalendar(guest, fixture, moved.route, date, movedPurpose);
    checks.relocation = { original: original.route, refused: refused.route, confirmed: moved.route,
        before: originalTime, after: movedTime, movedOnlyAfter: 'all affected consents and required approvals' };
}

async function verifyPhysical(users, fixture, output, checks) {
    const organizer = users.get(1).page;
    const faculty = users.get(6).page;
    const guest = users.get(3).page;
    let date = localDate(fixture, 2);
    await visit(organizer, fixture.url + '/rooms/new');
    await organizer.getByLabel('Activity').selectOption('meeting');
    await organizer.getByLabel('Total attendees').fill('2');
    await organizer.getByLabel('Purpose', { exact: true }).fill('Pilot browser room hold');
    await organizer.getByLabel('Duration (minutes)').fill('30');
    await organizer.getByRole('checkbox', { name: 'Projector' }).check();
    async function roomsFor(start) {
        const refresh = organizer.waitForResponse(value => value.url().endsWith('/rooms/candidates') && value.ok());
        await organizer.getByLabel('Date and start time').fill(start);
        await organizer.getByRole('button', { name: 'Refresh rooms' }).click();
        return (await refresh).json();
    }
    const relocatedStart = checks.relocation.after.slice(0, 16).replace(' ', 'T');
    const conflict = await roomsFor(relocatedStart);
    assert.equal(conflict.candidates.length, 0, 'An existing group commitment must block a legacy room booking.');
    let opening;
    for (const time of ['09:00', '11:00', '15:00', '16:00']) {
        const candidates = await roomsFor(date + 'T' + time);
        if (candidates.candidates.length) {
            opening = candidates.candidates[0].localStart;
            break;
        }
    }
    assert.ok(opening, 'Expected an available slot in the ordinary room service.');
    date = opening.slice(0, 10);
    await click(organizer, organizer.getByRole('button', { name: 'Submit for faculty approval' }));
    const roomRoute = new URL(organizer.url()).pathname;
    assert.match(roomRoute, /^\/rooms\/\d+$/);
    await visit(faculty, fixture.url + roomRoute);
    await click(faculty, faculty.getByRole('button', { name: 'Recheck and approve' }));
    assert.match(await faculty.locator('body').innerText(), /Confirmed/);
    await plan(organizer, fixture, { required: [3], date, room: Number(roomRoute.split('/').at(-1)), facilities: ['Projector'] });
    const { route } = await submitPlan(organizer, physicalPurpose);
    await response(guest, fixture, route, 'Approve revision');
    assert.match(await guest.locator('body').innerText(), /Confirmed/);
    assert.match(await guest.locator('#main-content').innerText(), /Approved room booking/);
    assert.match(await guest.locator('#main-content').innerText(), /Rehearsal teaching room/);
    await guest.screenshot({ path: path.join(output, 'confirmed-physical-meeting-desktop.png') });
    await verifyCalendar(organizer, fixture, route, date, physicalPurpose);
    await verifyCalendar(guest, fixture, route, date, physicalPurpose);
    await visit(organizer, fixture.url + roomRoute);
    await click(organizer, organizer.getByRole('button', { name: 'Cancel and release reservation' }), 409);
    assert.match(await organizer.locator('body').innerText(), /Cancel the confirmed group meeting before releasing its room/);
    checks.physical = { route, approvedRoom: roomRoute, calendar: date, linkedCancellation: 409,
        groupCalendarBlockedLegacyRoom: true };
}

async function verifyStandaloneReplacement(users, fixture, output, checks) {
    const organizer = users.get(6).page;
    const route = checks.online.route;
    const reschedule = route + '/reschedule';
    const arrangement = page => page.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
    await visit(organizer, fixture.url + route);
    const original = await arrangement(organizer);
    await click(organizer, organizer.getByRole('link', { name: 'Rescheduling and replacement approvals' }), 200, true);
    await visit(users.get(7).page, fixture.url + reschedule, 403);

    async function propose() {
        await visit(organizer, fixture.url + reschedule);
        await click(organizer, organizer.getByRole('button', { name: 'Find replacement times' }), 200, true);
        const options = organizer.getByRole('region', { name: 'Replacement options' });
        await measure(organizer);
        await options.getByRole('radio').first().check();
        await click(organizer, options.getByRole('button', { name: 'Propose replacement' }));
        assert.match(await organizer.getByRole('region', { name: 'Replacement proposal' }).innerText(),
            /1 of 4 required approvals recorded/);
        await visit(organizer, fixture.url + route);
        assert.equal(await arrangement(organizer), original);
    }

    await propose();
    await response(users.get(3).page, fixture, reschedule, 'Decline replacement');
    assert.match(await users.get(3).page.getByRole('region', { name: 'Rescheduling history' }).innerText(), /Declined/);
    await visit(organizer, fixture.url + route);
    assert.equal(await arrangement(organizer), original);
    await propose();
    await response(users.get(3).page, fixture, reschedule, 'Approve replacement');
    await response(users.get(1).page, fixture, reschedule, 'Approve replacement');
    const guest = users.get(4).page;
    await visit(guest, fixture.url + reschedule);
    const widths = await measure(guest);
    await guest.setViewportSize({ width: 390, height: 1000 });
    await guest.screenshot({ path: path.join(output, 'replacement-review-mobile.png') });
    await guest.setViewportSize({ width: 1440, height: 1000 });
    await visit(organizer, fixture.url + route);
    assert.equal(await arrangement(organizer), original);
    await response(guest, fixture, reschedule, 'Approve replacement');
    assert.match(await guest.getByRole('region', { name: 'Rescheduling history' }).innerText(), /Applied/);
    await guest.screenshot({ path: path.join(output, 'replacement-applied-desktop.png') });
    await visit(organizer, fixture.url + route);
    const updated = await arrangement(organizer);
    assert.notEqual(updated, original);
    for (const id of [6, 3, 1, 4]) {
        await verifyCalendar(users.get(id).page, fixture, route, updated.slice(0, 10), onlinePurpose);
    }
    checks.replacement = { route: reschedule, original, updated, unchangedUntilFinalApproval: true, widths };
}

async function verifyRoomSearch(users, fixture, output, checks) {
    const organizer = users.get(3);
    const approver = users.get(6).page;
    const guest = users.get(5).page;
    await plan(organizer.page, fixture, { required: [5], room: 'find', facilities: ['Projector'] });
    const direct = organizer.page.getByRole('region', { name: 'Direct options' });
    await measure(organizer.page);
    const first = direct.getByRole('radio').first();
    assert.ok(await first.isVisible(), 'An authorized instructor must be offered an eligible free room.');
    const ticket = await first.inputValue();
    const csrf = await direct.locator('[name=csrf_token]').inputValue();
    await first.check();
    await direct.getByLabel('Purpose').fill(instructorRoomPurpose);
    await direct.screenshot({ path: path.join(output, 'room-time-options-desktop.png') });
    await click(organizer.page, direct.getByRole('button', { name: 'Request room approval' }), 200, true);
    const roomRoute = new URL(organizer.page.url()).pathname;
    assert.match(roomRoute, /^\/rooms\/\d+$/);
    assert.match(await organizer.page.locator('#main-content').innerText(), /Pending Faculty Approval/);
    assert.equal(await organizer.page.getByRole('link', { name: 'Use this room for the group meeting' }).count(), 0);
    const replay = await organizer.context.request.post(fixture.url + '/meetings/submit', { maxRedirects: 0,
        form: { ticket, csrf_token: csrf, purpose: instructorRoomPurpose } });
    assert.equal(replay.status(), 303);
    assert.equal(replay.headers().location, roomRoute);
    await visit(approver, fixture.url + roomRoute);
    await click(approver, approver.getByRole('button', { name: 'Recheck and approve' }));
    await visit(organizer.page, fixture.url + roomRoute);
    await click(organizer.page, organizer.page.getByRole('link', { name: 'Use this room for the group meeting' }));
    assert.ok(await organizer.page.locator('input[name="requiredIds"][value="5"]').isChecked());
    await click(organizer.page, organizer.page.getByRole('button', { name: 'Find times' }));
    const { route } = await submitPlan(organizer.page, instructorRoomPurpose);
    await response(guest, fixture, route, 'Approve revision');
    assert.match(await guest.locator('#main-content').innerText(), /Approved room booking/);
    await guest.screenshot({ path: path.join(output, 'instructor-physical-meeting-desktop.png') });
    const start = await guest.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
    await verifyCalendar(guest, fixture, route, start.slice(0, 10), instructorRoomPurpose);
    checks.roomSearch = { route, roomRoute, approvedByDesignatedStaff: true, replaySameRoom: true };
}

async function verifyOtherRelationships(users, fixture, checks) {
    const outcomes = [];
    for (const [scenario, purpose] of [
        [scenarios[1], 'Pilot browser one-to-many'],
        [scenarios[2], 'Pilot browser many-to-one'],
    ]) {
        const organizer = users.get(scenario.actor).page;
        await plan(organizer, fixture, scenario);
        const { route } = await submitPlan(organizer, purpose);
        const voters = [...scenario.cohosts, ...scenario.required];
        for (const id of voters) await response(users.get(id).page, fixture, route, 'Approve revision');
        await visit(organizer, fixture.url + route);
        assert.match(await organizer.locator('#main-content').innerText(), /Confirmed/);
        const time = await organizer.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
        for (const id of [scenario.actor, ...voters]) {
            await verifyCalendar(users.get(id).page, fixture, route, time.slice(0, 10), purpose);
        }
        outcomes.push({ route, required: [scenario.actor, ...voters], confirmed: true });
    }
    checks.additionalRelationships = outcomes;
}

async function verifyPhysicalReplacement(users, fixture, output, checks) {
    const { route, roomRoute } = checks.roomSearch;
    const reschedule = route + '/reschedule';
    const organizer = users.get(3).page;
    const required = users.get(5).page;
    const faculty = users.get(6).page;
    const currentTime = page => page.getByRole('region', { name: 'Arrangement' }).locator('p').first().innerText();
    await visit(organizer, fixture.url + route);
    const original = await currentTime(organizer);
    const replacementDate = localDate(fixture, original.startsWith(localDate(fixture, 2)) ? 1 : 2);
    await visit(organizer, fixture.url + reschedule);
    async function findTimes() {
        await organizer.getByLabel('First date').fill(replacementDate);
        await organizer.getByLabel('Last date').fill(replacementDate);
        await click(organizer, organizer.getByRole('button', { name: 'Find replacement times' }), 200, true);
    }
    await findTimes();
    await organizer.getByRole('region', { name: 'Room and time options' }).getByRole('radio').first().check();
    const widths = await measure(organizer);
    await organizer.setViewportSize({ width: 390, height: 1000 });
    await organizer.screenshot({ path: path.join(output, 'replacement-room-options-mobile.png') });
    await organizer.setViewportSize({ width: 1440, height: 1000 });
    await click(organizer, organizer.getByRole('button', { name: 'Request replacement room approval' }), 200, true);
    const tracking = organizer.url();
    const nextRoom = await organizer.getByRole('link', { name: 'Replacement room request' }).getAttribute('href');
    assert.notEqual(nextRoom, roomRoute);
    assert.match(await organizer.locator('#main-content').innerText(), /Pending Faculty Approval/);
    await visit(faculty, fixture.url + nextRoom);
    await click(faculty, faculty.getByRole('button', { name: 'Recheck and approve' }));
    await visit(organizer, tracking);
    await findTimes();
    await organizer.getByRole('region', { name: 'Replacement options' }).getByRole('radio').first().check();
    await click(organizer, organizer.getByRole('button', { name: 'Propose replacement' }));
    assert.match(await organizer.getByRole('region', { name: 'Replacement proposal' }).innerText(),
        /1 of 2 required approvals recorded/);
    await visit(organizer, fixture.url + route);
    assert.equal(await currentTime(organizer), original);
    await visit(organizer, fixture.url + roomRoute);
    assert.match(await organizer.locator('#main-content').innerText(), /Confirmed/);
    await response(required, fixture, reschedule, 'Approve replacement');
    assert.match(await required.getByRole('region', { name: 'Rescheduling history' }).innerText(), /Applied/);
    await required.screenshot({ path: path.join(output, 'replacement-room-applied-desktop.png') });
    for (const page of [organizer, required]) await verifyCalendar(page, fixture, route, replacementDate, instructorRoomPurpose);
    await visit(organizer, fixture.url + roomRoute);
    assert.match(await organizer.locator('#main-content').innerText(), /Cancelled/);
    checks.physicalReplacement = { reschedule, priorRoom: roomRoute, nextRoom, replacementDate, widths };
}

async function main() {
    const [loginRecord, output, mode] = process.argv.slice(2);
    assert.ok(loginRecord && output, 'Provide the fictional logins file and screenshot folder.');
    const fixture = JSON.parse(await fs.readFile(loginRecord, 'utf8'));
    const base = new URL(fixture.url);
    assert.ok(base.protocol === 'http:' && base.hostname === '127.0.0.1' && base.port,
        'Browser verification requires a loopback pilot.');
    await fs.mkdir(output, { recursive: true });
    const browser = await chromium.launch({ channel: 'msedge', headless: true });
    const checks = { browser: 'Microsoft Edge', shapes: [] };
    const users = new Map();
    try {
        if (mode === '--verify-restart') {
            const evidence = JSON.parse(await fs.readFile(path.join(output, 'group-meeting-browser-checks.json'), 'utf8'));
            const staff = await login(browser, fixture, 6);
            const instructor = await login(browser, fixture, 3);
            const assistant = await login(browser, fixture, 5);
            await visit(staff.page, fixture.url + evidence.replacement.route);
            assert.match(await staff.page.getByRole('region', { name: 'Rescheduling history' }).innerText(), /Applied/);
            await verifyCalendar(instructor.page, fixture, evidence.online.route,
                evidence.replacement.updated.slice(0, 10), onlinePurpose);
            await visit(assistant.page, fixture.url + evidence.roomSearch.route);
            assert.match(await assistant.page.locator('#main-content').innerText(), /Approved room booking/);
            await visit(staff.page, fixture.url + '/meetings/preferences');
            assert.equal(await staff.page.locator('input[name=desired_gap]').inputValue(), '33');
            for (const user of [staff, instructor, assistant]) assert.deepEqual(user.errors, []);
            console.log('Fresh browser sessions verified the applied replacement, calendar, approved room and preferences after restart.');
            return;
        }
        const untrusted = await browser.newContext();
        const anonymous = await untrusted.request.get(fixture.url + '/meetings/', { maxRedirects: 0 });
        assert.equal(anonymous.status(), 302);
        assert.match(anonymous.headers().location, /^\/login/);
        await untrusted.close();
        for (const id of [1, 2, 3, 4, 5, 6, 7]) users.set(id, await login(browser, fixture, id));
        const noCsrf = await users.get(1).context.request.post(fixture.url + '/meetings/new', { form: {} });
        assert.equal(noCsrf.status(), 400);
        const admin = users.get(7).page;
        await click(admin, admin.locator('a[href="/meetings/"]:visible').first(), 200, true);
        assert.equal(new URL(admin.url()).pathname, '/meetings/');
        for (const scenario of scenarios) {
            const { page } = users.get(scenario.actor);
            if (scenario.role === 'Staff') await visit(page, fixture.url + '/appointments/');
            const workspaceLink = page.locator('a[href="/meetings/"]:visible').first();
            await click(page, workspaceLink, 200, true);
            assert.equal(new URL(page.url()).pathname, '/meetings/');
            await click(page, page.getByRole('link', { name: 'Find meeting times' }), 200, true);
            assert.equal(new URL(page.url()).pathname, '/meetings/new');
            await plan(page, fixture, scenario);
            const direct = page.getByRole('region', { name: 'Direct options' });
            assert.ok(await direct.getByRole('radio').count(), 'No direct options for ' + scenario.role);
            const explanation = await direct.innerText();
            assert.match(explanation, /Required calendars fit/);
            assert.match(explanation, /preferred-time coverage/);
            assert.match(explanation, /calendar gaps, cost/);
            const widths = await measure(page);
            if (scenario.actor === 6) {
                await page.screenshot({ path: path.join(output, 'group-meeting-plan-desktop.png') });
                await direct.screenshot({ path: path.join(output, 'group-meeting-options-desktop.png') });
                await page.setViewportSize({ width: 390, height: 1000 });
                await direct.screenshot({ path: path.join(output, 'group-meeting-plan-mobile.png') });
                await page.setViewportSize({ width: 1440, height: 1000 });
            }
            checks.shapes.push({ role: scenario.role, hosts: scenario.cohosts.length + 1, requiredGuests: scenario.required.length,
                direct: await direct.getByRole('radio').count(), widths, workspaceNavigation: true });
        }
        await verifyOnline(users, fixture, output, checks);
        await verifyRelocation(users, fixture, output, checks);
        await verifyPhysical(users, fixture, output, checks);
        await verifyStandaloneReplacement(users, fixture, output, checks);
        await verifyRoomSearch(users, fixture, output, checks);
        await verifyPhysicalReplacement(users, fixture, output, checks);
        await verifyOtherRelationships(users, fixture, checks);
        for (const { errors } of users.values()) assert.deepEqual(errors, []);
        checks.security = { anonymous: 302, noCsrf: 400 };
        await fs.writeFile(path.join(output, 'group-meeting-browser-checks.json'), JSON.stringify(checks, null, 2) + '\n');
        console.log(JSON.stringify(checks));
    } finally {
        await browser.close();
    }
}

main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
});
