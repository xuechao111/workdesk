import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const begin=source.indexOf('  let teachingStatusPollId=');
const requestCode=source.slice(begin,source.indexOf('  async function uploadCohortExceptionData(',begin));
const refreshBegin=source.indexOf('async function refreshStatus()');
const refreshCode=source.slice(refreshBegin,source.indexOf('refreshStatus();setInterval(',refreshBegin));
const oldStatus={state:'success',message:'old success',time:'2026-11-12 15:00:00',startedAt:'2026-11-12 14:58:00',lastSuccessTime:'2026-11-12 15:00:00'};
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}}
function runtime(){
  const elements=new Map(),calls=[];let clock=Date.parse('2026-11-12 16:00:00');
  class Clock extends Date{constructor(...args){super(...(args.length?args:[clock]))}static now(){return clock}}
  const context={Date:Clock,state:{teachingReady:true,updateState:'success',updateStatus:{...oldStatus}},
    $:id=>{if(!elements.has(id))elements.set(id,{style:{}});return elements.get(id)},
    renderUpdateStatus(){},setTimeout(){},location:{port:'8765'},shouldRefreshTeachingData:()=>false,
    ensureExtensionVersion:async()=>{},extensionRequest:async(...args)=>{calls.push(args);return {ok:true}},
    json:async()=>({...oldStatus})};
  vm.createContext(context);vm.runInContext(requestCode+refreshCode,context);
  return {context,calls,advance:ms=>clock+=ms,button:()=>context.$('#liveDataUpdateBtn')};
}

test('preparation and queued teaching updates ignore old success and reject duplicate clicks',async()=>{
  const r=runtime(),gate=deferred();r.context.ensureExtensionVersion=()=>gate.promise;
  const pending=r.context.updateAll();await r.context.refreshStatus();
  assert.equal(r.context.state.updateStatus.state,'running');assert.equal(r.button().disabled,true);
  assert.equal(await r.context.updateAll(),false);
  gate.resolve();assert.equal(await pending,true);await r.context.refreshStatus();
  assert.equal(r.button().disabled,true);assert.equal(r.calls.length,1);
});

test('a poll begun before a teaching request cannot overwrite its preparation',async()=>{
  const r=runtime(),poll=deferred(),gate=deferred();r.context.json=()=>poll.promise;
  const polling=r.context.refreshStatus();r.context.ensureExtensionVersion=()=>gate.promise;
  const updating=r.context.updateAll();poll.resolve({...oldStatus});await polling;
  assert.equal(r.context.state.updateStatus.state,'running');assert.equal(r.button().disabled,true);
  gate.reject(new Error('fixture stop'));await updating;
});

test('request failures remain visible without writing another task backend status',async()=>{
  const r=runtime();let writes=0;r.context.json=async(url,options)=>{if(options?.method==='POST')writes++;return {...oldStatus}};
  r.context.ensureExtensionVersion=async()=>{throw new Error('connector unavailable')};
  assert.equal(await r.context.updateAll(),false);await r.context.refreshStatus();
  assert.match(r.context.state.updateStatus.detail,/connector unavailable/);assert.equal(writes,0);
  assert.equal(r.context.state.updateStatus.lastSuccessTime,oldStatus.lastSuccessTime);
});

test('current backend progress and success release the submitted request',async()=>{
  const r=runtime();await r.context.updateAll();
  const startedAt=r.context.state.updateStatus.startedAt;
  r.context.json=async()=>({state:'running',message:'writing',time:startedAt,startedAt});
  await r.context.refreshStatus();assert.equal(r.context.state.updateStatus.message,'writing');assert.equal(r.button().disabled,true);
  r.advance(1000);r.context.json=async()=>({state:'success',message:'new success',time:'2026-11-12 16:00:01',startedAt});
  await r.context.refreshStatus();assert.equal(r.context.state.updateStatus.message,'new success');assert.equal(r.button().disabled,false);
});

test('an unacknowledged queue ends visibly instead of leaving update disabled forever',async()=>{
  const r=runtime();await r.context.updateAll();r.advance(121000);await r.context.refreshStatus();
  assert.equal(r.context.state.updateStatus.state,'error');assert.match(r.context.state.updateStatus.detail,/2分钟/);assert.equal(r.button().disabled,false);
});

test('out-of-order status responses cannot replace the newest backend result',async()=>{
  const r=runtime(),oldPoll=deferred(),newPoll=deferred();let count=0;
  r.context.json=()=>++count===1?oldPoll.promise:newPoll.promise;
  const first=r.context.refreshStatus(),second=r.context.refreshStatus();
  newPoll.resolve({state:'success',message:'newest'});await second;
  oldPoll.resolve({state:'running',message:'stale'});await first;
  assert.equal(r.context.state.updateStatus.message,'newest');
});
