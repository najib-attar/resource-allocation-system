/* Actual administration pages; reuse the shared keyboard/control inspector. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const {go,login,inspect,shot,results,ids,out}=require('../professor/browser_review.cjs');
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
    } else throw Error('Unsupported administration browser phase '+phase);
    const report=results();assert.deepEqual(report.errors,[]);
    assert.ok(report.expectedErrors.every(r=>[400,403,404,409].includes(r.status)),JSON.stringify(report.expectedErrors));
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({phase,views:report.views.length,keyboardSteps:report.keyboardSteps,errors:report.errors}));
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
