import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../chrome-extension/background.js',import.meta.url),'utf8');
const normalizers=source.slice(source.indexOf('function normalizeLocalBase('),source.indexOf('async function injectDashboardBridge('));
const leases=source.slice(source.indexOf('const mcpRelayLeases='),source.indexOf('async function reconcileUpdateRuntime('));
const messages=source.slice(source.indexOf('chrome.runtime.onMessage.addListener('));
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness(){
  let now=0,nextId=1,listener;
  const timers=new Map(),started=[],stopped=[],calls=[];
  const context={LOCAL_BASE:'http://127.0.0.1:8765',Map,Date,
    setTimeout:(fn,ms)=>{const id=nextId++;timers.set(id,{fn,at:now+ms});return id;},
    clearTimeout:id=>timers.delete(id),
    startMcpRelay:base=>{started.push(base);return ()=>stopped.push(base);},
    reconcileUpdateRuntime:async base=>calls.push(['schedule',base]),
    fetchRenewalInCurrentChrome:async()=>({ok:true,data:'renewal'}),
    fetchNctInCurrentChrome:async()=>({ok:true,data:'nct'}),
    fetchServiceInCurrentChrome:async()=>({ok:true,data:'service'}),
    fetchInCrm:async()=>({ok:true,data:'teaching'}),
    chrome:{runtime:{onMessage:{addListener:fn=>listener=fn},getManifest:()=>({version:'test'})},
      storage:{local:{get:async()=>({})}}},
  };
  vm.createContext(context);vm.runInContext(normalizers+leases+messages,context);
  const advance=ms=>{now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}};
  const send=async(type,base='http://127.0.0.1:8765')=>{
    const replies=[];listener({source:'codemao-dashboard',type,localBase:base}, {},reply=>replies.push(reply));
    await flush();return replies;
  };
  return {context,advance,send,started,stopped,calls};
}

test('a dashboard open longer than twelve minutes keeps a single relay alive through schedule polling',async()=>{
  const h=harness();await h.send('ping');
  for(let minute=0;minute<14;minute++){h.advance(60000);await h.send('get-schedule');}
  assert.equal(h.started.length,1);assert.equal(h.stopped.length,0);
  h.advance(12*60000);assert.equal(h.stopped.length,1);
});

test('manual renewal, service and annual-card updates reject replica traffic',async()=>{
  for(const type of ['fetch-renewal','fetch-service','fetch-nct']){
    const h=harness();const replies=await h.send(type,'http://127.0.0.1:8766');
    assert.deepEqual(h.started,[],type);
    assert.equal(replies[0].ok,false,type);
  }
});

test('main schedule heartbeat does not extend a replica relay lease',async()=>{
  const h=harness();await h.send('ping','http://127.0.0.1:8766');
  for(let minute=0;minute<13;minute++){h.advance(60000);await h.send('get-schedule');}
  assert.deepEqual(h.stopped,[]);
  assert.equal(h.started.filter(base=>base.endsWith(':8765')).length,1);
});

test('a rejected browser tab lookup replies immediately rather than leaving renewal waiting until timeout',async()=>{
  const h=harness();
  const renewal=source.slice(source.indexOf('async function fetchRenewalInCurrentChrome('),source.indexOf('async function fetchNctInCurrentChrome('));
  h.context.chrome.tabs={query:async()=>{throw new Error('browser tab lookup failed');}};
  vm.runInContext(renewal,h.context);
  const replies=[];
  // The real function rejects before its internal try block; its message
  // boundary must still convert that rejection into an actionable response.
  h.context.fetchRenewalInCurrentChrome=h.context.fetchRenewalInCurrentChrome.bind(h.context,'2026-12-01');
  const result=await h.send('fetch-renewal');replies.push(...result);
  assert.equal(replies.length,1);assert.equal(replies[0].ok,false);
  assert.match(replies[0].error,/browser tab lookup failed/);
});

test('rejected manual collectors all receive an explicit error response',async()=>{
  for(const [type,name] of [['fetch-crm','fetchInCrm'],['fetch-nct','fetchNctInCurrentChrome'],['fetch-service','fetchServiceInCurrentChrome']]){
    const h=harness();h.context[name]=async()=>{throw new Error('unexpected browser failure');};
    const replies=await h.send(type);assert.equal(replies.length,1);assert.equal(replies[0].ok,false);assert.match(replies[0].error,/unexpected browser failure/);
  }
});
