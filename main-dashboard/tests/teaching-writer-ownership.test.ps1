$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'bridge.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Bridge syntax invalid' }
foreach ($name in @('Test-TaskUpdateLocked','Test-TeachingUpdateActive','Repair-StaleStatus','Test-RecentUpdateRunning','Invoke-ExtensionUpdate','Set-ExtensionStatus')) {
    $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    Invoke-Expression $fn.Extent.Text
}
$root = Join-Path $PSScriptRoot ('writer-ownership-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
[void][IO.Directory]::CreateDirectory((Join-Path $root 'run-data'))
$rawFile = Join-Path $root 'run-data\group-lessons-raw.json'
[IO.File]::WriteAllText($rawFile, 'original input')
$script:writes = 0
$script:status = [pscustomobject]@{state='running';phase='local';time='2000-01-01 00:00:00';startedAt='2000-01-01 00:00:00'}
$staleStageSeconds = 360
function Read-StatusObject { return $script:status }
function Write-StatusObject { $script:writes++ }
function Test-StaleLegacyLoginWait { return $false }
function Assert($value, $message) { if (-not $value) { throw $message }; Write-Output "PASS $message" }
$lease = $null
try {
    $lease = [IO.File]::Open((Join-Path $root 'update.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    Repair-StaleStatus
    Assert ($script:writes -eq 0) 'quiet live writer is not falsely timed out'
    $script:status.state = 'error'
    Assert (Test-RecentUpdateRunning) 'live lock prevents duplicate preparation despite stale error status'
    foreach ($state in @('running','waiting','error','success')) {
        $null = Set-ExtensionStatus ('{"state":"' + $state + '","phase":"crm","message":"delayed client"}')
    }
    Assert ($script:writes -eq 0) 'delayed client progress and terminal states cannot overwrite writer status'
    $rejected = $false
    try { $null = Invoke-ExtensionUpdate 'invalid body that must not be decoded' } catch { $rejected = $_.Exception.Message.Contains('重复提交') }
    Assert $rejected 'duplicate raw upload is rejected before payload decoding or process launch'
    Assert ([IO.File]::ReadAllText($rawFile) -eq 'original input') 'duplicate upload preserves active writer input'
    $lease.Dispose(); $lease = $null
    $script:status.state = 'running'
    Repair-StaleStatus
    Assert ($script:writes -eq 1) 'orphaned stale status recovers after writer lease is released'
    $null = Set-ExtensionStatus '{"state":"running","phase":"crm","message":"new client"}'
    Assert ($script:writes -eq 2) 'new client can report progress after writer exits'
} finally {
    if ($null -ne $lease) { $lease.Dispose() }
    [IO.Directory]::Delete($root, $true)
}
