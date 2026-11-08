/* Actual administration pages; reuse the shared keyboard/control inspector. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const {go,login,submit,post,inspect,shot,results,ids,out}=require('../professor/browser_review.cjs');
const phase=process.env.ADMIN_PHASE||'ADM-UI-01';
async function views(page,pages) {
  for(const width of [1440,1024,768,390,320]) {
    await page.setViewportSize({width,height:950});
    for(const [name,url,status=200] of pages) {
      await go(page,url,status); await inspect(page,width,name); await shot(page,name+'-'+width);
    }
  }
}
async function main() {
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const admin=await login(browser,6);
    if(phase==='ADM-UI-01') {
      await views(admin.page,[['home','/administration/'],['filtered-home','/administration/?queue=rooms'],['invalid-queue','/administration/?queue=invalid',400]]);
      if(ids.room)assert.match(await (await admin.page.request.get(new URL('/administration/',admin.page.url()).href)).text(),new RegExp('/rooms/'+ids.room));
      for(const actor of [1,2,7,9]) {
        const user=await login(browser,actor);await go(user.page,'/administration/',403);await user.context.close();
      }
    } else if(phase==='ADM-UI-02') {
      if(!process.env.ADMIN_ACTIONS_ONLY)await views(admin.page,[['academic','/'],['eligibility','/academic-eligibility/'],['review','/academic-eligibility/'+ids.academic],['new-request','/add-request'],['requests','/requests'],['results-empty','/allocation-summary'],['schedules','/schedules']]);
      await go(admin.page,'/academic-eligibility/'+ids.academic);
      await admin.page.locator('[name=reason]').fill('Synthetic administrative eligibility review');
      try {await submit(admin.page,admin.page.locator('button[value=approve]'));}
      catch(error) {
        fs.writeFileSync(path.join(out,'form-diagnostic.json'),JSON.stringify(await admin.page.locator('main form').evaluateAll(forms=>forms.map(f=>({valid:f.checkValidity(),submitting:f.dataset.submitting,method:f.method,action:f.action,
          fields:[...f.elements].filter(x=>x.name!=='csrf_token').map(x=>({name:x.name,value:x.value,disabled:x.disabled,valid:x.checkValidity()}))}))),null,2));
        await admin.page.screenshot({path:path.join(out,'failed-submit.png'),fullPage:true});throw error;
      }
      await post(admin.page,'/academic-eligibility/'+ids.academic,{revision:'1',reviewVersion:'0',decision:'reject',reason:'Stale decision'},409);
      await go(admin.page,'/');
      await admin.page.locator('[name=strategy]').selectOption('priority');
      await submit(admin.page,admin.page.locator('form[action="/set-strategy"] button'));
      await go(admin.page,'/');await submit(admin.page,admin.page.locator('form[action="/run-allocation"] button'));
      await go(admin.page,'/administration/');
      const runLink=await admin.page.locator('#recent-runs a').first().getAttribute('href');
      await views(admin.page,[['run-history',runLink],['results','/allocation-summary'],['request-result','/request/'+ids.academic]]);
      const professor=await login(browser,2);
      await go(professor.page,'/professor/requests/'+ids.academic);
      assert.match(await professor.page.locator('main').innerText(),/Allocated|Approved/);
      await go(professor.page,runLink,403);await professor.context.close();
      await go(admin.page,'/administration/runs/99999999',404);
    } else if(phase==='ADM-UI-03') {
      await views(admin.page,[['room-requests','/rooms/'],['room-review','/rooms/'+ids.room],['room-policy','/rooms/configuration'],['loans','/equipment/'],['inventory','/equipment/inventory/'+ids.faculty],['custodians','/equipment/custodians'],['directory','/users'],['spaces','/spaces']]);
      await go(admin.page,'/users?q=Professor&role=Instructor');assert.match(await admin.page.locator('main').innerText(),/Professor Ada/);
      await go(admin.page,'/spaces?q=nonexistent-synthetic-space');assert.match(await admin.page.locator('main').innerText(),/No rows found/);
      await go(admin.page,'/rooms/'+ids.room);await submit(admin.page,admin.page.locator('button[value=approve]'));
      await go(admin.page,'/equipment/'+ids.equipment);await submit(admin.page,admin.page.locator('form[action$="/approve"] button'));
      const staff=await login(browser,7);await go(staff.page,'/equipment/'+ids.collection,403);await staff.context.close();
      await go(admin.page,'/equipment/inventory/'+ids.otherFaculty,403);
      await go(admin.page,'/equipment/'+ids.collection);await admin.page.locator('form[action$="/handover"] [name=condition]').fill('Synthetic inspected physical units');
      await submit(admin.page,admin.page.locator('form[action$="/handover"] button'));
      const returns=admin.page.locator('form[action$="/return"]');await returns.locator('[name=unitIds]').first().check();
      await returns.locator('[name=notes]').fill('Synthetic verified partial return');await submit(admin.page,returns.locator('button'));
      assert.match(await admin.page.locator('main').innerText(),/Partially Returned/);
      await go(admin.page,'/equipment/inventory/'+ids.faculty);
      const register=admin.page.locator('form').filter({has:admin.page.locator('[name=action][value=unit]')});
      await register.locator('[name=asset_tag]').fill('SYN-ADMIN-NEW');await submit(admin.page,register.locator('button'));
      await post(admin.page,'/equipment/inventory/'+ids.faculty,{action:'unit',type_id:ids.equipmentType,asset_tag:'SYN-ADMIN-NEW',condition:'usable'},409);
      await views(admin.page,[['partial-return','/equipment/'+ids.collection],['confirmed-room','/rooms/'+ids.room]]);
    } else if(phase==='ADM-UI-04') {
      await views(admin.page,[['calendar-month','/calendar/?view=month&date=2030-01-09'],['calendar-week','/calendar/?view=week&date=2030-01-09'],['calendar-day','/calendar/?view=day&date=2030-01-09'],['calendar-setup','/appointments/calendar-setup'],['publication','/calendar/publications'],['waiting-policy','/waiting-lists/configuration'],['waiting-review','/waiting-lists/'+ids.waiting],['managed-feedback','/feedback/?scope=managed'],['issue','/feedback/'+ids.feedback]]);
      await go(admin.page,'/appointments/calendar-setup');
      await admin.page.locator('[name=periodName]').fill('Synthetic explicit teaching week');
      await admin.page.locator('[name=fromDate]').fill('2030-01-07');await admin.page.locator('[name=untilDate]').fill('2030-01-13');
      await admin.page.locator('[name=requestId]').selectOption(String(ids.academic));await admin.page.locator('[name=weekStart]').fill('2030-01-07');
      await submit(admin.page,admin.page.locator('main form button'));
      await go(admin.page,'/calendar/publications');
      const publication=admin.page.locator('main form').filter({has:admin.page.locator('[name=id][value="'+ids.academic+'"]')});
      await publication.locator('[name=visibility]').selectOption('published');await publication.locator('[name=instructor]').selectOption('2');await submit(admin.page,publication.locator('button'));
      const professor=await login(browser,2);await go(professor.page,'/calendar/?view=day&date=2030-01-09');
      assert.match(await professor.page.locator('main').innerText(),/Synthetic teaching declaration/);await professor.context.close();
      await go(admin.page,'/waiting-lists/configuration');
      const notice=admin.page.locator('form').filter({has:admin.page.locator('[name=noticeMinutes]')});
      await notice.locator('[name=noticeMinutes]').fill('90');await submit(admin.page,notice.locator('button'));
      const semester=admin.page.locator('form').filter({has:admin.page.locator('[name=action][value=semester]')});
      await semester.locator('[name=name]').fill('Synthetic explicit semester');await semester.locator('[name=start]').fill('2030-01-01');await semester.locator('[name=end]').fill('2030-06-30');await submit(admin.page,semester.locator('button'));
      await post(admin.page,'/waiting-lists/configuration',{csrf_token:'',noticeMinutes:'100'},400);
      await go(admin.page,'/waiting-lists/'+ids.waiting);await submit(admin.page,admin.page.locator('button[value=approve]'));
      assert.match(await admin.page.locator('main').innerText(),/Preapproved/);
      const borrower=await login(browser,4);await go(borrower.page,'/equipment/'+ids.occupied);
      await submit(borrower.page,borrower.page.locator('form[action$="/cancel"] button'));await borrower.context.close();
      await go(admin.page,'/waiting-lists/'+ids.waiting);assert.match(await admin.page.locator('main').innerText(),/Assigned/);
      await go(admin.page,'/waiting-lists/');await submit(admin.page,admin.page.locator('form[action$="/refresh"] button'));
      await go(admin.page,'/feedback/'+ids.feedback);await admin.page.locator('[name=response]').fill('Synthetic responsible staff response');
      await submit(admin.page,admin.page.locator('form[action$="/update"] button'));
      const student=await login(browser,1);await go(student.page,'/feedback/'+ids.feedback);
      const reply=student.page.locator('form').filter({has:student.page.locator('[name=action][value=reply]')});
      await reply.locator('[name=response]').fill('Synthetic reporter clarification');await submit(student.page,reply.locator('button'));await student.context.close();
      await post(admin.page,'/feedback/'+ids.feedback+'/update',{action:'review',revision:'1',action_key:'a'.repeat(32),status:'Under Review',priority:'normal',response:'Stale response'},409);
      const staff=await login(browser,7);await go(staff.page,'/feedback/'+ids.feedback,403);await go(staff.page,'/waiting-lists/configuration',403);await staff.context.close();
      await views(admin.page,[['published-calendar','/calendar/?view=week&date=2030-01-09'],['assigned-waiting','/waiting-lists/'+ids.waiting],['responded-issue','/feedback/'+ids.feedback]]);
    } else throw Error('Unsupported administration browser phase '+phase);
    const report=results();assert.deepEqual(report.errors,[]);
    assert.ok(report.expectedErrors.every(r=>[400,403,404,409].includes(r.status)),JSON.stringify(report.expectedErrors));
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({phase,views:report.views.length,keyboardSteps:report.keyboardSteps,errors:report.errors}));
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
