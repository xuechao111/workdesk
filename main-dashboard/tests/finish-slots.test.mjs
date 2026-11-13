import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const code=source.slice(source.indexOf('  function finishSlotBreakdown('),source.indexOf('  function openFinishSlots('));
const context={};vm.runInNewContext(code,context);
const row=(slot,done,expected,teacher='A',cohort='W1')=>({slot,teacher,cohort,current:{evenDone:done,evenExpected:expected,livePending:true}});

test('completion slots use weighted completion counts and isolate teacher and package/cohort',()=>{
  const slots=context.finishSlotBreakdown([row('周五晚',8,10),row('周五晚',1,5),row('周六午',4,8),row('周五晚',99,100,'B'),row('周五晚',99,100,'A','W2')],'A','W1');
  assert.deepEqual(Array.from(slots,s=>s.slot),['周五晚','周六午','周六晚']);
  assert.equal(slots[0].attend,9);assert.equal(slots[0].expected,15);
  assert.equal(slots[1].attend,4);assert.equal(slots[2].expected,0);
  assert.equal(slots.some(s=>s.unverified),false);
  assert.equal(slots.reduce((n,s)=>n+s.attend,0),13);
  assert.equal(slots.reduce((n,s)=>n+s.expected,0),23);
});
test('zero completion stays zero and missing completion only marks its slot unavailable',()=>{
  const slots=context.finishSlotBreakdown([row('周五晚',0,10),row('周六午',undefined,10)],'A','W1');
  assert.equal(slots[0].attend,0);assert.equal(slots[0].expected,10);assert.equal(slots[0].unverified,false);
  assert.equal(slots[1].unverified,true);assert.equal(slots[2].unverified,false);
});

test('completion detail dialog shows three slots, fractions, total and can close',()=>{
  let modal,handler,removed=false;
  const button={focus(){},onclick:null},previous={focus(){}};
  const ctx={...context,analysisData:{classes:[row('周五晚',1,2),row('周六午',0,3)]},pct:v=>(v*100).toFixed(1)+'%',esc:String,
    document:{activeElement:previous,createElement:()=>modal={querySelectorAll:()=>[button],querySelector:()=>button,remove:()=>removed=true},body:{appendChild(){}},addEventListener:(name,fn)=>handler=fn,removeEventListener(){}}};
  const start=source.indexOf('  function openFinishSlots(');
  vm.runInNewContext(source.slice(start,source.indexOf('  function showOverviewStudents(',start)),ctx);
  ctx.openFinishSlots('A','W1');
  for(const label of ['周五晚','周六午','周六晚','已完课人次','应完课人次','合计','50.0%','20.0%'])assert.ok(modal.innerHTML.includes(label),label);
  assert.ok(!modal.innerHTML.includes('缺直播房间记录'));
  handler({key:'Escape'});assert.equal(removed,true);
});
