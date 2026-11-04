/* UI-10 negative authorization contracts against the real disposable Flask app.
 * Only login/session operations may succeed. All resource mutations below must
 * be rejected; the Python review runner independently snapshots committed rows.
 */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'playwright');
const fixture=JSON.parse(fs.readFileSync(process.env.PORTAL_INFO_FILE));
const output=process.env.PORTAL_OUTPUT_DIR;
const base=fixture.url, ids=fixture.ids;
const responses=[], sessionChecks=[], errors=[];
const sessions=new Map();
const forbiddenText=['PRIVATE unrelated appointment','Fictional capstone consultation',
  'Fictional research proposal review','Fictional peer project invitation',
  'Fictional design team workspace','Fictional lab coursework'];

function actionKey(){return crypto.randomBytes(16).toString('hex');}
function field(html,name){
  const match=html.match(new RegExp('name="'+name+'"[^>]*value="([^"]+)"'));
  assert.ok(match,'Fixture form field is missing: '+name);
  return match[1];
}
function privateBody(text){
  for(const value of forbiddenText) assert.ok(!text.includes(value),'Unauthorized record disclosed: '+value);
  assert.ok(!/Traceback|allocation_system\.exe|postgresql\+psycopg/.test(text),'Internal failure details disclosed');
}
async function login(browser,actor,next){
  const context=await browser.newContext({viewport:{width:390,height:900}});
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{
    if(message.type()==='error'&&!message.text().startsWith('Failed to load resource:')) errors.push(message.text());
  });
  await page.goto(base+'/login'+(next===undefined?'':'?next='+encodeURIComponent(next)));
  await page.locator('[name=username]').fill(fixture.users[String(actor)]);
  await page.locator('[name=password]').fill(fixture.password);
  const [response]=await Promise.all([page.waitForNavigation(),page.locator('button[type=submit]').click()]);
  assert.equal(response.status(),200,'Successful login must reach its permitted destination');
  const cookie=(await context.cookies()).find(item=>item.name==='session');
  assert.ok(cookie,'Session cookie missing');
  assert.equal(cookie.httpOnly,true);assert.equal(cookie.sameSite,'Lax');
  const csrf=await page.locator('[data-notifications]').getAttribute('data-csrf');
  assert.ok(csrf);
  return {context,page,csrf,cookie:{httpOnly:cookie.httpOnly,sameSite:cookie.sameSite,secure:cookie.secure}};
}
async function denied(actor,url,form={},status=403,label='Authorization rejection'){
  const session=sessions.get(actor);
  assert.ok(session,'Missing synthetic identity '+actor);
  const response=await session.page.request.post(base+url,{form:{csrf_token:session.csrf,...form}});
  const body=await response.text();
  responses.push({actor,method:'POST',url,status:response.status(),expected:status,label});
  assert.equal(response.status(),status,label+' '+url+'\n'+body.slice(0,500));
  privateBody(body);
}
async function deniedGet(actor,url){
  const response=await sessions.get(actor).page.request.get(base+url);
  responses.push({actor,method:'GET',url,status:response.status(),expected:403,label:'Private or privileged read rejected'});
  assert.equal(response.status(),403,'Unauthorized GET '+actor+' '+url);
  privateBody(await response.text());
}
async function authentication(browser){
  const context=await browser.newContext(), page=await context.newPage();
  await page.goto(base+'/login');
  const missing=await page.request.post(base+'/login',{form:{username:fixture.users['5'],password:fixture.password}});
  assert.equal(missing.status(),400);
  responses.push({actor:'anonymous',method:'POST',url:'/login',status:400,expected:400,label:'Missing login CSRF rejected before authentication'});
  await page.locator('[name=username]').fill(fixture.users['5']);
  await page.locator('[name=password]').fill('Deliberately incorrect synthetic password');
  const [invalid]=await Promise.all([page.waitForNavigation(),page.locator('button[type=submit]').click()]);
  assert.equal(invalid.status(),401);
  assert.equal(await page.locator('[name=username]').inputValue(),fixture.users['5']);
  assert.equal(await page.locator('[name=password]').inputValue(),'');
  assert.match(await page.locator('#sign-in-error').innerText(),/Sign-in failed/);
  responses.push({actor:'anonymous',method:'POST',url:'/login',status:401,expected:401,label:'Incorrect credentials rejected; username retained; password cleared'});
  await context.close();
  for(const target of ['https://example.invalid/','//example.invalid/','/\\example.invalid/']){
    const signed=await login(browser,5,target);
    assert.equal(new URL(signed.page.url()).origin,new URL(base).origin);
    assert.equal(new URL(signed.page.url()).pathname,'/student/');
    sessionChecks.push({check:'Unsafe next rejected',target,actualPath:'/student/',cookie:signed.cookie});
    await signed.context.close();
  }
  const safe='/calendar/?view=week&date=2030-01-07';
  const signed=await login(browser,5,safe);
  assert.equal(signed.page.url(),base+safe);
  sessionChecks.push({check:'Same-origin next preserved',target:safe,actualPath:new URL(signed.page.url()).pathname,cookie:signed.cookie});
  await signed.context.close();
}
async function crossUserMutations(){
  const owner=sessions.get(1).page;
  const appointmentHtml=await (await owner.request.get(base+'/appointments/'+ids.pending)).text();
  const appointmentRevision=field(appointmentHtml,'revision');
  const roomHtml=await (await owner.request.get(base+'/rooms/'+ids.roomPending)).text();
  const roomRevision=field(roomHtml,'revision');
  const seriesHtml=await (await owner.request.get(base+'/rooms/'+ids.roomSeries)).text();
  const roomOccurrence=seriesHtml.match(/\/rooms\/\d+\/occurrences\/(\d+)\/cancel/);
  assert.ok(roomOccurrence,'Seeded room series must expose a real cancellable occurrence');
  const equipmentSeries=await (await owner.request.get(base+'/equipment/'+ids.equipmentSeries)).text();
  const equipmentOccurrence=field(equipmentSeries,'occurrenceId');
  const reportHtml=await (await owner.request.get(base+'/feedback/'+ids.report)).text();
  const reportRevision=field(reportHtml,'revision');
  await owner.goto(base+'/appointments/calendar?month=2030-01&week=2030-01-07');
  const block=await owner.locator('form:has(input[name=action][value=unblock]) input[name=id]').first().inputValue();
  const feed=await (await owner.request.get(base+'/notifications/feed')).json();
  const foreignNotification=feed.html.match(/data-notification-id="(\d+)"/);
  assert.ok(foreignNotification,'Seeded owner must have a real private notification');
  await sessions.get(7).page.goto(base+'/equipment/'+ids.loan);
  const unit=await sessions.get(7).page.locator('form[action$="/return"] input[name=unitIds]').first().inputValue();
  const roomFields={revision:roomRevision,category:'study',purpose:'Unauthorized alteration',description:'Synthetic negative check',
    count:'5',duration:'60',start:'2030-01-14T10:00',roomId:'302',reservationMode:'once'};
  for(const action of ['cancel','reschedule','decline-invitation']){
    await denied(5,'/appointments/'+ids.pending+'/'+action,{revision:appointmentRevision,start:'2030-01-14T15:00'});
  }
  await denied(5,'/appointments/'+ids.pending+'/decision',{revision:appointmentRevision,decision:'approve'});
  await denied(2,'/appointments/'+ids.private+'/decision',{revision:'1',decision:'approve'});
  await denied(5,'/rooms/'+ids.roomPending+'/revise',roomFields);
  await denied(5,'/rooms/'+ids.roomPending+'/decision',{revision:roomRevision,decision:'approve'});
  await denied(5,'/rooms/'+ids.roomPending+'/cancel',{revision:roomRevision});
  await denied(5,'/rooms/'+ids.roomSeries+'/occurrences/'+roomOccurrence[1]+'/cancel',{revision:field(seriesHtml,'revision')});
  await denied(5,'/rooms/'+ids.roomPending+'/invitation',{revision:roomRevision,response:'decline'});
  await denied(1,'/rooms/'+ids.roomPending+'/decision',{revision:roomRevision,decision:'approve'});
  await denied(1,'/rooms/'+ids.roomPending+'/invitation',{revision:roomRevision,response:'accept'});
  for(const actor of [1,5]){
    const operations=[['approve',ids.borrowPending,{reason:'Synthetic forbidden approval'}],
      ['reject',ids.borrowPending,{reason:'Synthetic forbidden rejection'}],
      ['decision',ids.borrowPending,{decision:'approve'}],
      ['handover',ids.collection,{condition:'Synthetic unauthorized handover'}],
      ['return',ids.loan,{unitIds:unit,condition:'usable',notes:'Synthetic unauthorized return'}],
      ['approve-extension',ids.loan,{extensionId:'1'}],['reject-extension',ids.loan,{extensionId:'1'}]];
    for(const [action,request,data] of operations) await denied(actor,'/equipment/'+request+'/'+action,data);
  }
  for(const [action,request,data] of [
    ['cancel',ids.borrowPending,{}],['intend-return',ids.loan,{}],
    ['extension',ids.loan,{due:'2030-01-14T10:00',reason:'Synthetic unauthorized extension'}],
    ['cancel-occurrence',ids.equipmentSeries,{occurrenceId:equipmentOccurrence}],
  ]) await denied(5,'/equipment/'+request+'/'+action,data);
  await denied(5,'/waiting-lists/'+ids.queue+'/cancel');
  await denied(5,'/waiting-lists/'+ids.queue+'/review',{decision:'approve'});
  await denied(1,'/waiting-lists/'+ids.queue+'/review',{decision:'approve'});
  for(const actor of [1,5]) for(const [kind,request] of [['room',ids.roomPending],['equipment',ids.borrowPending]]){
    await denied(actor,'/waiting-lists/priority/'+kind+'/'+request,{priority:'0',reason:'Synthetic unauthorized override'});
  }
  for(const action of ['reply','review']) await denied(5,'/feedback/'+ids.report+'/update',{
    action,revision:reportRevision,action_key:actionKey(),response:'Synthetic unauthorized response',status:'Under Review',priority:'normal'});
  await denied(1,'/feedback/'+ids.report+'/update',{action:'review',revision:reportRevision,
    action_key:actionKey(),response:'Synthetic forbidden staff review',status:'Under Review',priority:'normal'});
  await denied(5,'/appointments/calendar',{action:'unblock',id:block});
  await denied(9,'/appointments/calendar',{action:'unblock',id:block});
  await denied(5,'/notifications/read',{id:foreignNotification[1]});
  await denied(1,'/appointments/'+ids.pending+'/cancel',{revision:'2147483647'},409,'Stale revision rejected without cancellation');
  await denied(1,'/rooms/'+ids.roomPending+'/cancel',{revision:'2147483647'},409,'Stale revision rejected without cancellation');
  await denied(1,'/equipment/'+ids.loan+'/cancel',{},409,'Borrowed equipment cannot be cancelled instead of physically returned');
  const missingCsrf=await owner.request.post(base+'/appointments/'+ids.pending+'/cancel',{form:{revision:appointmentRevision}});
  assert.equal(missingCsrf.status(),400);
  responses.push({actor:1,method:'POST',url:'/appointments/'+ids.pending+'/cancel',status:400,expected:400,label:'Missing resource CSRF rejected'});
}
async function privacyAndRoles(){
  const privatePages=['/appointments/'+ids.appointment,'/rooms/'+ids.room,'/rooms/'+ids.roomPending+'/revise',
    '/equipment/'+ids.loan,'/waiting-lists/'+ids.queue,'/feedback/'+ids.report,'/feedback/new/equipment/'+ids.loan];
  for(const url of privatePages) await deniedGet(5,url);
  for(const actor of [1,5,2,9,7,6]) await deniedGet(actor,'/appointments/'+ids.private);
  for(const actor of [2,9,7,6]) for(const url of ['/appointments/new','/rooms/new','/equipment/catalog']) await deniedGet(actor,url);
  for(const url of ['/appointments/availability','/appointments/calendar-setup','/rooms/configuration',
    '/equipment/inventory/'+ids.faculty,'/equipment/custodians','/waiting-lists/configuration','/calendar/publications','/users']) await deniedGet(1,url);
  for(const url of ['/appointments/','/rooms/','/equipment/','/waiting-lists/','/feedback/',
    '/calendar/?view=week&date=2030-01-07','/appointments/calendar?month=2030-01&week=2030-01-07','/notifications/','/notifications/feed']){
    const response=await sessions.get(5).page.request.get(base+url);
    assert.equal(response.status(),200);privateBody(await response.text());
    responses.push({actor:5,method:'GET',url,status:200,expected:200,label:'Authorized index/feed/calendar contains no unrelated private records'});
  }
  const busy=await sessions.get(5).page.request.get(base+'/rooms/availability/302?date=2030-01-08');
  assert.equal(busy.status(),200);privateBody(await busy.text());
  responses.push({actor:5,method:'GET',url:'/rooms/availability/302?date=2030-01-08',status:200,expected:200,label:'Authorized room busy/free discloses no event titles'});
}
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?
    {executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'msedge'})});
  try{
    await authentication(browser);
    for(const actor of [1,5,2,9,7,6]) sessions.set(actor,await login(browser,actor));
    await crossUserMutations();
    await privacyAndRoles();
    assert.deepEqual(errors,[],'Unexpected JavaScript errors in authorization checks');
    const report={checks:responses.length,results:responses,sessionChecks,browserErrors:errors,
      notes:['Every resource POST uses the caller’s actual valid CSRF token except the explicitly missing-CSRF case.',
        'No credential, session-cookie value, CSRF token or private report body is recorded.',
        'The Python runner independently records PostgreSQL state after each real POST; authorization rejection must leave resource state unchanged.']};
    fs.writeFileSync(path.join(output,'authorization-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({checks:responses.length,statusCounts:responses.reduce((all,row)=>(all[row.status]=(all[row.status]||0)+1,all),{}),sessionChecks,browserErrors:errors},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
