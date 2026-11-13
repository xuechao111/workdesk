import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {randomUUID} from "node:crypto";
import {spawn} from "node:child_process";

function isolatedRuntimeRoot(source, fallback, expectedPort){
  if(String(process.env.HF_DASHBOARD_PORT||expectedPort)!==String(expectedPort))throw new Error("INSTANCE_PORT_MISMATCH");
  const base=fs.realpathSync(source),candidate=path.resolve(process.env.HF_DASHBOARD_ROOT||fallback);
  const relative=path.relative(base,candidate);
  if(relative===".."||relative.startsWith(".."+path.sep)||path.isAbsolute(relative))throw new Error("INSTANCE_ROOT_MISMATCH");
  let current=candidate;
  while(true){
    if(fs.existsSync(current)&&fs.lstatSync(current).isSymbolicLink())throw new Error("INSTANCE_ROOT_REPARSE_POINT");
    const parent=path.dirname(current);if(parent===current)break;current=parent;
  }
  return candidate;
}


const RUNTIME_ROOT=isolatedRuntimeRoot(path.dirname(fileURLToPath(import.meta.url)),path.dirname(fileURLToPath(import.meta.url)),8765);
const DASHBOARD_CONFIG=path.join(RUNTIME_ROOT,"dashboard-config.json");
const DASHBOARD_SETTINGS=(()=>{try{return JSON.parse(fs.readFileSync(DASHBOARD_CONFIG,"utf8"))}catch{return {}}})();
const WORKBOOK = normalizeWorkbookUrl(DASHBOARD_SETTINGS.renewalWorkbookUrl || "");
const CONFIGURED_SHEET_ID = DASHBOARD_SETTINGS.renewalSheetId || "";
const TARGET_SHEET_NAME = "\u5956\u5b66\u91d1\u660e\u7ec6";
const TARGET_END_COLUMN = "AM";
const EXPECTED_COLUMN_COUNT = 39;
const FILTERS = {"续费月份":"","续费节点":"首续","战队":"深圳战区"};
const REQUIRED_COLUMNS = ["续费月份","用户ID","用户姓名","战区","战队","续费节点"];
const CREDENTIAL_FILES = [
  process.env.CODEMAO_SCHOLARSHIP_CREDENTIALS_FILE,
  "C:/Users/user/Desktop/Documents/编程猫管理skill/codemao-student-profile-extracted/codemao-course-data/sync.py",
].filter(Boolean);

function normalizeText(value) {
  return String(value ?? "").replace(/\s+/g," ").trim();
}

function normalizeSourceHeaders(source) {
  if (!Array.isArray(source.headers) || !Array.isArray(source.rows)) throw new Error("CRM_INPUT_INVALID");
  source.headers=source.headers.map(normalizeText);
  const duplicates=source.headers.filter((header,index,headers)=>headers.indexOf(header)!==index);
  if (!source.headers.length || source.headers.some(header=>!header) || duplicates.length) {
    throw new Error(`CRM_HEADERS_INVALID:空表头或重复列:${[...new Set(duplicates)].join("|")}`);
  }
  // Source schemas can grow independently of the authorized workbook. The
  // target's existing header names remain authoritative for writing columns.
  return source;
}

function projectTargetRows(source,targetHeaders) {
  const missing=targetHeaders.filter(header=>!source.headers.includes(header));
  if (missing.length) throw new Error(`CRM_MISSING_TARGET_COLUMNS:${missing.join("|")}`);
  return source.rows.map(row=>Object.fromEntries(targetHeaders.map(header=>[header,row[header] ?? ""])));
}

function normalizeWorkbookUrl(value) {
  const text=String(value||"").trim();
  const link=text.match(/https:\/\/alidocs\.dingtalk\.com\/i\/nodes\/[A-Za-z0-9]+/);
  return link?.[0] || "";
}

function selectDetailSheet(sheets, configuredId) {
  const candidates=sheets.filter(sheet=>normalizeText(sheet?.name)===TARGET_SHEET_NAME);
  const configured=candidates.find(sheet=>sheet.sheetId===configuredId);
  if(candidates.length>1&&!configured)throw new Error("DINGTALK_RENEWAL_DETAIL_SHEET_AMBIGUOUS");
  const target=configured||candidates[0];
  if(!target)throw new Error(`DINGTALK_RENEWAL_DETAIL_SHEET_NOT_FOUND:${TARGET_SHEET_NAME}`);
  return target.sheetId||target.name;
}

function normalizeDate(value) {
  if (typeof value === "number" || /^\d{10,13}$/.test(String(value ?? "").trim())) {
    const number = Number(value), milliseconds = number < 100000000000 ? number * 1000 : number;
    const date = new Date(milliseconds);
    if (!Number.isNaN(date.getTime())) return date.toISOString().slice(0,10);
  }
  const text = normalizeText(value).replace(/\//g,"-");
  const match = text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  return match ? `${match[1]}-${match[2].padStart(2,"0")}-${match[3].padStart(2,"0")}` : text;
}

function csvEscape(value) {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g,'""')}"` : text;
}

function matrixToCsv(matrix) {
  return matrix.map(row => row.map(csvEscape).join(",")).join("\r\n");
}

function validateSource(headers,rows) {
  const missing = REQUIRED_COLUMNS.filter(column => !headers.includes(column));
  if (missing.length) throw new Error(`CRM_MISSING_REQUIRED_COLUMNS:${missing.join("|")}`);
  if (!rows.length) throw new Error("CRM_SOURCE_EMPTY");
  for (const row of rows) {
    if (normalizeDate(row["续费月份"]) !== FILTERS["续费月份"]) throw new Error(`CRM_FILTER_MISMATCH:续费月份:${row["续费月份"]}`);
    if (normalizeText(row["续费节点"]) !== FILTERS["续费节点"]) throw new Error(`CRM_FILTER_MISMATCH:续费节点:${row["续费节点"]}`);
    if (normalizeText(row["战队"]) !== FILTERS["战队"]) throw new Error(`CRM_FILTER_MISMATCH:战队:${row["战队"]}`);
    if (!normalizeText(row["用户ID"])) throw new Error("CRM_USER_ID_EMPTY");
  }
  const fingerprints = rows.map(row => JSON.stringify(headers.map(header => row[header] ?? "")));
  if (new Set(fingerprints).size !== fingerprints.length) throw new Error("CRM_EXACT_ROW_DUPLICATED");
}

function readMcpCredentials() {
  if (DASHBOARD_SETTINGS.dingtalkConnectionUrl) {
    return {url:DASHBOARD_SETTINGS.dingtalkConnectionUrl,token:DASHBOARD_SETTINGS.dingtalkAccessKey || ""};
  }
  const file = CREDENTIAL_FILES.find(candidate => fs.existsSync(candidate));
  if (!file) throw new Error("DINGTALK_MCP_CONFIG_NOT_FOUND");
  const text = fs.readFileSync(file,"utf8");
  const url = text.match(/MCP_URL\s*=\s*["']([^"']+)["']/)?.[1];
  const token = text.match(/ACCESS_TOKEN\s*=\s*["']([^"']+)["']/)?.[1];
  if (!url) throw new Error("DINGTALK_MCP_CONFIG_INVALID");
  return {url,token:token || ""};
}

async function mcpRelayEnvelope(credentials,body,timeoutMs) {
  // Never infer the main instance from a missing environment variable.
  const port=String(process.env.HF_DASHBOARD_PORT||"8765");
  if(port!=="8765")throw new Error("DINGTALK_RELAY_INSTANCE_MISMATCH");
  if(!/^876[56]$/.test(port))throw new Error("DINGTALK_RELAY_INSTANCE_PORT_INVALID");
  const controller=new AbortController();
  const healthTimer=setTimeout(()=>controller.abort(),4000);
  try {
    const response=await fetch(`http://127.0.0.1:${port}/health`,{cache:"no-store",signal:controller.signal});
    if(!response.ok)throw new Error("DINGTALK_RELAY_INSTANCE_UNAVAILABLE");
    const health=await response.json();
    if(!health.ok||health.instance!=="main"||Number(health.port)!==8765||path.resolve(String(health.runtimeRoot||"" )).toLowerCase()!==RUNTIME_ROOT.toLowerCase())throw new Error("DINGTALK_RELAY_INSTANCE_MISMATCH");
  } finally {clearTimeout(healthTimer);}
  const directory=path.join(RUNTIME_ROOT,"run-data","mcp-relay");
  fs.mkdirSync(directory,{recursive:true});
  const id=randomUUID().replaceAll("-","");
  const base=path.join(directory,id),requestFile=base+".request.json",responseFile=base+".response.json",temporary=base+".request.tmp";
  try {
    fs.writeFileSync(temporary,JSON.stringify({id,url:credentials.url,token:credentials.token||"",bodyBase64:Buffer.from(body,"utf8").toString("base64"),timeoutMs,createdAt:new Date().toISOString()}),{encoding:"utf8",mode:0o600});
    fs.renameSync(temporary,requestFile);
    const deadline=Date.now()+timeoutMs+45000;
    while(Date.now()<deadline){
      if(fs.existsSync(responseFile)){
        const response=JSON.parse(fs.readFileSync(responseFile,"utf8").replace(/^\uFEFF/,""));
        if(response.id!==id)throw new Error("DINGTALK_RELAY_RESPONSE_MISMATCH");
        if(!response.ok)throw new Error(`DINGTALK_RELAY_FAILED:${Number(response.status)||"network"}`);
        return JSON.parse(String(response.bodyText||""));
      }
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    throw new Error("DINGTALK_RELAY_TIMEOUT:请确认当前工作台连接器保持启用");
  } finally {
    for(const suffix of [".request.tmp",".request.json",".response.json",".claimed"]){try{fs.rmSync(base+suffix,{force:true});}catch{}}
  }
}

async function mcpWindowsEnvelope(credentials,body,timeoutMs){
  const script=`$ErrorActionPreference='Stop';[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;$h=@{'Content-Type'='application/json';'Accept'='application/json'};if($env:HF_RENEWAL_TOKEN){$h.Authorization='Bearer '+$env:HF_RENEWAL_TOKEN};$body=[Console]::In.ReadToEnd();$r=Invoke-RestMethod -Method Post -Uri $env:HF_RENEWAL_URL -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec ([int]$env:HF_RENEWAL_TIMEOUT);$r|ConvertTo-Json -Depth 100 -Compress`;
  return new Promise((resolve,reject)=>{
    const child=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-Command',script],{windowsHide:true,env:{...process.env,HF_RENEWAL_URL:credentials.url,HF_RENEWAL_TOKEN:credentials.token||'',HF_RENEWAL_TIMEOUT:String(Math.ceil(timeoutMs/1000))}});
    const out=[];child.stdout.on('data',data=>out.push(data));
    const timer=setTimeout(()=>{child.kill();reject(new Error('DINGTALK_WINDOWS_TIMEOUT'));},timeoutMs+10000);
    child.on('error',()=>{clearTimeout(timer);reject(new Error('DINGTALK_WINDOWS_UNAVAILABLE'));});
    child.on('close',code=>{clearTimeout(timer);if(code!==0){reject(new Error('DINGTALK_WINDOWS_NETWORK_FAILED'));return;}try{resolve(JSON.parse(Buffer.concat(out).toString('utf8').replace(/^\uFEFF/,'')));}catch{reject(new Error('DINGTALK_WINDOWS_RESPONSE_INVALID'));}});
    child.stdin.on('error',()=>{});child.stdin.end(body);
  });
}
let renewalUseWindows=false;
let renewalUseBrowserRelay=false;

async function mcpCall(name,args,timeoutMs=180000) {
  const {url,token} = readMcpCredentials();
  const controller = new AbortController();
  const readOperation=["get_all_sheets","get_sheet","get_range"].includes(name);
  const timer = setTimeout(() => controller.abort(),readOperation&&!renewalUseBrowserRelay?Math.min(timeoutMs,12000):timeoutMs);
  try {
    const headers = {"content-type":"application/json","accept":"application/json"};
    if (token) headers.authorization = `Bearer ${token}`;
    const body=JSON.stringify({jsonrpc:"2.0",method:"tools/call",params:{name,arguments:args},id:1});
    let envelope;
    if(renewalUseWindows){
      envelope=await mcpWindowsEnvelope({url,token},body,timeoutMs);
    }else if(renewalUseBrowserRelay){
      envelope=await mcpRelayEnvelope({url,token},body,timeoutMs);
    }else{
      let response;
      try{response=await fetch(url,{method:"POST",headers,body,signal:controller.signal});}
      catch(error){
        // Only a read may select the alternate transport. A failed write is
        // never replayed, because it could already have reached the server.
        if(!readOperation||(!(error instanceof TypeError)&&!["AbortError","TimeoutError"].includes(error?.name)))throw error;
        clearTimeout(timer);
        envelope=await mcpWindowsEnvelope({url,token},body,timeoutMs);
        renewalUseWindows=true;
      }
      if(response){
        if (!response.ok) throw new Error(`DINGTALK_MCP_HTTP_${response.status}`);
        envelope=await response.json();
      }
    }
    if (envelope.error) throw new Error(`DINGTALK_MCP_ERROR:${JSON.stringify(envelope.error)}`);
    if (envelope.result?.isError === true) throw new Error(`DINGTALK_TOOL_ERROR:${name}:${envelope.result?.content?.find(item=>item.type==='text')?.text||'MCP tool failed'}`);
    const text = envelope.result?.content?.find(item => item.type === "text")?.text;
    const result = text ? JSON.parse(text) : envelope.result;
    if (result?.success === false || result?.isError === true) {
      if (result.errorCode === "forbidden.accessDenied" || /access denied/i.test(result.errorMsg || "")) throw new Error(`DINGTALK_ACCESS_DENIED:${name}`);
      throw new Error(`DINGTALK_TOOL_ERROR:${result.errorMsg || JSON.stringify(result)}`);
    }
    return result;
  } finally { clearTimeout(timer); }
}

function findRows(value) {
  if (Array.isArray(value) && (!value.length || Array.isArray(value[0]))) return value;
  if (!value || typeof value !== "object") return null;
  for (const key of ["values","data","rows","displayValues"]) if (Array.isArray(value[key]) && (!value[key].length || Array.isArray(value[key][0]))) return value[key];
  for (const child of Object.values(value)) { const rows=findRows(child); if (rows) return rows; }
  return null;
}

async function writeAndVerify(source) {
  const sheetId = await resolveTargetSheetId();
  const headerResult = await mcpCall("get_range",{nodeId:WORKBOOK,sheetId,range:`A1:${TARGET_END_COLUMN}1`});
  let targetHeaders = (findRows(headerResult)?.[0] || []).map(normalizeText);
  if (!targetHeaders.some(Boolean)) {
    const info=await mcpCall("get_sheet",{nodeId:WORKBOOK,sheetId});
    if (info.nonEmptyRange || Number(info.lastNonEmptyRow)>=0) throw new Error("DINGTALK_HEADER_EMPTY_WITH_EXISTING_DATA");
    // Preserve the established 39-column layout on a genuinely empty sheet.
    // This newly introduced CRM field has no column in that layout.
    targetHeaders=source.headers.filter(header=>header!=="is_page_get_coupon");
  }
  if (targetHeaders.length !== EXPECTED_COLUMN_COUNT || targetHeaders.some(header => !header)) throw new Error(`DINGTALK_HEADER_INVALID:${targetHeaders.length}`);
  if (new Set(targetHeaders).size!==targetHeaders.length) throw new Error("DINGTALK_HEADER_DUPLICATED");
  const tableRows = projectTargetRows(source,targetHeaders);
  validateSource(targetHeaders,tableRows);
  const infoBefore = await mcpCall("get_sheet",{nodeId:WORKBOOK,sheetId});
  const previousLastRow = Number(infoBefore.nonEmptyRange?.lastRow || (Number(infoBefore.lastNonEmptyRow)+1) || 1);
  const matrix = [targetHeaders,...tableRows.map(row => targetHeaders.map(header => row[header] ?? ""))];
  for (let start=0;start<matrix.length;start+=600) {
    const chunk=matrix.slice(start,start+600);
    await mcpCall("set_range_from_csv",{nodeId:WORKBOOK,sheetId,startCell:`A${start+1}`,csv:matrixToCsv(chunk),allowOverwrite:true});
  }
  const newLastRow=tableRows.length+1;
  if (previousLastRow>newLastRow) await mcpCall("clear_range",{nodeId:WORKBOOK,sheetId,range:`A${newLastRow+1}:${TARGET_END_COLUMN}${previousLastRow}`,type:"content"});
  const infoAfter=await mcpCall("get_sheet",{nodeId:WORKBOOK,sheetId});
  const verify=await Promise.all([
    mcpCall("get_range",{nodeId:WORKBOOK,sheetId,range:`A1:${TARGET_END_COLUMN}2`}),
    mcpCall("get_range",{nodeId:WORKBOOK,sheetId,range:`A${newLastRow}:${TARGET_END_COLUMN}${newLastRow}`}),
  ]);
  const top=findRows(verify[0])||[],bottom=findRows(verify[1])||[];
  if (JSON.stringify((top[0]||[]).map(normalizeText))!==JSON.stringify(targetHeaders)) throw new Error("VERIFY_HEADER_MISMATCH");
  const idIndex=targetHeaders.indexOf("用户ID");
  if (normalizeText(top[1]?.[idIndex])!==normalizeText(tableRows[0]["用户ID"])) throw new Error("VERIFY_FIRST_USER_MISMATCH");
  if (normalizeText(bottom[0]?.[idIndex])!==normalizeText(tableRows.at(-1)["用户ID"])) throw new Error("VERIFY_LAST_USER_MISMATCH");
  const actualLast=Number(infoAfter.nonEmptyRange?.lastRow || (Number(infoAfter.lastNonEmptyRow)+1) || 0);
  if (actualLast!==newLastRow) throw new Error(`VERIFY_ROW_COUNT_MISMATCH:${actualLast}/${newLastRow}`);
  return {rows:tableRows.length,lastRow:actualLast};
}

async function resolveTargetSheetId() {
  const listing=await mcpCall("get_all_sheets",{nodeId:WORKBOOK});
  const sheets=Array.isArray(listing)?listing:(listing?.sheets||listing?.data?.sheets||[]);
  return selectDetailSheet(sheets,CONFIGURED_SHEET_ID);
}

async function resolveDashboardSheetId() {
  const listing=await mcpCall("get_all_sheets",{nodeId:WORKBOOK});
  const sheets=Array.isArray(listing)?listing:(listing?.sheets||listing?.data?.sheets||[]);
  const dashboard=sheets.find(sheet=>normalizeText(sheet?.name)==="续费看板");
  if (!dashboard) return null;
  return dashboard.sheetId||dashboard.name;
}

async function updateDashboardTimestamp(sheetId, existingTimestamp=null) {
  sheetId ||= await resolveDashboardSheetId();
  if (!sheetId) throw new Error("DINGTALK_RENEWAL_DASHBOARD_NOT_FOUND");
  const timestamp=existingTimestamp||new Date().toLocaleString("sv-SE",{timeZone:"Asia/Shanghai",hour12:false});
  const value=`最新更新时间：${timestamp}`;
  const mergedRange="A1:H1";
  await mcpCall("unmerge_range",{nodeId:WORKBOOK,sheetId,rangeAddress:mergedRange});
  let writeError=null;
  try {
    await mcpCall("set_cell_range",{nodeId:WORKBOOK,sheetId,rangeAddress:"A1",cells:[[{type:"text",text:value}]]});
  } catch (error) {
    writeError=error;
  } finally {
    await mcpCall("merge_cells",{nodeId:WORKBOOK,sheetId,rangeAddress:mergedRange,mergeType:"mergeAll"});
  }
  if (writeError) throw writeError;
  const repeat=value=>[Array(8).fill(value)];
  await mcpCall("update_range",{nodeId:WORKBOOK,sheetId,rangeAddress:mergedRange,fontColors:repeat("#19334D"),fontWeights:repeat("bold"),fontSizes:repeat(14),horizontalAlignments:repeat("center"),verticalAlignments:repeat("middle"),wordWrap:"autoWrap"});
  const verification=await mcpCall("get_range",{nodeId:WORKBOOK,sheetId,range:"A1"});
  const actual=normalizeText(findRows(verification)?.[0]?.[0]);
  if (actual!==value) throw new Error(`VERIFY_DASHBOARD_TIMESTAMP_MISMATCH:${actual}`);
  return timestamp;
}

async function main() {
  if (!WORKBOOK) throw new Error("请先在工作台配置面板填写续费数据钉钉文档链接");
  const inputFile=process.argv[2];
  if (!inputFile || !fs.existsSync(inputFile)) throw new Error("CRM_INPUT_FILE_NOT_FOUND");
  const source=JSON.parse(fs.readFileSync(inputFile,"utf8").replace(/^\uFEFF/,""));
  if (!Array.isArray(source.headers) || !Array.isArray(source.rows)) throw new Error("CRM_INPUT_INVALID");
  const selectedMonth=String(source.renewalMonth||"");
  if (!/^\d{4}-(0[1-9]|1[0-2])-01$/.test(selectedMonth)) throw new Error("CRM_RENEWAL_MONTH_INVALID");
  FILTERS["续费月份"]=selectedMonth;
  normalizeSourceHeaders(source);
  if(source.rowcount!=null && Number(source.rowcount)!==source.rows.length)throw new Error("CRM_ROW_COUNT_MISMATCH");
  validateSource(source.headers,source.rows);
  console.log(`CRM_OK rows=${source.rows.length} columns=${source.headers.length}`);
  const dashboardSheetId=await resolveDashboardSheetId();
  const verification=await writeAndVerify(source);
  const dashboardTimestamp=dashboardSheetId?await updateDashboardTimestamp(dashboardSheetId):new Date().toLocaleString("sv-SE",{timeZone:"Asia/Shanghai",hour12:false});
  console.log(`SYNC_OK rows=${verification.rows} lastRow=${verification.lastRow}`);
  console.log(`${dashboardSheetId?"DASHBOARD_TIMESTAMP_OK":"LOCAL_TIMESTAMP_OK"} time=${dashboardTimestamp}`);
}

function selfTest(){
  const assert=(ok)=>{if(!ok)throw new Error("SELF_TEST_FAILED")};
  const rejects=fn=>{try{fn()}catch{return}throw new Error("SELF_TEST_EXPECTED_REJECTION")};
  assert(normalizeWorkbookUrl("[表格](https://alidocs.dingtalk.com/i/nodes/abc123?x=1)")==="https://alidocs.dingtalk.com/i/nodes/abc123");
  assert(!normalizeWorkbookUrl("https://example.com/i/nodes/abc"));
  assert(selectDetailSheet([{sheetId:"old",name:"其他表"},{sheetId:"new",name:TARGET_SHEET_NAME}],"old")==="new");
  rejects(()=>selectDetailSheet([{sheetId:"old",name:"其他表"}],"old"));
  rejects(()=>selectDetailSheet([{sheetId:"a",name:TARGET_SHEET_NAME},{sheetId:"b",name:TARGET_SHEET_NAME}],"old"));
  for(const month of ["2026-12-01","2027-01-01","2028-02-01"]){
    FILTERS["续费月份"]=month;
    const row={"续费月份":month,"用户ID":"test","用户姓名":"test","战区":"test","战队":"深圳战区","续费节点":"首续"};
    validateSource(REQUIRED_COLUMNS,[row]);
    rejects(()=>validateSource(REQUIRED_COLUMNS,[{...row,"续费月份":"2026-08-01"}]));
    rejects(()=>validateSource(REQUIRED_COLUMNS,[row,row]));
  }
  console.log("SELF_TEST_OK: workbook links, target isolation, month switching, wrong-month and duplicate guards");
}

const task=process.argv.includes("--self-test") ? Promise.resolve().then(selfTest) : process.argv.includes("--timestamp-only")
  ? updateDashboardTimestamp().then(timestamp=>console.log(`DASHBOARD_TIMESTAMP_OK time=${timestamp}`))
  : main();
task.catch(error=>{
  console.error(String(error?.message||error));
  process.exitCode=1;
});
