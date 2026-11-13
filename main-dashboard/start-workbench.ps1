param([switch]$NoBrowser, [int]$Port = 8765)

function Test-WorkbenchActualTaskActive([string]$runtimeRoot) {
    foreach ($lockName in @('update.lock','service-update.lock','scholarship-update.lock','nct-update.lock','cohort-exception-update.lock')) {
        $lockFile = Join-Path $runtimeRoot $lockName
        if (-not [IO.File]::Exists($lockFile)) { continue }
        $lease = $null
        try { $lease = [IO.File]::Open($lockFile,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
        catch { return $true }
        finally { if ($null -ne $lease) { $lease.Dispose() } }
    }
    $reservationFile = Join-Path $runtimeRoot 'teaching-launch.json'
    if (-not [IO.File]::Exists($reservationFile)) { return $false }
    $owner = $null
    try {
        $reservation = [IO.File]::ReadAllText($reservationFile) | ConvertFrom-Json
        if ([int]$reservation.processId -gt 0) {
            try { $owner = [Diagnostics.Process]::GetProcessById([int]$reservation.processId) }
            catch [ArgumentException] { return $false }
            return -not $owner.HasExited -and [string]$owner.StartTime.ToUniversalTime().Ticks -eq [string]$reservation.processStartTicks
        }
        return (([DateTime]::UtcNow - [IO.File]::GetLastWriteTimeUtc($reservationFile)).TotalSeconds -lt 30)
    } catch { return (([DateTime]::UtcNow - [IO.File]::GetLastWriteTimeUtc($reservationFile)).TotalSeconds -lt 30) }
    finally { if ($null -ne $owner) { $owner.Dispose() } }
}

function Test-WorkbenchStatusBlocksRestart([string]$statusName, $task) {
    if ([string]$task.state -ne 'running') { return $false }
    if ($statusName -ne 'status.json') { return $true }
    # Actual process/lease ownership is checked first. A main-task status
    # abandoned by a crashed bridge must not block recovery indefinitely.
    try {
        $stamp = [DateTime]::ParseExact([string]$task.time,'yyyy-MM-dd HH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
        $limit = if ([string]$task.phase -eq 'service') { 32 * 60 } else { 6 * 60 }
        return ((Get-Date) - $stamp).TotalSeconds -le $limit
    } catch { return $true }
}

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$url = "http://127.0.0.1:$Port/"
. (Join-Path $PSScriptRoot 'instance-guard.ps1')
Assert-WorkbenchPaths $root $root $Port 8765
if ($Port -ne 8765) { throw '主看板启动器只允许8765端口。' }
$bridgeSource=[IO.File]::ReadAllText((Join-Path $root 'bridge.ps1'))
$versionMatch=[regex]::Match($bridgeSource,'\$workbenchApiVersion\s*=\s*''([^'']+)''')
if (-not $versionMatch.Success) { throw '无法识别主看板服务版本，已停止。' }
$expectedApiVersion=$versionMatch.Groups[1].Value
$expectedBridgeHash = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([IO.File]::ReadAllBytes((Join-Path $root 'bridge.ps1'))))).Replace('-','')
$healthy = $false
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 4
    $healthy = $response.StatusCode -eq 200 -and $response.Content -match 'id="page-home"'
    if ($healthy) {
        try {
            $capability = Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:$Port/health") -TimeoutSec 3
            $healthy = $capability.ok -eq $true -and [string]$capability.apiVersion -eq $expectedApiVersion -and [string]$capability.bridgeHash -eq $expectedBridgeHash -and [string]$capability.sourceRoot -ieq $root
        } catch { $healthy = $false }
    }
} catch {}

if (-not $healthy) {
    $listenerPattern = '^\s*TCP\s+(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]):' + $Port + '\s+.*\s+LISTENING'
    $listener = netstat.exe -ano | Select-String $listenerPattern | Select-Object -First 1
    if ($listener) {
        $parts = $listener.ToString().Trim() -split '\s+'
        $oldPid = 0
        if ([int]::TryParse($parts[-1],[ref]$oldPid) -and $oldPid -gt 0) {
            $oldHealth=$null
            try { $oldHealth=Invoke-RestMethod -Uri ($url+'health') -TimeoutSec 3 } catch {}
            if($oldHealth -and -not $oldHealth.sourceRoot -and $oldHealth.apiVersion-eq'2026-10-12-live-class-source'){
                # Legacy main bridge predates ownership fields. The exact legacy
                # API version is sufficient here because this port is reserved
                # for the main installation; never apply this rule on 8766.
                $oldHealth|Add-Member sourceRoot $root -Force
                $oldHealth|Add-Member runtimeRoot $root -Force
            }
            if (-not $oldHealth -or [string]$oldHealth.sourceRoot -ine $root) { throw '8765已被其他目录或未知服务占用，已停止；请从原主看板目录运行修复，不会终止其他服务。' }
            if (Test-WorkbenchActualTaskActive ([string]$oldHealth.runtimeRoot)) { throw '主看板有活动更新进程或启动任务，请完成后再重启。' }
            foreach ($statusName in @('status.json','service-status.json','scholarship-status.json','nct-status.json','cohort-exception-status.json')) {
                $statusFile=Join-Path ([string]$oldHealth.runtimeRoot) $statusName
                if(Test-Path -LiteralPath $statusFile){$task=Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8|ConvertFrom-Json;if(Test-WorkbenchStatusBlocksRestart $statusName $task){throw '主看板有更新任务正在运行，请完成后再重启。'}}
            }
            Stop-Process -Id $oldPid -Force -ErrorAction Stop
            Start-Sleep -Milliseconds 500
        }
    }
    $env:HF_DASHBOARD_ROOT = $root
    $env:HF_DASHBOARD_INSTANCE = ''
    $env:HF_DASHBOARD_SOURCE_ROOT = $root
    $env:HF_DASHBOARD_PORT = [string]$Port
    $env:HF_DASHBOARD_NO_OPEN = '1'
    $bridge = Join-Path $root 'bridge.ps1'
    Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $bridge + '"') -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
            if ($response.StatusCode -eq 200 -and $response.Content -match 'id="page-home"') {
                $capability=Invoke-RestMethod -Uri ($url+'health') -TimeoutSec 3
                $healthy=$capability.ok -eq $true -and [string]$capability.apiVersion -eq $expectedApiVersion -and [string]$capability.bridgeHash -eq $expectedBridgeHash -and [string]$capability.sourceRoot -ieq $root
                if($healthy){break}
            }
        } catch {}
    }
}

if (-not $NoBrowser) { Start-Process $url }
if (-not $healthy) { throw 'Workbench service did not become healthy. Check bridge-request-errors.log and setup-report.txt.' }
