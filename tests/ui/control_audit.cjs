/* Inspect real rendered controls and follow same-origin GET destinations. */
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const inventory=[], destinations=new Map(), deadMatches=[];
const removed=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../docs/ui/student-portal/UI-10/dead-code.json')));
const selectors=[...removed.prototypeRules,...removed.legacyRules,...(removed.additionalLegacyRules||[])]
  .filter(r=>!r.startsWith('@')).flatMap(r=>r.split('{')[0].trim().split(','));
selectors.push('.service-button-primary');
function routeFor(address,fixture,method) {
  const pathname=new URL(address).pathname;
  return fixture.routes.find(r=>{
    const pattern=r.rule.split(/(<[^>]+>)/).map(p=>p.startsWith('<')?(p.startsWith('<int:')?'[0-9]+':'[^/]+'):p.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('');
    return r.methods.includes(method)&&new RegExp('^'+pattern+'$').test(pathname);
  });
}
async function inspect(page,label,fixture,actor='student') {
  const rows=await page.locator('a,button,input,select,textarea,summary').evaluateAll(elements=>elements.map(el=>({
    tag:el.tagName,name:el.name||'',type:el.type||'',id:el.id,cls:el.className,
    label:(el.getAttribute('aria-label')||el.textContent||el.labels?.[0]?.textContent||'').trim().slice(0,100),
    href:el.getAttribute('href'),action:el.form?.getAttribute('action'),method:el.form?.method,
    visible:!!el.getClientRects().length,disabled:!!el.disabled,form:!!el.form,
  })));
  for(const row of rows) {
    if(row.tag==='A' && row.href) {
      const address=new URL(row.href,page.url());
      assert.equal(address.origin,new URL(page.url()).origin,'Unexpected external destination');
      const route=routeFor(address,fixture,'GET');assert.ok(route,'Unknown GET '+address);
      row.endpoint=route.endpoint;
      if(row.visible) {
        if(address.hash && address.pathname===new URL(page.url()).pathname && address.search===new URL(page.url()).search) {
          assert.equal(await page.locator('[id="'+decodeURIComponent(address.hash.slice(1))+'"]').count(),1,'Missing anchor '+address);
        } else {
          address.hash='';
          const key=actor+' '+address.href;
          if(!destinations.has(key)) {
            const response=await page.request.get(address.href);
            destinations.set(key,{actor,url:address.href.replace(fixture.url,''),status:response.status(),endpoint:route.endpoint});
            assert.equal(response.status(),200,'Disconnected authorized link '+key);
          }
        }
      }
    } else if(row.form) {
      const route=routeFor(new URL(row.action||page.url(),page.url()),fixture,(row.method||'get').toUpperCase());
      assert.ok(route,'Unknown form '+JSON.stringify(row));row.endpoint=route.endpoint;
    } else if(row.tag==='SUMMARY') row.behavior='Native disclosure';
    else if(row.tag==='BUTTON') {
      assert.ok(/notification-toggle|navigation-toggle|sidebar-close/.test(row.cls)||row.label==='Mark all read','Untraced button '+JSON.stringify(row));
      row.behavior='Existing shell.js / notifications.js handler';
    }
    row.classification=row.disabled?'Intentionally disabled: selection/loading/eligibility state':'Verified functional';
  }
  const matches=await page.evaluate(selectors=>selectors.map(selector=>({selector,count:document.querySelectorAll(selector).length})).filter(r=>r.count),selectors);
  assert.deepEqual(matches,[],'Deleted selector still matches runtime DOM '+label);
  deadMatches.push({actor,label,matched:0,selectors:selectors.length});
  inventory.push({actor,label,url:page.url().replace(fixture.url,''),controls:rows});
}
function save(output) {
  fs.writeFileSync(path.join(output,'controls.json'),JSON.stringify(inventory,null,2)+'\n');
  fs.writeFileSync(path.join(output,'destinations.json'),JSON.stringify([...destinations.values()],null,2)+'\n');
  fs.writeFileSync(path.join(output,'deleted-selector-checks.json'),JSON.stringify(deadMatches,null,2)+'\n');
}
module.exports={inspect,save};
