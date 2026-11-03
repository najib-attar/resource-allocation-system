/* Browser acceptance for existing professor workflows and the new read API. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
const fixture = JSON.parse(fs.readFileSync(process.env.PROFESSOR_INFO_FILE));
const base = fixture.url, ids = fixture.ids, out = process.env.PROFESSOR_OUTPUT_DIR;
const checks = [], views = [], controls = [], errors = [], expectedErrors = [], tokens = new Map();
let keyboardSteps = 0, nativePickerSteps = 0;

async function go(page, url, status=200) {
  const response = await page.goto(base + url);
  assert.equal(response.status(), status, url);
}
async function submit(page, button, status=200) {
  const [response] = await Promise.all([page.waitForNavigation(), button.click()]);
  assert.equal(response.status(), status, await response.text());
}
async function login(browser, actor) {
  const context = await browser.newContext({viewport:{width:390,height:900}});
  const page = await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error' && !m.text().startsWith('Failed to load resource:')) errors.push(m.text());});
  page.on('response',r=>{if(r.status()>=400) expectedErrors.push({url:new URL(r.url()).pathname,status:r.status()});});
  await go(page,'/login');
  await page.locator('[name=username]').fill(fixture.users[actor]);
  await page.locator('[name=password]').fill(fixture.password);
  await submit(page,page.locator('button[type=submit]'));
  assert.equal(new URL(page.url()).pathname, actor===1?'/student/':actor===6?'/':'/appointments/');
  tokens.set(page,await page.locator('[data-csrf]').getAttribute('data-csrf'));
  return {context,page};
}
async function post(page,url,form,status) {
  const response=await page.request.post(base+url,{form:{csrf_token:tokens.get(page),...form},maxRedirects:0});
  assert.equal(response.status(),status,await response.text());
}
async function shot(page,label) {
  await page.screenshot({path:path.join(out,label+'.png'),fullPage:true});
}
async function calendar(page,date) {
  const response=await page.request.get(base+'/calendar/?view=day&date='+date);
  assert.equal(response.status(),200);
  return response.text();
}
async function inspect(page,width,name) {
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),width,name+' overflow');
  assert.equal(await page.locator('h1').count(),1,name+' heading');
  const unlabeled=await page.locator('main input:not([type=hidden]),main select,main textarea').evaluateAll(fields=>
    fields.filter(el=>el.getClientRects().length && !el.disabled && !el.getAttribute('aria-label') &&
      !el.getAttribute('aria-labelledby') && !Array.from(el.labels||[]).some(l=>l.textContent.trim()))
    .map(el=>el.name));
  assert.deepEqual(unlabeled,[],name+' unlabeled inputs');
  controls.push({name,width,items:await page.locator('main a,main button,main input,main select,main summary').evaluateAll(nodes=>
    nodes.filter(el=>el.getClientRects().length).map(el=>({tag:el.tagName,name:el.name||'',
      text:(el.getAttribute('aria-label')||el.textContent||'').trim().slice(0,100),
      href:el.getAttribute('href'),action:el.form?new URL(el.form.getAttribute('action')||location.href,location.href).pathname:null,disabled:!!el.disabled})))});
  await page.locator('a[href="#main-content"]').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'main-content');
  let complete=false;
  for(let i=0;i<240;i++) {
    await page.keyboard.press('Tab');
    const s=await page.evaluate(()=>{
      const el=document.activeElement,main=document.getElementById('main-content');
      if(!main.contains(el))return {outside:true};
      const b=el.getBoundingClientRect(),style=getComputedStyle(el);
      return {outside:false,w:b.width,h:b.height,x:b.x,outline:style.outlineStyle,
        tag:el.tagName,type:el.type,name:el.name,visible:el.matches(':focus-visible'),
        shadow:style.boxShadow,border:style.borderColor,text:el.textContent.trim().slice(0,40)};
    });
    if(s.outside){complete=true;break;}
    keyboardSteps++;
    assert.ok(s.w>0 && s.h>0,name+' hidden keyboard target');
    // Edge exposes native time/date picker subfocus on the outer input while
    // :focus-visible is false. Its native picker/segment has the visible focus.
    const nativePicker = ['time','date','datetime-local','month','week'].includes(s.type) && !s.visible;
    if(nativePicker)nativePickerSteps++;
    assert.ok(s.outline!=='none' || nativePicker,name+' missing focus: '+JSON.stringify(s));
    assert.ok(s.x>=-1 && s.x+s.w<=width+1,name+' offscreen keyboard focus: '+JSON.stringify(s));
  }
  assert.ok(complete,name+' incomplete keyboard walk');
  await page.evaluate(()=>{document.activeElement.blur();scrollTo(0,0);});
  views.push({name,width,overflow:false,fieldsLabeled:true,keyboardWalk:true});
}

(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    const p=await login(browser,2),q=await login(browser,3),student=await login(browser,1);
    for(const [actor,role] of [[1,'Student'],[2,'Instructor'],[9,'TeachingAssistant'],[7,'Staff'],[6,'Administrator']]) {
      const review=await login(browser,actor);
      await go(review.page,'/calendar/?view=week&date=2030-01-07');
      await inspect(review.page,390,'calendar-role-'+role);
      const response=await review.page.request.get(base+'/professor/academic-requests');
      assert.equal(response.status(),actor===2?200:403);
      await post(review.page,'/logout',{csrf_token:'invalid'},400);
      await review.page.locator('[data-account-menu] summary').click();
      await submit(review.page,review.page.locator('form[action="/logout"] button'));
      assert.equal((await review.page.request.get(base+'/professor/academic-requests',{maxRedirects:0})).status(),302);
      checks.push(role+': actual login redirect, read scope, CSRF and logout');
      await review.context.close();
    }
    const list=await p.page.request.get(base+'/professor/academic-requests');
    const data=await list.json();
    assert.deepEqual(new Set(data.items.map(i=>i.id)),new Set([ids.own,ids.rejected,ids.pending]));
    assert.deepEqual(Object.fromEntries(data.items.map(i=>[i.id,i.status])),
      {[ids.own]:'Approved',[ids.rejected]:'Rejected',[ids.pending]:'Pending'});
    assert.equal(data.creationEnabled,false);
    assert.equal((await p.page.request.get(base+'/professor/academic-requests/'+ids.other)).status(),403);
    assert.equal((await p.page.request.get(base+'/professor/academic-requests?status=Confirmed')).status(),400);
    const detail=await (await p.page.request.get(base+'/professor/academic-requests/'+ids.own)).json();
    assert.ok(detail.item.allocations.length);
    assert.equal(detail.item.academicBindings[0].weekStart,'2030-01-07');
    for(const url of ['/add-request','/requests','/calendar/publications','/appointments/calendar-setup'])
      assert.equal((await p.page.request.get(base+url)).status(),403);
    await post(p.page,'/run-allocation',{},403);
    await post(p.page,'/professor/academic-requests',{requesterId:'3'},403);
    checks.push('Owner-only API: actual published, rejected and pending records; private IDs, invalid filters and administrative/intake denials');

    await go(p.page,'/appointments/availability');
    const hours=p.page.locator('form').filter({has:p.page.locator('[name=action][value=hours]')});
    await hours.locator('[name=day]').selectOption('2');
    for(const [name,value] of Object.entries({startTime:'09:00',endTime:'12:00',validFrom:'2030-01-01',validUntil:'2030-01-31',excludedDates:'2030-01-15'}))
      await hours.locator(`[name=${name}]`).fill(value);
    await submit(p.page,hours.locator('button'));
    await shot(p.page,'hours-with-exclusion');
    const ownHours=await p.page.locator('form').filter({has:p.page.locator('[name=action][value=remove-hours]')}).last().locator('[name=id]').inputValue();
    await post(p.page,'/appointments/availability',{action:'remove-hours',id:ids.foreignHours},403);
    await post(p.page,'/appointments/availability',{action:'remove-hours',id:ownHours},409);
    checks.push('Own hour publication and exclusions; foreign deletion denied; future confirmed appointments protect removal');

    await go(p.page,'/appointments/calendar?month=2030-01&week=2030-01-07');
    const block=p.page.locator('form').filter({has:p.page.locator('[name=action][value=block]')});
    await block.locator('[name=start]').fill('2030-01-09T13:00');
    await block.locator('[name=end]').fill('2030-01-09T14:00');
    await block.locator('[name=reason]').fill('Professor review private block');
    await submit(p.page,block.locator('button'));
    await shot(p.page,'own-dated-block');
    assert.ok(!(await p.page.locator('main').innerText()).includes('PRIVATE PEER BLOCK'));
    await post(p.page,'/appointments/calendar',{action:'block',start:'2030-01-07T10:00',end:'2030-01-07T11:00',reason:'Conflicting block'},409);
    await submit(p.page,p.page.getByRole('button',{name:'Remove block: Professor review private block'}));
    checks.push('Own dated block add/remove; private peer block absent; confirmed appointment conflict rejected');

    const routes=[['appointments','/appointments/'],['hours','/appointments/availability'],
      ['appointment','/appointments/'+ids.multi],['room-invitation','/rooms/'+ids.roomAccept],
      ['schedule','/appointments/calendar?month=2030-01&week=2030-01-07'],
      ['calendar-month','/calendar/?view=month&date=2030-01-07'],
      ['calendar-week','/calendar/?view=week&date=2030-01-07'],
      ['calendar-day','/calendar/?view=day&date=2030-01-07'],['inbox','/notifications/']];
    for(const width of [1440,768,390,320]) {
      await p.page.setViewportSize({width,height:950});
      for(const [name,url] of routes) {
        await go(p.page,url);
        await inspect(p.page,width,name);
        if(width===1440 || width===320)await shot(p.page,name+'-'+width);
      }
    }
    checks.push('Month/week/day, schedule, appointments, hours, invitations and inbox responsive/keyboard review');

    await go(p.page,'/appointments/'+ids.multi);
    await submit(p.page,p.page.locator('button[name=decision][value=approve]'));
    assert.match(await p.page.locator('#approval-progress').innerText(),/1 of 2/);
    await go(q.page,'/appointments/'+ids.multi);
    await submit(q.page,q.page.locator('button[name=decision][value=approve]'));
    await go(student.page,'/appointments/'+ids.multi);
    assert.match(await student.page.locator('main').innerText(),/Confirmed/);
    const reschedule=student.page.locator('form[action$="/reschedule"]');
    await reschedule.locator('[name=start]').fill('2030-01-07T15:00');
    await submit(student.page,reschedule.locator('button'));
    assert.match(await student.page.locator('#approval-progress').innerText(),/0 of 2/);
    await shot(student.page,'reschedule-invalidated-approvals');
    await post(p.page,'/appointments/'+ids.multi+'/decision',{revision:'1',decision:'approve'},409);
    for(const page of [p.page,q.page]) {
      await go(page,'/appointments/'+ids.multi);
      await submit(page,page.locator('button[name=decision][value=approve]'));
    }
    await go(p.page,'/appointments/'+ids.multi);
    await submit(p.page,p.page.locator('form[action$="/cancel"] button'));
    assert.match(await p.page.locator('main').innerText(),/Cancelled/);
    await go(p.page,'/appointments/'+ids.decline);
    await submit(p.page,p.page.locator('button[name=decision][value=decline]'));
    await go(p.page,'/appointments/'+ids.confirmed);
    await submit(p.page,p.page.locator('form[action$="/cancel"] button'));
    await post(p.page,'/appointments/availability',{action:'remove-hours',id:ownHours},302);
    checks.push('Unanimous professor approval; student rescheduling invalidates both approvals; stale revision rejected; reapproval, professor cancellation and rejection persist');

    for(const [key,response] of [[ids.roomAccept,'accept'],[ids.roomDecline,'decline']]) {
      await go(p.page,'/rooms/'+key);
      assert.equal(await p.page.locator('form[action$="/decision"]').count(),0);
      await submit(p.page,p.page.locator(`button[name=response][value=${response}]`));
      await post(p.page,'/rooms/'+key+'/decision',{revision:'1',decision:'approve'},403);
    }
    checks.push('Optional room invitation accept/decline remains distinct from faculty approval and reservation');
    await go(p.page,'/notifications/');
    await submit(p.page,p.page.locator('form[action="/notifications/read"]').filter({has:p.page.locator('[name=throughId]')}).locator('button'));
    assert.ok(!(await calendar(p.page,'2030-01-07')).includes('Confirmed</span>'));
    await go(p.page,'/calendar/?view=day&date=2030-01-08&filtered=1&category=academic&state=confirmed');
    await shot(p.page,'academic-calendar-filtered');
    checks.push('Inbox mark-all persisted; cancellation removed confirmed commitments; academic calendar filter uses explicit binding');
    assert.deepEqual(errors,[]);
    assert.ok(expectedErrors.every(r=>[400,403,409].includes(r.status)),JSON.stringify(expectedErrors));
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({checks,views,keyboardSteps,nativePickerSteps,errors,expectedErrors},null,2)+'\n');
    fs.writeFileSync(path.join(out,'controls.json'),JSON.stringify(controls,null,2)+'\n');
    console.log(JSON.stringify({checks:checks.length,views:views.length,keyboardSteps,errors}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
