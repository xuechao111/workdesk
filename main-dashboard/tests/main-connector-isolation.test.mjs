import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read=f=>fs.readFileSync(new URL(`../${f}`,import.meta.url),'utf8');
const source=read('chrome-extension/background.js');
test('main manifest grants no replica host or content-script access',()=>{
 const m=JSON.parse(read('chrome-extension/manifest.json'));
 assert.ok(m.host_permissions.every(x=>!x.includes(':8766/')));
 assert.ok(m.content_scripts.every(s=>s.matches.every(x=>!x.includes(':8766/'))));
});
test('old replica alarm is cleared without any collection or relay request',async()=>{
 let listener;const cleared=[];
 const code=source.slice(source.indexOf('chrome.alarms.onAlarm.addListener('),source.indexOf('async function initializeMainConnector('));
 vm.runInNewContext(code,{chrome:{alarms:{onAlarm:{addListener:f=>listener=f},clear:async n=>cleared.push(n)}}});
 await listener({name:'codemao-test-update-half-hour'});
 assert.deepEqual(cleared,['codemao-test-update-half-hour']);
});
test('replica and forged sender messages cannot lease main relay or start collection',()=>{
 let listener;const calls=[];
 const context={chrome:{runtime:{id:'main-id',onMessage:{addListener:f=>listener=f}}},leaseMcpRelay:()=>calls.push('relay')};
 vm.runInNewContext(source.slice(source.indexOf('chrome.runtime.onMessage.addListener(')),context);
 for(const [base,sender] of [['http://127.0.0.1:8766',{}],['http://127.0.0.1:8765',{url:'http://127.0.0.1:8766/'}]]){
  let reply;listener({source:'codemao-dashboard',type:'ping',localBase:base},sender,r=>reply=r);
  assert.equal(reply.ok,false);
 }
 assert.equal(calls.length,0);
});
