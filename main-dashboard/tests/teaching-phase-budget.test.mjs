import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../chrome-extension/background.js',import.meta.url),'utf8');
const fn=(name,next)=>source.slice(source.indexOf(`async function ${name}(`),source.indexOf(`async function ${next}(`));
const minute=60000,epoch=Date.parse('2026-11-12T16:00:00+08:00');
function harness({completeAfter=12*minute}={}){
  let now=epoch,relay=false,serviceCalls=0;
  const statuses=[],writes=[];
  const state={autoSchedule:{}};
  class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
  const ctx={LOCAL_BASE:'main',CRM_RUNTIME_TIMEOUT_MS:6*minute,activeUpdateRuns:new Set(),
    normalizeLocalBase:x=>x,instanceStorageKey:n=>n,Date:Clock,Set,
    chrome:{storage:{local:{get:async()=>({...state}),set:async values=>{writes.push(values);Object.assign(state,values);},remove:async key=>{delete state[key];}}}},
    fetchWithTimeout:async()=>{
      assert.equal(relay,true,'relay must remain active for every writer-status poll');
      return {ok:true,json:async()=>({state:now-epoch>=completeAfter?'success':'running',phase:'local',time:new Clock().toISOString(),message:'writer'})};
    },
    postLocalStatus:async(...args)=>statuses.push(args),appendRunLog:async()=>{},
    startMcpRelay:()=>{relay=true;return ()=>{relay=false;};},
    waitForLocalPreparation:async()=>({alreadyRunning:true}),
    runScheduledServiceUpdate:async()=>{serviceCalls++;},
    setTimeout:callback=>{now+=2500;callback();return 0;}};
  vm.createContext(ctx);
  vm.runInContext(source.match(/const LOCAL_RUNTIME_TIMEOUT_MS=.*;/)[0]+source.slice(source.indexOf('function isCrmAuthenticationFailure('),source.indexOf('async function fetchInCrm('))+fn('reconcileUpdateRuntime','waitForTabReady')+fn('waitForLocalCompletion','waitForLocalRunner')+fn('runScheduledUpdate','checkMissedSchedules'),ctx);
  return {ctx,state,statuses,writes,now:()=>now,advance:ms=>{now+=ms;},relay:()=>relay,serviceCalls:()=>serviceCalls};
}

test('a valid twelve-minute writer keeps its relay until completion and service starts afterwards',async()=>{
  const h=harness();
  assert.equal((await h.ctx.runScheduledUpdate('slot','main')).ok,true);
  assert.ok(h.now()-epoch>=12*minute);
  assert.equal(h.serviceCalls(),1);
  assert.equal(h.relay(),false);
  assert.equal(h.statuses.some(args=>args[0]==='error'),false);
  assert.ok(h.writes.some(values=>values.updateRuntime?.phase==='local'&&values.updateRuntime.phaseStartedAt===epoch));
});

test('a writer exceeding twenty-one minutes ends explicitly and releases the relay',async()=>{
  const h=harness({completeAfter:Infinity});
  const result=await h.ctx.runScheduledUpdate('slot','main');
  assert.equal(result.ok,false);
  assert.match(result.error,/21分钟/);
  assert.ok(h.now()-epoch>=21*minute);
  assert.equal(h.serviceCalls(),0);
  assert.equal(h.relay(),false);
  assert.equal(h.state.updateRuntime,undefined);
});

test('recovery measures the local phase independently of earlier CRM duration',async()=>{
  const h=harness();
  h.state.updateRuntime={runningSince:epoch-30*minute,slotKey:'slot',phase:'local',phaseStartedAt:epoch-12*minute};
  h.ctx.fetchWithTimeout=async()=>({ok:true,json:async()=>({state:'running',phase:'local',time:new Date(epoch-12*minute).toISOString()})});
  await h.ctx.reconcileUpdateRuntime('main');
  assert.ok(h.state.updateRuntime);
  assert.deepEqual(h.statuses,[]);
  h.advance(10*minute);
  await h.ctx.reconcileUpdateRuntime('main');
  assert.equal(h.state.updateRuntime,undefined);
  assert.match(h.statuses[0][2],/21分钟/);
});

test('older stored runtimes acquire a persistent local phase start from server progress',async()=>{
  const h=harness();
  h.state.updateRuntime={runningSince:epoch-40*minute,slotKey:'slot'};
  h.ctx.fetchWithTimeout=async()=>({ok:true,json:async()=>({state:'running',phase:'local',time:new Date(epoch-12*minute).toISOString()})});
  await h.ctx.reconcileUpdateRuntime('main');
  assert.equal(h.state.updateRuntime.phase,'local');
  assert.equal(h.state.updateRuntime.phaseStartedAt,epoch-12*minute);
  assert.deepEqual(h.statuses,[]);
});

test('service recovery keeps its full budget after a long local write and migrates legacy phase timing',async()=>{
  for(const legacy of [false,true]){
    const h=harness();
    h.state.updateRuntime={runningSince:epoch-35*minute,slotKey:'slot',...(legacy?{}:{phase:'service',phaseStartedAt:epoch-10*minute})};
    h.ctx.fetchWithTimeout=async()=>({ok:true,json:async()=>({state:'running',phase:'service',time:new Date(epoch-10*minute).toISOString()})});
    await h.ctx.reconcileUpdateRuntime('main');
    assert.equal(h.state.updateRuntime.phase,'service');
    assert.equal(h.state.updateRuntime.phaseStartedAt,epoch-10*minute);
    assert.deepEqual(h.statuses,[]);
    h.advance(23*minute);
    await h.ctx.reconcileUpdateRuntime('main');
    assert.equal(h.state.updateRuntime,undefined);
    assert.match(h.statuses[0][2],/32分钟/);
  }
});

test('joining an existing writer carries its run id into service and final status',async()=>{
  const h=harness({completeAfter:0});
  h.ctx.waitForLocalPreparation=async(...args)=>{
    assert.match(args[4],/^teaching-/);
    return {alreadyRunning:true,runId:'existing-writer'};
  };
  assert.equal((await h.ctx.runScheduledUpdate('slot','main')).ok,true);
  assert.equal(h.statuses.at(-1)[5],'existing-writer');
  assert.ok(h.statuses.every(args=>args[5]==='existing-writer'));
  assert.equal(h.state.updateRuntime,undefined);
});

test('an old scheduler finalizer cannot remove a later runtime',async()=>{
  const h=harness({completeAfter:0});
  h.ctx.runScheduledServiceUpdate=async()=>{h.state.updateRuntime={runId:'newer-run',runningSince:epoch+1};};
  await h.ctx.runScheduledUpdate('slot','main');
  assert.equal(h.state.updateRuntime.runId,'newer-run');
  assert.notEqual(h.statuses.at(-1)[5],'newer-run');
});

test('recovery never replaces a different run on the server and clears only its old runtime',async()=>{
  for(const replacedDuringRead of [false,true]){
    const h=harness();
    h.state.updateRuntime={runId:'old',runningSince:epoch-40*minute};
    h.ctx.fetchWithTimeout=async()=>{
      if(replacedDuringRead)h.state.updateRuntime={runId:'new',runningSince:epoch};
      return {ok:true,json:async()=>({state:'running',phase:'crm',runId:'new',time:new Date(epoch).toISOString()})};
    };
    await h.ctx.reconcileUpdateRuntime('main');
    assert.deepEqual(h.statuses,[]);
    assert.equal(h.state.updateRuntime?.runId,replacedDuringRead?'new':undefined);
  }
});

test('preparation, progress and chunk commit transmit the same optional run identity',async()=>{
  const bodies=[];
  const ctx={LOCAL_BASE:'main',normalizeLocalBase:x=>x,Date,setTimeout,clearTimeout,
    utf8Base64:value=>Buffer.from(value).toString('base64'),
    fetchWithTimeout:async(url,options)=>{
      bodies.push([url,JSON.parse(options.body)]);
      return {ok:true,json:async()=>({classes:[]})};
    }};
  vm.createContext(ctx);
  vm.runInContext(fn('waitForLocalPreparation','postLocalStatus')+fn('postLocalStatus','appendRunLog')+fn('uploadCrmData','postLocalJson'),ctx);
  await ctx.waitForLocalPreparation('slot',10000,'main','prepare-extension','run-123');
  await ctx.postLocalStatus('running','progress','','crm','main','run-123');
  await ctx.uploadCrmData('fresh data','main','run-123');
  assert.equal(bodies.length,4);
  assert.ok(bodies.every(([,payload])=>payload.runId==='run-123'));
  assert.match(bodies.at(-1)[0],/extension-data-commit$/);
});
