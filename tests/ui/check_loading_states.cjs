/* Observe live fetch boundaries without delaying requests or mocking responses. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const root=path.resolve(__dirname,'../..');
const fixture=JSON.parse(fs.readFileSync(process.env.PORTAL_INFO_FILE || path.join(root,'build/student-portal/preview.json')));
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?
    {executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'msedge'})});
  try {
    const page=await browser.newPage({viewport:{width:390,height:900}});
    await page.addInitScript(()=>{
      window.loadingObservations=[];
      const fetchRequest=window.fetch;
      window.fetch=function(input,options){
        const url=String(input);
        if(url.endsWith('/appointments/times')) window.loadingObservations.push({kind:'appointments',
          busy:document.getElementById('times-list').getAttribute('aria-busy'),
          refreshDisabled:document.getElementById('find-times').disabled,
          submitDisabled:document.getElementById('submit-appointment').disabled,
          selected:document.getElementById('appointment-start').value,
          message:document.getElementById('times-message').textContent});
        if(url.endsWith('/rooms/candidates')) window.loadingObservations.push({kind:'rooms',
          busy:document.getElementById('room-candidates').getAttribute('aria-busy'),
          refreshDisabled:document.getElementById('find-rooms').disabled,
          submitDisabled:document.getElementById('submit-room').disabled,
          selected:document.getElementById('selected-room').value,
          message:document.getElementById('room-message').textContent});
        if(url.endsWith('/notifications/feed')) window.loadingObservations.push({kind:'notifications',
          message:document.querySelector('.notification-status')?.textContent,
          markDisabled:document.querySelector('[data-mark-all]')?.disabled});
        return fetchRequest.call(this,input,options);
      };
    });
    await page.goto(fixture.url+'/login');
    await page.locator('[name=username]').fill(fixture.users['1']);
    await page.locator('[name=password]').fill(fixture.password);
    await Promise.all([page.waitForNavigation(),page.locator('button[type=submit]').click()]);
    await page.waitForFunction(()=>window.loadingObservations.some(row=>row.kind==='notifications'));
    const notifications=await page.evaluate(()=>window.loadingObservations.filter(row=>row.kind==='notifications'));
    assert.ok(notifications.some(row=>row.markDisabled && row.message.includes('Loading')));
    await page.goto(fixture.url+'/appointments/new');
    await page.locator('[name=facultyId]').selectOption(String(fixture.ids.faculty));
    await page.locator('[data-picker=professorIds] summary').click();
    await page.locator('[name=professorIds][value="2"]').check();
    await page.locator('[name=appointmentDate]').fill('2030-01-14');
    await page.locator('[name=appointmentDate]').press('Tab');
    await page.locator('.appointment-choice').first().waitFor();
    const appointments=await page.evaluate(()=>window.loadingObservations.filter(row=>row.kind==='appointments'));
    const appointmentChoices=await page.locator('.appointment-choice').count();
    assert.ok(appointments.length);
    for(const row of appointments) assert.ok(row.busy==='true' && row.refreshDisabled && row.submitDisabled && row.selected==='');
    await page.goto(fixture.url+'/rooms/new');
    await page.locator('[name=purpose]').fill('Fictional loading-state verification');
    await page.locator('[name=start]').fill('2030-01-09T15:00');
    await page.locator('#find-rooms').click();
    await page.locator('.room-candidate').first().waitFor();
    const rooms=await page.evaluate(()=>window.loadingObservations.filter(row=>row.kind==='rooms'));
    assert.ok(rooms.length);
    for(const row of rooms) assert.ok(row.busy==='true' && row.refreshDisabled && row.submitDisabled && row.selected==='');
    const report={method:'Synchronous observation at the native fetch call, followed by the unchanged real network request; no response mocks or delays.',
      notifications,appointments,rooms,realAppointmentChoices:appointmentChoices,
      realRoomCandidates:await page.locator('.room-candidate').count(),passed:true};
    fs.writeFileSync(path.join(process.env.PORTAL_OUTPUT_DIR || path.join(root,'docs/ui/student-portal/UI-09'),'loading-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
