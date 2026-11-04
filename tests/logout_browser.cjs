'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const info = JSON.parse(fs.readFileSync(process.env.LOGOUT_BROWSER_INFO, 'utf8'));
const output = process.env.LOGOUT_BROWSER_OUTPUT;

async function login(context, actor) {
    const page = await context.request.get(info.url + '/login');
    const csrf = (await page.text()).match(/name="csrf_token" value="([^"]+)"/)[1];
    const response = await context.request.post(info.url + '/login', {form: {
        username: 'logout-browser-' + actor, password: info.password, csrf_token: csrf
    }, maxRedirects: 0});
    assert.equal(response.status(), 302);
}

(async () => {
    const browser = await chromium.launch({headless: true, channel: 'msedge'});
    const results = [];
    try {
        for (const [actor, role] of Object.entries(info.users)) {
            const context = await browser.newContext();
            const independent = await browser.newContext();
            try {
                await login(context, actor);
                await login(independent, actor);
                const page = await context.newPage();
                await page.goto(info.url + '/appointments/');
                await page.waitForLoadState('networkidle');
                const csrf = await page.locator('[data-notifications]').getAttribute('data-csrf');
                const copied = await context.cookies();
                const api = context.request;
                await api.get(info.url + '/static/favicon.svg?logoutRace=reset');
                const held = api.get(info.url + '/notifications/feed?logoutRace=held');
                let entered = false;
                for (let n = 0; n < 100; n++) {
                    const state = await api.get(info.url + '/static/favicon.svg?logoutRace=state');
                    if (state.headers()['x-logout-race-held'] === '1') { entered = true; break; }
                    await new Promise(resolve => setTimeout(resolve, 30));
                }
                assert.ok(entered, 'Real authenticated notification response must be held');
                await page.locator('[data-account-menu] summary').click();
                await page.locator('form[action="/logout"] button').click();
                await page.waitForURL(info.url + '/login');
                assert.equal((await api.get(info.url + '/appointments/', {maxRedirects: 0})).status(), 302);
                await api.get(info.url + '/static/favicon.svg?logoutRace=release');
                const delayed = await held;
                assert.equal(delayed.status(), 200);
                assert.ok(delayed.headers()['set-cookie'], 'Exercise an actual late refreshed cookie');
                const after = await api.get(info.url + '/appointments/', {maxRedirects: 0});
                assert.equal(after.status(), 302, 'Delayed response must not restore authentication');
                await context.addCookies(copied);
                const mutation = await api.post(info.url + '/appointments/calendar', {form: {
                    csrf_token: csrf, action: 'block', start: '2030-01-07T10:00', end: '2030-01-07T11:00',
                    reason: 'Must not persist from a logged-out cookie'
                }, maxRedirects: 0});
                assert.ok([302, 400].includes(mutation.status()), 'Replayed cookie must not authorize a POST');
                assert.equal((await independent.request.get(info.url + '/appointments/', {maxRedirects: 0})).status(), 200);
                await login(context, actor);
                assert.equal((await api.get(info.url + '/appointments/', {maxRedirects: 0})).status(), 200);
                results.push({actor: Number(actor), role, lateCookiePresent: true, protectedAfterLogout: after.status(),
                    replayedMutationStatus: mutation.status(), independentLoginStatus: 200, newLoginStatus: 200});
            } finally {
                await context.request.get(info.url + '/static/favicon.svg?logoutRace=release').catch(() => {});
                await context.close();
                await independent.close();
            }
        }
        fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify({passed: results.length, results}, null, 2) + '\n');
        console.log('PASS: ' + results.length + ' real-browser delayed-response logout regressions');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
