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
  const data=results();assert.equal(data.views.length,{'PROF-UI-01':30,'PROF-UI-02':15}[phase], 'Every planned phase view must execute');assert.deepEqual(data.errors,[]);assert.ok(data.expectedErrors.every(r=>[400,403,409].includes(r.status)));
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({...data,phase,checks},null,2)+'\n');
  console.log(JSON.stringify({phase,views:data.views.length,keyboardSteps:data.keyboardSteps,checks}));
 } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
