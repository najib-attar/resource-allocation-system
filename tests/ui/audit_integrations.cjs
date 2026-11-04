/* Independent UI-10 lifecycle checks; real pages, forms, server and PostgreSQL. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const fixture=JSON.parse(fs.readFileSync(process.env.PORTAL_INFO_FILE));
const out=process.env.PORTAL_OUTPUT_DIR, base=fixture.url, ids=fixture.ids;
const checks=[], errors=[], responses=[], controls=[];
async function login(browser,actor) {
  const context=await browser.newContext({viewport:{width:390,height:900}}), page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error' && !m.text().startsWith('Failed to load resource:')) errors.push(m.text());});
  page.on('response',r=>{if(r.status()>=400) responses.push({url:new URL(r.url()).pathname,status:r.status()});});
  await page.goto(base+'/login');
  await page.locator('[name=username]').fill(fixture.users[String(actor)]);
  await page.locator('[name=password]').fill(fixture.password);
  await submit(page,page.locator('button[type=submit]'));
  return {context,page};
}
async function submit(page,button,expected=200) {
  const [r]=await Promise.all([page.waitForNavigation(),button.click()]);
  assert.equal(r.status(),expected,await r.text());
}
async function inventory(page,label) {
  controls.push({label,url:page.url(),controls:await page.locator('a,button,input,select,textarea,summary').evaluateAll(nodes=>nodes.filter(el=>el.getClientRects().length).map(el=>({tag:el.tagName,text:(el.getAttribute('aria-label')||el.textContent||'').trim().slice(0,120),name:el.name||'',value:el.value||'',href:el.getAttribute('href'),type:el.type,disabled:el.disabled||false,action:el.form?.getAttribute('action'),method:el.form?.method}))) });
}
async function shot(page,label) {
  await inventory(page,label);
  await page.evaluate(()=>{document.activeElement.blur();scrollTo(0,0);});
  await page.screenshot({path:path.join(out,label+'.png'),fullPage:true});
}
async function calendarText(page,day) {
  const r=await page.request.get(base+'/calendar/?view=day&date='+day);
  assert.equal(r.status(),200);return r.text();
}
async function createAppointment(page,professors,invitees,n) {
  await page.goto(base+'/appointments/new');
  await page.locator('[name=facultyId]').selectOption(String(ids.faculty));
  await page.locator('[data-picker=professorIds] summary').click();
  for(const p of professors) await page.locator(`[name=professorIds][value="${p}"]`).check();
  if(invitees.length) {
    await page.locator('[data-picker=invitedIds] summary').click();
    for(const p of invitees) await page.locator(`[name=invitedIds][value="${p}"]`).check();
  }
  await page.locator('[name=purpose]').fill('UI10 participant combination '+n);
  await page.locator('[name=appointmentDate]').fill('2030-01-14');
  await page.locator('[name=appointmentDate]').press('Tab');
  await page.locator('.appointment-choice').first().waitFor();
  await page.locator('.manual-time summary').click();
  await page.locator('#manual-time').fill(`${10+n}:00`);
  await submit(page,page.locator('#submit-appointment'));
  assert.match(await page.locator('#approval-progress').innerText(),new RegExp(`0 of ${professors.length}`));
  await inventory(page,'appointment-pending-'+n);
  return new URL(page.url()).pathname;
}
async function appointmentLifecycles(browser,student,prof,second,peer) {
  const combinations=[[[2],[]],[[2,3],[]],[[2],[4,5]],[[2,3],[4,5]]];
  for(let n=0;n<combinations.length;n++) {
    const [required,invited]=combinations[n], url=await createAppointment(student,required,invited,n);
    for(const actor of required) {
      const page=actor===2?prof:second;
      await page.goto(base+url);
      await submit(page,page.locator('button[name=decision][value=approve]'));
    }
    await student.goto(base+url);
    assert.match(await student.locator('main').innerText(),/Confirmed/);
    assert.match(await calendarText(student,'2030-01-14'),new RegExp('UI10 participant combination '+n));
    if(invited.length) {
      await peer.goto(base+url);
      assert.equal(await peer.locator('form[action$="/cancel"]').count(),0);
      await submit(peer,peer.locator('form[action$="/decline-invitation"] button'));
      await student.reload();
      assert.match(await student.locator('main').innerText(),/Declined/);
      assert.match(await student.locator('main .service-status').first().innerText(),/Confirmed/);
    }
    const change=student.locator('form[action$="/reschedule"]');
    await change.locator('[name=start]').fill('2030-01-21T'+(10+n)+':00');
    await submit(student,change.locator('button'));
    assert.match(await student.locator('#approval-progress').innerText(),new RegExp(`0 of ${required.length}`));
    assert.doesNotMatch(await calendarText(student,'2030-01-14'),new RegExp('UI10 participant combination '+n));
    await submit(student,student.locator('form[action$="/cancel"] button'));
    assert.match(await student.locator('main').innerText(),/Cancelled/);
    checks.push(`Appointment combination ${n}: professors ${required}; invitees ${invited}; real form submission, unanimous confirmation, optional decline where applicable, calendar addition/removal, reschedule reset, cancellation.`);
  }
  const rejected=await createAppointment(student,[2],[],4);
  await prof.goto(base+rejected);
  await submit(prof,prof.locator('button[name=decision][value=decline]'));
  await student.goto(base+rejected);
  assert.match(await student.locator('main .service-status').first().innerText(),/Declined/);
  await shot(student,'professor-rejection');
  checks.push('Professor rejection persisted and displayed to organizer with history.');
}
async function physicalEquipment(student,staff) {
  const url='/equipment/'+ids.collection;
  await student.goto(base+url);
  assert.equal(await student.locator('form[action$="/handover"]').count(),0);
  await staff.goto(base+url);
  const handover=staff.locator('form[action$="/handover"]');
  await handover.locator('[name=condition]').fill('UI10 actual browser handover: usable');
  await submit(staff,handover.locator('button'));
  await student.reload();assert.match(await student.locator('main').innerText(),/Borrowed/);
  await submit(student,student.locator('form[action$="/intend-return"] button'));
  const extension=student.locator('form[action$="/extension"]');
  const due=new Date(Date.now()+3*86400000).toISOString().slice(0,16);
  await extension.locator('[name=due]').fill(due);
  await extension.locator('[name=reason]').fill('UI10 extension review');
  await submit(student,extension.locator('button'));
  assert.equal(await student.locator('form[action$="/extension"]').count(),0);
  assert.match(await student.locator('main').innerText(),/awaiting the custodian's decision/);
  await staff.reload();
  await submit(staff,staff.locator('form[action$="/approve-extension"] button'));
  await student.reload();assert.match(await student.locator('main').innerText(),/Approved/);
  assert.equal(await student.locator('form[action$="/extension"]').count(),1);
  await staff.reload();
  let returns=staff.locator('form[action$="/return"]');
  await returns.locator('[name=unitIds]').first().check();
  await returns.locator('[name=notes]').fill('UI10 first verified return');
  await submit(staff,returns.locator('button'));
  await student.reload();assert.match(await student.locator('main').innerText(),/Partially Returned/);
  await shot(student,'physical-partial-return');
  await staff.reload();returns=staff.locator('form[action$="/return"]');
  await returns.locator('[name=unitIds]').check();
  await returns.locator('[name=notes]').fill('UI10 final verified return');
  await submit(staff,returns.locator('button'));
  await student.reload();assert.equal(await student.locator('form[action$="/extension"]').count(),0);
  await shot(student,'physical-complete-return');
  checks.push('Custodian-only actual handover, borrower intent, extension request and approval, partial then full inspected return persisted; borrower never received custody controls.');
}
async function roomLifecycles(student,staff,prof,peer) {
  await student.goto(base+'/rooms/new');
  await student.locator('[name=purpose]').fill('UI10 approved room with participants');
  await student.locator('[name=start]').fill('2030-01-16T13:00');
  await student.locator('summary').filter({hasText:'Register student participants'}).click();
  await student.locator('[name=participantIds][value="4"]').check();
  await student.locator('summary').filter({hasText:'Invite professors'}).click();
  await student.locator('[name=professorIds][value="2"]').check();
  await student.locator('.room-candidate').first().waitFor();
  await submit(student,student.locator('#submit-room'));
  let url=new URL(student.url()).pathname;
  await peer.goto(base+url);
  assert.equal(await peer.locator('form[action$="/cancel"]').count(),0);
  await staff.goto(base+url);
  await submit(staff,staff.locator('button[name=decision][value=approve]'));
  await prof.goto(base+url);
  await submit(prof,prof.locator('button[name=response][value=accept]'));
  await student.reload();
  assert.match(await student.locator('main').innerText(),/Accepted/);
  assert.match(await calendarText(student,'2030-01-16'),/UI10 approved room with participants/);
  await shot(student,'room-approved-participants');
  await submit(student,student.locator('form[action$="/cancel"] button'));
  checks.push('Room actual registered participant access, faculty approval, optional professor acceptance, calendar publication and organizer cancellation persisted.');
  for(const mode of ['partial','all']) {
    await student.goto(base+'/rooms/new');
    await student.locator('[name=purpose]').fill('UI10 recurring room '+mode);
    await student.locator('[name=start]').fill('');
    await student.locator('[name=reservationMode]').selectOption('weekly');
    assert.ok(await student.locator('[name=start]').isDisabled());
    assert.ok(await student.locator('[data-one-time-start]').isHidden());
    await student.locator('[name=academicPeriod]').selectOption({index:1});
    await student.locator('[name=approvalMode]').selectOption(mode);
    await student.locator('[name=recurrenceStart]').fill('2030-01-22');
    await student.locator('[name=recurrenceEnd]').fill('2030-01-29');
    await student.locator('[name=recurrenceTime]').fill('14:00');
    await student.locator('[name=recurrenceDays][value="2"]').check();
    await student.locator('#find-rooms').click();
    await student.locator('.room-candidate').first().waitFor();
    await submit(student,student.locator('#submit-room'));
    url=new URL(student.url()).pathname;
    await staff.goto(base+url);
    if(mode==='partial') await staff.locator('[name=occurrenceIds]').first().check();
    await submit(staff,staff.locator('button[name=decision][value=approve]'));
    if(mode==='partial') {
      await staff.locator('[name=occurrenceIds]').check();
      await staff.locator('form[action$="/decision"] [name=reason]').fill('UI10 second date declined');
      await submit(staff,staff.locator('button[name=decision][value=reject]'));
    }
    await student.goto(base+url);
    await shot(student,'room-recurring-'+mode);
    if(mode==='partial') {
      await submit(student,student.locator('form[action*="/occurrences/"] button').first());
    } else await submit(student,student.locator('form[action="'+url+'/cancel"] button'));
    checks.push(`Recurring room ${mode}: empty irrelevant one-time start disabled; actual weekly preview/submission and faculty ${mode==='partial'?'selected-date approval/rejection and occurrence cancellation':'all-date approval and cancellation'} persisted.`);
  }
  await student.goto(base+'/rooms/new');
  await student.locator('[name=reservationMode]').selectOption('weekly');
  await student.locator('[name=reservationMode]').selectOption('once');
  assert.ok(await student.locator('[name=start]').isEnabled());
  assert.ok(await student.locator('[data-one-time-start]').isVisible());
}
async function rolesAndSessions(browser) {
  for(const [actor,role] of [[1,'Student'],[2,'Instructor'],[9,'TeachingAssistant'],[7,'Staff'],[6,'Administrator']]) {
    const {context,page}=await login(browser,actor);
    assert.equal(new URL(page.url()).pathname,actor===1?'/student/':actor===6?'/':'/appointments/');
    if(actor!==1) assert.equal(await page.locator('link[href$="student-services.css"]').count(),0);
    if(actor!==6) assert.equal((await page.request.get(base+'/users')).status(),403);
    if(actor!==1) assert.equal((await page.request.get(base+'/appointments/new')).status(),403);
    const csrf=await page.locator('[data-csrf]').getAttribute('data-csrf');
    assert.equal((await page.request.post(base+'/logout',{form:{csrf_token:'invalid'}})).status(),400);
    await page.locator('[data-account-menu] summary').click();
    await submit(page,page.locator('form[action="/logout"] button'));
    assert.equal(new URL(page.url()).pathname,'/login');
    const protectedResponse=await page.request.get(base+'/notifications/',{maxRedirects:0});
    assert.equal(protectedResponse.status(),302);
    assert.notEqual(csrf,'');
    checks.push(role+': role redirect, original shell, privilege denial, invalid CSRF rejection and real logout/session removal.');
    await context.close();
  }
}
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    await rolesAndSessions(browser);
    const s=await login(browser,1), p=await login(browser,2), q=await login(browser,3), peer=await login(browser,4), staff=await login(browser,7);
    await appointmentLifecycles(browser,s.page,p.page,q.page,peer.page);
    await physicalEquipment(s.page,staff.page);
    await roomLifecycles(s.page,staff.page,p.page,peer.page);
    assert.deepEqual(errors,[]);
    assert.ok(responses.every(r=>[400,403].includes(r.status)),JSON.stringify(responses));
    fs.writeFileSync(path.join(out,'integration-results.json'),JSON.stringify({checks,errors,expectedNegativeResponses:responses},null,2)+'\n');
    fs.writeFileSync(path.join(out,'controls.json'),JSON.stringify(controls,null,2)+'\n');
    console.log(JSON.stringify({checks,errors},null,2));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
