param(
    [switch]$IncludeFs1
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$launcher = Join-Path $scriptDir "launch_training.ps1"

$configs = @()
if ($IncludeFs1) {
    $configs += "configs\phase0b-nav.yaml"
}
$configs += @(
    "configs\phase0b-nav-fs3.yaml",
    "configs\phase0b-nav-fs5.yaml"
)

foreach ($configRel in $configs) {
    $configPath = Join-Path $repoRoot $configRel
    if (-not (Test-Path $configPath)) {
        throw "Config not found: $configPath"
    }
}

Write-Host "Starting phase0b frame-skip sweep..."
foreach ($configRel in $configs) {
    Write-Host ""
    Write-Host "=== Running $configRel ==="
    & $launcher -Config $configRel
    if ($LASTEXITCODE -ne 0) {
        throw "Run failed for $configRel with exit code $LASTEXITCODE"
    }
}

Write-Host ""
Write-Host "Sweep complete."
