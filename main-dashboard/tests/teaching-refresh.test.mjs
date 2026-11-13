import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const start=source.indexOf('function shouldRefreshTeachingData(');
const end=source.indexOf('async function refreshStatus()',start);
const context=vm.createContext({});
vm.runInContext(source.slice(start,end),context);
const refresh=context.shouldRefreshTeachingData;

test('a completed refresh missed while backgrounded is detected even when another run started',()=>{
  assert.equal(refresh({state:'running',lastSuccessTime:'19:00'}, {state:'running',lastSuccessTime:'19:30'}),true);
  assert.equal(refresh({state:'success',lastSuccessTime:'19:00'}, {state:'success',lastSuccessTime:'19:30'}),true);
});
test('unchanged status does not repeatedly reload the board',()=>{
  assert.equal(refresh({state:'running',lastSuccessTime:'19:00'}, {state:'running',lastSuccessTime:'19:00'}),false);
  assert.equal(refresh(null,{state:'success',lastSuccessTime:'19:30'}),false);
});
test('success transitions remain supported without a timestamp',()=>{
  assert.equal(refresh({state:'running'},{state:'success'}),true);
  assert.equal(refresh({state:'error'},{state:'waiting'}),false);
});

function snapshotRuntime(){
  let requests=0,renders=0,fail=false;
  let response={updatedAt:'2026-10-31 20:00:00',serviceUpdatedAt:'S1',rows:[],classes:[],cohorts:[],summary:{},weeks:{}};
  const ctx=vm.createContext({state:{name:'__team'},document:{hidden:false},analysisData:{updatedAt:'2026-10-31 19:00:00',serviceUpdatedAt:'S1',rows:[]},json:async()=>{requests++;if(fail)throw new Error('offline');return response},renderTeamBoard:()=>renders++,renderOverview:()=>renders++,renderAnalysis:()=>renders++});
  const begin=source.indexOf('  let teachingSnapshotCheckRunning=');
  vm.runInContext(source.slice(begin,source.indexOf('  setInterval(reconcileTeachingSnapshot',begin)),ctx);
  return {ctx,check:()=>ctx.reconcileTeachingSnapshot(),counts:()=>({requests,renders}),fail:value=>fail=value,response:value=>response=value};
}
test('visible board recovers a missed snapshot independently of status transitions',async()=>{
  const r=snapshotRuntime();await r.check();assert.equal(r.counts().renders,1);
  await r.check();assert.equal(r.counts().renders,1);
  r.response({updatedAt:'2026-10-31 18:00:00',rows:[]});await r.check();assert.equal(r.counts().renders,1);
});
test('temporary failure preserves data and retries successfully without a new status',async()=>{
  const r=snapshotRuntime();r.fail(true);await r.check();assert.equal(r.counts().renders,0);
  r.fail(false);await r.check();assert.equal(r.counts().renders,1);
});
test('hidden pages and unrelated tabs do not fetch snapshots',async()=>{
  const r=snapshotRuntime();r.ctx.document.hidden=true;await r.check();
  r.ctx.document.hidden=false;r.ctx.state.name='other';await r.check();assert.equal(r.counts().requests,0);
});
test('simultaneous checks share a single request and malformed data cannot replace the board',async()=>{
  const r=snapshotRuntime();r.response({updatedAt:'2026-10-31 20:00:00'});
  await Promise.all([r.check(),r.check()]);assert.deepEqual(r.counts(),{requests:1,renders:0});
});

test('a failed first load can recover without reloading the browser',async()=>{
  const r=snapshotRuntime();r.ctx.analysisData=null;await r.check();assert.equal(r.counts().renders,1);
});
