/* UI-10 positive equipment integration: real forms, decisions and assignment. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const fixture=JSON.parse(fs.readFileSync(process.env.PORTAL_INFO_FILE));
const output=process.env.PORTAL_OUTPUT_DIR, base=fixture.url, ids=fixture.ids;
const actions=[], checks=[], screenshots=[], errors=[], httpErrors=[];

async function login(browser,actor){
  const context=await browser.newContext({viewport:{width:390,height:900}});
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error') errors.push(message.text());});
  page.on('response',response=>{
    if(response.status()>=400) httpErrors.push({url:new URL(response.url()).pathname,status:response.status()});
  });
  assert.equal((await page.goto(base+'/login')).status(),200);
  await page.locator('[name=username]').fill(fixture.users[String(actor)]);
  await page.locator('[name=password]').fill(fixture.password);
  await submit(page,page.locator('button[type=submit]'));
  return {context,page};
}
async function submit(page,button){
  const control=await button.evaluate(element=>({label:element.textContent.trim(),
    action:element.form.getAttribute('action')||location.pathname,method:element.form.method}));
  const [response]=await Promise.all([page.waitForNavigation(),button.click()]);
  assert.equal(response.status(),200,'Real form failed: '+JSON.stringify(control)+'\n'+(await response.text()).slice(0,600));
  actions.push({...control,result:new URL(page.url()).pathname,status:response.status()});
}
async function screenshot(page,name){
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390,name+': horizontal overflow');
  await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});
  screenshots.push(name+'.png');
}
async function status(page,expected){
  assert.equal((await page.locator('main .service-status').first().innerText()).trim(),expected);
}
async function catalog(page,start,due,quantity,purpose){
  const query=new URLSearchParams({start,due});
  assert.equal((await page.goto(base+'/equipment/catalog?'+query)).status(),200);
  await page.locator('#equipment-faculty').selectOption(String(ids.faculty));
  await page.locator('[name=qty_'+ids.equipmentType+']').fill(String(quantity));
  await page.locator('[name=purpose]').fill(purpose);
}
async function requestOne(page,start,due,quantity,purpose){
  await catalog(page,start,due,quantity,purpose);
  await submit(page,page.locator('button[name=action][value=recommend]'));
  assert.match(await page.locator('#equipment-result h2').innerText(),/complete request is feasible/);
  await submit(page,page.locator('button[name=action][value=submit]'));
  await status(page,'Pending Approval');
  return new URL(page.url()).pathname;
}
async function oneTime(student,staff){
  const request=await requestOne(student,'2030-02-07T10:00','2030-02-08T10:00',1,'UI10 equipment approval then cancellation');
  await staff.goto(base+request);
  const approve=staff.locator('form[action$="/approve"]');
  await approve.locator('[name=reason]').fill('UI10 complete quantity approved by actual custodian');
  await submit(staff,approve.locator('button'));
  await student.reload();await status(student,'Approved');
  assert.equal(await student.locator('form[action$="/handover"]').count(),0);
  await screenshot(student,'one-time-approved');
  await submit(student,student.locator('form[action$="/cancel"] button'));
  await student.reload();await status(student,'Cancelled');
  checks.push({workflow:'One-time approval and cancellation',request,
    verified:'Student submitted exact quantity; custodian approved; borrower saw Approved without handover controls; cancellation before collection persisted.'});

  const rejected=await requestOne(student,'2030-02-09T10:00','2030-02-10T10:00',1,'UI10 equipment rejection');
  await staff.goto(base+rejected);
  const reject=staff.locator('form[action$="/reject"]');
  await reject.locator('[name=reason]').fill('UI10 synthetic custodian rejection explanation');
  await submit(staff,reject.locator('button'));
  await student.reload();await status(student,'Rejected');
  assert.match(await student.locator('main').innerText(),/UI10 synthetic custodian rejection explanation/);
  await screenshot(student,'one-time-rejected');
  checks.push({workflow:'One-time rejection',request:rejected,
    verified:'Custodian rejection and explanation appeared in a fresh student detail response and history.'});
}
async function recurring(student,staff){
  await catalog(student,'2030-01-22T11:00','2030-01-22T12:00',1,'UI10 recurring equipment partial decisions');
  await student.locator('[name=reservationMode]').selectOption('weekly');
  const period=await student.locator('[name=academicPeriod]').evaluate(select=>Array.from(select.options).find(option=>option.value)?.value);
  assert.ok(period,'Fixture must contain an explicitly configured semester');
  await student.locator('[name=academicPeriod]').selectOption(period);
  await student.locator('[name=approvalMode]').selectOption('partial');
  await student.locator('[name=recurrenceStart]').fill('2030-01-22');
  await student.locator('[name=recurrenceEnd]').fill('2030-01-29');
  await student.locator('[name=recurrenceTime]').fill('11:00');
  await student.locator('[name=recurrenceDays][value="2"]').check();
  await submit(student,student.locator('button[name=action][value=recommend]'));
  assert.equal(await student.locator('#equipment-result > ol > li').count(),2);
  assert.ok(await student.locator('[name=previewToken]').inputValue());
  await screenshot(student,'recurring-complete-preview');
  await submit(student,student.locator('button[name=action][value=submit]'));
  const request=new URL(student.url()).pathname;
  assert.equal(await student.locator('article[id^="occurrence-"]').count(),2);
  await staff.goto(base+request);
  let decision=staff.locator('form[action$="/decision"]');
  const first=await decision.locator('[name=occurrenceIds]').first().inputValue();
  const second=await decision.locator('[name=occurrenceIds]').nth(1).inputValue();
  await decision.locator('[name=occurrenceIds][value="'+first+'"]').check();
  await decision.locator('[name=reason]').fill('UI10 approve the first complete pickup only');
  await submit(staff,decision.locator('button[value=approve]'));
  await student.reload();
  assert.match(await student.locator('#occurrence-'+first+' h4').innerText(),/Approved/);
  assert.match(await student.locator('#occurrence-'+second+' h4').innerText(),/Pending Approval/);
  await screenshot(student,'recurring-selected-approval');
  await staff.reload();decision=staff.locator('form[action$="/decision"]');
  assert.equal(await decision.locator('[name=occurrenceIds]').count(),1);
  await decision.locator('[name=occurrenceIds][value="'+second+'"]').check();
  await decision.locator('[name=reason]').fill('UI10 reject the remaining pickup with explanation');
  await submit(staff,decision.locator('button[value=reject]'));
  await student.reload();
  assert.match(await student.locator('#occurrence-'+first+' h4').innerText(),/Approved/);
  assert.match(await student.locator('#occurrence-'+second+' h4').innerText(),/Rejected/);
  await submit(student,student.locator('#occurrence-'+first+' form[action$="/cancel-occurrence"] button'));
  await student.reload();
  assert.match(await student.locator('#occurrence-'+first+' h4').innerText(),/Cancelled/);
  assert.match(await student.locator('#occurrence-'+second+' h4').innerText(),/Rejected/);
  assert.equal(await student.locator('form[action$="/cancel-occurrence"]').count(),0);
  await screenshot(student,'recurring-rejection-and-occurrence-cancellation');
  checks.push({workflow:'Recurring partial approval, rejection and occurrence cancellation',request,occurrences:[first,second],
    verified:'Two dated pickups previewed and submitted with partial consent; custodian selected first approval and second rejection; student cancelled the future approved pickup; each distinct state persisted.'});
}
async function waiting(student,staff){
  const start='2030-02-05T10:00',due='2030-02-06T10:00';
  // The isolated fixture has four units, one physically outstanding overdue.
  // Reserving the three eligible units creates a genuine shortage for this date.
  const blocker=await requestOne(student,start,due,3,'UI10 equipment waiting blocker');
  await staff.goto(base+blocker);
  await submit(staff,staff.locator('form[action$="/approve"] button'));
  await student.goto(base+blocker);await status(student,'Approved');
  await catalog(student,start,due,1,'UI10 equipment queue assignment');
  await submit(student,student.locator('button[name=action][value=recommend]'));
  assert.match(await student.locator('#equipment-result h2').innerText(),/needs adjustment/);
  await student.locator('summary').filter({hasText:'Equipment unavailable? Join its waiting list'}).click();
  await student.locator('[name=acceptWaiting]').check();
  assert.ok(!(await student.locator('button[name=action][value=wait]').isDisabled()));
  await submit(student,student.locator('button[name=action][value=wait]'));
  const queue=new URL(student.url()).pathname;
  assert.match(queue,/^\/waiting-lists\/\d+$/);await status(student,'Pending Review');
  await staff.goto(base+queue);
  await staff.locator('[name=reason]').first().fill('UI10 preapproval without reserving unavailable equipment');
  await submit(staff,staff.locator('button[name=decision][value=approve]'));
  await student.reload();await status(student,'Preapproved');
  assert.match(await student.locator('main').innerText(),/Preapproval does not reserve a resource/);
  assert.match(await student.locator('main').innerText(),/Not assigned/);
  assert.equal(await student.getByRole('link',{name:'Open assigned reservation'}).count(),0);
  await screenshot(student,'equipment-queue-preapproved-unassigned');
  await staff.goto(base+blocker);
  await submit(staff,staff.locator('form[action$="/cancel"] button'));
  await staff.reload();await status(staff,'Cancelled');
  await student.goto(base+queue);await status(student,'Assigned');
  assert.match(await student.locator('main').innerText(),/Collection still requires physical handover/);
  const assigned=student.getByRole('link',{name:'Open assigned reservation'});
  const reservation=await assigned.getAttribute('href');
  await screenshot(student,'equipment-queue-assigned');
  const [response]=await Promise.all([student.waitForNavigation(),assigned.click()]);
  assert.equal(response.status(),200);await status(student,'Approved');
  assert.match(await student.locator('main').innerText(),/UI10 equipment queue assignment/);
  assert.match(await student.locator('main').innerText(),/Awaiting pickup/);
  assert.equal(await student.locator('form[action$="/handover"]').count(),0);
  await screenshot(student,'equipment-assigned-reservation-awaiting-custody');
  await student.goto(base+'/calendar/?view=day&date=2030-02-05');
  const reminder=student.locator('.calendar-event').filter({hasText:'Scheduled pickup: UI10 equipment queue assignment'});
  assert.equal(await reminder.count(),2); // Desktop timetable and responsive agenda share authorized entries.
  assert.match(await reminder.first().innerText(),/Equipment reminder only/);
  assert.doesNotMatch(await reminder.first().innerText(),/Personal commitment/);
  await student.goto(base+'/notifications/');
  assert.ok((await student.locator('main').innerText()).includes('UI10 equipment queue assignment'));
  checks.push({workflow:'Equipment waiting-list preapproval and automatic assignment',blockingRequest:blocker,queue,reservation,
    verified:'Three eligible assets were genuinely reserved; quantity-one request joined with policy consent; preapproval reserved nothing; custodian cancellation released the blocker and automatically assigned the complete queued request; student opened its Approved reservation awaiting physical custody; reminders and notifications reflected it.'});
}
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?
    {executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'msedge'})});
  try{
    const student=await login(browser,1),staff=await login(browser,7);
    await oneTime(student.page,staff.page);
    await recurring(student.page,staff.page);
    await waiting(student.page,staff.page);
    assert.deepEqual(errors,[],'Unexpected JavaScript/console errors');
    assert.deepEqual(httpErrors,[],'Unexpected HTTP errors');
    const report={checks,formActions:actions,screenshots,browserErrors:errors,httpErrors};
    fs.writeFileSync(path.join(output,'equipment-lifecycle-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({workflows:checks.length,realFormActions:actions.length,screenshots,browserErrors:errors,httpErrors},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
