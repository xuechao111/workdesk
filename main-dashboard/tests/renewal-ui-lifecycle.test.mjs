import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const begin=source.indexOf('  function renderScholarshipStatus(');
const code=source.slice(begin,source.indexOf("  $('#scholarshipBtn').onclick=updateScholarship;",begin));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
const oldStatus={state:'success',message:'old result',startedAt:'2026-10-31 18:43:00',time:'2026-10-31 18:43:05'};
function runtime(){
  const elements=new Map(),calls=[],timers=[];
  const ctx={state:{renewalReady:true,scholarshipStatus:{...oldStatus}},renewalMonthInput:{disabled:false},
    $:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id)},selectedRenewalMonth:()=> '2026-12',elapsedText:()=> '1秒',
    localStorage:{setItem(){}},ensureExtensionVersion:async()=>{},extensionRequest:async(...args)=>{calls.push(args);return {ok:true,data:{rows:[{id:1}]}}},
    json:async(url)=>url==='/scholarship-status'?{...oldStatus}:{ok:true},utf8Base64:JSON.stringify,
    setTimeout:fn=>timers.push(fn)};
  vm.createContext(ctx);vm.runInContext(code,ctx);
  return {ctx,calls,timers,elements,button:()=>ctx.$('#scholarshipBtn'),status:()=>ctx.$('#scholarshipStatus')};
}

test('CRM preparation cannot be overwritten by old success and duplicate clicks cannot collect twice',async()=>{
  const r=runtime(),gate=deferred();r.ctx.ensureExtensionVersion=()=>gate.promise;
  const updating=r.ctx.updateScholarship();
  assert.equal(r.button().disabled,true);await r.ctx.refreshScholarshipStatus();
  assert.match(r.status().textContent,/正在读取/);assert.equal(r.button().disabled,true);
  assert.equal(await r.ctx.updateScholarship(),false);
  gate.resolve();assert.equal(await updating,true);assert.equal(r.calls.length,1);
  await r.ctx.refreshScholarshipStatus();assert.match(r.status().textContent,/等待本地写表结果/);assert.equal(r.button().disabled,true);
});

test('a failed extension request remains visible instead of being replaced with an old success',async()=>{
  const r=runtime();r.ctx.extensionRequest=async()=>{throw new Error('connector unavailable')};
  assert.equal(await r.ctx.updateScholarship(),false);assert.match(r.status().textContent,/connector unavailable/);
  await r.ctx.refreshScholarshipStatus();assert.match(r.status().textContent,/connector unavailable/);assert.equal(r.button().disabled,false);
  r.ctx.extensionRequest=async()=>({data:{rows:[1]}});assert.equal(await r.ctx.updateScholarship(),true);
});

test('a status request started before a new update cannot overwrite its current state',async()=>{
  const r=runtime(),poll=deferred(),gate=deferred();r.ctx.json=()=>poll.promise;
  const polling=r.ctx.refreshScholarshipStatus();r.ctx.ensureExtensionVersion=()=>gate.promise;
  const updating=r.ctx.updateScholarship();poll.resolve({...oldStatus});await polling;
  assert.match(r.status().textContent,/正在读取/);assert.equal(r.button().disabled,true);
  gate.reject(new Error('stop fixture'));await updating;
});

test('only this request current backend status releases the submitted request',async()=>{
  const r=runtime();await r.ctx.updateScholarship();
  const started=r.ctx.state.scholarshipStatus.startedAt;
  r.ctx.json=async()=>({state:'running',message:'writing',startedAt:started,time:started});
  await r.ctx.refreshScholarshipStatus();assert.equal(r.ctx.state.scholarshipStatus.message,'writing');assert.equal(r.button().disabled,true);
  r.ctx.json=async()=>({state:'success',message:'fresh result',startedAt:started,time:started});
  await r.ctx.refreshScholarshipStatus();assert.equal(r.ctx.state.scholarshipStatus.message,'fresh result');assert.equal(r.button().disabled,false);
});

test('explicit connector and local startup errors are displayed with useful details',async()=>{
  for(const failure of ['crm','local']){
    const r=runtime();
    if(failure==='crm')r.ctx.extensionRequest=async()=>({ok:false,error:'CRM_LOGIN_EXPIRED'});
    else r.ctx.json=async()=>({ok:false,error:'WRITER_BUSY'});
    assert.equal(await r.ctx.updateScholarship(),false);
    assert.match(r.status().textContent,failure==='crm'?/CRM_LOGIN_EXPIRED/:/WRITER_BUSY/);
  }
});

test('selecting another month does not relabel the last successful renewal month',()=>{
  const r=runtime();r.ctx.state.scholarshipStatus={state:'success',message:'updated',time:'2026-11-06 15:58:24',lastSuccessTime:'2026-11-06 15:58:24',lastSuccessMonth:'2026-11-01'};
  r.ctx.renderScholarshipStatus();
  let brief=r.ctx.$('#scholarshipBrief').textContent;
  assert.match(brief,/已选 2026-12/);assert.match(brief,/上次成功 2026-11 11-06 15:58:24/);
  r.ctx.selectedRenewalMonth=()=> '2027-01';r.ctx.renderScholarshipStatus();brief=r.ctx.$('#scholarshipBrief').textContent;
  assert.match(brief,/已选 2027-01/);assert.match(brief,/上次成功 2026-11 11-06 15:58:24/);
});

test('local startup errors retain the last successful month and time while the error remains visible',async()=>{
  const r=runtime();r.ctx.state.scholarshipStatus={state:'success',message:'updated',time:'2026-11-06 15:58:24',lastSuccessMonth:'2026-11-01'};
  r.ctx.extensionRequest=async()=>{throw new Error('login expired')};
  await r.ctx.updateScholarship();
  assert.match(r.status().textContent,/login expired/);assert.match(r.ctx.$('#scholarshipBrief').textContent,/上次成功 2026-11 11-06 15:58:24/);
});

test('legacy success with no month never invents a successful selected month',()=>{
  const r=runtime();r.ctx.renderScholarshipStatus();
  assert.match(r.ctx.$('#scholarshipBrief').textContent,/上次成功 10-31 18:43:05/);
  assert.doesNotMatch(r.ctx.$('#scholarshipBrief').textContent,/上次成功 2026-12/);
});
