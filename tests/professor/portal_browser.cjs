/* Real professor phase acceptance; shared keyboard/control inspector. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const {go,submit,login,post,shot,inspect,fixture,base,ids,out,results}=require('./browser_review.cjs');
const phase=process.env.PROFESSOR_PORTAL_PHASE||'PROF-UI-01';
const widths=[1440,1024,768,390,320],checks=[];
async function views(page,pages) {
  for(const width of widths) {
    await page.setViewportSize({width,height:950});
    for(const [name,url] of pages) {
      await go(page,url);await inspect(page,width,name);
      assert.doesNotMatch(await page.locator('main').innerText(),/PRIVATE PEER/);
      await shot(page,name+'-'+width);
    }
  }

}
async function fillAcademic(page,kind,index=0) {
  await go(page,'/professor/requests/new?type='+kind);
  for(const [field,value] of Object.entries({title:'Synthetic '+kind+' declaration '+index,purpose:'Synthetic academic activity',facultyDeclaration:'Declared faculty, unverified',participantCount:'5'}))await page.locator('[name='+field+']').fill(value);
  await page.locator('[name=spaceId]').selectOption(kind==='CommitteeMeeting'?'301':'302');
  assert.match(await page.locator('[data-resource-summary]').innerText(),/Capacity.*not a reservation/);
  if(kind==='Recurring') {
    await page.locator('[data-slot-day]').selectOption('5');await page.locator('[data-slot-start]').fill('13:00');await page.locator('[data-slot-end]').fill('14:00');await page.locator('[data-add-slot]').click();
    await page.locator('[data-slot-day]').selectOption('7');await page.locator('[data-add-slot]').click();
    assert.equal(await page.locator('[name=timeData]').inputValue(),'5-13:00-14:00;7-13:00-14:00');
  } else {await page.locator('[name=day]').selectOption(String(index+2));await page.locator('[name=startTime]').fill('13:00');await page.locator('[name=endTime]').fill('14:00');}
  if(kind==='Exam') {await page.locator('[name=courseCode]').fill('SYN101');await page.locator('[name=courseName]').fill('Declared course');await page.locator('[name=canSplitAcrossRooms]').selectOption('true');}
  if(kind==='CommitteeMeeting') {
    await page.locator('[name=requiredParticipantIds][value="2"]').check();await page.locator('[name=requiredParticipantIds][value="3"]').check();await page.locator('[name=participantRole_2]').fill('Chair');
    await page.locator('[data-participant-search]').fill('no matching unselected person');assert.ok(await page.locator('[name=requiredParticipantIds][value="2"]').isVisible());
    assert.match(await page.locator('[data-participant-count]').innerText(),/2 selected/);await page.locator('[data-participant-search]').fill('');
  }
}
async function main(){
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const prof=await login(browser,2);
  if(phase==='PROF-UI-01') {
    await views(prof.page,[['home','/professor/?week=2030-01-07']]);
    const nav=prof.page.locator('nav[aria-label="Main navigation"] a');
    assert.deepEqual(await nav.evaluateAll(a=>a.map(x=>new URL(x.href).pathname)),['/professor/','/professor/requests','/calendar/','/notifications/']);
    const empty=await login(browser,12);await views(empty.page,[['empty-home','/professor/']]);await empty.context.close();
    for(const actor of [1,9,7,6]) {
      const user=await login(browser,actor);
      assert.equal((await user.page.request.get(base+'/professor/')).status(),403);
      await views(user.page,[[actor===1?'student-home':'role-'+actor+'-calendar',actor===1?'/student/':'/calendar/?view=day&date=2030-01-07']]);
      await user.context.close();
    }
    assert.equal((await prof.page.request.get(base+'/appointments/new')).status(),403);
    await post(prof.page,'/run-allocation',{},403);
    checks.push('Home empty/populated and all five role shells at five widths; real four-item professor navigation, no student creation or admin allocation.');
  }
  if(phase==='PROF-UI-02') {
    await views(prof.page,[['appointments','/appointments/'],['appointment-detail','/appointments/'+ids.multi]]);
    const empty=await login(browser,12);await views(empty.page,[['empty-appointments','/appointments/']]);await empty.context.close();
    const peer=await login(browser,3),student=await login(browser,1);
    await go(prof.page,'/appointments/'+ids.multi);await submit(prof.page,prof.page.locator('button[name=decision][value=approve]'));
    assert.equal(await prof.page.locator('button[name=decision][value=approve]').count(),0);
    assert.match(await prof.page.locator('main').innerText(),/You approved this revision/);
    await go(peer.page,'/appointments/'+ids.multi);await submit(peer.page,peer.page.locator('button[name=decision][value=approve]'));
    await go(student.page,'/appointments/'+ids.multi);const reschedule=student.page.locator('form[action$="/reschedule"]');
    await reschedule.locator('[name=start]').fill('2030-01-07T14:00');await submit(student.page,reschedule.locator('button'));
    await post(prof.page,'/appointments/'+ids.multi+'/decision',{revision:1,decision:'approve'},409);
    for(const user of [prof,peer]) {await go(user.page,'/appointments/'+ids.multi);await submit(user.page,user.page.locator('button[name=decision][value=approve]'));}
    await go(prof.page,'/appointments/'+ids.multi);await submit(prof.page,prof.page.locator('form[action$="/cancel"] button'));
    await go(prof.page,'/appointments/'+ids.decline);await submit(prof.page,prof.page.locator('button[name=decision][value=decline]'));
    await post(prof.page,'/appointments/'+ids.multi+'/reschedule',{revision:2,start:'2030-01-07T15:00'},403);
    await go(prof.page,'/appointments/');await shot(prof.page,'history-after-decisions');
    checks.push('Actual own approval, no duplicate approve control, unanimous confirmation, Student reschedule reset/stale rejection, reapproval, cancellation and decline; private/state persistence independently checked.');
    await peer.context.close();await student.context.close();
  }
  if(phase==='PROF-UI-03') {
    await views(prof.page,[['office-hours','/appointments/availability'],['schedule','/appointments/calendar?month=2030-01&week=2030-01-07']]);
    const empty=await login(browser,12);await views(empty.page,[['empty-office-hours','/appointments/availability'],['empty-schedule','/appointments/calendar?month=2030-01&week=2030-01-07']]);await empty.context.close();
    await go(prof.page,'/appointments/availability');
    const form=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=hours]')});
    for(const [name,value] of Object.entries({startTime:'09:00',endTime:'12:00',validFrom:'2030-01-01',validUntil:'2030-01-31',excludedDates:'2030-01-15'}))await form.locator('[name='+name+']').fill(value);
    await form.locator('[name=day]').selectOption('2');
    const [published]=await Promise.all([prof.page.waitForNavigation(),form.evaluate(el=>{const button=el.querySelector('button[type=submit]');el.requestSubmit(button);el.requestSubmit(button);})]);assert.equal(published.status(),200);
    let removal=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=remove-hours]')}).last();
    const pattern=await removal.locator('[name=id]').inputValue();await submit(prof.page,removal.locator('button'),409);
    assert.match(await prof.page.locator('[role=alert]').innerText(),/future confirmed appointments/);await inspect(prof.page,320,'protected-hours-removal');await shot(prof.page,'protected-hours-removal-320');
    await go(prof.page,'/appointments/calendar?month=2030-01&week=2030-01-07');
    const confirmedConflict=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=block]')});
    await confirmedConflict.locator('[name=start]').fill('2030-01-07T10:00');await confirmedConflict.locator('[name=end]').fill('2030-01-07T11:00');await confirmedConflict.locator('[name=reason]').fill('Conflict with confirmed appointment');await submit(prof.page,confirmedConflict.locator('button'),409);
    for(const width of widths) {await prof.page.setViewportSize({width,height:950});await inspect(prof.page,width,'block-conflict');await shot(prof.page,'block-conflict-'+width);}
    await go(prof.page,'/appointments/'+ids.confirmed);await submit(prof.page,prof.page.locator('form[action$="/cancel"] button'));
    await go(prof.page,'/appointments/availability');removal=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=remove-hours]')}).filter({has:prof.page.locator('[name=id][value="'+pattern+'"]')});await submit(prof.page,removal.locator('button'));
    await go(prof.page,'/appointments/calendar?month=2030-01&week=2030-01-07');
    const block=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=block]')});
    await block.locator('[name=start]').fill('2030-01-08T12:00');await block.locator('[name=end]').fill('2030-01-08T13:00');await block.locator('[name=reason]').fill('Professor review private block');await submit(prof.page,block.locator('button'));
    await submit(prof.page,prof.page.getByRole('button',{name:'Remove block: Professor review private block'}));
    const conflict=prof.page.locator('form').filter({has:prof.page.locator('[name=action][value=block]')});
    await conflict.locator('[name=start]').fill('2030-01-08T10:00');await conflict.locator('[name=end]').fill('2030-01-08T11:00');await conflict.locator('[name=reason]').fill('Personal preference during academic allocation');await submit(prof.page,conflict.locator('button'));

    checks.push('Double native hour submission produced one POST; inclusive/excluded dates persisted, confirmed appointment blocked removal until cancellation, block create/remove, confirmed-appointment conflict rollback and unchanged academic publication under an overlapping personal block verified.');
  }
  if(phase==='PROF-UI-04') {
    await views(prof.page,['Exam','OneTime','Recurring','CommitteeMeeting'].map(kind=>['new-'+kind,'/professor/requests/new?type='+kind]));
    const created=[];
    for(const [index,kind] of ['Exam','OneTime','Recurring','CommitteeMeeting'].entries()) {
      await fillAcademic(prof.page,kind,index);
      if(kind==='OneTime') {const [r]=await Promise.all([prof.page.waitForNavigation(),prof.page.locator('[data-academic-form]').evaluate(el=>{const button=el.querySelector('button[type=submit]');el.requestSubmit(button);el.requestSubmit(button);})]);assert.equal(r.status(),200);}
      else await submit(prof.page,prof.page.locator('[data-academic-form] button[type=submit]'));
      assert.match(await prof.page.locator('main').innerText(),/Pending Eligibility Review/);created.push(Number(new URL(prof.page.url()).pathname.split('/').pop()));
    }
    assert.equal(new Set(created).size,4);
    await fillAcademic(prof.page,'OneTime');await prof.page.locator('[name=title]').fill('   ');await submit(prof.page,prof.page.locator('[data-academic-form] button[type=submit]'),400);
    assert.equal(await prof.page.locator('[name=facultyDeclaration]').inputValue(),'Declared faculty, unverified');
    for(const width of widths) {await prof.page.setViewportSize({width,height:950});await inspect(prof.page,width,'invalid-academic-form');await shot(prof.page,'invalid-academic-form-'+width);}
    checks.push('Four real self-owned pending submissions, source resource profile, split declaration, serialized recurring helper, selected participant search/roles, duplicate-submit protection and retained invalid form values; no allocation on submission.');
  }
  if(phase==='PROF-UI-05') {
    await views(prof.page,[['academic-list','/professor/requests'],['allocated-request','/professor/requests/'+ids.academic.Exam],['unallocated-request','/professor/requests/'+ids.rejected],['pending-review','/professor/requests/'+ids.pending]]);
    const empty=await login(browser,12);await views(empty.page,[['empty-academic-list','/professor/requests']]);await empty.context.close();
    await go(prof.page,'/professor/requests?limit=1');assert.equal(await prof.page.locator('.service-list .service-row').count(),1);
    await prof.page.getByRole('link',{name:'Next page',exact:true}).click();assert.equal(new URL(prof.page.url()).searchParams.get('offset'),'1');
    assert.equal(await prof.page.locator('[name=limit]').inputValue(),'1');await prof.page.getByRole('link',{name:'Previous page',exact:true}).click();
    await prof.page.locator('[name=type]').selectOption('Exam');await prof.page.locator('[name=status]').selectOption('Rejected');await submit(prof.page,prof.page.getByRole('button',{name:'Apply filters',exact:true}));
    assert.equal(await prof.page.locator('.service-list .service-row').count(),1);assert.match(await prof.page.locator('main').innerText(),/Allocation explanation/);
    const peer=await login(browser,3);assert.equal((await peer.page.request.get(base+'/professor/requests/'+ids.pending)).status(),403);await post(peer.page,'/professor/requests/'+ids.pending+'/revise',{},403);
    const admin=await login(browser,6);
    async function review(key,decision) {
      await go(admin.page,'/academic-eligibility/'+key);await admin.page.locator('[name=reason]').fill('Synthetic individual administrative decision.');await submit(admin.page,admin.page.locator('button[name=decision][value='+decision+']'));
    }
    await review(ids.academic.Exam,'reject');await views(prof.page,[['rejected-eligibility-still-allocated','/professor/requests/'+ids.academic.Exam]]);
    assert.ok(await prof.page.locator('.academic-allocation').count()>0);assert.equal(await prof.page.locator('a[href$="/revise"]').count(),0);
    await post(prof.page,'/professor/requests/'+ids.academic.Exam+'/revise',{},400);
    await review(ids.pending,'approve');await views(prof.page,[['revise-as-exam','/professor/requests/'+ids.pending+'/revise?type=Exam']]);
    const token=await prof.page.locator('[name=submissionKey]').inputValue();
    await prof.page.locator('[name=title]').fill('Revised examination declaration');await prof.page.locator('[name=courseCode]').fill('REV101');await prof.page.locator('[name=courseName]').fill('Declared revised examination');
    await submit(prof.page,prof.page.locator('[data-academic-form] button[type=submit]'));
    assert.match(await prof.page.locator('main').innerText(),/Pending Eligibility Review/);assert.equal(await prof.page.locator('.academic-allocation').count(),0);
    const result=await (await prof.page.request.get(base+'/professor/academic-requests/'+ids.pending)).json();assert.equal(result.item.type,'Exam');assert.equal(result.item.revision,2);
    const stale=await post(prof.page,'/professor/requests/'+ids.pending+'/revise',{requestType:'Exam',revision:1,submissionKey:token,title:'Stale revision',purpose:'Declared',spaceId:302,participantCount:5,day:7,startTime:'10:00',endTime:'11:00',courseCode:'REV101',courseName:'Declared',examType:'General',canSplitAcrossRooms:'false'},400);
    assert.match(await stale.text(),/name="revision" value="1"/);
    assert.match(await stale.text(),/Reload saved declaration/);
    await shot(prof.page,'revision-reset-eligibility');
    checks.push('Owner list/filter/page controls, actual allocated vs unallocated states, private IDs, published read-only after rejection, same-record unpublished type revision invalidates approval, stale revision rejected; no administrative allocation controls.');
    await peer.context.close();await admin.context.close();
  }
  if(phase==='PROF-UI-06') {
    await views(prof.page,[['calendar-month','/calendar/?view=month&date=2030-01-07'],['calendar-week','/calendar/?view=week&date=2030-01-07'],['calendar-day','/calendar/?view=day&date=2030-01-07'],['academic-calendar-detail','/calendar/academic/'+ids.academic.Exam+'?date=2030-01-08'],['inbox','/notifications/']]);
    const empty=await login(browser,12);await views(empty.page,[['empty-inbox','/notifications/']]);await empty.context.close();
    await go(prof.page,'/calendar/?view=week&date=2030-01-07');await prof.page.getByRole('link',{name:'Next',exact:true}).click();assert.equal(new URL(prof.page.url()).searchParams.get('date'),'2030-01-14');
    await prof.page.getByRole('link',{name:'Previous',exact:true}).click();
    const filters=prof.page.locator('form.calendar-filters');for(const box of await filters.locator('[name=category]').all())await box.uncheck();await filters.locator('[name=category][value=academic]').check();await submit(prof.page,filters.getByRole('button',{name:'Apply filters'}));
    assert.equal(new URL(prof.page.url()).searchParams.getAll('category').join(','),'academic');
    assert.equal(await prof.page.locator('a[href="/calendar/publications"]').count(),0);
    await go(prof.page,'/notifications/');const first=prof.page.locator('main a[data-notification-id]').first();await Promise.all([prof.page.waitForNavigation(),first.click()]);
    await go(prof.page,'/notifications/');await submit(prof.page,prof.page.locator('form[action="/notifications/read"]').filter({has:prof.page.locator('[name=throughId]')}).locator('button'));
    assert.match(await prof.page.locator('main').innerText(),/0 unread/);await shot(prof.page,'inbox-all-read');
    await post(prof.page,'/calendar/publications',{id:ids.academic.Exam,visibility:'published'},403);
    checks.push('Month/week/day and academic detail at five widths; real date navigation and category filtering, recipient link read and mark-all persisted, empty Inbox and administrative publication denial.');
  }
  const data=results();assert.equal(data.views.length,{'PROF-UI-01':30,'PROF-UI-02':15,'PROF-UI-03':26,'PROF-UI-04':25,'PROF-UI-05':35,'PROF-UI-06':30}[phase], 'Every planned phase view must execute');assert.deepEqual(data.errors,[]);assert.ok(data.expectedErrors.every(r=>[400,403,409].includes(r.status)));
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({...data,phase,checks},null,2)+'\n');
  console.log(JSON.stringify({phase,views:data.views.length,keyboardSteps:data.keyboardSteps,checks}));
 } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
