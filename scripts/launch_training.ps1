param(
    [string]$Config = "",
    [string]$Resume = "",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$pythonDir = Join-Path $repoRoot "python"

if (-not $Config) {
    $Config = Join-Path $repoRoot "configs\phase1a.yaml"
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    $pythonExe = "python"
}

$args = @("train.py", "--config", $Config)
if ($Resume) {
    $args += @("--resume", $Resume)
}
if ($ExtraArgs) {
    $args += $ExtraArgs
}

Push-Location $pythonDir
try {
    & $pythonExe @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

