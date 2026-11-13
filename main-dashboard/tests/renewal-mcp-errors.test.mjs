import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=fs.readFileSync(new URL('../sync-renewal-table.mjs',import.meta.url),'utf8');
const code=source.slice(source.indexOf('async function mcpCall('),source.indexOf('\nfunction findRows('));
function call(envelope){
 const context={AbortController,setTimeout,clearTimeout,readMcpCredentials:()=>({url:'https://fixture.invalid',token:''}),fetch:async()=>({ok:true,json:async()=>envelope})};
 vm.createContext(context);vm.runInContext('let renewalUseBrowserRelay=false;let renewalUseWindows=false;'+code,context);return context.mcpCall('update_range',{});
}
test('renewal writer rejects MCP tool errors even without success false',async()=>{
 await assert.rejects(call({result:{isError:true,content:[{type:'text',text:'merged range rejected'}]}}),/DINGTALK_TOOL_ERROR/);
 await assert.rejects(call({result:{content:[{type:'text',text:JSON.stringify({isError:true,errorMsg:'write rejected'})}]}}),/DINGTALK_TOOL_ERROR/);
});
test('renewal writer keeps legitimate nested business fields',async()=>{
 const result=await call({result:{content:[{type:'text',text:JSON.stringify({success:true,rows:[{success:false}]})}]}});
 assert.equal(result.success,true);assert.equal(result.rows[0].success,false);
});
