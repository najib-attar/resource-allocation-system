const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright-core');

const route = '/appointments/rehearsal';
const cases = [
    { id: 1, role: 'Student', shape: '1 to 1', required: [4], cohosts: [], optional: [2] },
    { id: 3, role: 'Instructor', shape: '1 to 2', required: [1, 4], cohosts: [], optional: [2] },
    { id: 5, role: 'Research Assistant', shape: '2 to 1', required: [4], cohosts: [1], optional: [2] },
    { id: 6, role: 'Staff', shape: '2 to 2', required: [3, 4], cohosts: [1], optional: [2] },
];

async function login(browser, base, account) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    await page.goto(base + '/login');
    await page.locator('#username').fill(account.username);
    await page.locator('#password').fill(account.password);
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: 'Sign in' }).click()]);
    assert.notEqual(new URL(page.url()).pathname, '/login');
    return { context, page };
}

async function assertWidth(page, width) {
    await page.setViewportSize({ width, height: 1000 });
    const dimensions = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
    }));
    assert.equal(dimensions.viewport, width);
    assert.ok(dimensions.document <= width, 'Horizontal overflow at ' + width + ': ' + dimensions.document);
    return dimensions;
}

async function checkBoxes(page, field, heading, ids) {
    if (!ids.length) return;
    const disclosure = page.getByText(heading, { exact: true });
    const checkbox = page.locator('input[name="' + field + '"][value="' + ids[0] + '"]');
    if (!await checkbox.isVisible()) {
        await disclosure.focus();
        await page.keyboard.press('Enter');
    }
    for (const id of ids) {
        const control = page.locator('input[name="' + field + '"][value="' + id + '"]');
        assert.equal(await control.isVisible(), true);
        await control.focus();
        await page.keyboard.press('Space');
        assert.equal(await control.isChecked(), true);
    }
}

async function submit(page, status) {
    const button = page.getByRole('button', { name: 'Find rehearsal times' });
    await button.focus();
    const [response] = await Promise.all([page.waitForNavigation(), page.keyboard.press('Enter')]);
    assert.equal(response.status(), status);
    return response;
}

function datePart(fixture, value, options) {
    return new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Istanbul', ...options }).format(new Date(fixture[value]));
}

async function main() {
    const [secretRecord, output] = process.argv.slice(2);
    if (!secretRecord || !output) throw new Error('Provide the local fixture login file and audit output folder.');
    const fixture = JSON.parse(await fs.readFile(secretRecord, 'utf8'));
    const source = new URL(fixture.url);
    if (source.protocol !== 'http:' || source.hostname !== '127.0.0.1' || !source.port)
        throw new Error('The browser smoke requires the dedicated loopback fixture.');
    await fs.mkdir(output, { recursive: true });
    const result = { browser: 'Microsoft Edge', shapes: [], checks: [] };
    const browser = await chromium.launch({ channel: 'msedge', headless: true });
    try {
        const anonymous = await browser.newContext();
        const redirect = await anonymous.request.get(fixture.url + route, { maxRedirects: 0 });
        assert.equal(redirect.status(), 302);
        assert.match(redirect.headers().location, /^\/login/);
        await anonymous.close();
        result.checks.push('Anonymous request redirected to sign-in.');

        for (const scenario of cases) {
            const account = fixture.accounts.find(entry => entry.id === scenario.id);
            const { context, page } = await login(browser, fixture.url, account);
            const errors = [];
            page.on('pageerror', () => errors.push('Unhandled browser exception'));
            page.on('console', entry => { if (entry.type() === 'error') errors.push('Browser console error'); });
            try {
                const userMenu = page.locator('[data-account-menu] > summary');
                await userMenu.focus();
                await page.keyboard.press('Enter');
                const link = page.getByRole('link', { name: 'Meeting rehearsal', exact: true });
                await link.focus();
                const [opened] = await Promise.all([page.waitForNavigation(), page.keyboard.press('Enter')]);
                assert.equal(opened.status(), 200);
                assert.equal(opened.headers()['cache-control'], 'private, no-store');
                assert.equal(new URL(page.url()).pathname, route);
                assert.equal(await page.locator('input[name="requiredIds"][value="' + scenario.id + '"]').count(), 0);
                assert.equal(await page.getByRole('link', { name: 'Open Appointments' }).getAttribute('href'), '/appointments/');
                assert.equal(await page.getByRole('link', { name: 'Open Calendar' }).getAttribute('href'), '/calendar/');

                if (scenario.id === 1) {
                    await page.screenshot({ path: path.join(output, 'meeting-rehearsal-form-1440.png'), fullPage: true });
                }
                await checkBoxes(page, 'requiredIds', 'Choose required attendees', scenario.required);
                await checkBoxes(page, 'cohostIds', 'Choose co-hosts', scenario.cohosts);
                await checkBoxes(page, 'optionalIds', 'Choose optional invitees', scenario.optional);

                const searched = await submit(page, 200);
                assert.equal(searched.headers()['cache-control'], 'private, no-store');
                const recommendations = page.getByRole('region', { name: 'Recommended times' });
                assert.match(await recommendations.innerText(), new RegExp('\\b' + scenario.shape + '\\b'));
                const direct = recommendations.getByRole('region', { name: 'Direct options' });
                const conditional = recommendations.getByRole('region', { name: 'Options requiring one move' });
                const directCount = await direct.locator('ol > li').count();
                const conditionalCount = await conditional.locator('ol > li').count();
                assert.ok(directCount > 0, 'Expected direct recommendations for ' + scenario.role);
                assert.ok(conditionalCount > 0, 'Expected conditional recommendations for ' + scenario.role);
                assert.match(await conditional.innerText(), /Proposed replacement time/);
                assert.match(await conditional.innerText(), /consent/);

                for (const [key, expected] of Object.entries({
                    requiredIds: scenario.required, cohostIds: scenario.cohosts, optionalIds: scenario.optional,
                })) {
                    const selected = await page.locator('input[name="' + key + '"]:checked').evaluateAll(inputs =>
                        inputs.map(input => Number(input.value)).sort((a, b) => a - b));
                    assert.deepEqual(selected, [...expected].sort((a, b) => a - b));
                }
                const widths = [];
                for (const width of [1440, 1024, 768, 390, 320]) widths.push(await assertWidth(page, width));
                if (scenario.id === 1) {
                    await assertWidth(page, 1440);
                    await recommendations.screenshot({ path: path.join(output, 'direct-and-conditional-results-1440.png') });
                }
                if (scenario.id === 6) {
                    await assertWidth(page, 390);
                    await page.screenshot({ path: path.join(output, 'staff-many-to-many-390.png'), fullPage: true });
                }
                assert.deepEqual(errors, []);
                result.shapes.push({ role: scenario.role, shape: scenario.shape, directCount, conditionalCount,
                                     viewports: widths, keyboard: 'menu, participant inputs, submit' });

                if (scenario.id === 1) {
                    assert.equal((await context.request.post(fixture.url + route, { form: {} })).status(), 400);
                    const fresh = await page.goto(fixture.url + route);
                    assert.equal(fresh.status(), 200);
                    await submit(page, 409);
                    assert.match(await page.getByRole('alert').innerText(), /at least one|required/i);
                    result.checks.push('Missing CSRF returned 400; empty required selection returned 409.');

                    await page.goto(fixture.url + route);
                    await checkBoxes(page, 'requiredIds', 'Choose required attendees', [4]);
                    const first = await page.locator('#rehearsal-from').inputValue();
                    await page.locator('#rehearsal-until').fill(first);
                    await page.locator('#rehearsal-preferred').fill(first + 'T13:00');
                    await submit(page, 200);
                    const sameDay = datePart(fixture, 'teachingStarts', { weekday: 'short', day: '2-digit', month: 'short' }).replace(',', '');
                    const entries = await page.getByRole('region', { name: 'Direct options' }).locator('li strong').allInnerTexts();
                    assert.ok(entries.length > 0);
                    for (const entry of entries) {
                        assert.ok(entry.includes(sameDay), 'Unexpected teaching-day date label: ' + entry);
                        const minutes = [...entry.matchAll(/([0-9]{2}):([0-9]{2})/g)]
                            .map(match => Number(match[1]) * 60 + Number(match[2]));
                        assert.equal(minutes.length, 2);
                        assert.ok(minutes[1] <= 13 * 60 || minutes[0] >= 14 * 60, 'Direct time overlapped the fixture lecture.');
                    }
                    result.checks.push('One-day search preferred 13:00 but direct options excluded the 13:00–14:00 teaching commitment.');

                    if (fixture.publicSlot) {
                        const [date, localStart] = fixture.publicSlot.start.split('T');
                        const localEnd = fixture.publicSlot.end.split('T')[1];
                        function minutes(clock) {
                            const [hour, minute] = clock.slice(0, 5).split(':').map(Number);
                            return hour * 60 + minute;
                        }
                        await page.goto(fixture.url + route);
                        await checkBoxes(page, 'requiredIds', 'Choose required attendees', [3]);
                        await page.locator('#rehearsal-from').fill(date);
                        await page.locator('#rehearsal-until').fill(date);
                        await page.locator('#rehearsal-preferred').fill(date + 'T' + localStart.slice(0, 5));
                        await submit(page, 200);
                        const options = await page.getByRole('region', { name: 'Direct options' }).locator('li strong').allInnerTexts();
                        assert.ok(options.length > 0);
                        for (const text of options) {
                            const [start, end] = [...text.matchAll(/([0-9]{2}:[0-9]{2})/g)].map(match => minutes(match[1]));
                            assert.ok(end <= minutes(localStart) || start >= minutes(localEnd));
                        }
                        result.checks.push('Direct options excluded the verified public timetable mirror.');
                    }
                }
            } finally {
                await context.close();
            }
        }
        const administrator = await login(browser, fixture.url, fixture.accounts.find(entry => entry.id === 7));
        try {
            assert.equal((await administrator.page.goto(fixture.url + route)).status(), 200);
            const csrf = await administrator.page.locator('form[action="' + route + '"] [name="csrf_token"]').inputValue();
            const unauthorized = await administrator.context.request.post(fixture.url + route, { form: {
                csrf_token: csrf, requiredIds: '99999', duration: '30',
                fromDate: await administrator.page.locator('#rehearsal-from').inputValue(),
                untilDate: await administrator.page.locator('#rehearsal-until').inputValue(),
            } });
            assert.equal(unauthorized.status(), 409);
            result.checks.push('Administrator preview opened; an ID outside the synthetic participant roster was rejected.');
        } finally {
            await administrator.context.close();
        }

        const student = await login(browser, fixture.url, fixture.accounts.find(entry => entry.id === 1));
        const professor = await login(browser, fixture.url, fixture.accounts.find(entry => entry.id === 4));
        try {
            const purpose = 'Synthetic rehearsal direct booking verification';
            await student.page.goto(fixture.url + route);
            await checkBoxes(student.page, 'requiredIds', 'Choose required attendees', [4]);
            await submit(student.page, 200);
            const booking = student.page.getByRole('region', { name: 'Request a standard appointment' });
            const firstStart = await booking.getByLabel('Direct option').inputValue();
            assert.match(firstStart, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
            await booking.getByLabel('Purpose').fill(purpose);
            await booking.screenshot({ path: path.join(output, 'eligible-standard-booking-1440.png') });
            const [appointment] = await Promise.all([student.page.waitForNavigation(),
                booking.getByRole('button', { name: 'Request appointment' }).click()]);
            assert.equal(appointment.status(), 200);
            const appointmentPath = new URL(student.page.url()).pathname;
            assert.match(appointmentPath, /^\/appointments\/\d+$/);
            const studentDetail = await student.page.locator('main').innerText();
            assert.ok(studentDetail.includes(purpose));
            assert.match(studentDetail, /Pending Approval/i);

            const review = await professor.page.goto(fixture.url + appointmentPath);
            assert.equal(review.status(), 200);
            const [approved] = await Promise.all([professor.page.waitForNavigation(),
                professor.page.getByRole('button', { name: 'Approve this revision' }).click()]);
            assert.equal(approved.status(), 200);
            assert.match(await professor.page.locator('main').innerText(), /Confirmed/i);
            await student.page.reload();
            assert.match(await student.page.locator('main').innerText(), /Confirmed/i);
            await professor.page.screenshot({ path: path.join(output, 'confirmed-standard-appointment-1440.png'), fullPage: true });

            for (const user of [student, professor]) {
                const calendar = await user.page.goto(fixture.url + '/calendar/?view=day&date=' + firstStart.slice(0, 10));
                assert.equal(calendar.status(), 200);
                const event = user.page.locator('main a[href="' + appointmentPath + '"]:visible').filter({ hasText: purpose });
                assert.equal(await event.count(), 1);
            }
            result.checks.push('Student posted a direct CDMCS option into the standard workflow. Instructor approved. Both calendars showed the confirmed appointment.');
        } finally {
            await student.context.close();
            await professor.context.close();
        }
    } finally {
        await browser.close();
    }
    await fs.writeFile(path.join(output, 'checks.json'), JSON.stringify(result, null, 2) + '\n', 'utf8');
    console.log(JSON.stringify(result));
}

main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
});
