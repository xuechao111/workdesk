$ErrorActionPreference='Stop'
$dashboard=Split-Path -Parent $PSScriptRoot
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $dashboard 'bridge.ps1'),[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Bridge syntax invalid'}
foreach($name in @('Write-ScholarshipStatusObject','Read-ScholarshipStatusObject','Repair-ScholarshipStatus','Test-ScholarshipUpdateLocked','Test-TaskUpdateLocked','Invoke-ScholarshipExtensionUpdate','Write-NctStatusObject','Read-NctStatusObject','Repair-NctStatus','Repair-ServiceStatus','Invoke-ServiceExtensionUpdate','Invoke-NctExtensionUpdate')){
 $fn=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 Invoke-Expression $fn.Extent.Text
}
function Assert($ok,$message){if(-not$ok){throw $message};Write-Output "PASS $message"}
$root=Join-Path $PSScriptRoot ('scholarship-lifecycle-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
$scholarshipStatusFile=Join-Path $root 'scholarship-status.json'
$scholarshipRunner=Join-Path $root 'fake-runner.ps1'
[IO.File]::WriteAllText($scholarshipRunner,'# fixture')
$utf8NoBom=[Text.UTF8Encoding]::new($false)
$lock=$null
$port=8765
try{
 $old=(Get-Date).AddMinutes(-20).ToString('yyyy-MM-dd HH:mm:ss')
 $running=@{state='running';time=$old;startedAt=$old}|ConvertTo-Json -Compress
 [IO.File]::WriteAllText($scholarshipStatusFile,$running)
 $lock=[IO.File]::Open((Join-Path $root 'scholarship-update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 Assert (Test-ScholarshipUpdateLocked) 'exclusive writer lease is detected'
 Repair-ScholarshipStatus
 Assert ((Read-ScholarshipStatusObject).state-eq'running') 'slow live writer is never marked stale'
 try{Invoke-ScholarshipExtensionUpdate '{}';throw 'Expected lease rejection'}catch{Assert ($_.Exception.Message-match'正在更新') 'new data cannot overwrite an active writer source'}
 $lock.Dispose();$lock=$null
 Repair-ScholarshipStatus
 Assert ((Read-ScholarshipStatusObject).state-eq'error') 'abandoned stale task becomes retryable'
 [IO.File]::WriteAllText($scholarshipStatusFile,(@{state='success';time='2026-11-06 15:58:24';lastSuccessMonth='2026-12-01';renewalMonth='2026-12-01'}|ConvertTo-Json -Compress))
 Write-ScholarshipStatusObject 'running' 'fixture' '筛选：2027-01-01' $old
 $saved=Read-ScholarshipStatusObject
 Assert ($saved.lastSuccessTime-eq'2026-11-06 15:58:24'-and$saved.lastSuccessMonth-eq'2026-12-01'-and$saved.renewalMonth-eq'2027-01-01') 'month switch retains the prior successful month and timestamp'
 Write-ScholarshipStatusObject 'error' 'fixture failure'
 Assert ((Read-ScholarshipStatusObject).lastSuccessTime-eq'2026-11-06 15:58:24') 'failed request retains the last verified success'
 function Start-Process {throw 'fixture process launch failed'}
 $data=@{headers=@('header');rows=@(@{value=1});renewalMonth='2026-12-01'}|ConvertTo-Json -Depth 5 -Compress
 $payload=@{data=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($data));renewalMonth='2026-12-01'}|ConvertTo-Json -Compress
 try{Invoke-ScholarshipExtensionUpdate $payload;throw 'Expected scope rejection'}catch{Assert ($_.Exception.Message-match'采集范围未确认') 'old replica or unscoped renewal input is rejected before writing'}
 Assert (-not(Test-Path (Join-Path $root 'renewal-table-source.json'))) 'unscoped input cannot replace main renewal source'
 $data=@{headers=@('header');rows=@(@{value=1});renewalMonth='2026-12-01';renewalScope=@{version=1;groupScope='all';region='深圳战区';node='首续';month='2026-12-01'}}|ConvertTo-Json -Depth 5 -Compress
 $payload=@{data=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($data));renewalMonth='2026-12-01'}|ConvertTo-Json -Compress
 try{Invoke-ScholarshipExtensionUpdate $payload;throw 'Expected launch rejection'}catch{Assert ($_.Exception.Message-match'fixture process launch failed') 'launch failures propagate immediately'}
 Assert ((Read-ScholarshipStatusObject).state-eq'error') 'launch failure never leaves a fake running status'
 $serviceStatusFile=Join-Path $root 'service-status.json';$nctStatusFile=Join-Path $root 'nct-status.json'
 foreach($kind in @('service','nct')){
  $statusPath=Join-Path $root ($kind+'-status.json')
  [IO.File]::WriteAllText($statusPath,$running)
  $otherLock=[IO.File]::Open((Join-Path $root ($kind+'-update.lock')),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  try{
   if($kind-eq'service'){Repair-ServiceStatus}else{Repair-NctStatus}
   Assert ((Get-Content $statusPath -Raw)-eq$running) "$kind active writer is not marked stale"
   $blocked=$false
   try{if($kind-eq'service'){Invoke-ServiceExtensionUpdate '{}'}else{Invoke-NctExtensionUpdate '{}'}}catch{$blocked=$true}
   Assert $blocked "$kind active writer prevents source replacement"
  }finally{$otherLock.Dispose()}
  [IO.File]::WriteAllText($statusPath,'{"state":"error"}')
  $serviceRunner=$scholarshipRunner;$nctRunner=$scholarshipRunner
  if($kind-eq'service'){
   $fixtureData=@{im=@{rows=@(1)};wecom=@{rows=@(1)}}
   $fixtureBody=@{data=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($fixtureData|ConvertTo-Json -Depth 5 -Compress)));runId='fixture'}|ConvertTo-Json -Compress
  }else{
   $filters=@{startDate='2026-11-01';endDate='2026-11-06';orderStatus='paid';productName='fixture'}
   $fixtureData=@{headers=@('header');rows=@(@{value=1});filters=$filters}
   $fixtureBody=@{data=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($fixtureData|ConvertTo-Json -Depth 5 -Compress)));filters=$filters}|ConvertTo-Json -Depth 5 -Compress
  }
  try{if($kind-eq'service'){Invoke-ServiceExtensionUpdate $fixtureBody}else{Invoke-NctExtensionUpdate $fixtureBody};throw 'Expected launch rejection'}catch{Assert ($_.Exception.Message-match'fixture process launch failed') "$kind launch failure propagates"}
  Assert ((Get-Content $statusPath -Raw -Encoding UTF8|ConvertFrom-Json).state-eq'error') "$kind launch failure leaves no fake running status"
 }
 Remove-Item Function:Start-Process
 $lock=[IO.File]::Open((Join-Path $root 'scholarship-update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 [IO.File]::WriteAllText($scholarshipStatusFile,$running)
 $previousRoot=$env:HF_DASHBOARD_ROOT
 try{
  $env:HF_DASHBOARD_ROOT=$root
  $process=Start-Process powershell.exe -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $dashboard 'run-scholarship-update.ps1')+'"'),'-InputFile',('"'+(Join-Path $root 'absent.json')+'"'))
  Assert ($process.ExitCode-ne0) 'duplicate runner exits without executing the writer'
  Assert ((Get-Content $scholarshipStatusFile -Raw)-eq$running) 'duplicate runner cannot replace the owner status'
 }finally{$env:HF_DASHBOARD_ROOT=$previousRoot}
 $lock.Dispose();$lock=$null
 foreach($kind in @('service','nct')){
  $statusPath=Join-Path $root ($kind+'-status.json')
  [IO.File]::WriteAllText($statusPath,$running)
  $otherLock=[IO.File]::Open((Join-Path $root ($kind+'-update.lock')),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  $previousRoot=$env:HF_DASHBOARD_ROOT
  try{
   $env:HF_DASHBOARD_ROOT=$root
   $runner=Join-Path $dashboard ('run-'+$kind+'-update.ps1')
   $process=Start-Process powershell.exe -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$runner+'"'),'-InputFile',('"'+(Join-Path $root 'absent.json')+'"'))
   Assert ($process.ExitCode-ne0) "$kind duplicate runner exits"
   Assert ((Get-Content $statusPath -Raw)-eq$running) "$kind duplicate runner preserves owner status"
  }finally{$otherLock.Dispose();$env:HF_DASHBOARD_ROOT=$previousRoot}
 }
}finally{
 if($null-ne$lock){$lock.Dispose()}
 if(Test-Path Function:Start-Process){Remove-Item Function:Start-Process}
 Remove-Item -LiteralPath $root -Recurse -Force
}
