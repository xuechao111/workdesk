import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

test('service refresh preserves local metrics without credentials or workbook access',()=>{
  const root=fs.mkdtempSync(path.join(path.dirname(fileURLToPath(import.meta.url)),'service-local-'));
  try{
    const input=path.join(root,'input.json'),output=path.join(root,'service-data.json');
    const source={updatedAt:'2026-11-06 14:00:00',dates:['2026-11-06'],teachers:[{老师:'甲',im:90,wecom:80,voiceDialCount:7,voiceConnectedCount:6}],groups:[{小组:'A',im:90,wecom:80}],today:{dates:['2026-11-06'],teachers:[{老师:'甲',im:90,voiceDialCount:7,voiceConnectedCount:6}],groups:[],status:'ready'}};
    fs.writeFileSync(input,JSON.stringify(source));
    // Deliberately invalid connection: the local path must never invoke it.
    fs.writeFileSync(path.join(root,'dashboard-config.json'),JSON.stringify({dingtalkConnectionUrl:'http://127.0.0.1:1/forbidden'}));
    const result=spawnSync(process.execPath,[fileURLToPath(new URL('../sync-service-data.mjs',import.meta.url)),input,output],{env:{...process.env,HF_DASHBOARD_ROOT:root},encoding:'utf8',timeout:5000});
    assert.equal(result.status,0,result.stderr);
    const actual=JSON.parse(fs.readFileSync(output,'utf8'));
    assert.equal(actual.outputMode,'local');
    assert.equal(actual.sheetId,undefined);
    assert.equal(actual.updatedAt,source.updatedAt);
    assert.equal(actual.teachers[0].voiceDialCount,7);
    assert.equal(actual.today.teachers[0].voiceConnectedCount,6);
    assert.equal(actual.groups[0].im,90);
    assert.match(result.stdout,/SERVICE_OK teachers=1 groups=1.*mode=local/);
    assert.equal(fs.existsSync(path.join(root,'run-data','mcp-relay')),false);
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});
