import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
const source = readFileSync(new URL('../assets/app.js', import.meta.url), 'utf8');
const between = (start, end) => {
  const a = source.indexOf(start), b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a);
  return source.slice(a, b);
};
const history = between('  function ecHistPrep(', '  // totals for a set of days:');
function sum(records) {
  const d = {days:['2026-09-10'], customers:{list:['Synthetic'],statuses:['Complete','Pending','Cancelled'],history:records}};
  const ctx = {d, ecMask:(data,idx)=>{const mask=new Uint8Array(data.days.length);idx.forEach(i=>mask[i]=1);return mask;}};
  vm.createContext(ctx);
  vm.runInContext(history+'; result=ecHistSum(d,[true],[0],"test");',ctx);
  return ctx.result;
}
const row = (id,status,delivered) => [0,0,id,id+'-sub','2026-09-10','2026-09-10',status,100,status===2?0:100,...(delivered===undefined?[]:[delivered])];

test('delivery rates use actual delivery dates, not booking slots or undelivered statuses',()=>{
  const h=sum([row('next',0,'2026-09-11'),row('same',0,'2026-09-10'),row('pending',1,'2026-09-10'),row('cancelled',2,'2026-09-10')]);
  assert.equal(h.dl0,1); assert.equal(h.dl1,1); assert.equal(h.dln,2);
  assert.equal(h.l0,3,'Booking lead time remains a separate, non-cancelled metric');
});
test('pending-only and legacy histories cannot invent delivered rates',()=>{
  assert.equal(sum([row('pending',1,'2026-09-10')]).dln,0);
  assert.equal(sum([row('legacy',0)]).dln,0);
});

const loader=between('  function loadEcom()', '  function ecPrep(');
const page=between('  function pageEcom()', '  // ------------------------------------------------------------------ store assessment');
function loadContext(status) {
  let requests=0, cleared=0;
  const button={};
  const ctx={S:{page:'ecom',ecomAuthenticated:true,ecomAuthChecked:true},AFTER:[],esc:x=>x,
    $:()=>button,ecUnlocked:()=>ctx.S.ecomAuthenticated,ecClearData:()=>cleared++,ecLockPanel:()=>'<locked>',
    fetch:()=>{requests++;return Promise.resolve({ok:false,status});},render:()=>vm.runInContext('html=pageEcom()',ctx)};
  vm.createContext(ctx);vm.runInContext(loader+page+'; html=pageEcom();',ctx);
  return {ctx,button,requests:()=>requests,cleared:()=>cleared};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('persistent loading failures remain visible and retry only on user action',async()=>{
  const {ctx,button,requests}=loadContext(503);
  await tick(); assert.equal(requests(),1); assert.match(ctx.html,/could not be loaded/); assert.ok(ctx.S.ecomErr);
  ctx.render(); await tick(); assert.equal(requests(),1);
  ctx.AFTER.at(-1)(); button.onclick(); await tick(); assert.equal(requests(),2); assert.match(ctx.html,/could not be loaded/);
});
test('an expired server session returns to login without a request loop',async()=>{
  const {ctx,requests,cleared}=loadContext(401);
  await tick();assert.equal(ctx.S.ecomAuthenticated,false);assert.equal(ctx.html,'<locked>');assert.equal(cleared(),1);assert.equal(requests(),1);
});
test('the old sessionStorage unlock flag does not authorize the new interface',()=>{
  const ctx={S:{},sessionStorage:{getItem:()=> 'unlocked'}};vm.createContext(ctx);
  vm.runInContext(between('  function ecUnlocked()', '  function ecClearData(')+'; result=ecUnlocked()',ctx);
  assert.equal(ctx.result,false);
});

test('locking during an in-flight response cannot repopulate private data or table caches',async()=>{
  let release;
  const ctx={S:{page:'ecom',ecomAuthenticated:true,tables:{'ec-open':{spec:{rows:['synthetic']}},ach:{page:1}}},
    sessionStorage:{removeItem:()=>{}},fetch:()=>new Promise(resolve=>release=resolve),
    ecUnlocked:()=>ctx.S.ecomAuthenticated,ecPrep:()=>assert.fail('A response after Lock must be discarded'),render:()=>{}};
  vm.createContext(ctx);
  vm.runInContext(between('  function ecClearData()', '  function ecCheckSession(')+loader+'; loadEcom(); S.ecomAuthenticated=false; ecClearData();',ctx);
  release({ok:true,json:()=>Promise.resolve({schema:10})});await tick();
  assert.equal(ctx.S.ecom,null);assert.equal(ctx.S.ecomC,null);assert.equal(ctx.S.tables['ec-open'],undefined);assert.ok(ctx.S.tables.ach);
});
