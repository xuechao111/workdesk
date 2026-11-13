$ErrorActionPreference='Stop'
$base=Split-Path -Parent $PSScriptRoot
foreach($file in @('bridge.ps1','start-workbench.ps1')) {
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $base $file),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw "Syntax invalid: $file"}
    foreach($name in @('Write-TeachingAtomicText','Read-StatusObject','Write-StatusObject','Test-TaskUpdateLocked','Test-TeachingUpdateActive','Repair-StaleStatus','Test-RecentUpdateRunning','Set-ExtensionStatus','Invoke-ExtensionUpdate','Send-ExtensionClasses','Test-WorkbenchActualTaskActive','Test-WorkbenchStatusBlocksRestart')) {
        $fn=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
        if($fn){Invoke-Expression $fn.Extent.Text}
    }
}
$root=Join-Path $PSScriptRoot ('teaching-identity-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
$statusFile=Join-Path $root 'status.json'
$staleStageSeconds=360
$classPreparationJobs=@{}
$script:prepared=0
function Assert($value,$message){if(-not$value){throw $message};Write-Output "PASS $message"}
function Test-StaleLegacyLoginWait{return $false}
function Test-ScheduledSlotAlreadyCompleted{return $false}
function Test-ScheduledSlotCoolingDown{return ''}
function Register-ScheduledSlotAttempt{}
function Send-ClassPreparation{$script:prepared++}
function Set-Stage($phase,$minutes,$runId='current') {
    $stamp=(Get-Date).AddMinutes(-$minutes).ToString('yyyy-MM-dd HH:mm:ss')
    $value=@{state='running';phase=$phase;runId=$runId;message='stage';time=$stamp;startedAt=$stamp;lastSuccessTime='2026-11-09 21:33:10'}|ConvertTo-Json -Compress
    Write-TeachingAtomicText $statusFile $value
}
$lease=$null;$pythonWorker=$null
try {
    Set-Stage 'service' 27
    Assert (Test-WorkbenchStatusBlocksRestart 'status.json' (Read-StatusObject)) 'launcher preserves a legitimate long service collection'
    Repair-StaleStatus
    Assert ((Read-StatusObject).state-eq'running') 'legitimate 27-minute service retry is not timed out at six minutes'
    Set-Stage 'service' 33
    $lease=[IO.File]::Open((Join-Path $root 'service-update.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    Repair-StaleStatus
    Assert ((Read-StatusObject).state-eq'running') 'live service writer prevents premature main-status unlock'
    Assert (Test-WorkbenchActualTaskActive $root) 'launcher detects a real service lock even without a reliable running status'
    $lease.Dispose();$lease=$null
    Repair-StaleStatus
    Assert ((Read-StatusObject).state-eq'error'-and(Read-StatusObject).runId-eq'current') 'orphaned service stage closes after 32 minutes retaining run identity'
    Set-Stage 'crm' 7
    Assert (-not(Test-WorkbenchStatusBlocksRestart 'status.json' (Read-StatusObject))) 'orphaned stale main status does not permanently prevent launcher recovery'
    Repair-StaleStatus
    Assert ((Read-StatusObject).state-eq'error') 'CRM stage still recovers after six minutes'

    Set-Stage 'service' 1
    foreach($state in @('success','error','running','waiting')) {
        $null=Set-ExtensionStatus (@{state=$state;phase='service';runId='old';message='old task'}|ConvertTo-Json -Compress)
    }
    Assert ((Read-StatusObject).message-eq'stage'-and(Read-StatusObject).runId-eq'current') 'late service progress and terminal messages from older runs are ignored'
    $null=Set-ExtensionStatus '{"state":"success","phase":"service","runId":"current","message":"current complete"}'
    Assert ((Read-StatusObject).state-eq'success') 'matching run can publish its terminal state'
    $null=Set-ExtensionStatus '{"state":"error","phase":"crm","message":"legacy report"}'
    Assert ((Read-StatusObject).state-eq'error'-and(Read-StatusObject).runId-eq'current') 'legacy status keeps identity and remains protocol compatible'
    $rejected=$false
    try{$null=Invoke-ExtensionUpdate '{"runId":"old","data":"invalid stale payload"}'}catch{$rejected=$_.Exception.Message.Contains('所属任务')}
    Assert $rejected 'stale upload is rejected before decoding or changing raw input'
    Send-ExtensionClasses $null '{"slotKey":"manual","runId":"new-run"}'
    Assert ((Read-StatusObject).runId-eq'new-run'-and$script:prepared-eq1) 'new preparation changes identity before class loading'
    Set-Stage 'crm' 7
    Send-ExtensionClasses $null '{"slotKey":"manual"}'
    Assert ((Read-StatusObject).runId-ne'current'-and -not [string]::IsNullOrWhiteSpace((Read-StatusObject).runId)) 'legacy new preparation receives a fresh generated identity'

    $owner=[Diagnostics.Process]::GetProcessById($PID)
    $marker=@{launchId='test';processId=$PID;processStartTicks=[string]$owner.StartTime.ToUniversalTime().Ticks}|ConvertTo-Json -Compress
    $owner.Dispose()
    Write-TeachingAtomicText (Join-Path $root 'teaching-launch.json') $marker
    Assert (Test-WorkbenchActualTaskActive $root) 'launcher respects startup ownership before Python locks'
    [IO.File]::Delete((Join-Path $root 'teaching-launch.json'))

    # Use the same CRT byte lock as production rather than another .NET
    # exclusive handle. The child exits naturally; no process termination.
    $python='C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $pythonScript=Join-Path $root 'lock.py'
    $lockSource="import msvcrt,time`nfrom pathlib import Path`nf=Path('update.lock').open('a+b')`nf.write(b'0');f.flush();f.seek(0)`nmsvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)`nPath('ready').write_text('ready')`ntime.sleep(3)`nf.close()`n"
    [IO.File]::WriteAllText($pythonScript,$lockSource)
    $pythonWorker=Microsoft.PowerShell.Management\Start-Process $python -ArgumentList ('"'+$pythonScript+'"') -WorkingDirectory $root -PassThru -WindowStyle Hidden
    $deadline=[DateTime]::UtcNow.AddSeconds(8)
    while(-not[IO.File]::Exists((Join-Path $root 'ready'))-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 50}
    Assert ([IO.File]::Exists((Join-Path $root 'ready'))) 'real Python CRT byte-lock fixture started'
    Assert (Test-TaskUpdateLocked 'update.lock') 'bridge lock probe detects real Python msvcrt byte ownership'
    Assert (Test-WorkbenchActualTaskActive $root) 'launcher lock probe detects real Python byte ownership'
    Assert ($pythonWorker.WaitForExit(6000)) 'Python byte-lock fixture ends naturally'
    Assert (-not(Test-TaskUpdateLocked 'update.lock')) 'bridge recognizes released Python byte lock'
    . (Join-Path $base 'run-direct-from-extension.ps1')
    Set-Stage 'local' 1
    Write-TeachingAtomicText (Join-Path $root 'teaching-launch.json') $marker
    $exitCode=Invoke-TeachingWriterSupervision (Join-Path $root 'missing-runtime.exe') @() $root 1
    Assert ($exitCode-eq1-and -not[IO.File]::Exists((Join-Path $root 'teaching-launch.json'))) 'failed wrapper releases only its own launch reservation'
    Assert ((Read-StatusObject).runId-eq'current'-and(Read-StatusObject).state-eq'error') 'wrapper terminal error preserves run identity through atomic publication'
} finally {
    if($null-ne$lease){$lease.Dispose()}
    if($null-ne$pythonWorker){$null=$pythonWorker.WaitForExit(6000);$pythonWorker.Dispose()}
    [IO.Directory]::Delete($root,$true)
}
