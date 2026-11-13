$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
function Write-TeachingAtomicText([string]$path, [string]$text) {
    $temporary = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $text, [Text.UTF8Encoding]::new($false))
        for ($attempt = 0; $attempt -lt 6; $attempt++) {
            try {
                if ([IO.File]::Exists($path)) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
                else { [IO.File]::Move($temporary, $path) }
                return
            } catch {
                if ($attempt -eq 5) { throw }
                Start-Sleep -Milliseconds 25
            }
        }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}

function Complete-TeachingWriterFailure($runtimeRoot, $startedAt, $message, $detail) {
    # Publish failure only after the worker has exited and its lease is free.
    $lease = $null
    try {
        $lease = [IO.File]::Open((Join-Path $runtimeRoot 'update.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $statusFile = Join-Path $runtimeRoot 'status.json'
        $previous = $null
        if (Test-Path -LiteralPath $statusFile) { $previous = [IO.File]::ReadAllText($statusFile) | ConvertFrom-Json }
        if ($previous -and $startedAt -and [string]$previous.startedAt -ne $startedAt) { return }
        if ($previous -and [string]$previous.state -in @('success','error')) { return }
        $lastSuccess = if ($previous -and $previous.lastSuccessTime) { [string]$previous.lastSuccessTime } else { '' }
        $status = [ordered]@{state='error';phase='supervisor';runId=[string]$previous.runId;message=$message;detail=$detail;time=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss');startedAt=$startedAt;lastSuccessTime=$lastSuccess} | ConvertTo-Json -Compress
        Write-TeachingAtomicText $statusFile $status
    } catch {
        [Console]::Error.WriteLine('Writer final status was not replaced: ' + $_.Exception.Message)
    } finally { if ($null -ne $lease) { $lease.Dispose() } }
}

function Invoke-TeachingWriterSupervision($executable, $workerArguments, $runtimeRoot, [int]$maxSeconds = 1200) {
    $statusFile = Join-Path $runtimeRoot 'status.json'
    $startedAt = ''
    if (Test-Path -LiteralPath $statusFile) {
        try { $startedAt = [string](([IO.File]::ReadAllText($statusFile) | ConvertFrom-Json).startedAt) } catch {}
    }
    $log = Join-Path $runtimeRoot 'update.log'
    $errorLog = Join-Path $runtimeRoot ('update-worker-' + [Guid]::NewGuid().ToString('N') + '.stderr.log')
    $worker = $null
    $reservationFile = Join-Path $runtimeRoot 'teaching-launch.json'
    $launchId = ''
    if ([IO.File]::Exists($reservationFile)) {
        try { $launchId = [string](([IO.File]::ReadAllText($reservationFile) | ConvertFrom-Json).launchId) } catch {}
    }
    try {
        if ([string]::IsNullOrWhiteSpace($executable) -or -not (Test-Path -LiteralPath $executable)) { throw 'Python runtime not found.' }
        $worker = Start-Process -FilePath $executable -ArgumentList $workerArguments -WorkingDirectory $runtimeRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError $errorLog
        if (-not $worker.WaitForExit($maxSeconds * 1000)) {
            # Target only this child and descendants, never the dashboard
            # bridge or another independent update worker.
            $termination = @(& "$env:SystemRoot\System32\taskkill.exe" /PID $worker.Id /T /F 2>&1)
            if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine(($termination -join "`n")) }
            if (-not $worker.WaitForExit(15000)) { throw 'Timed-out worker could not be confirmed stopped; its status remains owned by the worker.' }
            Complete-TeachingWriterFailure $runtimeRoot $startedAt '教学数据更新超过时限，已停止本轮任务' "本轮超过 $maxSeconds 秒，已终止本轮写入进程并释放任务锁；部分子表可能已更新，请重新更新。"
            return 124
        }
        $worker.WaitForExit()
        $exitCode = $worker.ExitCode
        Complete-TeachingWriterFailure $runtimeRoot $startedAt '教学数据更新进程异常退出' "写入进程已结束（退出码 $exitCode），但未返回成功结果；请查看 update.log 后重试。"
        return $exitCode
    } catch {
        if ($null -eq $worker -or $worker.HasExited) {
            Complete-TeachingWriterFailure $runtimeRoot $startedAt '教学数据更新未能完成' $_.Exception.Message
        }
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    } finally {
        # A dead/failed wrapper must not leave a launch reservation behind.
        # Keep the marker if a timed-out child could not actually be stopped.
        if ($launchId -and ($null -eq $worker -or $worker.HasExited)) {
            try {
                $reservation = [IO.File]::ReadAllText($reservationFile) | ConvertFrom-Json
                if ([string]$reservation.launchId -eq $launchId -and [int]$reservation.processId -in @(0,$PID)) {
                    [IO.File]::Delete($reservationFile)
                }
            } catch {}
        }
        if (Test-Path -LiteralPath $errorLog) {
            try {
                $errors = [IO.File]::ReadAllText($errorLog)
                if ($errors) { [IO.File]::AppendAllText($log, $errors, [Text.UTF8Encoding]::new($false)) }
                [IO.File]::Delete($errorLog)
            } catch {}
        }
        if ($null -ne $worker) { $worker.Dispose() }
    }
}

# Load supervision in behavior tests without starting a production run.
if ($MyInvocation.InvocationName -eq '.') { return }
$root = $env:HF_DASHBOARD_ROOT
if ([string]::IsNullOrWhiteSpace($root)) { $root = $sourceRoot }
. (Join-Path $PSScriptRoot 'instance-guard.ps1')
Assert-WorkbenchPaths $sourceRoot $root $(if($env:HF_DASHBOARD_PORT){[int]$env:HF_DASHBOARD_PORT}else{8765}) 8765
$env:HF_DASHBOARD_ROOT=$root
$env:HF_DASHBOARD_PORT='8765'
$bundledPython = 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$portablePython = Join-Path $sourceRoot 'runtime\python\python.exe'
$python = if (Test-Path -LiteralPath $portablePython) { $portablePython } elseif (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
$script = Join-Path $sourceRoot 'run_dashboard_update.py'
$log = Join-Path $root 'update.log'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$exitCode = Invoke-TeachingWriterSupervision $python @('-u', ('"' + $script + '"'), '--from-raw') $root
exit $exitCode
