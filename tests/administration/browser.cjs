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
    } else throw Error('Unsupported administration browser phase '+phase);
    const report=results();assert.deepEqual(report.errors,[]);
    assert.ok(report.expectedErrors.every(r=>[400,403,404,409].includes(r.status)),JSON.stringify(report.expectedErrors));
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({phase,views:report.views.length,keyboardSteps:report.keyboardSteps,errors:report.errors}));
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
