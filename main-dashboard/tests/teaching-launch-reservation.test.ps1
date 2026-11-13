$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'bridge.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Bridge syntax invalid' }
foreach ($name in @('Write-TeachingAtomicText','Read-StatusObject','Write-StatusObject','Test-TaskUpdateLocked','Test-TeachingUpdateActive','Repair-StaleStatus','Test-RecentUpdateRunning','Invoke-ExtensionUpdate','Set-ExtensionStatus')) {
    $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    Invoke-Expression $fn.Extent.Text
}
$root = Join-Path $PSScriptRoot ('teaching-launch-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory((Join-Path $root 'run-data'))
$statusFile = Join-Path $root 'status.json'
$reservationFile = Join-Path $root 'teaching-launch.json'
$rawFile = Join-Path $root 'run-data\group-lessons-raw.json'
$sourceRoot = $root
$staleStageSeconds = 360
$script:starts = 0
$script:failStart = $false
function Assert($value, $message) { if (-not $value) { throw $message }; Write-Output "PASS $message" }
function Test-StaleLegacyLoginWait { return $false }
function Start-Process {
    param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru,$ErrorAction)
    $script:starts++
    if ($script:failStart) { throw 'injected process start failure' }
    Assert (Test-TeachingUpdateActive) 'reservation blocks a competing request before a process ID is returned' | Out-Host
    Assert (-not (Test-TaskUpdateLocked 'update.lock')) 'launch reservation does not hold the Python writer lock' | Out-Host
    return [Diagnostics.Process]::GetProcessById($PID)
}
function Reset-Status {
    Write-TeachingAtomicText $statusFile '{"state":"running","phase":"crm","startedAt":"2026-11-12 17:00:00","lastSuccessTime":"2026-11-09 21:33:10","time":"2000-01-01 00:00:00"}'
}
$body = @{data=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('[{"info":{"teacherName":"teacher"},"liveAttendance":{}}]'))} | ConvertTo-Json -Compress
$reader = $null
try {
    Reset-Status
    $null = Invoke-ExtensionUpdate $body
    Assert ($script:starts -eq 1 -and (Test-TeachingUpdateActive)) 'launched wrapper owns reservation before Python has locked'
    $original = [IO.File]::ReadAllText($rawFile)
    $rejected = $false
    try { $null = Invoke-ExtensionUpdate 'invalid competing upload' } catch { $rejected = $_.Exception.Message.Contains('重复提交') }
    Assert ($rejected -and $script:starts -eq 1 -and [IO.File]::ReadAllText($rawFile) -eq $original) 'duplicate launch cannot replace raw input in startup window'
    # Recreate the function from source: no in-memory launch state survives.
    $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-TeachingUpdateActive' }, $true)
    Invoke-Expression $fn.Extent.Text
    Assert (Test-TeachingUpdateActive) 'bridge restart recovers active ownership from disk'
    $null = Set-ExtensionStatus '{"state":"error","phase":"crm","message":"late failure"}'
    Assert ((Read-StatusObject).state -eq 'running') 'delayed client cannot overwrite startup status'
    $reservation = Get-Content $reservationFile -Raw | ConvertFrom-Json
    $reservation.processStartTicks = '1'
    Write-TeachingAtomicText $reservationFile ($reservation | ConvertTo-Json -Compress)
    Assert (-not (Test-TeachingUpdateActive)) 'a reused PID with a different creation time does not retain ownership'
    Write-TeachingAtomicText $reservationFile '{"launchId":"pending","processId":0,"processStartTicks":""}'
    [IO.File]::SetLastWriteTimeUtc($reservationFile, [DateTime]::UtcNow.AddSeconds(-31))
    Assert (-not (Test-TeachingUpdateActive)) 'orphaned pending startup reservation expires'
    Reset-Status
    Repair-StaleStatus
    Assert ((Read-StatusObject).state -eq 'error') 'orphaned running status is repaired after reservation expires'
    [IO.File]::Delete($reservationFile)
    Reset-Status
    $script:failStart = $true
    $failed = $false
    try { $null = Invoke-ExtensionUpdate $body } catch { $failed = $_.Exception.Message.Contains('injected process start failure') }
    Assert ($failed -and -not [IO.File]::Exists($reservationFile)) 'launch failure releases its reservation'
    Assert ((Read-StatusObject).state -eq 'error' -and (Read-StatusObject).lastSuccessTime -eq '2026-11-09 21:33:10') 'launch failure closes status and preserves last success'

    # An open reader with delete sharing must retain its complete old version
    # while a new complete JSON document becomes visible at the same path.
    Write-TeachingAtomicText $statusFile '{"state":"old"}'
    $reader = [IO.File]::Open($statusFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
    Write-TeachingAtomicText $statusFile '{"state":"new"}'
    $textReader = [IO.StreamReader]::new($reader)
    $old = $textReader.ReadToEnd()
    Assert ($old -eq '{"state":"old"}' -and [IO.File]::ReadAllText($statusFile) -eq '{"state":"new"}') 'atomic publication exposes whole old and new states to concurrent readers'
    $textReader.Dispose(); $reader = $null
    Assert (@(Get-ChildItem $root -Filter '*.tmp').Count -eq 0) 'atomic publication leaves no temporary status files'
} finally {
    if ($null -ne $reader) { $reader.Dispose() }
    [IO.Directory]::Delete($root, $true)
}
