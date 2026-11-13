import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../chrome-extension/background.js',import.meta.url),'utf8');
const fn=(name,next)=>source.slice(source.indexOf(`async function ${name}(`),source.indexOf(`async function ${next}(`));
function harness({phase='local',owner=false,serviceFail=false}={}){
 const state={updateRuntime:{runningSince:Date.now(),slotKey:'slot'},autoSchedule:{}};
 const calls=[];let ctx;
 const active=new Set(owner?['main']:[]);
 ctx={LOCAL_BASE:'main',CRM_RUNTIME_TIMEOUT_MS:360000,LOCAL_RUNTIME_TIMEOUT_MS:660000,activeUpdateRuns:active,
 normalizeLocalBase:x=>x,instanceStorageKey:n=>n,
 chrome:{storage:{local:{get:async()=>({...state}),set:async value=>Object.assign(state,value),remove:async key=>{delete state[key]}}}},
 fetchWithTimeout:async()=>({ok:true,json:async()=>({state:'success',phase,time:new Date().toISOString()})}),
 postLocalStatus:async(...a)=>calls.push(['status',...a]),appendRunLog:async()=>{},startMcpRelay:()=>()=>{},
 waitForLocalPreparation:async()=>({alreadyRunning:true}),waitForLocalCompletion:async()=>({message:'local done'}),
 runScheduledServiceUpdate:async()=>{calls.push(['service']);await ctx.reconcileUpdateRuntime('main');if(serviceFail)throw Error('service failed')},
 setTimeout:callback=>{callback();return 0},Date,Set};
 vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('function isCrmAuthenticationFailure('),source.indexOf('async function fetchInCrm('))+fn('reconcileUpdateRuntime','waitForTabReady')+fn('runScheduledUpdate','checkMissedSchedules'),ctx);
 return {ctx,state,calls,active};
}
test('watchdog keeps live owner lock during intermediate local success',async()=>{
 const h=harness({owner:true});await h.ctx.reconcileUpdateRuntime('main');assert.ok(h.state.updateRuntime);assert.equal(h.state.autoSchedule.lastSuccessKey,undefined);
});
test('restart recovery does not stamp local-only completion as whole success',async()=>{
 const h=harness();await h.ctx.reconcileUpdateRuntime('main');assert.equal(h.state.autoSchedule.lastSuccessKey,undefined);assert.match(h.state.autoSchedule.lastResult,/教学服务未确认/);
});
test('joined local update must complete service before successful schedule',async()=>{
 const h=harness();delete h.state.updateRuntime;const r=await h.ctx.runScheduledUpdate('slot','main');assert.equal(r.ok,true);assert.equal(h.calls.filter(x=>x[0]==='service').length,1);assert.equal(h.state.autoSchedule.lastSuccessKey,'slot');assert.equal(h.active.size,0);
});
test('joined update failing service retries and remains failed',async()=>{
 const h=harness({serviceFail:true});delete h.state.updateRuntime;const r=await h.ctx.runScheduledUpdate('slot','main');assert.equal(r.ok,false);assert.equal(h.calls.filter(x=>x[0]==='service').length,2);assert.equal(h.state.autoSchedule.lastSuccessKey,undefined);assert.equal(h.active.size,0);
});
test('service completion ignores another run even with a fresh success timestamp',async()=>{
 const now=Date.now();const statuses=[{state:'success',runId:'other',time:new Date(now).toISOString()},{state:'success',runId:'expected',time:new Date(now).toISOString()}];let reads=0;
 const ctx={LOCAL_BASE:'main',normalizeLocalBase:x=>x,Date,setTimeout:callback=>{callback();return 0},fetchWithTimeout:async()=>({ok:true,json:async()=>statuses[reads++]})};
 vm.createContext(ctx);vm.runInContext(fn('waitForServiceCompletion','runScheduledServiceUpdate'),ctx);
 const result=await ctx.waitForServiceCompletion(now,1000,'main','expected');assert.equal(result.runId,'expected');assert.equal(reads,2);
});

for(const [message,code,expected] of [
 ['浏览器已登录但标签已关闭','UPDATE_FAILED','error'],
 ['CRM读取失败：网络中断','CRM_READ_FAILED','error'],
 ['请先在当前浏览器打开并登录CRM后台','CRM_READ_FAILED','error'],
 ['当前浏览器的CRM登录已失效','CRM_AUTH_REQUIRED','waiting'],
 ['当前谷歌浏览器的 Superset 登录已失效，请在原页面登录后重试。','', 'waiting']
])test(`scheduler classifies ${code||'Superset auth'} as ${expected}: ${message}`,async()=>{
 const h=harness();delete h.state.updateRuntime;
 h.ctx.waitForLocalPreparation=async()=>{const error=new Error(message);error.code=code;throw error};
 const result=await h.ctx.runScheduledUpdate('slot','main');
 assert.equal(result.ok,false);assert.equal(h.calls.at(-1)[1],expected);
 assert.equal(h.state.autoSchedule.lastErrorCode,expected==='waiting'?'CRM_AUTH_REQUIRED':'UPDATE_FAILED');
 assert.equal(h.state.updateRuntime,undefined);assert.equal(h.active.size,0);
});
