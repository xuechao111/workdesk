$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'run-direct-from-extension.ps1')
$runtime = (Get-Process -Id $PID).Path
$fixture = Join-Path $PSScriptRoot ('writer-supervision-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($fixture)
$statusFile = Join-Path $fixture 'status.json'
$scriptFile = Join-Path $fixture 'worker.ps1'
function Assert($value, $message) { if (-not $value) { throw $message }; Write-Output "PASS $message" }
function Reset-Status {
    [IO.File]::WriteAllText($statusFile, '{"state":"running","phase":"local","startedAt":"2026-11-12 15:03:20","lastSuccessTime":"2026-11-09 21:33:10"}')
}
function Run-Worker($body, $seconds = 10) {
    Reset-Status
    [IO.File]::WriteAllText($scriptFile, $body)
    return Invoke-TeachingWriterSupervision $runtime @('-NoProfile','-File',('"' + $scriptFile + '"')) $fixture $seconds
}
$sentinel = $null
$lease = $null
try {
    $success = '$s=Get-Content .\status.json -Raw|ConvertFrom-Json;$s.state="success";$s|ConvertTo-Json -Compress|Set-Content .\status.json;Write-Output "normal output";exit 0'
    $code = Run-Worker $success
    Assert ($code -eq 0) 'successful worker exit is preserved'
    Assert ((Get-Content $statusFile -Raw | ConvertFrom-Json).state -eq 'success') 'supervisor does not replace worker success'
    $code = Run-Worker '[Console]::Error.WriteLine("worker failure");exit 7'
    $status = Get-Content $statusFile -Raw | ConvertFrom-Json
    Assert ($code -eq 7 -and $status.state -eq 'error') 'abnormal worker exit closes a running status'
    Assert ($status.lastSuccessTime -eq '2026-11-09 21:33:10') 'failure preserves the last verified success'
    Assert (([IO.File]::ReadAllText((Join-Path $fixture 'update.log'))).Contains('worker failure')) 'stderr is retained in update log'

    $sentinel = Start-Process $runtime -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 90') -PassThru -WindowStyle Hidden
    $timeoutBody = '$lease=[IO.File]::Open((Join-Path $PWD "update.lock"),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);[IO.File]::WriteAllText((Join-Path $PWD "worker.pid"),[string]$PID);$child=Start-Process (Get-Process -Id $PID).Path -ArgumentList @("-NoProfile","-Command","Start-Sleep -Seconds 90") -PassThru -WindowStyle Hidden;[IO.File]::WriteAllText((Join-Path $PWD "child.pid"),[string]$child.Id);Start-Sleep -Seconds 90'
    $code = Run-Worker $timeoutBody 3
    $status = Get-Content $statusFile -Raw | ConvertFrom-Json
    Assert ($code -eq 124 -and $status.state -eq 'error' -and $status.phase -eq 'supervisor') 'hard timeout reaches a terminal failure'
    $probe = [IO.File]::Open((Join-Path $fixture 'update.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $probe.Dispose()
    Assert $true 'timed-out writer releases its real file lock before failure is published'
    foreach ($pidFile in @('worker.pid','child.pid')) {
        $ownedPid = [int][IO.File]::ReadAllText((Join-Path $fixture $pidFile))
        Assert (-not (Get-Process -Id $ownedPid -ErrorAction SilentlyContinue)) "owned process $pidFile is stopped"
    }
    $sentinel.Refresh()
    Assert (-not $sentinel.HasExited) 'unrelated task process remains running'

    Reset-Status
    $code = Invoke-TeachingWriterSupervision (Join-Path $fixture 'missing.exe') @() $fixture 1
    Assert ($code -eq 1 -and (Get-Content $statusFile -Raw | ConvertFrom-Json).state -eq 'error') 'runtime startup failure closes status immediately'
    Reset-Status
    $lease = [IO.File]::Open((Join-Path $fixture 'update.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    Complete-TeachingWriterFailure $fixture '2026-11-12 15:03:20' 'should not replace' 'another live worker'
    Assert ((Get-Content $statusFile -Raw | ConvertFrom-Json).state -eq 'running') 'failure publisher cannot overwrite a live task holding the lease'
    $lease.Dispose(); $lease = $null
    Complete-TeachingWriterFailure $fixture 'a different run' 'should not replace' 'stale supervisor'
    Assert ((Get-Content $statusFile -Raw | ConvertFrom-Json).state -eq 'running') 'stale supervisor cannot replace a newer run'
} finally {
    if ($null -ne $lease) { $lease.Dispose() }
    if ($null -ne $sentinel) { if (-not $sentinel.HasExited) { $sentinel.Kill(); $sentinel.WaitForExit() }; $sentinel.Dispose() }
    [IO.Directory]::Delete($fixture, $true)
}
