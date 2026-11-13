import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const text=fs.readFileSync(new URL('../sync-renewal-table.mjs',import.meta.url),'utf8');
const code=text.slice(text.indexOf('let renewalUseWindows='),text.indexOf('function findRows('));
function setup(fetch){
 const calls=[];
 const scope={AbortController,setTimeout,clearTimeout,TypeError,JSON,readMcpCredentials:()=>({url:'https://fixture.invalid',token:''}),fetch,
 mcpWindowsEnvelope:async(credentials,body)=>{calls.push(JSON.parse(body).params.name);return {result:{success:true}}}};
 vm.createContext(scope);vm.runInContext(code,scope);return {scope,calls};
}
test('initial read network failure selects main Windows transport for subsequent calls',async()=>{
 let count=0;const h=setup(async()=>{count++;throw new TypeError('fetch failed')});
 await h.scope.mcpCall('get_all_sheets',{});await h.scope.mcpCall('set_range_from_csv',{});
 assert.equal(count,1);assert.deepEqual(h.calls,['get_all_sheets','set_range_from_csv']);
});
test('ambiguous failed write never replays through relay',async()=>{
 const h=setup(async()=>{throw new TypeError('fetch failed')});
 await assert.rejects(h.scope.mcpCall('set_range_from_csv',{}),/fetch failed/);assert.equal(h.calls.length,0);
});
test('HTTP permission denial never switches transport',async()=>{
 const h=setup(async()=>({ok:false,status:403}));
 await assert.rejects(h.scope.mcpCall('get_all_sheets',{}),/HTTP_403/);assert.equal(h.calls.length,0);
});
