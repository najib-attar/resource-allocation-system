/* Real professor submission/admin review, using the shared browser checks. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const {go,submit,login,post,shot,inspect,base,out,results}=require('./browser_review.cjs');
const checks=[],negative=[];
async function review(page,key,decision='approve') {
  await go(page,'/academic-eligibility/'+key);
  await page.locator('[name=reason]').fill('Synthetic administrative review of the declared academic need.');
  await submit(page,page.locator(`button[name=decision][value=${decision}]`));
}
async function create(page,kind,index) {
  await go(page,'/professor/requests/new?type='+kind);
  await page.locator('[name=title]').fill('Synthetic '+kind+' teaching activity');
  await page.locator('[name=purpose]').fill('Declared academic activity for browser verification');
  await page.locator('[name=facultyDeclaration]').fill('Declared faculty; affiliation unverified');
  await page.locator('[name=participantCount]').fill('5');
  await page.locator('[name=spaceId]').selectOption(kind==='CommitteeMeeting'?'302':'301');
  if(kind==='Recurring')await page.locator('[name=timeData]').fill('5-13:00-14:00;6-13:00-14:00');
  else {
    await page.locator('[name=day]').selectOption(String(index+2));
    await page.locator('[name=startTime]').fill('13:00');await page.locator('[name=endTime]').fill('14:00');
  }
  if(kind==='Exam') {
    await page.locator('[name=courseCode]').fill('SYN101');await page.locator('[name=courseName]').fill('Declared synthetic course');
  }
  if(kind==='CommitteeMeeting') {
    for(const key of ['2','3'])await page.locator(`[name=requiredParticipantIds][value="${key}"]`).check();
    await page.locator('[name=participantRole_2]').fill('Supervisor');
  }
  await submit(page,page.locator('main button[type=submit]'));
  const key=Number(new URL(page.url()).pathname.split('/').pop());
  assert.match(await page.locator('main').innerText(),/Pending Eligibility Review/);
  return key;
}
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    const prof=await login(browser,2),admin=await login(browser,6),peer=await login(browser,3);
    for(const [actor,name] of [[1,'Student'],[2,'Instructor'],[7,'Staff'],[9,'TeachingAssistant']]) {
      const user=await login(browser,actor);
      const response=await user.page.request.get(base+'/academic-eligibility/');assert.equal(response.status(),403);
      negative.push({role:name,path:'/academic-eligibility/',status:403});
      await post(user.page,'/academic-eligibility/1',{revision:1,reviewVersion:0,decision:'approve',reason:'Unauthorized'},403);
      await user.context.close();
    }
    await go(admin.page,'/academic-eligibility/');assert.match(await admin.page.locator('main').innerText(),/Replacement allocation is blocked/);
    for(const width of [1440,768,390,320]) {
      for(const page of [prof.page,admin.page])await page.setViewportSize({width,height:950});
      for(const [page,name,url] of [[prof.page,'academic-list','/professor/requests'],[prof.page,'legacy-detail','/professor/requests/1'],
          [admin.page,'legacy-review','/academic-eligibility/1'],[admin.page,'review-queue','/academic-eligibility/']]) {
        await go(page,url);await inspect(page,width,name);
        assert.doesNotMatch(await page.locator('main').innerText(),/[\u0637\u0622\u00c2\u00c3]/,'Template encoding corruption');
        if(name==='legacy-detail'||name==='legacy-review')assert.match(await page.locator('main').innerText(),/Monday\s*\u00b7\s*10:00\u201311:00/);
        if(width===1440||width===320)await shot(page,name+'-'+width);
      }
      for(const kind of ['Exam','OneTime','Recurring','CommitteeMeeting']) {
        await go(prof.page,'/professor/requests/new?type='+kind);await inspect(prof.page,width,'new-'+kind);
        if(width===320)await shot(prof.page,'new-'+kind+'-320');
      }
    }
    checks.push('All four forms, owner list/detail, legacy review and queue responsive at four widths.');
    await post(admin.page,'/run-allocation',{},302);
    await go(admin.page,'/academic-eligibility/');assert.match(await admin.page.locator('main').innerText(),/Replacement allocation is blocked/);
    const ids=[];
    for(const [index,kind] of ['Exam','OneTime','Recurring','CommitteeMeeting'].entries()) {
      const key=await create(prof.page,kind,index);ids.push(key);await review(admin.page,key);
    }
    // Invalidate an actual approval using the owner form; reject its stale review token.
    const key=ids[1];await go(admin.page,'/academic-eligibility/'+key);
    const version=await admin.page.locator('[name=reviewVersion]').inputValue();
    await go(prof.page,`/professor/requests/${key}/revise`);
    await prof.page.locator('[name=title]').fill('Revised synthetic teaching declaration');
    await submit(prof.page,prof.page.locator('main button[type=submit]'));
    assert.match(await prof.page.locator('main').innerText(),/Pending Eligibility Review/);
    await post(admin.page,'/academic-eligibility/'+key,{revision:1,reviewVersion:version,decision:'approve',reason:'Stale decision'},409);
    await review(admin.page,key);
    await shot(prof.page,'revision-requires-review');
    const pending=await create(prof.page,'OneTime',0);
    assert.equal((await peer.page.request.get(base+'/professor/requests/'+pending)).status(),403);
    await post(prof.page,'/run-allocation',{},403);
    await review(admin.page,1,'reject');
    await shot(admin.page,'legacy-rejected-reservation-preserved');
    assert.match(await admin.page.locator('main').innerText(),/remains in the current publication/);
    await go(prof.page,'/professor/requests/1');
    assert.match(await prof.page.locator('main').innerText(),/Eligibility Rejected/);
    assert.match(await prof.page.locator('main').innerText(),/Approved/);
    assert.equal((await prof.page.request.get(base+'/professor/requests/1/revise')).status(),400);
    await post(prof.page,'/professor/requests/1/revise',{},400);
    checks.push('Active published request stays read-only after eligibility rejection; rejected POST leaves persistence unchanged.');
    await post(admin.page,'/run-allocation',{},302);
    for(const id of ids) {
      const data=await (await prof.page.request.get(base+'/professor/academic-requests/'+id)).json();
      assert.equal(data.item.status,'Approved');assert.equal(data.item.eligibilityStatus,'Eligible');
    }
    const pendingData=await (await prof.page.request.get(base+'/professor/academic-requests/'+pending)).json();
    assert.equal(pendingData.item.status,'Pending');assert.equal(pendingData.item.eligibilityStatus,'Pending Eligibility Review');
    await go(prof.page,'/professor/requests/'+ids[0]);await shot(prof.page,'allocated-academic-request');
    await go(admin.page,'/academic-eligibility/');await shot(admin.page,'reviewed-queue-after-publication');
    checks.push('Real submissions -> approvals -> revision invalidation/stale denial -> legacy rejection preserves reservation -> authorized C++ replacement; pending input excluded.');
    const data=results();assert.deepEqual(data.errors,[]);assert.ok(data.expectedErrors.every(r=>[400,403,409].includes(r.status)));
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({...data,checks,negative,requestIds:ids,pendingId:pending},null,2)+'\n');
    console.log(JSON.stringify({views:data.views.length,keyboardSteps:data.keyboardSteps,checks:checks.length}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
