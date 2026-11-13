$ErrorActionPreference = 'Stop'
$updater = Join-Path (Split-Path -Parent $PSScriptRoot) 'self-update.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($updater, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Updater syntax is invalid.' }
foreach ($name in @('Assert-ReleasePath','Resolve-ChildPath','Resolve-DownloadedPackageRoot')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if (-not $definition) { throw "Missing function: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('workdesk-selection-fixture-' + [Guid]::NewGuid().ToString('N'))
try {
    $repository = Join-Path $testRoot 'workdesk-main'
    $replica = Join-Path $repository 'replica-dashboard'
    $main = Join-Path $repository 'main-dashboard'
    [void][IO.Directory]::CreateDirectory($replica)
    [void][IO.Directory]::CreateDirectory($main)
    if ((Resolve-DownloadedPackageRoot $repository) -ne $replica) { throw 'Wrong package selected.' }
    foreach ($path in @('requirements.txt','.gitignore')) {
        if ((Assert-ReleasePath $path) -ne $path) { throw "Allowed metadata rejected: $path" }
    }
    foreach ($path in @('../main-dashboard/bridge.ps1','dashboard-config.json','instances/test/dashboard-config.json')) {
        $rejected = $false
        try { [void](Assert-ReleasePath $path) } catch { $rejected = $true }
        if (-not $rejected) { throw "Unsafe path accepted: $path" }
    }
    $empty = Join-Path $testRoot 'main-only'
    [void][IO.Directory]::CreateDirectory((Join-Path $empty 'main-dashboard'))
    $rejected = $false
    try { [void](Resolve-DownloadedPackageRoot $empty) } catch { $rejected = $true }
    if (-not $rejected) { throw 'Missing replica package must not fall back to main.' }
    Write-Output 'PASS replica package selection, metadata allowlist and unsafe-path rejection (7 checks)'
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $temporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($temporary, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved) -like 'workdesk-selection-fixture-*') {
        Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
    }
}
