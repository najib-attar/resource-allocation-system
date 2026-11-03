/* Final integration/accessibility audit of the real loopback Flask application. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const root = path.resolve(__dirname, '../..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'build/student-portal/preview.json')));
const output = path.join(root, 'docs/ui/student-portal/UI-09');
const widths = [1440,768,390,320];
const id = fixture.ids;
const pages = [
  ['home','/student/?week=2030-01-07'], ['appointments','/appointments/'], ['appointment-new','/appointments/new'],
  ['appointment','/appointments/'+id.pending], ['invitation','/appointments/'+id.invitation],
  ['rooms','/rooms/'], ['room-new','/rooms/new'], ['room','/rooms/'+id.room],
  ['room-pending','/rooms/'+id.roomPending], ['room-revise','/rooms/'+id.roomPending+'/revise'],
  ['room-series','/rooms/'+id.roomSeries], ['room-availability','/rooms/availability/302?date=2030-01-08'],
  ['equipment','/equipment/'], ['equipment-catalog','/equipment/catalog?start=2030-01-07T10:00&due=2030-01-09T10:00'],
  ['equipment-loan','/equipment/'+id.loan], ['equipment-pending','/equipment/'+id.borrowPending],
  ['equipment-series','/equipment/'+id.equipmentSeries], ['waiting','/waiting-lists/'],
  ['waiting-detail','/waiting-lists/'+id.queue], ['waiting-policy','/waiting-lists/policy'],
  ['feedback','/feedback/'], ['feedback-new','/feedback/new/equipment/'+id.loan], ['feedback-detail','/feedback/'+id.report],
  ['calendar-month','/calendar/?view=month&date=2030-01-07'], ['calendar-week','/calendar/?view=week&date=2030-01-07'],
  ['calendar-day','/calendar/?view=day&date=2030-01-07'], ['calendar-published','/calendar/?view=day&date=2030-01-08&scope=published'],
  ['academic','/calendar/academic/'+id.academic+'?date=2030-01-08'],
  ['schedule','/appointments/calendar?month=2030-01&week=2030-01-07'], ['inbox','/notifications/'],
];
async function login(page, actor, base=fixture) {
  await page.goto(base.url+'/login');
  await page.locator('[name=username]').fill(base.users[String(actor)]);
  await page.locator('[name=password]').fill(base.password);
  await Promise.all([page.waitForNavigation(),page.locator('button[type=submit]').click()]);
}
async function keyboard(page, width, name) {
  await page.locator('a[href="#main-content"]').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(()=>document.activeElement.id), 'main-content');
  let steps=0, reachedEnd=false;
  for (;steps<160;steps++) {
    await page.keyboard.press('Tab');
    const state = await page.evaluate(()=>{
      const el=document.activeElement, main=document.getElementById('main-content');
      if (!main.contains(el)) return {outside:true};
      const b=el.getBoundingClientRect();
      const region=el.getAttribute('role')==='region';
      const fragments=Array.from(el.getClientRects());
      const visible=fragments.every(r=>{
        const y=region && r.height>innerHeight ? Math.max(5,Math.min(innerHeight-120,(Math.max(0,r.y)+Math.min(innerHeight-120,r.bottom))/2)) : r.y+r.height/2;
        const hit=document.elementFromPoint(r.x+r.width/2,y);
        return hit===el || el.contains(hit);
      });
      return {outside:false,tag:el.tagName,cls:el.className,text:el.textContent.trim().slice(0,55),
        x:b.x,y:b.y,w:b.width,h:b.height,outline:getComputedStyle(el).outlineStyle,visible};
    });
    if (state.outside) {reachedEnd=true;break;}
    assert.ok(state.w>0 && state.h>0, name+': hidden keyboard target '+JSON.stringify(state));
    assert.ok(state.x>=-1 && state.x+state.w<=width+1, name+': keyboard bounds '+JSON.stringify(state));
    assert.notEqual(state.outline,'none',name+': no focus indicator '+JSON.stringify(state));
    assert.ok(state.visible,name+': obscured keyboard focus '+JSON.stringify(state));
  }
  assert.ok(reachedEnd,name+': complete main-content keyboard walk did not finish');
  return steps;
}
async function inspect(page,width,name,student=true) {
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width,name+': page overflow');
  assert.equal(await page.locator('h1').count(),1,name+': heading');
  const unlabeled=await page.locator('main input:not([type=hidden]),main select,main textarea').evaluateAll(fields=>fields.filter(el=>{
    if (!el.getClientRects().length || el.disabled) return false;
    return !((el.getAttribute('aria-label')||'').trim() ||
      (el.getAttribute('aria-labelledby')||'').split(/\s+/).some(id=>document.getElementById(id)?.textContent.trim()) ||
      Array.from(el.labels||[]).some(label=>label.textContent.trim()));
  }).map(el=>({tag:el.tagName,name:el.name})));
  assert.deepEqual(unlabeled,[],name+': unlabeled form controls');
  if (student) {
    assert.equal(await page.locator('.app-navigation a').count(),4);
    assert.deepEqual(await page.locator('.app-navigation a').evaluateAll(links=>links.map(a=>new URL(a.href).pathname+new URL(a.href).hash)),
      ['/student/','/student/#my-activity','/calendar/','/notifications/']);
  }
  const steps=await keyboard(page,width,name);
  await page.evaluate(()=>{document.activeElement.blur();scrollTo(0,0);});
  return steps;
}
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?
    {executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'msedge'})});
  const results=[], errors=[];
  let totalViews=0, keyboardSteps=0;
  try {
    const context=await browser.newContext();
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    for (const width of widths) {
      await page.setViewportSize({width,height:900});
      assert.equal((await page.goto(fixture.url+'/login')).status(),200);
      keyboardSteps+=await inspect(page,width,'final-login',false);
      await page.screenshot({path:path.join(output,`final-login-${width}.png`),fullPage:true});
      totalViews++;
    }
    results.push('Final minimal login at all four widths: complete keyboard walk, form labels, focus and overflow passed');
    await login(page,1);
    for (const [name,url] of pages) {
      for (const width of widths) {
        await page.setViewportSize({width,height:900});
        const response=await page.goto(fixture.url+url);
        assert.equal(response.status(),200,name+': response');
        assert.ok(!(await page.locator('body').innerText()).includes('PRIVATE unrelated'));
        keyboardSteps+=await inspect(page,width,name);
        if (['home','schedule'].includes(name)) await page.screenshot({path:path.join(output,`final-${name}-${width}.png`),fullPage:true});
        totalViews++;
      }
      const forms=await page.locator('form[method=post]').evaluateAll(forms=>forms.map(form=>({
        action:new URL(form.getAttribute('action')||location.href,location.href).href,
        csrf:form.querySelector('[name=csrf_token]')?.value})));
      for (const form of forms) {
        assert.ok(form.csrf,name+': CSRF input');
        assert.equal(new URL(form.action).origin,new URL(fixture.url).origin);
        assert.equal((await page.request.post(form.action)).status(),400,name+': CSRF rejection');
      }
      results.push(name+': all four widths; complete keyboard walk, labels, focus, navigation, privacy, status and CSRF passed');
    }
    for (const url of ['/appointments/availability','/appointments/calendar-setup','/rooms/configuration',
      '/equipment/inventory/'+id.faculty,'/equipment/custodians','/waiting-lists/configuration','/calendar/publications','/requests']) {
      assert.equal((await page.request.get(fixture.url+url)).status(),403,'Student privilege boundary '+url);
    }
    // Exercise actual CSRF rejection as a browser navigation, with no API mock.
    await page.goto(fixture.url+'/appointments/'+id.pending);
    const form=page.locator('form[action$="/cancel"]');
    await form.locator('[name=csrf_token]').evaluate(el=>{el.value='invalid';});
    const [csrfResponse]=await Promise.all([page.waitForNavigation(),form.locator('button').click()]);
    assert.equal(csrfResponse.status(),400);
    await page.screenshot({path:path.join(output,'csrf-error-320.png'),fullPage:true});
    results.push('Eight staff/administration-only GET boundaries denied; real CSRF rejection retained HTTP 400 and student error presentation');
    await context.close();
    const rolePages={
      2:['/appointments/','/appointments/availability','/appointments/calendar?month=2030-01&week=2030-01-07','/rooms/','/equipment/','/waiting-lists/','/feedback/','/calendar/?date=2030-01-07','/notifications/'],
      7:['/appointments/','/rooms/','/rooms/'+id.roomPending,'/equipment/','/equipment/'+id.loan,'/equipment/inventory/'+id.faculty,'/waiting-lists/','/feedback/','/feedback/'+id.report,'/calendar/?date=2030-01-07','/notifications/'],
      6:['/','/requests','/rooms/configuration','/equipment/custodians','/waiting-lists/configuration','/calendar/publications','/notifications/'],
    };
    for (const [actor,urls] of Object.entries(rolePages)) {
      const roleContext=await browser.newContext();const rolePage=await roleContext.newPage();
      rolePage.on('pageerror',e=>errors.push(e.message));await login(rolePage,actor);
      for (const width of [1440,390]) {
        await rolePage.setViewportSize({width,height:900});
        for (const url of urls) {
          const response=await rolePage.goto(fixture.url+url);
          assert.equal(response.status(),200,'Role '+actor+' '+url);
          assert.equal(await rolePage.locator('.student-service').count(),0);
          assert.equal(await rolePage.locator('link[href$="student-services.css"]').count(),0);
          assert.equal(await rolePage.evaluate(()=>document.documentElement.scrollWidth),width,'Role overflow '+actor+' '+url);
          totalViews++;
        }
        await rolePage.screenshot({path:path.join(output,`role-${actor}-${width}.png`),fullPage:true});
        if (width===390) {
          await rolePage.locator('[data-navigation-toggle]').click();
          assert.equal(await rolePage.locator('#app-sidebar').getAttribute('role'),'dialog');
          await rolePage.keyboard.press('Escape');
          assert.equal(await rolePage.locator('#app-sidebar').isVisible(),false);
          assert.ok(await rolePage.evaluate(()=>document.activeElement.hasAttribute('data-navigation-toggle')));
        }
      }
      results.push('Role '+actor+': '+urls.length+' existing views at desktop/mobile, original shell, no student stylesheet, no overflow and drawer/Escape focus passed');
      await roleContext.close();
    }
    const fault=JSON.parse(fs.readFileSync(path.join(root,'build/student-portal/unavailable-preview.json')));
    const faultContext=await browser.newContext();const faultPage=await faultContext.newPage();
    await login(faultPage,1,fault);
    for (const width of widths) {
      await faultPage.setViewportSize({width,height:900});
      const response=await faultPage.goto(fault.url+'/equipment/catalog');
      assert.equal(response.status(),503);
      assert.equal(response.headers()['cache-control'],'private, no-store');
      assert.match(await faultPage.locator('main').innerText(),/Service temporarily unavailable/);
      assert.ok(!(await faultPage.locator('body').innerText()).includes('allocation_system.exe'));
      keyboardSteps+=await inspect(faultPage,width,'real-service-unavailable');
      await faultPage.screenshot({path:path.join(output,`service-unavailable-${width}.png`),fullPage:true});
      totalViews++;
    }
    await faultContext.close();
    results.push('Real separate review server with an intentionally tiny existing engine timeout: 503 at four widths, safe private presentation, labels, keyboard and overflow passed; no responses mocked');
    assert.deepEqual(errors,[],'Browser JavaScript errors');
    const report={totalViews,keyboardSteps,results,browserErrors:errors};
    fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
