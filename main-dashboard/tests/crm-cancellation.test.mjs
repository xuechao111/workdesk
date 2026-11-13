import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../chrome-extension/background.js',import.meta.url),'utf8');
const collect=source.slice(source.indexOf('async function collectCrmData('),source.indexOf('async function fetchComparisonLiveRooms('));

test('a failed class aborts and drains sibling workers before reporting failure',async()=>{
  const requested=[],aborted=[],progress=[];
  const response=(data,status=200)=>({status,ok:status===200,arrayBuffer:async()=>new TextEncoder().encode(JSON.stringify(data)).buffer});
  const context={Date,AbortController,TextDecoder,URL,setTimeout,clearTimeout,
    fetch:async(url,options)=>{
      const id=Number(new URL(url).searchParams.get('classId'));
      requested.push(id);
      if(id===1)return response({},403);
      return new Promise((resolve,reject)=>{
        options.signal.addEventListener('abort',()=>{aborted.push(id);reject(new Error('aborted'));},{once:true});
      });
    }};
  vm.createContext(context);vm.runInContext(collect,context);
  await assert.rejects(context.collectCrmData([[1,1],[2,2],[3,3],[4,4],[5,5]],[],async(...args)=>progress.push(args)),/CRM_HTTP_403/);
  assert.deepEqual(requested,[1,2,3,4]);
  assert.deepEqual(aborted,[2,3,4]);
  assert.deepEqual(progress,[]);
});

test('an outer collection timeout prevents late CRM progress from overwriting terminal status',async()=>{
  let progressCallback;
  const statuses=[];
  const context={LOCAL_BASE:'http://127.0.0.1:8765',normalizeLocalBase:x=>x,
    collectCrmData:async(classes,excluded,onProgress)=>{progressCallback=onProgress;return new Promise(()=>{});},
    fetchComparisonLiveRooms:()=>{},postLocalStatus:async(...args)=>statuses.push(args),appendRunLog:async()=>{},
    setTimeout:callback=>{queueMicrotask(callback);return 0;},Date};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function isCrmAuthenticationFailure('),source.indexOf('const RENEWAL_COLUMN_NAMES')),context);
  const result=await context.fetchInCrm([[1,1]]);
  assert.equal(result.ok,false);
  await progressCallback('late progress','old collection');
  assert.deepEqual(statuses,[]);
});
