$ErrorActionPreference='Stop'
$source=Join-Path (Split-Path -Parent $PSScriptRoot) 'bridge.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Bridge syntax invalid'}
foreach($name in @('Test-ScheduledSlotAlreadyCompleted','Test-StaleLegacyLoginWait','Set-ExtensionStatus')) {
 $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 Invoke-Expression $fn.Extent.Text
}
$fixture=Join-Path $PSScriptRoot ('schedule-status-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($fixture)
$serviceStatusFile=Join-Path $fixture 'service-status.json'
$script:now=[datetime]'2026-10-31 15:23:51'
function Get-Date {return $script:now}
$script:status=[pscustomobject]@{state='success';phase='service';lastSuccessTime='2026-10-31 15:22:25';startedAt='2026-10-31 15:17:59'}
function Read-StatusObject { return $script:status }
function Test-TaskUpdateLocked { return $false }
function Test-TeachingUpdateActive { return $false }
$script:writes=0
function Write-StatusObject { $script:writes++ }
function Assert($value,$message){if(-not$value){throw $message};Write-Output "PASS $message"}
try {
 foreach($key in @('codemao-update-half-hour-6-1500|2026-10-31','codemao-test-update-half-hour-6-1500|2026-10-31','codemao-update-6-1500|2026-10-31')){
  Assert (Test-ScheduledSlotAlreadyCompleted $key) "completed slot $key deduplicates"
 }
 Assert (-not(Test-ScheduledSlotAlreadyCompleted 'codemao-update-half-hour-6-1530|2026-10-31')) 'future slot must run'
 Assert (-not(Test-ScheduledSlotAlreadyCompleted 'manual')) 'manual refresh must run'
 [IO.File]::WriteAllText($serviceStatusFile,'{"state":"success","lastSuccessTime":"2026-10-31 15:22:23"}')
 $legacy=[pscustomobject]@{state='waiting';detail='请先在当前浏览器打开并登录CRM后台；控制台不会另开页面。；本时段会继续自动重试。'}
 Assert (Test-StaleLegacyLoginWait $legacy $script:status) 'obsolete tab warning cannot replace verified success'
 $null=Set-ExtensionStatus ($legacy|ConvertTo-Json -Compress)
 Assert ($script:writes-eq0) 'ignored warning does not write status'
 $auth=[pscustomobject]@{state='waiting';detail=($legacy.detail+' CRM_AUTH_REQUIRED')}
 Assert (-not(Test-StaleLegacyLoginWait $auth $script:status)) 'real authentication failure remains visible'
 $script:status.state='running'
 Assert (-not(Test-StaleLegacyLoginWait $legacy $script:status)) 'running task status is not hidden'
 $script:status.state='success';$script:now=[datetime]'2026-10-31 15:31:00'
 Assert (-not(Test-StaleLegacyLoginWait $legacy $script:status)) 'previous slot cannot suppress current login wait'
 $script:now=[datetime]'2026-10-31 15:23:51'
 [IO.File]::WriteAllText($serviceStatusFile,'{"state":"error","lastSuccessTime":"2026-10-31 15:22:23"}')
 Assert (-not(Test-StaleLegacyLoginWait $legacy $script:status)) 'failed service stage never counts as complete'
}finally{Remove-Item -LiteralPath $fixture -Recurse -Force}
